"""Drug-name resolution (typos, brands, multiple drugs). Uses the real catalog in the database."""
import pytest

from app.rag.drugs import MAX_DRUGS, resolve_drugs


def names(text):
    return [d.generic for d in resolve_drugs(text)]


@pytest.mark.parametrize("text,expected", [
    ("What are the side effects of lisinopril?", ["lisinopril"]),
    ("what are the advantages and side effects of Linsinopril?", ["lisinopril"]),   # the user's own typo
    ("side effects of Lipitor", ["atorvastatin"]),                                  # brand name
    ("side effects of atorvastin", ["atorvastatin"]),                               # missing letter
    ("Humria warnings", ["adalimumab"]),                                            # transposed letters
    ("ozempick", ["semaglutide"]),
    ("Eliquis vs Jardiance", ["apixaban", "empagliflozin"]),                        # two drugs, in order
    ("sertralin and omeprazol", ["sertraline", "omeprazole"]),
])
def test_resolves_names_brands_and_typos(text, expected):
    assert names(text) == expected


@pytest.mark.parametrize("text", [
    "What is the capital of France?", "side effects of ibuprofen", "tell me about insulin",
    "what is prescribed for everyone", "effects of treatment", "",
])
def test_does_not_invent_a_drug_that_is_not_in_the_catalog(text):
    assert names(text) == []


def test_repeated_mentions_count_once():
    assert names("lisinopril, Zestril, and lisinopril again") == ["lisinopril"]


def test_the_cap_constant_is_sane():
    assert 1 <= MAX_DRUGS <= 5
