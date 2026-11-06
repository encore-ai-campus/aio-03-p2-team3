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
6. 인터넷: Enable all public internet access는 끄고 package managers 허용을 둔다(설치는 PyPI만 닿으면 된다). 설치가 막히면 보고서에 나온 막힌 도메인만 Additional allowed domains에 더한다. 화면 이름은 Enable all public internet access(끔)·Enable package manager domains(켬)·Additional allowed domains(없음)이고, 이 값으로 게시했다(2026-11-05). Issue 번호만으로 요청하려면 10번대로 `api.github.com` 하나만 더한다. [Claude proposal · Request]
7. 공유 설정은 3절을 따른다.
8. 대화 입력창 위의 Edit environment · Save and publish → 설정 창(Description·Repositories·Scripts·Public internet access·HTTP secrets·Environment variables·Privacy)을 검토 → 오른쪽 아래 Publish(Save draft는 초안만 저장) → "Environment published"가 뜨고 Unpublished 표시가 사라졌는지 본다. 그 뒤 새 작업에서 고를 수 있다. [chatgpt-research ②]
9. 나중에 바꿀 때: … 메뉴 → Edit → 바꿀 것을 말함 → 시험 → 저장 → Republish. 이미 시작한 작업은 옛 상태를 쓰므로 새 작업을 시작해야 반영된다. [chatgpt-research ②]
10. Issue 번호만으로 요청하기(4절 2번) 준비 — 환경을 만든 사람이 한 번 한다: 9번처럼 `…` 메뉴 → Edit로 대화를 열고 → 입력창 위 Edit environment · Save and publish → 설정 창 Public internet access의 Additional allowed domains에 `api.github.com`을 더한다(Enable all public internet access는 끈 채로) → Publish → 그 뒤 시작한 새 작업부터 반영된다. Codex는 이 주소로 요청에 적힌 번호의 Issue 본문만 읽는다(RULES 2절 4번). 더한 뒤에도 Codex가 본문을 못 열면 4절 2번대로 본문을 붙인다. [Request]

## 3. Business에서 환경 공유가 되는지 확인하기
공유 방법(Privacy > Who can use → 워크스페이스)은 공식 문서의 Enterprise 절에만 있어 Business에서 되는지 모른다. 아래로 확인한다. [chatgpt-research ⑤ · Claude proposal]
1. 환경을 만든 사람: 설정 창 Privacy의 Who can use(기본 Only me)를 눌러 "Everyone at <워크스페이스 이름>"을 고르고 다시 Publish한다. 2026-11-05 우리 워크스페이스에서 이 선택지가 있어 바꿨다. [Request]
2. 다른 팀원 한 명: 작업을 시작하는 화면(4절 1번)에서 `aio-03-p2-team3`가 보이는지, 골라서 작업이 시작되는지 본다. 이 확인은 아직 하지 않았다.
3. 판정
   - 1번 선택지가 있고 2번에서 보이며 시작된다 → 공유 됨. 모두 이 환경을 쓴다.
   - 선택지가 Private뿐이거나 2번에서 안 보인다 → 공유 안 됨. 팀원마다 2절 순서로 자기 환경을 만든다(같은 요청 문구, 키 없음).
4. 결과는 사용자에게 알려 6단계 기록 때 `.work/STATUS.md`에 남긴다.

## 4. Codex에 작업 맡기기
팀원 절차는 세 단계다: ① 요청 보내기(1·2번) → ② PR 확인(3번) → ③ 병합(4번). Codex는 레포의 `AGENTS.md`를 자동으로 읽고 그 지시대로 규칙 파일을 연다. 그래서 요청 문구에 'AGENTS.md부터 읽으라'는 말을 쓰지 않는다. Codex는 요청 문구에 적지 않아도 `AGENTS.md`의 'Codex가 꼭 할 일'대로 검사·테스트 실행 → push → PR 열기 → 답 맨 앞 PR 링크까지 한다. 답에 PR 링크가 없으면 5번(예비)을 쓴다. 충돌은 5절. [Request]
1. 작업 시작: chatgpt.com 왼쪽 세로 아이콘 줄의 `…` → **Codex**(새 작업은 Codex 화면 왼쪽 위 New chat) → 입력창 위 **Cloud**는 그대로 두고 **Choose environment** → `aio-03-p2-team3` → 입력창(Do anything)에 2번 요청을 쓰고 보낸다. 브랜치를 고르는 칸은 없고, 레포 기본 브랜치 `main`에서 시작한다(2026-11-05 시험에서 변경이 `work → origin/main`으로 비교되고 PR이 `main` 기준으로 열림). 시작한 작업은 Codex 화면 왼쪽 Recents에 구름 아이콘과 함께 남는다. Settings > Codex Cloud > Environments의 `···` 메뉴에는 Edit·Delete environment만 있어 거기서는 시작하지 못한다. [Request · AGENTS.md 'Codex가 꼭 할 일' 1번]
2. 요청 문구(빈칸을 채워 붙여넣기). 관련 상태·도구·노드, 수정 범위, 확인 조건은 꼭 적는다. [TASK 이 레포의 규칙 · RULES 2절 4번 · Claude proposal] 검사·테스트·push·PR은 레포 규칙이 정하므로 요청에 적지 않는다. [Request]
   ```
   작업: <한 줄>
   관련 상태·도구·노드: <상태 필드·도구·노드 이름, 없으면 없음>
   수정 범위: <파일·폴더>
   확인 조건: <완료 기준>
   Issue: #<번호>
   조율함: <팀원>   ← 공통 부분(상태·도구 스키마·노드·엣지)을 고칠 때만
   ```
   - `Issue:` 줄에는 번호만 적는다. Codex가 GitHub에서 그 Issue 본문(완료 기준)을 읽는다(2절 10번을 마친 환경, RULES 2절 4번). Codex가 `Issue #번호 본문을 열지 못했습니다. 본문을 붙여 주세요.`라고 답하면, 같은 작업 입력창에 Issue 본문을 붙여 다시 보낸다. [Request]
   - 계획 파일의 하위 작업이면 `작업:` 줄에 `docs/plans/<작업명>.md#N 절만 하세요`를 쓴다. 하위 작업마다 새 작업을 시작한다(RULES 7절 4번).
   - 기능이 둘 이상 섞인 요청이면 Codex는 구현하지 않고 계획 파일만 만든다(RULES 7절 1번).
3. PR 확인: Codex 답에서 실행 결과(`N passed`, `검사 통과`)를 보고, 답 맨 앞의 `PR #번호` 링크를 눌러 GitHub로 간다. PR 화면 'Files changed'에서 수정 범위 밖 파일이 없는지 보고, 아래 검사 칸에서 `rules-check`·`tests`·`pr-check`가 모두 초록 체크(All checks have passed)인지 본다(2026-11-05 시험에서 약 15초). PR에 올라간 내용의 테스트는 GitHub CI가 맡으므로 Codex에게 PR 뒤 CI 결과를 다시 확인하게 하지 않는다(작업 중 인터넷이 막혀 읽을 수 있는지 모른다). [Request · Claude proposal]
   - 빨간 X거나 범위 밖 파일이 바뀌었으면 병합하지 않는다. 그 줄의 Details에서 오류를 복사해(범위 밖이면 고칠 점을 적어) 같은 Codex 작업 입력창(Ask for follow-up changes)에 "이 오류를 고쳐 주세요"와 함께 보낸다.
   - 본문이 양식대로가 아니면: 본문 오른쪽 위 `···` → Edit → Codex 답의 PR 설명 붙여넣기 → Update comment(AGENTS.md 'Codex가 꼭 할 일' 4번). 본문을 고치면 `pr-check`가 다시 돈다. `pr-check`가 빨간 X면 '읽은 파일'·'최신 흐름 갱신' 칸 문제이니 오류를 같은 작업에 보내 PR 설명을 다시 받는다.
   - Codex에 병합을 맡길 때(4번 나)도 이 확인(범위 밖 파일, 초록 체크)은 직접 한다.
4. 병합: 초록 체크를 본 뒤 둘 중 하나로 한다. 누구나 병합하고, 병합한 브랜치는 지우지 않는다(Delete branch를 누르지 않음, RULES 5절 6번). [Request]
   - 가. GitHub에서 직접: PR 화면 Merge pull request → Confirm merge.
   - 나. Codex에 맡기기: 같은 Codex 작업 입력창에 `병합해 주세요`를 보낸다. Codex는 필수 검사(`rules-check`·`tests`·`pr-check`)가 모두 통과했을 때만 병합하고, 아니면 `검사가 끝난 뒤 다시 요청해 주세요.`라고 답한다(AGENTS.md 'Codex가 꼭 할 일' 6번). 그렇게 답하면 PR 화면에서 초록 체크를 본 뒤 다시 보내거나 가로 병합한다.
   - `main`에는 Ruleset 'main 필수 검사'가 있다(`rules-check`·`tests` 필수, strict 끔, Bypass 없음, 삭제·강제 push 막기, 2026-11-06 GitHub 기록으로 확인, `pr-check`는 6-3-2 병합 뒤 사용자가 더함). 두 검사가 통과하기 전에는 GitHub이 병합을 막는다(실제로 막히는지는 7절에서 본다).
5. 예비 — 답에 PR 링크가 없을 때: 작업 화면에는 PR을 여는 버튼이 없다(Changes 창의 아이콘·`···` 메뉴도 보기 기능과 Copy git apply command뿐, 2026-11-05 확인). 같은 작업 입력창에 아래 후속 요청을 보내면 Codex가 새 브랜치에 커밋해 push하고 PR을 연다(6-1 시험에서 이 방법으로 엶). 그 뒤 3번부터 한다. [Request]
   ```
   이 변경을 새 브랜치에 커밋해 GitHub에 push하고, main으로 PR을 열어 주세요. PR 설명은 앞 답의 양식 그대로 넣고, 답 맨 앞에 PR 링크를 적어 주세요.
   ```
   - 2026-11-05 시험: 브랜치 이름은 Codex가 `docs/<작업명>`처럼 RULES 3절 형식으로 정했고, PR 본문에 양식이 들어갔다. [Request]

## 5. 충돌이 났을 때
1. 규칙: 그 PR에 댓글 `@codex 최신 main에 맞게 충돌을 고쳐 주세요`를 단다(RULES 5절 7번). 이 댓글은 GitHub 연동 흐름이라 Legacy가 맡고, 새 경로에서 만든 PR에도 되는지는 **6단계에서 확인**한다. [Request · chatgpt-research ①]
2. 6단계에서 함께 시험할 방법: 그 PR을 만든 원래 작업(`…` → Codex 화면 왼쪽 Recents)으로 돌아가 같은 문장을 요청하고, 같은 PR이 고쳐지는지 본다. 기존 작업은 자기 파일을 이어 쓰고, 작업 상태는 마지막 실행 뒤 7일까지 되살릴 수 있다. [Request · chatgpt-research ①]
3. 둘 다 안 되면 GitHub 웹 화면에서 고치거나, PR을 닫고 최신 `main`에서 같은 작업을 다시 낸다(RULES 5절 7번).
4. 6-2 결과(PR #26, 2026-11-05): 원래 Codex 작업에 후속 요청을 보내 같은 PR을 고쳤다(팀원 작업 창 캡처로 확인, 2026-11-06). GitHub 기록과도 맞는다: PR에 `@codex` 댓글이 없고, 같은 브랜치에 팀원 계정으로 고침 커밋 2개(README 충돌 해결, 최신 `main` 병합)가 올라간 뒤 병합됐다. 2번 방법은 1회 동작했고, 1번 댓글은 아직 시험하지 않았다. [Request · Claude proposal]

## 6. 문서 작업용 ChatGPT 프로젝트
설계서·보고서·발표 원고처럼 대화로 다듬는 일에 쓴다. 레포 파일을 바꾸는 일은 4절의 Codex 작업으로 PR을 연다. [Claude proposal]
ChatGPT 프로젝트(아래 지침 포함)는 Codex 작업에 쓰이지 않는다. 프로젝트 지침은 그 프로젝트 대화에만 적용되고 Codex 작업은 `…` → Codex에서 따로 시작하며, 둘을 잇는 방법은 공식 문서에 없다(2026-11-06 확인). Codex가 따를 규칙은 레포 `AGENTS.md`에 둔다. [Claude proposal · step6-3-handoff]
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
- PR 여는 순서(4절 2·5번): 6-1에서는 버튼이 없어 후속 요청으로 열었다(**확인함**, PR 양식이 본문에 들어갔고 브랜치 이름은 Codex가 RULES 3절 형식으로 정함, 1회). 6-1-2에서 요청 한 번으로 PR까지 가게 했다(처음엔 요청 문구에 넣었고, 뒤에 RULES 5절 3·4번으로 옮겨 요청 문구에서 뺌). PR #26 팀원 시험(2026-11-05, 팀원 작업 창 캡처로 확인)에서는 첫 요청에 README 수정과 로컬 검사까지만 하고 PR을 열지 않아 4절 5번 예비 후속 요청으로 열었다. 그래서 6-3-1-2에서 PR 열기를 자동으로 읽히는 `AGENTS.md` 'Codex가 꼭 할 일'로 옮겼다. 첫 요청 한 번에 PR이 열리는지, 답 맨 앞에 PR 링크가 있는지, 본문 양식·브랜치 이름이 같은지: 6-3-1-2 병합 뒤 다음 팀원 작업에서 본다.
- Codex 병합(4절 4번 나): PR #26에서 팀원이 병합을 요청하자 Codex가 `tests`가 끝나기 전에 병합했다(병합 09:00:38Z, `tests` 완료 09:00:41Z, GitHub 기록). 6-3-1-2에서 병합 조건을 `AGENTS.md`에 두었고, Ruleset 'main 필수 검사'는 **확인함**(사용자가 만들어 `main`에 적용, `rules-check`·`tests` 필수, strict 끔, Bypass 없음, 삭제·강제 push 막기, 2026-11-06 GitHub 기록). Ruleset이 검사 전 병합을 실제로 막는지, Codex가 검사 통과를 보고 병합하거나 '검사가 끝난 뒤 다시 요청해 주세요'라고 답하는지: 다음 팀원 작업에서 본다.
- PR 댓글 `@codex`가 동작하는지(5절 1번): 6-2에서 본다(아직 시험 안 함). 새 경로에서 원래 작업으로 같은 PR을 고칠 수 있는지(5절 2번): PR #26에서 1회 됨(5절 4번, 팀원 작업 창 캡처·GitHub 기록으로 확인).
- 요청 문구 첫 줄('AGENTS.md부터 읽고 …') 없이도 Codex가 레포 규칙(`AGENTS.md` 'Codex가 꼭 할 일')대로 검사·테스트·push·PR까지 하는지(6-3-1에서 뺌): 6-3-1 병합 뒤 첫 팀원 작업에서 본다. 답 맨 앞 PR 링크와 PR 본문 양식으로 판단한다.
- `Issue: #번호`만으로 Codex가 Issue 본문을 읽는지(2절 10번을 마친 뒤): 첫 Issue 작업에서 본다. 못 읽으면 Codex 답의 '본문을 붙여 주세요'와 그때 환경 설정을 남긴다.
- 새 작업이 최신 `main`(최근 병합 포함)에서 시작하는지(공식 아님, 커뮤니티 보고): 6-1 시험 PR은 `main` 기준으로 열리고 CI를 통과했다. 앞 팀원의 병합을 반영하는지는 6-2에서 본다.
- 작업 중 끊김·자동 요약: 6-1 시험에서 끊김 없음, 자동 요약은 화면으로 알 수 없었다.
