"""Client-side gateway to the MCP server. This is where the TRUST BOUNDARY lives.

The MCP server trusts its caller (like any internal service). So THIS layer guarantees:
  * the LLM only ever sees tool schemas WITHOUT `member_id`
  * `member_id` always comes from the authenticated session, never from the model or the chat text
  * only tools the server actually advertises can be called (no invented tool names)
  * arguments the schema doesn't define are dropped
  * every call has a timeout, and failures come back as data (so the UI can show them)
"""
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp import Client, StdioServerParameters

from app.guardrails.fencing import ContextItem

BACKEND_DIR = Path(__file__).resolve().parents[1]
CALL_TIMEOUT_SECONDS = 15
IDENTITY_FIELD = "member_id"


def stdio_server_params() -> StdioServerParameters:
    """Launch our MCP server as a child process, speaking over its stdin/stdout."""
    return StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"],
                                 cwd=str(BACKEND_DIR))


@dataclass(frozen=True)
class ToolOutcome:
    tool: str
    ok: bool
    data: Any = None          # parsed result when ok
    error: str | None = None  # user-visible error text when not ok

    def to_context_item(self, item_id: str) -> ContextItem:
        body = json.dumps(self.data, indent=2) if self.ok else f"ERROR: {self.error}"
        return ContextItem(id=item_id, kind="tool_result", text=f"tool: {self.tool}\n{body}")


class McpGateway:
    """Long-lived connection (one subprocess shared by all requests)."""

    def __init__(self, target: Any | None = None):
        # target: StdioServerParameters (production), or an MCPServer instance (in-process tests)
        self._client = Client(target if target is not None else stdio_server_params())
        self._specs: dict[str, dict] = {}

    async def __aenter__(self) -> "McpGateway":
        await self._client.__aenter__()
        for tool in (await self._client.list_tools()).tools:
            schema = json.loads(json.dumps(tool.input_schema))      # deep copy
            schema.get("properties", {}).pop(IDENTITY_FIELD, None)  # hide identity from the LLM
            schema["required"] = [r for r in schema.get("required", []) if r != IDENTITY_FIELD]
            self._specs[tool.name] = {
                "name": tool.name, "description": tool.description or "", "input_schema": schema,
                "takes_identity": IDENTITY_FIELD in (tool.input_schema.get("properties") or {}),
            }
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.__aexit__(*exc)

    def llm_tools(self, allowed: "frozenset[str] | set[str] | None" = None) -> list[dict]:
        """Tool definitions safe to show the model: no identity parameter, and ONLY the tools the
        caller's role is allowed to use (None = all, used by tests)."""
        return [{k: v for k, v in s.items() if k != "takes_identity"}
                for s in self._specs.values() if allowed is None or s["name"] in allowed]

    async def call(self, tool: str, llm_args: dict[str, Any], member_id: str | None,
                   allowed: "frozenset[str] | set[str] | None" = None) -> ToolOutcome:
        spec = self._specs.get(tool)
        if spec is None:
            return ToolOutcome(tool, False, error=f"Unknown tool '{tool}'.")
        if allowed is not None and tool not in allowed:      # enforced here even if the model asks anyway
            return ToolOutcome(tool, False, error=f"The tool '{tool}' is not permitted for this account.")
        if spec["takes_identity"] and not member_id:
            return ToolOutcome(tool, False, error="No patient is selected for this session.")

        allowed = set(spec["input_schema"].get("properties", {}))
        args = {k: v for k, v in (llm_args or {}).items() if k in allowed}   # drop unexpected keys
        if spec["takes_identity"]:
            args[IDENTITY_FIELD] = member_id          # ALWAYS overwrite: the model cannot choose

        try:
            result = await asyncio.wait_for(self._client.call_tool(tool, args), CALL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            return ToolOutcome(tool, False, error=f"{tool} timed out after {CALL_TIMEOUT_SECONDS}s.")
        except Exception as exc:                       # transport/protocol failure
            return ToolOutcome(tool, False, error=f"{type(exc).__name__}: {exc}")

        if result.is_error:
            message = " ".join(getattr(b, "text", "") for b in result.content).strip()
            return ToolOutcome(tool, False, error=message or "Tool failed.")
        data = result.structured_content
        if data is None:
            data = {"text": " ".join(getattr(b, "text", "") for b in result.content)}
        return ToolOutcome(tool, True, data=data)
