"""Chat with the agent in your terminal, as one of the 8 synthetic patients.

From backend/:  python -m scripts.chat_cli [MEMBER_ID]     (default EHP-100001 = Maria Alvarez)
Members: EHP-100001 Maria | SUM-200002 James | LKB-300003 Priya | HSC-400004 Harold
         HSC-400005 Linda | SUM-200007 Daniel | EHP-100008 Aisha | HSC-400009 Robert
Type 'quit' to exit. Progress events print in grey as the graph runs; memory persists within a session.
"""
import asyncio
import sys
import uuid

from app.agent.graph import build_graph
from app.agent.runner import run_agent
from app.auth.access import Access
from app.mcp_client import McpGateway

GREY, RESET, BOLD = "\033[90m", "\033[0m", "\033[1m"


async def main(member_id: str) -> None:
    session = uuid.uuid4().hex
    async with McpGateway() as gateway:
        graph = build_graph(gateway)
        print(f"Logged in as {member_id}. Ask about coverage, copays, prescriptions, policies. 'quit' exits.\n")
        while True:
            try:
                question = input(f"{BOLD}you>{RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if question.lower() in {"quit", "exit"}:
                break
            async for ev in run_agent(graph, question, Access.patient(member_id), session):
                t = ev["type"]
                if t == "status":
                    print(f"{GREY}  · {ev['message']}{RESET}")
                elif t == "tool":
                    print(f"{GREY}  · MCP tool {ev['name']}: {ev['status']}{(' - ' + ev['error']) if ev.get('error') else ''}{RESET}")
                elif t == "retrieval":
                    print(f"{GREY}  · {ev['count']} document passage(s) retrieved{RESET}")
                elif t == "final":
                    print(f"\n{BOLD}bot [{ev['kind']}]>{RESET} {ev['text']}")
                    for s in ev["sources"]:
                        where = f" p.{s['page']}" if s.get("page") else ""
                        print(f"   [{s['id']}] {s['title']}{where}  {s.get('url') or ''}")
                    if ev.get("debug", {}).get("guard"):
                        print(f"   {GREY}(output guard blocked the model's draft: {ev['debug']['guard']}){RESET}")
                    print()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "EHP-100001"))
