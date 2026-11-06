# AGENTS.md

이 레포는 단위 프로젝트2 팀 과제(LangGraph 에이전트)를 담는다. 팀원은 ChatGPT(Codex)로, 세팅 단계는 Claude로 고치고 모두 PR로 올린다.
ChatGPT·Codex·Claude 모두 이 파일을 가장 먼저 읽는다. Codex는 이 파일을 자동으로 읽지만, 아래 '먼저 읽을 것'의 파일은 자동으로 들어가지 않는다. 요청 문구에 적혀 있지 않아도 작업 전에 그 파일을 직접 열어 끝까지 읽고, 다 읽기 전에는 어떤 파일도 고치지 않는다.

## 먼저 읽을 것 (모든 작업)
1. `.work/RULES.md`: 공통 규칙. 끝까지 읽는다.
2. `.work/TASK.md`: 이 레포의 규칙과 파일 지도. 끝까지 읽는다.
3. `docs/PROJECT_CONTEXT.md`: 최신 흐름(현재 상태). 작업 전에 읽고, 끝낼 때 바꾼 영역의 절을 고친다(RULES 5절).

그 밖의 파일은 TASK.md 파일 지도에서 찾아 필요한 것만 연다.
규칙은 위 파일에만 둔다. 이 파일에는 요약을 두지 않는다(두 곳에 두면 어긋난다).

## 확인 명령
- 테스트: `uv run pytest` (처음 한 번은 `uv sync`)
- 규칙 검사: `python3 .work/check.py` (PR 전에 통과시킨다. 테스트는 부르지 않으니 위 테스트도 따로 돌린다)

<!-- 출처: 진입 파일 구조 [Past work: setup] · CLAUDE.md 대신 AGENTS.md(Codex가 읽음) [Claude proposal] · 이 레포에 CLAUDE.md는 두지 않는다 [Claude proposal] -->
