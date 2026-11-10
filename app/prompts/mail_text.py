"""메일·스레드를 프롬프트에 넣을 텍스트로 바꾼다(프롬프트 변수용, LLM 호출 없음)."""

from app.graph.state import EmailMessage, ThreadContext

NONE = "(없음)"


def email_text(email: EmailMessage) -> str:
    sender = email["from_name"] or email["from_addr"]
    who = "나(판매자)" if email["direction"] == "out" else f"상대방 {sender}"
    return (f"보낸 사람: {who}\n받은 시각: {email['received_at']}\n"
            f"제목: {email['subject']}\n본문:\n{email['body_text']}")


def thread_text(context: ThreadContext | None, current_message_id: str) -> str:
    if not context:
        return NONE
    parts = []
    if context.get("summary"):
        parts.append(f"요약: {context['summary']}")
    if context.get("confirmed_terms"):
        parts.append(f"앞서 확인한 조건: {context['confirmed_terms']}")
    for message in context.get("recent_messages") or []:
        if message["gmail_message_id"] != current_message_id:
            parts.append("---\n" + email_text(message))
    return "\n".join(parts) or NONE
