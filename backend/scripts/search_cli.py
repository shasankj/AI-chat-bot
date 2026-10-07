"""Try the retriever by hand.  From backend/:  python -m scripts.search_cli "your question here"
Shows raw results (no distance cut-off) and marks which ones would pass MAX_DISTANCE."""
import sys

from app.rag.retriever import MAX_DISTANCE, search

question = " ".join(sys.argv[1:]) or "What is prior authorization?"
print(f"Q: {question}\n(MAX_DISTANCE = {MAX_DISTANCE})\n")
for i, r in enumerate(search(question, k=5, max_distance=None), 1):
    mark = "PASS" if r.distance <= MAX_DISTANCE else "drop"
    print(f"{i}. [{mark}] distance={r.distance:.3f}  p.{r.page_number}  {r.source_title[:55]}")
    print(f"   {r.content[:220]}…")
    print(f"   {r.source_url}\n")
