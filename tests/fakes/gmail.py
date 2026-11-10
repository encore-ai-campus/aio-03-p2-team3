"""Gmail SDK의 요청 모양·페이지·메일·첨부를 재현한다. 네트워크 호출은 없다."""

from base64 import urlsafe_b64encode
from copy import deepcopy

from app.clients.gmail import GoogleClient
from tests.fakes.google import FakeGoogle


def encoded(value):
    return urlsafe_b64encode(value.encode()).decode().rstrip("=")


def message(message_id="fake-message", thread_id="fake-thread", sender="sender@example.invalid",
            labels=None, body="테스트용 가상 문의입니다."):
    return {
        "id": message_id, "threadId": thread_id, "internalDate": "1794268800000",
        "labelIds": ["INBOX"] if labels is None else labels,
        "payload": {"mimeType": "text/plain", "headers": [
            {"name": "From", "value": sender}, {"name": "To", "value": "demo@example.invalid"},
            {"name": "Subject", "value": "가상 문의"},
            {"name": "Message-ID", "value": f"<{message_id}@example.invalid>"},
        ], "body": {"data": encoded(body)}},
    }


def history_page(*message_ids, history_id="1001", next_page=None):
    page = {"historyId": history_id, "history": [
        {"id": history_id, "messagesAdded": [{"message": {"id": value}} for value in message_ids]},
    ]}
    if next_page:
        page["nextPageToken"] = next_page
    return page


class _Request:
    def __init__(self, mailbox, kind, params, value):
        self.mailbox, self.kind, self.params, self.value = mailbox, kind, params, value

    def execute(self, *, num_retries):
        self.mailbox.calls.append((self.kind, self.params, num_retries))
        if isinstance(self.value, Exception):
            raise self.value
        return deepcopy(self.value)


class _History:
    def __init__(self, mailbox):
        self.mailbox = mailbox

    def list(self, **params):
        return _Request(self.mailbox, "history", params, self.mailbox.pages[params.get("pageToken")])


class _Attachments:
    def __init__(self, mailbox):
        self.mailbox = mailbox

    def get(self, **params):
        value = self.mailbox.attachment_data[(params["messageId"], params["id"])]
        return _Request(self.mailbox, "attachment", params, value)


class _Messages:
    def __init__(self, mailbox):
        self.mailbox = mailbox

    def get(self, **params):
        return _Request(self.mailbox, "message", params, self.mailbox.raw_messages[params["id"]])

    def attachments(self):
        return _Attachments(self.mailbox)


class Mailbox:
    def __init__(self):
        self.pages = {None: history_page("fake-message")}
        self.raw_messages = {"fake-message": message()}
        self.attachment_data = {}
        self.calls = []

    def users(self):
        return self

    def history(self):
        return _History(self)

    def messages(self):
        return _Messages(self)


class FakeGmailGoogle(FakeGoogle, GoogleClient):
    def __init__(self):
        super().__init__()
        self.mailbox = Mailbox()
        self.verify_error = None

    def gmail(self, access_token):
        self.calls.append(("gmail", access_token))
        return self.mailbox

    def verify_push_token(self, token, audience, service_account):
        self.calls.append(("verify", token, audience, service_account))
        if self.verify_error:
            raise self.verify_error
