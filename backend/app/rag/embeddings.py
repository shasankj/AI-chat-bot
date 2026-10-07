"""Local text embeddings (no API key, no per-call cost) using fastembed + ONNX.

The SAME model must embed both the documents (ingestion) and the user's
question (retrieval); vectors from different models live in different spaces
and can't be compared. That's why this lives in one shared module.
"""
from functools import lru_cache
from pathlib import Path

from fastembed import TextEmbedding

# By default fastembed caches in the system temp dir, which the OS may purge
# (forcing a silent 200 MB re-download). Keep it inside the project; it's git-ignored.
CACHE_DIR = Path(__file__).resolve().parents[2] / ".model_cache"

MODEL_NAME = "BAAI/bge-base-en-v1.5"
EMBEDDING_DIM = 768  # must equal vector(768) in db/003_vector_schema.sql


@lru_cache(maxsize=1)
def _model() -> TextEmbedding:
    # Loaded once per process (first call downloads ~210 MB, then it's cached on disk).
    return TextEmbedding(MODEL_NAME, cache_dir=str(CACHE_DIR))


def embed_passages(texts: list[str]) -> list[list[float]]:
    """Embed document chunks. Returns one 768-float list per text."""
    return [v.tolist() for v in _model().passage_embed(texts)]


def embed_query(question: str) -> list[float]:
    """Embed a user question. BGE models are trained so that queries get a short
    instruction prefix; query_embed() adds it for us. Passages get none."""
    return next(iter(_model().query_embed(question))).tolist()
