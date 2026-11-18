"""대화형 마스터의 모델 선택과 결과 전달. SQL/HTTP/업무 계산을 하지 않는다."""
import json

from langchain_core.messages import AIMessage, ToolMessage, message_to_dict
from langgraph.types import interrupt
from pydantic import ValidationError

from app.graph.master.tools import AGENT_TOOLS
from app.graph.schemas import Answer, Task, WorkflowError
from app.llm.client import classify_error

MAX_CALLS = 12


def tool_message(call, result):
    # 원문 전체는 별도 본인 조회에 남기고 모델 문맥의 도구 결과만 제한한다.
    content = json.dumps(result, ensure_ascii=False, default=str)
    if len(content) > 24000:
        content = json.dumps({"truncated": True, "excerpt": content[:23000]}, ensure_ascii=False)
    return message_to_dict(ToolMessage(content=content, tool_call_id=call["id"]))


def decide(state, choose, context):
    if state.get("agent_calls", 0) >= MAX_CALLS:
        return {"error": "agent_step_limit", "next": "finish"}
    try:
        message = AIMessage.model_validate(choose(state["messages"], context))
        if len(message.tool_calls) > 1 or message.invalid_tool_calls:
            raise WorkflowError("invalid_tool_calls")
        messages = [*state["messages"], message_to_dict(message)]
        calls = state.get("agent_calls", 0) + 1
        if not message.tool_calls:
            return {"messages": messages, "agent_calls": calls, "next": "finish"}
        call = message.tool_calls[0]
        base = {"messages": messages, "agent_calls": calls, "tool_call": call}
        try:
            definition = AGENT_TOOLS[call["name"]].invoke(call["args"])
            if call["name"] == "ask_user":
                return {**base, "dialog_question": definition["question"], "next": "agent_question"}
            command = Task(id=f"turn_{state.get('turn', 1)}_tool_{calls}", **definition)
            # 실제 업무 실행은 기존 prepare/검증/승인 노드를 통과한다.
            return {**base, "tasks": [*state["tasks"], command.model_dump(mode="json")],
                    "next": "validate_plan"}
        except (KeyError, ValueError, ValidationError):
            return {**base, "tool_call": None, "messages": [*messages,
                tool_message(call, {"status": "failed", "code": "invalid_tool_input"})], "next": "plan"}
    except Exception as error:
        # 예외에는 키/원문을 포함할 수 있으므로 안전한 코드만 저장한다.
        code = error.code if hasattr(error, "code") else f"agent_model_{classify_error(error)}"
        return {"error": code, "next": "finish"}


def observe(state):
    call = state.get("tool_call")
    current = state["current"]
    if call is None or current not in state["results"]:
        return None
    result = {**state["results"][current], "evidence": state["evidence"].get(current, [])}
    return {"messages": [*state["messages"], tool_message(call, result)],
            "current": None, "tool_call": None,
            "next": "finish" if result["status"] in {"cancelled", "unknown"} else "plan"}


def question(state):
    raw = interrupt({"kind": "question", "task_id": "agent", "fields": ["response"],
                     "message": state["dialog_question"]})
    answer = Answer.model_validate(raw)
    if answer.task_id != "agent" or set(answer.answers) != {"response"} or not isinstance(answer.answers["response"], str):
        raise WorkflowError("invalid_answer")
    return {"messages": [*state["messages"], tool_message(state["tool_call"], answer.answers)],
            "tool_call": None, "dialog_question": None, "next": "plan"}
