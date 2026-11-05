# ChatGPT 사용 안내 (팀원용)

팀원이 ChatGPT Business 워크스페이스에서 Codex로 이 레포 작업을 맡기는 방법이다. 근거는 `.work/design/chatgpt-research.md`(5-1단계)와 `.work/design/setup-research.md`(1단계)이고, 화면 상태는 2026-11-05 사용자 확인이다. [Request · Claude proposal]
표시: **(화면에서 확인)** 공식 문서로 못 본 것. 보이는 버튼 이름이 다르면 화면을 따르고, 결과를 6단계 기록에 남긴다.
항목 끝 태그는 출처다(`.work/RULES.md` 머리말).

## 0. 지금 우리 워크스페이스 (2026-11-05 화면 확인)
- Business 워크스페이스에 Chat/Work 전환과 Work 화면이 보인다. 그래서 **새 Codex Cloud(Work in > Cloud)** 를 쓴다. [Request]
- Settings > Codex Cloud에 Environments·Personal vault 탭이 있고, Settings > Coding에 Code Review가 있다. Code Review와 PR 댓글 `@codex`는 GitHub 연동 흐름이라 Legacy가 맡는다. [Request · chatgpt-research ①]
- 환경 `aio-03-p2-team3`(레포 `encore-ai-campus/aio-03-p2-team3`)이 만들어져 있으나 **Unpublished·Private** 다. 게시 전 환경은 작업에 못 쓴다. → 2절로 마무리한다. [Request · chatgpt-research ②]
- Codex 환경에는 API 키를 넣지 않는다. Codex에서 도는 테스트는 가짜 응답으로 하고, 실제 API 시험은 로컬(`.env`)과 Render에서 한다(`.work/TASK.md` 환경 줄). [Request]

## 1. 팀원 연결 순서 (각자 한 번)
1. GitHub에서 레포 초대를 수락한다(Settings 탭이 보이면 admin). [Past work: setup · setup-research ①]
2. ChatGPT에 Business 워크스페이스로 로그인하고, 위쪽 Chat/Work 전환에 Work가 보이는지 본다. [Request]
3. GitHub를 연결한다: 환경 만들기 화면 또는 Codex Cloud 설정의 Connect to GitHub → 자기 GitHub 계정 허용 → 설치 대상 `encore-ai-campus` → 레포 `aio-03-p2-team3` 허용. GitHub 조직 승인이 필요하다고 나오면 조직 Owner에게 승인을 요청한다(요청 메일이 간다). [setup-research ③]
   - 커넥터를 조직에 한 번 설치하면 팀원은 계정 허용만 하면 되는지 **(화면에서 확인)**.
4. 환경: 3절에서 공유가 되면 공유된 환경을 고른다. 안 되면 2절 순서로 자기 환경을 만든다. [Claude proposal]

## 2. 기존 Unpublished 환경을 마무리해 Publish하기 (환경을 만든 사람)
1. Settings > Codex Cloud > Environments에서 `aio-03-p2-team3`를 연다. 레포가 `encore-ai-campus/aio-03-p2-team3`인지 본다. [chatgpt-research ②]
2. 준비가 멈춰 있으면 Get started로 이어 가거나, 환경의 … 메뉴 → Edit으로 아래 요청을 넣는다. Unpublished 환경을 이어 여는 버튼 이름은 **(화면에서 확인)**. [chatgpt-research ②]
3. 넣을 요청(그대로 붙여넣기): [Claude proposal · chatgpt-research ②]
   ```
   Python 3.12와 uv를 쓴다. `uv sync`로 설치하고 `uv run pytest`가 통과하게 준비해 줘.
   API 키와 비밀값은 넣지 않는다. 테스트는 실제 외부 API를 부르지 않는다.
   ```
4. 보고서·설정을 검토한다: Install script에 `uv sync`가 있는지, Python이 3.12인지(`uv run python --version`), `uv run pytest`가 모두 통과했는지. uv가 미리 깔려 있는지와 Python 버전을 고르는 칸이 따로 있는지는 **(화면에서 확인)**. [chatgpt-research ②]
5. Environment variables와 HTTP secrets는 **비워 둔다**. Personal vault도 지금은 쓰지 않는다. [Request]
6. 인터넷: Enable all public internet access는 끄고 package managers 허용을 둔다(설치는 PyPI만 닿으면 된다). 설치가 막히면 보고서에 나온 막힌 도메인만 Additional allowed domains에 더한다. 기본값은 **(화면에서 확인)**. [Claude proposal · chatgpt-research ④]
7. 공유 설정은 3절을 따른다.
8. Publish → "Environment published"가 뜨고 Unpublished 표시가 사라졌는지 본다. 그 뒤 새 작업에서 고를 수 있다. [chatgpt-research ②]
9. 나중에 바꿀 때: … 메뉴 → Edit → 바꿀 것을 말함 → 시험 → 저장 → Republish. 이미 시작한 작업은 옛 상태를 쓰므로 새 작업을 시작해야 반영된다. [chatgpt-research ②]

## 3. Business에서 환경 공유가 되는지 확인하기
공유 방법(Privacy > Who can use → 워크스페이스)은 공식 문서의 Enterprise 절에만 있어 Business에서 되는지 모른다. 아래로 확인한다. [chatgpt-research ⑤ · Claude proposal]
1. 환경을 만든 사람: 환경 설정에서 Privacy > Who can use를 연다. 워크스페이스(팀 전체)를 고를 수 있으면 고르고 저장 → Publish(이미 게시했으면 Republish).
2. 다른 팀원 한 명: Work in > Cloud → Select environment에 `aio-03-p2-team3`가 보이는지, 골라서 작업이 시작되는지 본다.
3. 판정
   - 1번 선택지가 있고 2번에서 보이며 시작된다 → 공유 됨. 모두 이 환경을 쓴다.
   - 선택지가 Private뿐이거나 2번에서 안 보인다 → 공유 안 됨. 팀원마다 2절 순서로 자기 환경을 만든다(같은 요청 문구, 키 없음).
4. 결과는 사용자에게 알려 6단계 기록 때 `.work/STATUS.md`에 남긴다.

## 4. Codex에 작업 맡기기
1. Work in > Cloud → 환경 `aio-03-p2-team3` → 브랜치 `main`을 고르고 요청을 쓴다. [chatgpt-research ① · RULES 2절 1번]
2. 요청 문구(빈칸을 채워 붙여넣기). 관련 상태·도구·노드, 수정 범위, 확인 조건은 꼭 적는다. [TASK 이 레포의 규칙 · RULES 2절 4번 · Claude proposal]
   ```
   AGENTS.md부터 읽고 레포 규칙대로 해 주세요.
   작업: <한 줄>
   관련 상태·도구·노드: <상태 필드·도구·노드 이름, 없으면 없음>
   수정 범위: <파일·폴더>
   확인 조건: <완료 기준>. `uv run pytest`와 `python3 .work/check.py`가 통과할 것.
   테스트는 실제 외부 API를 부르지 말고 가짜 응답으로 한다.
   Issue: #<번호> — 아래에 본문(완료 기준)을 붙임
   <Issue 본문>
   조율함: <팀원>   ← 공통 부분(상태·도구 스키마·노드·엣지)을 고칠 때만
   마지막 답에 .github/pull_request_template.md 양식을 채운 PR 설명을 함께 내 주세요.
   ```
   - 계획 파일의 하위 작업이면 `작업:` 줄에 `docs/plans/<작업명>.md#N 절만 하세요`를 쓴다. 하위 작업마다 새 작업을 시작한다(RULES 7절 4번).
   - 기능이 둘 이상 섞인 요청이면 Codex는 구현하지 않고 계획 파일만 만든다(RULES 7절 1번).
3. 결과(변경과 시험 결과)를 검토하고 PR을 연다. PR을 여는 버튼·순서는 **(화면에서 확인)**. PR 설명이 양식대로 들어가지 않았으면 Codex 마지막 답의 PR 설명을 붙여넣는다. [chatgpt-research ① · RULES 5절 4번]
4. 병합은 사람이 한다. 누구나 병합하고, 병합한 브랜치는 지우지 않는다(RULES 5절 6번).

## 5. 충돌이 났을 때
1. 규칙: 그 PR에 댓글 `@codex 최신 main에 맞게 충돌을 고쳐 주세요`를 단다(RULES 5절 7번). 이 댓글은 GitHub 연동 흐름이라 Legacy가 맡고, 새 경로에서 만든 PR에도 되는지는 **6단계에서 확인**한다. [Request · chatgpt-research ①]
2. 6단계에서 함께 시험할 방법: 그 PR을 만든 원래 작업(Work)으로 돌아가 같은 문장을 요청하고, 같은 PR이 고쳐지는지 본다. 기존 작업은 자기 파일을 이어 쓰고, 작업 상태는 마지막 실행 뒤 7일까지 되살릴 수 있다. [Request · chatgpt-research ①]
3. 둘 다 안 되면 GitHub 웹 화면에서 고치거나, PR을 닫고 최신 `main`에서 같은 작업을 다시 낸다(RULES 5절 7번).

## 6. 문서 작업용 ChatGPT 프로젝트
설계서·보고서·발표 원고처럼 대화로 다듬는 일에 쓴다. 레포 파일을 바꾸는 일은 4절의 Codex 작업으로 PR을 연다. [Claude proposal]
1. 사이드바 New project → 이름(예: `aio-03-p2-team3 문서`) → 프로젝트의 ••• 메뉴 → Project settings → 지침에 아래를 붙여넣는다. 프로젝트 지침은 그 프로젝트에서만 쓰이고 전역 맞춤 지침보다 우선한다. [chatgpt-research ⑥]
   ```
   이 프로젝트는 GitHub 레포 encore-ai-campus/aio-03-p2-team3(단위 프로젝트2, LangGraph 에이전트) 문서 작업용이다.
   - 레포가 유일한 원본이다. 상태와 결정은 내가 붙여넣은 레포 파일(특히 docs/PROJECT_CONTEXT.md) 내용을 기준으로 말하고, 없는 기능을 지어내지 않는다.
   - 내가 정해야 할 것(기능 범위, 화면 문구, 상태·데이터 구조, LLM·외부 API)은 추측하지 말고 먼저 묻는다.
   - 확인할 것이 있으면 답의 앞부분에 "❗ 확인할 것:" 목록으로 모은다.
   - API 키·토큰과 실제 개인정보(실명, 연락처, 이메일, 일정 원문)는 문서·예시에 넣지 않는다.
   - 레포에 넣을 결과는 파일 경로와 바꿀 절을 밝혀 적는다. 레포 반영은 Codex 작업으로 PR을 연다.
   ```
2. Sources 탭에 레포 파일 사본을 올리지 않는다(레포가 바뀌면 어긋난다). 필요한 파일은 그때그때 붙여넣는다. [Claude proposal · RULES 1절]
3. Work로 할 때는 프로젝트를 열고 Work를 고르면 프로젝트 맥락을 쓴다. [chatgpt-research ⑥]
4. Business에서 프로젝트를 팀원과 공유하는 방법은 **(화면에서 확인)**. 공유 메뉴가 없으면 각자 1번대로 만든다. [chatgpt-research ⑥]

## 7. 6단계 연결 시험에서 확인할 것
6단계(`.work/FLOW.md`)에서 화면으로 보고 결과를 `.work/STATUS.md`에 남긴다. [Request · Claude proposal]
- 3절 환경 공유가 되는지, 2절의 인터넷 기본값·uv·Python 3.12
- PR 여는 버튼·순서, PR 양식과 마지막 답의 PR 설명이 들어가는지, 브랜치 이름을 어떻게 정하는지
- PR 댓글 `@codex`가 동작하는지(5절 1번), 새 경로에서 원래 작업으로 같은 PR을 고칠 수 있는지(5절 2번)
- 새 작업이 최신 `main`(최근 병합 포함)에서 시작하는지(공식 아님, 커뮤니티 보고)
