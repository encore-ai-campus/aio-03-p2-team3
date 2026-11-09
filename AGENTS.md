# AGENTS.md

이 레포는 팀 과제를 담는다(과제 이름과 내용은 `.work/TASK.md` 맨 위). 팀원은 ChatGPT(Codex)로, 세팅 단계는 Claude로 고치고 모두 PR로 올린다.
ChatGPT·Codex·Claude 모두 이 파일을 가장 먼저 읽는다. Codex는 이 파일을 자동으로 읽지만, 아래 '먼저 읽을 것'의 파일은 자동으로 들어가지 않는다. 요청 문구에 적혀 있지 않아도 작업 전에 그 파일을 직접 열어 끝까지 읽고, 다 읽기 전에는 어떤 파일도 고치지 않는다.

## 먼저 읽을 것 (모든 작업)
1. `.work/RULES.md`: 공통 규칙. 끝까지 읽는다.
2. `.work/TASK.md`: 이 레포의 규칙과 파일 지도. 끝까지 읽는다.
3. `docs/PROJECT_CONTEXT.md`: 최신 흐름(현재 상태). 작업 전에 읽고, 끝낼 때 바꾼 영역의 절을 고친다(RULES 5절).

그 밖의 파일은 TASK.md 파일 지도에서 찾아 필요한 것만 연다.
규칙은 위 파일과 아래 'Codex가 꼭 할 일'에만 둔다. Codex가 꼭 할 일은 자동으로 읽히는 이 파일에만 두고, 그 밖의 규칙 요약은 이 파일에 두지 않는다(두 곳에 두면 어긋난다).

## 확인 명령
- 테스트: `uv run pytest` (처음 한 번은 `uv sync`)
- 규칙 검사: `python3 .work/check.py` (PR 전에 통과시킨다. 테스트는 부르지 않으니 위 테스트도 따로 돌린다)

## Codex가 꼭 할 일 (Codex 작업)
Codex는 요청 문구에 적혀 있지 않아도 아래를 모두 한다. 로컬에서 고치고 검사만 하고 끝내지 않는다. PR이 열려야 작업이 끝난다. [Request]
1. 시작: 레포 기본 브랜치 `main`에서 시작한다(작업 화면에 브랜치 칸 없음, `docs/CHATGPT_GUIDE.md` 4절 1번). 위 '먼저 읽을 것'을 끝까지 읽고(최신 흐름 `docs/PROJECT_CONTEXT.md` 포함), 그 밖의 파일은 `.work/TASK.md` 파일 지도에서 찾아 필요한 것만 연다. [Request]
2. 최신 흐름 갱신: 파일을 바꿨으면 `docs/PROJECT_CONTEXT.md`에서 바꾼 영역의 절과 그 절의 '마지막 갱신'을 같은 PR에서 고친다(RULES 5절 1번). [Request]
3. 검사·테스트: `python3 .work/check.py`와 `uv run pytest`를 직접 실행해 둘 다 통과시킨다. 통과하지 못하면 PR을 열지 않고 먼저 고친다. 고칠 수 없으면 오류와 시도한 방법을 답에 적는다. [Past work: aio3 · Request]
4. PR 열기: 3번을 마친 뒤 새 브랜치에 커밋해 GitHub에 push하고, `main`으로 PR을 연다. PR 본문에 `.github/pull_request_template.md` 양식을 모두 채우고, 마지막 답에도 같은 설명과 3번의 두 실행 결과를 낸다. 그중 '설명' 칸의 '작동 방식(발표용)'은 요청자가 읽고 발표 질문에 답할 수 있게 따로 짚어 안내한다. [Request] 양식의 '읽은 파일' 칸에는 '먼저 읽을 것' 세 파일을 끝까지 읽을 때 본 `읽음 확인 코드:` 줄 값을, '최신 흐름 갱신' 칸에는 `고친 절: <번호>` 또는 `해당 없음 — <이유>`를 적는다. CI `pr-check`가 이 두 칸을 본다. [Request · Claude proposal]
5. 답 첫 줄: `🔔 PR을 열었습니다. 확인 후 병합해 주세요: <PR 링크>`. 그 아래 ⚠·❗ 줄은 RULES 5절 5번 순서를 따른다. [Request]
6. 병합: 스스로 병합하지 않는다. 팀원이 병합을 요청하면 그 PR의 필수 검사(`rules-check`·`tests`·`pr-check`)가 모두 통과했을 때만 병합한다. 통과를 확인할 수 없거나 아직 끝나지 않았으면 병합하지 않고 `검사가 끝난 뒤 다시 요청해 주세요.`라고 답한다. GitHub도 통과 전 병합을 막는다(Ruleset 'main 필수 검사'). 병합한 브랜치는 지우지 않는다. [Request]

<!-- 출처: 진입 파일 구조 [Past work: setup] · CLAUDE.md 대신 AGENTS.md(Codex가 읽음) [Claude proposal] · 이 레포에 CLAUDE.md는 두지 않는다 [Claude proposal] · 'Codex가 꼭 할 일'은 RULES에서 옮김(6-3-1-2, PR #26 팀원 시험에서 첫 요청에 PR을 안 열고 검사 전에 병합함) [Request] -->
