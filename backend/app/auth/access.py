"""Roles and what each may do. The single source of truth for authorization.

`Access` is created ONLY from the server-side signed session, never from request bodies or from
anything the LLM says. Everything downstream (gateway, graph, audit) receives it as a frozen object.
"""
from dataclasses import dataclass

GUEST, PATIENT, PHARMACIST, ADMIN = "guest", "patient", "pharmacist", "admin"
ROLES = (GUEST, PATIENT, PHARMACIST, ADMIN)

ALL_TOOLS = frozenset({"get_patient_profile", "list_prescriptions", "get_drug_coverage", "get_plan_details"})
PUBLIC_TOOLS = frozenset({"get_plan_details"})            # plan catalog: not patient-specific

# Tool allowlist per role. Enforced in code by McpGateway; the LLM only ever sees these tools.
ROLE_TOOLS: dict[str, frozenset[str]] = {
    GUEST: PUBLIC_TOOLS,
    PATIENT: ALL_TOOLS,
    PHARMACIST: ALL_TOOLS,
    ADMIN: PUBLIC_TOOLS,        # admins get a dashboard, NOT patient records through chat
}


@dataclass(frozen=True)
class Access:
    role: str
    subject: str | None = None      # member_id whose records tools may read (patient: self; pharmacist: selected)
    label: str = ""                 # display name of the demo persona

    @classmethod
    def patient(cls, member_id: str, label: str = "") -> "Access":
        return cls(PATIENT, member_id, label)

    @classmethod
    def guest(cls) -> "Access":
        return cls(GUEST, None, "Guest")

    @property
    def tools(self) -> frozenset[str]:
        return ROLE_TOOLS.get(self.role, frozenset())

    @property
    def can_read_records(self) -> bool:
        """True only if a role that may read patient records ALSO has a patient in scope."""
        return self.role in (PATIENT, PHARMACIST) and self.subject is not None

    @property
    def memory_key(self) -> str:
        """Conversation memory is scoped by role AND patient, so switching patient starts fresh."""
        return f"{self.role}:{self.subject or 'none'}"
