"""마스터 조립. 업무 구현은 주입하고 전이에는 LLM을 호출하지 않는다."""

from langgraph.graph import END, START, StateGraph

from app.graph.master.context import Dependencies
from app.graph.master.nodes import MasterNodes
from app.graph.master.state import WorkflowState


def build_workflow(*, dependencies: Dependencies, checkpointer):
    if checkpointer is None:
        raise ValueError("질문/승인 재개를 위한 checkpointer를 주입하세요")
    nodes = MasterNodes(dependencies)
    graph = StateGraph(WorkflowState)
    prepares = [f"{domain}_prepare" for domain in ("mail", "documents", "calendar")]
    rechecks = [f"{domain}_recheck" for domain in ("mail", "documents", "calendar")]
    executes = [f"{domain}_execute" for domain in ("mail", "documents", "calendar")]
    for name in ("load_context", "plan", "validate_plan", "select_task", "inspect_result",
                 "reflect", "ask_user", "await_approval", "cancel_action", "mark_execution", "record_result", "finish"):
        graph.add_node(name, getattr(nodes, name))
    for domain in ("mail", "documents", "calendar"):
        graph.add_node(f"{domain}_prepare", nodes.prepare)
        graph.add_node(f"{domain}_recheck", nodes.recheck)
        graph.add_node(f"{domain}_execute", nodes.execute)
        graph.add_edge(f"{domain}_prepare", "inspect_result")
        graph.add_conditional_edges(f"{domain}_recheck", lambda state: state["next"],
                                    ["mark_execution", "inspect_result", "record_result"])
        graph.add_edge(f"{domain}_execute", "select_task")
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "plan")
    graph.add_edge("plan", "validate_plan")
    routes = {
        "validate_plan": ["select_task", "finish"],
        "select_task": [*prepares, "finish"],
        "inspect_result": ["record_result", "ask_user", "await_approval", "reflect"],
        "reflect": [*prepares, "record_result"],
        "ask_user": prepares,
        "await_approval": [*prepares, *rechecks, "cancel_action"],
        "cancel_action": ["select_task", "record_result"],
    }
    for name, destinations in routes.items():
        graph.add_conditional_edges(name, lambda state: state["next"], destinations)
    graph.add_conditional_edges("mark_execution", lambda state: f"{state['work']['action']['domain']}_execute", executes)
    graph.add_edge("record_result", "select_task")
    graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)


def build_graph(*, node_overrides: dict | None = None):
    """기존 Gmail start_run 호출 경계. 같은 마스터에서 수신 준비 작업을 실행한다."""
    from app.graph.mail.inbound import InboundGraph

    return InboundGraph(node_overrides=node_overrides)
