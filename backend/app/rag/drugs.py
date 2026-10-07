"""Find which catalog drug(s) a question is about, tolerating typos ("Linsinopril" -> lisinopril).

This is plain code on purpose. The result decides WHICH FDA label we are allowed to search, so it must be
deterministic and testable. An LLM could hallucinate a drug name; a fuzzy string match against our own
13-drug catalog cannot invent one that isn't there.
"""
import re
from dataclasses import dataclass
from difflib import get_close_matches
from functools import lru_cache

from sqlalchemy import text

from app.db import read_engine

MAX_DRUGS = 3                 # more than this in one question -> the caller refuses and asks to narrow it
FUZZY_CUTOFF = 0.82           # similarity needed to accept a misspelling (0.82 catches 1-2 wrong letters)
MIN_TOKEN_LEN = 5             # ignore short words: they produce accidental fuzzy matches
_TOKEN = re.compile(r"[A-Za-z][A-Za-z-]+")


@dataclass(frozen=True)
class Drug:
    drug_id: int
    generic: str
    brand: str | None

    @property
    def display(self) -> str:
        return f"{self.generic} ({self.brand})" if self.brand else self.generic


@lru_cache(maxsize=1)
def _catalog() -> tuple[dict[str, Drug], tuple[Drug, ...]]:
    """name (generic OR brand, lower-case) -> Drug. Loaded once; the catalog changes only via migrations."""
    with read_engine.connect() as conn:
        rows = conn.execute(text("SELECT drug_id, generic_name, brand_name FROM hc_drugs ORDER BY drug_id")).all()
    drugs = tuple(Drug(r[0], r[1], r[2]) for r in rows)
    names: dict[str, Drug] = {}
    for d in drugs:
        names[d.generic.lower()] = d
        if d.brand:
            names[d.brand.lower()] = d
    return names, drugs


def catalog_drugs() -> tuple[Drug, ...]:
    return _catalog()[1]


def resolve_drugs(*texts: str) -> list[Drug]:
    """Every distinct catalog drug mentioned in the given texts (exact name first, then fuzzy), in order."""
    names, _ = _catalog()
    found: dict[int, Drug] = {}
    for t in texts:
        for token in _TOKEN.findall(t or ""):
            word = token.lower()
            if len(word) < MIN_TOKEN_LEN:
                continue
            match = names.get(word)
            if match is None:
                close = get_close_matches(word, names.keys(), n=1, cutoff=FUZZY_CUTOFF)
                match = names[close[0]] if close else None
            if match is not None:
                found.setdefault(match.drug_id, match)
    return list(found.values())
