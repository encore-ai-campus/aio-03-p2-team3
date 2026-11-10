"""실행 기록으로 판정하고 4개 지표를 계산한다(계획 17절, R-13, `docs/TEST_REPORT.md` 4절).

판정 재료는 실행 하나의 `run_id`로 묶인 DB 기록뿐이다: `runs`(종료 이유), `run_events`(`tool_call`·`run_end`·`send`),
`reply_candidates`(후보 종류·개수·확인 필요·재질문 항목·본문), `quotes`(견적서 초안). 판정 결과(`judgment`)에는
메일·후보 본문을 넣지 않고, 사실 비교용 값 조각(숫자+단위)만 넣는다.

지표(성찰 끔/켬을 따로 센다):
1. 태스크 완료율 = 완료 조건을 모두 채운 실행 수 / 판정한 실행 수
2. 도구 선택 정확도 = 부른 도구 집합이 정답 도구 조합과 같은 실행 수 / 판정한 실행 수
   (정답에 없는 도구 = 불필요한 호출, 정답에 있는데 안 부른 도구 = 누락. 같은 도구를 성찰로 다시 부른 것은 집합이라 한 번)
3. 응답 일관성 점수 = 같은 시나리오·같은 성찰 설정을 반복한 실행들의 모든 쌍에서 사실·사용자 조건·응답 구조가
   각각 같은 비율의 평균(0~1). 반복이 2번 미만인 시나리오는 빼고, 전체 점수는 시나리오 점수의 평균.
4. 평균 재시행 횟수 = (통신·형식 재시도 `call_retries` + 성찰 재실행 `reflection_retries` + 사용자 재승인 발송)
   의 합 / 판정한 실행 수. 최초 실행(첫 시도·첫 승인)은 세지 않는다.
"""

from collections import defaultdict
from itertools import combinations
import re

from sqlalchemy import select

from app.db.engine import Database
from app.db.models import Quote, ReplyCandidate, Run, RunEvent
from app.evaluation.scenarios import Scenario

FACT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(억\s*원|만\s*원|천\s*원|원|개|박스|EA|ea|개월|월|일|%)?")
METRICS = ("task_completion", "tool_accuracy", "consistency", "retries")
METRIC_NAMES = {
    "task_completion": "태스크 완료율", "tool_accuracy": "도구 선택 정확도",
    "consistency": "응답 일관성 점수", "retries": "평균 재시행 횟수",
}


def facts(text: str) -> list[str]:
    """본문의 숫자+단위 조각(금액·수량·날짜). 쉼표·띄어쓰기는 지운다."""
    return [re.sub(r"[\s,]", "", number + (unit or "")) for number, unit in FACT_RE.findall(text)]


def judge_run(database: Database, run_id: str, scenario: Scenario, approval: list[str] | None = None) -> dict:
    """실행 하나를 시나리오의 완료 조건·정답 도구 조합과 비교한다. approval: 승인 발송 결과 키(차례대로)."""
    expect = scenario.expect
    with database.session() as session:
        run = session.scalar(select(Run).where(Run.run_id == run_id))
        events = session.scalars(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)).all()
        rows = session.scalars(select(ReplyCandidate).where(ReplyCandidate.run_id == run_id)
                               .order_by(ReplyCandidate.id)).all()
        quote = session.scalar(select(Quote).where(Quote.run_id == run_id).order_by(Quote.id.desc()))
        candidates = [{"kind": r.kind, "subject": r.subject, "body": r.body, "asks": list(r.asks_fields or []),
                       "needs_review": r.needs_review, "notice": r.notice} for r in rows]
        quote_draft = dict(quote.draft) if quote is not None else None
        end_reason, reflection_enabled = run.end_reason, run.reflection_enabled
        tools = [e.tool for e in events if e.event == "tool_call" and e.tool]
        run_end = next((e.detail for e in events if e.event == "run_end"), {})
        sends = [e.detail for e in events if e.event == "send"]

    called = set(tools)
    unnecessary = sorted(called - expect.tools)
    missing = sorted(expect.tools - called)
    low, high = expect.candidates
    bodies = " ".join(c["body"] for c in candidates)
    checks = {
        "end_reason": end_reason == expect.end_reason,
        "candidate_count": low <= len(candidates) <= high,
        "kind": bool(candidates) and all(c["kind"] == expect.kind for c in candidates),
        "needs_review": bool(candidates) and all(c["needs_review"] == expect.needs_review for c in candidates),
        "notice": all(c["notice"] == expect.notice for c in candidates),
    }
    if expect.asks:
        checks["asks"] = bool(candidates) and all(set(expect.asks) <= set(c["asks"]) for c in candidates)
    if expect.quote:
        checks["quote"] = quote_draft is not None
    if expect.forbidden:
        checks["forbidden"] = not any(word in bodies for word in expect.forbidden)
    if expect.approval:
        checks["approval"] = list(approval or []) == list(expect.approval)

    run_facts = sorted({f for c in candidates for f in facts(c["body"])})
    if quote_draft is not None:
        run_facts += [f"합계:{quote_draft.get('total')}"]
        run_facts += [f"{line.get('item_name')}:{line.get('quantity')}{line.get('unit') or ''}"
                      for line in quote_draft.get("lines", [])]
    call_retries = int(run_end.get("call_retries") or 0)
    reflection_retries = int(run_end.get("reflection_retries") or 0)
    resends = max(0, len(sends) - 1)
    return {
        "run_id": run_id, "scenario": scenario.key, "reflection_enabled": reflection_enabled,
        "completed": all(checks.values()), "checks": checks,
        "tools_called": tools, "tool_hit": not unnecessary and not missing,
        "unnecessary": unnecessary, "missing": missing,
        "call_retries": call_retries, "reflection_retries": reflection_retries, "resends": resends,
        "retries": call_retries + reflection_retries + resends,
        "signature": {
            "facts": sorted(run_facts),
            "conditions": [end_reason, sorted({a for c in candidates for a in c["asks"]}),
                           any(c["needs_review"] for c in candidates),
                           sorted({c["notice"] for c in candidates if c["notice"]})],
            "structure": [len(candidates), sorted(c["kind"] for c in candidates),
                          all(c["subject"].startswith("Re: ") for c in candidates), quote_draft is not None],
        },
    }


def _rate(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else None


def consistency(judgments: list[dict]) -> dict:
    """같은 시나리오 반복 실행들의 쌍 비교. 반환: 시나리오별 항목 일치율과 전체 점수."""
    by_scenario = defaultdict(list)
    for j in judgments:
        by_scenario[j["scenario"]].append(j["signature"])
    scores = {}
    for key, signatures in by_scenario.items():
        pairs = list(combinations(signatures, 2))
        if not pairs:
            scores[key] = {"runs": len(signatures), "score": None}
            continue
        parts = {part: _rate(sum(a[part] == b[part] for a, b in pairs), len(pairs))
                 for part in ("facts", "conditions", "structure")}
        scores[key] = {"runs": len(signatures), **parts, "score": round(sum(parts.values()) / 3, 4)}
    measured = [s["score"] for s in scores.values() if s["score"] is not None]
    return {"score": round(sum(measured) / len(measured), 4) if measured else None,
            "scenarios_measured": len(measured), "by_scenario": scores}


def summarize(judgments: list[dict]) -> dict:
    """성찰 설정 하나의 판정 목록 → 4개 지표."""
    total = len(judgments)
    completed = sum(j["completed"] for j in judgments)
    hits = sum(j["tool_hit"] for j in judgments)
    by_scenario = defaultdict(lambda: {"completed": 0, "total": 0, "tool_hits": 0, "retries": 0})
    unnecessary, missing = defaultdict(int), defaultdict(int)
    for j in judgments:
        row = by_scenario[j["scenario"]]
        row["completed"] += j["completed"]
        row["total"] += 1
        row["tool_hits"] += j["tool_hit"]
        row["retries"] += j["retries"]
        for tool in j["unnecessary"]:
            unnecessary[tool] += 1
        for tool in j["missing"]:
            missing[tool] += 1
    retries = {part: sum(j[part] for j in judgments) for part in ("call_retries", "reflection_retries", "resends")}
    retry_total = sum(retries.values())
    return {
        "runs": total,
        "task_completion": {"completed": completed, "total": total, "rate": _rate(completed, total)},
        "tool_accuracy": {"hits": hits, "judged": total, "rate": _rate(hits, total),
                          "unnecessary": dict(unnecessary), "missing": dict(missing)},
        "consistency": consistency(judgments),
        "retries": {"total": retry_total, "runs": total, "average": _rate(retry_total, total), **retries},
        "by_scenario": dict(by_scenario),
    }


def compute_metrics(judgments: list[dict]) -> dict:
    """성찰 끔(`off`)·켬(`on`) 각각의 4개 지표."""
    return {label: summarize([j for j in judgments if j["reflection_enabled"] is enabled])
            for label, enabled in (("off", False), ("on", True))}


def _show(value, digits=2):
    return "미측정" if value is None else f"{value:.{digits}f}"


def render_markdown(metrics: dict) -> str:
    """`docs/TEST_REPORT.md` 결과 표에 붙여넣을 표."""
    off, on = metrics["off"], metrics["on"]

    def cell(summary, metric):
        data = summary[metric]
        if metric == "task_completion":
            return f"{_show(data['rate'])} ({data['completed']}/{data['total']})"
        if metric == "tool_accuracy":
            return f"{_show(data['rate'])} ({data['hits']}/{data['judged']})"
        if metric == "consistency":
            return f"{_show(data['score'])} (시나리오 {data['scenarios_measured']}개)"
        return f"{_show(data['average'])} ({data['total']}/{data['runs']})"

    lines = ["| 지표 | 성찰 끔 | 성찰 켬 |", "|---|---|---|"]
    lines += [f"| {METRIC_NAMES[m]} | {cell(off, m)} | {cell(on, m)} |" for m in METRICS]
    lines += ["", "| 시나리오 | 완료(끔) | 완료(켬) | 도구 적중(끔) | 도구 적중(켬) | 재시행(끔) | 재시행(켬) |",
              "|---|---|---|---|---|---|---|"]
    for key in sorted(set(off["by_scenario"]) | set(on["by_scenario"])):
        a = off["by_scenario"].get(key, {"completed": 0, "total": 0, "tool_hits": 0, "retries": 0})
        b = on["by_scenario"].get(key, {"completed": 0, "total": 0, "tool_hits": 0, "retries": 0})
        lines.append(f"| {key} | {a['completed']}/{a['total']} | {b['completed']}/{b['total']} | "
                     f"{a['tool_hits']}/{a['total']} | {b['tool_hits']}/{b['total']} | {a['retries']} | {b['retries']} |")
    return "\n".join(lines) + "\n"
