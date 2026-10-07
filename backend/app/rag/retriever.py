"""Hybrid retrieval: vector search (meaning) + keyword search (exact terms), fused with RRF,
with optional METADATA FILTERS (category, drug) applied inside the database query.

Uses the READ-ONLY database role. Retrieval can never modify data.
"""
from dataclasses import dataclass

from sqlalchemy import text

from app.db import read_engine
from app.rag.embeddings import embed_query

# Cosine DISTANCE (pgvector's <=>) = 1 - cosine similarity.
#   0.0 = identical direction, ~0.3-0.5 = clearly related, >0.6 = probably unrelated.
# RELEVANCE GATE: chunks whose vector distance exceeds MAX_DISTANCE are dropped, even if the
# keyword search found them. Keywords can only ADD precision; they can never smuggle an
# off-topic chunk past the gate. If nothing survives, the agent must say "I don't know".
DEFAULT_TOP_K = 5
MAX_DISTANCE = 0.47   # PROVISIONAL: midpoint of the in/out-of-scope gap in tests/eval_retrieval.py
CANDIDATES = 20       # how deep each ranked list goes before fusion
RRF_K = 60            # standard RRF constant; damps the advantage of rank 1 over rank 2


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    content: str
    page_number: int | None
    distance: float          # cosine distance to the question (always computed, for the gate)
    source_title: str
    source_url: str
    score: float = 0.0       # RRF score (hybrid) - higher is better

    @property
    def similarity(self) -> float:
        return 1.0 - self.distance


# Metadata filters, shared by every query. NULL means "no filter on this field".
#   :category  -> 'coverage_policy' | 'drug_label'
#   :drug_ids  -> int[] of catalog drugs (only drug labels have a drug_id)
_FILTER = """
      (CAST(:category AS text) IS NULL OR s.category = CAST(:category AS text))
  AND (CAST(:drug_ids AS int[]) IS NULL OR s.drug_id = ANY(CAST(:drug_ids AS int[])))
"""

_VECTOR_SQL = text(f"""
    SELECT c.chunk_id, c.content, c.page_number,
           c.embedding <=> CAST(:q AS vector) AS distance,
           s.title, s.url, 0.0 AS score
    FROM hc_policy_chunks c
    JOIN hc_policy_sources s USING (source_id)
    WHERE {_FILTER}
    ORDER BY c.embedding <=> CAST(:q AS vector)
    LIMIT :k
""")

# 1. `vec`  : top CANDIDATES by cosine distance          (served by the HNSW index)
# 2. `kw`   : top CANDIDATES by keyword rank              (served by the GIN index)
#             plainto_tsquery ANDs the question's meaningful words ("hpms" & "use"): a chunk must
#             contain ALL of them. Measured (tests/eval_retrieval.py): OR-ing the words let common
#             words like "part"/"drug" flood the list and HURT ranking; AND is precise, and when
#             nothing matches the list is simply empty, so we fall back to pure vector search.
# 3. `fused`: FULL JOIN both lists; each list contributes 1/(RRF_K + rank). A chunk appearing
#             in both lists gets both contributions and floats to the top.
_HYBRID_SQL = text(f"""
    WITH q AS (
        SELECT CAST(:q AS vector) AS v,
               plainto_tsquery('english', :question) AS tsq
    ),
    vec AS (
        SELECT c.chunk_id, row_number() OVER (ORDER BY c.embedding <=> q.v) AS rnk
        FROM hc_policy_chunks c JOIN hc_policy_sources s USING (source_id), q
        WHERE {_FILTER}
        ORDER BY c.embedding <=> q.v
        LIMIT :cand
    ),
    kw AS (
        SELECT c.chunk_id, row_number() OVER (ORDER BY ts_rank_cd(c.content_tsv, q.tsq) DESC) AS rnk
        FROM hc_policy_chunks c JOIN hc_policy_sources s USING (source_id), q
        WHERE c.content_tsv @@ q.tsq AND {_FILTER}
        ORDER BY ts_rank_cd(c.content_tsv, q.tsq) DESC
        LIMIT :cand
    ),
    fused AS (
        SELECT COALESCE(vec.chunk_id, kw.chunk_id) AS chunk_id,
               COALESCE(1.0 / (:rrf + vec.rnk), 0) + COALESCE(1.0 / (:rrf + kw.rnk), 0) AS score
        FROM vec FULL OUTER JOIN kw ON vec.chunk_id = kw.chunk_id
    )
    SELECT c.chunk_id, c.content, c.page_number,
           c.embedding <=> q.v AS distance,
           s.title, s.url, f.score
    FROM fused f
    JOIN hc_policy_chunks c ON c.chunk_id = f.chunk_id
    JOIN hc_policy_sources s ON s.source_id = c.source_id
    CROSS JOIN q
    ORDER BY f.score DESC, distance
    LIMIT :k
""")


def search(question: str, k: int = DEFAULT_TOP_K, max_distance: float | None = MAX_DISTANCE,
           mode: str = "hybrid", category: str | None = None,
           drug_ids: list[int] | None = None) -> list[RetrievedChunk]:
    """Return up to k chunks, best first, dropping any beyond max_distance
    (pass max_distance=None to see raw results, e.g. when calibrating).
    mode: 'hybrid' (default) or 'vector' (kept so we can measure the difference).
    category / drug_ids: metadata filters applied INSIDE the query (see _FILTER)."""
    if mode not in ("hybrid", "vector"):
        raise ValueError(f"unknown mode: {mode}")
    qvec = "[" + ",".join(f"{x:.7f}" for x in embed_query(question)) + "]"
    filters = {"category": category, "drug_ids": list(drug_ids) if drug_ids else None}
    with read_engine.connect() as conn:
        # FILTERED ANN PITFALL: an HNSW index returns its ~40 nearest vectors FIRST and applies the WHERE
        # clause AFTERWARDS, so a selective filter (one drug = ~100 of ~4,800 chunks) can leave almost nothing.
        # pgvector >= 0.8 "iterative scan" keeps walking the graph until enough rows pass the filter.
        # SET LOCAL lasts for this transaction only (and is allowed on our read-only session).
        conn.execute(text("SET LOCAL hnsw.iterative_scan = 'relaxed_order'"))
        conn.execute(text("SET LOCAL hnsw.ef_search = 100"))
        if mode == "vector":
            rows = conn.execute(_VECTOR_SQL, {"q": qvec, "k": k, **filters}).all()
        else:
            rows = conn.execute(_HYBRID_SQL, {"q": qvec, "question": question, "k": k,
                                              "cand": CANDIDATES, "rrf": RRF_K, **filters}).all()
    results = [RetrievedChunk(r[0], r[1], r[2], float(r[3]), r[4], r[5], float(r[6])) for r in rows]
    if max_distance is not None:
        results = [r for r in results if r.distance <= max_distance]
    return results
