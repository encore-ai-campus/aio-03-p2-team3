# aio-03-p2-team3 1단계 — 연결 준비 확인 결과

작성 2026-11-05, Claude. 2단계 대화에 handoff와 함께 첨부한다.
표시: **확인**(공식 문서) · **미확인**(공식 문서로 못 봄, 화면에서 확인할 것)

## ① 레포 만들기·초대 (GitHub Docs)
- 확인: 조직 Owner가 Member의 레포 생성 가능 여부와 종류(공개·비공개)를 Member privileges에서 정한다. Owner는 항상 모든 종류를 만들 수 있다. — docs.github.com/en/organizations/managing-organization-settings/restricting-repository-creation-in-your-organization
- 확인: "People with admin access to a repository can manage teams and people with access". 순서: 레포 Settings → Access의 Collaborators & teams → Add people → 사람 선택 → Choose a role → Add. — docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/managing-teams-and-people-with-access-to-your-repository
- 미확인: 레포를 만든 Member가 admin 권한을 받는지(위 두 문서에 문장 없음). → 만든 뒤 레포에 Settings 탭이 보이면 admin이다.
- 미확인: 브랜치 자동 삭제의 기본값(공식 페이지 2회 열기 실패). → Settings → General → Pull Requests의 "Automatically delete head branches"가 꺼져 있는지 화면에서 본다.
- 미확인: 팀원이 조직 Member가 아니면(외부 협업자) Owner 설정에 따라 초대가 막힐 수 있다.

## ② Claude GitHub 앱 설치 요청 (GitHub Docs · Claude Code Docs)
- 확인: 조직 Member는 앱 설치를 요청할 수 있고, 설치 권한이 없으면 GitHub이 Owner에게 메일을 보낸다. Owner는 선택한 레포를 바꾸고 설치 여부를 정한다. 요청은 Marketplace가 아니라 앱 공개 설치 페이지 `https://github.com/apps/APP-NAME/installations/new`에서 한다. — docs.github.com/en/apps/using-github-apps/requesting-a-github-app-from-your-organization-owner
- 확인: Claude GitHub 앱 페이지는 github.com/apps/claude. 앱 방식 연결은 공개 레포 전부와 앱이 설치된 비공개 레포에 닿는다. Projects의 스레드는 복제하는 레포마다 앱 설치가 필요하다. — code.claude.com/docs/en/claude-code-on-the-web
- 미확인: 공개 레포에 앱 없이 push·PR이 되는지. → 2단계 전에 설치 승인을 받아 둔다(이 대화가 Project 안이므로 위 문장에 따라 필요).

## ③ ChatGPT Business의 GitHub·Codex 연결 (OpenAI)
- 확인: Codex Cloud는 Plus·Pro·Business·Enterprise·Edu 등이 대상이고 Free·Go에는 없다. — help.openai.com/en/articles/11369540
- 확인(Enterprise 관리자 안내): Workspace Settings > Settings and Permissions의 Codex 부분에서 ChatGPT GitHub Connector를 켜고 "Allow members to use Codex cloud"를 켠다. 사용자는 Connect to GitHub → 자기 계정 허용 → 설치 대상(조직) 선택 → 연결할 레포 허용 순서이고, 이때 GitHub 관리자 승인이 필요할 수 있다. — developers.openai.com/codex/enterprise
- 미확인: Business 워크스페이스의 같은 토글 이름·위치(Business 릴리스 노트에는 Workspace settings > Permissions & Roles가 보이지만 Codex·GitHub 토글은 확인 못 함). → chatgpt.com/codex가 열리고 Connect to GitHub가 되면 켜져 있는 것이다.
- 미확인: 커넥터를 조직에 한 번 설치하면 팀원은 자기 계정 허용만 하면 되는지.

## ④ Codex Cloud 환경 개요 (developers.openai.com/codex/cloud/environments)
- 확인: 환경은 chatgpt.com/codex/settings/environments에서 만든다. 작업 순서: 컨테이너 생성·브랜치 체크아웃 → setup 스크립트(인터넷 허용) → 에이전트 실행(인터넷 기본 꺼짐).
- 확인: 환경 설정의 "Set package versions"로 Python 등 런타임 버전을 고정한다. 기본 이미지는 openai/codex-universal.
- 확인: setup 스크립트·환경변수·비밀값을 바꾸면 캐시가 자동으로 무효화된다.
- 미확인(5단계에서 볼 것): uv 설치 여부와 `uv sync` 뒤 .venv 유지(커뮤니티 글에 문제 보고 있음), @codex review.

## 작업량 기록 (6단계 기준 맞춤용)
- 계획: 웹검색 3, 웹페이지 4 / 실제: 웹검색 3, 웹페이지 6(실패 2). Claude Code 문서 1건이 원문 전체(약 35KB)로 와서 실행 중 양이 계획(71KB)을 넘었다. 다음부터 code.claude.com 페이지는 크다고 보고 5KB 대신 30KB로 잡는다.
