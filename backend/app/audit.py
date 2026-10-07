"""Append-only audit trail of who did what to whose records (table hc_audit_log, migration 006).

PRIVACY: we log the LENGTH and an 8-char hash of each question, never the question text.
FAILURE POLICY: if the audit write fails we log loudly and flag it in /health, but keep serving.
(A regulated production system would fail CLOSED for patient-data access; this is a documented demo trade-off.)
"""
import asyncio
import hashlib
import logging
from dataclasses import dataclass, field

from sqlalchemy import text

from app.db import audit_engine

log = logging.getLogger("audit")


@dataclass
class AuditEvent:
    event_type: str                      # login | logout | chat_turn | select_patient | list_patients | admin_view
    actor_role: str
    actor_label: str
    subject_member_id: str | None = None
    outcome_kind: str | None = None
    guard_reason: str | None = None
    intent: str | None = None
    tools: list[str] = field(default_factory=list)
    question: str | None = None          # hashed + measured here, NEVER stored


_INSERT = text("""
    INSERT INTO hc_audit_log (event_type, actor_role, actor_label, subject_member_id, outcome_kind,
                              guard_reason, intent, tools, question_len, question_sha8)
    VALUES (:event_type, :actor_role, :actor_label, :subject, :outcome_kind,
            :guard_reason, :intent, :tools, :qlen, :qhash)
""")


class DbAuditSink:
    def __init__(self, engine=audit_engine):
        self.engine, self.failures = engine, 0

    @property
    def ok(self) -> bool:
        return self.failures == 0

    def _write(self, ev: AuditEvent) -> None:
        q = ev.question
        with self.engine.begin() as conn:
            conn.execute(_INSERT, {
                "event_type": ev.event_type, "actor_role": ev.actor_role, "actor_label": ev.actor_label[:80],
                "subject": ev.subject_member_id, "outcome_kind": ev.outcome_kind,
                "guard_reason": (ev.guard_reason or None) and ev.guard_reason[:120],
                "intent": ev.intent, "tools": ev.tools,
                "qlen": len(q) if q is not None else None,
                "qhash": hashlib.sha256(q.encode()).hexdigest()[:8] if q else None,
            })

    async def record(self, ev: AuditEvent) -> None:
        try:
            await asyncio.to_thread(self._write, ev)
        except Exception:                                    # never let auditing crash a request
            self.failures += 1
            log.exception("audit write failed")


class ListSink:
    """In-memory sink for tests."""
    def __init__(self):
        self.events: list[AuditEvent] = []
        self.ok = True

    async def record(self, ev: AuditEvent) -> None:
        self.events.append(ev)
