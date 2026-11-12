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
- 위 Uvicorn 명령은 기본 `AI_RUNTIME=server`의 사용자별 DB 키 방식이다. 개인 `.env` 키를 쓰려면 아래 전용 로컬 실행 절차를 따른다.
- Render 시작 명령: `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- 현재는 계획 2절의 앱 뼈대에 6절의 Google 로그인·Gmail 감시 등록을 더한 상태다. 업무 노드·도구, 알림 처리·발송·후보 저장·화면 기능은 후속 작업에서 구현한다. 가짜 LLM 그래프 검증은 `uv run pytest tests/test_graph.py tests/test_llm.py`로 실행한다.
- 로그인: 기본 화면의 'Gmail 연결하기' → `/login` → Google 로그인. `GOOGLE_OAUTH_*`·`TOKEN_ENCRYPTION_KEY`·`SESSION_SECRET`이 필요하며, 기본 서버 모드에서는 `GMAIL_PUBSUB_TOPIC`도 있어야 로그인 버튼이 켜진다(빠진 이름을 로그인 화면이 보여 줌, 키 만드는 명령은 `.env.example`). 로컬 모드는 아래 개인 OAuth 설정을 사용한다. 가짜 Google 응답 검증은 `uv run pytest tests/test_auth.py tests/test_local_gmail.py`로 실행한다.
- `DATABASE_URL`을 비우면 `app/db/local.sqlite3`에 로컬 DB를 만든다(커밋 제외). Postgres는 `postgres://`·`postgresql://` 주소도 `psycopg` 드라이버로 연결한다. 서버 시작 시 `app/db/migrations/`의 Alembic 리비전으로 기존 데이터와 승인 이력을 보존하며 갱신한다. SQLite의 기존 단가표 제약 변경은 테이블 복사 방식이고 Postgres는 트랜잭션 안에서 변경한다. 운영 갱신 전 DB 백업을 보관한다. 테스트는 메모리 SQLite와 이전 스키마에서의 갱신을 확인한다.
- DB 엔진·세션 팩터리와 컴파일한 그래프를 재사용한다. LLM은 호출 시 해당 사용자의 현재 키로 구성하며 공용 클라이언트를 캐시하지 않는다. 실행 기록은 `runs`·`run_events` 표에 저장한다. 원문 대신 노드 이름·바뀐 필드·오류 종류·프롬프트 버전·소요 시간을 남긴다.
- HTMX 2.0.8은 `app/web/static/js/htmx.min.js`에 포함했다([공식 배포 파일](https://cdn.jsdelivr.net/npm/htmx.org@2.0.8/dist/htmx.min.js), 같은 폴더 `htmx.LICENSE`에 0BSD 라이선스). 실행 중 외부 CDN 요청은 없다. 색·글꼴·간격은 `app/web/static/css/tokens.css`에서 조정한다.
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

모든 LLM 호출은 OpenAI Responses API를 사용한다. 공용 서버(기본 `AI_RUNTIME=server`)에서는 각 사용자가 Google 로그인 후 `/settings`의 **내 OpenAI API 키**에서 등록·교체·삭제한다. `stored_key`의 Gmail 자동 처리(분석·답장·요약·성찰)와 PI·PO·CI·PL AI 추출은 해당 사용자의 DB 키만 쓰며, 키가 없거나 암호문을 읽지 못하면 API 호출 전에 차단한다. 공용 `.env`·Render의 `OPENAI_API_KEY`로 대체하지 않는다. 개인 PC의 전용 로컬 앱과 HTTPS 서버에 연결한 개인 실행기는 지정 소유자의 `.env` 키만 사용한다. 근거는 `.work/design/api-choice.md`, 실행 계약은 `docs/CONTRACT.md` 6절·11절·`.env.example`이다. Codex 검증은 가짜 응답만 사용한다.

### 개인 PC의 .env 키로 실행

1. 레포 루트의 개인 `.env`에 `AI_RUNTIME=local`을 지정한다. 처음에는 `LOCAL_OWNER_GOOGLE_SUB`와 `OPENAI_API_KEY`를 비워도 화면을 열 수 있다. 아래 절차로 본인 Google OAuth 앱과 로컬 콜백을 준비하고 `.env.example`의 명령으로 개인 `SESSION_SECRET`·`TOKEN_ENCRYPTION_KEY`를 만든다. `DATABASE_URL`은 공용 Render DB를 가리키지 않게 한다. 비우면 PC의 `app/db/local.sqlite3`를 쓴다.
2. `uv run python -m app.local`을 실행하고 `http://127.0.0.1:8000`에서 본인 Google 계정으로 로그인한다. `/settings`의 **현재 로그인으로 검증된 본인 Google 식별자**를 확인해 개인 `.env`의 `LOCAL_OWNER_GOOGLE_SUB`에 직접 지정한다. 최초 로그인 사용자를 자동 소유자로 지정하지 않는다.
3. 개인 `.env`의 `OPENAI_API_KEY`에 본인 키를 넣고 앱을 다시 시작한다. `/settings`에서 **로컬 .env 키 사용 가능**을 확인한다. 다른 계정·소유자 미지정·키 누락이면 AI를 차단한다. DB 사용자 키는 읽거나 저장하지 않으며 키·해시·일부 문자열도 화면에 표시하지 않는다. 키 변경도 `.env` 수정 후 재시작한다.

전용 명령은 `127.0.0.1`에만 바인딩하며 `--port`만 지원한다(포트를 바꾸면 OAuth 콜백도 맞춘다). 공개 바인딩·리로드 옵션은 없다. 일반 Uvicorn 명령이나 Render·`PORT`가 지정된 공용 실행에서 `AI_RUNTIME=local`이면 시작을 거부한다. Host·`APP_BASE_URL`을 로컬 주소로 바꿔도 허용하지 않는다. 로컬 서비스를 외부 프록시·터널로 공개하지 않는다.

### 로컬 Gmail 연결과 새 메일 수집

1. [Google Cloud 콘솔](https://console.cloud.google.com/)에서 본인 프로젝트를 만들고 **Gmail API**를 사용 설정한다. **Google Auth Platform**의 브랜딩·잠재고객을 설정하고 테스트 중인 외부 앱이면 본인 테스트용 Gmail을 테스트 사용자로 등록한다. 데이터 액세스 범위는 `openid`, `email`, `https://www.googleapis.com/auth/gmail.readonly`, `https://www.googleapis.com/auth/gmail.send`다.
2. **Clients → 클라이언트 만들기 → 웹 애플리케이션**에서 개인 OAuth 클라이언트를 만든다. 승인된 리디렉션 URI에 `http://127.0.0.1:8000/auth/google/callback`을 등록한다. 다른 포트를 쓰면 콘솔과 `.env`의 콜백 포트를 함께 바꾼다. 운영 OAuth 클라이언트 비밀값을 팀원에게 배포하거나 복사하지 않는다.
3. 본인 PC의 `.env`에 개인 클라이언트 ID·비밀값을 `GOOGLE_OAUTH_CLIENT_ID`·`GOOGLE_OAUTH_CLIENT_SECRET`으로 넣고, `GOOGLE_OAUTH_REDIRECT_URI`를 위 URI와 일치시킨다. `APP_BASE_URL`은 `http://127.0.0.1:8000`으로 지정하고 브라우저도 같은 주소를 쓴다. 로컬의 `GMAIL_PUBSUB_TOPIC`과 `PUBSUB_PUSH_*`는 비워도 된다. 공용 Render의 OAuth·토픽·구독·푸시 주소는 변경하지 않는다.
4. `uv run python -m app.local` 실행 → Google 로그인·Gmail 읽기/보내기 권한 동의 → 위 절차대로 본인 sub·OpenAI 키 지정 후 재시작 → `/inbox`의 **로컬 새 메일 수집 켜짐**과 `/settings`의 **로컬 .env 키 사용 가능**을 확인한다. 소유자 미지정·다른 계정이면 수집을 대기한다. 처음 연결할 때 `users.getProfile`의 현재 historyId만 저장하므로 연결 전에 있던 메일함 전체를 처리하지 않는다.

앱이 켜져 있으면 본인 Google 토큰으로 30초 간격으로 `history.list`를 조회한다. 화면을 닫아도 앱이 켜져 있으면 수집하며 수신 포트·공개 터널·Pub/Sub가 필요 없다. 기존 MIME 변환·필터·중복 방지·AI 후보 생성과 사용자 승인 후 발송을 사용한다. 화면 목록은 별도로 90초마다 갱신된다. 로컬에서는 Google `users.watch`·`users.stop`을 호출하지 않아 같은 계정의 공용 감시를 덮어쓰지 않는다.

로그아웃·재연결 동의 취소·Google 연결 만료/취소·앱/PC 종료 시 추가 수집을 멈춘다. 정상 접근 토큰 만료는 저장된 갱신 토큰으로 갱신한다. 통신 실패는 마지막 커서를 보존하고 다음 주기에 중복 메일을 건너뛰며 이어 읽는다. historyId가 만료(404)되면 자동 전체 동기화 없이 **다시 로그인**을 안내한다. 명시적으로 다시 로그인하면 현재 위치로 재설정하므로 로그아웃/만료 기간의 과거 메일은 처리하지 않는다. 프로그램만 재시작하면 같은 로컬 DB의 마지막 커서부터 이어 읽되, 커서가 만료됐으면 재로그인이 필요하다. Google 외부 앱 테스트 상태의 갱신 토큰은 7일 만료 등 Google 정책에 따라 재동의를 요구할 수 있다.

**현재 구현 범위:** 로컬 키·소유자 제한과 Gmail 연결·새 메일 수집, 서버의 장치 연결·사용자별 작업 큐까지다. 개인 실행 프로그램과 기존 AI 호출 연결은 아직 없다(계획 4절). 실제 키·Google 식별자는 채팅·Codex·Issue·PR·레포에 넣지 않는다.

### 개인 PC AI 실행 — HTTPS 서버와 연결

Google 로그인 후 `/settings`에서 `stored_key`(기존 본인 DB 키) 또는 `local_worker`(개인 PC 키)를 선택한다. `local_worker`는 서버 저장 키나 공용 환경 키로 자동 전환하지 않는다. 메일 분석·답장·거래 추출·요약·성찰과 PI/PO/CI/PL AI 추출을 PC에서 실행한다. 수동 문서 작성·검토·파일 발급과 메일의 사용자 승인 후 발송은 유지한다.

1. 본인 PC의 Windows/macOS/Linux에 Python 3.12·uv와 같은 버전의 저장소를 준비하고 `uv sync --locked`한다. **Windows는 WSL 없이 PowerShell에서 실행한다.** 본인 사용자 프로필의 로컬 폴더를 사용한다. 개인 `.env` 또는 `.env.worker`에 `OPENAI_API_KEY`, `LOCAL_OWNER_GOOGLE_SUB`(본인 로그인으로 검증된 서버 `/settings` 식별자), 선택 모델 `OPENAI_MODEL`을 지정한다. 키를 Render·채팅·Issue에 넣지 않는다. 실행기는 지정한 파일만 읽으며 파일을 올리지 않는다.
2. 본인 서버 설정에서 `local_worker`를 선택한다. PC에서 `uv run python -m app.worker.pc pair --service https://<본인-서비스> --name "내 PC"`를 실행하고, 표시된 서비스 주소·장치 이름·일회용 코드를 본인 Google 계정의 서버 화면과 대조해 승인한다. 연결 계정의 검증 식별자가 로컬 설정과 다르면 중단한다.
3. `uv run python -m app.worker.pc run --service https://<본인-서비스> --max-output-tokens 2048 --requests-per-minute 10 --max-concurrency 1`로 시작한다. `--env`와 `--credentials`로 개인 파일 위치를 지정할 수 있다. 기본 `.worker-device.json`은 커밋 제외이며 토큰을 출력하지 않는다. Windows는 본인 Windows 계정의 DPAPI로 암호화하고 파일 소유자·사용자 전용 DACL을 검사한다. macOS/Linux는 소유자·600 권한을 검사한다. 기존 파일을 덮지 않으므로 재연결 때 본인이 기존 파일을 삭제하거나 새 파일 경로를 선택한다.
4. **PC와 프로그램을 켜 두어야 AI가 동작한다.** 브라우저를 닫아도 실행기는 계속된다. 중지는 `Ctrl+C`, 연결 해제는 서버 `/settings`에서 한다. 이미 OpenAI에 전송한 요청의 취소는 보장하지 않지만 해제 후 결과는 거부한다. 키 교체·삭제는 개인 `.env` 수정 후 실행기를 중지하고 재시작한다. 모드 변경·장치 교체는 미완료 작업을 취소하고 재승인을 요구한다.

Windows PowerShell 빠른 시작(본인 사용자 폴더의 저장소 루트에서 실행, [uv 설치 안내](https://docs.astral.sh/uv/getting-started/installation/) 참조):

```powershell
uv python install 3.12
uv sync --locked
if (-not (Test-Path .env.worker)) { Copy-Item .env.example .env.worker }
notepad .env.worker
```

메모장에서 개인 키·본인 식별자·모델을 채운다. 서버 `/settings`에서 `local_worker`를 선택한 뒤, 본인이 사용할 서비스 주소를 확인하고 실행한다:

```powershell
$serviceUrl = "https://aio3-gmail-quote.onrender.com"
uv run python -m app.worker.pc pair --service $serviceUrl --env .env.worker --name "내 Windows PC"
# 본인 서버 화면에서 PC의 이름·코드를 대조해 승인한 후:
uv run python -m app.worker.pc run --service $serviceUrl --env .env.worker --max-output-tokens 2048 --requests-per-minute 10
```

Windows 장치 파일은 다른 Windows 사용자·PC로 복사해서 재사용하지 않는다. `credentials_unavailable`이면 현재 사용자/로컬 파일 접근 권한·파일 손상을 확인하고, 본인이 기존 파일을 삭제하거나 새 `--credentials` 경로로 다시 연결·승인한다. macOS/Linux에서 만든 평문 장치 파일을 Windows에서 자동으로 받아들이지 않는다.

모델은 PC `OPENAI_MODEL`과 서버 모델이 같아야 하며 임의 모델로 대체하지 않는다. 출력 토큰(기본 2048, 최대 32768), 호출 빈도(기본 분당 10회, 최대 60회), 동시 작업 1개는 PC가 강제한다. 서버는 이 상한·OpenAI URL·헤더를 작업으로 지정하지 못한다. 인증서 검증과 환경의 프록시·CA 신뢰를 유지하며, 인증서 검사 해제나 리다이렉트는 제공하지 않는다. 서버는 여전히 Gmail 메일·스레드·프롬프트 변수·AI 결과·문서를 본다. 이 방식은 OpenAI 키만 PC에 두며 메일을 서버로부터 숨기는 방식은 아니다.

문제 해결: `WORKER_UNAVAILABLE`은 PC 오프라인/해제이므로 실행·연결을 확인한다. `WORKER_TIMEOUT`은 PC 종료·임대/전체 기한 초과이므로 상태를 확인한 뒤 새 요청을 시작한다. `WORKER_VERSION_MISMATCH`는 동일 코드 버전·모델로 갱신하고 재연결한다. `WORKER_KEY_REQUIRED`는 `.env` 키 누락 또는 OpenAI 401/403이므로 키·결제·권한을 확인하고 재시작한다. `WORKER_OWNER_MISMATCH`는 본인 식별자와 연결 계정을 확인한다. `WORKER_RATE_LIMIT`은 OpenAI 429 또는 PC 상한이므로 기다린다. `WORKER_NETWORK`는 OpenAI 연결/503 재시도 소진이다. 프로그램의 안전한 `unauthorized`/`expired` 중단은 해제·토큰 30일 만료를 확인하고 다시 연결한다. 실패한 메일은 자동 재처리하거나 발송하지 않는다.

서버 프로토콜 시험은 `GET /api/worker/protocol`의 설치 정의·모델을 확인한 뒤 `POST /api/worker/pairings`로 이름과 지원 정의를 보내 시작한다. PC에 전달된 연결 코드와 이름을 본인 서버 화면에서 확인·승인하면 PC가 secret으로 조회해 장치 토큰을 한 번 받는다. 코드는 10분·1회, 토큰은 30일이며 서버에는 해시만 남긴다. 화면에는 온라인/오프라인·만료와 해제 기능을 제공한다. 재연결/교체는 새 승인으로 진행하고 기존 장치·미완료 작업을 취소한다.

PC는 outbound HTTPS로 본인 작업을 claim/heartbeat/complete하며 수신 포트나 터널이 필요 없다. 큐는 설치된 구조화 AI 요청만 받으며 장치 토큰에는 메일 승인·발송·파일 권한이 없다. OpenAI 키 입력 필드는 장치 API와 DB에 추가하지 않는다. 임대 만료만으로 이미 전송됐을 수 있는 요청을 자동 재배포하지 않으며 외부 API의 exactly-once를 보장하지 않는다. 세부 경로·한도·오류는 `docs/CONTRACT.md` 6절이다.

DB 마이그레이션은 기존 사용자·키·메일·승인을 보존한다. 운영 DB 백업 뒤 배포하며 Google OAuth·토큰 암호화 키·공용 Pub/Sub 설정은 유지한다. 전송 변수는 완료 때 삭제하며 검증 결과는 호출자에게 전달할 때까지만 암호화해 보관한다(소비·해제·원래 120초 기한에 삭제). 검증은 `uv run pytest tests/test_worker_execution.py tests/test_worker_process.py tests/test_worker_queue.py`와 임시 PostgreSQL의 `uv run --with pgserver==0.1.4 pytest tests/test_worker_postgres.py`로 한다. 실제 키·Gmail·Render 확인은 사람이 계획 5절에서 수행한다. 전용 로컬 앱 방식은 위의 `uv run python -m app.local` 설치·시작·중지 안내를 따른다.

### 코드 병합 뒤 실제 이용 전 확인

- GitHub 브랜치는 코드와 DB 변경 스크립트를 보관한다. 운영 DB의 사용자·메일·문서·승인 데이터는 브랜치에 들어 있지 않으므로 DB 백업을 대신하지 못한다. 운영 데이터는 이용 가능한 Render 백업/스냅샷 또는 `pg_dump` 등으로 별도 보관하고, 복구에 필요한 기존 `TOKEN_ENCRYPTION_KEY`도 안전하게 유지한다. DB 백업·암호화 키를 공개 GitHub에 올리지 않는다.
- 자동/가짜 API 시험 통과와 실제 서비스 연결 확인은 구분한다. 1~4절의 코드가 병합돼도 Render 배포·DB 갱신 결과, 개인 PC 설치·키/모델 설정, 본인 로그인·장치 승인, 가상 메일과 네 문서 추출을 실제 환경에서 확인해야 한다. 이 확인 전에는 서비스 전체가 정상이라고 단정하지 않는다. 계획 5절(#157)이 그 확인 단계이며, 실패가 나오면 해당 구현을 수정한다.
- AI는 코드/배포 설정 검토, 자동·모의 시험, 실제 확인 절차와 비밀값 없는 결과 정리를 도울 수 있다. 현재 Codex 환경에는 실제 API 키를 넣지 않으므로 개인 키 입력·Google 동의/장치 승인·본인 PC 실행·실제 API 과금 프로젝트 확인은 사람이 한다. 권한 있는 환경에서 수행 가능한 DB 백업/배포 지원도 별도 명시적 요청과 실제 접근 권한이 있어야 하며, 이 작업에서 실행하지 않았다.
- AI에 맡길 준비 작업 요청문: `Issue: #157. local-openai-execution.md 5절의 사전 점검과 실행 절차·결과 기록 초안을 준비해 주세요. 코드·마이그레이션·기존 자동 검사 근거를 확인하고, 실제 키 입력·운영 변경·개인 메일 시험은 하지 말아 주세요. 사람이 할 PC/계정/API 확인을 구분하고 미확인 결과를 완료로 표시하지 마세요.`

| 무엇 | 쓰임 | 키 발급 | 환경변수 |
|---|---|---|---|
| OpenAI Responses API `gpt-6-luna` | 메일 분석·답장·거래 추출·요약·성찰과 무역 문서 AI 추출(PI·PO·CI·PL) | OpenAI 플랫폼 API 키 화면(https://platform.openai.com/api-keys) | 서버: 사용자별 `/settings` 등록. 전용 로컬: `AI_RUNTIME=local`·`LOCAL_OWNER_GOOGLE_SUB`·`OPENAI_API_KEY`. 모델은 `OPENAI_MODEL`(비우면 `gpt-6-luna`) |
| Gmail API | 사용자별 메일 읽기·감시 등록, 승인한 답장·견적서 첨부 발송 | Google Cloud 콘솔: Gmail API 사용 설정 → Google Auth Platform → Clients에서 OAuth 웹 애플리케이션 클라이언트 생성, 로컬·Render 콜백 주소 등록 | `GOOGLE_OAUTH_CLIENT_ID` `GOOGLE_OAUTH_CLIENT_SECRET` `GOOGLE_OAUTH_REDIRECT_URI` |
| Cloud Pub/Sub | Gmail 메일함 변경 알림을 서비스로 푸시 전달 | Google Cloud 콘솔: Pub/Sub API 사용 설정 → 토픽·푸시 구독 설정. OIDC 확인 방식 권장, 비밀 토큰은 대체 방식을 쓸 때만 | `GMAIL_PUBSUB_TOPIC` `PUBSUB_PUSH_AUDIENCE` `PUBSUB_PUSH_SERVICE_ACCOUNT` `PUBSUB_PUSH_TOKEN`(대체 방식 전용) |
| Google Calendar API | 도구 2(구글캘린더 등록)용으로 유지 | Calendar API와 사용자별 Google OAuth를 사용. 일정 도구 작업 때 연결 | Gmail과 같은 `GOOGLE_OAUTH_CLIENT_ID` `GOOGLE_OAUTH_CLIENT_SECRET` `GOOGLE_OAUTH_REDIRECT_URI` |

API 키 외 앱 설정도 같은 계약 11절을 따른다. 실제 값은 `.env`·Render에만 넣는다.

| 환경변수 | 설명 |
|---|---|
| `DATABASE_URL` | Postgres 접속 주소. 로컬에서 비우면 SQLite 파일 사용 |
| `TOKEN_ENCRYPTION_KEY` | Google 토큰·사용자 OpenAI 키 암호화 키. 기존 값을 유지한다 |
| `SESSION_SECRET` | 로그인 세션 쿠키 서명 키 |
| `APP_BASE_URL` | 서비스 주소. 링크·리디렉션 확인용 |
| `REFLECTION_ENABLED_DEFAULT` | 성찰 기본값. 설정할 때 `true` 또는 `false` 지정 |

특일 정보·단기예보·네이버 지역 검색·네이버 길찾기는 MVP에서 제외했다. 일정(캘린더) 도구 작업 때 `.work/design/api-choice.md`의 '일정 도구 추천 후보'를 요청자에게 추천하고 채택 여부를 확인한다.

주의:

- 메일과 기억·추출에 필요한 내용을 OpenAI API로 전송한다. 테스트용 Google 계정과 가상 메일을 사용하고 실제 개인정보를 넣지 않는다. API 데이터 보관·이용은 [OpenAI 안내](https://platform.openai.com/docs/guides/your-data)와 계정 설정을 확인한다. 일정 도구 연결 때도 LLM에는 일정 제목 없이 바쁜 시간대만 넘긴다.
- OpenAI API는 ChatGPT 구독과 별도로 과금된다. 키를 만든 프로젝트의 결제·사용 한도·선택 모델 이용 권한을 확인한다. 무료 이용이나 무제한 호출을 가정하지 않는다.
- OAuth 게시·권한과 Pub/Sub 푸시 수신 인증은 별도 Google Cloud·로그인·알림 수신 작업에서 설정한다.
- LLM·외부 API를 더하거나 바꾸는 일은 요청자가 정한다(`.work/TASK.md`).

전환 적용 순서:

1. 공용 `.env`·Render의 `OPENAI_API_KEY`를 제거한다. 다른 모델을 쓸 때만 `OPENAI_MODEL`을 지정한다. 기존 `TOKEN_ENCRYPTION_KEY`·Google OAuth·Gmail·Pub/Sub 값은 유지한다.
2. DB 백업 후 PR 병합·Render 자동 배포(`uv sync --locked`)가 끝나면 각 사용자가 로그인해 `/settings`에 본인 키를 등록한다. 저장은 API를 호출하지 않으며 유효성은 실제 AI 요청 시 확인한다. 가상 메일·무역 문서로 본인 프로젝트의 사용량을 확인한다. 미등록 상태에서 실패한 메일은 자동 재처리하지 않는다. 키 교체·삭제는 다음 AI 호출부터 적용되며 이미 시작된 작업은 취소되지 않는다.
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

React는 기존 Google 로그인 세션으로 `GET /api/session`에서 CSRF 토큰을 받고, 변경 요청에 `X-CSRF-Token`과 세션 쿠키를 함께 보낸다. PI는 `/api/trade/pi`에서 작성/목록, `/extract`에서 텍스트 추출, `/{id}`에서 조회/전체 수정, `/{id}/versions/{revision}`에서 이전 버전을 조회한다. 입력 수량·금액은 정확한 십진수 문자열이며 API 형식은 `/docs`에서 확인한다.

`POST /api/trade/pi/{id}/reviews`에 `revision`과 `formats`(`pdf`, `xlsx`)를 보내 검토 제안을 만든다. 반환된 제안의 ID·revision·content_hash를 그대로 `…/reviews/{proposal_id}/decisions`로 보내 `approve`, `cancel`, `modify` 중 하나를 선택한다. 수정 선택은 `document`에 새 입력 전체를 함께 보내며 새 버전·새 제안을 다시 확인한다. 부족한 수정 입력은 `needs_input`으로 돌아온다. 승인은 문서 확정과 파일 발급이며 메일 발송을 포함하지 않는다. 취소 시 파일을 발급하지 않고, 승인 재시도는 같은 파일을 반환한다. 파일은 로그인한 소유자만 `/api/trade/files/{file_id}`에서 내려받는다.

회사·통화별 은행·단가는 `/api/trade/settings` 하위 API, 직인/로고 PNG는 `/branding/{seal|logo}`에 설정한다. 검토 제안에는 그 시점의 문서·계좌·이미지를 보관해 이후 설정 변경이 승인 파일을 바꾸지 않는다. 다른 주소의 React는 `FRONTEND_ORIGINS`에 허용 출처를 지정하고 `credentials: 'include'`를 사용한다. 서로 다른 사이트의 쿠키가 필요하면 HTTPS에서만 `SESSION_SAME_SITE=none`을 사용한다. 운영 배포·React 화면은 이번 백엔드 구현에 포함하지 않는다.
