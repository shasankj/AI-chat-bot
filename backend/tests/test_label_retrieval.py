"""Metadata-filtered retrieval over the FDA labels (integration: needs the labels ingested).
Run:  python -m pytest -q tests/test_label_retrieval.py     (skipped automatically if labels are not ingested)
"""
import pytest
from sqlalchemy import text

from app.db import read_engine
from app.rag.drugs import resolve_drugs
from app.rag.retriever import search


def _labels_loaded() -> int:
    with read_engine.connect() as conn:
        return conn.execute(text("""SELECT count(DISTINCT s.source_id) FROM hc_policy_sources s
                                    JOIN hc_policy_chunks c USING (source_id) WHERE s.category = 'drug_label'""")).scalar()


pytestmark = pytest.mark.skipif(_labels_loaded() < 13, reason="FDA labels not (fully) ingested: python -m scripts.ingest --category drug_label")

LISINOPRIL = [resolve_drugs("lisinopril")[0].drug_id]
BOTH = [d.drug_id for d in resolve_drugs("lisinopril and metformin")]


def test_drug_filter_returns_only_that_drugs_label():
    res = search("What are the side effects?", k=5, max_distance=None, category="drug_label", drug_ids=LISINOPRIL)
    assert len(res) == 5
    assert all("lisinopril" in r.source_title.lower() for r in res)


def test_filtered_search_still_returns_k_results_for_an_unrelated_query():
    # The "filtered ANN" pitfall: without iterative scan an HNSW index finds its nearest ~40 vectors FIRST and
    # filters AFTERWARDS, so a selective filter can return far fewer than k. This must still return k.
    res = search("copay tier prior authorization deductible", k=5, max_distance=None,
                 category="drug_label", drug_ids=LISINOPRIL)
    assert len(res) == 5 and all("lisinopril" in r.source_title.lower() for r in res)


def test_multi_drug_filter_returns_passages_from_each_requested_label_only():
    res = search("warnings", k=8, max_distance=None, category="drug_label", drug_ids=BOTH)
    titles = {r.source_title.lower() for r in res}
    assert any("lisinopril" in t for t in titles) and any("metformin" in t for t in titles)
    assert all(("lisinopril" in t or "metformin" in t) for t in titles)


def test_coverage_category_never_returns_label_text():
    res = search("What is prior authorization?", k=8, max_distance=None, category="coverage_policy")
    assert res and all("FDA prescribing information" not in r.source_title for r in res)


def test_label_category_never_returns_coverage_documents():
    res = search("What is prior authorization?", k=8, max_distance=None, category="drug_label")
    assert res and all("FDA prescribing information" in r.source_title for r in res)


def test_label_chunks_carry_page_numbers_for_citations():
    res = search("angioedema", k=3, max_distance=None, category="drug_label", drug_ids=LISINOPRIL)
    assert all(r.page_number and r.source_url.startswith("https://dailymed.nlm.nih.gov/") for r in res)


def test_keyword_match_finds_exact_label_terms():
    res = search("lactic acidosis", k=3, max_distance=None, category="drug_label",
                 drug_ids=[resolve_drugs("metformin")[0].drug_id])
    assert any("lactic acidosis" in r.content.lower() for r in res)
