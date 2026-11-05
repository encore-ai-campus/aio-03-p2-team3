# aio-03-p2-team3 5-1단계 — Codex·ChatGPT 공식 확인 결과

작성 2026-11-05, Claude. 5-2단계(`docs/CHATGPT_GUIDE.md`)의 근거다. `.work/design/setup-research.md`에서 확인한 것(플랜 대상, GitHub 연결 순서, Legacy 환경 개요)은 다시 적지 않는다.
표시: **확인**(공식 문서) · **미확인**(공식 문서로 못 봄, 화면에서 확인할 것) · **어긋남**(공식 문서끼리 다름)
출처 약칭: [CE] learn.chatgpt.com/docs/environments/cloud-environments(사용자가 붙여넣은 본문, 2026-11-05) · [LG] developers.openai.com/codex/environments/cloud-environment · [IA] developers.openai.com/codex/cloud/internet-access · [WC] help.openai.com/en/articles/20001275 · [UC] help.openai.com/en/articles/20001545 · [PJ] help.openai.com/en/articles/10169521 · [BR] help.openai.com/en/articles/11391654

## ① 새 Codex Cloud와 Codex Cloud (Legacy)
- 확인: Legacy는 Code Review와 Linear·GitHub 연동을 계속 지원하고, OpenAI는 Legacy를 없앨 계획이다. [CE] 넘어가는 동안 Code Review, Security Review, 기존 Linear·GitHub 연동 흐름은 Legacy를 쓴다. [UC][WC]
- 확인: Legacy 환경은 사용자가 시작할 때만 새 경로로 옮겨지고, 원래 환경은 그대로 남는다. [UC]
- 확인: 새 경로에서 작업 시작은 웹·데스크톱 앱의 Work in > Cloud에서 게시된 환경을 고르고 요청을 쓴다. 모바일은 Codex를 열고 환경을 고른다. 환경은 웹·데스크톱에서만 만든다. [CE]
- 확인: 새 경로는 setup·maintenance 스크립트 대신 Codex가 레포를 살펴 준비·시험하고, 결과를 Install script(의존성 설치)·Start skill(서비스 시작·준비 확인)에 적는다. 스크립트를 직접 쓰지 않아도 된다. [CE] Legacy는 setup 스크립트를 직접 쓰고 자동 설치는 npm·yarn·pnpm·pip·pipenv·poetry만이다(uv 없음). [LG]
- 확인: 새 경로는 새 작업마다 게시된 환경의 준비된 파일에서 시작하고, 기존 작업은 자기 파일(커밋 안 한 변경 포함)을 이어 쓴다. 작업 VM 상태는 마지막 실행 뒤 7일까지 되살릴 수 있다. 저장 상태는 버전 관리를 대신하지 않는다. [CE][UC]
- 확인: 새 경로의 결과는 "변경과 시험 결과를 검토한 뒤 커밋하거나 PR을 연다". [CE] PR을 여는 버튼·순서는 문서에 없다. → 미확인, 6단계 연결 시험에서 화면으로 본다.
- 참고(공식 아님): OpenAI 커뮤니티 글에 새 경로에서 최근 병합이 빠진 채 시작, 커밋을 따로 요청해야 함 같은 보고가 있다. 6단계에서 확인할 항목으로만 둔다.
- 영향: RULES 5절 7번의 PR 댓글 `@codex …`는 GitHub 연동 흐름이라 Legacy에 기댄다. Legacy가 없어지면 바꿔야 한다(규칙 변경은 요청자가 정함).

## ② 환경 만들기·Python 3.12·uv (새 경로) [CE]
- 확인: 만드는 곳은 새 작업에서 Work in > Cloud → Select environment → Create environment, 또는 Settings > Codex Cloud > Environments > Create environment. 순서: GitHub 레포 고르기(필요하면 GitHub 연결) → Get started → 요청받은 값 넣기(버전·명령·서비스를 지정해 요청할 수 있음) → 보고서·설정 검토 → Publish → Environment published 뒤 Start a new task.
- 확인: 설정을 바꾸려면 환경의 … 메뉴 → Edit → 바꿀 것을 말함 → 시험 → 저장 → Republish. 기존 작업은 옛 상태를 그대로 쓰므로 새 작업을 시작해야 반영된다. 게시 전 환경은 Unpublished 표시가 붙고 작업에 못 쓴다.
- 미확인: uv가 미리 깔려 있는지, Python 3.12를 고르는 별도 칸이 있는지(새 문서에 없음). → 환경을 만들 때 "Python 3.12와 uv를 쓰고 `uv sync` 뒤 `uv run pytest`가 통과하게 준비해 줘"라고 요청하고 Install script에 적힌 명령을 확인한다. Legacy는 Set package versions로 Python 버전을 고정한다. [LG]
- 확인: Business 플랜 작업 VM은 4 vCPU·16 GiB·디스크 32 GiB.
- 확인: 레포에 둔 skill은 클라우드 작업에서 쓰인다. 컴퓨터·브라우저 사용은 아직 안 된다.

## ③ 환경변수·비밀값 (새 경로) [CE]
- 확인: 환경 설정에서 Environment variables 또는 HTTP secrets 옆 Manage로 넣는다.
  - Environment variable: 프로그램에 실제 값이 그대로 간다.
  - Network secret(HTTP secrets): 프로그램은 자리표시만 받고, 프록시가 허용 도메인으로 가는 HTTPS(443) 요청에서만 실제 값으로 바꾼다. 설치·작업 중 모두 된다. Key·Value·Allowed domains를 넣는다. 프로그램이 실제 값을 읽어야 하면 Environment variables에 둔다.
- 확인: Personal vault(Settings > Codex Cloud → Personal vault 탭 → Add → Type·Key·Value → Applies to)에 자기 값을 두면, 공유 환경이 요청한 값만 작업에 들어간다. 공유하면 요구 사항만 공유되고 자기 값은 공유되지 않는다.
- 확인: Legacy의 secrets는 setup 스크립트에서만 쓰이고 에이전트 단계 전에 지워진다. 환경변수는 작업 내내 있다. [LG]
- 영향: 이 레포는 키를 Codex 환경 비밀값에 둔다(TASK.md). 새 경로에서 SDK가 키를 직접 읽으면(`GEMINI_API_KEY` 등) Network secret으로는 안 되고 Environment variable 또는 Personal vault 환경변수로 둬야 한다. 실제 키 대신 시험 중에는 넣지 않는 것도 고를 수 있다(5-2에서 안내, 결정은 요청자).

## ④ 작업 중 인터넷 접근
- 확인(새 경로): Enable all public internet access를 켜면 전체 공개 인터넷, 끄면 package managers 허용과 Additional allowed domains에 적은 곳만 닿는다. 환경 소유 Network secret을 저장하면 그 도메인이 허용 목록에 더해진다. [CE] 새 문서에는 기본값이 적혀 있지 않다. → 미확인, 환경 설정 화면에서 본다.
- 확인(Legacy): setup 스크립트는 인터넷이 켜져 있고, 에이전트 단계는 기본으로 꺼져 있다. 켤 때 허용 목록은 None·Common dependencies·All(unrestricted)에서 고르고 도메인을 더할 수 있다. [IA][LG]
- 영향: RULES 2절 4번의 "Codex는 작업 중 인터넷이 꺼져 있어 Issue를 열지 못할 수 있다"는 Legacy 기준이다. 새 경로에서도 GitHub API가 허용 목록에 없으면 같다.

## ⑤ ChatGPT Work와 플랜
- 확인: ChatGPT는 Chat과 Work로 나뉘고, Work는 긴 여러 단계 작업용 에이전트, Codex는 개발 작업용으로 남는다. Codex Cloud 권한은 Work Cloud·Codex Local과 따로 관리된다. [WC]
- 어긋남: [WC]는 Work가 EKM을 켠 Enterprise·Edu 워크스페이스용이라고 적는다. [BR](Business 릴리스 노트)은 데스크톱 전환에서 Work를 고를 수 있다고 적고, Sites를 Work에서 시작하라고 한다. → 우리 Business 워크스페이스에서 Work가 보이는지 화면에서 확인한다. 새 Codex Cloud의 시작 경로가 Work in > Cloud라서 영향이 있다.
- 확인: 환경 공유 방법(Privacy > Who can use → 워크스페이스)은 "Enterprise 워크스페이스" 절에 있다. [CE] → Business에서 공유가 되는지 미확인. 안 되면 팀원마다 환경을 만든다.

## ⑥ ChatGPT 프로젝트 지침을 넣는 곳 [PJ]
- 확인: 프로젝트의 ••• 메뉴 → Project settings에 지침을 넣는다. 프로젝트 지침은 그 프로젝트에서만 쓰이고 전역 맞춤 지침보다 우선한다.
- 확인: 프로젝트 만들기는 사이드바 New project → 이름. 파일은 Project settings가 아니라 Sources 탭으로 옮겨졌다. [PJ] · Enterprise·Edu 릴리스 노트(2026-02-23)
- 확인: Work에서도 프로젝트를 열고 Work를 고르면 프로젝트 맥락을 쓴다. [WC]
- 미확인: Business에서 프로젝트를 팀원과 공유하는 방법(공유 소개는 Enterprise·Edu 릴리스 노트에서만 봄).

## 작업량 기록
- 계획: 웹검색 2, 웹페이지 3 / 실제: 웹검색 3, 웹페이지 2(거절 1, 실패 1), 사용자 붙여넣기 1(약 14KB). learn.chatgpt.com은 검색 결과 본문 속 주소라 도구가 거절했다. 다음부터 이 주소는 처음부터 붙여넣기를 받는다.
