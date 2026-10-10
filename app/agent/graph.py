"""Multi-Agent LangGraph Workflow:
guard_input (SecurityGuardAgent) -> route (SupervisorAgent) -> authz (SecurityGuardAgent)
-> [tools_node (OrderToolsAgent) | composite_node (CompositeMultiStepAgent) | retrieve_node (PolicyRetrievalAgent)]
-> compose_node (SynthesisAgent) -> finalize_node (SynthesisAgent) -> END
"""
from __future__ import annotations
from ..db import get_conn
from ..retrieval.store import VectorStore
from ..retrieval.retriever import Retriever
from . import nodes

def _run_nodes(state: dict, conn, retriever) -> dict:
    """Sequential runner for nodes when executing directly or as fallback."""
    state.update(nodes.guard_input(state))
    state.update(nodes.route(state))
    
    authz_out = nodes.authz(state, conn)
    if authz_out:
        state.update(authz_out)
        state.update(nodes.finalize_node(state) or {})
        return state

    intent = state.get("intent", "general")
    ran = False

    if intent in ("order_status", "return_eligibility", "refund", "raise_return", "warranty"):
        state.update(nodes.tools_node(state, conn) or {})
        ran = True
    elif intent in ("multi_step", "what_if"):
        state.update(nodes.composite_node(state, conn, retriever) or {})
        ran = True

    if not ran or not state.get("answer"):
        if intent in ("policy_fact", "general") or state.get("answer_type") in (None, "", "not_found"):
            state.update(nodes.retrieve_node(state, conn, retriever) or {})

    state.update(nodes.compose_node(state) or {})
    state.update(nodes.finalize_node(state) or {})
    return state

def build_graph():
    """Returns a callable graph.execute(state)."""
    try:
        from langgraph.graph import StateGraph, END
        from .state import AgentState
        conn_holder = {}

        def _guard(s):
            return {**s, **nodes.guard_input(s)}

        def _route(s):
            return {**s, **nodes.route(s)}

        def _authz(s):
            out = nodes.authz(s, conn_holder["conn"])
            return {**s, **(out or {})}

        def _tools(s):
            return {**s, **(nodes.tools_node(s, conn_holder["conn"]) or {})}

        def _composite(s):
            return {**s, **(nodes.composite_node(s, conn_holder["conn"], conn_holder["retriever"]) or {})}

        def _retrieve(s):
            return {**s, **(nodes.retrieve_node(s, conn_holder["conn"], conn_holder["retriever"]) or {})}

        def _compose(s):
            return {**s, **(nodes.compose_node(s) or {})}

        def _finalize(s):
            return {**s, **(nodes.finalize_node(s) or {})}

        def _dispatch_after_authz(s):
            if s.get("refused"):
                return "finalize"
            intent = s.get("intent", "general")
            if intent in ("order_status", "return_eligibility", "refund", "raise_return", "warranty"):
                return "tools"
            elif intent in ("multi_step", "what_if"):
                return "composite"
            return "retrieve"

        g = StateGraph(AgentState)
        g.add_node("guard_input", _guard)
        g.add_node("route", _route)
        g.add_node("authz", _authz)
        g.add_node("tools", _tools)
        g.add_node("composite", _composite)
        g.add_node("retrieve", _retrieve)
        g.add_node("compose", _compose)
        g.add_node("finalize", _finalize)

        g.set_entry_point("guard_input")
        g.add_edge("guard_input", "route")
        g.add_edge("route", "authz")
        g.add_conditional_edges("authz", _dispatch_after_authz, {
            "finalize": "finalize",
            "tools": "tools",
            "composite": "composite",
            "retrieve": "retrieve"
        })
        g.add_edge("tools", "compose")
        g.add_edge("composite", "compose")
        g.add_edge("retrieve", "compose")
        g.add_edge("compose", "finalize")
        g.add_edge("finalize", END)
        compiled = g.compile()

        class Graph:
            def execute(self, state: dict) -> dict:
                conn = get_conn()
                try:
                    conn_holder["conn"] = conn
                    conn_holder["retriever"] = Retriever(conn)
                    return compiled.invoke(state)
                finally:
                    conn.close()
        return Graph()
    except Exception:
        class Graph:
            def execute(self, state: dict) -> dict:
                conn = get_conn()
                try:
                    return _run_nodes(state, conn, Retriever(conn))
                finally:
                    conn.close()
        return Graph()
