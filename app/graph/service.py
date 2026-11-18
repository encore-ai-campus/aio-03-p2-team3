"""대화 실행과 화면 투영. DB와 런타임 조립은 호출자가 주입한다."""
from contextlib import ExitStack
import json
from threading import Lock
from typing import Callable, Protocol
from uuid import uuid4

from langchain_core.messages import messages_from_dict

from app.graph.schemas import WorkflowError


class Conversations(Protocol):
    def list(self, owner: int) -> list[dict]: ...
    def get(self, owner: int, conversation_id: str) -> dict: ...
    def claim(self, owner: int, conversation_id: str, *, title=None, revision=None) -> dict: ...
    def finish(self, owner: int, conversation_id: str, view: dict, status: str) -> None: ...
    def interrupt_running(self) -> None: ...


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
        runtime = None
        try:
            runtime = self._runtime()
            if operation == "start":
                runtime.start(actor_id=owner, thread_id=conversation_id, request=payload["message"])
            elif operation == "message":
                runtime.message(actor_id=owner, thread_id=conversation_id, request=payload["message"])
            elif operation == "resume":
                runtime.resume(actor_id=owner, thread_id=conversation_id, response=payload["response"])
            elif operation == "recover":
                runtime.recover(actor_id=owner, thread_id=conversation_id)
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
        self.store.finish(owner, conversation_id, view, status)
