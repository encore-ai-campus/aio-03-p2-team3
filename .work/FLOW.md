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

## 3-2단계 실행 환경 — 3-2-1, 3-2-2, 3-2-3으로 나눔(2026-11-05, 무료 LLM·API 조사가 더해져 한 대화로 약 150KB)
### 정한 것 (2026-11-05)
- 지금 쓰기로 확정한 LLM·외부 API 가운데 무료로 쓸 수 있는 것은 사용자가 세팅 단계(3-2-1, 3-2-2)에서 정한다. [Request]
- 나중에 기능을 더하며 다른 LLM·API를 더하거나 바꿀 수 있으므로, 그때 요청자에게 묻는 과정은 남긴다. 3-2-3에서 `.work/TASK.md` 환경 줄에 적는다. [Request]
- 레포 문서와 과제 안내(`.work/design/initial-setup.md` 3절)에는 지정된 LLM·API가 없다(2026-11-05 확인). 사용자가 이미 정한 것이 있으면 명령어 뒤에 적고, 그 단계는 그것만 확인한다. [Claude proposal]
- 테스트 명령은 `uv run pytest`로 한다. 서버 실행 명령은 코드 구조가 정해지면 README에 더한다. [Claude proposal]
- README 템플릿(claude-github-setup `template/owned/common/README.md.tmpl`)은 아래 세 줄이 전부다. 이 레포는 규칙을 직접 소유하므로(RULES 머리말) 첫 줄의 '공통 설정 레포가 관리'는 '이 레포가 관리'로 고친다. 원본 레포는 열지 않는다. [Past work: setup · Claude proposal]
  - `- 공통 규칙: .work/RULES.md (공통 설정 레포 [{{SETUP_REPO}}](...)가 관리)`
  - `- 이 레포의 규칙과 파일 지도: .work/TASK.md`
  - `- 진행기록: .work/STATUS.md`
- README 팀원 표(`.work/design/initial-setup.md` 8절 '팀원과 담당'에서 옮김, 담당 칸은 '프로젝트 끝에 PR 내역으로 정리'): 김민성 `doomdiver100T` · 정원철 `krw82` · 김진혁 `rlawlsgura-stack` · 임석원 `swihm1989-ship-it` [Request]

## 3-2-1단계 무료 LLM 고르기
- 할 일:
  1. 공식 문서(제공자 문서·가격 페이지)로 무료로 쓸 수 있는 LLM API 후보를 확인한다: 무료 한도(분당·일당 요청), 무료 등급의 데이터 사용 조건, LangChain 연동 패키지 이름, 키 발급 경로(사이트 → 메뉴 순서), 키를 넣을 환경변수 이름. 사용자가 정한 LLM이 있으면 그것만 확인한다. [Request]
  2. 후보와 추천을 보이고 사용자가 고르게 한다. [Request]
  3. `.work/design/api-choice.md`(새 파일)의 'LLM' 절에 후보 표, 고른 것, 설정 경로, 출처를 적는다(4KB 이하). TASK.md 파일 지도에 이 파일을 더한다. [Claude proposal]
  4. STATUS.md에 3-2-2 안내를 쓰고, `docs/PROJECT_CONTEXT.md` 9절을 고친다.
- 읽을 것: 이 절과 '3-2단계 정한 것'
- 만들 것: `.work/design/api-choice.md`
- 섞지 않을 것: 외부 API 조사(3-2-2), README·.env.example·pyproject(3-2-3)
- 도구: 웹검색 1, 웹페이지 3, 스크립트 3 (웹검색 결과는 회당 약 20KB라 검색은 한 번만 하고, 나온 공식 페이지를 웹페이지로 연다)

## 3-2-2단계 무료 외부 API 고르기 — 3-2-2-1, 3-2-2-2로 나눔(2026-11-05, 사용자 질문과 네이버 지도 추가로 한 대화가 약 130KB)
- 묶음 목표: 일정 조정 에이전트에 쓸 외부 API를 사용자가 고르고 `.work/design/api-choice.md` '외부 API' 절이 PR로 올라간다. [Request]

## 3-2-2-1단계 외부 API 후보 조사 (완료)
- 할 일: Google Calendar·특일 정보·단기예보를 공식 문서로 확인하고 후보를 보여 사용자가 고르게 했다. 결과는 api-choice.md '외부 API' 절의 후보 표와 '정한 것'.
- 읽을 것: 이 절, '3-2단계 정한 것', `.work/design/api-choice.md`
- 만들 것: api-choice.md '외부 API' 절(후보·정한 것)
- 섞지 않을 것: 3-2-2-2의 일
- 도구: 웹검색 1, 웹페이지 5, 스크립트 3

## 3-2-2-2단계 네이버 지도·캘린더 인증 확정
- 할 일:
  1. 네이버 지도 API를 공식 문서로 확인한다: 쓸 기능(장소 검색·주소↔좌표·길찾기) 후보, 무료 한도·과금 조건, 인증(Client ID·Secret 헤더), 키 발급 경로, 환경변수 이름. 네이버 클라우드 플랫폼 Maps와 네이버 개발자센터 검색(지역) API가 다르므로 둘을 구분한다. [Request]
  2. Google OAuth 동의 화면 '테스트' 상태의 사용자 제한과 프로덕션 게시(캘린더 범위 검증) 조건을 공식 문서로 확인한다. [Claude proposal]
  3. 캘린더 방식(A 팀 데모 캘린더+서비스 계정 · B 사용자별 OAuth · A+B)과 네이버 지도 기능을 추천과 함께 보이고 사용자가 고르게 한다. 배포 뒤 다른 팀이 체험할 수 있어야 한다(과제 최소 범위 7번). [Request]
  4. api-choice.md '외부 API' 절에 네이버 지도 열, '고른 것', '설정 경로'(키 발급 경로, 환경변수 이름)를 더하고 '진행 중' 표시와 질문 기록을 정리한다(파일 6KB 이하).
  5. STATUS.md에 3-2-3 안내를 쓰고, `docs/PROJECT_CONTEXT.md` 2절('외부 API' 줄)·9절을 고친다.
- 읽을 것: 이 절과 '3-2단계 정한 것', `.work/design/api-choice.md`
- 만들 것: api-choice.md '외부 API' 절 마무리
- 섞지 않을 것: LLM 다시 고르기(3-2-1), README·.env.example·pyproject(3-2-3)
- 도구: 웹검색 1, 웹페이지 3, 스크립트 4

## 3-2-3단계 실행 환경 파일 (완료)
- 할 일: [Request]
  1. `README.md`: 실행 방법, 두 산출물(설계서·시험 보고서)의 위치(`docs/PROJECT_CONTEXT.md` 8절과 같게), 팀원 표('3-2단계 정한 것'), 고른 LLM·API와 키 발급 경로(`.work/design/api-choice.md` 요약).
  2. `.env.example`: 환경변수 이름과 설명만.
  3. `pyproject.toml`: Python 3.12, uv. 공통 패키지(LangGraph 등)와 api-choice.md에서 고른 것의 패키지. 버전은 PyPI(`pip index versions <패키지>`)로 확인해 `==`로 고정한다. [Claude proposal: 웹검색 대신 PyPI 조회로 작업량을 줄임]
  4. `AGENTS.md` '확인 명령'에 `uv run pytest`를 적는다. `.work/TASK.md` 환경 줄의 '세팅 3단계에서 정한다'를 실제 명령으로 고치고, 'LLM·외부 API를 더하거나 바꾸는 작업은 요청자가 정한다(대화면 묻고, Codex 작업이면 질문을 결과로 돌려준다)'를 더한다(규칙 파일 변경이므로 PR '⚠ 규칙 변경'에 적는다). [Request]
  5. TASK.md 파일 지도, STATUS.md, `docs/PROJECT_CONTEXT.md` 2절('사용할 LLM과 외부 API' 줄)·7절(환경변수)·9절을 고친다.
- 읽을 것: 이 절과 '3-2단계 정한 것', `.work/design/api-choice.md`, `docs/PROJECT_CONTEXT.md`
- 만들 것: `README.md`, `.env.example`, `pyproject.toml`
- 섞지 않을 것: LLM·API 다시 고르기(3-2-1·3-2-2), 검사 도구·CI(4단계), ChatGPT 사용 안내(5단계)
- 도구: 스크립트 5

## 4단계 검사 도구·CI — 4-1, 4-2로 나눔(2026-11-05, 원본 세 파일이 약 36KB라 한 대화로 약 101KB)
- 원래 할 일: claude-github-setup의 `measure.py`·`check.py`를 복사해 이 레포에 맞추고(진입 파일 AGENTS.md, STATUS.md 형식, TASK.md 파일 지도 검사), CI를 만들어 전체 검사를 통과시킨다. AGENTS.md '확인 명령'에 검사 명령을 적는다. [Request]

### 정한 것 (2026-11-05)
- 원본: `doomdiver100T/claude-github-setup` 커밋 9c45959의 `template/managed/common/` 아래 `.work/measure.py` 15.1KB, `.work/check.py` 20.6KB, `.github/workflows/rules-check.yml` 0.7KB. [Past work: setup]
- 원본은 복제하지 않고 `git clone --depth 1 --no-checkout --filter=blob:none <원본 주소> <임시 폴더>` 뒤 `git show HEAD:<경로>`로 그 파일만 연다. 원본 레포에는 `register_repo_root`를 부르지 않는다(CLAUDE.md가 자동으로 들어온다). [Claude proposal]
- 만들 파일은 `git show HEAD:<경로> > <이 레포 경로>`로 복사한 뒤 바뀔 부분만 고친다. 그래서 '만들 것' 양은 고친 부분만 센다. [Claude proposal]
- 순서: check.py가 measure.py를 불러와(`load_measure`) STATUS 안내의 작업량을 다시 잰다. 그래서 measure.py(4-1)를 먼저 하고 check.py·CI(4-2)를 뒤에 한다. [Claude proposal]
- 시작 파일: 원본 measure.py의 `START_FILES`는 `.work/RULES.md`·`.work/TASK.md`·`.work/STATUS.md` 셋이다. 이 레포는 AGENTS.md대로 `AGENTS.md`와 `docs/PROJECT_CONTEXT.md`도 시작할 때 읽으므로 4-1에서 둘을 더한다. check.py는 안내의 작업량을 다시 재서 2KB 넘게 다르면 오류로 보므로, 시작 파일을 실제와 같게 둬야 한다. [Claude proposal]
- 원본 레포는 비공개라 그냥 복제하면 인증 오류가 난다. 먼저 `add_repo`(읽기)로 이 대화에 붙인 뒤 위 방법으로 연다. [Claude proposal · 4-1에서 확인]
- measure.py(4-1): `START_FILES`에 `AGENTS.md`·`docs/PROJECT_CONTEXT.md`를 더했고, 도구 표에 `레포 연결`(1회 4KB)을 더했고, `--read`도 레포 밖 파일을 `이름=KB`로 받게 했다(STATUS 안내가 원본 파일을 '읽을 파일'에 적기 때문). 도구 이름 `레포 연결`처럼 띄어쓰기가 있는 항목은 셸에서 따옴표로 감싼다. [Claude proposal]
- check.py(4-2-1): `uv run pytest`는 부르지 않는다. 표준 라이브러리만 써서 uv·네트워크 없이(Codex 환경 포함) 돌고, 테스트 실패와 규칙 위반을 따로 보이게 하려는 것이다. CI(4-2-2)는 check.py와 별도로 uv 설치 → `uv sync` → `uv run pytest` 단계를 둔다. [Claude proposal]
- check.py(4-2-1) 고친 것: 필수 파일을 `AGENTS.md`·RULES·TASK·STATUS·`docs/PROJECT_CONTEXT.md`·PR 양식으로 바꿈, skill·pipeline·agent 유형 검사와 `template.json` 검사를 지움, 출처 태그를 `[Request · Claude proposal]`처럼 이은 꼴도 받음, 나눈 단계의 묶음 제목은 FLOW 줄 검사에서 건너뜀, PROJECT_CONTEXT 절마다 '마지막 갱신' 줄 검사를 더함, 자동으로 읽히는 파일(`CLAUDE.md`·`.claude/`·`.mcp.json`·하위 폴더 `AGENTS.md`)은 이 레포 규칙에 금지 조항이 없어 오류가 아니라 경고로 둠. [Claude proposal]
- check.py는 STATUS 안내의 백틱 항목을 모두 재므로, 안내 줄의 덧붙임 설명에는 백틱을 쓰지 않는다(4-2-1에서 덧붙임의 git show가 항목으로 읽혀 오류가 났다). [Claude proposal]
- CI(4-2-2): 작업을 둘로 나눴다. `rules-check`(원본 그대로 setup-python 3.12 → `python .work/check.py`)와 `tests`(`astral-sh/setup-uv@v10.3.3` → `uv sync --locked` → `uv run pytest`). PR에 두 결과가 따로 보인다. setup-uv는 `v10` 같은 큰 버전 태그가 없어 전체 버전으로 고정했다(2026-11-05 `git ls-remote`로 확인). `--locked`는 `uv.lock`이 `pyproject.toml`과 어긋나면 실패하게 한다. [Claude proposal]

## 4-1단계 measure.py (완료)
- 할 일: 원본 `measure.py`를 복사해 이 레포에 맞춘다(`START_FILES`, 필요하면 도구 표에 `레포 연결`). `--start`·`--read`·`--show`·`--outline`을 이 레포 파일로 한 번씩 돌려 본다. 4-2 안내를 `measure.py`로 재서 STATUS에 적고, TASK 파일 지도에 `.work/measure.py`를 더한다. [Request · Claude proposal]
- 읽을 것: 이 절과 4단계 '정한 것', 원본 `.work/measure.py`
- 만들 것: `.work/measure.py`
- 섞지 않을 것: check.py·CI(4-2), 규칙 내용 변경, ChatGPT 사용 안내(5단계)
- 도구: 스크립트 5, 레포 연결 2

## 4-2단계 check.py·CI — 4-2-1, 4-2-2로 나눔(2026-11-05, measure.py로 다시 재니 약 107KB)
- 할 일: 원본 `check.py`를 복사해 이 레포에 맞춘다(필수 파일의 진입 파일을 `CLAUDE.md`에서 `AGENTS.md`로, STATUS.md 형식, TASK.md 파일 지도 검사, 이 레포에 없는 유형 검사는 정리). `check.py`가 `uv run pytest`도 부를지 정한다. 원본 `rules-check.yml`로 CI를 만들고, AGENTS.md '확인 명령'에 `python3 .work/check.py`를 적는다. 로컬 검사와 PR의 CI가 모두 통과하게 한다. TASK 파일 지도에 두 파일을 더한다. [Request · Claude proposal]
- 읽을 것: 이 절과 4단계 '정한 것', 원본 `.work/check.py`·`.github/workflows/rules-check.yml`, `.github/pull_request_template.md`
- 만들 것: `.work/check.py`, `.github/workflows/rules-check.yml`
- 섞지 않을 것: measure.py 고치기(4-1, 꼭 필요하면 이유를 PR에 적는다), 규칙 내용 변경, ChatGPT 사용 안내(5단계)
- 도구: 스크립트 6, 레포 연결 2
- 작업량(계획 값): 약 92KB — 시작 37KB, 읽을 것 25KB(원본 21KB 포함), 만들 것(고친 부분) 10KB, 실행 중 20KB
- 나눈 까닭: 4-1에서 measure.py로 다시 재니 원본 check.py 20.6KB, 실행 중 약 32KB(스크립트 8, 레포 연결 2)로 약 107KB였다. CI는 check.py가 로컬에서 통과한 뒤에야 확인할 수 있어 뒤로 뗐다. [Claude proposal]

## 4-2-1단계 check.py (완료)
- 할 일: 원본 `check.py`를 복사해 이 레포에 맞춘다(필수 파일의 진입 파일을 `CLAUDE.md`에서 `AGENTS.md`로, STATUS.md 형식, TASK.md 파일 지도 검사, 이 레포에 없는 유형 검사는 정리). `check.py`가 `uv run pytest`도 부를지 정해 4단계 '정한 것'에 적는다(4-2-2의 CI가 따른다). 로컬에서 `python3 .work/check.py`를 통과시키고, AGENTS.md '확인 명령'에 적고, TASK 파일 지도에 더한다. [Request · Claude proposal]
- 읽을 것: 이 절과 4단계 '정한 것', 원본 `.work/check.py`, `.github/pull_request_template.md`
- 만들 것: `.work/check.py`
- 섞지 않을 것: CI(4-2-2), measure.py 고치기(4-1, 꼭 필요하면 이유를 PR에 적는다), 규칙 내용 변경, ChatGPT 사용 안내(5단계)
- 도구: 스크립트 5, 레포 연결 2

## 4-2-2단계 CI (완료)
- 할 일: 원본 `rules-check.yml`로 CI를 만든다(check.py는 테스트를 부르지 않으므로 uv 설치·`uv sync`·`uv run pytest` 단계를 따로 둔다 — 4단계 '정한 것'). PR에서 CI가 통과하는지 확인하고, TASK 파일 지도에 더한다. [Request · Claude proposal]
- 읽을 것: 이 절과 4단계 '정한 것', 원본 `.github/workflows/rules-check.yml`, `.github/pull_request_template.md`
- 만들 것: `.github/workflows/rules-check.yml`
- 섞지 않을 것: check.py 고치기(4-2-1, 꼭 필요하면 이유를 PR에 적는다), 규칙 내용 변경, ChatGPT 사용 안내(5단계)
- 도구: 스크립트 5(CI 결과 확인 포함), 레포 연결 2

## 5단계 ChatGPT 사용 안내 — 5-1, 5-2로 나눔(2026-11-05, 공식 문서 조사가 더해져 한 대화로 약 118KB)
- 원래 할 일: 팀원 연결 순서, Codex Cloud 환경(Python 3.12·uv), 작업 요청 문구, 문서 작업용 ChatGPT 프로젝트 지침을 정리한다. 새 경로(ChatGPT Work)와 "Codex Cloud (Legacy)"의 차이도 확인한다. [Request · Claude proposal]
- 읽을 것: `.work/design/setup-research.md`, `docs/PROJECT_CONTEXT.md`, 공식 문서(OpenAI)
- 만들 것: `docs/CHATGPT_GUIDE.md`
- 섞지 않을 것: 규칙 내용 변경, 검사 도구(4단계)
- 도구: 웹검색 3, 웹페이지 4
- 나눈 까닭: 4-2-2에서 measure.py로 재니 시작 파일 39KB, 실행 중 65KB(웹검색 3, 웹페이지 4)로 약 118KB였다. 공식 문서 조사를 결과 파일로 남기는 5-1을 앞에 두고, 5-2는 그 파일만 읽고 안내 글을 쓴다. [Claude proposal]

## 5-1단계 Codex·ChatGPT 공식 확인
- 할 일: OpenAI 공식 문서로 Codex Cloud 환경 설정(Python 3.12·uv 설치, 비밀값, 작업 중 인터넷 접근), 새 경로(ChatGPT Work)와 "Codex Cloud (Legacy)"의 차이, ChatGPT 프로젝트 지침을 넣는 곳을 확인해 `.work/design/chatgpt-research.md`에 출처와 함께 적고 TASK 파일 지도에 더한다. `.work/design/setup-research.md`에서 이미 확인한 것은 다시 찾지 않는다. [Request · Claude proposal]
- 읽을 것: 이 절, `.work/design/setup-research.md`, 공식 문서(OpenAI)
- 만들 것: `.work/design/chatgpt-research.md`
- 섞지 않을 것: 안내 글 쓰기(5-2), 규칙 내용 변경, 검사 도구(4단계)
- 도구: 웹검색 2, 웹페이지 3

## 5-2단계 ChatGPT 사용 안내 글
- 할 일: 5-1 결과로 팀원 연결 순서, Codex Cloud 환경(Python 3.12·uv), 작업 요청 문구, 문서 작업용 ChatGPT 프로젝트 지침을 `docs/CHATGPT_GUIDE.md`에 정리하고 TASK 파일 지도에 더한다. [Request · Claude proposal]
- 읽을 것: 이 절, `.work/design/chatgpt-research.md`, `.work/design/setup-research.md`
- 만들 것: `docs/CHATGPT_GUIDE.md`
- 섞지 않을 것: 새 공식 조사(5-1, 꼭 필요하면 한 번만 하고 PR에 적는다), 규칙 내용 변경, 검사 도구(4단계)
- 도구: 스크립트 3

## 6단계 연결 시험 — 6-1, 6-2로 나눔(2026-11-05, 공식 문서의 작업 시작 경로 "Work in > Cloud"가 화면에 없어 먼저 찾는다)

## 6-1단계 Codex 작업 시작 경로 찾기 (Claude 대화)
- 할 일: 사용자 화면 캡처로 새 Codex Cloud에서 환경 `aio-03-p2-team3`를 골라 작업을 시작하는 경로를 찾는다(후보 순서는 `.work/design/step6-handoff.md`). 사용자가 자기 줄로 한 번 해 보며 시작 버튼·PR 버튼 이름을 확인하게 돕는다. 결과로 `docs/CHATGPT_GUIDE.md` 4절(1번 시작 경로, 검사 확인: Codex 답의 실행 결과와 PR의 CI 초록 체크)과 7절을 고치고, 인계 파일의 팀원 메시지 [ ]를 채워 사용자에게 준다. [Request · Claude proposal]
- 읽을 것: 이 절, `.work/design/step6-handoff.md`, `docs/CHATGPT_GUIDE.md`
- 만들 것: `docs/CHATGPT_GUIDE.md` 고침, 팀원 메시지(답으로)
- 섞지 않을 것: 규칙 내용 변경, 팀원 결과 기록(6-2), 공식 문서 검색(화면 후보로 못 찾으면 찾은 것을 인계 파일에 적고 검색은 다음 대화로 넘긴다: 검색까지 하면 기준을 넘는다)
- 도구: 캡처 6, 스크립트 4

## 6-1-2단계 Codex 요청 한 번으로 PR까지 (Claude 대화)
- 할 일: 6-1 시험 뒤 정한 것(`.work/design/step6-handoff.md` '6-1 시험 뒤 정한 것')대로 `docs/CHATGPT_GUIDE.md` 4절(요청 문구에 push·PR·PR 링크를 넣고, 팀원 절차를 요청 → PR 확인 → 병합으로 줄이고, PR 링크가 없을 때의 후속 요청을 예비로 둠)·7절과 `.work/RULES.md` 5절 4·5번(Codex가 PR을 직접 열고 첫 줄에 PR 링크)을 고친다. 규칙 변경은 RULES 4절 절차와 PR '⚠ 규칙 변경'에 적는다. 새 3단계 팀원 메시지를 답으로 준다. [Request]
- 읽을 것: 이 절, `.work/design/step6-handoff.md#6-1 시험 뒤 정한 것 (2026-11-05, 6-1-2단계로 넘김)`, `docs/CHATGPT_GUIDE.md#4. Codex에 작업 맡기기`, `docs/CHATGPT_GUIDE.md#7. 6단계 연결 시험에서 확인할 것`
- 만들 것: `docs/CHATGPT_GUIDE.md` 고침, `.work/RULES.md` 5절 고침, 팀원 메시지(답으로)
- 섞지 않을 것: 6-2 결과 기록, 5절 4·5번 밖의 규칙 변경, 공식 문서 검색, Codex로 시험해 보기(첫 팀원 시험이 확인한다)
- 도구: 스크립트 4

## 6-2단계 연결 시험 (팀원 각자 ChatGPT)
- 할 일: 팀원마다 Codex로 README 팀원 표의 자기 줄에 한 줄 소개를 넣는 PR을 열고 병합한다. 끊김·자동 요약 여부를 STATUS.md에 남긴다. [Request · Claude proposal: 3-2에서 팀원 표가 채워지므로 '이름 넣기'를 '한 줄 소개 넣기'로 바꿈]
- 확인할 것: Codex PR에 PR 양식과 마지막 답의 PR 설명이 들어가는지, 브랜치 이름을 어떻게 정하는지, PR 댓글 `@codex`가 동작해 충돌을 고칠 수 있는지, 새 경로에서 원래 작업으로 돌아가 같은 PR을 고칠 수 있는지, Business에서 환경 공유가 되는지. 순서와 항목은 `docs/CHATGPT_GUIDE.md` 5절·7절. [Request · Claude proposal]
- 읽을 것: `docs/CHATGPT_GUIDE.md`
- 만들 것: README 팀원 표의 각자 한 줄
- 섞지 않을 것: 다른 파일 수정
- 도구: 없음(Claude 대화 아님)

## 6-3단계 팀원 편의 개선 — 6-3-1, 6-3-2로 나눔(2026-11-06, 규칙·안내 글과 CI 확인을 한 대화로 하면 기준을 넘음)

## 6-3-1단계 규칙·안내 글 (Claude 대화)
- 할 일: `.work/design/step6-3-handoff.md` '6-3-1 규칙·안내 글'대로 AGENTS.md 문구 강화, 안내 글 2·4·5·6·7절, README '팀원 빠른 시작', RULES 2절 4번(Issue 번호만으로 본문 읽기)을 고친다. 규칙 변경은 RULES 4절 절차와 PR '⚠ 규칙 변경'에 적는다. [Request · Claude proposal]
- 읽을 것: 이 절, `.work/design/step6-3-handoff.md`의 '공식 확인'·'정한 것'·'답 대기'·'6-3-1' 절, `docs/CHATGPT_GUIDE.md`의 2·4·5·6·7절, `README.md`
- 만들 것: 위 파일 고침
- 섞지 않을 것: 읽음 확인 코드·PR 양식·check.py·CI(6-3-2), 팀원 메시지(6-3-2 뒤), 공식 문서 검색(인계 파일에 있음)
- 도구: 스크립트 6

## 6-3-2단계 CI 확인 (Claude 대화)
- 할 일: `.work/design/step6-3-handoff.md` '6-3-2 CI 확인'대로 읽음 확인 코드, PR 양식 두 칸, `check.py --pr`와 파일 지도 역검사, CI 작업 `pr-check`, RULES 5절·AGENTS.md 한 줄을 넣고, 이 PR로 `pr-check` 통과를 확인한다. 새 3단계 팀원 메시지를 답으로 준다. [Request · Claude proposal]
- 읽을 것: 이 절, `.work/design/step6-3-handoff.md`의 '정한 것'·'6-3-2' 절, `.work/check.py`(1~30·81~102·166~175·326~360줄만), `.github/workflows/rules-check.yml`, `.github/pull_request_template.md`
- 만들 것: 위 파일 고침
- 섞지 않을 것: 안내 글 4절 외의 개편, 6-2 결과 기록
- 도구: 스크립트 8

## 7단계 다음 과제용 템플릿 레포
- 할 일: 6단계 기록을 반영해 [공통] 파일과 [과제별] 파일의 빈 틀, 시작 안내를 담은 GitHub Template repository를 만든다. 기준 100KB와 도구 1회 크기도 기록을 보고 고친다. [Request]
- 읽을 것: `.work/TASK.md` 파일 지도, `.work/STATUS.md` '최근 완료'
- 만들 것: 템플릿 레포
- 섞지 않을 것: 이 레포의 과제 코드
- 도구: 6단계 뒤에 잰다
