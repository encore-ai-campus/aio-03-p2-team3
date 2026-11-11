from app.trade.ci import agent, operations
from app.trade.ci.models import CIInput, CIText
from app.trade.ci.rendering import render_ci_files
from app.trade.ci.repository import ci_repository
from app.trade.common.router import document_router

router = document_router("CI", CIInput, operations, ci_repository, agent.extract_ci, render_ci_files, text_model=CIText)
