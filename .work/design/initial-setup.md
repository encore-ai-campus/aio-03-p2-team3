# aio-03-p2-team3 초기 세팅 — 인계 파일 (조사 결과)

작성 2026-11-05, Claude. 다음 대화(1단계)는 이 파일을 첨부해 시작한다. 2단계에서 레포 `.work/design/initial-setup.md`로 커밋한다.
출처 태그: [Request] 사용자 요청·과제 안내 페이지 · [Past work: setup] claude-github-setup · [Past work: aio3] aio-03-p1-team3 · [Claude proposal]

## 1. 목표 [Request]
- 팀 4명, 레포 `encore-ai-campus/aio-03-p2-team3`(새로 만듦).
- 한 대화의 작업량 배분은 claude-github-setup 방식을 따른다.
- 협업은 프로젝트1 Aio3 방식을 따른다(레포가 원본이고 팀원이 AI로 PR을 연다). 이번에는 팀원 모두 ChatGPT로 PR을 연다.
- 만들 것: ChatGPT에서 쓸 초기 세팅(레포 틀과 사용 안내).

## 2. 결정 (2026-11-05 사용자 답변)
- Q1 요금제: 사용자를 포함한 4명 모두 ChatGPT Business다. Codex Cloud를 기본 경로로 하고 Free·Go용 경로는 넣지 않는다. [Request]
- Q2 권한: 조직 Member이고 레포를 만들 권한이 있다. 앱 설치 같은 다른 권한은 사용자가 찾아보거나 조직에 요청한다. 1단계에서 필요한 권한 목록을 만든다. [Request]
- Q3 초기 파일: Claude GitHub 앱으로 Claude가 단계마다 PR을 연다. [Request]
- Q4 공개 범위: Public. [Request]
- Q5 공통 규칙: 한 번 복사한 뒤 팀 레포가 소유한다. 공통 설정 레포에서 업데이트 PR을 보내지 않는다. [Request]
- Q6 병합: 승인 없이 본인을 포함해 누구나 병합한다. 필수 리뷰 같은 브랜치 보호 규칙은 두지 않는다. [Request] AI(ChatGPT·Codex·Claude)는 병합하지 않고 사람이 병합한다. [Past work: setup·aio3] 과제 안내의 병합 전 절차 ①설명 ②검토 ③반영 가운데 ①은 PR 양식에 남기고, ②는 선택(병합 뒤 댓글도 됨)으로 둔다. [Claude proposal]
- PR 크기와 브랜치: PR을 일부러 작게 나누지 않는다. 충돌은 AI가 반영해 고친 뒤 다시 PR로 올린다. 병합한 브랜치는 지우지 않고 남긴다(자동 삭제를 켜지 않는다). [Request]
- Q7 3번째 과제에서 다시 쓸 틀: 따로 템플릿 레포(GitHub Template repository)를 만든다. 다음 과제 때는 'Use this template'으로 새 레포를 만든다. 2~5단계에서 파일을 '공통(다음 과제에도 그대로 씀)'과 '과제별'로 나눠 만들고, TASK.md 파일 지도에 어느 쪽인지 표시한다. [Request·Claude proposal]

## 3. 과제 조건 요약 (노션 '단위 프로젝트 2 안내', 2026-11-05 조회) [Request]
- 목표: LangGraph로 다중 도구 선택과 순환형 워크플로우, 자가 성찰·피드백 루프, 실제 API 데이터 시나리오 시험, 서비스 배포.
- 공식명은 「복합 API 연계 일정 조정 에이전트」이고 주제는 확장해도 된다(식단, 자격증, 정보 탐색 등). 공통 기술 요건은 같다.
- 최소 범위: 조건·누락 확인 → 다중 도구 선택·호출과 다음 노드 결정 → 단기·장기 기억, 컨텍스트·요약 → 오류 감지·수정·재실행·검증 순환 → 실제 API 정상·오류 시나리오 → 성찰 전후 같은 기준 측정 → 배포.
- 상태 설계: 그래프 상태, 단기 기억(Session), 장기 기억, 컨텍스트, 요약. 상태 필드·기억 연동·컨텍스트 관리·오류와 종료를 표로 적는다.
- 필수 산출물: 에이전트 아키텍처 설계서, 에이전트 시험 결과 보고서. 지표는 태스크 완료율, 도구 선택 정확도, 응답 일관성 점수, 평균 재시행 횟수(성찰 전후 비교).
- 저장소·환경: 조직 팀 저장소에 코드·설계서·시험 기록 위치를 정한다. README에 Python 3.12·uv·패키지 버전·실행 명령을 적는다. 환경변수 이름은 .env.example에 두고 키는 서버 환경에 둔다.
- 협업: 작업 등록 → 브랜치 → PR과 담당자 설명 → 리뷰·병합. 상태 객체·도구 스키마·그래프는 고치기 전에 관련 담당자와 조율한다. 같은 파일을 고칠 때도 조율한다.
- AI 사용 허용. 병합 전 ① 담당자가 변경 이유·입출력·상태 변화·오류 처리를 설명 ② 검토자가 정상·오류 요청의 실제 결과를 확인 ③ 담당자가 반영한 뒤 병합. AI에는 관련 상태·도구·노드, 수정 범위, 확인 조건을 전달한다.
- 기록: 설계 결정·오류 사례·수정 이유·버전·재실행 결과를 Issue·PR·팀 노션에 남긴다. README에는 실행 방법, 두 산출물 위치, 팀원별 담당을 적는다.
- 배포: Render 지원. 비밀값은 서버 환경에 두고, 다른 팀이 체험할 수 있게 한다.
- 일정: 11/9(월) 대표 입력·출력과 최소 범위 · 11/13(금) 설계 초안 · 11/18(수) 핵심 구현·시험·배포 정리 · 11/19(목) 오전 배포 주소 공유·상호 체험, 15:00 최종 제출, 15시 발표(20분 + 질의 5분).
- 제출: 설계서, 시험 보고서, 코드 저장소와 README, 배포 주소, PPT.

## 4. 가져올 방식
### 4-1 claude-github-setup [Past work: setup] (doomdiver100T/claude-github-setup, 커밋 9c45959)
- 구성: 진입 파일 → `.work/RULES.md`(공통 규칙) · `.work/TASK.md`(레포 규칙과 파일 지도) · `.work/STATUS.md`(진행기록) · `.work/FLOW.md`(작업 흐름) · `.work/measure.py`·`check.py` · PR 양식('⚠ 규칙 변경' 칸) · CI.
- 원본 경로(template/ 아래): managed/common/.work/RULES.md 17KB · check.py 20.6KB · measure.py 15.1KB · managed/common/.github/pull_request_template.md · managed/common/.github/workflows/rules-check.yml · owned/common/.work/TASK.md.tmpl·STATUS.md.tmpl · managed/common/CLAUDE.md.tmpl.
- RULES 절: 1 원칙(레포가 유일한 원본, 필요한 파일만 읽음, 범위 밖 수정 금지) · 2 시작(최신 main, 열린 PR이 있으면 멈춤) · 3 작업(브랜치·커밋, 비밀값) · 4 규칙 수정(추가·수정·삭제로 병합, 전체 다시 읽기) · 5 끝낼 때(STATUS 갱신, check 통과, 병합은 사람) · 6 진행기록(지금 할 일/대기/보류/최근 완료/이전 기록 요약) · 7 작업량과 단계 작업.
- 7절 요점: 작업량 = 시작 파일 + 읽을 것 + 첨부 + 실행 중 생기는 양(도구 횟수 × 1회 크기: 웹검색 15, 웹페이지 5, MCP 5, 서브에이전트 5, 스크립트 3KB) + 만들 것. 기준 100KB(처음 값). 같은 절차를 다른 입력으로 돌리면 대화를 나눈다. 중간 결과는 파일로 커밋한다. 끊기면 저장된 것을 보고 남은 일만 한다. 단계 안내 형식은 명령어·첨부·읽을 파일·읽지 않을 파일·만들 파일·도구·작업량. 기준을 넘으면 작업 배분량 검토(N-1, N-2…)를 한다.
- ChatGPT용으로 바꿀 점 [Claude proposal]: 진입 파일을 CLAUDE.md 대신 AGENTS.md로 한다(Codex가 읽음). 열린 PR 확인은 `gh api` 대신 GitHub 커넥터로 한다. '공통 설정 레포가 관리' 문구는 Q5를 따른다. 기준 100KB는 처음 값으로 두고 6단계 기록을 보고 맞춘다.

### 4-2 aio-03-p1-team3 [Past work: aio3] (byeon2261/aio-03-p1-team3, public)
- CLAUDE.md 절: 1 시작 전(docs/PROJECT_CONTEXT.md 먼저, 이어서 CONTRACT·OWNERS. Issue 완료 기준을 따르고 PR에 Closes #. 끝나면 PROJECT_CONTEXT 갱신. 역할 변경은 Issue Assignees. 모호하면 질문) · 2 브랜치·커밋·PR(feat/fix/docs, 작업 하나 = PR 하나, 한국어 커밋, AI는 병합 안 함, 리뷰 1명 후 병합 담당자) · 3 담당·공통 파일(공통 파일을 고치면 PR에 이유·영향을 적고 담당자 리뷰) · 4 의존성 버전 고정 · 5 PR 전 check 스크립트와 CI · 6 비밀값·개인정보 · 7 문서는 코드 기준, 그림은 Mermaid.
- 원본 경로: CLAUDE.md 7.5KB · docs/PROJECT_CONTEXT.md 13.4KB(형식 참고) · docs/OWNERS.md 3.9KB · docs/CONTRACT.md 34KB(읽지 않음) · .github/pull_request_template.md 1.2KB · .github/workflows/tests.yml 1.5KB.
- 운영: 남은 작업은 Issue와 Assignees로 관리. 팀원마다 자기 AI 프로젝트에 배경 스냅샷을 첨부.
- 이번에 바꿀 점 [Claude proposal]: CONTRACT.md는 상태 객체·도구 스키마·그래프 노드 계약으로 바꾼다(과제의 '공통 부분 조율'). 병합 규칙은 Q6을 따른다.

## 5. ChatGPT 쪽 사실 (2026-11-05 웹 확인)
- 확인(공식 2곳): Codex Cloud는 Plus·Pro·Business·Enterprise·Edu 대상이고 Free·Go에는 없다 — help.openai.com/en/articles/11369540, developers.openai.com/codex/pricing
- 확인(공식): Codex Cloud는 GitHub 연결 → 레포 선택·환경 만들기 → 작업 → 결과 검토 → PR 열기 순서로 쓴다 — developers.openai.com/codex/cloud
- 확인(공식): Codex는 레포의 AGENTS.md를 지침으로 읽는다(/init로 틀 생성) — openai.com/index/introducing-codex, help 11369540
- 확인(공식 1곳): ChatGPT GitHub 플러그인 기능에 'Write'가 표시된다 — openai.com/business/plugins/github. 채팅에서 PR을 여는 세부 동작은 확인하지 못했다.
- 미확인(커뮤니티 글만): ChatGPT Codex Connector 앱은 레포 소유자마다 따로 설치한다. 조직 Owner가 아니면 Request를 보내고 Owner가 승인한다. 공식 문서로는 '권한이 없으면 GitHub 관리자에게 요청'까지만 확인했다(developers.openai.com/codex/security/setup).
- 아직 안 본 것: Codex 환경의 Python 3.12·uv 설정, 조직 레포에서 @codex review 설정, ChatGPT 프로젝트 지침(문서 작업용).
- Q1에 따라 확인할 것: Business 워크스페이스 설정에서 Codex Cloud와 GitHub 앱이 켜져 있는지, 꺼져 있으면 누가 켜는지(워크스페이스 관리자). 문서 작업용 지침을 팀이 함께 쓸 수 있는 Business 공유 프로젝트 기능.

## 6. 단계 계획 (어림 작업량, 기준 100KB) [Claude proposal]
| 단계 | 누가·어디서 | 할 일 | 만들 것 | 작업량 |
|---|---|---|---|---|
| 1 | Claude 새 대화 | 연결 준비 공식 확인(레포 생성·초대, Claude 앱·Codex 커넥터의 조직 설치·요청, Codex 환경 개요), 수동 준비 안내 | setup-research.md | 약 90KB |
| 수동 | 사용자(GitHub·ChatGPT) | 레포 만들기, 팀원 3명 Write 초대, 앱 설치·승인 요청 | — | — |
| 2 | Claude 새 대화 | 규칙 글 | AGENTS.md, .work/RULES.md, .work/TASK.md, PR 양식, .work/design/ 인계 2개 | 약 88KB |
| 3 | Claude 새 대화 | 진행·과제 문서 | .work/STATUS.md, .work/FLOW.md, docs/PROJECT_CONTEXT.md, docs/OWNERS.md, README, .env.example, pyproject(uv) | 약 80KB |
| 4 | Claude 새 대화 | 검사 도구·CI | .work/measure.py·check.py(복사 후 맞춤), CI, 전체 검사 통과 | 약 70KB |
| 5 | Claude 새 대화 | ChatGPT 사용 안내 | docs/CHATGPT_GUIDE.md(팀원 연결 순서, Codex 환경, 작업 요청 문구, 문서 작업용 ChatGPT 프로젝트 지침) | 약 90KB |
| 6 | 팀원 각자 ChatGPT | 연결 시험: README 팀원 표에 자기 이름을 넣는 PR → 병합. 끊김·요약 여부를 STATUS에 기록 | — | — |
| 7 | Claude 새 대화 | 3번째 과제용 템플릿 레포 만들기(공통 파일 + 과제별 파일 빈 틀 + 시작 안내), 6단계 기록 반영 | 템플릿 레포 | 6단계 뒤에 잼 |
- 단계마다 PR 하나를 열고, 병합한 뒤 다음 단계로 간다. 1단계와 수동 준비는 동시에 해도 된다. 2단계에서 push하기 전에 레포와 Claude 앱 접근이 준비돼 있어야 한다.
- 7단계를 6단계 뒤에 두는 이유: 팀원이 실제로 써 본 결과를 반영한 틀만 다음 과제로 넘긴다. [Claude proposal]

## 7. 1단계 안내
- [ ] 1단계 연결 준비 확인 — 사용자 수동 준비 순서와 setup-research.md가 나옴
  - 명령어: `aio-03-p2-team3 1단계를 시작해 주세요` (이 파일 첨부)
  - 첨부: `p2-team3-handoff.md=13`
  - 읽을 파일: 첨부 파일만
  - 읽지 않을 파일: 두 원본 레포, 메모리·지난 대화
  - 만들 파일: `setup-research.md=6`
  - 도구: `웹검색=3` `웹페이지=4` `스크립트=2`
  - 작업량: 약 90KB(실행 중 71KB 포함) / 기준 100KB
- 할 일: 2절 결정에 맞춰 공식 문서(GitHub Docs, OpenAI help·developers)로 다음을 확인한다.
  ① 조직에 레포 만들기(Public, README 포함), 만든 Member가 받는 레포 권한, 팀원 3명 Write 초대(브랜치 자동 삭제는 끈 채로 둔다)
  ② Member가 Claude GitHub 앱을 조직에 설치 요청하는 방법
  ③ ChatGPT Business에서 GitHub 연결, Codex 커넥터 조직 설치 요청, 워크스페이스 설정(Codex Cloud·GitHub 앱)
  ④ Codex Cloud 환경 만들기 개요
  확인한 핵심 문장과 출처를 요약하지 않고 setup-research.md(6KB 이하)로 저장해 보낸다. 사용자에게 수동 준비 순서와 '조직·워크스페이스에 요청할 권한 목록'(무엇을, 누구에게, 어느 화면에서)을 안내한다.
- 섞지 않을 것: 규칙 글 작성(2단계), 원본 레포 읽기.

## 8. 2단계 결정과 3단계 할 일 (2026-11-05)
### 사용자 결정 [Request]
- 열린 PR과 관계없이 진행한다. 앞 PR 병합 뒤 충돌이 나면 그 PR에서 AI에게 최신 흐름에 맞게 고치게 한다(매번 멈추는 것보다 편함).
- 최신 흐름은 프로젝트1 Aio3의 `docs/PROJECT_CONTEXT.md` 방식으로 한다. '팀원이 고칠 때마다 최신 흐름이 갱신되고, 다음 사람이 그걸 보고 작업하는 문서'의 기능이 우선이다. 영역별 절로 나눠 각 PR은 바꾼 영역의 절만 고친다. 남은 작업은 Issue로 관리한다. `.work/STATUS.md`는 세팅 단계 기록만 한다.
- 큰 작업: 기능이 둘 이상 섞인 요청은 계획 파일(`docs/plans/`)을 먼저 PR로 올리고, 하위 작업마다 새 Codex 작업으로 한다. KB 재기는 세팅 단계 작업에만 쓴다.
### 2단계에서 Claude가 정한 것 [Claude proposal]
- 진입 파일은 `AGENTS.md` 하나만 두고 CLAUDE.md는 두지 않는다.
- PROJECT_CONTEXT의 '마지막 갱신'은 절마다 둔다(맨 위 공용 줄을 모든 PR이 고치면 충돌).
- 공통 부분(상태 객체·도구 스키마·그래프)의 파일 위치는 코드 구조가 정해진 뒤 TASK.md에 적는다. 별도 CONTRACT.md는 만들지 않았다.
- 규칙·PR 양식은 [공통], TASK.md·README·design 파일은 [과제별]로 표시했다.
### 3단계 할 일
- 만들 것: `.work/STATUS.md`(세팅 진행기록, 이 절의 '3단계 안내'를 옮겨 오고 1~2단계를 '최근 완료'에), `.work/FLOW.md`(세팅 단계 목록, 6절 표 기준), `docs/PROJECT_CONTEXT.md`(Aio3 형식 참고, 영역별 절과 절마다 '마지막 갱신'), `docs/OWNERS.md`, `README.md`(실행 방법, 산출물 위치, 팀원별 담당), `.env.example`, `pyproject.toml`(Python 3.12·uv, 버전은 웹에서 확인), `docs/plans/README.md`(계획 파일 형식, RULES 7절). TASK.md 파일 지도도 고친다.
- 읽을 것: 이 절, 프로젝트1 Aio3의 `docs/PROJECT_CONTEXT.md`·`docs/OWNERS.md`(형식 참고), claude-github-setup의 `template/owned/common/.work/STATUS.md.tmpl`·`README.md.tmpl`.
- 섞지 않을 것: 검사 도구·CI(4단계), ChatGPT 사용 안내(5단계).
- 팀원 이름·GitHub 아이디·담당은 사용자에게 묻는다(OWNERS·README).
### 6단계에서 확인할 것
- Codex가 PR을 만들 때 PR 양식과 마지막 답의 PR 설명이 들어가는지, 브랜치 이름을 어떻게 정하는지.
- PR 댓글 `@codex`로 충돌을 고칠 수 있는지(커뮤니티에 실패 보고가 있음).
- Codex Cloud 문서 제목이 "Codex Cloud (Legacy)"로 바뀌어 있다. 새 경로(ChatGPT Work)와의 차이는 5단계에서 확인한다.
### 3단계 안내
- [ ] 3단계 진행·과제 문서 — 위 '만들 것'이 PR로 올라감
  - 명령어: `aio-03-p2-team3 3단계를 시작해 주세요`
  - 첨부: 없음
  - 읽을 파일: `.work/design/initial-setup.md#8. 2단계 결정과 3단계 할 일` `aio3:docs/PROJECT_CONTEXT.md=13.4` `aio3:docs/OWNERS.md=3.9` `setup:STATUS.md.tmpl=0.7` `setup:README.md.tmpl=0.2`
  - 읽지 않을 파일: `.work/design/setup-research.md`, initial-setup.md의 1~7절, 원본 레포의 다른 파일, 메모리·지난 대화
  - 만들 파일: `STATUS.md=3` `FLOW.md=6` `PROJECT_CONTEXT.md=8` `OWNERS.md=2` `README.md=4` `.env.example=1` `pyproject.toml=1` `plans/README.md=2`
  - 도구: `웹검색=3` `웹페이지=3` `스크립트=4`
  - 작업량: 약 142KB(실행 중 72KB 포함) / 기준 100KB — 기준 초과. 병합 후 작업 배분량 검토를 한다(RULES 8절)

### 2단계 작업량 기록 (6단계 기준 맞춤용)
- 계획 약 88KB / 실제는 기준을 넘었다: 첨부 19KB, 원본 읽기 약 32KB, 웹검색 3회(결과가 길어 회당 약 20KB), 만든 것 약 28KB, 질문·답 3번. 같은 대화에서 결정 질문을 두 번 주고받으며 웹검색이 더해졌다. 다음부터 Codex 동작처럼 확인이 필요한 질문은 앞 단계(조사)에서 끝낸다.
