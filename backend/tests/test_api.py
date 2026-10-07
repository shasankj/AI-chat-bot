"""HTTP API tests (REST + SSE). Real DB + MCP server, FAKE LLM/retriever/audit sink: free and deterministic.
Run:  python -m pytest -q tests/test_api.py
"""
import json
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.audit import ListSink
from app.auth import session as session_module
from app.guardrails import messages
from app.main import MAX_CONCURRENT_CHATS, create_app
from mcp_server.server import server
from tests.test_agent import FakeLLM, FakeRetriever, gate

MARIA, JAMES = "EHP-100001", "SUM-200002"
ORIGIN = "http://localhost:5173"            # the allowed React dev origin
EVIL = "https://evil.example"


@pytest.fixture
def make_client():
    opened = []

    def make(fake=None, retriever=None):
        fake = fake or FakeLLM(gate=gate(), answer="Prior authorization means pre-approval [S1].")
        sink = ListSink()
        app = create_app(gateway_target=server, llm_factory=fake, retriever=retriever or FakeRetriever(),
                         audit_sink=sink, warm_up=False)
        client = TestClient(app, base_url="http://localhost:8000")
        client.__enter__()                     # runs the lifespan (starts the in-process MCP gateway)
        opened.append(client)
        return client, sink, fake

    yield make
    for c in opened:
        c.__exit__(None, None, None)


def login(client, persona, member_id=None):
    body = {"persona": persona, **({"member_id": member_id} if member_id else {})}
    return client.post("/auth/demo-login", json=body, headers={"Origin": ORIGIN})


def chat(client, question, conversation_id=None):
    body = {"question": question, **({"conversation_id": conversation_id} if conversation_id else {})}
    with client.stream("POST", "/chat", json=body, headers={"Origin": ORIGIN}) as r:
        if r.status_code != 200:
            r.read()
            return r.status_code, r.json(), r
        return 200, parse_sse(list(r.iter_lines())), r


def parse_sse(lines):
    events, name = [], None
    for line in lines:
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:") and name:
            events.append((name, json.loads(line[5:].strip())))
            name = None
    return events


def final_of(events):
    return next(p for n, p in events if n == "final")


# ------------------------------------------------------------------------------ public REST
def test_health_and_security_headers(make_client):
    client, _, _ = make_client()
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["mcp_tools"] == 4
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"


def test_personas_and_sources(make_client):
    client, _, _ = make_client()
    personas = client.get("/auth/personas").json()["personas"]
    assert len(personas) == 11                                          # guest + 8 patients + pharmacist + admin
    assert {p["persona"] for p in personas} == {"guest", "patient", "pharmacist", "admin"}
    srcs = client.get("/sources").json()["sources"]
    assert all(s["url"].startswith("https://") for s in srcs)
    by_cat = {c: [s for s in srcs if s["category"] == c] for c in ("coverage_policy", "drug_label")}
    assert len(by_cat["coverage_policy"]) == 4 and len(by_cat["drug_label"]) == 13


def test_unknown_route_uses_the_common_error_shape(make_client):
    client, _, _ = make_client()
    r = client.get("/nope")
    assert r.status_code == 404 and "error" in r.json()


# ------------------------------------------------------------------------------ authentication
def test_chat_requires_sign_in(make_client):
    client, _, fake = make_client()
    status, body, _ = chat(client, "hello")
    assert status == 401 and "sign in" in body["error"].lower() and fake.calls["gate"] == 0


def test_login_sets_httponly_samesite_cookie_and_me_works(make_client):
    client, sink, _ = make_client()
    r = login(client, "patient", MARIA)
    assert r.status_code == 200 and r.json()["role"] == "patient" and r.json()["subject"] == MARIA
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "hc_session=" in cookie
    me = client.get("/me").json()
    assert me["subject_label"] == "Maria Alvarez" and me["capabilities"]["can_read_records"] is True
    assert [e.event_type for e in sink.events] == ["login"]


def test_forged_tampered_and_expired_cookies_are_rejected(make_client):
    client, _, _ = make_client()
    claims = {"sid": "s", "role": "admin", "subject": None, "label": "x"}
    forged_wrong_key = jwt.encode({**claims, "exp": int(time.time()) + 3600}, "not-the-secret", algorithm="HS256")
    expired = jwt.encode({**claims, "exp": int(time.time()) - 10}, session_module._secret, algorithm="HS256")
    alg_none = jwt.encode({**claims, "exp": int(time.time()) + 3600}, key="", algorithm="none")
    bogus_role = jwt.encode({**claims, "role": "superuser", "exp": int(time.time()) + 3600},
                            session_module._secret, algorithm="HS256")
    for token in (forged_wrong_key, expired, alg_none, bogus_role, "garbage", ""):
        client.cookies.clear()
        client.cookies.set("hc_session", token)
        assert client.get("/me").status_code == 401, token[:20]


def test_editing_a_valid_cookie_breaks_the_signature(make_client):
    client, _, _ = make_client()
    login(client, "patient", MARIA)
    good = client.cookies["hc_session"]
    head, payload, sig = good.split(".")
    tampered_payload = jwt.utils.base64url_encode(json.dumps(
        {"sid": "s", "role": "admin", "subject": None, "label": "x", "exp": int(time.time()) + 3600}).encode()).decode()
    client.cookies.clear()
    client.cookies.set("hc_session", f"{head}.{tampered_payload}.{sig}")
    assert client.get("/me").status_code == 401


def test_login_validation(make_client):
    client, _, _ = make_client()
    r = login(client, "patient", "x' OR '1'='1")
    assert r.status_code == 422 and "x' OR" not in r.text                  # input is NOT echoed back
    assert login(client, "patient", "ZZZ-999999").status_code == 404       # valid format, no such patient
    assert login(client, "patient").status_code == 404                     # patient needs a member_id
    assert login(client, "pharmacist", MARIA).status_code == 422           # member_id only for patients
    assert client.post("/auth/demo-login", json={"persona": "root"}, headers={"Origin": ORIGIN}).status_code == 422


def test_logout_clears_the_session(make_client):
    client, sink, _ = make_client()
    login(client, "guest")
    assert client.post("/auth/logout", headers={"Origin": ORIGIN}).status_code == 200
    assert client.get("/me").status_code == 401
    assert [e.event_type for e in sink.events] == ["login", "logout"]


# ------------------------------------------------------------------------------ CSRF / CORS
def test_foreign_origin_is_blocked_on_post_requests(make_client):
    client, _, _ = make_client()
    r = client.post("/auth/demo-login", json={"persona": "guest"}, headers={"Origin": EVIL})
    assert r.status_code == 403 and "origin" in r.json()["error"].lower()
    login(client, "guest")
    status, body, _ = None, None, None
    r = client.post("/chat", json={"question": "hi"}, headers={"Origin": EVIL})
    assert r.status_code == 403


def test_cors_allows_our_frontend_only(make_client):
    client, _, _ = make_client()
    ok = client.options("/chat", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST",
                                          "Access-Control-Request-Headers": "content-type"})
    assert ok.headers.get("access-control-allow-origin") == ORIGIN
    assert ok.headers.get("access-control-allow-credentials") == "true"
    bad = client.options("/chat", headers={"Origin": EVIL, "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


# ------------------------------------------------------------------------------ chat over SSE
def test_chat_streams_events_and_audits_the_turn(make_client):
    client, sink, _ = make_client()
    login(client, "patient", MARIA)
    status, events, resp = chat(client, "What is prior authorization?")
    assert status == 200 and resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"].startswith("no-cache")
    names = [n for n, _ in events]
    assert names[0] == "meta" and names[-2:] == ["final", "done"]
    assert {"status", "retrieval"} <= set(names)
    f = final_of(events)
    assert f["kind"] == "answer" and f["sources"][0]["url"].startswith("https://") and f["conversation_id"]
    turn = [e for e in sink.events if e.event_type == "chat_turn"][0]
    assert turn.actor_role == "patient" and turn.subject_member_id == MARIA and turn.outcome_kind == "answer"


def test_chat_rejects_unknown_fields_so_identity_cannot_be_smuggled_in(make_client):
    client, _, fake = make_client()
    login(client, "patient", MARIA)
    r = client.post("/chat", json={"question": "my meds?", "member_id": JAMES}, headers={"Origin": ORIGIN})
    assert r.status_code == 422 and fake.calls["gate"] == 0
    assert client.post("/chat", json={"question": "x" * 2001}, headers={"Origin": ORIGIN}).status_code == 422
    assert client.post("/chat", json={"question": ""}, headers={"Origin": ORIGIN}).status_code == 422


def test_failures_inside_a_chat_turn_are_streamed_and_redacted(make_client):
    boom = RuntimeError("cannot connect to postgresql://user:SECRETPW@db.example.com/x")
    client, sink, _ = make_client(retriever=FakeRetriever(error=boom))
    login(client, "guest")
    status, events, _ = chat(client, "What is prior authorization?")
    f = final_of(events)
    assert status == 200 and f["kind"] == "error" and "SECRETPW" not in json.dumps(events)
    assert any(n == "error" for n, _ in events)
    assert [e for e in sink.events if e.event_type == "chat_turn"][0].outcome_kind == "error"


# ------------------------------------------------------------------------------ roles
def test_role_isolation_on_rest_endpoints(make_client):
    client, _, _ = make_client()
    login(client, "patient", MARIA)
    assert client.get("/patients").status_code == 403
    assert client.get("/admin/summary").status_code == 403
    assert client.post("/session/select-patient", json={"member_id": JAMES}, headers={"Origin": ORIGIN}).status_code == 403

    login(client, "pharmacist")
    assert client.get("/patients").status_code == 200 and len(client.get("/patients").json()["patients"]) == 8
    assert client.get("/admin/summary").status_code == 403

    login(client, "admin")
    assert client.get("/patients").status_code == 403
    summary = client.get("/admin/summary")
    assert summary.status_code == 200
    assert {"last_24h", "recent_audit", "policy_sources"} <= set(summary.json())
    assert len(summary.json()["policy_sources"]) == 17      # 4 coverage documents + 13 FDA labels


def test_guest_and_admin_cannot_read_patient_records_through_chat(make_client):
    fake = FakeLLM(gate=gate(patient=True, docs=False), answer="unused")
    client, _, _ = make_client(fake=fake)
    for persona, expected in (("guest", messages.SIGN_IN_FOR_RECORDS), ("admin", messages.ADMIN_NO_RECORDS)):
        login(client, persona)
        _, events, _ = chat(client, "What is my copay for Lipitor?")
        assert final_of(events)["text"] == expected
    assert fake.calls["planner"] == 0 and fake.calls["answer"] == 0


def test_pharmacist_flow_select_patient_then_read_only_that_patients_records(make_client):
    calls = [{"name": "get_patient_profile", "id": "x", "args": {"member_id": JAMES}}]    # model tries James
    fake = FakeLLM(gate=gate(patient=True, docs=False), tool_calls=calls,
                   answer="The plan is Evergreen Basic HMO [T1].")
    client, sink, _ = make_client(fake=fake)
    login(client, "pharmacist")

    _, events, _ = chat(client, "What plan are they on?")
    assert final_of(events)["text"] == messages.SELECT_PATIENT_FIRST            # nobody selected yet

    assert client.post("/session/select-patient", json={"member_id": "ZZZ-999999"},
                       headers={"Origin": ORIGIN}).status_code == 404
    sel = client.post("/session/select-patient", json={"member_id": MARIA}, headers={"Origin": ORIGIN})
    assert sel.status_code == 200 and sel.json()["subject_label"] == "Maria Alvarez"
    assert client.get("/me").json()["subject"] == MARIA                          # cookie was re-signed

    _, events, _ = chat(client, "What plan are they on?")
    assert final_of(events)["kind"] == "answer" and "Evergreen Basic HMO" in fake.answer_prompt
    assert "Summit Choice PPO" not in fake.answer_prompt                         # never James's record

    types = [e.event_type for e in sink.events]
    assert "select_patient" in types
    turn = [e for e in sink.events if e.event_type == "chat_turn"][-1]
    assert turn.subject_member_id == MARIA and turn.tools == ["get_patient_profile"]


# ------------------------------------------------------------------------------ abuse controls
def test_login_is_rate_limited(make_client):
    client, _, _ = make_client()
    codes = [login(client, "guest").status_code for _ in range(12)]
    assert codes[:10] == [200] * 10 and codes[10] == 429
    r = login(client, "guest")
    assert "retry-after" in r.headers and "Too many" in r.json()["error"]


def test_chat_is_rate_limited_per_session(make_client):
    client, _, _ = make_client()
    login(client, "guest")
    codes = [chat(client, "What is prior authorization?")[0] for _ in range(17)]
    assert codes[:15] == [200] * 15 and codes[15] == 429


def test_server_sheds_load_when_too_many_chats_are_running(make_client):
    client, _, fake = make_client()
    login(client, "guest")
    client.app.state.active_chats = MAX_CONCURRENT_CHATS
    status, body, resp = chat(client, "What is prior authorization?")
    assert status == 503 and resp.headers["retry-after"] == "5" and fake.calls["gate"] == 0
