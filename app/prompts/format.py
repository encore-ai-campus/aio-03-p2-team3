"""프롬프트에 넣을 메일·기억·선호를 짧은 글로 바꾸는 도우미(8절)."""

import json

EMAIL_BODY_LIMIT = 4000
RECENT_BODY_LIMIT = 600


def _clip(text: str | None, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + " …(생략)"


def email_text(email: dict) -> str:
    sender = email.get("from_addr") or ""
    if email.get("from_name"):
        sender = f"{email['from_name']} <{sender}>"
    return (
        f"보낸 사람: {sender}\n제목: {email.get('subject') or ''}\n"
        f"본문:\n{_clip(email.get('body_text'), EMAIL_BODY_LIMIT)}"
    )


def thread_context_text(context: dict | None) -> str:
    if not context:
        return "없음"
    lines = []
    if context.get("summary"):
        lines.append(f"요약: {context['summary']}")
    if context.get("confirmed_terms"):
        lines.append("확인한 조건: " + json.dumps(context["confirmed_terms"], ensure_ascii=False))
    if context.get("last_result"):
        lines.append("직전 결과·답 안 된 항목: " + json.dumps(context["last_result"], ensure_ascii=False))
    for message in context.get("recent_messages") or []:
        who = "보낸 메일" if message.get("direction") == "out" else "받은 메일"
        lines.append(f"- {who} / {message.get('subject') or ''}: {_clip(message.get('body_text'), RECENT_BODY_LIMIT)}")
    return "\n".join(lines) or "없음"


def preferences_text(preferences: dict | None) -> str:
    return json.dumps(preferences, ensure_ascii=False) if preferences else "없음"
