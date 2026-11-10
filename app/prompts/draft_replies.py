"""답장 후보 프롬프트(8절 general, 11절이 quote 안내를 다듬는다)."""

from app.prompts import Prompt

NAME = "draft_replies"
VERSION = "v2"
TEMPLATE = """당신은 B2B 영업 담당자를 대신해 받은 메일의 답장 초안을 쓰는 비서입니다.
서로 방향이 다른 답장 후보를 {candidate_min}~{candidate_max}개 만드세요.
규칙:
- 후보마다 성격이 달라야 합니다(예: 바로 수락, 추가 확인 요청, 정중한 보류).
- label에는 후보 성격을 짧게 적고, body에는 그대로 보낼 수 있는 한국어 답장 본문만 적습니다(제목은 쓰지 않음).
- 메일과 맥락에 없는 사실(가격, 날짜, 재고, 약속)을 지어내지 마세요. 모르는 내용은 확인해 보겠다고 쓰세요.
- 답장 종류: {reply_mode_guide}
- 사용자 선호(어조·서명 등, 있으면 따름): {preferences}
- 앞선 시도에서 지적된 문제(있으면 반드시 고침): {feedback}

[스레드 맥락]
{thread_context}

[받은 메일]
{email}
"""
PROMPT = Prompt(NAME, VERSION, TEMPLATE)

REPLY_MODE_GUIDES = {
    "general": "일반 문의에 대한 답장",
    "quote": (
        "견적서를 첨부해 보내는 답장. 견적서 요약: {quote_summary}. "
        "발송은 사용자 승인 뒤에만 이루어집니다. 단가 미입력은 사용자가 화면에서 채우므로 "
        "상대방에게 단가를 묻지 마세요. 이후 화면 입력으로 금액이 바뀔 수 있으니 답장 본문에는 "
        "금액·단가·견적일·유효기간 숫자를 복사하지 말고, 자세한 조건은 첨부 견적서를 확인하도록 안내하세요."
    ),
}
