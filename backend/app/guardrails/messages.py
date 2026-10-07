"""Every fixed reply the bot can give WITHOUT asking the LLM.

Keeping them as constants in code means a prompt injection can never rewrite them,
and tests can assert on them exactly.
"""
import re

NOT_A_DOCTOR = (
    "I'm an AI assistant, not a doctor or pharmacist, so I can't give medical advice, "
    "diagnoses, dosing guidance, or drug-safety information. "
    "Please consult a doctor or pharmacist."
)

EMERGENCY = (
    "This may be an emergency. I'm an AI, not a doctor, and I can't help with this. "
    "If you or someone else may be in danger or having a medical emergency, call 911 "
    "(or your local emergency number) right now. In the US you can also call or text 988 "
    "for the Suicide & Crisis Lifeline."
)

REFUSED_REQUEST = (
    "I can't help with that request. I can only answer questions about insurance coverage, "
    "prescriptions, and pharmacy policy, using approved policy documents and patient records."
)

NO_INFO = (
    "I don't know. I couldn't find that in the approved policy documents or patient "
    "records I have access to."
)

UNSUPPORTED_INPUT = (
    "Sorry, I can only read plain English text messages (up to 1,000 characters). "
    "Please rephrase your question."
)

SIGN_IN_FOR_RECORDS = (
    "I can only look up personal prescription and coverage records for a signed-in patient. "
    "Please sign in as a patient, or ask a general policy or plan question."
)

ADMIN_NO_RECORDS = (
    "Admin accounts can't view patient records through chat. Use the admin dashboard for audit and "
    "system information, or ask a general policy or plan question."
)

SELECT_PATIENT_FIRST = "Please select a patient first, then I can look up their prescriptions and coverage."

NO_DRUG_LABEL = (
    "I don't know. I only have official FDA labels for the drugs in my catalog, and I couldn't match that drug. "
    "Please ask a pharmacist or doctor."
)

OTHER_PERSON = (
    "I can only share information about the patient who is signed in or selected, not about other people. "
    "I can't look up anyone else's records."
)

TOO_MANY_DRUGS = "Please ask about one to three drugs at a time so I can quote the right labels."

# Added in code to every drug-information answer, before the standard footer.
DRUG_INFO_NOTICE = (
    "This is general information quoted from the official FDA label. It is not medical advice and does not take "
    "your own health, other medicines, or doses into account."
)

# Appended in code to every normal answer (never left to the model to remember).
FOOTER = "I'm an AI assistant, not a doctor. For medical questions, please consult a doctor or pharmacist."

# Replies that must pass through untouched (no footer, no citation requirement).
CANNED = {NOT_A_DOCTOR, EMERGENCY, REFUSED_REQUEST, NO_INFO, UNSUPPORTED_INPUT,
          SIGN_IN_FOR_RECORDS, ADMIN_NO_RECORDS, SELECT_PATIENT_FIRST, NO_DRUG_LABEL, TOO_MANY_DRUGS, OTHER_PERSON}


_SECRET_PATTERNS = [
    (re.compile(r"[a-z+]+://[^\s'\"]+"), "[redacted-url]"),                    # postgresql://user:pw@host/db
    (re.compile(r"sk-[A-Za-z0-9_\-]{8,}"), "[redacted-key]"),                   # API keys
    (re.compile(r"(?i)(password|passwd|pwd|api[_-]?key|token)\s*[=:]\s*\S+"), r"\1=[redacted]"),
]


def redact(text: str) -> str:
    """Strip secrets/URLs from any text that may be shown to a user."""
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def error_message(exc: Exception) -> str:
    """Errors are shown to the user, not hidden (your requirement). Type + first line of the message
    only, never a stack trace; secrets and URLs are redacted and the length is capped."""
    first_line = (str(exc).strip().splitlines() or [""])[0]
    return f"Something went wrong: {type(exc).__name__}: {redact(first_line)[:300]}".rstrip(": ")
