# aio-03-p2-team3

단위 프로젝트 2 (팀 3) 「복합 API 연계 일정 조정 에이전트」. LangGraph로 다중 도구 선택, 순환형 워크플로우, 자가 성찰·피드백 루프를 만들고 배포한다. 과제 개요와 현재 상태는 `docs/PROJECT_CONTEXT.md`.

## 팀원 빠른 시작

1. 요청: chatgpt.com 왼쪽 `…` → Codex → Cloud · Choose environment `aio-03-p2-team3` → `docs/CHATGPT_GUIDE.md` 4절 2번 요청 문구(작업, 관련 상태·도구·노드, 수정 범위, 확인 조건, `Issue: #번호`)를 채워 보낸다. AGENTS.md를 읽으라는 말과 검사·PR 지시는 쓰지 않는다(Codex가 레포 규칙대로 한다).
2. PR 확인: 답 맨 앞 PR 링크 → Files changed에 수정 범위 밖 파일이 없고 `rules-check`·`tests`·`pr-check`가 초록 체크인지 본다. 빨간 X면 같은 작업에 오류를 붙여 고쳐 달라고 한다.
3. 병합: 초록 체크를 본 뒤 Merge pull request → Confirm merge, 또는 같은 Codex 작업에 `병합해 주세요`(Codex는 검사가 모두 통과했을 때만 병합한다). `main`은 `rules-check`·`tests`·`pr-check`가 통과해야 병합된다. 브랜치는 지우지 않는다.

자세한 것과 막힐 때(PR 링크가 없을 때, 충돌)는 `docs/CHATGPT_GUIDE.md` 4·5절.

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
uv run uvicorn app.main:app --reload  # 로컬 서버
```

- 기본 화면: `http://127.0.0.1:8000/`(`/inbox`로 이동). 상태 확인: `http://127.0.0.1:8000/healthz` → `{"status":"ok"}`. 화면·상태 확인에는 API 키가 필요 없다.
- Render 시작 명령: `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- 현재는 계획 2절의 앱 뼈대에 6절의 Google 로그인·Gmail 감시 등록을 더한 상태다. 업무 노드·도구, 알림 처리·발송·후보 저장·화면 기능은 후속 작업에서 구현한다. 가짜 LLM 그래프 검증은 `uv run pytest tests/test_graph.py tests/test_llm.py`로 실행한다.
- 로그인: 기본 화면의 'Gmail 연결하기' → `/login` → Google 로그인. `GOOGLE_OAUTH_*`·`GMAIL_PUBSUB_TOPIC`·`TOKEN_ENCRYPTION_KEY`·`SESSION_SECRET`이 모두 있어야 로그인 버튼이 켜진다(빠진 이름을 로그인 화면이 보여 줌, 키 만드는 명령은 `.env.example`). 실제 Google 로그인에는 Google Cloud 설정(계획 5절)이 필요하고, 가짜 Google 응답 검증은 `uv run pytest tests/test_auth.py`로 실행한다.
- 앱 DB는 PostgreSQL 전용이다(react-supabase 계획 4절). `DATABASE_URL`이 비었거나 비PostgreSQL 주소면 서버가 시작을 거부한다(과거의 `app/db/local.sqlite3` 자동 생성 경로는 제거). `postgres://`·`postgresql://` 주소는 `psycopg` 드라이버로 연결하며, Supabase는 Session pooler 주소(포트 5432)에 `?sslmode=require`를 붙인다(트랜잭션 pooler 6543은 안 쓴다). 엔진 풀 상한은 프로세스당 pool_size 5·max_overflow 10·timeout 30초·recycle 1800초다. 서버 시작 시 `app/db/migrations/`의 Alembic 리비전으로 기존 데이터와 승인 이력을 보존하며 갱신하되, 대상 스키마를 `public`으로 고정해 Supabase의 `auth`·`storage` 스키마는 건드리지 않는다. 운영 갱신 전 DB 백업을 보관한다. 테스트는 실제 PostgreSQL에서 갱신을 확인하고, 역사적 SQLite 이관 검사만 `tests/test_trade_upgrade.py` 첫 검사로 한시적으로 남긴다.
- 기존 SQLite → PostgreSQL 데이터 이전(일회성): `uv run python -m app.db.copy_data --source <SQLite 파일 경로|DB URL> [--target <PostgreSQL 주소>] [--dry-run] [--yes]`. 원본 SQLite 파일은 임시 사본을 갱신해 읽어 원본을 고치지 않고, 쓰기는 `--yes`를 줄 때만 한다. 대상에 원본과 다른 데이터가 있으면 합치지 않고 실패하고, 이미 같으면 다시 쓰지 않고 대조만 통과한다. 복사·시퀀스 정렬은 대상 한 트랜잭션으로 커밋해 중간 실패 시 전부 롤백된다. 대조는 표별 행 수·모든 열 값·PK/시퀀스를 비교한다.
- Storage 미참조 객체 목록·수동 정리(react-supabase 8절): `uv run python -m app.files.cleanup` — 버킷에 있지만 `file_assets`가 가리키지 않는 객체(업로드 성공 뒤 SQL 실패로 남은 것)를 목록화한다. `--older-than-hours <시간>`(기본 24)으로 대상을 줄이고 `--delete --yes`를 함께 줄 때만 지운다. 참조 중인 객체는 절대 지우지 않고 크론·자동 정리는 없다(사람이 확인 후 실행).
- 테스트 DB 준비(별도 설치 불필요): 로컬 macOS·Linux는 개발 의존성 `pgserver`가 세션마다 임베디드 PostgreSQL을 띄우고(`uv run pytest`만 실행) 테스트별로 DB를 만들어 지운다. CI(GitHub Actions `tests` 작업)는 `postgres:16` service 컨테이너를 띄워 `TEST_DATABASE_URL`로 가리킨다. 로컬에서도 준비된 PostgreSQL에 `TEST_DATABASE_URL=postgres://… uv run pytest`로 연결할 수 있다. 단위 테스트는 `.env`의 실제 LLM 키가 스며들지 않게 키 환경을 비우고, LLM 응답은 각 테스트가 명시적으로 주입한 가짜만 쓴다.
- DB 엔진·세션 팩터리, 컴파일한 그래프, 설정한 LLM 클라이언트를 재사용한다. 실행 기록은 `runs`·`run_events` 표에 저장한다. 원문 대신 노드 이름·바뀐 필드·오류 종류·프롬프트 버전·소요 시간을 남긴다.
- HTMX 2.0.8은 `app/web/static/js/htmx.min.js`에 포함했다([공식 배포 파일](https://cdn.jsdelivr.net/npm/htmx.org@2.0.8/dist/htmx.min.js), 같은 폴더 `htmx.LICENSE`에 0BSD 라이선스). 실행 중 외부 CDN 요청은 없다. 색·글꼴·간격은 `app/web/static/css/tokens.css`에서 조정한다.
- React 화면(react-supabase 계획 6절, 2026-11-12): `cd frontend && npm ci && npm run dev`로 Vite 개발 서버를 띄우고 `http://localhost:5173/app/`(슬래시 포함)로 접속한다. `/api` 요청은 `frontend/vite.config.js` 프록시가 로컬 FastAPI(`127.0.0.1:8000`)로 보낸다. 로그인 연결에는 `frontend/.env`에 `VITE_SUPABASE_URL`·`VITE_SUPABASE_PUBLISHABLE_KEY`가 필요하고(틀: `frontend/.env.example`) 서버 `.env`의 `SUPABASE_URL`이 `GET /api/me`의 Bearer 검증에 쓰인다. 실제 Google 로그인은 계획 2절 콘솔 설정(비대칭 signing key·Google 공급자·redirect 허용)이 먼저다. 검사는 `frontend/`에서 `npm run lint`, `npm run build`. 지금은 시안 그대로의 로그인 화면·사이드바/하단탐색 뼈대·`/app` 라우팅·인증 경계·`/api/me` 연결만 있고 문서작성 등 나머지 화면은 자리만 있다(계획 11절 이후 연결).
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

2026-11-11 요청에 따라 모든 LLM 호출을 OpenAI Responses API로 통일했다. 근거와 자세한 경로는 `.work/design/api-choice.md`. 환경변수 이름의 기준은 `docs/CONTRACT.md` 11절, 이름과 설명만 담은 설정 틀은 `.env.example`이다. 키는 로컬 `.env`와 Render 환경변수에 둔다. Codex 환경에는 키를 넣지 않는다(테스트는 가짜 응답, `docs/CHATGPT_GUIDE.md`). 콘솔 설정과 실제 연동은 별도 작업에서 진행한다.

| 무엇 | 쓰임 | 키 발급 | 환경변수 |
|---|---|---|---|
| OpenAI Responses API `gpt-6-luna` | 메일 분석·답장·거래 추출·요약·성찰과 무역 문서 AI 추출(PI·PO·CI·PL) | OpenAI 플랫폼 API 키 화면(https://platform.openai.com/api-keys) | `OPENAI_API_KEY` · `OPENAI_MODEL`(선택, 비우면 `gpt-6-luna`) |
| Gmail API | 사용자별 메일 읽기·감시 등록, 승인한 답장·견적서 첨부 발송 | Google Cloud 콘솔: Gmail API 사용 설정 → Google Auth Platform → Clients에서 OAuth 웹 애플리케이션 클라이언트 생성, 로컬·Render 콜백 주소 등록 | `GOOGLE_OAUTH_CLIENT_ID` `GOOGLE_OAUTH_CLIENT_SECRET` `GOOGLE_OAUTH_REDIRECT_URI` |
| Cloud Pub/Sub | Gmail 메일함 변경 알림을 서비스로 푸시 전달 | Google Cloud 콘솔: Pub/Sub API 사용 설정 → 토픽·푸시 구독 설정. OIDC 확인 방식 권장, 비밀 토큰은 대체 방식을 쓸 때만 | `GMAIL_PUBSUB_TOPIC` `PUBSUB_PUSH_AUDIENCE` `PUBSUB_PUSH_SERVICE_ACCOUNT` `PUBSUB_PUSH_TOKEN`(대체 방식 전용) |
| Google Calendar API | 도구 2(구글캘린더 등록)용으로 유지 | Calendar API와 사용자별 Google OAuth를 사용. 일정 도구 작업 때 연결 | Gmail과 같은 `GOOGLE_OAUTH_CLIENT_ID` `GOOGLE_OAUTH_CLIENT_SECRET` `GOOGLE_OAUTH_REDIRECT_URI` |

API 키 외 앱 설정도 같은 계약 11절을 따른다. 실제 값은 `.env`·Render에만 넣는다.

| 환경변수 | 설명 |
|---|---|
| `DATABASE_URL` | 앱 DB PostgreSQL 접속 주소(빈 값·비PostgreSQL 주소는 거부). Supabase는 Session pooler 주소에 `?sslmode=require` |
| `TOKEN_ENCRYPTION_KEY` | Google 토큰 암호화 키 |
| `SESSION_SECRET` | 로그인 세션 쿠키 서명 키 |
| `APP_BASE_URL` | 서비스 주소. 링크·리디렉션 확인용 |
| `REFLECTION_ENABLED_DEFAULT` | 성찰 기본값. 설정할 때 `true` 또는 `false` 지정 |
| `SUPABASE_URL` `SUPABASE_SECRET_KEY` `SUPABASE_STORAGE_BUCKET` | Supabase 전환용 서버 설정. `SUPABASE_URL`은 Bearer 토큰 검증(JWKS·issuer)에 읽는다(계획 5절 적용). `SUPABASE_SECRET_KEY`는 Gmail 연결 시작의 계정 일치 확인(계획 7절 적용, 2026-11-12)과 Storage 전환(계획 8절)에, `SUPABASE_STORAGE_BUCKET`은 Storage 전환(계획 8절)부터 적용 |
| `VITE_SUPABASE_URL` `VITE_SUPABASE_PUBLISHABLE_KEY` | React 브라우저용 Supabase 설정(계획 6절 적용, 2026-11-12). `frontend/.env`에만 두고 서버 비밀과 분리한다 |

특일 정보·단기예보·네이버 지역 검색·네이버 길찾기는 MVP에서 제외했다. 일정(캘린더) 도구 작업 때 `.work/design/api-choice.md`의 '일정 도구 추천 후보'를 요청자에게 추천하고 채택 여부를 확인한다.

주의:

- 메일과 기억·추출에 필요한 내용을 OpenAI API로 전송한다. 테스트용 Google 계정과 가상 메일을 사용하고 실제 개인정보를 넣지 않는다. API 데이터 보관·이용은 [OpenAI 안내](https://platform.openai.com/docs/guides/your-data)와 계정 설정을 확인한다. 일정 도구 연결 때도 LLM에는 일정 제목 없이 바쁜 시간대만 넘긴다.
- OpenAI API는 ChatGPT 구독과 별도로 과금된다. 키를 만든 프로젝트의 결제·사용 한도·선택 모델 이용 권한을 확인한다. 무료 이용이나 무제한 호출을 가정하지 않는다.
- OAuth 게시·권한과 Pub/Sub 푸시 수신 인증은 별도 Google Cloud·로그인·알림 수신 작업에서 설정한다.
- LLM·외부 API를 더하거나 바꾸는 일은 요청자가 정한다(`.work/TASK.md`).

전환 적용 순서:

1. 로컬 `.env`와 Render에 `OPENAI_API_KEY`를 먼저 등록한다. 다른 모델을 쓸 때만 `OPENAI_MODEL`을 지정한다. 기존 Google OAuth·Gmail·Pub/Sub 값은 그대로 둔다.
2. PR 병합 후 Render 자동 배포(`uv sync --locked`)가 끝나면 `/healthz`, 테스트용 Gmail의 분석·답장, 무역 문서 추출을 확인한다. 실제 API 시험은 로컬·Render에서 가상 메일로 한다.
3. 전환 확인 후 기존 `GEMINI_API_KEY`·`GEMINI_MODEL`·`TRADE_EXTRACT_BACKEND`를 로컬·Render에서 제거한다. 앱은 이 값을 더 이상 읽지 않는다. 이전 Gemini 실행 기록과 응답 시간은 과거 결과이며 OpenAI 성능은 다시 측정한다.

## 팀원

| 이름 | GitHub | 맡은 바 | 한 줄 소개 |
|---|---|---|---|
| 김민성 | `doomdiver100T` | 프로젝트 끝에 PR 내역으로 정리 | 함께 배우고 성장하는 개발자를 지향합니다. |
| 정원철 | `krw82` | 프로젝트 끝에 PR 내역으로 정리 | 함께 배우며 꾸준히 성장하는 개발자입니다. |
| 김진혁 | `rlawlsgura-stack` | 프로젝트 끝에 PR 내역으로 정리 | 안녕하세요 |
| 임석원 | `swihm1989-ship-it` | 프로젝트 끝에 PR 내역으로 정리 | 코딩의 귀재 |


## 독립 무역 문서 JSON API

상세 경로·도메인 차이·요청 예시·폴더 구조는 [React 무역 문서 API](docs/trade-api.md)를 참고한다. PI와 같은 작성/수정/검토/선택/다운로드 경로를 PO·CI·PL에도 제공한다. CI는 승인된 PI 버전을 선택하고, PL은 최종 검토 전에 `/packing-review`의 합계를 확인한다.

[현재 구현] React는 기존 Google 로그인 세션으로 `GET /api/session`에서 CSRF 토큰을 받고, 변경 요청에 `X-CSRF-Token`과 세션 쿠키를 함께 보낸다. PI는 `/api/trade/pi`에서 작성/목록, `/extract`에서 텍스트 추출, `/{id}`에서 조회/전체 수정, `/{id}/versions/{revision}`에서 이전 버전을 조회한다. 입력 수량·금액은 정확한 십진수 문자열이며 API 형식은 `/docs`에서 확인한다.

`POST /api/trade/pi/{id}/reviews`에 `revision`과 `formats`(`pdf`, `xlsx`)를 보내 검토 제안을 만든다. 반환된 제안의 ID·revision·content_hash를 그대로 `…/reviews/{proposal_id}/decisions`로 보내 `approve`, `cancel`, `modify` 중 하나를 선택한다. 수정 선택은 `document`에 새 입력 전체를 함께 보내며 새 버전·새 제안을 다시 확인한다. 부족한 수정 입력은 `needs_input`으로 돌아온다. 승인은 문서 확정과 파일 발급이며 메일 발송을 포함하지 않는다. 취소 시 파일을 발급하지 않고, 승인 재시도는 같은 파일을 반환한다. 파일은 로그인한 소유자만 `/api/trade/files/{file_id}`에서 내려받는다.

[현재 구현] 회사·통화별 은행·단가는 `/api/trade/settings` 하위 API, 직인/로고 PNG는 `/branding/{seal|logo}`에 설정한다. 검토 제안에는 그 시점의 문서·계좌·이미지를 보관해 이후 설정 변경이 승인 파일을 바꾸지 않는다. 다른 주소의 React는 `FRONTEND_ORIGINS`에 허용 출처를 지정하고 `credentials: 'include'`를 사용한다. 서로 다른 사이트의 쿠키가 필요하면 HTTPS에서만 `SESSION_SAME_SITE=none`을 사용한다.

### React·Supabase 전환 목표(2026-11-12 확정, 6절까지 적용)

화면을 React(JavaScript·Vite), 로그인을 Supabase Auth(Google), DB를 Supabase PostgreSQL, 파일을 비공개 Supabase Storage(버킷 `trade-files`)로 전환한다. 계획은 `docs/plans/react-supabase/PLAN.md`, 계약은 `docs/CONTRACT.md` 7.1·9.1·11·16.3절이다.

- 로그인 뒤 `GET /api/me`(인증 상태·프로필·Gmail 연결 상태)에서 시작하고, React JSON API는 `Authorization: Bearer <Supabase access token>`만 쓴다. 위 쿠키+CSRF 안내는 전환 기간의 기존 경로용이다(계획 21·22절 전환 뒤 닫는다).
- 서버는 검증한 Supabase UUID를 기존 정수 `user_id`(`users.supabase_uid` 매핑)에 연결한다. 파일은 서버가 `POST /api/files`로 한 파일씩 받아 Storage에 저장하고 메타데이터만 DB에 남긴다(첨부 파일당 5MiB·문서당 5개·PDF/XLSX/TXT/PNG/JPEG).
- 개발은 `frontend/`의 Vite 개발 서버로 `/api`를 FastAPI로 프록시하고(계획 6절 적용, 2026-11-12 — 시안 이식 로그인 화면·`/app` 라우팅·인증 경계·`/api/me` 연결 포함), 배포는 React 빌드 파일을 기존 Render FastAPI가 같은 출처에서 제공한다(별도 프론트 호스팅 없음, 계획 21절).
- 서버 설정 `SUPABASE_URL`·`SUPABASE_SECRET_KEY`·`SUPABASE_STORAGE_BUCKET`·`DATABASE_URL`(PostgreSQL), 브라우저 설정 `VITE_SUPABASE_URL`·`VITE_SUPABASE_PUBLISHABLE_KEY`. 서버는 `SUPABASE_URL`로 Bearer 토큰을 검증한다(계획 5절 적용, 2026-11-12). Storage 설정은 계획 8절부터 읽는다.
