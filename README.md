# aio-03-p2-team3

단위 프로젝트 2 (팀 3) 「복합 API 연계 일정 조정 에이전트」. LangGraph로 다중 도구 선택, 순환형 워크플로우, 자가 성찰·피드백 루프를 만들고 배포한다. 과제 개요와 현재 상태는 `docs/PROJECT_CONTEXT.md`.

- 공통 규칙: `.work/RULES.md` (이 레포가 관리)
- 이 레포의 규칙과 파일 지도: `.work/TASK.md`
- 진행기록: `.work/STATUS.md`

AI(ChatGPT·Codex·Claude)는 `AGENTS.md`부터 읽는다.

## 실행 방법

필요한 것: [uv](https://github.com/astral-sh/uv). Python 3.12는 uv가 `.python-version`을 보고 맞춰 준다.

```bash
# uv 설치 (macOS·Linux)
curl -LsSf https://astral.sh/uv/install.sh | sh
# uv 설치 (Windows PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

uv sync                  # 패키지 설치(.venv 생성, uv.lock 기준)
cp .env.example .env     # 값을 채운다. .env는 올리지 않는다
uv run pytest            # 테스트
```

- 서버 실행 명령은 코드 구조가 정해지면 여기에 더한다.
- 패키지 추가: `uv add <패키지>==<버전>`(개발용은 `uv add --dev …`). 버전은 `pip index versions <패키지>`로 확인하고, 바뀐 `pyproject.toml`·`uv.lock`을 함께 PR에 올린다.

## 산출물 위치

| 무엇 | 위치 | 상태 |
|---|---|---|
| 에이전트 아키텍처 설계서 | `docs/ARCHITECTURE.md` | 아직 없음(11/13 초안) |
| 에이전트 시험 결과 보고서 | `docs/TEST_REPORT.md` | 아직 없음 |
| 시험 실행 기록(실행마다 한 파일) | `docs/test-records/` | 아직 없음 |
| 큰 작업의 계획 파일 | `docs/plans/` | 형식만 있음 |
| 발표 PPT | 미정 | 아직 없음 |

위치를 바꾸면 이 표와 `docs/PROJECT_CONTEXT.md` 8절을 함께 고친다.

## LLM·외부 API와 키 발급

근거와 자세한 경로는 `.work/design/api-choice.md`. 환경변수 이름과 설명은 `.env.example`. 키는 로컬 `.env`와 Render 환경변수에 둔다. Codex 환경에는 키를 넣지 않는다(테스트는 가짜 응답, `docs/CHATGPT_GUIDE.md`).

| 무엇 | 쓰임 | 키 발급 | 환경변수 |
|---|---|---|---|
| Google Gemini API `gemini-3.8-flash`(무료 등급) | LLM | Google AI Studio API 키 화면(https://aistudio.google.com/app/apikey) | `GEMINI_API_KEY` |
| Google Calendar API | 일정 읽기·만들기(사용자별 OAuth 로그인) | Google Cloud 콘솔: Calendar API 사용 설정 → Google Auth Platform(외부, 앱 게시) → Clients에서 웹 애플리케이션 클라이언트, Render 주소의 리디렉션 URI | `GOOGLE_OAUTH_CLIENT_ID` `GOOGLE_OAUTH_CLIENT_SECRET` |
| 특일 정보(천문연)·단기예보(기상청) | 공휴일·절기, 날씨 | 공공데이터포털에서 두 API '활용신청'(자동승인) → 마이페이지 인증키 | `DATA_GO_KR_SERVICE_KEY` |
| 네이버 지역 검색(NAVER API HUB) | 장소→주소·좌표 | 네이버 클라우드 콘솔(대표 계정) → NAVER API HUB → Application 등록 → 인증 정보 | `NAVER_HUB_CLIENT_ID` `NAVER_HUB_CLIENT_SECRET` |
| 네이버 Maps Directions 5 | 길찾기 | 같은 콘솔 Maps → Application 등록(Directions 5) → 인증 정보, '이용 한도 설정'은 무료량 이하 | `NCP_MAPS_CLIENT_ID` `NCP_MAPS_CLIENT_SECRET` |

주의:
- Gemini 무료 등급은 입력이 Google 제품 개선에 쓰인다. 실제 개인정보를 넣지 않는다. LLM에는 일정 제목 없이 바쁜 시간대만 넘긴다.
- 체험자에게는 테스트용 Google 계정으로 로그인하도록 안내한다(OAuth 검증을 받지 않아 '확인되지 않은 앱' 경고가 뜨면 '고급 → 이동').
- LLM·외부 API를 더하거나 바꾸는 일은 요청자가 정한다(`.work/TASK.md`).

## 팀원

| 이름 | GitHub | 맡은 바 |
|---|---|---|
| 김민성 | `doomdiver100T` | 프로젝트 끝에 PR 내역으로 정리 |
| 정원철 | `krw82` | 프로젝트 끝에 PR 내역으로 정리 |
| 김진혁 | `rlawlsgura-stack` | 프로젝트 끝에 PR 내역으로 정리 |
| 임석원 | `swihm1989-ship-it` | 프로젝트 끝에 PR 내역으로 정리 |
