"""send_email: 승인한 답장을 같은 스레드로 보낸다(CONTRACT 4.4절, 계획 9절).

그래프 노드는 이 도구를 부르지 않는다. 승인 경로(`app/services/approval.py`)만 `use_google(access)` 안에서 부른다.
Gmail 발송은 자동 재시도하지 않는다(`GoogleClient.send_message`): 시간 초과여도 실제로 나갔을 수 있다.
"""

from base64 import b64decode, urlsafe_b64encode
from contextlib import contextmanager
from contextvars import ContextVar
from email.message import EmailMessage
from time import perf_counter

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.clients.gmail import GoogleError, GoogleUnavailable, TokenExpired
from app.services.auth import get_access_token
from app.tools.base import ToolResult

_access = ContextVar("send_email_google_access", default=None)


class Input(BaseModel):
    user_id: int
    thread_id: str
    to_addrs: list[str]
    subject: str
    body: str
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)
    attachments: list[dict[str, str]] = Field(default_factory=list)


@contextmanager
def use_google(access):
    """이 안에서 부른 send_email은 `access`(GoogleAccess)로 보낸다."""
    token = _access.set(access)
    try:
        yield
    finally:
        _access.reset(token)


def build_raw(data: Input, sender: str | None = None) -> str:
    """Gmail `raw` 값(base64url MIME). 답장 머리글(In-Reply-To·References)로 같은 대화에 붙는다."""
    message = EmailMessage()
    if sender:
        message["From"] = sender
    message["To"] = ", ".join(data.to_addrs)
    message["Subject"] = data.subject
    if data.in_reply_to:
        message["In-Reply-To"] = data.in_reply_to
    if data.references:
        message["References"] = " ".join(data.references)
    message.set_content(data.body)
    for attachment in data.attachments:
        maintype, _, subtype = attachment["mime_type"].partition("/")
        message.add_attachment(
            b64decode(attachment["content_b64"]), maintype=maintype, subtype=subtype or "octet-stream",
            filename=attachment["filename"],
        )
    return urlsafe_b64encode(message.as_bytes()).decode()


def google_error_kind(error: GoogleError) -> str:
    """Google 오류를 `ToolResult.error_kind`로 바꾼다(승인 경로의 원본 머리글 조회도 같이 쓴다)."""
    if isinstance(error, TokenExpired):
        return "auth"
    label = str(error)
    if label in {"HTTP 401", "HTTP 403"}:
        return "auth"
    if label == "HTTP 429":
        return "rate_limit"
    if label.startswith("HTTP 4"):
        return "invalid_input"  # Gmail이 요청을 거절함(보내지 않음이 확실)
    if isinstance(error, GoogleUnavailable):  # 5xx·시간 초과·연결 끊김: 실제로 나갔는지 모름
        return "network"
    return "internal"


@tool(args_schema=Input)
def send_email(**kwargs) -> ToolResult:
    """승인한 답장을 Gmail로 같은 스레드(threadId)에 보낸다. 성공하면 보낸 메일 id."""
    data = Input(**kwargs)
    access = _access.get()
    started = perf_counter()

    def finish(**fields):
        return ToolResult(source="gmail", duration_ms=int((perf_counter() - started) * 1000), **fields)

    if access is None:
        return finish(ok=False, error_kind="internal", error_message="Gmail 연결이 준비되지 않았습니다", attempts=0)
    try:
        gmail = access.google.gmail(get_access_token(access, data.user_id))
        sent_id = access.google.send_message(gmail, build_raw(data), data.thread_id)
    except GoogleError as error:
        # 오류 원문에는 토큰·주소가 섞일 수 있어 짧은 이름만 남긴다.
        return finish(ok=False, error_kind=google_error_kind(error), error_message=f"{error.code}: {error}")
    return finish(ok=True, value={"sent_message_id": sent_id})
