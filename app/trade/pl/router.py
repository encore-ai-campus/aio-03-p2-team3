from fastapi import Depends, Request

from app.trade.api import require_write
from app.trade.common.models import DocumentResult
from app.trade.common.rendering import render_approved_files
from app.trade.common.router import document_router
from app.trade.pl import agent, operations
from app.trade.pl.models import PLInput, PackingDecision
from app.trade.pl.repository import pl_repository
from app.web.deps import current_user_id

router = document_router("PL", PLInput, operations, pl_repository, agent.extract_pl, render_approved_files)


@router.get("/{document_id}/packing-review")
def packing_review(document_id: int, request: Request, user_id: int = Depends(current_user_id)):
    return operations.packing_review(document_id, repository=pl_repository(request.app.state.database, user_id))


@router.post("/{document_id}/packing-review/decisions", response_model=DocumentResult)
def packing_decision(document_id: int, command: PackingDecision, request: Request,
                     user_id: int = Depends(require_write)):
    return operations.decide_packing(document_id, command, repository=pl_repository(request.app.state.database, user_id))
