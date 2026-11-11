from app.trade.common.rendering import render_approved_files
from app.trade.common.router import document_router
from app.trade.po import agent, operations
from app.trade.po.models import POInput
from app.trade.po.repository import po_repository

router = document_router("PO", POInput, operations, po_repository, agent.extract_po, render_approved_files)
