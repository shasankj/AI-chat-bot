"""See the MCP tools work over the REAL transport (a child process speaking over stdio).

From backend/:  python -m scripts.mcp_demo [MEMBER_ID]      (default EHP-100001 = Maria Alvarez)
The member id plays the role of the 'logged-in patient'. Notice the 'evil' attempt at the end:
the model asks for someone else's record, and the gateway overrides it with the session's id.
"""
import asyncio
import json
import sys

from app.mcp_client import McpGateway


async def main(member_id: str) -> None:
    async with McpGateway() as gw:
        print("Tools the LLM is allowed to see (note: no member_id anywhere):")
        for spec in gw.llm_tools():
            print(f"  - {spec['name']}({', '.join(spec['input_schema'].get('properties', {}))})")

        for tool, args in [("get_patient_profile", {}),
                           ("list_prescriptions", {}),
                           ("get_drug_coverage", {"drug_name": "Ozempic"}),
                           ("get_drug_coverage", {"drug_name": "'; DROP TABLE hc_drugs;--"}),
                           ("get_patient_profile", {"member_id": "SUM-200002"})]:   # the 'evil' attempt
            out = await gw.call(tool, args, member_id=member_id)
            print(f"\n>>> {tool}({args})")
            print(json.dumps(out.data, indent=2) if out.ok else f"ERROR (shown to user): {out.error}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "EHP-100001"))
