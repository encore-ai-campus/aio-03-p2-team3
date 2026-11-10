"""reflect: 오류 감지 → 원인 분석 → 수정 전략 선택 → 재실행 → 검증(계획 12절, 계약 12.1절).

- 감지는 규칙 검사로만 한다(LLM 없음). 문제가 있을 때만 `reflect_fix`로 원인과 수정 지시를 받는다.
- 재실행은 라우팅(`route_after_reflect`)이 `reflection.retry_target` 노드로 보내서 한다.
  그 노드가 끝나면 다시 이 노드로 와서 같은 기준으로 검사하고 `verified`를 남긴다.
- 오류 유형별·전체 한도(`LIMITS`)를 넘으면 실패가 아니라 '확인 필요' 후보로 끝낸다(대체 경로).
- 성찰 재실행(`reflection_retries*`)과 통신·형식 재시도(`call_retries`)는 따로 센다.
"""

from dataclasses import dataclass, field
import json
import re

from pydantic import BaseModel, Field

from app.config import LIMITS
from app.graph.nodes.common import agent_error, preferences_of
from app.graph.state import AgentState, ReflectionIssue, ReflectionResult, ReplyCandidate
from app.llm.client import call_structured
from app.prompts.reflect_fix import PROMPT, STRATEGY_GUIDES
from app.quote.required_fields import FIELD_LABELS
from app.runlog.logger import current_event
from app.tools.check_required_fields import find_missing
from app.tools.fallback import fallback_candidates, reply_subject

NODE = "reflect"
# 앞 단계의 잘못을 먼저 고친다: 경로 → 입력 → 형식 → 내용.
ISSUE_ORDER = ("wrong_tool", "missing_param", "inconsistent", "hallucination")
RETRY_STRATEGIES = {"reprompt", "reroute", "followup"}

_NUM = r"(?<![\d.])(\d{1,3}(?:,\d{3})+|\d+)"
MONEY_RE = re.compile(_NUM + r"\s*(억\s*원|만\s*원|천\s*원|원|만원)")
WON_SIGN_RE = re.compile(r"(?:₩|KRW)\s*(\d{1,3}(?:,\d{3})+|\d+)", re.IGNORECASE)
QUANTITY_RE = re.compile(
    _NUM + r"\s*(박스|box|ea|세트|set|개(?!월)|대(?!표)|장|권|병|매|부|켤레|벌|롤|팩|톤|kg|통|캔|봉|포)(?![a-z])",
    re.IGNORECASE,
)
DATE_RES = (
    re.compile(r"(?<!\d)(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})(?!\d)"),
    re.compile(r"(?<![\d.])(\d{1,2})\s*월\s*(\d{1,2})\s*일"),
    re.compile(r"(?<![\d/.-])(\d{1,2})/(\d{1,2})(?![\d/])"),
)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
DEAL_KEYWORDS = ("견적", "발주", "주문", "구매", "납품", "단가")
MONEY_UNITS = {"억원": 100_000_000, "만원": 10_000, "천원": 1_000, "원": 1}


class ReflectAnalysis(BaseModel):
    cause: str = Field(min_length=1, description="문제가 생긴 원인 한두 문장")
    feedback: str = Field(min_length=1, description="다시 실행할 단계의 프롬프트에 더할 구체적 수정 지시")


@dataclass
class Finding:
    issue: ReflectionIssue
    strategy: str | None            # 수정 전략(계약 12.1절). None이면 고칠 길이 없어 대체 경로
    target: str | None              # 재실행할 노드
    feedback: str                   # 규칙 검사로 만든 수정 지시(LLM이 실패해도 씀)
    update: dict = field(default_factory=dict)   # 경로를 바꿀 때 함께 고칠 상태
    selected_tool: str | None = None


def reflect(state: AgentState) -> dict:
    try:
        return _reflect(state)
    except Exception as error:
        # 성찰 자체의 오류로 실행을 실패시키지 않는다. 원문 없이 종류만 남기고 확인 필요로 끝낸다.
        message = f"성찰 실행 실패 ({type(error).__name__})"
        result = ReflectionResult(passed=False, issues=[], cause=message, strategy="fallback",
                                  retry_target=None, feedback=None, verified=None)
        current_event("reflection", detail={"stage": "strategy", "strategy": "fallback",
                                            "retry_target": None, "reason": "internal"})
        return {"errors": [agent_error(NODE, "internal", message)], **_fallback_update(state, result)}


def _reflect(state: AgentState) -> dict:
    previous = state["reflection"]
    rechecking = bool(previous and not previous["passed"] and previous["strategy"] in RETRY_STRATEGIES)
    findings = detect(state)
    issues = [f.issue for f in findings]
    current_event("reflection", detail={"stage": "detect", "issues": issues, "rechecking": rechecking})
    verified = (not findings) if rechecking else None
    if rechecking:
        current_event("reflection", detail={
            "stage": "verify", "verified": verified, "after_strategy": previous["strategy"],
            "retried": previous["retry_target"], "issues": [i["type"] for i in issues],
        })
    if not findings:
        result = ReflectionResult(passed=True, issues=[], cause=None, strategy=None,
                                  retry_target=None, feedback=None, verified=verified)
        return {"reflection": result, "reflection_history": [result]}

    primary = next(f for kind in ISSUE_ORDER for f in findings if f.issue["type"] == kind)
    kind = primary.issue["type"]
    by_type = dict(state["reflection_retries_by_type"])
    total = state["reflection_retries"]
    over_limit = (total >= LIMITS["REFLECTION_MAX_RETRIES_TOTAL"]
                  or by_type.get(kind, 0) >= LIMITS["REFLECTION_MAX_RETRIES_BY_TYPE"][kind])
    if over_limit or primary.strategy is None:
        cause = _rule_cause(findings)
        current_event("reflection", detail={"stage": "analyze", "cause": cause, "llm": False})
        current_event("reflection", detail={
            "stage": "strategy", "strategy": "fallback", "retry_target": None,
            "reason": "limit" if over_limit else "no_fix", "issue_type": kind,
            "reflection_retries": total, "by_type": by_type,
        })
        result = ReflectionResult(passed=False, issues=issues, cause=cause, strategy="fallback",
                                  retry_target=None, feedback=None, verified=verified)
        return _fallback_update(state, result)

    rule_feedback = " / ".join(dict.fromkeys(f.feedback for f in findings if f.issue["type"] == kind))
    cause, llm_feedback, call_update = _analyze(state, findings, primary)
    feedback = f"{llm_feedback}\n규칙 검사로 찾은 문제: {rule_feedback}" if llm_feedback else rule_feedback
    by_type[kind] = by_type.get(kind, 0) + 1
    current_event("reflection", detail={
        "stage": "strategy", "strategy": primary.strategy, "retry_target": primary.target,
        "issue_type": kind, "reflection_retries": total + 1, "by_type": by_type,
    })
    if primary.selected_tool:
        current_event("tool_select", tool=primary.selected_tool, detail={
            "reason": primary.update.get("tool_reason"), "by": "reflection",
        })
    result = ReflectionResult(passed=False, issues=issues, cause=cause, strategy=primary.strategy,
                              retry_target=primary.target, feedback=feedback, verified=verified)
    return {
        "reflection": result, "reflection_history": [result],
        "reflection_retries": total + 1, "reflection_retries_by_type": by_type,
        **call_update, **primary.update,
    }


# --- 감지(규칙 검사, LLM 없음) ---------------------------------------------------------------

def detect(state: AgentState) -> list[Finding]:
    return [*_wrong_tool(state), *_missing_param(state), *_inconsistent(state), *_hallucination(state)]


def _candidate_node(state: AgentState) -> str:
    return "draft_followup" if state["reply_mode"] == "followup" else "draft_replies"


def _issue(kind: str, detail: str, evidence: str) -> ReflectionIssue:
    return ReflectionIssue(type=kind, detail=detail, evidence=evidence)


def _labels(state: AgentState, keys: list[str]) -> list[str]:
    labels = dict(FIELD_LABELS)
    if state["required_fields"]:
        labels.update({f["key"]: f["label"] for f in state["required_fields"]["fields"]})
    return [labels.get(key, key) for key in keys]


def has_deal_signal(email: dict) -> bool:
    text = f"{email.get('subject') or ''}\n{email.get('body_text') or ''}"
    return any(word in text for word in DEAL_KEYWORDS) and bool(QUANTITY_RE.search(text))


def _wrong_tool(state: AgentState) -> list[Finding]:
    mode = state["reply_mode"]
    if mode == "quote":
        if state["missing_fields"]:
            labels = ", ".join(_labels(state, state["missing_fields"]))
            reason = f"필수 항목({labels})이 빠져 견적서 대신 재질문 후보를 만듦(성찰)"
            return [Finding(
                _issue("wrong_tool", "빠진 필수 항목이 있는데 견적서 경로로 감", f"missing_fields={state['missing_fields']}"),
                "followup", "draft_followup", f"견적서를 보내지 말고 빠진 항목({labels})을 모두 물으세요.",
                {"reply_mode": "followup", "selected_tool": "draft_followup_replies", "tool_reason": reason},
                "draft_followup_replies",
            )]
        if state["deal_terms"] and state["required_fields"]:
            missing = find_missing(state["deal_terms"], state["required_fields"])
            if missing:
                reason = "검토 결과와 거래 항목이 맞지 않아 거래 항목 추출부터 다시 함(성찰)"
                return [Finding(
                    _issue("wrong_tool", "거래 항목에 필수 항목이 빠졌는데 견적서 경로로 감", f"recomputed_missing={missing}"),
                    "reroute", "extract_deal",
                    f"필수 항목({', '.join(_labels(state, missing))})을 메일에서 다시 확인해 정확히 뽑으세요.",
                    {"reply_mode": None, "selected_tool": "extract_deal_terms", "tool_reason": reason},
                    "extract_deal_terms",
                )]
    if mode == "general" and state["deal_terms"] is None and has_deal_signal(state["email"]):
        reason = "메일에 견적·주문 표현과 수량이 있어 일반 답장 대신 거래 항목을 추출함(성찰)"
        return [Finding(
            _issue("wrong_tool", "거래 내용이 있는데 일반 답장 경로로 감", "deal_keyword+quantity"),
            "reroute", "extract_deal", "메일의 거래 내용(품목·수량·납기 등)을 뽑으세요.",
            {"intent": "deal", "reply_mode": None, "selected_tool": "extract_deal_terms", "tool_reason": reason},
            "extract_deal_terms",
        )]
    return []


def _missing_param(state: AgentState) -> list[Finding]:
    mode = state["reply_mode"]
    terms = state["deal_terms"]
    if mode in ("quote", "followup") and (terms is None or (mode == "quote" and not terms["items"])):
        what = "거래 항목" if terms is None else "거래 품목"
        return [Finding(
            _issue("missing_param", f"후보 도구의 필수 입력({what})이 비어 있음", "deal_terms" if terms is None else "deal_terms.items"),
            "reprompt", "extract_deal", f"{what}이 비어 있습니다. 메일에서 거래 항목을 빠짐없이 뽑으세요.",
        )]
    if mode == "quote" and state["quote_draft"] is None:
        return [Finding(
            _issue("missing_param", "견적서 동봉 답장의 필수 입력(견적서 초안)이 비어 있음", "quote_draft"),
            "reprompt", "make_quote", "견적서 초안이 비어 있어 견적서를 다시 만듭니다.",
        )]
    return []


def _inconsistent(state: AgentState) -> list[Finding]:
    findings = []
    target = _candidate_node(state)
    candidates = state["candidates"]
    count = len(candidates)
    low, high = LIMITS["CANDIDATE_MIN"], LIMITS["CANDIDATE_MAX"]
    if not low <= count <= high:
        findings.append(Finding(
            _issue("inconsistent", f"후보 수가 {low}~{high}개가 아님", f"candidates={count}"),
            "reprompt", target, f"답장 후보를 정확히 {low}~{high}개 만드세요.",
        ))
    email = state["email"]
    if state["thread_id"] != email["thread_id"]:
        findings.append(Finding(
            _issue("inconsistent", "실행 스레드와 메일 스레드가 다름", "thread_id"),
            None, None, "스레드가 맞지 않습니다.",
        ))
    expected_kind = state["reply_mode"] or "general"
    subject = reply_subject(email)
    if any(c["kind"] != expected_kind for c in candidates):
        findings.append(Finding(
            _issue("inconsistent", f"후보 종류가 답장 종류({expected_kind})와 다름", "kind"),
            "reprompt", target, "지금 만드는 답장 종류에 맞는 후보를 만드세요.",
        ))
    if any(c["subject"] != subject for c in candidates):
        findings.append(Finding(
            _issue("inconsistent", "후보 제목이 원래 메일의 답장 제목과 달라 다른 스레드가 될 수 있음", "subject"),
            "reprompt", target, "원래 메일에 대한 답장으로 쓰세요.",
        ))
    known = _known_addresses(state)
    stray = sum(1 for c in candidates for addr in EMAIL_RE.findall(c["body"]) if addr.lower() not in known)
    if stray:
        findings.append(Finding(
            _issue("inconsistent", "본문에 원문·기억에 없는 메일 주소가 있어 받는 사람이 맞지 않을 수 있음", f"unknown_addresses={stray}"),
            "reprompt", target, "원래 보낸 사람에게 답하는 본문으로 쓰고, 원문에 없는 메일 주소를 적지 마세요.",
        ))
    if state["reply_mode"] == "followup" and state["missing_fields"]:
        missing = state["missing_fields"]
        labels = dict(zip(missing, _labels(state, missing)))
        absent = sorted({labels[key] for c in candidates for key in missing
                         if key not in c["asks_fields"] or labels[key] not in c["body"]})
        if absent:
            findings.append(Finding(
                _issue("inconsistent", "재질문 후보가 빠진 항목을 다 묻지 않음", f"not_asked={absent}"),
                "reprompt", "draft_followup",
                f"모든 후보 본문에 빠진 항목 이름({', '.join(labels.values())})을 그대로 적어 모두 물으세요.",
            ))
    return findings


def _hallucination(state: AgentState) -> list[Finding]:
    source = _source_text(state)
    numbers = _numbers_in(source)
    money = numbers | _money_values(source)   # JSON의 정수 금액(견적서 합계 등)도 근거로 본다
    dates = _dates_in(source)
    unsupported = []
    for candidate in state["candidates"]:
        body = candidate["body"]
        for token, value in _money_tokens(body):
            if value not in money:
                unsupported.append(token)
        for match in QUANTITY_RE.finditer(body):
            if _to_int(match.group(1)) not in numbers:
                unsupported.append(match.group(0))
        for token, month_day in _date_tokens(body):
            if month_day not in dates:
                unsupported.append(token)
    if not unsupported:
        return []
    shown = ", ".join(dict.fromkeys(token.strip() for token in unsupported))
    return [Finding(
        _issue("hallucination", "후보 본문에 원문·거래 항목·견적서에 없는 금액·수량·날짜가 있음", shown),
        "reprompt", _candidate_node(state),
        f"원문과 거래 항목에 없는 값({shown})을 쓰지 마세요. 모르는 값은 확인 뒤 안내하겠다고 쓰세요.",
    )]


def _source_text(state: AgentState) -> str:
    """후보가 근거로 삼아도 되는 글. 과거 거래 기록(상대방 거래 기록)은 이번 거래 값의 근거가 아니다."""
    email = state["email"]
    long_term = state["long_term"] or {}
    parts = [email.get("subject") or "", email.get("body_text") or "", email.get("received_at") or ""]
    context = state["thread_context"]
    if context:
        parts += [context.get("summary") or "", _dump(context.get("confirmed_terms")), _dump(context.get("last_result"))]
        parts += [f"{m.get('subject') or ''}\n{m.get('body_text') or ''}" for m in context.get("recent_messages") or []]
    parts += [_dump(state["deal_terms"]), _dump(state["quote_draft"]),
              _dump(long_term.get("price_list")), _dump(long_term.get("company")), _dump(preferences_of(state))]
    return "\n".join(parts)


def _known_addresses(state: AgentState) -> set[str]:
    return {addr.lower() for addr in EMAIL_RE.findall(_source_text(state) + "\n" + " ".join(state["email"]["to_addrs"])
                                                         + " " + state["email"]["from_addr"])}


def _dump(value) -> str:
    return "" if value is None else json.dumps(value, ensure_ascii=False)


def _to_int(raw: str) -> int:
    return int(raw.replace(",", ""))


def _numbers_in(text: str) -> set[int]:
    return {_to_int(raw) for raw in re.findall(r"\d{1,3}(?:,\d{3})+|\d+", text)}


def _money_tokens(text: str) -> list[tuple[str, int]]:
    tokens = [(m.group(0), _to_int(m.group(1)) * MONEY_UNITS[re.sub(r"\s", "", m.group(2))])
              for m in MONEY_RE.finditer(text)]
    return tokens + [(m.group(0), _to_int(m.group(1))) for m in WON_SIGN_RE.finditer(text)]


def _money_values(text: str) -> set[int]:
    return {value for _, value in _money_tokens(text)}


def _date_tokens(text: str) -> list[tuple[str, tuple[int, int]]]:
    tokens = []
    for pattern in DATE_RES:
        for match in pattern.finditer(text):
            month, day = (int(g) for g in match.groups()[-2:])
            if 1 <= month <= 12 and 1 <= day <= 31:
                tokens.append((match.group(0), (month, day)))
    return tokens


def _dates_in(text: str) -> set[tuple[int, int]]:
    return {month_day for _, month_day in _date_tokens(text)}


# --- 원인 분석·대체 경로 ---------------------------------------------------------------------

def _rule_cause(findings: list[Finding]) -> str:
    return "규칙 검사: " + "; ".join(f"{f.issue['type']} — {f.issue['detail']}" for f in findings)


def _analyze(state: AgentState, findings: list[Finding], primary: Finding) -> tuple[str, str | None, dict]:
    """문제가 있을 때만 LLM으로 원인·수정 지시를 받는다. 실패하면 규칙 검사 결과로 대신한다."""
    terms = state["deal_terms"]
    deal_summary = "없음" if terms is None else json.dumps({
        "filled": sorted(k for k, v in terms.items() if k not in ("items", "evidence") and v),
        "items": len(terms["items"]), "missing_fields": state["missing_fields"],
    }, ensure_ascii=False)
    result = call_structured(PROMPT, ReflectAnalysis, {
        "reply_mode": state["reply_mode"] or "없음",
        "strategy": STRATEGY_GUIDES[primary.strategy], "retry_target": primary.target,
        "issues": "\n".join(f"- {f.issue['type']}: {f.issue['detail']} (근거: {f.issue['evidence']})" for f in findings),
        "deal_summary": deal_summary,
    })
    retries = max(result.attempts - 1, 0)
    if result.ok:
        cause, feedback = result.value.cause.strip(), result.value.feedback.strip()
    else:
        cause, feedback = _rule_cause(findings), None
    current_event("reflection", detail={
        "stage": "analyze", "cause": cause, "llm": True, "llm_ok": result.ok,
        "error_kind": result.error_kind,
    })
    return cause, feedback, {"call_retries": retries}


def _fallback_update(state: AgentState, result: ReflectionResult) -> dict:
    """한도를 넘으면 마지막 후보에 '확인 필요'를 달아 승인 대기로 끝낸다(계약 3.3절)."""
    kind = state["reply_mode"] or "general"
    candidates = [ReplyCandidate(**{**c, "needs_review": True, "notice": "reflection_limit"})
                  for c in state["candidates"][:LIMITS["CANDIDATE_MAX"]]]
    if not candidates:
        candidates = fallback_candidates(
            state["email"], kind=kind,
            asks_fields=state["missing_fields"] if kind == "followup" else None,
            preferences=preferences_of(state), notice="reflection_limit",
        )
    return {"reflection": result, "reflection_history": [result], "candidates": candidates,
            "needs_review": True, "notice": "reflection_limit"}
