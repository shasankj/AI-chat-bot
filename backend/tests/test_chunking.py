"""Regression tests for the defects we found in real chunks. Run: python -m pytest -q"""
from app.rag.chunking import chunk_page, clean_text, is_mostly_non_latin, strip_page_furniture


def test_hyphenated_compounds_are_not_glued():
    assert "cost-sharing" in clean_text("the cost-\nsharing amount")
    assert "non-formulary" in clean_text("a non-\nformulary drug")


def test_broken_url_is_repaired():
    assert "Appeals-and-Grievances" in clean_text("see Appeals-and-\nGrievances/Downloads")


def test_page_number_removed_only_at_page_edges():
    page = "6 \n \nReal text starts here.\nIn 2026\n2026\nMore text.\nEnd of page text.\n \n"
    out = strip_page_furniture(page)
    assert not out.startswith("6")
    assert "\n2026\n" in out            # a number line in the MIDDLE is kept


def test_revision_stamp_removed():
    t = clean_text("30.2.7 - Review (Rev. 18, Issued: 01-15-16, Effective: 01-15-16) CMS will review.")
    assert "Rev." not in t and "CMS will review." in t


def test_non_latin_page_skipped():
    assert is_mostly_non_latin("ատրճանակ العربية ատրճանակ العربية English")
    assert chunk_page("ատրճանակ العربية " * 30) == []


def test_mixed_language_chunk_dropped():
    english = "Plans must cover a wide range of prescription drugs that people with Medicare take. " * 8
    mixed = english + "العربية ատրճանակ 中文 " * 6
    assert chunk_page(english) != []
    assert all("العربية" not in c for c in chunk_page(mixed))


def test_chunks_start_at_sentence_boundaries_and_overlap():
    sentences = [f"Sentence number {i} explains one fact about prior authorization." for i in range(60)]
    chunks = chunk_page(" ".join(sentences), size=400, overlap=150)
    assert len(chunks) > 3
    assert all(c.startswith("Sentence number") for c in chunks)      # never mid-sentence
    assert all(len(c) <= 400 for c in chunks)
    # the last sentence of chunk N is repeated at the start of chunk N+1
    last = chunks[0].split(". ")[-1].rstrip(".")
    assert last in chunks[1]
