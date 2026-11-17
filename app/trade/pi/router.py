"""React용 PI API. 화면 코드와 메일 발송을 포함하지 않는다."""
from fastapi import Depends, Request
from pydantic import Field

from app.trade.common.api import require_write
from app.trade.common.models import DocumentResult, InputModel
from app.trade.common.router import document_router
from app.trade.pi import agent, operations
from app.trade.pi.models import PIInput
from app.trade.pi.rendering import render_pi_files
from app.trade.pi.repository import pi_repository

router = document_router("PI", PIInput, operations, pi_repository, agent.extract_pi, render_pi_files)


class IssuerRefresh(InputModel):
    revision: int = Field(ge=1, strict=True)


@router.post("/{document_id}/refresh-issuer", response_model=DocumentResult)
def refresh_issuer(document_id: int, command: IssuerRefresh, request: Request,
                   user_id: int = Depends(require_write)):
    repository = pi_repository(request.app.state.database, user_id)
    return operations.refresh_issuer(document_id, command.revision, repository=repository)
