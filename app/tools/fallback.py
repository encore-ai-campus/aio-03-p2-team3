"""한도 오류 때 쓰는 기본 답장 틀 후보(계약 3.2절, 계획 8절).

후보의 `notice`에는 안내 종류 키(`rate_limit`)를 두고, 화면은 `NOTICE_MESSAGES`로 문구를 보여 준다.
"""

from app.graph.state import EmailMessage, ReplyCandidate

NOTICE_MESSAGES = {
    "rate_limit": "한도 초과로 AI 후보를 만들지 못했습니다. 기본 답장 틀을 확인해 고친 뒤 보내 주세요.",
}

FALLBACK_LABEL = "기본 답장(확인 필요)"
FALLBACK_BODY = (
    "안녕하세요.\n\n"
    "보내 주신 메일 잘 받았습니다. 내용을 확인한 뒤 다시 연락드리겠습니다.\n\n"
    "감사합니다."
)


def reply_subject(email: EmailMessage) -> str:
    subject = (email.get("subject") or "").strip()
    return subject if subject.lower().startswith("re:") else f"Re: {subject}".strip()


def with_signature(body: str, preferences: dict | None) -> str:
    signature = (preferences or {}).get("signature")
    if isinstance(signature, str) and signature.strip() and signature.strip() not in body:
        return f"{body}\n\n{signature.strip()}"
    return body


def fallback_candidates(email: EmailMessage, *, kind="general", asks_fields=None,
                        preferences: dict | None = None, notice="rate_limit") -> list[ReplyCandidate]:
    return [ReplyCandidate(
        label=FALLBACK_LABEL, subject=reply_subject(email),
        body=with_signature(FALLBACK_BODY, preferences), kind=kind,
        asks_fields=list(asks_fields or []), needs_review=True, notice=notice,
    )]
