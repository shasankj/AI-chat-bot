"""Layer 1: inspect the user's message BEFORE any LLM sees it. Pure code, deterministic.

Honest limits: pattern matching catches known and lazily-obfuscated attacks, not every
creative paraphrase. That's why layers 2-4 exist. A blocked message never reaches the model.
The order of checks matters: safety (emergency) > security (injection) > policy (medical advice).
"""
import re
import unicodedata
from dataclasses import dataclass

from app.guardrails import messages

MAX_CHARS = 1000


@dataclass(frozen=True)
class InputVerdict:
    allowed: bool
    category: str            # ok | invalid | emergency | injection | medical_advice
    message: str | None      # canned reply when blocked
    cleaned: str             # sanitized text (what the rest of the system should use)
    info_shaped: bool = False  # looks like a GENERAL drug-information question (see INFO_PATTERNS)


def sanitize(raw: str) -> str:
    """Normalize so attackers can't hide patterns behind formatting tricks."""
    text = unicodedata.normalize("NFKC", raw)       # fullwidth 'ｉｇｎｏｒｅ' -> 'ignore'
    # Drop control chars + invisible format chars (zero-width spaces, bidi overrides, soft hyphens).
    text = "".join(ch for ch in text
                   if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf", "Co", "Cs"))
    return re.sub(r"\s+", " ", text).strip()


def has_non_latin_letters(text: str) -> bool:
    """Our model/embeddings are English-only. Rejecting other scripts also blocks homoglyph
    tricks (Cyrillic 'а' that looks like Latin 'a' and slips past our regexes)."""
    return any(ch.isalpha() and ord(ch) > 0x24F for ch in text)   # above Latin Extended-B


def _rx(*patterns: str) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


# ---- patterns ---------------------------------------------------------------------------
# Emergencies: first-person / urgent phrasing, so "does my plan cover stroke medication?" passes.
EMERGENCY_PATTERNS = _rx(
    r"\b(suicid\w*|kill (myself|himself|herself)|end (my|his|her) life|want to die|self[- ]?harm)\b",
    r"\b(i am|i'm|im|i feel|i think i|someone is|he is|she is|he's|she's|my \w+ is)\b.{0,50}"
    r"\b(having a (heart attack|stroke|seizure)|overdos\w+|can'?t breathe|cannot breathe|"
    r"chest pain|bleeding (heavily|badly)|unconscious|not breathing)\b",
    r"\b(took|taken|swallowed) (too|way too) (many|much)\b",
)

INJECTION_PATTERNS = _rx(
    r"\b(ignore|disregard|forget|override|bypass|skip)\b.{0,40}\b(previous|prior|above|earlier|all|your|these|the)\b"
    r".{0,25}\b(instructions?|rules?|prompts?|guidelines?|guardrails?|restrictions?|policies|safety checks?)\b",
    r"\b(reveal|show|print|repeat|output|leak|display|tell me|give me)\b.{0,40}"
    r"\b(system|hidden|initial|developer|internal|secret)\b.{0,15}\b(prompt|instructions?|message|rules)\b",
    r"\b(what|which) (are|were) your (instructions|rules|guidelines|system prompt)\b",
    r"\byou are now\b|\bfrom now on,? you\b|\bpretend (to be|you are|you're)\b|\broleplay as\b",
    r"\bact as (if you (are|were)|an? )?(unrestricted|different|new|evil|jailbroken|unfiltered|dan)\b",
    r"\b(developer|debug|admin|god|sudo|jailbreak) mode\b|\bdo anything now\b|\bjailbreak\w*\b",
    r"\b(disable|turn off|remove|deactivate)\b.{0,25}\b(guardrails?|safety|filters?|restrictions?|safeguards?)\b",
    r"<\s*/?\s*(system|assistant|developer|untrusted_document|tool_result|account|user_message|recent_conversation)\b|<\|?(im_start|im_end)\|?>|"
    r"\[/?(inst|sys)\]|^\s*#{1,3}\s*(system|instruction)",
    # Role-play as a clinician: must be an ASSIGNMENT ("you're a physician now", "act as my pharmacist"),
    # not just 'you' near 'doctor' ("Can you tell me if my doctor accepts my plan?").
    r"\b(you are|you're|youre) (now |going to be |to be )?(a |an |my |the )?"
    r"(doctor|physician|nurse|pharmacist|medical professional)\b",
    r"\b(act|play|pretend|roleplay|role-play|behave) (as|like|to be|that you are)?\s*(a |an |my |the )?"
    r"(doctor|physician|nurse|pharmacist|medical professional)\b",
    r"\bbe my (doctor|physician|nurse|pharmacist)\b",
    r"\byou (were|are|have been) (told|instructed|programmed|configured|given)\b",
    r"\b(initial|original|first|earlier|beginning) (instructions?|prompt|message|rules)\b|"
    r"\btext (that appears )?(before|above) this\b|\bwhat text were you\b",
    r"\b(i authori[sz]e you|i'?m authori[sz]ing|i am authori[sz]ing|authori[sz]ed you to)\b",
    r"\bno (content |safety )?(rules|restrictions|filters|guardrails)\b",
    r"\bnew instructions?\s*:|\bsystem (message|prompt)\s*:",
    r"\b(drop|delete|truncate|alter)\s+table\b|\bunion\s+select\b|;\s*--|\bselect\s+\*\s+from\b",
    r"\b(i am|i'm|this is)\b.{0,20}\b(your (developer|creator|admin)|from anthropic|an? (admin|developer))\b",
)

# Medical ADVICE: clinical judgement about a person, dosing, diagnosis. ALWAYS refused ("not a doctor").
MEDICAL_PATTERNS = _rx(
    r"\b(diagnos\w+|what('?s| is) wrong with me|what (do|could|might) i have)\b",
    r"\bshould (i|we|he|she|they)\b.{0,40}\b(take|taking|stop|start|increase|decrease|skip|switch|combine|use|"
    r"double|halve|quit|continue)\b",
    r"\b(can|could|may|is it ok|is it okay|is it safe) (i|to|for me to)\b.{0,30}\b(take|taking|mix|combine)\b"
    r".{0,60}\b(with|alongside|together|while)\b",
    r"\b(is it|are they|is this) (safe|dangerous|harmful|okay|ok) (to|for|with|if)\b",
    # dosing is never answered, not even from the label: it is the most dangerous kind of "advice"
    r"\b(what|how much|how many)\b.{0,30}\b(dose|dosage|mg|pills?|tablets?)\b.{0,25}\b(should|do i need|to take|can i)\b",
    r"\b(dose|dosage|dosing)\b.{0,30}\b(safe|recommended|normal|typical|maximum|max)\b",
    r"\b(usual|typical|normal|standard|recommended|starting|maximum|max|safe|right|correct|proper|appropriate|average)"
    r"\s+(daily\s+)?(dose|dosage|dosing)\b",
    r"\bhow (much|many)\b.{0,40}\b(should|can|could|do i|to) (i |you |one |a person )?(take|use|give)\b",
    r"\boverdos\w+",
    r"\bprescribe me\b|\brecommend (me )?(a|an|some) (drug|medication|medicine|tablet|pill)s?\b",
    r"\b(combine|mix)\b.{0,30}\b(drugs?|medications?|medicines?|tablets|pills)\b|\b(safest|safe)\b.{0,30}\b(combine|mix|together)\b",
    r"\b(symptoms?|treat(ment)? (for|of)|cure for|home remed\w+|medication for (my|a)|best (drug|medication|medicine) for)\b",
    r"\b(which|what) (drug|medication|medicine|pill)s? (is|are|works?) (best|better|safest|right for me)\b",
    r"\b(pregnan\w+|breastfeeding|nursing) .{0,30}\b(take|safe|medication|drug)\b",
    r"\bdo i (have|need) (a|an)\b.{0,20}\b(infection|disease|condition|disorder|cancer|diabetes)\b",
    r"\b(my|i have|i'?ve got|i am (feeling|experiencing)|i feel|experiencing)\b.{0,40}"
    r"\b(pain|ache|fever|rash|dizz\w+|nausea|vomiting|headache|swelling|bleeding)\b",
)

# Drug INFORMATION: general, factual questions answerable by quoting the official FDA label.
# A match only marks the question "info-shaped". It is NOT permission by itself: the graph also requires
# a real catalog drug, no personal wording (below), AND the LLM gate to agree (the gate can only be stricter).
INFO_PATTERNS = _rx(
    r"\b(side[- ]effects?|adverse (effects?|reactions?|events?))\b",
    r"\b(contraindications?|contraindicated|boxed warning|black box warning|warnings?|precautions?)\b",
    r"\b(drug[- ])?interactions?\b|\binteracts? with\b",
    r"\bwhat (is|are) \w+( \w+)? (used|prescribed|indicated) (for|to)\b|\b(used|indicated) (for|to treat)\b",
    r"\b(indications?|uses?)\b (of|for)\b|\bwhat does \w+ (do|treat)\b",
    r"\bhow (does|do) .{1,40} work\b|\bmechanism of action\b",
    r"\b(benefits?|advantages?)\b",
    r"\b(does|do|can|could|may|will)\b.{1,40}\b(cause|causes|lead to|result in|trigger)\b",
)

# Personal wording turns a general question into a personal one ("what side effects will I get?").
# "tell me / show me / give me ..." is just politeness, so it is removed before checking.
_POLITE_ME = re.compile(r"\b(tell|show|give|teach|help|let|remind|explain to) me\b", re.IGNORECASE)
_PERSONAL = re.compile(r"\b(i|i'm|im|i've|ive|i'll|my|me|mine|myself|we|our|ours)\b", re.IGNORECASE)


def has_personal_wording(folded: str) -> bool:
    return bool(_PERSONAL.search(_POLITE_ME.sub(" ", folded)))


def looks_like_injection(text: str) -> bool:
    """Shared with layer 2: also used to screen retrieved documents (indirect injection)."""
    folded = sanitize(text).casefold()
    return any(p.search(folded) for p in INJECTION_PATTERNS)


def check_input(raw: str) -> InputVerdict:
    cleaned = sanitize(raw or "")
    if not cleaned or len(cleaned) > MAX_CHARS or has_non_latin_letters(cleaned):
        return InputVerdict(False, "invalid", messages.UNSUPPORTED_INPUT, cleaned[:MAX_CHARS])

    folded = cleaned.casefold()
    if any(p.search(folded) for p in EMERGENCY_PATTERNS):
        return InputVerdict(False, "emergency", messages.EMERGENCY, cleaned)
    if any(p.search(folded) for p in INJECTION_PATTERNS):
        return InputVerdict(False, "injection", messages.REFUSED_REQUEST, cleaned)
    if any(p.search(folded) for p in MEDICAL_PATTERNS):
        return InputVerdict(False, "medical_advice", messages.NOT_A_DOCTOR, cleaned)

    info_shaped = any(p.search(folded) for p in INFO_PATTERNS)
    if info_shaped and has_personal_wording(folded):
        # "What side effects will I get?" is about THIS person: that is advice territory, never label quoting.
        return InputVerdict(False, "medical_advice", messages.NOT_A_DOCTOR, cleaned)
    return InputVerdict(True, "ok", None, cleaned, info_shaped=info_shaped)
