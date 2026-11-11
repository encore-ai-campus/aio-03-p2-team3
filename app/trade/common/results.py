from app.trade.common.models import DocumentResult
from app.trade.review_fields import missing_review_fields


def document_result(document: dict) -> DocumentResult:
    return DocumentResult(
        document_id=document["trade_doc_id"], document_type=document["document_type"],
        revision=document["revision"], status=document["status"], document=document,
        missing_fields=[".".join(map(str, item.path)) for item in missing_review_fields(document)],
        issues=[{"code": "DOCUMENT_INVALID", "message": message}
                for message in document.get("blocking_issues", [])])
