"""모델용 업무 입구. 실행은 기존 master의 prepare/승인/execute 경계를 지난다."""
from typing import Annotated, Literal
from copy import deepcopy

from langchain_core.tools import tool
from pydantic import AwareDatetime, Field

from app.graph.calendar.schemas import CalendarEventSelection, CalendarMoveInput
from app.graph.documents.schemas import (
    CounterpartySearch, DocumentInput, DocumentKind, DraftDocumentSearch, IssuedDocumentSearch, KnowledgeDocumentSearch, TradePriceSearch,
)

from app.graph.mail.schemas import (
    AttachmentInput, FollowupCancelInput, FollowupInput, FollowupListInput, ReplyEditInput, SearchInput, SentMailSearch,
)
from app.mail.schemas import ComposeInput

Positive = Annotated[int, Field(gt=0, strict=True)]


def task(domain, operation, **inputs):
    return {"domain": domain, "operation": operation, "inputs": inputs}


@tool(args_schema=SearchInput)
def search_mail(**inputs) -> dict:
    """본인의 앱에 수집된 수신 메일을 제목·발신자·본문·수신 시각으로 찾는다.
    아직 답장 안 한 메일은 reply_status=unanswered를 넣는다. 발송 전 초안은 답장으로 세지 않는다.
    결과의 thread_id로 원문을 조회한다. 다음 페이지는 같은 조건과 next_cursor를 사용한다.
    """
    return task("mail", "search", **SearchInput.model_validate(inputs).model_dump(mode="json"))


@tool
def get_mail(thread_id: str) -> dict:
    """검색 결과의 실제 thread_id로 원문과 저장된 답장 후보를 조회한다."""
    return task("mail", "query", thread_id=thread_id)


@tool(args_schema=AttachmentInput)
def list_mail_attachments(**inputs) -> dict:
    """get_mail에서 읽은 thread_id와 정확한 gmail_message_id로 실제 Gmail 첨부를 조회한다.
    첨부 결과의 파일명·형식·크기를 사용한다. 목록이 비면 원본에 첨부가 없다. 읽기 실패는 빈 목록과 구별한다.
    """
    return task("mail", "attachments", **AttachmentInput.model_validate(inputs).model_dump(mode="json"))


@tool(args_schema=SentMailSearch)
def search_sent_mail(**inputs) -> dict:
    """앱에 수집된 실제 발송 메일을 제목이나 상대 이메일로 찾는다. 여러 스레드가 맞으면 사용자에게 선택을 요청한다."""
    return task("mail", "search_sent", **SentMailSearch.model_validate(inputs).model_dump(mode="json"))


@tool(args_schema=FollowupInput)
def register_mail_followup(**inputs) -> dict:
    """사용자가 요청한 답장 미수신 알림을 앱에 등록한다. 이번 조회에서 찾은 thread_id와 사용자가 지정한 기한을 사용한다.
    결과의 기준 발송 시각·기한·상태를 안내한다. 실제 발송 기록이 있어야 등록되며, 알림은 앱에 표시된다.
    """
    return task("mail", "register_followup", **FollowupInput.model_validate(inputs).model_dump(mode="json"))


@tool(args_schema=FollowupListInput)
def list_mail_followups(**inputs) -> dict:
    """내 답장 대기 알림과 상태를 조회한다. next_cursor가 있으면 같은 조회의 다음 페이지에 사용한다."""
    return task("mail", "list_followups", **FollowupListInput.model_validate(inputs).model_dump(mode="json"))


@tool(args_schema=FollowupCancelInput)
def cancel_mail_followup(**inputs) -> dict:
    """사용자가 지정한 기존 후속 알림을 취소한다. 이번 list_mail_followups에서 확인한 ID를 쓰고 상태를 확인한다."""
    return task("mail", "cancel_followup", **FollowupCancelInput.model_validate(inputs).model_dump(mode="json"))


@tool(args_schema=ComposeInput)
def prepare_new_mail(**inputs) -> dict:
    """기존 스레드에 답장하지 않고 새 메일 초안을 앱에 저장한다. 수신자는 사용자가 확인한 주소만 넣는다.
    저장된 id는 채팅 편집 카드에서 쓴다. 이 도구는 메일을 보내지 않는다.
    """
    return task("mail", "compose", **ComposeInput.model_validate(inputs).model_dump(mode="json"))


@tool(args_schema=ReplyEditInput)
def prepare_edit_reply(**inputs) -> dict:
    """기존 답장 초안의 변경 제안을 만든다. get_mail의 candidates에서 실제 ID·현재 본문을 확인한다.
    요청과 무관한 문장을 보존한다. 후보가 여러 개면 선택받는다. 승인 후 초안만 저장한다.
    """
    return task("mail", "edit_reply", **ReplyEditInput.model_validate(inputs).model_dump(mode="json"))


@tool
def prepare_reply(thread_id: str) -> dict:
    """본인 수신 메일의 기존 분석 그래프로 답장 후보를 생성한다. 발송하지 않는다."""
    return task("mail", "draft", thread_id=thread_id)


@tool
def get_document(kind: DocumentKind, document_id: Positive) -> dict:
    """본인의 PI/PO/CI/PL 문서와 현재 revision을 조회한다."""
    return task("documents", "get", kind=kind, document_id=document_id)


@tool(args_schema=TradePriceSearch)
def search_trade_prices(**inputs) -> dict:
    """등록된 단가표의 품목 판매가·매입가를 확인한다. 계약서 검색이나 문서 작성과 별개다.
    반환된 unit_price·currency·unit·price_basis를 그대로 쓴다. scope가 common이면 공통 단가라고 알린다.
    거래처 후보가 여러 개면 선택받고, 품목 후보가 여러 개면 실제 SKU와 조건을 표시한다.
    """
    return task("documents", "search_trade_prices", **TradePriceSearch.model_validate(inputs).model_dump(mode="json"))


@tool(args_schema=CounterpartySearch)
def search_counterparties(**inputs) -> dict:
    """등록된 거래처 카드에서 담당자·이메일·전화·주소를 확인한다. 이름·별칭·이메일을 검색한다.
    여러 카드가 일치하면 후보를 보여주고 선택을 받는다. 빈 필드를 추측하지 않는다.
    """
    return task("documents", "search_counterparties", **CounterpartySearch.model_validate(inputs).model_dump(mode="json"))


@tool(args_schema=DraftDocumentSearch)
def list_trade_drafts(**inputs) -> dict:
    """작성 중인 본인의 PI·PO·CI·PL과 현재 입력 누락을 확인한다. 현재 버전이 발급된 문서는 목록에서 제외한다.
    결과의 실제 누락·버전과 이어 쓰기 링크를 사용한다.
    """
    return task("documents", "search_drafts", **DraftDocumentSearch.model_validate(inputs).model_dump(mode="json"))


@tool(args_schema=IssuedDocumentSearch)
def search_trade_documents(**inputs) -> dict:
    """발급된 본인 PI/PO/CI/PL을 찾는다. 종류, 문서번호, 거래처명, 발급일(한국 날짜, 양끝 포함) 중
    최소 한 조건을 넣는다. issued_from/issued_to는 YYYY-MM-DD다. 발급 당시 버전과 다운로드 파일을 반환한다."""
    return task("documents", "search_issued", **IssuedDocumentSearch.model_validate(inputs).model_dump(mode="json"))


@tool(args_schema=KnowledgeDocumentSearch)
def search_knowledge_documents(**inputs) -> dict:
    """문서함에 업로드한 본인 파일을 찾거나 조항을 검색한다. 파일 열기에는 filename만, 내용 질문에는 query와
    알고 있는 filename 또는 검색 결과의 document_id를 넣는다. 질의는 한국어·영어 검색에 쓰인다.
    파일명이 같을 때는 반환된 후보에서 고르고, 실제 조항과 sources에 있는 페이지를 인용한다."""
    return task("documents", "search_knowledge", **KnowledgeDocumentSearch.model_validate(inputs).model_dump(mode="json"))


@tool
def document_schema(kind: DocumentKind) -> dict:
    """문서 values의 실제 입력 스키마를 확인한다. 구조를 추측하지 말고 작성 전에 조회한다."""
    return task("documents", "schema", kind=kind)


@tool(args_schema=DocumentInput)
def prepare_document(**inputs) -> dict:
    """PI/PO/CI/PL 초안을 작성/수정한다. 원문 text 또는 확인된 values를 사용한다.
    기존 문서 수정에는 document_id와 최신 revision이 필요하다. 단가와 근거를 지어내지 않는다.
    """
    inputs = deepcopy(inputs)
    for item in (inputs.get("values") or {}).get("items", []):
        if isinstance(item, dict):
            item["confirm_price_override"] = False
    return task("documents", "draft", **inputs)


@tool
def prepare_issue(kind: DocumentKind, document_id: Positive, revision: Positive,
                  formats: list[Literal["pdf", "xlsx"]] | None = None) -> dict:
    """현재 문서 버전의 PDF/XLSX 발급을 제안한다. 실제 발급은 사용자 승인 후 수행한다."""
    return task("documents", "issue", kind=kind, document_id=document_id, revision=revision,
                formats=formats or ["pdf", "xlsx"])


@tool
def prepare_packing(document_id: Positive, revision: Positive) -> dict:
    """PL 포장 합계 확인을 요청한다. 최종 파일 발급 승인은 별도 prepare_issue로 받는다."""
    return task("documents", "approve_packing", kind="PL", document_id=document_id, revision=revision)


@tool
def prepare_send(candidate_id: Positive, file_ids: list[str] | None = None) -> dict:
    """답장 발송을 준비한다. 사용자가 후보를 직접 선택하고 최종 승인해야 전송된다.
    file_ids는 실제 발급 결과만 사용한다. 기존 견적 후보에는 별도 첨부를 섞지 않는다.
    """
    return task("mail", "send", candidate_id=candidate_id, file_ids=file_ids or [])


@tool
def list_calendar_events(
    start: Annotated[AwareDatetime, Field(description="요청 기간의 시작. ISO 8601 오프셋을 포함한다. 날짜만 있으면 현지 자정.")],
    end: Annotated[AwareDatetime, Field(description="요청 기간의 끝. ISO 8601 오프셋을 포함한다. 하루 조회는 다음날 자정.")],
) -> dict:
    """이미 등록된 기본 Google 캘린더의 일정 제목과 시각을 조회한다. '내일 일정 뭐 있어?', '회의 몇 시야?'에 사용한다.
    최대 62일을 조회한다. 반환한 events의 제목·시작·종료를 사용한다. all_day는 종료일을 포함하지 않는다.
    total이 events 길이보다 크면 일부 표시임을 알리고, 빈 시간은 find_slots를 사용한다.
    """
    return task("calendar", "list_events", start=start.isoformat(), end=end.isoformat())


@tool(args_schema=CalendarMoveInput)
def prepare_move_calendar_event(**inputs) -> dict:
    """등록된 일정의 시각을 옮길 제안. 이번 요청의 list_calendar_events에서 대상 ID를 찾고, 유사 제목이면 사용자가 골라야 한다.
    사용자가 말한 새 시각을 전달한다. 기존 길이를 보존하며 충돌과 버전을 확인한 뒤 승인 카드를 만든다.
    """
    return task("calendar", "move_event", **CalendarMoveInput.model_validate(inputs).model_dump(mode="json"))


@tool(args_schema=CalendarEventSelection)
def prepare_cancel_calendar_event(**inputs) -> dict:
    """등록 일정의 취소를 제안한다. 이번 요청의 list_calendar_events에서 확인한 ID를 사용한다.
    반복 일정은 사용자가 지정한 한 회차만 취소한다. 최종 승인까지 Google 일정은 바뀌지 않는다.
    """
    return task("calendar", "cancel_event", **CalendarEventSelection.model_validate(inputs).model_dump(mode="json"))


@tool
def find_slots(start: str, end: str, timezone: str, duration_minutes: Positive,
               calendar_ids: Annotated[list[str], Field(min_length=1, max_length=32)],
               participants: list[str] | None = None, step_minutes: Positive | None = None,
               preferred_hours: list[int] | None = None) -> dict:
    """시간 범위에서 모든 캘린더가 비어 있는 회의 시간 후보를 찾는다. start/end는 시간대 offset을
    포함한 ISO 8601 시각(예: 2026-11-24T09:00:00+09:00), timezone은 IANA 이름(예: Asia/Seoul),
    calendar_ids는 확인할 캘린더 ID 목록이다. 반환된 slots 중 시간을 사용자가 고르게 하고
    create_event의 selected_start에는 그 선택만 사용한다."""
    return task("calendar", "find_slots", start=start, end=end, timezone=timezone,
                duration_minutes=duration_minutes, calendar_ids=calendar_ids,
                participants=participants or [], step_minutes=step_minutes or 15,
                preferred_hours=preferred_hours if preferred_hours is not None else [])


@tool
def create_event(start: str, end: str, timezone: str, duration_minutes: Positive,
                 calendar_ids: Annotated[list[str], Field(min_length=1, max_length=32)],
                 title: Annotated[str, Field(max_length=200)], selected_start: str,
                 target_calendar_id: str | None = None, participants: list[str] | None = None) -> dict:
    """선택한 시간(selected_start)에 일정을 등록한다. 실제 등록은 사용자 승인 뒤에 실행된다.
    캘린더가 여럿이면 target_calendar_id로 대상을 정하고, start/end는 조회 범위 그대로 전달한다."""
    return task("calendar", "create", start=start, end=end, timezone=timezone,
                duration_minutes=duration_minutes, calendar_ids=calendar_ids,
                title=title, selected_start=selected_start,
                target_calendar_id=target_calendar_id, participants=participants or [])


@tool
def ask_user(question: str) -> dict:
    """대상/조건이 모호하거나 사용자가 정해야 하는 사실이 부족하면 질문하고 답을 기다린다."""
    return {"question": question}


AGENT_TOOLS = {item.name: item for item in (search_mail, get_mail, list_mail_attachments, search_sent_mail,
    register_mail_followup, list_mail_followups, cancel_mail_followup, prepare_new_mail, prepare_reply, prepare_edit_reply, get_document, list_trade_drafts, search_trade_documents, search_trade_prices, search_counterparties,
    search_knowledge_documents, document_schema,
    prepare_document, prepare_issue, prepare_packing, prepare_send,
    list_calendar_events, find_slots, create_event, prepare_move_calendar_event, prepare_cancel_calendar_event, ask_user)}
