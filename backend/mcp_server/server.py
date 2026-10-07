"""MCP server: exposes four READ-ONLY tools over stdio.

Run standalone (from backend/):  python -m mcp_server.server
NEVER print() in this process: with the stdio transport, stdout IS the protocol channel.
Diagnostics go to stderr via logging.
"""
import asyncio
import logging
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from mcp_server import queries

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[mcp] %(message)s")
log = logging.getLogger("mcp_server")

server = MCPServer(
    name="healthcare-readonly",
    instructions="Read-only lookups of a patient's profile, prescriptions and plan drug coverage.",
)

# Hints for clients/UIs (hints only; real enforcement is the read-only DB role).
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)


async def _run(fn, *args) -> dict[str, Any]:
    """Run blocking DB code off the event loop. Errors propagate: the MCP layer returns them to the
    client as an error result (is_error=True) so the UI can show them instead of hiding them."""
    log.info("tool=%s", fn.__name__)                    # tool name only: never log patient data
    try:
        return await asyncio.to_thread(fn, *args)
    except queries.ToolInputError as exc:
        # Anticipated failure -> ToolError: the message REACHES the user/model (is_error=True).
        # Any OTHER exception is treated by the SDK as a crash: the client sees only a generic
        # "Error executing tool X" and the traceback stays in the server log (no secret leakage).
        raise ToolError(str(exc)) from exc


@server.tool(annotations=READ_ONLY)
async def get_patient_profile(member_id: str) -> dict[str, Any]:
    """Get the current patient's basic profile (name, age, sex, allergies on file) and their
    insurance plan (plan name, carrier, type, premium, deductible, out-of-pocket maximum)."""
    return await _run(queries.patient_profile, member_id)


@server.tool(annotations=READ_ONLY)
async def list_prescriptions(member_id: str, include_inactive: bool = False) -> dict[str, Any]:
    """List the current patient's prescriptions: drug, dosage, frequency, refills, prescriber, status,
    plus the plan's tier, copay, prior-authorization requirement and quantity limit for each drug.
    By default only ACTIVE prescriptions; set include_inactive=true to include completed/discontinued."""
    return await _run(queries.prescriptions, member_id, include_inactive)


@server.tool(annotations=READ_ONLY)
async def get_drug_coverage(member_id: str, drug_name: str) -> dict[str, Any]:
    """Look up how the current patient's plan covers one drug (generic or brand name):
    tier, copay, prior authorization required, quantity limit."""
    return await _run(queries.drug_coverage, member_id, drug_name)


@server.tool(annotations=READ_ONLY)
async def get_plan_details(plan_name: str | None = None) -> dict[str, Any]:
    """Public plan information (premium, deductible, out-of-pocket maximum, copay per drug tier).
    Give plan_name for one plan, or omit it to list all plans. Not patient-specific."""
    return await _run(queries.plan_details, plan_name)


if __name__ == "__main__":
    server.run()   # stdio transport by default
