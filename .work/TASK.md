# aio-03-p2-team3 — 이 레포의 규칙과 지도

과제: 단위 프로젝트2 「복합 API 연계 일정 조정 에이전트」(LangGraph, 주제 확장 가능) [Request]
레포 주소: `encore-ai-campus/aio-03-p2-team3` (Public) [Request]
공통 규칙: `.work/RULES.md`. 이 파일보다 먼저 끝까지 읽는다.
이 파일은 과제별 파일이다. 다음 과제의 템플릿에는 빈 틀로 들어간다. [Request]

## 이 레포의 규칙
<!-- 이 레포에만 해당하는 규칙. 고칠 때는 공통 규칙 4절을 따른다. -->
- 공통 부분: 그래프 상태 객체, 도구 스키마(입출력), 그래프 노드·엣지. 고치기 전에 관련 팀원(그 부분을 지금 고치고 있거나 최근에 고친 사람)과 조율한다. 같은 파일을 여럿이 고칠 때도 조율한다. [Request]
  - 요청자는 AI에게 맡기기 전에 조율하고, 요청에 `조율함: <팀원>`을 적는다. 그 줄 없이 공통 부분을 바꿔야 하면 AI는 공통 규칙 5절 5번의 ⚠ 줄을 쓴다. [Claude proposal]
  - 공통 부분의 파일 위치: 정의 원본 `docs/CONTRACT.md` 2·3·4절, 코드는 그래프 상태 `app/graph/state.py`, 도구 스키마 `app/tools/base.py`·`app/tools/registry.py`·각 도구 파일의 `Input`, 그래프 노드·엣지 `app/graph/build.py`·`app/graph/routing.py`(코드 파일은 `docs/plans/gmail-quote-mvp.md#2`에서 만든다). 코드와 계약을 같은 PR에서 함께 고친다. [Claude proposal]
- 담당은 미리 정하지 않는다. 누구나 어느 부분이든 맡는다. 프로젝트를 마친 뒤 팀원별 PR 내역을 바탕으로 맡은 바를 정리해 README에 적는다. [Request]
- AI에게 작업을 맡길 때 요청에 관련 상태·도구·노드, 수정 범위, 확인 조건을 적는다. [Request]
- 병합 전 절차: ① PR을 연 사람이 '설명' 칸에 변경 이유·입출력·상태 변화·오류 처리·작동 방식(발표용)을 적는다(필수, 칸마다 쓸 내용은 PR 양식). ② 검토자가 정상·오류 요청의 실제 결과를 확인한다(선택, 병합 뒤 댓글도 된다). ③ PR을 연 사람이 반영한다. [Request · Claude proposal]
- 기록: 설계 결정·오류 사례·수정 이유·버전·재실행 결과를 Issue, PR('오류·재실행 기록' 칸), 팀 노션에 남긴다. [Request]
- 요구사항 가리키기: 계획·설계서·시험 보고서·PR은 과제 요구사항을 `docs/REQUIREMENTS.md`의 R-ID(예: R-02)로 가리킨다. PR은 '관련 Issue·계획' 칸에 적는다. [Request · Claude proposal]
- 환경: Python 3.12, uv. 환경변수 이름은 `.env.example`에 두고, 키는 각자 로컬 `.env`와 서버 환경(Render)에 둔다. Codex 환경에는 API 키를 넣지 않고, Codex에서 도는 테스트는 실제 API 대신 가짜 응답으로 한다. 실제 API 시험은 로컬과 Render에서 한다. [Request] 설치는 `uv sync`, 테스트는 `uv run pytest`. 패키지는 `uv add <패키지>==<버전>`(개발용은 `--dev`)으로 더하고, 버전은 `pip index versions <패키지>`로 확인하며, 바뀐 `pyproject.toml`·`uv.lock`을 함께 올린다. 서버 실행 명령은 코드 구조가 정해지면 README에 더한다. [Claude proposal]
- LLM·외부 API를 더하거나 바꾸는 작업은 요청자가 정한다(대화면 묻고, Codex 작업이면 질문을 결과로 돌려준다). 정한 것은 `.work/design/api-choice.md`·`.env.example`·README에 반영한다. [Request]

## 파일 지도
<!-- 형식: - `경로` — 무엇인지 [공통|과제별]. [공통] 다음 과제에도 그대로 씀 · [과제별] 이 과제용(템플릿에는 빈 틀) [Request]
     맨 앞 경로가 실제로 있는지, 레포의 모든 파일이 경로 줄이나 `/`로 끝나는 폴더 줄로 덮이는지 check.py가 검사한다. -->
- `AGENTS.md` — 진입 파일(ChatGPT·Codex·Claude가 먼저 읽음) [공통]
- `README.md` — 레포 소개, 실행 방법, 산출물 위치, LLM·API 키 발급, 팀원 [과제별]
- `pyproject.toml` — Python 3.12·패키지(버전 고정)·pytest 설정 [과제별]
- `uv.lock` — uv가 만드는 잠금 파일. 손으로 고치지 않는다 [과제별]
- `.python-version` — uv가 쓸 Python 버전(3.12) [과제별]
- `.env.example` — 환경변수 이름과 설명(값 없음) [과제별]
- `.gitignore` — `.env`·`.venv` 등 올리지 않을 파일 [과제별]
- `tests/test_env.py` — 실행 환경 확인 테스트(Python 버전, 패키지 불러오기, `.env.example`에 값 없음) [과제별]
- `.work/RULES.md` — 공통 규칙 [공통]
- `.work/TASK.md` — 이 파일 [과제별]
- `.work/STATUS.md` — 세팅 진행기록(지금 할 일·다음 단계 안내). 세팅 단계 작업과 진행기록을 물을 때만 읽는다 [과제별]
- `.work/FLOW.md` — 세팅 작업 흐름(단계 목록) [과제별]
- `.work/measure.py` — 작업량 재기 도구(공통 규칙 8절). 크기만 내고, `--show`로 절만 연다 [공통]
- `.work/check.py` — 규칙 검사 도구(공통 규칙 5절 3번). 표준 라이브러리만 쓰고 테스트는 부르지 않는다. `--pr`은 PR 본문의 '읽은 파일'·'최신 흐름 갱신' 칸을 본다(공통 규칙 5절 4번) [공통]
- `.github/pull_request_template.md` — PR 양식 [공통]
- `.github/workflows/rules-check.yml` — CI. PR과 main 변경마다 규칙 검사(`check.py`)와 테스트(`uv sync --locked`·`uv run pytest`)를 따로 돌리고, PR(본문 고침 포함)에서는 `pr-check`(`check.py --pr`)도 돌린다 [공통]
- `docs/PROJECT_CONTEXT.md` — 최신 흐름(과제 개요, 영역별 현재 상태, 산출물 위치). 모든 작업 전에 읽는다 [과제별]
- `docs/plans/README.md` — 계획 파일 형식(RULES 7절) [공통]
- `docs/plans/` — 큰 작업의 계획 파일 `<작업명>.md`(RULES 7절) [과제별]
- `docs/CONTRACT.md` — gmail-quote-mvp 공통 계약(폴더 구조, 그래프 상태·노드·전이·한도, 도구 입출력, 필수 항목 출처, LLM 호출, DB 표, 실행 기록, 화면, Google, 환경변수). 하위 작업은 13절에서 자기가 읽을 절만 연다 [과제별]
- `docs/CHATGPT_GUIDE.md` — 팀원용 ChatGPT 사용 안내(연결 순서, Codex 환경 게시·공유 확인, 작업 요청 문구, 충돌 처리, 문서 작업용 프로젝트 지침) [과제별]
- `.work/design/initial-setup.md` — 초기 세팅 인계(결정, 팀원, 단계 계획, 3단계 할 일). 세팅 단계 작업에서만 읽는다 [과제별]
- `.work/design/setup-research.md` — 연결 준비 공식 확인 결과(1단계). 세팅 단계 작업에서만 읽는다 [과제별]
- `.work/design/api-choice.md` — 고른 LLM·외부 API와 근거(후보 비교, 설정 경로, 출처). LLM·API를 더하거나 바꿀 때 읽는다 [과제별]
- `.work/design/step6-handoff.md` — 6단계 인계(화면에서 본 것, 작업 시작 경로 후보, 정한 것, 팀원 메시지 초안). 6-1단계에서 읽는다 [과제별]
- `.work/design/step6-3-handoff.md` — 6-3단계 인계(공식 확인: Codex의 AGENTS.md 자동 읽기, 정한 것, 6-3-1·6-3-2 할 일). 6-3단계에서 읽는다 [과제별]
- `.work/design/mvp-plan-handoff.md` — MVP 계획 인계(정한 것, 확인한 사실, Claude 추천 설계, 규칙 변경·계획 대화 안내). 그 대화들에서 4절이 가리키는 절만 읽는다 [과제별]
- `docs/REQUIREMENTS.md` — 과제 요구사항 정리(노션 원문을 구현 관점으로 재구성, R-ID·D-ID). 계획·설계서·시험 보고서에서 필요한 절만 읽는다 [과제별]
- `docs/ARCHITECTURE.md` — Gmail 견적 MVP 에이전트 아키텍처 설계서 초안(D-01, 20에서 최종 코드와 맞춤) [과제별]
- `.work/design/chatgpt-research.md` — Codex·ChatGPT 공식 확인 결과(5-1단계: 새 Codex Cloud와 Legacy, 환경·비밀값·인터넷, 프로젝트 지침 위치). 세팅 단계 작업과 Codex 환경을 바꿀 때 읽는다 [과제별]

읽음 확인 코드: TASK-Z966

