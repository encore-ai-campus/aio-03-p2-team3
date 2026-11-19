"""analyze_email: LLM 한 번으로 의도를 정하고 다음 도구와 그 이유를 남긴다(계획 8절, R-02·R-04)."""

import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.graph.master.common import failure_update
from app.graph.state import AgentState
from app.llm.client import call_structured, delegated_to_worker
from app.prompts.analyze_email import INBOUND_PROMPT, PROMPT
from app.prompts.format import email_text, thread_context_text
from app.runlog.logger import current_event
from app.services.memory import context_for_model

NEXT_TOOL = {"general": "draft_replies", "deal": "extract_deal_terms", "ignore": None}


class Meeting(BaseModel):
    selected_start: AwareDatetime
    timezone: str = Field(default="Asia/Seoul", max_length=60)
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    duration_evidence: str | None = Field(default=None, max_length=200)
    evidence: str = Field(min_length=2, max_length=350)

    @model_validator(mode="after")
    def validate_timezone(self):
        try:
            zone = ZoneInfo(self.timezone)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("시간대 이름을 확인해 주세요") from error
        if self.selected_start.utcoffset() != self.selected_start.astimezone(zone).utcoffset():
            raise ValueError("시작 시각의 오프셋과 시간대가 일치해야 합니다")
        return self


class EmailAnalysis(BaseModel):
    intent: Literal["general", "deal", "ignore"]
    reason: str = Field(min_length=1, description="판단 근거 한 문장")


class InboundEmailAnalysis(EmailAnalysis):
    model_config = ConfigDict(title="EmailAnalysis")

    meeting: Meeting | None = None
    calendar_related: bool = False
    schedule_only: bool = False
    contract_question: bool = False


def current_text(body: str) -> str:
    kept = []
    for line in body.splitlines():
        if re.match(r"\s*(?:[-_]{2,}\s*(?:original message|forwarded message|원본 메시지)|On .+ wrote:)", line, re.I):
            break
        if not line.lstrip().startswith(">"):
            kept.append(line)
    return "\n".join(kept)


def _korean_clock(text: str, instant: datetime) -> datetime:
    clock = re.search(r"(오전|오후)\s*(1[0-2]|[1-9])\s*시(?:\s*([0-5]?\d)\s*분|\s*(반))?", text)
    if clock:
        period, hour, minutes, half = clock.groups()
        return instant.replace(hour=int(hour) % 12 + (12 if period == "오후" else 0),
                                    minute=30 if half else int(minutes or 0), second=0, microsecond=0)
    return instant


def _meeting_data(meeting: Meeting, text: str, received: datetime) -> dict | None:
    if meeting.evidence not in text or re.search(r"아니|또는|혹은|\beither\b", meeting.evidence, re.I):
        return None
    selected = meeting.selected_start.astimezone(ZoneInfo(meeting.timezone))
    reference = received.astimezone(selected.tzinfo)
    relative = re.search(r"내일\s*모레|모레|내일|오늘", meeting.evidence)
    if relative:
        days = {"오늘": 0, "내일": 1, "모레": 2, "내일모레": 2}
        day = reference.date() + timedelta(days=days["".join(relative[0].split())])
        selected = selected.replace(year=day.year, month=day.month, day=day.day)
    selected = _korean_clock(meeting.evidence, selected)
    duration = meeting.duration_minutes
    duration_evidence = meeting.duration_evidence
    if not duration_evidence or duration_evidence not in text or not re.search(
        r"동안|소요|길이|분간|시간가량|까지|(?:for|until|duration)\b|[–~—]", duration_evidence, re.I
    ):
        duration = None
    else:
        span = re.search(r"(?:\bfor\s+)?(\d+)\s*(분|시간|minutes?|hours?)"
                         r"(?:\s*(?:동안|간|가량|소요))?", duration_evidence, re.I)
        if "까지" in duration_evidence:
            finish = _korean_clock(duration_evidence.rsplit("부터", 1)[-1], selected)
            if finish != selected:
                duration = int((finish.astimezone(UTC) - selected.astimezone(UTC)).total_seconds() / 60)
        elif span:
            duration = int(span[1]) * (60 if span[2].lower().startswith(("시간", "hour")) else 1)
    if duration is not None and not 1 <= duration <= 1440:
        duration = None
    return {"selected_start": selected.isoformat(), "timezone": meeting.timezone, "duration_minutes": duration}


def analyze_email(state: AgentState, *, enrich=False) -> dict:
    # load_memory의 고정 다음 노드. 기억 조회·요약 실패를 덮어쓰지 않는다.
    if state["step_status"] != "ok":
        return {}
    email = state["email"]
    expanded = enrich and not delegated_to_worker()
    received = datetime.fromisoformat(email["received_at"]) if expanded else None
    variables = {
        "thread_context": thread_context_text(context_for_model(state)),
        "email": email_text(email),
    }
    if received is not None:
        variables["email"] = ("메일을 받은 한국 시각: " + received.astimezone(ZoneInfo("Asia/Seoul")).isoformat()
                              + "\n" + email_text({**email, "body_text": current_text(email["body_text"])}))
    result = call_structured(INBOUND_PROMPT if expanded else PROMPT,
                             InboundEmailAnalysis if expanded else EmailAnalysis, variables)
    retries = max(result.attempts - 1, 0)
    if not result.ok:
        return failure_update(
            state, "analyze_email", result.error_kind,
            f"메일 분석 LLM 호출 실패 ({result.error_kind})", call_retries=retries,
        )
    intent = result.value.intent
    selected = NEXT_TOOL[intent]
    reason = result.value.reason.strip()
    update = {
        "intent": intent, "selected_tool": selected, "tool_reason": reason,
        "step_status": "ok", "call_retries": retries,
    }
    if expanded and intent != "ignore":
        analysis = result.value
        if analysis.meeting is not None:
            text = email["subject"] + "\n" + current_text(email["body_text"])
            proposal = _meeting_data(analysis.meeting, text, received)
            if proposal is not None:
                update["calendar_proposal"] = proposal
        update["calendar_related"] = analysis.calendar_related or analysis.meeting is not None
        update["schedule_only"] = analysis.schedule_only
        update["contract_question"] = analysis.contract_question
        if (analysis.schedule_only and update["calendar_related"]) or analysis.contract_question:
            intent = update["intent"] = "general"
            selected = update["selected_tool"] = NEXT_TOOL[intent]
    if intent == "general":
        update["reply_mode"] = "general"
    elif intent == "ignore":
        update["end_reason"] = "ignored"
    if selected:
        current_event("tool_select", tool=selected, detail={"reason": reason, "intent": intent})
    return update
