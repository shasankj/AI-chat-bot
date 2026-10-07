"""Shared state that flows through the graph. Every node reads it and returns a PARTIAL update.

Everything is plain dicts/strings (no custom classes) so the checkpointer can serialize it safely.
"""
from typing import Annotated, Any, TypedDict

MAX_HISTORY = 6   # entries kept (3 user/assistant exchanges)


def append_history(old: list[dict] | None, new: list[dict] | None) -> list[dict]:
    """Reducer: when a node returns {"history": [...]}, APPEND to the old list and keep the tail,
    instead of replacing it (the default behaviour for state keys)."""
    return ((old or []) + (new or []))[-MAX_HISTORY:]


class AgentState(TypedDict, total=False):
    # ---- persists across turns of one conversation (checkpointed)
    history: Annotated[list[dict], append_history]    # [{"role": "user"|"assistant", "content": str}]

    # ---- per-turn values (the runner resets these at the start of every turn)
    question: str                  # sanitized user message
    standalone: str | None         # the question rewritten to stand alone (resolves "it", "that drug")
    queries: list[str]             # 1-3 focused search queries (a compound question is split: multi-query retrieval)
    intent: str | None             # in_scope | medical_advice | off_topic | manipulation
    needs_policy_docs: bool
    needs_patient_data: bool
    needs_plan_catalog: bool
    info_shaped: bool              # layer 1 saw a GENERAL drug-information question
    mode: str | None               # None (coverage questions) or 'drug_info' (FDA-label mode)
    drug_ids: list[int]            # catalog drugs named in the USER's own words
    drug_names: list[str]
    doc_items: list[dict]          # retrieved chunks:   {"id": "S1", "text", "title", "url", "page", "distance"}
    tool_items: list[dict]         # MCP tool results:   {"id": "T1", "tool", "ok", "text", "error"}
    context_text: str              # fenced text actually shown to the model
    kept_ids: list[str]            # ids that survived fencing (the only ones citations may use)
    dropped_ids: list[str]         # ids removed as suspected injections
    raw_answer: str | None         # the model's unverified answer
    final: dict[str, Any] | None   # the verified reply sent to the user (set exactly once)


def fresh_turn(question: str) -> dict[str, Any]:
    """Per-turn reset. Without this the checkpointer would leak last turn's `final` into this one."""
    return {"question": question, "standalone": None, "queries": [], "intent": None,
            "needs_policy_docs": False, "needs_patient_data": False, "needs_plan_catalog": False,
            "info_shaped": False, "mode": None, "drug_ids": [], "drug_names": [],
            "doc_items": [], "tool_items": [], "context_text": "", "kept_ids": [], "dropped_ids": [],
            "raw_answer": None, "final": None}
