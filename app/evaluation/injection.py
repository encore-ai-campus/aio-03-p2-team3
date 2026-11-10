"""준비된 응답·고의 실패 주입과 실행 기록 표시(계획 17절, CONTRACT 8.2절 `detail.injected`).

- `ScenarioBackend`: `app/llm/client.py`의 `use_backend()`에 넣는 LLM 대역. 출력 형식(스키마) 이름마다
  ① 주입 목록(`inject`) → ② 가짜 응답(`fake`, 가짜 LLM 실행에서만) → ③ 실제 Gemini(실제 API 실행) 순으로 답한다.
  호출마다 주입 여부를 `calls`에 남긴다.
- `InjectedSendFailure`: Google 호출 객체를 감싸 승인 발송(`send_message`)에 고의 실패를 차례로 넣는다.
- `mark_injected()`·`mark_injected_sends()`: 실행이 끝난 뒤 주입한 호출에 해당하는 `llm_call`·`retry`·`send` 줄의
  `detail`에 `injected: true`와 `injection`(`prepared` 준비된 응답 / `failure` 고의 실패 / `mixed`)을 더한다.
  실제 API가 답한 호출의 줄은 그대로 둔다.
"""

from copy import deepcopy

from sqlalchemy import select

from app.db.engine import Database
from app.db.models import RunEvent


class _Bound:
    def __init__(self, owner, schema):
        self.owner, self.schema = owner, schema

    def invoke(self, prompt):
        return self.owner.answer(self.schema, prompt)


class ScenarioBackend:
    def __init__(self, inject: dict | None = None, fake: dict | None = None, real=None):
        """real: 실제 API 실행이면 실제 LLM 백엔드를 돌려주는 함수, 가짜 LLM 실행이면 None."""
        self.inject = {name: list(items) for name, items in (inject or {}).items()}
        self.fake = {name: list(items) for name, items in (fake or {}).items()}
        self.real = real
        self.calls: list[tuple[str, str | None]] = []   # (스키마 이름, prepared/failure/None=실제 API)

    def with_structured_output(self, schema):
        return _Bound(self, schema)

    def _prepared(self, name, item):
        if callable(item):
            self.calls.append((name, "failure"))
            raise item()
        self.calls.append((name, "prepared"))
        return deepcopy(item)

    def answer(self, schema, prompt):
        name = schema.__name__
        if self.inject.get(name):
            return self._prepared(name, self.inject[name].pop(0))
        if self.fake.get(name):
            queue = self.fake[name]
            return self._prepared(name, queue.pop(0) if len(queue) > 1 else queue[0])
        if self.real is None:
            self.calls.append((name, "prepared"))
            raise LookupError(f"준비된 응답 없음: {name}")   # 시나리오 정의 누락(internal로 분류됨)
        self.calls.append((name, None))
        return self.real().with_structured_output(schema).invoke(prompt)


class InjectedSendFailure:
    """`send_message`만 가로채고 나머지는 감싼 Google 호출 객체에 넘긴다."""

    def __init__(self, google, failures):
        self._google = google
        self._failures = list(failures)
        self.sends: list[bool] = []    # send_message를 부를 때마다 주입했는지

    def __getattr__(self, name):
        return getattr(self._google, name)

    def send_message(self, gmail, raw, thread_id):
        if self._failures:
            self.sends.append(True)
            raise self._failures.pop(0)()
        self.sends.append(False)
        return self._google.send_message(gmail, raw, thread_id)


def _flag(row: RunEvent, kinds: list[str | None]) -> None:
    kinds = {k for k in kinds if k}
    if kinds:
        row.detail = {**row.detail, "injected": True,
                      "injection": kinds.pop() if len(kinds) == 1 else "mixed"}


def mark_injected(database: Database, run_id: str, calls: list[tuple[str, str | None]]) -> int:
    """LLM 호출 기록에 주입 표시를 단다. 표시한 줄 수를 돌려준다.

    `call_structured()`는 한 번 부를 때 `attempts`만큼 백엔드를 부르고, 실패한 시도마다 `retry` 줄을 남긴 뒤
    끝에 `llm_call` 한 줄을 남긴다. 그 순서대로 `calls`를 나눠 각 줄에 맞춘다.
    """
    kinds = [kind for _, kind in calls]
    marked = 0
    with database.session() as session:
        rows = session.scalars(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)).all()
        position, retries = 0, []
        for row in rows:
            if row.event == "retry":
                retries.append(row)
            elif row.event == "llm_call":
                attempts = int(row.detail.get("attempts") or 0)
                chunk = kinds[position:position + attempts]
                for index, retry in enumerate(retries):
                    if index < len(chunk) and chunk[index]:
                        _flag(retry, [chunk[index]])
                        marked += 1
                if any(chunk):
                    _flag(row, chunk)
                    marked += 1
                position += attempts
                retries = []
        if position != len(kinds) and any(kinds):
            # 기록과 호출 수가 어긋나면(예상 밖 경로) 실행 전체를 주입 실행으로 보수적으로 표시한다.
            for row in rows:
                if row.event == "llm_call" and not row.detail.get("injected"):
                    _flag(row, ["mixed"])
                    marked += 1
    return marked


def mark_injected_sends(database: Database, run_id: str, injected: list[bool]) -> int:
    """승인 발송 시도마다(`send` 줄 순서) 고의 실패를 넣었으면 표시한다."""
    marked = 0
    with database.session() as session:
        rows = session.scalars(select(RunEvent).where(
            RunEvent.run_id == run_id, RunEvent.event == "send",
        ).order_by(RunEvent.seq)).all()
        for row, flag in zip(rows, injected):
            if flag:
                _flag(row, ["failure"])
                marked += 1
    return marked
