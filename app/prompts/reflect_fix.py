"""성찰 원인 분석 프롬프트(계획 12절). 규칙 검사가 문제를 찾았을 때만 부른다."""

from app.prompts import Prompt

NAME = "reflect_fix"
VERSION = "v1"
TEMPLATE = """당신은 메일 답장 에이전트의 결과를 검토하는 검토자입니다.
규칙 검사가 아래 문제를 찾았습니다. 문제마다 원인을 짧게 분석하고, 다시 실행할 단계의 프롬프트에 더할 수정 지시를 쓰세요.
규칙:
- cause에는 왜 이런 결과가 나왔는지 한두 문장으로 적습니다.
- feedback에는 다시 실행할 단계가 그대로 따를 수 있는 구체적인 지시를 적습니다(예: "원문에 없는 금액 500만원을 쓰지 마세요").
- 메일과 거래 항목에 없는 사실(금액, 수량, 날짜)을 새로 만들라고 지시하지 마세요.
- 개인 정보(이름, 연락처, 메일 주소)를 적지 마세요.

[답장 종류] {reply_mode}
[고른 수정 전략] {strategy} → 다시 실행할 단계: {retry_target}
[찾은 문제]
{issues}
[거래 항목 요약]
{deal_summary}
"""
PROMPT = Prompt(NAME, VERSION, TEMPLATE)

STRATEGY_GUIDES = {
    "reprompt": "오류 이유를 프롬프트에 더해 같은 단계를 다시 실행",
    "reroute": "경로를 바꿔 거래 항목 추출부터 다시 실행",
    "followup": "견적서 대신 빠진 항목을 묻는 재질문 후보로 대체",
}
