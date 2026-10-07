"""Measure retrieval quality for DRUG-INFORMATION questions, and prove what metadata filtering buys us.

Run from backend/:  python -m tests.eval_labels
For each question we know a phrase the correct label passage must contain. We compare three setups:
  A) unfiltered      : search ALL documents (labels + coverage rules), vector+keyword hybrid
  B) category filter : only FDA labels
  C) category + drug : only the label of the drug named in the question (what production does)
Metrics: hit@k (is a correct passage in the top k?) and drug-precision (share of the top-5 that come from the
RIGHT drug's label; unfiltered search happily returns other drugs' labels).
"""
from app.rag.drugs import resolve_drugs
from app.rag.retriever import MAX_DISTANCE, search

# (question, [any of these phrases (case-insensitive) must appear in a correct passage])
CASES = [
    ("What are the side effects of lisinopril?", ["cough", "angioedema", "hypotension", "dizziness"]),
    ("What is lisinopril used for?", ["hypertension", "heart failure"]),
    ("What are the contraindications of lisinopril?", ["angioedema", "aliskiren"]),
    ("What are the warnings for lisinopril?", ["fetal toxicity"]),
    ("What are the side effects of Lipitor?", ["myalgia", "arthralgia", "diarrhea", "nasopharyngitis"]),
    ("What is atorvastatin used for?", ["LDL-C", "cardiovascular", "hyperlipidemia"]),
    ("What is the boxed warning for metformin?", ["lactic acidosis"]),
    ("How does metformin work?", ["hepatic glucose production", "insulin sensitivity"]),
    ("What are the warnings for Eliquis?", ["premature discontinuation", "spinal/epidural", "bleeding"]),
    ("How does apixaban work?", ["factor Xa", "FXa"]),   # the label abbreviates it as FXa (first version of this needle was too literal)
    ("What is Jardiance used for?", ["type 2 diabetes", "heart failure", "chronic kidney disease"]),
    ("What are the warnings for Ozempic?", ["thyroid c-cell", "pancreatitis"]),
    ("What are the warnings for Humira?", ["serious infections", "malignancy"]),
    ("What are the warnings for Zoloft?", ["suicidal thoughts", "suicidality"]),
    ("What is the boxed warning for Synthroid?", ["obesity", "weight loss"]),
    ("What are the side effects of Norvasc?", ["edema", "dizziness", "flushing", "palpitations"]),
    ("What are the side effects of Crestor?", ["myalgia", "headache", "abdominal pain", "asthenia"]),
    ("What are the warnings for omeprazole?", ["gastric malignancy", "clostridium", "bone fracture", "hypomagnesemia"]),
    ("What are the side effects of albuterol?", ["paradoxical bronchospasm", "tachycardia", "tremor"]),
]


def rank_of(results, needles):
    return next((i for i, r in enumerate(results, 1) if any(n.lower() in r.content.lower() for n in needles)), None)


def main() -> None:
    setups = {
        "A unfiltered":      lambda q, ids: search(q, k=5, max_distance=None),
        "B category filter": lambda q, ids: search(q, k=5, max_distance=None, category="drug_label"),
        "C category + drug": lambda q, ids: search(q, k=5, max_distance=None, category="drug_label", drug_ids=ids),
    }
    stats = {name: {"ranks": [], "precision": []} for name in setups}
    print(f"{'A':>3} {'B':>3} {'C':>3}  question")
    for q, needles in CASES:
        drugs = resolve_drugs(q)
        ids = [d.drug_id for d in drugs]
        row = []
        for name, fn in setups.items():
            res = fn(q, ids)
            stats[name]["ranks"].append(rank_of(res, needles))
            right = sum(1 for r in res if any(d.generic in r.source_title.lower() or (d.brand or "~").lower() in r.source_title.lower() for d in drugs))
            stats[name]["precision"].append(right / max(len(res), 1))
            row.append(str(stats[name]["ranks"][-1] or "-"))
        print(f"{row[0]:>3} {row[1]:>3} {row[2]:>3}  {q}")

    n = len(CASES)
    print(f"\n{'setup':20} {'hit@1':>6} {'hit@3':>6} {'hit@5':>6}   drug-precision@5")
    for name, s in stats.items():
        h = lambda k: sum(1 for r in s["ranks"] if r and r <= k)
        print(f"{name:20} {h(1):>3}/{n} {h(3):>3}/{n} {h(5):>3}/{n}   {sum(s['precision'])/n:.0%}")

    # ---- what filtering REALLY buys: scenarios where the question does not carry the drug's name -----------
    print("\nSCENARIO 2: name-less queries (e.g. a rewritten follow-up like 'What are the warnings?')")
    from app.rag.drugs import resolve_drugs as rd
    generic_qs = ["What are the side effects?", "What are the warnings?", "What is it used for?", "How does it work?", "boxed warning"]
    drugs = [rd(n)[0] for n in ("lisinopril", "atorvastatin", "metformin", "apixaban", "sertraline")]

    def from_drug(res, d):
        return sum(d.generic in r.source_title.lower() or (d.brand or "~").lower() in r.source_title.lower() for r in res)

    un = fl = total = 0
    for d in drugs:
        for q in generic_qs:
            un += from_drug(search(q, k=5, max_distance=None, category="drug_label"), d)
            fl += from_drug(search(q, k=5, max_distance=None, category="drug_label", drug_ids=[d.drug_id]), d)
            total += 5
    print(f"  share of top-5 from the RIGHT drug's label:  category only {un/total:.0%}   category + drug filter {fl/total:.0%}")

    print("\nSCENARIO 3: do FDA-label passages leak into COVERAGE answers when unfiltered?")
    from tests.eval_retrieval import IN_SCOPE
    leaked = sum("FDA prescribing information" in r.source_title for q, _ in IN_SCOPE for r in search(q, k=5, max_distance=None))
    print(f"  unfiltered: {leaked}/{len(IN_SCOPE) * 5} top-5 passages are label text;  with category='coverage_policy': 0 by construction")

    # relevance gate: how far away is the best label passage, in vs. out of scope?
    inside = [search(q, k=1, max_distance=None, category="drug_label", drug_ids=[d.drug_id for d in resolve_drugs(q)])[0].distance for q, _ in CASES]
    print(f"\nnearest label passage distance for these questions: min {min(inside):.3f}  max {max(inside):.3f}   (gate MAX_DISTANCE = {MAX_DISTANCE})")


if __name__ == "__main__":
    main()
