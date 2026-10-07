"""Run one conversation turn and yield UI events. The FastAPI layer streams these as SSE.

Event types:  status | retrieval | tool | final | error
"""
import re
import uuid
from typing import Any, AsyncIterator

from app.agent.state import fresh_turn
from app.auth.access import Access
from app.guardrails.messages import error_message
from mcp_server.queries import validate_member_id

MAX_QUESTION_CHARS = 2000      # cap BEFORE any processing (the input guard enforces the real 1000 limit)
_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


async def run_agent(graph: Any, question: str, access: Access,
                    session_id: str | None = None) -> AsyncIterator[dict]:
    """`access` comes from the server-side signed session. It is the ONLY source of role and patient scope."""
    try:
        if access.subject is not None:
            validate_member_id(access.subject)
        # Memory key = role + patient + conversation id: one patient's conversation can never be loaded
        # under another patient, even if two clients pick the same conversation id.
        session = session_id if session_id and _SESSION_RE.fullmatch(session_id) else uuid.uuid4().hex
        config = {"configurable": {"thread_id": f"{access.memory_key}:{session}", "access": access}}

        async for event in graph.astream(fresh_turn((question or "")[:MAX_QUESTION_CHARS]),
                                         config, stream_mode="custom"):
            yield event
    except Exception as exc:                       # never swallow: tell the user what failed
        text = error_message(exc)
        yield {"type": "error", "message": text}
        yield {"type": "final", "text": text, "kind": "error", "citations": [], "sources": [],
               "tools": [], "debug": {}}
