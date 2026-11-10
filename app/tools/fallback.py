"""한도 오류 때 쓰는 기본 답장 틀(계약 3.2절).

LLM을 부르지 않고 고정 문구로 후보 1개를 만든다. '확인 필요' 표시를 달아
사용자가 고쳐 보내게 한다. 문구는 메일 분석·후보 작업(8)에서 다듬을 수 있다.
"""

from app.graph.state import EmailMessage, ReplyCandidate

_BODIES = {
    "general": "메일 잘 받았습니다. 내용을 확인한 뒤 다시 연락드리겠습니다.",
    "followup": "메일 잘 받았습니다. 견적서 작성에 필요한 내용을 확인한 뒤 다시 연락드리겠습니다.",
    "quote": "요청하신 견적서를 확인한 뒤 보내 드리겠습니다.",
}


def fallback_candidates(reply_mode: str, email: EmailMessage) -> list[ReplyCandidate]:
    subject = email["subject"] or ""
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}".strip()
    return [{
        "label": "기본 답장(AI 후보를 만들지 못함)",
        "subject": subject,
        "body": _BODIES.get(reply_mode, _BODIES["general"]),
        "kind": reply_mode if reply_mode in _BODIES else "general",
        "asks_fields": [],
        "needs_review": True,
        "notice": "rate_limit",
    }]
