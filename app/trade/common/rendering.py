"""승인된 스냅숏만 읽어 PDF/XLSX bytes를 만든다. 저장·계산·외부 호출은 하지 않는다."""
from app.trade.common.pdf import render_trade_document
from app.trade.common.renderers import _xlsx_bytes
from app.trade.review.models import Branding, RenderedFile


def render_approved_files(payload: dict, branding: Branding) -> list[RenderedFile]:
    document = {**payload["document"], "status": "issued"}
    stem = f"{document['doc_no']}-r{payload['revision']}"
    files = []
    for file_format in payload["formats"]:
        if file_format == "pdf":
            content = render_trade_document(document, document.get("bank"), logo=branding.logo,
                                            seal=branding.seal, issued_on=document["issue_date"],
                                            footer_label="APPROVED DOCUMENT")
            media_type = "application/pdf"
        elif file_format == "xlsx":
            content = _xlsx_bytes(document, document.get("bank"), seal=branding.seal)
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            raise ValueError("지원하지 않는 파일 형식")
        files.append(RenderedFile(file_format, f"{stem}.{file_format}", media_type, content))
    return files
