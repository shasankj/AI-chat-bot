"""MCP server + gateway tests. Integration tests: they use the real (read-only) database.
Run:  python -m pytest -q tests/test_mcp.py
"""
import asyncio

from mcp import Client
from sqlalchemy import text

from app.db import read_engine
from app.guardrails.output_guard import check_output
from app.mcp_client import McpGateway
from mcp_server.server import server

MARIA = "EHP-100001"    # Evergreen Basic HMO, 3 active prescriptions
JAMES = "SUM-200002"    # Summit Choice PPO
HAROLD = "HSC-400004"   # Harbor Medicare Rx Plus: 2 active + 1 discontinued


def run(coro):
    return asyncio.run(coro)


async def call(tool, args):
    async with Client(server) as c:
        return await c.call_tool(tool, args)


def table_count(name):
    with read_engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {name}")).scalar()


# ------------------------------------------------------------------------- the tools
def test_four_tools_all_marked_read_only():
    async def go():
        async with Client(server) as c:
            return (await c.list_tools()).tools
    tools = run(go())
    assert {t.name for t in tools} == {"get_patient_profile", "list_prescriptions",
                                       "get_drug_coverage", "get_plan_details"}
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)


def test_profile():
    r = run(call("get_patient_profile", {"member_id": MARIA})).structured_content
    assert r["name"] == "Maria Alvarez" and r["allergies_on_file"] == ["penicillin"]
    assert r["plan"]["plan_name"] == "Evergreen Basic HMO" and r["plan"]["monthly_premium"] == "$289.00"
    assert "phone" not in str(r).lower() and MARIA not in str(r)     # data minimization


def test_prescriptions_active_only_by_default():
    r = run(call("list_prescriptions", {"member_id": HAROLD})).structured_content
    assert r["count"] == 2 and {p["drug"] for p in r["prescriptions"]} == {"apixaban", "rosuvastatin"}
    r = run(call("list_prescriptions", {"member_id": HAROLD, "include_inactive": True})).structured_content
    assert r["count"] == 3 and "discontinued" in {p["status"] for p in r["prescriptions"]}


def test_prescription_carries_plan_coverage():
    rx = run(call("list_prescriptions", {"member_id": MARIA})).structured_content["prescriptions"]
    lisinopril = next(p for p in rx if p["drug"] == "lisinopril")
    assert lisinopril["plan_tier"] == 1 and lisinopril["plan_copay"] == "$5.00"


def test_coverage_by_brand_and_generic_and_unknown():
    a = run(call("get_drug_coverage", {"member_id": MARIA, "drug_name": "Lipitor"})).structured_content
    b = run(call("get_drug_coverage", {"member_id": MARIA, "drug_name": "atorvastatin"})).structured_content
    assert a == b and a["tier"] == 1 and a["copay"] == "$5.00"
    prior_auth = run(call("get_drug_coverage", {"member_id": MARIA, "drug_name": "Ozempic"})).structured_content
    assert prior_auth["requires_prior_authorization"] is True and prior_auth["tier"] == 4
    unknown = run(call("get_drug_coverage", {"member_id": MARIA, "drug_name": "unobtainium"})).structured_content
    assert unknown["found"] is False


def test_plan_details_public_info():
    r = run(call("get_plan_details", {})).structured_content
    assert r["count"] == 4
    harbor = run(call("get_plan_details", {"plan_name": "Harbor Medicare Rx Plus"})).structured_content["plans"][0]
    assert harbor["copay_by_drug_tier"]["tier_1"] == "$0.00" and harbor["out_of_pocket_max"] == "$2,000.00"


# ------------------------------------------------------------------------- hostile inputs
def test_sql_injection_attempts_are_rejected_and_change_nothing():
    before = (table_count("hc_drugs"), table_count("hc_patients"))
    attacks = [
        ("get_patient_profile", {"member_id": "x' OR '1'='1"}),
        ("get_patient_profile", {"member_id": "EHP-100001'; DROP TABLE hc_patients;--"}),
        ("get_drug_coverage", {"member_id": MARIA, "drug_name": "'; DROP TABLE hc_drugs;--"}),
        ("get_drug_coverage", {"member_id": MARIA, "drug_name": "lisinopril' OR '1'='1"}),
        ("get_plan_details", {"plan_name": "x'; DELETE FROM hc_insurance_plans;--"}),
    ]
    for tool, args in attacks:
        r = run(call(tool, args))
        assert r.is_error, (tool, args)
        assert "may contain only" in r.content[0].text or "must look like" in r.content[0].text  # message is visible
    assert (table_count("hc_drugs"), table_count("hc_patients")) == before


def test_unknown_member_gives_visible_error():
    r = run(call("get_patient_profile", {"member_id": "ZZZ-999999"}))
    assert r.is_error and "No patient was found" in r.content[0].text


def test_database_is_read_only_even_if_code_were_compromised():
    import pytest
    from sqlalchemy.exc import InternalError, ProgrammingError
    with read_engine.connect() as conn:
        with pytest.raises((InternalError, ProgrammingError)):
            conn.execute(text("UPDATE hc_patients SET first_name = 'Hacked'"))


# ------------------------------------------------------------------------- the gateway (trust boundary)
def test_gateway_hides_identity_from_llm_and_forces_session_member():
    async def go():
        async with McpGateway(server) as gw:
            specs = gw.llm_tools()
            # The model tries to read ANOTHER patient by passing their member_id:
            out = await gw.call("get_patient_profile", {"member_id": JAMES}, member_id=MARIA)
            return specs, out
    specs, out = run(go())
    assert all("member_id" not in s["input_schema"]["properties"] for s in specs)
    assert all("member_id" not in s["input_schema"].get("required", []) for s in specs)
    assert out.ok and out.data["name"] == "Maria Alvarez"          # session wins, NOT James Okafor


def test_gateway_rejects_invented_tools_and_drops_unexpected_args():
    async def go():
        async with McpGateway(server) as gw:
            bad = await gw.call("run_sql", {"query": "select * from hc_patients"}, member_id=MARIA)
            ok = await gw.call("get_drug_coverage", {"drug_name": "Lipitor", "evil": "x"}, member_id=MARIA)
            return bad, ok
    bad, ok = run(go())
    assert not bad.ok and "Unknown tool" in bad.error
    assert ok.ok and ok.data["tier"] == 1


def test_gateway_returns_errors_as_data():
    async def go():
        async with McpGateway(server) as gw:
            return await gw.call("get_drug_coverage", {"drug_name": "'; DROP TABLE x;--"}, member_id=MARIA)
    out = run(go())
    assert not out.ok and "may contain only" in out.error


# ------------------------------------------------------------------------- integration with Step 7
def test_tool_output_works_with_output_guard():
    async def go():
        async with McpGateway(server) as gw:
            return await gw.call("get_drug_coverage", {"drug_name": "Lipitor"}, member_id=MARIA)
    item = run(go()).to_context_item("T1")
    good = check_output("Lipitor is tier 1 with a $5.00 copay [T1].", {"T1"}, set(), item.text)
    assert good.ok, good.reason                       # '$5.00' is found in the tool text
    bad = check_output("Lipitor is tier 1 with a $9.00 copay [T1].", {"T1"}, set(), item.text)
    assert not bad.ok and bad.reason.startswith("ungrounded_dollar_amount")


# ------------------------------------------------------------------------- the real transport
def test_real_stdio_subprocess_end_to_end():
    async def go():
        async with McpGateway() as gw:            # spawns `python -m mcp_server.server`
            names = [s["name"] for s in gw.llm_tools()]
            out = await gw.call("get_patient_profile", {}, member_id=HAROLD)
            return names, out
    names, out = run(go())
    assert len(names) == 4
    assert out.ok and out.data["name"] == "Harold Whitfield"
