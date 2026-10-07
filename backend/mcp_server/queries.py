"""The ONLY SQL the chatbot can ever run against patient data: four fixed, parameterized queries.

Rules every function here follows:
  * inputs are validated against strict formats BEFORE touching the database
  * SQL text is constant; user-influenced values travel only as bound parameters (:name)
  * connection is the read-only engine (role = SELECT only, session read-only, 10s timeout)
  * money is returned as "$5.00" strings (human-readable AND checkable by the output guard)
  * results are capped, and expose the minimum needed (no phone numbers, no member ids)
"""
import re
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.db import read_engine

MEMBER_ID_RE = re.compile(r"^[A-Z]{3}-\d{6}$")
DRUG_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 \-]{1,59}$")
PLAN_NAME_RE = DRUG_NAME_RE
MAX_ROWS = 50


class ToolInputError(ValueError):
    """Bad input from the caller. The message is safe to show to the user."""


def _money(v: Decimal | None) -> str | None:
    return None if v is None else f"${v:,.2f}"


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def validate_member_id(member_id: str) -> str:
    if not isinstance(member_id, str) or not MEMBER_ID_RE.fullmatch(member_id):
        raise ToolInputError("member_id must look like ABC-123456.")
    return member_id


def validate_name(value: str, label: str) -> str:
    if not isinstance(value, str) or not DRUG_NAME_RE.fullmatch(value.strip()):
        raise ToolInputError(f"{label} may contain only letters, digits, spaces and hyphens (2-60 characters).")
    return value.strip()


def _patient_exists(conn, member_id: str) -> None:
    found = conn.execute(text("SELECT 1 FROM hc_patients WHERE member_id = :m"), {"m": member_id}).first()
    if not found:
        raise ToolInputError("No patient was found for the current session.")


# --------------------------------------------------------------------------- tool 1
def patient_profile(member_id: str) -> dict[str, Any]:
    validate_member_id(member_id)
    with read_engine.connect() as conn:
        row = conn.execute(text("""
            SELECT pt.first_name, pt.last_name,
                   CAST(date_part('year', age(pt.date_of_birth)) AS int) AS age,
                   pt.sex, pt.allergies,
                   p.plan_name, p.carrier, p.plan_type,
                   p.monthly_premium, p.annual_deductible, p.out_of_pocket_max
            FROM hc_patients pt
            JOIN hc_insurance_plans p ON p.plan_id = pt.plan_id
            WHERE pt.member_id = :m
        """), {"m": member_id}).mappings().first()
    if not row:
        raise ToolInputError("No patient was found for the current session.")
    return {
        "name": f"{row['first_name']} {row['last_name']}",
        "age": row["age"],
        "sex": row["sex"],
        "allergies_on_file": list(row["allergies"]),
        "plan": {
            "plan_name": row["plan_name"], "carrier": row["carrier"], "plan_type": row["plan_type"],
            "monthly_premium": _money(row["monthly_premium"]),
            "annual_deductible": _money(row["annual_deductible"]),
            "out_of_pocket_max": _money(row["out_of_pocket_max"]),
        },
    }


# --------------------------------------------------------------------------- tool 2
def prescriptions(member_id: str, include_inactive: bool = False) -> dict[str, Any]:
    validate_member_id(member_id)
    with read_engine.connect() as conn:
        _patient_exists(conn, member_id)
        rows = conn.execute(text("""
            SELECT d.generic_name, d.brand_name, rx.dosage, rx.frequency, rx.quantity,
                   rx.refills_remaining, rx.prescriber_name, rx.status, rx.start_date, rx.end_date,
                   c.tier, c.copay, c.requires_prior_auth, c.quantity_limit
            FROM hc_prescriptions rx
            JOIN hc_patients pt ON pt.patient_id = rx.patient_id
            JOIN hc_drugs d     ON d.drug_id = rx.drug_id
            LEFT JOIN hc_plan_drug_coverage c ON c.drug_id = rx.drug_id AND c.plan_id = pt.plan_id
            WHERE pt.member_id = :m AND (CAST(:all AS boolean) OR rx.status = 'active')
            ORDER BY rx.status, d.generic_name
            LIMIT :lim
        """), {"m": member_id, "all": include_inactive, "lim": MAX_ROWS}).mappings().all()
    return {
        "count": len(rows),
        "prescriptions": [{
            "drug": r["generic_name"], "brand": r["brand_name"], "dosage": r["dosage"],
            "frequency": r["frequency"], "quantity": r["quantity"],
            "refills_remaining": r["refills_remaining"], "prescriber": r["prescriber_name"],
            "status": r["status"], "start_date": _iso(r["start_date"]), "end_date": _iso(r["end_date"]),
            "plan_tier": r["tier"], "plan_copay": _money(r["copay"]),
            "requires_prior_authorization": r["requires_prior_auth"],
            "quantity_limit": r["quantity_limit"],
        } for r in rows],
    }


# --------------------------------------------------------------------------- tool 3
def drug_coverage(member_id: str, drug_name: str) -> dict[str, Any]:
    validate_member_id(member_id)
    name = validate_name(drug_name, "drug_name")
    with read_engine.connect() as conn:
        _patient_exists(conn, member_id)
        rows = conn.execute(text("""
            SELECT d.generic_name, d.brand_name, d.drug_class, p.plan_name,
                   c.tier, c.copay, c.requires_prior_auth, c.quantity_limit
            FROM hc_drugs d
            JOIN hc_patients pt ON pt.member_id = :m
            JOIN hc_insurance_plans p ON p.plan_id = pt.plan_id
            LEFT JOIN hc_plan_drug_coverage c ON c.drug_id = d.drug_id AND c.plan_id = pt.plan_id
            WHERE lower(d.generic_name) = lower(:n) OR lower(d.brand_name) = lower(:n)
            LIMIT 1
        """), {"m": member_id, "n": name}).mappings().first()
    if not rows:
        return {"found": False, "message": f"'{name}' is not in the drug catalog I have data for."}
    if rows["tier"] is None:
        return {"found": True, "covered": False, "drug": rows["generic_name"], "plan": rows["plan_name"],
                "message": "This drug has no coverage entry on the patient's plan in my data."}
    return {
        "found": True, "covered": True, "drug": rows["generic_name"], "brand": rows["brand_name"],
        "drug_class": rows["drug_class"], "plan": rows["plan_name"], "tier": rows["tier"],
        "copay": _money(rows["copay"]), "requires_prior_authorization": rows["requires_prior_auth"],
        "quantity_limit": rows["quantity_limit"],
    }


# --------------------------------------------------------------------------- tool 4 (public info)
def plan_details(plan_name: str | None = None) -> dict[str, Any]:
    name = validate_name(plan_name, "plan_name") if plan_name else None
    with read_engine.connect() as conn:
        plans = conn.execute(text("""
            SELECT plan_id, plan_name, carrier, plan_type, monthly_premium, annual_deductible, out_of_pocket_max
            FROM hc_insurance_plans
            WHERE CAST(:n AS text) IS NULL OR lower(plan_name) = lower(:n)
            ORDER BY plan_name LIMIT :lim
        """), {"n": name, "lim": MAX_ROWS}).mappings().all()
        tiers = conn.execute(text("""
            SELECT plan_id, tier, max(copay) AS copay
            FROM hc_plan_drug_coverage GROUP BY plan_id, tier ORDER BY plan_id, tier
        """)).mappings().all()
    if not plans:
        return {"count": 0, "plans": [], "message": "No plan with that name."}
    return {"count": len(plans), "plans": [{
        "plan_name": p["plan_name"], "carrier": p["carrier"], "plan_type": p["plan_type"],
        "monthly_premium": _money(p["monthly_premium"]),
        "annual_deductible": _money(p["annual_deductible"]),
        "out_of_pocket_max": _money(p["out_of_pocket_max"]),
        "copay_by_drug_tier": {f"tier_{t['tier']}": _money(t["copay"])
                               for t in tiers if t["plan_id"] == p["plan_id"]},
    } for p in plans]}
