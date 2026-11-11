"""React용 PI API. 화면 코드와 메일 발송을 포함하지 않는다."""
from fastapi import APIRouter, Depends, Request
from pydantic import Field, model_validator

from app.trade.api import require_write
from app.trade.common.models import DocumentResult, DocumentSummary, InputModel
from app.trade.pi import agent, operations
from app.trade.pi.models import PIInput
from app.trade.pi.rendering import render_pi_files
from app.trade.pi.repository import pi_repository
from app.trade.review import operations as review
from app.trade.review.models import Decision, ReviewRequest, ReviewView
from app.trade.review.repository import SQLReviews
from app.web.deps import current_user_id

router = APIRouter(prefix="/api/trade/pi", tags=["PI"])


class PIRevision(InputModel):
    revision: int = Field(ge=1, strict=True)
    document: PIInput


class PIText(InputModel):
    text: str = Field(min_length=1, max_length=20000)


class PIDecision(Decision):
    document: PIInput | None = None

    @model_validator(mode="after")
    def check_modified_document(self):
        if (self.action == "modify") != (self.document is not None):
            raise ValueError("수정 선택에만 새 문서 내용을 함께 보내세요")
        return self


def repositories(request, user_id):
    database = request.app.state.database
    return pi_repository(database, user_id), SQLReviews(database, user_id, "PI")


@router.get("", response_model=list[DocumentSummary])
def list_documents(request: Request, user_id: int = Depends(current_user_id)):
    repository, _ = repositories(request, user_id)
    return operations.list_pi(repository=repository)


@router.post("", response_model=DocumentResult, status_code=201)
def create(command: PIInput, request: Request, user_id: int = Depends(require_write)):
    repository, _ = repositories(request, user_id)
    return operations.create_pi(command, repository=repository)


@router.post("/extract", response_model=DocumentResult, status_code=201)
def extract(command: PIText, request: Request, user_id: int = Depends(require_write)):
    repository, _ = repositories(request, user_id)
    return operations.extract_pi(command.text, repository=repository, extractor=agent.extract_pi)


@router.get("/{document_id}", response_model=DocumentResult)
def get_document(document_id: int, request: Request, user_id: int = Depends(current_user_id)):
    repository, _ = repositories(request, user_id)
    return operations.get_pi(document_id, repository=repository)


@router.get("/{document_id}/versions/{revision}")
def get_version(document_id: int, revision: int, request: Request, user_id: int = Depends(current_user_id)):
    repository, _ = repositories(request, user_id)
    return operations.get_pi_version(document_id, revision, repository=repository)


@router.put("/{document_id}", response_model=DocumentResult)
def replace_document(document_id: int, command: PIRevision, request: Request,
                      user_id: int = Depends(require_write)):
    repository, _ = repositories(request, user_id)
    return operations.revise_pi(document_id, command.revision, command.document, repository=repository)


@router.post("/{document_id}/reviews", response_model=ReviewView, status_code=201)
def propose(document_id: int, command: ReviewRequest, request: Request,
            user_id: int = Depends(require_write)):
    _, reviews = repositories(request, user_id)
    return review.propose(document_id, command, repository=reviews, check_document=operations.check_pi_for_review)


@router.get("/{document_id}/reviews/{proposal_id}", response_model=ReviewView)
def get_review(document_id: int, proposal_id: str, request: Request,
               user_id: int = Depends(current_user_id)):
    _, reviews = repositories(request, user_id)
    return review.get_proposal(proposal_id, document_id, repository=reviews)


@router.post("/{document_id}/reviews/{proposal_id}/decisions", response_model=ReviewView | DocumentResult)
def decide(document_id: int, proposal_id: str, command: PIDecision, request: Request,
           user_id: int = Depends(require_write)):
    repository, reviews = repositories(request, user_id)
    if command.action == "modify":
        previous_proposal = review.check_decision(proposal_id, document_id, command, repository=reviews)
        revised = operations.revise_pi(document_id, command.revision, command.document, repository=repository,
                                       review_reference=(proposal_id, command.content_hash))
        if revised.status != "ready":
            return revised
        return review.propose(document_id, ReviewRequest(revision=revised.revision, formats=previous_proposal["payload"]["formats"]), repository=reviews,
                              check_document=operations.check_pi_for_review)
    return review.decide(proposal_id, document_id, command, repository=reviews, renderer=render_pi_files)
