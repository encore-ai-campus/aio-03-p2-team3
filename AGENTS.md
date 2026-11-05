# AGENTS.md

이 레포는 단위 프로젝트2 팀 과제(LangGraph 에이전트)를 담는다. 팀원은 ChatGPT(Codex)로, 세팅 단계는 Claude로 고치고 모두 PR로 올린다.
ChatGPT·Codex·Claude 모두 이 파일을 가장 먼저 읽는다.

## 먼저 읽을 것 (모든 작업)
1. `.work/RULES.md`: 공통 규칙. 끝까지 읽는다.
2. `.work/TASK.md`: 이 레포의 규칙과 파일 지도. 끝까지 읽는다.
3. `docs/PROJECT_CONTEXT.md`: 최신 흐름(현재 상태). 작업 전에 읽고, 끝낼 때 바꾼 영역의 절을 고친다(RULES 5절).

그 밖의 파일은 TASK.md 파일 지도에서 찾아 필요한 것만 연다.
규칙은 위 파일에만 둔다. 이 파일에는 요약을 두지 않는다(두 곳에 두면 어긋난다).

## 확인 명령
- 테스트: `uv run pytest` (처음 한 번은 `uv sync`)
- 검사 도구(`python3 .work/check.py`)는 세팅 4단계에서 여기에 적는다.

<!-- 출처: 진입 파일 구조 [Past work: setup] · CLAUDE.md 대신 AGENTS.md(Codex가 읽음) [Claude proposal] · 이 레포에 CLAUDE.md는 두지 않는다 [Claude proposal] -->
