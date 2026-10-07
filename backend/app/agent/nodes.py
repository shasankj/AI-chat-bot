"""The graph's nodes. Each is a small async function: (state) -> PARTIAL state update.

Dependencies (LLM factory, MCP gateway, retriever) are injected, so tests can swap in fakes.
Progress events go out through LangGraph's stream writer; the UI shows them live.
"""
import asyncio
import json
import re
from typing import Any, Callable, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.config import get_stream_writer
from pydantic import BaseModel, Field

from app.agent.prompts import GATE_SYSTEM, PLANNER_SYSTEM
from app.auth.access import ADMIN, GUEST, Access
from app.guardrails import messages
from app.guardrails.fencing import ContextItem, build_context
from app.guardrails.input_guard import check_input
from app.guardrails.output_guard import check_output
from app.guardrails.prompts import build_drug_info_prompt, build_system_prompt
from app.mcp_client import McpGateway
from app.rag.drugs import MAX_DRUGS, resolve_drugs

TOP_K = 5
MAX_TOOL_CALLS = 3

_CITATION_RE = re.compile(r"\s*\[[ST]\d+\]")

# canned reply -> the 'kind' the UI uses to style it
_KIND_OF_CANNED = {messages.NO_INFO: "no_info", messages.NOT_A_DOCTOR: "medical_advice",
                   messages.EMERGENCY: "emergency", messages.REFUSED_REQUEST: "injection",
                   messages.UNSUPPORTED_INPUT: "invalid", messages.SIGN_IN_FOR_RECORDS: "access",
                   messages.ADMIN_NO_RECORDS: "access", messages.SELECT_PATIENT_FIRST: "access",
                   messages.NO_DRUG_LABEL: "no_info", messages.TOO_MANY_DRUGS: "invalid",
                   messages.OTHER_PERSON: "access"}


class Gate(BaseModel):
    """Structured output of the intent/routing classifier.

    ONLY `intent` is required. Models routinely omit fields they consider irrelevant (e.g. an off-topic question
    gets no `needs_policy_docs`); a strict schema turned that harmless omission into a user-facing validation
    error. Every other field has a safe default, and the routing code below copes with each default.
    """
    intent: Literal["in_scope", "drug_information", "medical_advice", "off_topic", "manipulation"]
    needs_patient_data: bool = Field(default=False, description="requires THIS patient's own records")
    needs_plan_catalog: bool = Field(default=False, description="requires plan catalog facts for a named plan")
    needs_policy_docs: bool = Field(default=False, description="requires general rules/definitions from policy documents")
    standalone_question: str = Field(default="", description="the latest message rewritten to stand on its own")
    search_queries: list[str] = Field(default_factory=list, description="1-3 focused search queries")


def emit(**event: Any) -> None:
    get_stream_writer()(event)          # delivered to whoever is iterating graph.astream(...)


def make_final(text: str, kind: str, **extra: Any) -> dict[str, Any]:
    return {"text": text, "kind": kind, "citations": [], "sources": [], **extra}


MAX_QUERIES = 3


def _screened_queries(candidates: list[str], standalone: str) -> list[str]:
    """Sub-queries are LLM output: re-screen each one (it must still pass the input guard), cap the length and
    the count, and ALWAYS keep the standalone question so a bad split can never lose the original intent."""
    out = [standalone]
    for q in candidates or []:
        q = (q or "").strip()[:200]
        if q and q.lower() != standalone.lower() and q not in out and check_input(q).allowed:
            out.append(q)
        if len(out) >= MAX_QUERIES:
            break
    return out


def _text(ai_message: Any) -> str:
    content = ai_message.content
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def _format_history(history: list[dict] | None) -> str:
    return "\n".join(f"{h['role']}: {h['content']}" for h in (history or [])) or "(none)"


def _access(config: RunnableConfig) -> Access:
    return config["configurable"]["access"]          # set by the runner from the signed session only


def _no_records_message(access: Access) -> str:
    if access.role == GUEST:
        return messages.SIGN_IN_FOR_RECORDS
    if access.role == ADMIN:
        return messages.ADMIN_NO_RECORDS
    return messages.SELECT_PATIENT_FIRST             # pharmacist with no patient selected


class AgentNodes:
    def __init__(self, gateway: McpGateway, llm_factory: Callable[[int], Any],
                 retriever: Callable[[str, int], list]):
        self.gateway = gateway
        self.llm = llm_factory
        self.retriever = retriever

    # ------------------------------------------------------------------ 1. input guard (code)
    async def input_guard(self, state: dict) -> dict:
        emit(type="status", stage="guard", message="Checking your message…")
        verdict = check_input(state["question"])
        if not verdict.allowed:
            return {"question": verdict.cleaned, "final": make_final(verdict.message, verdict.category)}
        drugs = resolve_drugs(verdict.cleaned)          # from the user's OWN words, never from model output
        return {"question": verdict.cleaned, "info_shaped": verdict.info_shaped,
                "drug_ids": [d.drug_id for d in drugs], "drug_names": [d.display for d in drugs]}

    # ------------------------------------------------------------------ 2. gate (Haiku, sees ONLY the user's words)
    async def gate(self, state: dict, config: RunnableConfig) -> dict:
        emit(type="status", stage="gate", message="Understanding your question…")
        access = _access(config)
        # The account facts come from the SIGNED SESSION (not from anything the user typed), so the classifier can
        # resolve "their prescriptions" for a pharmacist without trusting user text.
        prompt = (f'<account role="{access.role}" patient_in_scope="{str(access.subject is not None).lower()}"/>\n'
                  f"<recent_conversation>\n{_format_history(state.get('history'))}\n</recent_conversation>\n"
                  f"<user_message>\n{state['question']}\n</user_message>")
        result = await self.llm(300).with_structured_output(Gate).ainvoke(
            [SystemMessage(GATE_SYSTEM), HumanMessage(prompt)])
        if result is None:
            raise RuntimeError("The intent classifier returned no result.")

        if result.intent == "medical_advice":
            return {"intent": result.intent, "final": make_final(messages.NOT_A_DOCTOR, "medical_advice")}
        if result.intent == "manipulation":
            return {"intent": result.intent, "final": make_final(messages.REFUSED_REQUEST, "injection")}
        if result.intent == "off_topic":
            return {"intent": result.intent, "final": make_final(messages.NO_INFO, "no_info")}

        # The rewritten question is LLM output: re-screen it, and fall back to the user's own words.
        standalone = (result.standalone_question or "").strip()[:400]
        if not standalone or not check_input(standalone).allowed:
            standalone = state["question"]

        if result.intent == "drug_information":
            # DRUG-INFORMATION MODE. Allowed only if EVERYTHING agrees (the gate can only ever be stricter):
            #   layer 1 saw a general, non-personal, info-shaped question  AND  the gate agrees  AND
            #   the user named a drug from our catalog (so there is an official label to quote).
            if not state.get("info_shaped"):
                return {"intent": result.intent, "final": make_final(messages.NOT_A_DOCTOR, "medical_advice")}
            if not state.get("drug_ids"):
                return {"intent": result.intent, "final": make_final(messages.NO_DRUG_LABEL, "no_info")}
            if len(state["drug_ids"]) > MAX_DRUGS:
                return {"intent": result.intent, "final": make_final(messages.TOO_MANY_DRUGS, "invalid")}
            # No record-access check: label text is public. And NO patient data is ever mixed in.
            return {"intent": "drug_information", "mode": "drug_info", "standalone": standalone,
                    "queries": _screened_queries(result.search_queries, standalone),
                    "needs_policy_docs": True, "needs_patient_data": False, "needs_plan_catalog": False}

        # AUTHORIZATION: personal-record questions need a role that may read records AND a patient in scope.
        # Decided here in code, from the signed session, so no prompt can talk its way past it.
        if result.needs_patient_data and not access.can_read_records:
            return {"intent": "in_scope",
                    "final": make_final(_no_records_message(access), "access")}

        return {"intent": "in_scope", "standalone": standalone,
                "queries": _screened_queries(result.search_queries, standalone),
                "needs_patient_data": result.needs_patient_data,
                "needs_plan_catalog": result.needs_plan_catalog,
                "needs_policy_docs": result.needs_policy_docs
                                     or not (result.needs_patient_data or result.needs_plan_catalog)}

    # ------------------------------------------------------------------ 3a. retrieve (hybrid RAG)
    async def retrieve(self, state: dict) -> dict:
        drug_mode = state.get("mode") == "drug_info"
        emit(type="status", stage="retrieve",
             message="Searching the FDA label…" if drug_mode else "Searching policy documents…")
        # Metadata filters keep the two corpora apart: label text must never leak into coverage answers
        # (and vice versa), and a drug question may only see the label of the drug it names.
        filters = ({"category": "drug_label", "drug_ids": state["drug_ids"]} if drug_mode
                   else {"category": "coverage_policy"})
        queries = state.get("queries") or [state["standalone"]]
        runs = await asyncio.gather(*(asyncio.to_thread(lambda q=q: self.retriever(q, TOP_K, **filters))
                                      for q in queries))
        # MULTI-QUERY retrieval: a compound question ("advantages AND side effects") blurs into one embedding that
        # matches neither topic well. One search per focused sub-query, fused by Reciprocal Rank Fusion, keeps both.
        scores: dict[int, float] = {}
        by_id: dict[int, Any] = {}
        for run in runs:
            for rank, c in enumerate(run, 1):
                scores[c.chunk_id] = scores.get(c.chunk_id, 0.0) + 1.0 / (60 + rank)
                by_id.setdefault(c.chunk_id, c)
        limit = min(8, TOP_K + 2 * (len(queries) - 1))        # more topics -> room for a few more passages
        chunks = sorted(by_id.values(), key=lambda c: -scores[c.chunk_id])[:limit]
        items = [{"id": f"S{i}", "text": c.content, "title": c.source_title, "url": c.source_url,
                  "page": c.page_number, "distance": round(c.distance, 3)}
                 for i, c in enumerate(chunks, 1)]
        emit(type="retrieval", count=len(items),
             sources=[{k: d[k] for k in ("id", "title", "url", "page", "distance")} for d in items])
        return {"doc_items": items}

    # ------------------------------------------------------------------ 3b. plan + run MCP tools
    async def plan_tools(self, state: dict, config: RunnableConfig) -> dict:
        if not (state.get("needs_patient_data") or state.get("needs_plan_catalog")):
            return {}
        access = _access(config)
        member_id = access.subject                              # from the session, never from the model
        emit(type="status", stage="tools", message="Looking up records…")

        # The model is only SHOWN the tools this role may use (and the gateway re-checks on every call).
        planner = self.llm(300).bind_tools(self.gateway.llm_tools(access.tools), tool_choice="any")
        ai = await planner.ainvoke([SystemMessage(PLANNER_SYSTEM),
                                    HumanMessage(f"<question>\n{state['standalone']}\n</question>")])

        calls, seen = [], set()
        for c in ai.tool_calls:                                   # dedupe, cap
            key = (c["name"], json.dumps(c["args"], sort_keys=True))
            if key not in seen and len(calls) < MAX_TOOL_CALLS:
                seen.add(key)
                calls.append(c)
        for c in calls:
            emit(type="tool", name=c["name"], status="running")

        outcomes = await asyncio.gather(*(self.gateway.call(c["name"], c["args"], member_id, access.tools) for c in calls))
        items = []
        for i, (c, out) in enumerate(zip(calls, outcomes), 1):
            emit(type="tool", name=out.tool, status="ok" if out.ok else "error",
                 error=None if out.ok else messages.redact(out.error or ""))
            items.append({"id": f"T{i}", "tool": out.tool, "ok": out.ok, "error": out.error,
                          "text": out.to_context_item(f"T{i}").text})
        return {"tool_items": items}

    # ------------------------------------------------------------------ 4. build context (fence + screen)
    async def build_context(self, state: dict) -> dict:
        items = [ContextItem(d["id"], "document", d["text"], d["title"], d["url"], d["page"])
                 for d in state.get("doc_items", [])]
        items += [ContextItem(t["id"], "tool_result", t["text"]) for t in state.get("tool_items", [])]
        context_text, kept, dropped = build_context(items)
        if dropped:
            emit(type="status", stage="screen", message=f"Removed {len(dropped)} suspicious passage(s).")

        kept_ids = [k.id for k in kept]
        update: dict[str, Any] = {"context_text": context_text, "kept_ids": kept_ids, "dropped_ids": dropped}

        tools_by_id = {t["id"]: t for t in state.get("tool_items", [])}
        has_good_evidence = any(k.kind == "document" or tools_by_id[k.id]["ok"] for k in kept)
        if not has_good_evidence:
            errors = [t["error"] for t in tools_by_id.values() if not t["ok"] and t["id"] in kept_ids]
            if errors:   # tools failed and there is nothing else to answer from: SHOW the error
                text = "Something went wrong: " + " ".join(dict.fromkeys(messages.redact(e) for e in errors))
                update["final"] = make_final(text, "error")
            else:        # the 'I don't know' path: no evidence, so the LLM is never even called
                update["final"] = make_final(messages.NO_INFO, "no_info")
        return update

    # ------------------------------------------------------------------ 5. answer (Haiku, strict prompt)
    async def answer(self, state: dict) -> dict:
        emit(type="status", stage="compose", message="Writing the answer…")
        user = (f"{state['context_text']}\n\n"
                f"Question to answer:\n<user_question>\n{state['standalone']}\n</user_question>")
        system = (build_drug_info_prompt(state["drug_names"]) if state.get("mode") == "drug_info"
                  else build_system_prompt())
        ai = await self.llm(700).ainvoke([SystemMessage(system), HumanMessage(user)])
        return {"raw_answer": _text(ai)}

    # ------------------------------------------------------------------ 6. output guard (code)
    async def output_guard(self, state: dict) -> dict:
        emit(type="status", stage="verify", message="Verifying the answer against the sources…")
        kept = set(state["kept_ids"])
        docs = {d["id"]: d for d in state["doc_items"] if d["id"] in kept}
        tools = {t["id"]: t for t in state["tool_items"] if t["id"] in kept}
        source_text = "\n".join([d["text"] for d in docs.values()] + [t["text"] for t in tools.values()])
        drug_mode = state.get("mode") == "drug_info"
        verdict = check_output(state["raw_answer"], kept, {d["url"] for d in docs.values()}, source_text,
                               notice=messages.DRUG_INFO_NOTICE if drug_mode else None)

        debug = {"intent": state.get("intent"), "dropped": state.get("dropped_ids", []),
                 "drugs": state.get("drug_names", []) if drug_mode else []}
        if not verdict.ok:
            return {"final": make_final(verdict.text, "blocked", debug={**debug, "guard": verdict.reason})}
        if verdict.text in messages.CANNED:                       # the model itself chose a fixed reply
            return {"final": make_final(verdict.text, _KIND_OF_CANNED[verdict.text], debug=debug)}

        sources = []
        for cid in verdict.citations:
            if cid in docs:
                d = docs[cid]
                sources.append({"id": cid, "type": "document", "title": d["title"],
                                "url": d["url"], "page": d["page"]})
            else:
                sources.append({"id": cid, "type": "records", "url": None, "page": None,
                                "title": f"Patient records ({tools[cid]['tool']})"})
        return {"final": make_final(verdict.text, "answer", citations=verdict.citations, sources=sources,
                                    debug=debug, mode="drug_info" if drug_mode else "coverage")}

    # ------------------------------------------------------------------ 7. finalize
    async def finalize(self, state: dict) -> dict:
        final = state["final"]
        final.setdefault("debug", {"intent": state.get("intent"), "dropped": state.get("dropped_ids", [])})
        final["tools"] = [{"name": t["tool"], "status": "ok" if t["ok"] else "error"}
                          for t in state.get("tool_items", [])]
        emit(type="final", **final)

        update: dict[str, Any] = {"final": final}
        if final["kind"] in ("answer", "no_info"):
            # Memory stores only screened user text and VERIFIED answers (no citation ids, no footer).
            clean = _CITATION_RE.sub("", final["text"]).replace(messages.FOOTER, "").strip()
            update["history"] = [{"role": "user", "content": state["question"]},
                                 {"role": "assistant", "content": clean}]
        return update
