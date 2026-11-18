"""메일함 업무 경계. 읽기·수동 처리·발송은 본인 데이터에만 적용한다."""
from app.services import approval
from app.services.gmail_push import _mailbox_lock
from app.services.mail_processing import process_saved
from app.services.auth import get_access_token
from app.clients.gmail import GoogleError
from email.utils import getaddresses
from app.quote.calc import fill_prices
from app.quote.pdf import render_quote_pdf


class MailError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def read_thread(store, owner, thread_id):
    thread = store.thread(owner, thread_id)
    if thread is None:
        raise MailError(404, "not_found", "메일을 찾을 수 없습니다.")
    return thread


def read_quote(store, owner, quote_id):
    quote = store.quote(owner, quote_id)
    if quote is None:
        raise MailError(404, "not_found", "견적서를 찾을 수 없습니다.")
    return quote


def complete_quote_prices(store, owner, quote_id, prices):
    quote = read_quote(store, owner, quote_id)
    if quote["status"] != "needs_price":
        raise MailError(409, "quote_changed", "견적서 상태가 바뀌었습니다. 최신 내용을 확인해 주세요.")
    try:
        if any(not k.isdecimal() or not v.isdecimal() for k, v in prices.items()):
            raise ValueError()
        values = {int(k): int(v) for k, v in prices.items()}
        if len(values) != len(prices):
            raise ValueError()
        draft = fill_prices(quote["draft"], values)
    except (ValueError, TypeError):
        raise MailError(400, "invalid_prices", "빠진 단가를 모두 0 이상의 원 단위 정수로 입력해 주세요.") from None
    if not store.complete_quote(owner, quote_id, quote["draft"], draft):
        raise MailError(409, "quote_changed", "견적서가 변경되었습니다. 최신 내용을 확인해 주세요.")
    return {"status": draft["status"]}


def quote_pdf(store, owner, quote_id):
    return render_quote_pdf(read_quote(store, owner, quote_id)["draft"])


def process_manually(access, store, owner, row_id, *, graph=None):
    message_id = store.message_key(owner, row_id)
    if message_id is None:
        raise MailError(404, "not_found", "메일을 찾을 수 없습니다.")
    if not store.connected(owner):
        raise MailError(409, "gmail_disconnected", "Gmail 연결을 확인한 뒤 다시 시도해 주세요.")
    with _mailbox_lock(access.database, owner):
        process_saved(access, store, owner, message_id, graph=graph, force=True)
    row = store.get(owner, message_id)
    return {"thread_id": row["thread_id"], "status": row["status"]}


def send_candidate(access, store, owner, candidate_id, *, storage=None, revision=None):
    candidate = store.candidate(owner, candidate_id)
    if candidate is None:
        raise MailError(404, "not_found", "답장 후보를 찾을 수 없습니다.")
    document = candidate["document"]
    if candidate["trade_doc_id"]:
        if not document or revision != document["revision"]:
            raise MailError(409, "document_changed", "문서가 변경되었습니다. 최신 문서를 다시 확인해 주세요.")
        result = approval.send_approved_trade_document(owner, candidate["trade_doc_id"], candidate_id,
                         access=access, storage=storage, expected_revision=revision)
    elif candidate["quote_id"]:
        result = approval.send_approved_quote(owner, candidate["quote_id"], candidate_id, access=access)
    elif candidate["kind"] == "quote":
        raise MailError(409, "document_missing", "관련 문서를 확인해 주세요.")
    else:
        result = approval.send_approved_candidate(owner, candidate_id, access=access)
    if result.outcome == "not_found":
        raise MailError(404, "not_found", "답장 후보를 찾을 수 없습니다.")
    return {"outcome": result.outcome, "thread_id": result.thread_id}


def preview_candidate(access, store, owner, candidate_id):
    candidate = store.candidate(owner, candidate_id)
    if candidate is None:
        raise MailError(404, "not_found", "답장 후보를 찾을 수 없습니다.")
    try:
        gmail = access.google.gmail(get_access_token(access, owner))
        headers = access.google.get_reply_headers(gmail, candidate["source_message_id"])
    except GoogleError:
        raise MailError(503, "preview_failed", "발송 대상을 확인하지 못했습니다. Gmail 연결을 확인해 주세요.") from None
    recipients = [address for _, address in getaddresses([headers.get("reply-to") or headers.get("from", "")]) if address]
    if not recipients:
        raise MailError(409, "recipient_missing", "답장 받을 주소를 확인할 수 없습니다.")
    return {**candidate, "to_addrs": recipients}
