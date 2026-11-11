from app.trade.common.models import DocumentResult, Party
from app.trade.common.review_fields import missing_review_fields


def editable_values(document, fields, item_fields):
    values = {key: document.get(key) for key in fields if key not in {"items", "buyer", "seller"}}
    for role in ("buyer", "seller"):
        values[role] = {key: (document.get(role) or {}).get(key) for key in Party.model_fields}
    values["items"] = [{**{key: item[key] for key in item_fields
                          if key != "confirm_price_override" and item.get(key) is not None},
                        **({"confirm_price_override": item.get("price_override_confirmed") is True}
                           if "confirm_price_override" in item_fields else {})}
                       for item in document.get("items", [])]
    return values


def document_result(document: dict, inputs: dict | None = None) -> DocumentResult:
    return DocumentResult(
        document_id=document["trade_doc_id"], document_type=document["document_type"],
        revision=document["revision"], status=document["status"], document=document,
        input=inputs or {},
        missing_fields=[".".join(map(str, item.path)) for item in missing_review_fields(document)
                        if item.required],
        issues=[{"code": "DOCUMENT_INVALID", "message": message}
                for message in document.get("blocking_issues", [])])


def artifact_view(file) -> dict:
    return {"id": file.id, "file_format": file.file_format, "filename": file.filename,
            "media_type": file.media_type, "content_hash": file.content_hash,
            "download_url": f"/api/trade/files/{file.id}"}
