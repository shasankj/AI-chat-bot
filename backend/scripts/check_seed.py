"""Step 3 check: row counts + a sample join, using the READ-ONLY role.

Run from backend/:  python -m scripts.check_seed
Passing proves two things: the data exists, AND the chatbot's read-only role can see it.
"""
from sqlalchemy import text

from app.db import read_engine

EXPECTED = {"hc_insurance_plans": 4, "hc_drugs": 13, "hc_plan_drug_coverage": 52,
            "hc_patients": 8, "hc_prescriptions": 16}

with read_engine.connect() as conn:
    for table, expected in EXPECTED.items():
        n = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()  # table names are constants above
        print(f"{'OK ' if n == expected else 'BAD'} {table:24} {n} (expected {expected})")

    print("\nMaria Alvarez's active prescriptions with her plan's copay:")
    rows = conn.execute(text("""
        SELECT d.generic_name, rx.dosage, c.tier, c.copay, p.plan_name
        FROM hc_prescriptions rx
        JOIN hc_patients pt          ON pt.patient_id = rx.patient_id
        JOIN hc_drugs d              ON d.drug_id     = rx.drug_id
        JOIN hc_plan_drug_coverage c ON c.drug_id = rx.drug_id AND c.plan_id = pt.plan_id
        JOIN hc_insurance_plans p    ON p.plan_id = pt.plan_id
        WHERE pt.member_id = :member AND rx.status = 'active'
        ORDER BY d.generic_name
    """), {"member": "EHP-100001"})   # :member is a BOUND parameter, never string-formatted
    for r in rows:
        print("  ", tuple(r))
