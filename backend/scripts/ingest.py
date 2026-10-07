"""Ingestion: download each registered PDF -> extract -> chunk -> embed -> store.

Run from backend/:
    python -m scripts.ingest --dry-run      # download + extract + chunk only; NO embedding, NO db writes
    python -m scripts.ingest                # full run (skips PDFs that haven't changed)
    python -m scripts.ingest --source-id 1  # just one source
    python -m scripts.ingest --force        # re-ingest even if the PDF hash is unchanged
    python -m scripts.ingest --category drug_label     # only FDA labels (or: coverage_policy)

Uses the OWNER database role (it must write). The chatbot itself never does.
"""
import argparse
import hashlib
import io
import time

import httpx
from pypdf import PdfReader
from sqlalchemy import text

from app.db import owner_engine
from app.rag.chunking import chunk_page
from app.rag.embeddings import embed_passages

MAX_PDF_BYTES = 150 * 1024 * 1024
EMBED_BATCH = 32


def download_pdf(url: str) -> bytes:
    """URLs come ONLY from our own hc_policy_sources table, never from user input."""
    with httpx.Client(follow_redirects=True, timeout=120,
                      headers={"User-Agent": "Mozilla/5.0 (healthcare-chatbot ingestion)"}) as client:
        resp = client.get(url)
        resp.raise_for_status()
    data = resp.content
    if len(data) > MAX_PDF_BYTES:
        raise ValueError(f"PDF too large: {len(data)} bytes")
    if not data.startswith(b"%PDF"):          # magic bytes: it must really be a PDF, not an HTML error page
        raise ValueError("Downloaded file is not a PDF")
    return data


def extract_chunks(pdf_bytes: bytes) -> list[tuple[int, int, str]]:
    """Return [(page_number, chunk_index, text)]; chunk_index is global per document."""
    reader = PdfReader(io.BytesIO(pdf_bytes))   # parsed in memory; nothing written to disk
    out, idx = [], 0
    for page_no, page in enumerate(reader.pages, start=1):
        try:
            page_text = page.extract_text() or ""
        except Exception as e:                  # one bad page shouldn't kill the whole document
            print(f"    ! page {page_no}: extraction failed ({e}); skipped")
            continue
        for piece in chunk_page(page_text):
            out.append((page_no, idx, piece))
            idx += 1
    return out


def to_vector_literal(vec: list[float]) -> str:
    """pgvector accepts the text form '[0.1,0.2,...]' and casts it with ::vector."""
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


def store(source_id: int, sha: str, chunks: list[tuple[int, int, str]], vectors: list[list[float]]) -> None:
    rows = [{"sid": source_id, "idx": i, "page": p, "content": c, "emb": to_vector_literal(v)}
            for (p, i, c), v in zip(chunks, vectors)]
    # ONE transaction: delete old chunks + insert new + stamp the source.
    # If anything fails, the old data stays intact (never a half-ingested document).
    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM hc_policy_chunks WHERE source_id = :sid"), {"sid": source_id})
        conn.execute(text("""
            INSERT INTO hc_policy_chunks (source_id, chunk_index, page_number, content, embedding)
            VALUES (:sid, :idx, :page, :content, CAST(:emb AS vector))
        """), rows)
        conn.execute(text("""
            UPDATE hc_policy_sources SET content_sha256 = :sha, ingested_at = now()
            WHERE source_id = :sid
        """), {"sha": sha, "sid": source_id})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--source-id", type=int)
    ap.add_argument("--category", choices=["coverage_policy", "drug_label"])
    args = ap.parse_args()

    with owner_engine.connect() as conn:
        sources = conn.execute(text("""
            SELECT s.source_id, s.title, s.url, s.content_sha256,
                   (SELECT count(*) FROM hc_policy_chunks c WHERE c.source_id = s.source_id) AS n_chunks
            FROM hc_policy_sources s
            WHERE (CAST(:sid AS int) IS NULL OR s.source_id = CAST(:sid AS int))
              AND (CAST(:cat AS text) IS NULL OR s.category = CAST(:cat AS text))
            ORDER BY s.source_id
        """), {"sid": args.source_id, "cat": args.category}).mappings().all()

    for s in sources:
        print(f"\n[{s['source_id']}] {s['title'][:70]}")
        t0 = time.time()
        try:
            pdf = download_pdf(s["url"])
            sha = hashlib.sha256(pdf).hexdigest()
            print(f"    downloaded {len(pdf)/1e6:.1f} MB, sha256={sha[:12]}…")

            if not args.force and not args.dry_run and s["content_sha256"] == sha and s["n_chunks"] > 0:
                print("    unchanged since last ingestion; skipping (use --force to redo)")
                continue

            chunks = extract_chunks(pdf)
            pages = len({p for p, _, _ in chunks})
            avg = sum(len(c) for _, _, c in chunks) // max(len(chunks), 1)
            print(f"    {len(chunks)} chunks from {pages} pages (avg {avg} chars)")
            if not chunks:
                print("    ! no extractable text (scanned PDF?). Not stored; needs OCR.")
                continue
            if args.dry_run:
                print(f"    sample: {chunks[len(chunks)//2][2][:160]}…")
                continue

            vectors: list[list[float]] = []
            for i in range(0, len(chunks), EMBED_BATCH):
                batch = [c for _, _, c in chunks[i:i + EMBED_BATCH]]
                vectors.extend(embed_passages(batch))
                print(f"    embedded {min(i + EMBED_BATCH, len(chunks))}/{len(chunks)}", end="\r")
            store(s["source_id"], sha, chunks, vectors)
            print(f"\n    stored in {time.time()-t0:.0f}s")
        except Exception as e:
            # Fail loudly per source and continue with the others; never swallow silently.
            print(f"    ERROR: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
