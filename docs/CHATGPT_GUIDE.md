# ChatGPT 사용 안내 (팀원용)

팀원이 ChatGPT Business 워크스페이스에서 Codex로 이 레포 작업을 맡기는 방법이다. 근거는 `.work/design/chatgpt-research.md`(5-1단계)와 `.work/design/setup-research.md`(1단계)이고, 화면 상태는 2026-11-05 사용자 확인이다. [Request · Claude proposal]
표시: **(화면에서 확인)** 공식 문서로 못 본 것. 보이는 버튼 이름이 다르면 화면을 따르고, 결과를 6단계 기록에 남긴다.
항목 끝 태그는 출처다(`.work/RULES.md` 머리말).

## 0. 지금 우리 워크스페이스 (2026-11-05 화면 확인)
- Business 워크스페이스에 Chat/Work 전환과 Work 화면이 보인다. 새 Codex Cloud(Settings > Codex Cloud의 환경)를 쓴다. [Request]
- 공식 문서의 "Work in > Cloud" 메뉴는 Work 화면에 없다(입력창 아래는 Choose project·Files·Plugins, + 메뉴에도 Cloud 없음). Codex 작업은 왼쪽 세로 아이콘 줄의 `…` → **Codex** 화면에서 시작하고, 입력창 위 **Cloud · Choose environment**가 그 자리다(4절 1번, 2026-11-05 사용자가 직접 해 봄). [Request]
- Settings > Codex Cloud에 Environments·Personal vault 탭이 있고, Settings > Coding에 Code Review가 있다. Code Review와 PR 댓글 `@codex`는 GitHub 연동 흐름이라 Legacy가 맡는다. [Request · chatgpt-research ①]
- 환경 `aio-03-p2-team3`(레포 `encore-ai-campus/aio-03-p2-team3`)을 2절 순서로 마무리해 게시했고, Who can use를 "Everyone at 엔코아 AI 캠퍼스"로 바꿔 다시 게시했다(Business에서도 워크스페이스 공유 선택지가 있다). [Request]
- 팀원 모두 1절 순서로 GitHub 계정을 연결하고 환경 만들기 화면의 레포 목록에서 팀 레포를 확인했다(2026-11-05). [Request]
- Codex 환경에는 API 키를 넣지 않는다. Codex에서 도는 테스트는 가짜 응답으로 하고, 실제 API 시험은 로컬(`.env`)과 Render에서 한다(`.work/TASK.md` 환경 줄). [Request]

## 1. 팀원 연결 순서 (각자 한 번)
팀원 모두 이 순서로 마쳤다(2026-11-05). 앱(ChatGPT Codex Connector)은 조직에 이미 설치돼 있어 각자 GitHub 계정만 연결하면 된다. 한국어 화면이면 메뉴 이름이 우리말로 보인다. [Request]
1. GitHub 알림(또는 이메일)으로 온 `aio-03-p2-team3` 레포 초대를 수락한다.
2. chatgpt.com에 Business 계정으로 로그인 → 왼쪽 아래 프로필 아이콘(내 이름) → Settings(설정) → 왼쪽 목록 Codex Cloud → Environments 탭 → Create environment.
3. 레포 선택 칸에서 GitHub 연결을 요청하면 Connect GitHub를 누른다. 연결 요청 없이 레포 목록이 바로 보이면 6번으로 간다.
4. GitHub 창이 열리면: GitHub 로그인 → Authorize ChatGPT Codex Connector → Authorize → ChatGPT 창으로 돌아가 6번으로 간다.
5. GitHub 창이 안 열리면:
   1. 주소창 오른쪽의 팝업 차단 표시를 눌러 chatgpt.com 팝업을 허용하고 3번을 다시 누른다.
   2. 그래도 안 열리면 `https://github.com/apps/chatgpt-codex-connector/installations/new`로 들어가 설치할 곳 목록에서 `encore-ai-campus`를 누른다.
   3. 'Update ChatGPT Codex Connector's repository access' 화면에 `encore-ai-campus/aio-03-p2-team3`가 보이면 정상이다. 아무것도 바꾸지 말고 Update access도 누르지 말고 창을 닫는다. 화면이 다르거나 팀 레포가 없으면 사용자에게 캡처를 보낸다.
   4. ChatGPT로 돌아가 2번부터 다시 한다.
6. 레포 목록에 `encore-ai-campus/aio-03-p2-team3`가 보이면 연결된 것이다. Get started는 누르지 말고 창을 닫는다(환경은 공유된 `aio-03-p2-team3`를 쓴다).
7. 2번에서 Codex Cloud가 안 보이거나 6번에서 레포가 안 보이면 사용자에게 알린다.

## 2. 기존 Unpublished 환경을 마무리해 Publish하기 (환경을 만든 사람)
1. Settings > Codex Cloud > Environments에서 `aio-03-p2-team3`를 연다. 레포가 `encore-ai-campus/aio-03-p2-team3`인지 본다. [chatgpt-research ②]
2. 환경을 열면 "Edit aio-03-p2-team3" 대화(Cloud environment setup)가 열린다. 아래쪽 입력창(Ask for follow-up changes)에 아래 요청을 넣는다. 이 대화는 왼쪽 Recents에 구름 아이콘과 함께 남는다. [Request]
3. 넣을 요청(그대로 붙여넣기): [Claude proposal · chatgpt-research ②]
   ```
   Python 3.12와 uv를 쓴다. `uv sync`로 설치하고 `uv run pytest`가 통과하게 준비해 줘.
   API 키와 비밀값은 넣지 않는다. 테스트는 실제 외부 API를 부르지 않는다.
   ```
4. 보고서·설정을 검토한다: Install script에 `uv sync`가 있는지, Python이 3.12인지(`uv run python --version`), `uv run pytest`가 모두 통과했는지. 2026-11-05 결과: Python 3.12.14·uv, `uv sync` 성공, 테스트 9개 통과, 규칙 검사 통과. Codex가 Install script·Start skill·`UV_CACHE_DIR`(쓰기 가능한 uv 캐시 경로, 비밀값 아님)을 설정 초안에 저장했다. [Request]
5. HTTP secrets는 **비워 두고**, Environment variables에는 Codex가 넣은 `UV_CACHE_DIR`만 둔다(키·토큰은 넣지 않는다). Personal vault도 지금은 쓰지 않는다. [Request]
6. 인터넷: Enable all public internet access는 끄고 package managers 허용을 둔다(설치는 PyPI만 닿으면 된다). 설치가 막히면 보고서에 나온 막힌 도메인만 Additional allowed domains에 더한다. 화면 이름은 Enable all public internet access(끔)·Enable package manager domains(켬)·Additional allowed domains(없음)이고, 이 값으로 게시했다. [Claude proposal · Request]
7. 공유 설정은 3절을 따른다.
8. 대화 입력창 위의 Edit environment · Save and publish → 설정 창(Description·Repositories·Scripts·Public internet access·HTTP secrets·Environment variables·Privacy)을 검토 → 오른쪽 아래 Publish(Save draft는 초안만 저장) → "Environment published"가 뜨고 Unpublished 표시가 사라졌는지 본다. 그 뒤 새 작업에서 고를 수 있다. [chatgpt-research ②]
9. 나중에 바꿀 때: … 메뉴 → Edit → 바꿀 것을 말함 → 시험 → 저장 → Republish. 이미 시작한 작업은 옛 상태를 쓰므로 새 작업을 시작해야 반영된다. [chatgpt-research ②]

## 3. Business에서 환경 공유가 되는지 확인하기
공유 방법(Privacy > Who can use → 워크스페이스)은 공식 문서의 Enterprise 절에만 있어 Business에서 되는지 모른다. 아래로 확인한다. [chatgpt-research ⑤ · Claude proposal]
1. 환경을 만든 사람: 설정 창 Privacy의 Who can use(기본 Only me)를 눌러 "Everyone at <워크스페이스 이름>"을 고르고 다시 Publish한다. 2026-11-05 우리 워크스페이스에서 이 선택지가 있어 바꿨다. [Request]
2. 다른 팀원 한 명: 작업을 시작하는 화면(4절 1번)에서 `aio-03-p2-team3`가 보이는지, 골라서 작업이 시작되는지 본다. 이 확인은 아직 하지 않았다.
3. 판정
   - 1번 선택지가 있고 2번에서 보이며 시작된다 → 공유 됨. 모두 이 환경을 쓴다.
   - 선택지가 Private뿐이거나 2번에서 안 보인다 → 공유 안 됨. 팀원마다 2절 순서로 자기 환경을 만든다(같은 요청 문구, 키 없음).
4. 결과는 사용자에게 알려 6단계 기록 때 `.work/STATUS.md`에 남긴다.

## 4. Codex에 작업 맡기기
1. 작업 시작: chatgpt.com 왼쪽 세로 아이콘 줄의 `…` → **Codex**(새 작업은 Codex 화면 왼쪽 위 New chat) → 입력창 위 **Cloud**는 그대로 두고 **Choose environment** → `aio-03-p2-team3` → 입력창(Do anything)에 2번 요청을 쓰고 보낸다. 브랜치를 고르는 칸은 없고, 레포 기본 브랜치 `main`에서 시작한다(2026-11-05 시험에서 변경이 `work → origin/main`으로 비교되고 PR이 `main` 기준으로 열림). 시작한 작업은 Codex 화면 왼쪽 Recents에 구름 아이콘과 함께 남는다. Settings > Codex Cloud > Environments의 `···` 메뉴에는 Edit·Delete environment만 있어 거기서는 시작하지 못한다. [Request · RULES 2절 1번]
2. 요청 문구(빈칸을 채워 붙여넣기). 관련 상태·도구·노드, 수정 범위, 확인 조건은 꼭 적는다. [TASK 이 레포의 규칙 · RULES 2절 4번 · Claude proposal]
   ```
   AGENTS.md부터 읽고 레포 규칙대로 해 주세요.
   작업: <한 줄>
   관련 상태·도구·노드: <상태 필드·도구·노드 이름, 없으면 없음>
   수정 범위: <파일·폴더>
   확인 조건: <완료 기준>. `uv run pytest`와 `python3 .work/check.py`를 직접 실행해 둘 다 통과시키고, 실행 결과를 답에 보여 줄 것.
   테스트는 실제 외부 API를 부르지 말고 가짜 응답으로 한다.
   Issue: #<번호> — 아래에 본문(완료 기준)을 붙임
   <Issue 본문>
   조율함: <팀원>   ← 공통 부분(상태·도구 스키마·노드·엣지)을 고칠 때만
   마지막 답에 .github/pull_request_template.md 양식을 채운 PR 설명을 함께 내 주세요.
   ```
   - 계획 파일의 하위 작업이면 `작업:` 줄에 `docs/plans/<작업명>.md#N 절만 하세요`를 쓴다. 하위 작업마다 새 작업을 시작한다(RULES 7절 4번).
   - 기능이 둘 이상 섞인 요청이면 Codex는 구현하지 않고 계획 파일만 만든다(RULES 7절 1번).
3. 결과 검토: Codex 답에서 바뀐 파일과 실행 결과(`N passed`, `검사 통과`)를 본다. 작업 화면 오른쪽 패널의 Changes(+/−)를 누르면 바뀐 줄을 볼 수 있다. 통과하지 않았거나 수정 범위 밖 파일이 바뀌었으면 같은 작업 입력창(Ask for follow-up changes)에 고칠 점을 보낸다(예: "검사를 통과하게 고쳐 주세요"). [Request · Claude proposal]
4. PR 열기: 작업 화면에는 PR을 여는 버튼이 없다(Changes 창의 아이콘·`···` 메뉴도 보기 기능과 Copy git apply command뿐, 2026-11-05 확인). 같은 작업 입력창에 아래 후속 요청을 보내면 Codex가 새 브랜치에 커밋해 push하고 PR을 연다. 답 맨 앞의 `PR #번호` 링크를 눌러 GitHub로 간다. [Request]
   ```
   이 변경을 새 브랜치에 커밋해 GitHub에 push하고, main으로 PR을 열어 주세요. PR 설명은 앞 답의 양식 그대로 넣고, 답 맨 앞에 PR 링크를 적어 주세요.
   ```
   - 2026-11-05 시험: 브랜치 이름은 Codex가 `docs/<작업명>`처럼 RULES 3절 형식으로 정했고, PR 본문에 양식이 들어갔다. [Request]
   - 본문이 양식대로가 아니면: 본문 오른쪽 위 `···` → Edit → Codex 답의 PR 설명 붙여넣기 → Update comment(RULES 5절 4번).
5. 병합 전 확인: PR 화면 'Files changed'에서 수정 범위 밖 파일이 없는지 보고, 아래 검사 칸에서 `rules-check`·`tests`가 모두 초록 체크(All checks have passed)인지 본다(2026-11-05 시험에서 약 15초). 빨간 X면 병합하지 않고, 그 줄의 Details에서 오류를 복사해 같은 Codex 작업 입력창에 "이 오류를 고쳐 주세요"와 함께 보낸다. [Request · Claude proposal]
6. 병합은 사람이 한다. 초록 체크를 본 뒤 Merge pull request → Confirm merge. 누구나 병합하고, 병합한 브랜치는 지우지 않는다(Delete branch를 누르지 않음, RULES 5절 6번).

## 5. 충돌이 났을 때
1. 규칙: 그 PR에 댓글 `@codex 최신 main에 맞게 충돌을 고쳐 주세요`를 단다(RULES 5절 7번). 이 댓글은 GitHub 연동 흐름이라 Legacy가 맡고, 새 경로에서 만든 PR에도 되는지는 **6단계에서 확인**한다. [Request · chatgpt-research ①]
2. 6단계에서 함께 시험할 방법: 그 PR을 만든 원래 작업(`…` → Codex 화면 왼쪽 Recents)으로 돌아가 같은 문장을 요청하고, 같은 PR이 고쳐지는지 본다. 기존 작업은 자기 파일을 이어 쓰고, 작업 상태는 마지막 실행 뒤 7일까지 되살릴 수 있다. [Request · chatgpt-research ①]
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
- 작업을 시작하는 경로(4절 1번): **확인함**(6-1, 2026-11-05). 공유된 환경이 다른 팀원 화면에 보이는지(3절 2번): 6-2에서 본다.
- PR 여는 순서(4절 4번): **확인함**. 버튼은 없고 후속 요청으로 연다. PR 양식이 본문에 들어갔고, 브랜치 이름은 Codex가 RULES 3절 형식으로 정했다(1회). 팀원 시험에서도 같은지 본다.
- PR 댓글 `@codex`가 동작하는지(5절 1번), 새 경로에서 원래 작업으로 같은 PR을 고칠 수 있는지(5절 2번): 6-2에서 본다.
- 새 작업이 최신 `main`(최근 병합 포함)에서 시작하는지(공식 아님, 커뮤니티 보고): 6-1 시험 PR은 `main` 기준으로 열리고 CI를 통과했다. 앞 팀원의 병합을 반영하는지는 6-2에서 본다.
- 작업 중 끊김·자동 요약: 6-1 시험에서 끊김 없음, 자동 요약은 화면으로 알 수 없었다.
