"""네 문서가 실제 공유하는 HTTP 흐름. 업무 규칙과 AI 진입점은 도메인에서 주입한다."""
from fastapi import APIRouter, Depends, Request
from pydantic import Field, create_model, model_validator

from app.trade.common.api import require_write
from app.trade.common import operations as common
from app.trade.common.models import DocumentError, DocumentResult, DocumentSummary, InputModel
from app.files.sources import SourcesLink, link_document_sources
from app.trade.review import operations as review
from app.trade.review.models import Decision, ReviewRequest, ReviewView
from app.trade.review.repository import SQLReviews
from app.services.openai_keys import user_openai
from app.web.deps import current_user_id


class TextInput(InputModel):
    text: str = Field(min_length=1, max_length=20000)


class Modification(Decision):
    @model_validator(mode="after")
    def check_modified_document(self):
        if (self.action == "modify") != (self.document is not None):
            raise ValueError("수정 선택에만 새 문서 내용을 함께 보내세요")
        return self


def document_router(kind, input_model, operations, repository_factory, extractor, renderer, *, text_model=TextInput):
    router = APIRouter(prefix=f"/api/trade/{kind.lower()}", tags=[kind])
    Revision = create_model(f"{kind}Revision", __base__=InputModel,
                            revision=(int, Field(ge=1, strict=True)), document=(input_model, ...))
    Choice = create_model(f"{kind}Decision", __base__=Modification, document=(input_model | None, None))

    def repositories(request, user_id):
        database = request.app.state.database
        return repository_factory(database, user_id), SQLReviews(database, user_id, kind,
                                                                 storage=request.app.state.storage)

    @router.get("", response_model=list[DocumentSummary])
    def list_documents(request: Request, user_id: int = Depends(current_user_id)):
        repository, _ = repositories(request, user_id)
        return common.list_documents(repository=repository)

    @router.post("", response_model=DocumentResult, status_code=201)
    def create(command: input_model, request: Request, user_id: int = Depends(require_write)):
        repository, _ = repositories(request, user_id)
        return operations.create(command, repository=repository)

    @router.post("/extract", response_model=DocumentResult, status_code=201)
    def extract(command: text_model, request: Request, user_id: int = Depends(require_write)):
        repository, _ = repositories(request, user_id)
        values = command.model_dump()
        text = values.pop("text")
        with user_openai(request.app.state.database, user_id, settings=request.app.state.settings,
                         cipher=request.app.state.google_access.cipher) as ai:
            try:
                return operations.extract(text, repository=repository, extractor=extractor, **values)
            except DocumentError:
                if ai.issue is not None:
                    raise DocumentError(ai.issue.code, ai.issue.message, ai.issue.status_code) from None
                raise

    @router.get("/{document_id}", response_model=DocumentResult)
    def get_document(document_id: int, request: Request, user_id: int = Depends(current_user_id)):
        repository, _ = repositories(request, user_id)
        return common.get_document(document_id, repository=repository, result=operations.result)

    @router.get("/{document_id}/versions/{revision}")
    def get_version(document_id: int, revision: int, request: Request, user_id: int = Depends(current_user_id)):
        repository, _ = repositories(request, user_id)
        return common.get_version(document_id, revision, repository=repository)

    @router.put("/{document_id}", response_model=DocumentResult)
    def replace_document(document_id: int, command: Revision, request: Request, user_id: int = Depends(require_write)):
        repository, _ = repositories(request, user_id)
        return operations.revise(document_id, command.revision, command.document, repository=repository)

    @router.put("/{document_id}/sources")
    def replace_sources(document_id: int, command: SourcesLink, request: Request,
                        user_id: int = Depends(require_write)):
        # 문서 출처 연결(CONTRACT 16.3절): 파일 ID 목록·기대 revision 검증 후 새 revision·대기 검토 무효화.
        return link_document_sources(request.app.state.database, user_id, kind, document_id,
                                     command.revision, command.file_ids)

    @router.post("/{document_id}/reviews", response_model=ReviewView, status_code=201)
    def propose(document_id: int, command: ReviewRequest, request: Request, user_id: int = Depends(require_write)):
        _, reviews = repositories(request, user_id)
        return review.propose(document_id, command, repository=reviews, check_document=operations.check)

    @router.get("/{document_id}/reviews/{proposal_id}", response_model=ReviewView)
    def get_review(document_id: int, proposal_id: str, request: Request, user_id: int = Depends(current_user_id)):
        _, reviews = repositories(request, user_id)
        return review.get_proposal(proposal_id, document_id, repository=reviews)

    @router.post("/{document_id}/reviews/{proposal_id}/decisions", response_model=ReviewView | DocumentResult)
    def decide(document_id: int, proposal_id: str, command: Choice, request: Request, user_id: int = Depends(require_write)):
        repository, reviews = repositories(request, user_id)
        if command.action == "modify":
            previous = review.check_decision(proposal_id, document_id, command, repository=reviews)
            revised = operations.revise(document_id, command.revision, command.document, repository=repository,
                                         review_reference=(proposal_id, command.content_hash))
            if revised.status != "ready":
                return revised
            return review.propose(document_id, ReviewRequest(revision=revised.revision, formats=previous["payload"]["formats"]),
                                  repository=reviews, check_document=operations.check)
        return review.decide(proposal_id, document_id, command, repository=reviews, renderer=renderer)

    return router
