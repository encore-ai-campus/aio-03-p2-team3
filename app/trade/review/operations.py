"""최종 검토의 내용·버전·선택을 확인한다. LLM과 메일 발송을 호출하지 않는다."""
from copy import deepcopy
from hashlib import sha256
import json
from typing import Callable

from app.trade.common.models import DocumentError
from app.trade.review.models import Branding, Decision, RenderedFile, ReviewRepository, ReviewRequest


def content_hash(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def propose(document_id: int, request: ReviewRequest, *, repository: ReviewRepository,
            check_document: Callable[[dict], None]) -> dict:
    document = repository.document(document_id)
    if document["revision"] != request.revision:
        raise DocumentError("REVISION_CONFLICT", "최신 문서를 다시 확인하세요")
    if document["status"] != "ready" or document.get("blocking_issues"):
        raise DocumentError("DOCUMENT_NOT_READY", "빠진 항목과 오류를 먼저 확인하세요")
    check_document(document)
    branding = repository.branding()
    payload = {"document_id": document_id, "document_type": document["document_type"],
               "revision": request.revision, "document": deepcopy(document),
               "formats": sorted(set(request.formats)),
               "seal_sha256": sha256(branding.seal).hexdigest(),
               "logo_sha256": sha256(branding.logo).hexdigest() if branding.logo else None}
    return repository.create(document_id, request.revision, payload, content_hash(payload), branding)


def check_decision(proposal_id: str, document_id: int, decision: Decision, *, repository: ReviewRepository) -> dict:
    proposal = repository.get(proposal_id)
    if proposal["document_id"] != document_id:
        raise DocumentError("PROPOSAL_NOT_FOUND", "검토 제안을 찾을 수 없습니다", 404)
    if (proposal["revision"] != decision.revision or proposal["content_hash"] != decision.content_hash
            or content_hash(proposal["payload"]) != proposal["content_hash"]):
        raise DocumentError("PROPOSAL_MISMATCH", "확인한 내용과 검토 제안이 일치하지 않습니다")
    return proposal


def get_proposal(proposal_id: str, document_id: int, *, repository: ReviewRepository) -> dict:
    proposal = repository.get(proposal_id)
    if proposal["document_id"] != document_id:
        raise DocumentError("PROPOSAL_NOT_FOUND", "검토 제안을 찾을 수 없습니다", 404)
    return proposal


def download_file(file_id: str, *, repository: ReviewRepository) -> dict:
    return repository.file(file_id)


def decide(proposal_id: str, document_id: int, decision: Decision, *, repository: ReviewRepository,
           renderer: Callable[[dict, Branding], list[RenderedFile]]) -> dict:
    proposal = check_decision(proposal_id, document_id, decision, repository=repository)
    if decision.action == "cancel":
        return repository.cancel(proposal_id, decision.revision, decision.content_hash)
    if decision.action != "approve":
        raise DocumentError("MODIFIED_DOCUMENT_REQUIRED", "수정할 문서 내용을 함께 보내세요", 422)
    if proposal["status"] == "approved":
        return proposal
    if proposal["status"] != "pending":
        raise DocumentError("PROPOSAL_CONFLICT", "현재 대기 중인 검토 제안을 다시 확인하세요")
    document = repository.document(document_id)
    if document["revision"] != decision.revision or document["status"] != "ready":
        raise DocumentError("REVISION_CONFLICT", "최신 문서를 다시 확인하세요")
    branding = proposal["branding"]
    if (sha256(branding.seal).hexdigest() != proposal["payload"]["seal_sha256"]
            or (sha256(branding.logo).hexdigest() if branding.logo else None) != proposal["payload"]["logo_sha256"]):
        raise DocumentError("PROPOSAL_MISMATCH", "검토한 회사 이미지와 저장된 이미지가 일치하지 않습니다")
    try:
        files = renderer(proposal["payload"], proposal["branding"])
    except (ValueError, ArithmeticError, TypeError) as error:
        raise DocumentError("RENDER_FAILED", "파일을 만들지 못했습니다. 문서와 회사 이미지를 확인하세요", 422) from error
    if (sorted(file.file_format for file in files) != sorted(proposal["payload"]["formats"])
            or any(not file.content for file in files)):
        raise DocumentError("RENDER_FAILED", "요청한 형식의 파일을 모두 만들지 못했습니다", 422)
    return repository.approve(proposal_id, decision.revision, decision.content_hash, files)
