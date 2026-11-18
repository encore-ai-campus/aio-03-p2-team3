"""모델용 업무 입구. 실행은 기존 master의 prepare/승인/execute 경계를 지난다."""
from typing import Annotated, Literal
from copy import deepcopy

from langchain_core.tools import tool
from pydantic import Field

from app.graph.documents.schemas import DocumentInput, DocumentKind, IssuedDocumentSearch, KnowledgeDocumentSearch

Positive = Annotated[int, Field(gt=0, strict=True)]


def task(domain, operation, **inputs):
    return {"domain": domain, "operation": operation, "inputs": inputs}


@tool
def search_mail(query: Annotated[str, Field(max_length=200)] = "", cursor: Positive | None = None) -> dict:
    """본인 앱에 수집된 메일을 제목/발신자로 검색한다. 다음 페이지는 반환한 cursor를 사용한다."""
    return task("mail", "search", query=query, cursor=cursor)


@tool
def get_mail(thread_id: str) -> dict:
    """검색 결과의 실제 thread_id로 원문과 저장된 답장 후보를 조회한다."""
    return task("mail", "query", thread_id=thread_id)


@tool
def prepare_reply(thread_id: str) -> dict:
    """본인 수신 메일의 기존 분석 그래프로 답장 후보를 생성한다. 발송하지 않는다."""
    return task("mail", "draft", thread_id=thread_id)


@tool
def get_document(kind: DocumentKind, document_id: Positive) -> dict:
    """본인의 PI/PO/CI/PL 문서와 현재 revision을 조회한다."""
    return task("documents", "get", kind=kind, document_id=document_id)


@tool(args_schema=IssuedDocumentSearch)
def search_trade_documents(**inputs) -> dict:
    """발급된 본인 PI/PO/CI/PL을 찾는다. 종류, 문서번호, 거래처명, 발급일(한국 날짜, 양끝 포함) 중
    최소 한 조건을 넣는다. issued_from/issued_to는 YYYY-MM-DD다. 발급 당시 버전과 다운로드 파일을 반환한다."""
    return task("documents", "search_issued", **IssuedDocumentSearch.model_validate(inputs).model_dump(mode="json"))


@tool(args_schema=KnowledgeDocumentSearch)
def search_knowledge_documents(**inputs) -> dict:
    """문서함에 업로드한 본인 파일을 찾거나 조항을 검색한다. 파일 열기에는 filename만, 내용 질문에는 query와
    알고 있는 filename 또는 검색 결과의 document_id를 넣는다. 파일명만 같을 때는 반환된 후보에서 고른다."""
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
def ask_user(question: str) -> dict:
    """대상/조건이 모호하거나 사용자가 정해야 하는 사실이 부족하면 질문하고 답을 기다린다."""
    return {"question": question}


AGENT_TOOLS = {item.name: item for item in (search_mail, get_mail, prepare_reply, get_document, search_trade_documents,
    search_knowledge_documents, document_schema,
    prepare_document, prepare_issue, prepare_packing, prepare_send, ask_user)}
