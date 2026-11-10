"""프롬프트 자리. 업무 지시는 해당 하위 작업에서 채운다."""

from app.prompts import Prompt

NAME = "analyze_email"
VERSION = "v1"
TEMPLATE = "{input}"
PROMPT = Prompt(NAME, VERSION, TEMPLATE)
