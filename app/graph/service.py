"""대화 실행과 화면 투영. DB와 런타임 조립은 호출자가 주입한다."""
from __future__ import annotations

from contextlib import ExitStack
import json
import logging
from threading import Lock
from typing import Callable, Protocol
from uuid import uuid4

from langchain_core.messages import messages_from_dict

from app.graph.schemas import WorkflowError

logger = logging.getLogger(__name__)

NODE_LABELS = {"load_context": "대화 맥락 불러오기", "plan": "다음 작업 판단",
               "reflect": "작업 결과 재검토", "cancel_action": "작업 취소"}
PREPARE_LABELS = {
    ("mail", "search"): "메일 검색", ("mail", "query"): "메일 원문 조회",
    ("mail", "draft"): "답장 초안 작성", ("mail", "send"): "답장 발송 준비",
    ("documents", "get"): "문서 조회", ("documents", "schema"): "문서 입력 조건 확인",
    ("documents", "search_trade_prices"): "등록 단가 조회",
    ("documents", "search_counterparties"): "거래처 정보 조회",
    ("documents", "search_issued"): "발급 문서 검색",
    ("documents", "search_knowledge"): "문서함 검색",
    ("documents", "draft"): "문서 초안 작성", ("documents", "issue"): "파일 발급 준비",
    ("documents", "approve_packing"): "포장 합계 승인 준비",
    ("calendar", "list_events"): "캘린더 일정 조회",
    ("calendar", "find_slots"): "일정 후보 조회", ("calendar", "create"): "일정 등록 준비",
}
EXECUTE_LABELS = {"send": "답장 발송", "issue": "파일 발급", "approve_packing": "포장 합계 승인",
                  "create": "일정 등록"}


class Conversations(Protocol):
    def list(self, owner: int) -> list[dict]: ...
    def get(self, owner: int, conversation_id: str) -> dict: ...
    def claim(self, owner: int, conversation_id: str, *, title=None, revision=None) -> dict: ...
    def update_progress(self, owner: int, conversation_id: str, revision: int, steps: list[dict]) -> None: ...
    def finish(self, owner: int, conversation_id: str, revision: int, view: dict, status: str) -> None: ...
    def interrupt_running(self) -> None: ...


def progress_label(node, state, operation):
    if node == "plan" and state.get("error"):
        return None
    if node in NODE_LABELS:
        return NODE_LABELS[node]
    domain, _, phase = node.partition("_")
    if phase == "prepare":
        task = next((task for task in state.get("tasks", []) if task["id"] == state.get("current")), {})
        return PREPARE_LABELS.get((domain, task.get("operation")), "업무 준비")
    if phase == "recheck":
        return "승인 내용 재확인"
    if phase == "execute":
        if operation == "recover":
            return "저장된 실행 결과 확인"
        action = (state.get("work") or {}).get("action") or {}
        return EXECUTE_LABELS.get(action.get("operation"), "업무 실행")
    return None


def project(snapshot):
    state, waiting = snapshot["state"], snapshot["waiting"]
    messages = []
    questions = {}
    for item in messages_from_dict(state.get("messages", [])):
        if item.type == "ai":
            for call in item.tool_calls:
                if call["name"] == "ask_user":
                    questions[call["id"]] = call["args"].get("question", "")
        if item.type == "tool" and item.tool_call_id in questions:
            answer = json.loads(item.content).get("response")
            if isinstance(answer, str):
                messages.extend([{"role": "assistant", "text": questions[item.tool_call_id]},
                                 {"role": "user", "text": answer}])
        if item.type not in {"human", "ai"}:
            continue
        text = item.content if isinstance(item.content, str) else "\n".join(
            part.get("text", "") for part in item.content if isinstance(part, dict))
        if text:
            messages.append({"role": "user" if item.type == "human" else "assistant", "text": text})
    results = [{"task_id": task["id"], "domain": task["domain"], "operation": task["operation"],
                "kind": task["inputs"].get("kind"),
                **state["results"][task["id"]]} for task in state["tasks"] if task["id"] in state["results"]]
    status = ("needs_approval" if waiting and waiting["kind"] == "approval" else "needs_input" if waiting
              else "error" if state["error"] else "interrupted" if snapshot["pending"]
              else "review" if any(item["status"] == "unknown" for item in results) else "completed")
    return {"messages": messages, "results": results, "waiting": waiting, "error": state["error"],
            "working": state.get("work")}, status


class AgentService:
    def __init__(self, store: Conversations, runtime_factory: Callable):
        self.store, self.runtime_factory = store, runtime_factory
        self.stack, self.lock, self.runtime = ExitStack(), Lock(), None
        store.interrupt_running()

    def _runtime(self):
        with self.lock:
            if self.runtime is None:
                self.runtime = self.stack.enter_context(self.runtime_factory())
            return self.runtime

    def close(self):
        self.stack.close()

    def start(self, owner, request):
        return self.store.claim(owner, uuid4().hex, title=request)

    def submit(self, owner, conversation_id, revision):
        return self.store.claim(owner, conversation_id, revision=revision)

    def run(self, owner, conversation_id, operation, payload):
        previous = self.store.get(owner, conversation_id)
        revision = previous["revision"]
        steps = {}
        task_ids = {}
        progress_available = True

        def on_task(event):
            nonlocal progress_available
            if not progress_available:
                return
            step_id = event["id"]
            if "input" in event:
                label = progress_label(event["name"], event["input"], operation)
                if label is None:
                    return
                steps[step_id] = {"label": label, "status": "running"}
                task_ids[step_id] = event["input"].get("current")
            elif step_id in steps:
                result = event["result"] or {}
                work = result.get("work") or {}
                outcome = (result.get("results") or {}).get(task_ids[step_id], {})
                failed = event["error"] or result.get("error") or "failed" in (work.get("status"), outcome.get("status"))
                review = work.get("status") == "needs_review" or outcome.get("status") == "unknown"
                status = "failed" if failed else "review" if review else "completed"
                steps[step_id] = {**steps[step_id], "status": status}
            else:
                return
            try:
                self.store.update_progress(owner, conversation_id, revision, list(steps.values()))
            except Exception:
                progress_available = False
                logger.warning("업무 도우미 진행 상태 저장 실패")

        runtime = None
        try:
            runtime = self._runtime()
            execution = {"actor_id": owner, "thread_id": conversation_id, "on_task": on_task}
            if operation == "start":
                runtime.start(**execution, request=payload["message"])
            elif operation == "message":
                runtime.message(**execution, request=payload["message"])
            elif operation == "resume":
                runtime.resume(**execution, response=payload["response"])
            elif operation == "recover":
                runtime.recover(**execution)
            else:
                raise WorkflowError("unsupported_operation")
            view, status = project(runtime.snapshot(actor_id=owner, thread_id=conversation_id))
            prior = {item["task_id"]: item for item in previous.get("results", [])}
            prior.update({item["task_id"]: item for item in view["results"]})
            view["results"] = list(prior.values())
        except Exception as error:
            code = error.code if isinstance(error, WorkflowError) else "agent_execution_failed"
            view, status = {key: previous.get(key) for key in ("messages", "results", "waiting")}, "error"
            if runtime is not None:
                try:
                    view, status = project(runtime.snapshot(actor_id=owner, thread_id=conversation_id))
                    if status == "completed":
                        status = "error"
                except WorkflowError:
                    pass
            view["error"] = code
        self.store.finish(owner, conversation_id, revision, view, status)
