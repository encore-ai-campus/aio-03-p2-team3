"""Gmail 수신 계약의 준비 하위 흐름. 발송은 하지 않는다."""

from copy import deepcopy

from langgraph.graph import END

from app.graph import routing
from app.graph.schemas import WorkflowError
from app.runlog.logger import traced_node, traced_route

from app.graph.master.context_adapter import load_memory
from app.graph.mail.classify_adapter import analyze_email
from app.graph.mail.draft_adapter import draft_replies
from app.graph.mail.followup_adapter import draft_followup
from app.graph.mail.pending_adapter import save_pending
from app.graph.documents.extract_adapter import extract_deal
from app.graph.documents.required_adapter import check_required
from app.graph.documents.quote_adapter import make_quote
from app.graph.master.review import reflect
from app.graph.master.failure import finish_failed

IMPLEMENTATIONS = {function.__name__: function for function in (
    load_memory, analyze_email, draft_replies, extract_deal, check_required,
    draft_followup, make_quote, reflect, save_pending, finish_failed,
)}

NODE_NAMES = (
    "load_memory", "analyze_email", "draft_replies", "extract_deal", "check_required",
    "draft_followup", "make_quote", "reflect", "save_pending", "finish_failed",
)


class InboundPreparation:
    """Gmail v1 상태를 새 마스터의 준비 작업으로 바꾸는 제한된 호환 어댑터.

    별도의 StateGraph/체크포인터를 만들지 않는다. 후보 준비 중 발송하지 않으며
    Gmail 수신기·평가·PC 스키마가 의존하는 기록과 누적 필드만 보존한다.
    """

    def __init__(self, overrides):
        if set(overrides) - set(NODE_NAMES):
            raise ValueError("등록되지 않은 노드입니다")
        self.nodes = {name: traced_node(name)(overrides.get(name) or IMPLEMENTATIONS[name]) for name in NODE_NAMES}
        self.routes = {name: traced_route(name, route) for name, route in {
            "analyze_email": routing.route_after_analyze,
            "extract_deal": routing.route_after_extract,
            "check_required": routing.route_after_check,
            "make_quote": routing.route_after_quote,
            "draft_replies": routing.route_after_draft,
            "draft_followup": routing.route_after_draft,
            "reflect": routing.route_after_reflect,
        }.items()}

    def invoke(self, initial, config=None):
        state = deepcopy(initial)
        node = "load_memory"
        for _ in range(min((config or {}).get("recursion_limit", 64), 64)):
            if node == END:
                return state
            update = self.nodes[node](state)
            for key, value in update.items():
                if key in {"tools_called", "reflection_history", "errors", "call_retries"}:
                    state[key] = state[key] + value
                else:
                    state[key] = value
            node = self.routes[node](state) if node in self.routes else {
                "load_memory": "analyze_email", "save_pending": END, "finish_failed": END,
            }[node]
        raise WorkflowError("inbound_step_limit")


def build_inbound(*, node_overrides: dict | None = None):
    return InboundPreparation(node_overrides or {})
