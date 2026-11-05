# 세팅 작업 흐름

이 레포의 초기 세팅 단계 목록이다. 단계마다 새 대화(또는 팀원 각자의 ChatGPT)에서 한 단계씩 하고, 단계마다 PR 하나를 연 뒤 병합하고 다음 단계로 간다. [Past work: setup]
단계별 결정의 근거는 `.work/design/initial-setup.md`(6절 단계 계획, 8절 2단계 결정과 3단계 할 일)에 있다. 진행 상황과 다음 단계 안내는 `.work/STATUS.md`에 둔다. [Past work: setup]
작업량 재기·나누기는 `.work/RULES.md` 8절을 따른다. 아래 작업량은 계획 값이고, 실제 값은 STATUS.md '최근 완료'에 남긴다.
도구 횟수 표기: 웹검색·웹페이지·스크립트·MCP·서브에이전트 = 예상 횟수.

## 1단계 연결 준비 확인 (완료)
- 할 일: 공식 문서로 조직 레포 만들기·팀원 Write 초대, Claude GitHub 앱 조직 설치 요청, ChatGPT Business의 GitHub 연결·Codex 커넥터·워크스페이스 설정, Codex Cloud 환경 개요를 확인하고 사용자에게 수동 준비 순서를 안내한다. [Request]
- 읽을 것: 인계 파일(이후 `.work/design/initial-setup.md`)
- 만들 것: `.work/design/setup-research.md`
- 섞지 않을 것: 규칙 글 작성(2단계), 원본 레포 읽기
- 도구: 웹검색 3, 웹페이지 4, 스크립트 2

## 수동 준비 (사용자, 완료)
- 할 일: 레포 만들기(Public, README 포함, 브랜치 자동 삭제 끔), 팀원 3명 Write 초대, Claude 앱과 ChatGPT Codex Connector 설치·승인 요청. [Request]
- 읽을 것: `.work/design/setup-research.md`
- 만들 것: 없음(GitHub·ChatGPT 화면 작업)
- 섞지 않을 것: 레포 파일 작성
- 도구: 없음

## 2단계 규칙 글 (완료)
- 할 일: 진입 파일과 공통·레포 규칙, PR 양식을 만들고 1단계 결과와 인계 파일을 `.work/design/`에 커밋한다. [Request]
- 읽을 것: `.work/design/initial-setup.md`, `.work/design/setup-research.md`, claude-github-setup·프로젝트1 Aio3의 규칙 원본
- 만들 것: `AGENTS.md`, `.work/RULES.md`, `.work/TASK.md`, `.github/pull_request_template.md`, `.work/design/` 2개
- 섞지 않을 것: 진행·과제 문서(3단계)
- 도구: 웹검색 3

## 3단계 진행·과제 문서 — 3-1, 3-2로 나눔(2026-11-05, 기준 초과 약 142KB)

## 3-1단계 진행 문서 (완료)
- 할 일: 세팅 진행기록, 이 작업 흐름, 최신 흐름 문서, 계획 파일 형식을 만들고 TASK.md 파일 지도를 고친다. [Request]
- 읽을 것: `.work/design/initial-setup.md#8. 2단계 결정과 3단계 할 일 (2026-11-05)`, 프로젝트1 Aio3의 `docs/PROJECT_CONTEXT.md`(형식 참고), claude-github-setup의 `template/owned/common/.work/STATUS.md.tmpl`
- 만들 것: `.work/STATUS.md`, `.work/FLOW.md`, `docs/PROJECT_CONTEXT.md`, `docs/plans/README.md`
- 섞지 않을 것: README·.env.example·pyproject(3-2), 검사 도구·CI(4단계), ChatGPT 사용 안내(5단계)
- 도구: 스크립트 3

## 3-2단계 실행 환경
- 할 일: [Request]
  1. `README.md`: 실행 방법, 두 산출물(설계서·시험 보고서)의 위치(`docs/PROJECT_CONTEXT.md` 8절과 같게), 팀원 표(이름·GitHub 아이디는 `.work/design/initial-setup.md` 8절 '팀원과 담당', 담당 칸은 '프로젝트 끝에 PR 내역으로 정리').
  2. `.env.example`: 환경변수 이름과 설명만.
  3. `pyproject.toml`: Python 3.12, uv. 패키지 버전은 PyPI(`pip index versions <패키지>`)로 확인해 `==`로 고정한다. [Claude proposal: 웹검색 대신 PyPI 조회로 작업량을 줄임]
  4. `AGENTS.md` '확인 명령'에 테스트 명령을 적는다. `.work/TASK.md` 환경 줄의 '세팅 3단계에서 정한다'를 실제 명령으로 고친다(규칙 파일 변경이므로 PR '⚠ 규칙 변경'에 적는다).
  5. TASK.md 파일 지도, STATUS.md, `docs/PROJECT_CONTEXT.md` 9절을 고친다.
- 요청자만 정할 것: LLM 제공자와 외부 API(일정·지도 등)를 아직 정하지 않았으면, 대화 시작 때 묻는다. 답이 없으면 공통 패키지(LangGraph 등)만 넣고 나머지는 '팀 결정 후 추가'로 둔다. [Claude proposal]
- 읽을 것: `.work/design/initial-setup.md#8. 2단계 결정과 3단계 할 일 (2026-11-05)`의 '팀원과 담당'과 '3-2 실행 환경', `docs/PROJECT_CONTEXT.md`, claude-github-setup의 `template/owned/common/README.md.tmpl`
- 만들 것: `README.md`, `.env.example`, `pyproject.toml`
- 섞지 않을 것: 진행 문서의 내용 변경(3-1), 검사 도구·CI(4단계), ChatGPT 사용 안내(5단계)
- 도구: 웹페이지 2, 스크립트 4

## 4단계 검사 도구·CI
- 할 일: claude-github-setup의 `measure.py`·`check.py`를 복사해 이 레포에 맞추고(진입 파일 AGENTS.md, STATUS.md 형식, TASK.md 파일 지도 검사), CI를 만들어 전체 검사를 통과시킨다. AGENTS.md '확인 명령'에 검사 명령을 적는다. [Request]
- 읽을 것: claude-github-setup의 `template/managed/common/.work/measure.py`·`check.py`·`.github/workflows/rules-check.yml`, 이 레포의 규칙 파일
- 만들 것: `.work/measure.py`, `.work/check.py`, `.github/workflows/` CI 파일
- 섞지 않을 것: 규칙 내용 변경, ChatGPT 사용 안내(5단계)
- 도구: 스크립트 5

## 5단계 ChatGPT 사용 안내
- 할 일: 팀원 연결 순서, Codex Cloud 환경(Python 3.12·uv), 작업 요청 문구, 문서 작업용 ChatGPT 프로젝트 지침을 정리한다. 새 경로(ChatGPT Work)와 "Codex Cloud (Legacy)"의 차이도 확인한다. [Request · Claude proposal]
- 읽을 것: `.work/design/setup-research.md`, `docs/PROJECT_CONTEXT.md`, 공식 문서(OpenAI)
- 만들 것: `docs/CHATGPT_GUIDE.md`
- 섞지 않을 것: 규칙 내용 변경, 검사 도구(4단계)
- 도구: 웹검색 3, 웹페이지 4

## 6단계 연결 시험 (팀원 각자 ChatGPT)
- 할 일: 팀원마다 Codex로 README 팀원 표의 자기 줄에 한 줄 소개를 넣는 PR을 열고 병합한다. 끊김·자동 요약 여부를 STATUS.md에 남긴다. [Request · Claude proposal: 3-2에서 팀원 표가 채워지므로 '이름 넣기'를 '한 줄 소개 넣기'로 바꿈]
- 확인할 것: Codex PR에 PR 양식과 마지막 답의 PR 설명이 들어가는지, 브랜치 이름을 어떻게 정하는지, PR 댓글 `@codex`로 충돌을 고칠 수 있는지.
- 읽을 것: `docs/CHATGPT_GUIDE.md`
- 만들 것: README 팀원 표의 각자 한 줄
- 섞지 않을 것: 다른 파일 수정
- 도구: 없음(Claude 대화 아님)

## 7단계 다음 과제용 템플릿 레포
- 할 일: 6단계 기록을 반영해 [공통] 파일과 [과제별] 파일의 빈 틀, 시작 안내를 담은 GitHub Template repository를 만든다. 기준 100KB와 도구 1회 크기도 기록을 보고 고친다. [Request]
- 읽을 것: `.work/TASK.md` 파일 지도, `.work/STATUS.md` '최근 완료'
- 만들 것: 템플릿 레포
- 섞지 않을 것: 이 레포의 과제 코드
- 도구: 6단계 뒤에 잰다
