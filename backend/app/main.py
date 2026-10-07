"""FastAPI application: REST endpoints + one Server-Sent-Events endpoint for chat.

Run (from backend/):  uvicorn app.main:app --reload --port 8000
Docs (Swagger UI):    http://localhost:8000/docs
"""
import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, Callable, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.agent.graph import build_graph, default_retriever
from app.agent.llm import make_llm
from app.agent.runner import run_agent
from app.audit import AuditEvent, DbAuditSink
from app.auth.access import ADMIN, GUEST, PATIENT, PHARMACIST, Access
from app.auth.session import COOKIE_NAME, cookie_kwargs, issue_token, read_token
from app.config import settings
from app.db import read_engine
from app.guardrails.messages import error_message
from app.mcp_client import McpGateway
from app.rag.embeddings import embed_query
from app.ratelimit import SlidingWindowLimiter

log = logging.getLogger("api")

MEMBER_ID_PATTERN = r"^[A-Z]{3}-\d{6}$"
MAX_CONCURRENT_CHATS = 8          # hard cap on simultaneous LLM-backed turns (cost + overload protection)

PHARMACIST_LABEL, ADMIN_LABEL = "Pat Rivera (Pharmacist)", "Alex Kim (Admin)"


# =============================================================================== request models
# extra="forbid": unknown fields are rejected, so a client can't smuggle in e.g. {"member_id": "..."}.
class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    persona: Literal["guest", "patient", "pharmacist", "admin"]
    member_id: str | None = Field(default=None, pattern=MEMBER_ID_PATTERN)


class SelectPatientRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    member_id: str | None = Field(default=None, pattern=MEMBER_ID_PATTERN)   # None clears the selection


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")


# =============================================================================== small DB helpers (read-only)
def _patient_name(member_id: str) -> str | None:
    with read_engine.connect() as conn:
        row = conn.execute(text("SELECT first_name || ' ' || last_name FROM hc_patients WHERE member_id = :m"),
                           {"m": member_id}).first()
    return row[0] if row else None


def _list_patients() -> list[dict]:
    with read_engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT pt.member_id, pt.first_name, pt.last_name, p.plan_name
            FROM hc_patients pt JOIN hc_insurance_plans p USING (plan_id)
            ORDER BY pt.last_name, pt.first_name""")).all()
    return [{"member_id": r[0], "name": f"{r[1]} {r[2]}", "plan": r[3]} for r in rows]


def _sse(event: str, payload: dict) -> str:
    """One Server-Sent Event: 'event:' names it, 'data:' carries JSON, a blank line ends it."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


# =============================================================================== app factory
def create_app(*, gateway_target: Any = None, llm_factory: Callable = make_llm,
               retriever: Callable = default_retriever, audit_sink: Any = None,
               warm_up: bool = True) -> FastAPI:
    """Everything external (LLM, retriever, MCP target, audit sink) is injectable, so tests can fake them."""
    sink = audit_sink or DbAuditSink()
    limiter = SlidingWindowLimiter()
    allowed_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    background: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with McpGateway(gateway_target) as gateway:      # ONE long-lived MCP subprocess
            app.state.gateway = gateway
            app.state.graph = build_graph(gateway, llm_factory, retriever)
            app.state.active_chats = 0
            if warm_up:                                         # load the embedding model before the first user
                await asyncio.to_thread(embed_query, "warm up")
            yield

    app = FastAPI(title="Care Bot API", version="1.0.0", lifespan=lifespan)

    app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_credentials=True,
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers.setdefault("Cache-Control", "no-store")       # API responses may contain health data
        return response

    # ---- errors are shown to the user, in one consistent shape, with secrets redacted ----
    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Report WHERE and WHY only. pydantic's default response echoes the offending input back.
        problems = [f"{'.'.join(str(p) for p in e['loc'] if p != 'body')}: {e['msg']}" for e in exc.errors()[:5]]
        return JSONResponse({"error": "Invalid request.", "details": problems}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse({"error": error_message(exc)}, status_code=500)

    # =========================================================================== dependencies
    def client_ip(request: Request) -> str:
        # NOTE: behind a reverse proxy you'd read X-Forwarded-For, but ONLY from a trusted proxy.
        return request.client.host if request.client else "unknown"

    def rate_limit(key: str, limit: int, window: int = 60) -> None:
        retry = limiter.check(key, limit, window)
        if retry:
            raise HTTPException(429, f"Too many requests. Try again in {retry}s.", headers={"Retry-After": str(retry)})

    def check_origin(request: Request) -> None:
        """CSRF defense in depth (on top of SameSite=Lax): browsers always send Origin on cross-site POSTs."""
        origin = request.headers.get("origin")
        if origin and origin not in allowed_origins:
            raise HTTPException(403, "Request origin is not allowed.")

    def session(request: Request) -> tuple[Access, str]:
        parsed = read_token(request.cookies.get(COOKIE_NAME))
        if parsed is None:
            raise HTTPException(401, "Please sign in first (choose Guest if you only want general policy answers).")
        return parsed

    def require(*roles: str):
        def dep(request: Request) -> tuple[Access, str]:
            access, sid = session(request)
            if access.role not in roles:
                raise HTTPException(403, f"This action is not available to the '{access.role}' role.")
            return access, sid
        return dep

    def set_session(response: JSONResponse, access: Access, sid: str | None = None) -> None:
        response.set_cookie(value=issue_token(access, sid), **cookie_kwargs())

    async def audit(event_type: str, access: Access, **kw: Any) -> None:
        await sink.record(AuditEvent(event_type, access.role, access.label or access.role,
                                     subject_member_id=kw.pop("subject", access.subject), **kw))

    def session_info(access: Access, subject_label: str | None) -> dict:
        return {"role": access.role, "label": access.label, "subject": access.subject,
                "subject_label": subject_label,
                "capabilities": {"can_read_records": access.can_read_records, "tools": sorted(access.tools),
                                 "can_select_patient": access.role == PHARMACIST,
                                 "is_admin": access.role == ADMIN}}

    # =========================================================================== REST: public
    @app.get("/health")
    async def health():
        db_ok = True
        try:
            await asyncio.to_thread(_patient_name, "AAA-000000")      # trivial read-only query
        except Exception:
            db_ok = False
        return {"status": "ok" if db_ok else "degraded", "database": db_ok,
                "mcp_tools": len(app.state.gateway.llm_tools()), "audit_ok": sink.ok, "model": settings.llm_model}

    @app.get("/auth/personas")
    async def personas():
        """What the demo sign-in dropdown shows. SYNTHETIC people only. Real systems use SSO instead."""
        patients = await asyncio.to_thread(_list_patients)
        return {"demo_notice": "Simulated sign-in for demonstration. Not real authentication.",
                "personas": [{"persona": GUEST, "label": "Guest (no sign-in)"},
                             *({"persona": PATIENT, "label": f"Patient: {p['name']}", "member_id": p["member_id"],
                                "plan": p["plan"]} for p in patients),
                             {"persona": PHARMACIST, "label": PHARMACIST_LABEL},
                             {"persona": ADMIN, "label": ADMIN_LABEL}]}

    @app.get("/sources")
    async def sources():
        """The policy PDFs the bot may cite (also shown as references in the UI)."""
        def q():
            with read_engine.connect() as conn:
                return conn.execute(text("""SELECT title, publisher, url, doc_type, description, verified_on, category
                                            FROM hc_policy_sources ORDER BY category, source_id""")).mappings().all()
        return {"sources": [dict(r) for r in await asyncio.to_thread(q)]}

    # =========================================================================== REST: auth
    @app.post("/auth/demo-login", dependencies=[Depends(check_origin)])
    async def demo_login(body: LoginRequest, request: Request):
        rate_limit(f"login:{client_ip(request)}", limit=10)
        if body.persona == PATIENT:
            name = body.member_id and await asyncio.to_thread(_patient_name, body.member_id)
            if not name:
                raise HTTPException(404, "No such demo patient.")
            access = Access(PATIENT, body.member_id, name)
        elif body.member_id is not None:
            raise HTTPException(422, "member_id is only used with the patient persona.")
        elif body.persona == PHARMACIST:
            access = Access(PHARMACIST, None, PHARMACIST_LABEL)
        elif body.persona == ADMIN:
            access = Access(ADMIN, None, ADMIN_LABEL)
        else:
            access = Access.guest()
        response = JSONResponse(session_info(access, access.label if access.role == PATIENT else None))
        set_session(response, access)
        await audit("login", access)
        return response

    @app.post("/auth/logout", dependencies=[Depends(check_origin)])
    async def logout(request: Request):
        parsed = read_token(request.cookies.get(COOKIE_NAME))
        if parsed:
            await audit("logout", parsed[0])
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE_NAME, path="/")
        return response

    @app.get("/me")
    async def me(sess: tuple[Access, str] = Depends(session)):
        access, _ = sess
        label = await asyncio.to_thread(_patient_name, access.subject) if access.subject else None
        return session_info(access, label)

    # =========================================================================== REST: pharmacist
    @app.get("/patients")
    async def patients(sess: tuple[Access, str] = Depends(require(PHARMACIST))):
        access, _ = sess
        await audit("list_patients", access, subject=None)
        return {"patients": await asyncio.to_thread(_list_patients)}

    @app.post("/session/select-patient", dependencies=[Depends(check_origin)])
    async def select_patient(body: SelectPatientRequest, sess: tuple[Access, str] = Depends(require(PHARMACIST))):
        access, sid = sess
        name = None
        if body.member_id:
            name = await asyncio.to_thread(_patient_name, body.member_id)
            if not name:
                raise HTTPException(404, "No such patient.")
        updated = Access(PHARMACIST, body.member_id, access.label)
        response = JSONResponse(session_info(updated, name))
        set_session(response, updated, sid)               # re-sign the cookie with the new patient scope
        await audit("select_patient", updated)
        return response

    # =========================================================================== REST: admin
    @app.get("/admin/summary")
    async def admin_summary(sess: tuple[Access, str] = Depends(require(ADMIN))):
        access, _ = sess

        def q():
            with read_engine.connect() as conn:
                by_kind = conn.execute(text("""
                    SELECT coalesce(outcome_kind,'unknown') AS kind, count(*) AS n FROM hc_audit_log
                    WHERE event_type='chat_turn' AND occurred_at > now() - interval '24 hours'
                    GROUP BY 1 ORDER BY 2 DESC""")).mappings().all()
                reasons = conn.execute(text("""
                    SELECT guard_reason, count(*) AS n FROM hc_audit_log
                    WHERE guard_reason IS NOT NULL AND occurred_at > now() - interval '24 hours'
                    GROUP BY 1 ORDER BY 2 DESC LIMIT 10""")).mappings().all()
                recent = conn.execute(text("""
                    SELECT occurred_at, event_type, actor_role, actor_label, subject_member_id,
                           outcome_kind, tools FROM hc_audit_log ORDER BY audit_id DESC LIMIT 25""")).mappings().all()
                srcs = conn.execute(text("""
                    SELECT s.title, s.url, s.verified_on, s.ingested_at, s.category, count(c.chunk_id) AS chunks
                    FROM hc_policy_sources s LEFT JOIN hc_policy_chunks c USING (source_id)
                    GROUP BY s.source_id ORDER BY s.category, s.source_id""")).mappings().all()
            return by_kind, reasons, recent, srcs

        by_kind, reasons, recent, srcs = await asyncio.to_thread(q)
        await audit("admin_view", access)
        return {"last_24h": {"chat_outcomes": [dict(r) for r in by_kind],
                             "guard_block_reasons": [dict(r) for r in reasons]},
                "recent_audit": [dict(r) for r in recent],
                "policy_sources": [dict(r) for r in srcs],
                "audit_ok": sink.ok}

    # =========================================================================== SSE: chat
    @app.post("/chat", dependencies=[Depends(check_origin)])
    async def chat(body: ChatRequest, request: Request, sess: tuple[Access, str] = Depends(session)):
        access, sid = sess
        rate_limit(f"chat:{sid}", limit=15)
        rate_limit(f"chat-ip:{client_ip(request)}", limit=60)
        if app.state.active_chats >= MAX_CONCURRENT_CHATS:
            raise HTTPException(503, "The assistant is busy. Please retry in a few seconds.",
                                headers={"Retry-After": "5"})

        conversation_id = body.conversation_id or uuid.uuid4().hex

        async def stream():
            app.state.active_chats += 1
            final: dict = {}
            tools_used: list[str] = []
            try:
                yield ": connected\n\n"                                  # comment line: opens the stream at once
                yield _sse("meta", {"conversation_id": conversation_id})
                async for ev in run_agent(app.state.graph, body.question, access, conversation_id):
                    if ev["type"] == "tool" and ev.get("status") in ("ok", "error"):
                        tools_used.append(ev["name"])
                    if ev["type"] == "final":
                        final = ev
                        ev = {**ev, "conversation_id": conversation_id}
                    yield _sse(ev["type"], ev)
                yield _sse("done", {})
            finally:
                # Runs on completion, error AND client disconnect (the user closed the tab / aborted).
                app.state.active_chats -= 1
                task = asyncio.create_task(audit(
                    "chat_turn", access, outcome_kind=final.get("kind", "aborted"),
                    guard_reason=(final.get("debug") or {}).get("guard"),
                    intent=(final.get("debug") or {}).get("intent"),
                    tools=tools_used, question=body.question))
                background.add(task)                                      # hold a reference until it finishes
                task.add_done_callback(background.discard)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    return app


app = create_app()
