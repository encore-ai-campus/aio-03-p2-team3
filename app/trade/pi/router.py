"""React용 PI API. 화면 코드와 메일 발송을 포함하지 않는다."""
from app.trade.common.router import document_router
from app.trade.pi import agent, operations
from app.trade.pi.models import PIInput
from app.trade.pi.rendering import render_pi_files
from app.trade.pi.repository import pi_repository

router = document_router("PI", PIInput, operations, pi_repository, agent.extract_pi, render_pi_files)
