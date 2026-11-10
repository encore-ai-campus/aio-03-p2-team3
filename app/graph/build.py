"""모든 계약 노드·전이. 뒤 작업은 nodes/의 함수만 채운다."""

from importlib import import_module

from langgraph.graph import END, START, StateGraph

from app.graph import routing
from app.graph.state import AgentState
from app.runlog.logger import traced_node, traced_route

NODE_NAMES = (
    "load_memory", "analyze_email", "draft_replies", "extract_deal", "check_required",
    "draft_followup", "make_quote", "reflect", "save_pending", "finish_failed",
)


def build_graph(*, node_overrides: dict | None = None):
    overrides = node_overrides or {}
    if set(overrides) - set(NODE_NAMES):
        raise ValueError("등록되지 않은 노드입니다")
    graph = StateGraph(AgentState)
    for name in NODE_NAMES:
        function = overrides.get(name) or getattr(import_module(f"app.graph.nodes.{name}"), name)
        graph.add_node(name, traced_node(name)(function))
    graph.add_edge(START, "load_memory")
    graph.add_edge("load_memory", "analyze_email")
    routes = {
        "analyze_email": (routing.route_after_analyze, ["draft_replies", "extract_deal", END, "save_pending", "finish_failed"]),
        "extract_deal": (routing.route_after_extract, ["check_required", "save_pending", "finish_failed"]),
        "check_required": (routing.route_after_check, ["draft_followup", "make_quote", "finish_failed"]),
        "make_quote": (routing.route_after_quote, ["draft_replies", "finish_failed"]),
        "draft_replies": (routing.route_after_draft, ["reflect", "save_pending", "finish_failed"]),
        "draft_followup": (routing.route_after_draft, ["reflect", "save_pending", "finish_failed"]),
        "reflect": (routing.route_after_reflect, ["save_pending", "extract_deal", "draft_replies", "draft_followup", "make_quote"]),
    }
    for name, (route, destinations) in routes.items():
        graph.add_conditional_edges(name, traced_route(name, route), destinations)
    graph.add_edge("save_pending", END)
    graph.add_edge("finish_failed", END)
    return graph.compile()
