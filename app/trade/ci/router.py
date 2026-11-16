import re

from fastapi import APIRouter, Depends, Query, Request, Response

from app.auth.deps import current_user_id
from app.services.openai_keys import user_openai
from app.trade.common.api import require_write
from app.trade.ci import agent, operations
from app.trade.ci.models import CIInput, CIText, SourcePIPage, StandaloneCIInput
from app.trade.ci.rendering import render_ci_files
from app.trade.ci.repository import ci_repository
from app.trade.common.router import document_router
from app.trade.common.models import DocumentError, DocumentResult
from app.trade.common.router import TextInput

router = APIRouter()


@router.post("/api/trade/ci/extract-standalone", response_model=DocumentResult, status_code=201, tags=["CI"])
def extract_standalone(command: TextInput, request: Request, user_id: int = Depends(require_write)):
    repository = ci_repository(request.app.state.database, user_id)
    with user_openai(request.app.state.database, user_id, settings=request.app.state.settings,
                     cipher=request.app.state.google_access.cipher) as ai:
        try:
            return operations.extract_standalone(command.text, repository=repository, extractor=agent.extract_standalone_ci)
        except DocumentError:
            if ai.issue is not None:
                raise DocumentError(ai.issue.code, ai.issue.message, ai.issue.status_code) from None
            raise


@router.get("/api/trade/ci/source-pis", response_model=SourcePIPage, tags=["CI"])
def source_pis(request: Request, response: Response, cursor: str | None = None,
               source_pi_id: int | None = Query(default=None, ge=1, le=2147483647),
               source_revision: int | None = Query(default=None, ge=1, le=2147483647),
               user_id: int = Depends(current_user_id)):
    if ((source_pi_id is None) != (source_revision is None)
            or cursor is not None and source_pi_id is not None):
        raise DocumentError("INVALID_SOURCE_PI_QUERY", "PI ID와 버전을 함께 지정하고 cursor와 나누어 조회하세요", 422)
    pair = None
    if cursor is not None:
        if not re.fullmatch(r"[1-9][0-9]{0,9}:[1-9][0-9]{0,9}", cursor):
            raise DocumentError("INVALID_CURSOR", "올바른 PI 목록 cursor가 필요합니다", 422)
        pair = tuple(map(int, cursor.split(":")))
        if any(value > 2147483647 for value in pair):
            raise DocumentError("INVALID_CURSOR", "올바른 PI 목록 cursor가 필요합니다", 422)
    response.headers["Cache-Control"] = "private, no-store"
    return ci_repository(request.app.state.database, user_id).source_pis(
        cursor=pair, source_pi_id=source_pi_id, source_revision=source_revision)


# 정적 source-pis를 문서 ID 경로보다 먼저 등록한다.
router.include_router(document_router("CI", CIInput | StandaloneCIInput, operations, ci_repository,
                                     agent.extract_ci, render_ci_files, text_model=CIText))
