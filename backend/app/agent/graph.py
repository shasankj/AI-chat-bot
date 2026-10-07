"""Wire the nodes into a LangGraph state machine."""
from typing import Any, Callable

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from app.agent.llm import make_llm
from app.agent.nodes import AgentNodes
from app.agent.state import AgentState
from app.mcp_client import McpGateway
from app.rag.retriever import search


def default_retriever(question: str, k: int, **filters) -> list:
    """Hybrid search + relevance gate (max distance). `filters` = category / drug_ids metadata filters."""
    return search(question, k=k, **filters)


def build_graph(gateway: McpGateway,
                llm_factory: Callable[[int], Any] = make_llm,
                retriever: Callable[..., list] = default_retriever,
                checkpointer: Any = None):
    n = AgentNodes(gateway, llm_factory, retriever)

    g = StateGraph(AgentState)
    for name in ("input_guard", "gate", "retrieve", "plan_tools", "build_context",
                 "answer", "output_guard", "finalize"):
        g.add_node(name, getattr(n, name))

    g.add_edge(START, "input_guard")

    # A conditional edge is a function (state) -> next node name(s). Returning a LIST runs those
    # nodes in PARALLEL: that is how retrieval and MCP tool calls overlap.
    g.add_conditional_edges("input_guard",
                            lambda s: "finalize" if s.get("final") else "gate",
                            ["finalize", "gate"])

    def after_gate(s: dict) -> list[str]:
        if s.get("final"):                       # medical advice / manipulation / off-topic
            return ["finalize"]
        nxt = []
        if s.get("needs_policy_docs"):
            nxt.append("retrieve")
        if s.get("needs_patient_data") or s.get("needs_plan_catalog"):
            nxt.append("plan_tools")
        return nxt or ["retrieve"]

    g.add_conditional_edges("gate", after_gate, ["retrieve", "plan_tools", "finalize"])
    g.add_edge("retrieve", "build_context")      # build_context runs once, after whichever branches ran
    g.add_edge("plan_tools", "build_context")
    g.add_conditional_edges("build_context",
                            lambda s: "finalize" if s.get("final") else "answer",
                            ["finalize", "answer"])
    g.add_edge("answer", "output_guard")
    g.add_edge("output_guard", "finalize")
    g.add_edge("finalize", END)

    # The checkpointer stores conversation state per thread_id. InMemorySaver is for development;
    # production would use a Postgres-backed saver so memory survives restarts.
    return g.compile(checkpointer=checkpointer or InMemorySaver())
