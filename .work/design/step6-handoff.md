# 6단계 인계 — Codex 작업 시작 경로 찾기와 팀원 메시지

작성 2026-11-05, Claude. 5-2 대화가 길어져 6-1단계(새 대화)로 넘기는 인계다. 6-1에서 읽고, 6-1을 마치면 결과를 `docs/CHATGPT_GUIDE.md`에 옮긴 뒤 이 파일은 기록으로 둔다. [Request · Claude proposal]

## 화면에서 본 것 (2026-11-05, 사용자 캡처)
- Settings > Codex Cloud: Environments·Personal vault 탭, Search, + Create environment. 목록에 `aio-03-p2-team3`(encore-ai-campus/aio-03-p2-team3), Sharing "Shared by you", 줄 끝 `···` 메뉴. **줄(이름)을 눌러도 열리지 않는다.** `···` 메뉴 안은 아직 안 봄.
- 환경 설정 창(게시할 때 본 것): Description · Repositories · Scripts(Install script, Start skill) · Public internet access · HTTP secrets · Environment variables(`UV_CACHE_DIR`) · Privacy(Who can use: Everyone at 엔코아 AI 캠퍼스) · Advanced › · Save draft / Publish.
- 환경 준비 대화: 제목 "Edit aio-03-p2-team3", 화면 "Cloud environment setup", 입력창 "Ask for follow-up changes", 입력창 아래 `⚙ Custom`과 모델 선택(GPT-6.1 Sol Medium), 입력창 위 "Edit environment · Save and publish". 왼쪽 Recents에 구름 아이콘이 붙어 남는다(같은 이름 대화가 둘 있음).
- 웹 Work 화면: 위쪽 Chat/Work 전환, 입력창 "Work with ChatGPT", 입력창 아래 Choose project · Files · Plugins · Open desktop app. "Work in" 메뉴 없음.
- 데스크톱 앱 Work 화면: 입력창 "ChatGPT로 Work 시작", 입력창 아래 `+`·`승인 요청`·모델 선택, 오른쪽 위 아이콘 둘. `+` 메뉴: 파일 및 폴더 · 프로젝트에서 Work 시작 · 스케치 · Google Contacts·Calendar·Gmail·Drive · Documents · PDF …(스크롤 더 있음, 끝까지는 안 봄). Cloud 항목은 보이는 범위에 없음.
- 왼쪽 세로 아이콘 줄(집, 그 아래 아이콘들, `…`, 격자, 폴더): 이름은 아직 안 봄.

## 6-1에서 확인할 후보 (위에서부터)
1. Environments 목록 줄 끝 `···` 메뉴 안(새 작업 시작 같은 항목이 있는지)
2. "Edit aio-03-p2-team3" 대화 입력창 아래 `⚙ Custom` 메뉴(환경·클라우드 선택이 있는지)
3. 데스크톱 `+` 메뉴를 끝까지 내린 아래쪽
4. 왼쪽 세로 아이콘 줄의 이름(마우스를 올려 봄)
5. 그래도 없으면 공식 문서(새 Codex Cloud 작업 시작)를 한 번 찾는다. learn.chatgpt.com은 웹페이지 도구가 거절하므로 처음부터 사용자에게 본문 붙여넣기를 받는다(5-1에서 배운 것).

## 정한 것
- Codex가 검사를 직접 실행하고 결과를 답에 보여 준다. 팀원은 답의 `9 passed`·`검사 통과`와, PR 화면의 CI(`rules-check`·`tests`) 초록 체크를 보고 병합한다. 빨간 X면 병합하지 않고 Details의 오류를 Codex 작업에 보낸다. [Request · Claude proposal]
- 사용자가 먼저 자기 줄로 한 번 해 보고(시작 버튼·PR 버튼 이름 확인), 그 뒤 팀원에게 보낸다. [Claude proposal]
- 팀원은 모두 GitHub 연결을 마쳤다. 환경은 공유된 `aio-03-p2-team3` 하나를 쓴다. [Request]

## 팀원 메시지 초안 ([ ]는 6-1에서 실제 이름으로 채움)
```
안녕하세요. Codex 연결 시험 2단계입니다(10~20분 정도).

① 작업 시작
[6-1에서 확인한 경로] → 환경 'aio-03-p2-team3' → 브랜치 main 선택

② 아래 요청을 붙여넣고 보내기(<이름>만 바꿔 주세요)

AGENTS.md부터 읽고 레포 규칙대로 해 주세요.
작업: README.md 팀원 표의 제 줄(<이름>)에 한 줄 소개를 넣어 주세요.
관련 상태·도구·노드: 없음
수정 범위: README.md 팀원 표의 제 줄만
확인 조건: `uv run pytest`와 `python3 .work/check.py`를 직접 실행해 둘 다 통과시키고, 실행 결과를 답에 보여 주세요.
마지막 답에 .github/pull_request_template.md 양식을 채운 PR 설명을 함께 내 주세요.

③ Codex 답 확인
- 바뀐 파일이 README.md 한 줄뿐인지
- 실행 결과에 '9 passed'와 '검사 통과'가 보이는지
(아니면 같은 작업 입력창에 "검사를 통과하게 고쳐 주세요"라고 보내 주세요)

④ PR 열고 확인
1. Codex 답 근처의 [PR 버튼] 클릭 → GitHub PR 화면이 열림
2. 'Files changed' 탭에서 README.md 한 줄만 바뀌었는지 확인
3. PR 화면 아래쪽 검사 칸에서 rules-check와 tests가 모두 초록 체크(All checks have passed)가 될 때까지 1~2분 기다리기
   - 빨간 X가 뜨면 병합하지 말고, 그 줄의 Details를 눌러 오류 내용을 복사한 뒤 Codex 작업 입력창에 "이 오류를 고쳐 주세요"와 함께 보내 주세요
4. PR 본문이 양식대로가 아니면: 본문 오른쪽 위 ··· → Edit → Codex 마지막 답의 PR 설명 붙여넣기 → Update comment

⑤ 병합
초록 체크를 확인한 뒤 'Merge pull request' → 'Confirm merge'('Delete branch'는 누르지 않기)

⑥ 충돌이 났을 때('This branch has conflicts' 표시)
1. PR 화면 맨 아래 댓글 칸에 "@codex 최신 main에 맞게 충돌을 고쳐 주세요" 입력 → Comment
2. 5분 안에 새 커밋이 안 생기면: ChatGPT 왼쪽 Recents에서 그 작업 클릭 → 같은 문장 보내기
3. 충돌 표시가 사라지고 초록 체크가 뜨면 ⑤대로 병합

끝나면 아래 다섯 가지를 답장으로 알려 주세요.
1. ①의 시작 경로가 맞았는지(다르면 실제 경로)
2. ④-1의 PR 버튼 이름
3. PR 본문에 양식이 들어갔는지, 브랜치 이름은 무엇이었는지
4. 충돌이 났다면 ⑥-1과 ⑥-2 중 무엇이 됐는지
5. 작업 중 끊김이나 자동 요약이 있었는지

감사합니다!
```
