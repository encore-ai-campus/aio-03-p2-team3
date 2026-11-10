"""메일 분석 프롬프트(8절). 의도 하나와 근거 한 문장을 구조화 출력으로 받는다."""

from app.prompts import Prompt

NAME = "analyze_email"
VERSION = "v1"
TEMPLATE = """당신은 B2B 영업 담당자의 메일함을 돕는 비서입니다. 받은 메일 하나를 읽고 의도를 하나로 분류하세요.
- general: 답장이 필요한 일반 문의(인사, 질문, 일정 조율 등). 품목·수량·납기 같은 거래 조건이 없다.
- deal: 견적 요청·주문·발주처럼 품목, 수량, 납기, 단가 같은 거래 조건이 들어 있거나 견적서를 원한다.
- ignore: 답장이 필요 없는 메일(광고, 뉴스레터, 자동 알림, 스팸, 단순 수신 확인).
reason에는 그렇게 판단한 근거를 한국어 한 문장으로 적으세요. 메일 원문을 길게 옮기지 마세요.

[스레드 맥락]
{thread_context}

[받은 메일]
{email}
"""
PROMPT = Prompt(NAME, VERSION, TEMPLATE)
