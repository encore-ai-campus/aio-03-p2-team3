"""대화형 마스터의 Bearer 전용 HTTP 경계. 모델/서비스 실행은 백그라운드로 접수한다."""
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth.supabase import bearer_user_id
from app.graph.schemas import WorkflowError

router = APIRouter(prefix="/api/agent", tags=["agent"])

MESSAGES = {
    "workflow_not_found": "대화를 찾을 수 없습니다.",
    "agent_busy": "이미 처리 중인 요청이 있습니다. 완료 후 다시 시도해 주세요.",
    "stale_conversation": "다른 화면에서 대화가 변경됐습니다. 최신 상태를 다시 읽어 주세요.",
}


def reply(function, *args, status=200, **kwargs):
    try:
        return JSONResponse(function(*args, **kwargs), status_code=status,
                            headers={"Cache-Control": "private, no-store"})
    except WorkflowError as error:
        return JSONResponse({"error": {"code": error.code, "message": MESSAGES.get(error.code, "요청 상태를 확인해 주세요.")}},
                            status_code=404 if error.code == "workflow_not_found" else 409,
                            headers={"Cache-Control": "private, no-store"})


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=8000, pattern=r"\S")


class Continue(Message):
    revision: int = Field(gt=0)


class Resume(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(gt=0)
    response: dict


class Recover(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(gt=0)


@router.get("/conversations")
def conversations(request: Request, owner: int = Depends(bearer_user_id)):
    return reply(request.app.state.agent.store.list, owner)


@router.get("/conversations/{conversation_id}")
def conversation(conversation_id: UUID, request: Request, owner: int = Depends(bearer_user_id)):
    return reply(request.app.state.agent.store.get, owner, conversation_id.hex)


@router.post("/conversations")
def start(body: Message, request: Request, background: BackgroundTasks, owner: int = Depends(bearer_user_id)):
    service = request.app.state.agent
    def accept():
        data = service.start(owner, body.message)
        background.add_task(service.run, owner, data["id"], "start", body.model_dump())
        return data
    return reply(accept, status=202)


def accept(request, background, owner, conversation_id, body, operation):
    service = request.app.state.agent
    data = service.submit(owner, conversation_id.hex, body.revision)
    background.add_task(service.run, owner, data["id"], operation, body.model_dump())
    return data


@router.post("/conversations/{conversation_id}/messages")
def message(conversation_id: UUID, body: Continue, request: Request, background: BackgroundTasks,
            owner: int = Depends(bearer_user_id)):
    return reply(accept, request, background, owner, conversation_id, body, "message", status=202)


@router.post("/conversations/{conversation_id}/resume")
def resume(conversation_id: UUID, body: Resume, request: Request, background: BackgroundTasks,
           owner: int = Depends(bearer_user_id)):
    return reply(accept, request, background, owner, conversation_id, body, "resume", status=202)


@router.post("/conversations/{conversation_id}/recover")
def recover(conversation_id: UUID, body: Recover, request: Request, background: BackgroundTasks,
            owner: int = Depends(bearer_user_id)):
    return reply(accept, request, background, owner, conversation_id, body, "recover", status=202)
