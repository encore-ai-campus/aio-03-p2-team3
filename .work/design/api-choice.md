# LLM·외부 API 선택

세팅 3-2-1(LLM)·3-2-2(외부 API)의 선택과, 요청자가 2026-11-09에 정한 Gmail 견적 MVP의 API 변경을 기록한다(`docs/plans/gmail-quote-mvp.md#3`, R-04·D-03). 환경변수는 `docs/CONTRACT.md` 11절을 기준으로 `.env.example`·README에 반영한다. [Request]
나중에 기능을 더하며 다른 LLM·API를 더하거나 바꾸면 요청자에게 묻고 이 파일을 고친다(`.work/TASK.md` 이 레포의 규칙). [Request]

## 지식 문서 비전 AI 추출 방식 (2026-11-13, 계획)

- 사용자 선택: 지식 문서는 전부 비전 AI로 읽는다. 텍스트 PDF와 스캔을 일반 파서/Tesseract로 나누어 추출하는 방식은 사용하지 않는다. 이 선택은 `docs/plans/document-ingestion.md`의 계획이며 기존 메일/무역 추출 코드나 운영 설정을 바꾸지 않았다.
- 경계: `DocumentExtractor`와 `Embedder`를 독립적으로 주입해 비전 추출 모델과 임베딩 모델을 각각 바꿀 수 있게 한다. 현재 앱의 구조화 AI·PC 실행 프로토콜이 지식 문서 이미지/임베딩 입력을 이미 지원한다고 가정하지 않는다.
- 입력: 확정 형식은 전 페이지를 출처/순서가 있는 이미지로 변환해 비전 모델에 전달한다. PDF·Office·TXT 등의 변환/렌더러 설치와 표·인쇄 영역/잘림은 별도 검증한다. Tesseract/한국어 데이터 설치를 이번 필수 조건으로 두지 않는다.
- 미확정: 구체 비전 공급자/모델, 임베딩 공급자/모델·차원, 실제 문서 외부 전송/보관 범위, 변환 도구와 HWP 대응. 기존 사용자 키를 쓰는 OpenAI는 후보이며 기본 `OPENAI_MODEL`이 비전 입력을 지원하는지/정확한지 실제 확인한 것은 아니다. 새로운 환경변수·모델 기본값은 공급자를 선택하는 후속 작업에서 README·`.env.example`과 함께 정한다.
- 검증: 원문/표/페이지 대응·출력 중단·판독 불가를 확인하고 의심 구간은 검토/수정 후 임베딩한다. 실제 문서 업로드·모델 호출·비용/정확도 측정·운영 배포는 하지 않았다. Parent-child는 별도의 청크/검색 구조 추천이며 사용자 채택으로 기록하지 않는다.
- 출처: [OpenAI 파일 입력](https://developers.openai.com/api/docs/guides/file-inputs), [비전의 한계](https://developers.openai.com/api/docs/guides/images-vision#limitations). API의 PDF·일반 문서 처리 차이와 작은 글씨/한국어/정확도 제한을 확인했다. 특정 공급자 채택의 근거로 바꾸지 않는다.

## LLM
### 전용 로컬 .env 키 모드 (2026-11-12, Issue #153)
- 요청: 개인 PC에서 본인 `.env` 키를 사용하고 공용 서버의 환경 키 사용 금지를 유지한다. `AI_RUNTIME` 기본은 `server`이며, 전용 `uv run python -m app.local`의 실제 루프백 리스너가 있는 `local` 실행에서만 환경 키를 선택한다. Render·공용 실행은 로컬 모드로 시작할 수 없다.
- 본인 확인: Google 검증 로그인 후 로컬 `/settings`에서 본인 식별자를 확인해 `LOCAL_OWNER_GOOGLE_SUB`에 직접 지정한다. 일치하는 검증 사용자만 허용하고 소유자 미지정·다른 사용자·키 누락은 차단한다. 최초 방문 자동 등록은 없다. 로컬 모드에서는 DB 사용자 키 조회·저장·교체·삭제를 차단하고 `.env` 변경 뒤 재시작한다. 키·해시·부분 문자열을 노출하지 않는다.
- 서버의 사용자별 암호화 DB 키 방식·명시적 가짜 백엔드 주입은 유지한다. 어느 서버 사용자 키가 없어도 환경 키로 대체하지 않는다. 모델·OpenAI API 선택은 기존과 같다. 개인 PC Gmail 수집·Render 장치 연결·큐·개인 실행 프로그램은 아직 없으며 후속 계약만 `docs/CONTRACT.md` 6절에 정했다. 실제 키·운영 설정 변경·실제 API 호출은 하지 않았다.

### 사용자별 키 등록 (2026-11-12)
- 요청: 공용 사이트에서도 각 사용자의 OpenAI 키만 사용한다. `/settings`에서 등록·교체·삭제하고 기존 `TOKEN_ENCRYPTION_KEY`로 암호화해 사용자별 DB 행에 보관한다. 메일 자동 처리·요약·성찰·4종 문서 AI 추출 모두 소유자 키를 선택한다.
- 기본 `server` 실행에서는 `.env`의 `OPENAI_API_KEY`를 호출에 사용하지 않는다. 키가 없거나 복호화할 수 없으면 차단하며 공용 키 대체 경로는 없다. 전용 로컬 실행은 위 절의 별도 소유자 제한을 따른다. 모델 설정은 기존 `OPENAI_MODEL`을 유지한다. 저장 시 API 호출은 하지 않는다. 아래 11/11의 환경변수 키 등록 절차는 이전 기록이다.

현재 선택: 2026-11-11 · 모든 LLM 호출을 OpenAI Responses API로 통일. 아래 후보·초기 선택·모델 변경은 당시 기록이다.

### 전체 OpenAI 전환 (2026-11-11)
- 바꾼 것: 메일 분석·답장 후보·거래 추출·스레드 요약·성찰과 PI·PO·CI·PL 독립 문서 추출을 모두 LangChain `ChatOpenAI(use_responses_api=True)`로 호출한다. 사용자가 Gemini에서 OpenAI로 전환하도록 요청했다. Gmail API·Google OAuth·Cloud Pub/Sub·Calendar 연결은 별도 API이므로 유지한다. [Request]
- 모델·설정: 무역 문서 추출에 이미 채택한 기본 모델 `gpt-6-luna`를 유지하고 전체 호출에 사용한다. `OPENAI_API_KEY`와 선택값 `OPENAI_MODEL`만 읽으며, `GEMINI_API_KEY`·`GEMINI_MODEL`·`TRADE_EXTRACT_BACKEND`는 더 이상 읽지 않는다. Gemini로 되돌아가는 경로와 `langchain-google-genai` 의존성을 제거한다.
- 구조화 출력: `call_structured()`를 공유하고 실제 `ChatOpenAI`에는 `with_structured_output(schema, method="function_calling", strict=False)`를 쓴다. 기존 스키마의 기본값·선택 필드·자유 키 dict를 보존하면서 반환값을 Pydantic으로 검증한다. 독립 무역 추출의 wire 스키마와 십진수 문자열 검증은 유지한다. SDK 자동 재시도는 0, 제한 시간은 20초이며 429는 재시도하지 않는다. 시간 초과·연결 오류·5xx는 최대 3회 시도하고 형식 오류는 별도 1회 재시도한다.
- 적용: 로컬 `.env`·Render에 `OPENAI_API_KEY`를 먼저 등록하고 프로젝트의 결제·사용 한도·모델 권한을 확인한다. PR 병합과 자동 배포 뒤 `/healthz`·가상 메일·독립 문서 추출을 확인하고 예전 Gemini 변수와 `TRADE_EXTRACT_BACKEND`를 제거한다. ChatGPT 구독과 OpenAI API 이용료는 별개다. 키는 채팅·레포·Codex 환경에 넣지 않는다.
- 데이터·시험: OpenAI API로 메일과 필요한 기억·문서 입력이 전송된다. 테스트용 계정과 가상 자료만 사용한다. 데이터 보관·이용은 [OpenAI API 데이터 안내](https://platform.openai.com/docs/guides/your-data)와 계정 설정을 확인한다(이 환경에서는 해당 페이지가 HTTP 403으로 열리지 않아 최신 정책을 직접 확인하지 못함). Codex 검증은 대역만 사용하며 실제 API 성능과 성찰 비교 지표는 전환 뒤 다시 측정한다. 과거 Gemini 시험 기록·원본 사본은 당시 근거로 보존한다.

### 후보
| 항목 | Google Gemini API | Groq |
|---|---|---|
| 무료 한도 | 문서에 숫자 없음. AI Studio에서 내 프로젝트 한도 확인. 프로젝트 단위, 하루 한도는 태평양 시간 자정 초기화 | Free plan: `openai/gpt-oss-120b`·`openai/gpt-oss-20b`·`qwen/qwen3.8-27b` 각 분당 30회·하루 1,000회·분당 8K 토큰·하루 200K 토큰. 조직 단위 |
| 무료 모델(텍스트) | `gemini-3.8-flash`, `gemini-3.6-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3-flash-preview`, Gemma 4. `gemini-2.5-pro`·`gemini-2.5-flash`는 지원 중단(2026-12-01부터 다른 모델로 넘어감). Pro·Gemini 4 Argon은 무료 아님. 무료 등급은 Gemini 3 이상에서 Google 검색·지도 그라운딩 불가 | 위 칸의 모델 |
| 무료 등급 데이터 사용 | 가격 페이지 'Used to improve our products': 무료 Yes, 유료 No. 입력·응답을 Google 제품·모델 개선에 쓸 수 있고 사람이 검토할 수 있다. 민감·기밀·개인 정보를 넣지 말 것. 만 18세 이상 | 기본적으로 추론 요청 데이터를 보관하지 않는다. 조사용 로그 최대 30일(끌 수 있음). 학습 사용 여부는 문서에 없음 |
| LangChain 패키지 | `langchain-google-genai` (`ChatGoogleGenerativeAI`) | `langchain-groq` (`ChatGroq`) |
| 환경변수 | `GOOGLE_API_KEY` 또는 `GEMINI_API_KEY` | `GROQ_API_KEY` |

### 고른 것 (2026-11-05)
- Google Gemini API, 모델 `gemini-3.8-flash`. 까닭: 무료 텍스트 모델 가운데 에이전트 작업용으로 가장 강한 모델이다. [Request: 사용자가 추천안을 고름]
- 무료 한도가 Groq보다 넉넉한지는 확인하지 못했다(숫자 비공개). 키를 만든 사람이 AI Studio에서 `gemini-3.8-flash`의 분당 요청·분당 토큰·일당 요청을 보고 이 줄을 고친다. [Claude proposal]
- 무료 등급은 입력이 Google 제품 개선에 쓰이므로 실제 개인정보를 넣지 않는다(RULES 3절). 11/19 상호 체험 때 화면에 '개인정보를 넣지 마세요'를 안내한다. [Claude proposal]
- 쓰지 않는 것: Groq(분당 8K 토큰이 이 과제에 빠듯함), 다른 LLM으로 넘기는 대비책(모델이 바뀌면 응답 일관성 지표가 흔들림). 필요해지면 요청자에게 묻고 더한다. [Claude proposal]

### 모델 변경 (2026-11-10, Issue #62)
- 바꾼 것: 기본 모델을 `gemini-3.8-flash` → `gemini-3.6-flash`로 바꿨다. [Request: 요청자가 추천안을 고름]
- 까닭: 실제 API 확인(#62)에서 Render의 메일 분석 호출 6번이 모두 `network`로 실패했고, 요청자 PC에서 같은 키로 짧은 요청(`hello`)을 보내도 `gemini-3.8-flash`는 5번 모두 HTTP 503(0.9~7.9초)이었다. 같은 때 `gemini-3.6-flash`·`gemini-3.5-flash-lite`는 3번 모두 200, `gemini-3.1-flash-lite`는 3번 모두 503이었다. 3.6은 응답한 모델 가운데 lite보다 성능이 높다. Google 개발자 포럼의 Google 측 답변은 무료 등급 3.8 Flash의 503을 서비스 일시 과부하로 설명한다(https://discuss.ai.google.dev/t/free-tier-interactions-api-getmodel-succeeds-but-generation-returns-503-on-gemini-3-8-flash-and-429-on-gemini-3-6-flash/189550 , 2026-11-10 조회).
- 방식: 모델 이름은 `app/llm/client.py`의 `DEFAULT_MODEL`이고 환경변수 `GEMINI_MODEL`로 덮어쓴다. 시연 때 3.6도 막히면 Render 환경변수만 바꿔 다른 무료 모델로 옮긴다(재배포됨). 한 실행 안에서 모델을 섞는 대비책은 여전히 두지 않는다(응답 일관성). [Claude proposal]
- 함께 한 일: 이전 키가 대화에 노출돼 같은 결제 없는 프로젝트에서 새 키를 만들어 Render `GEMINI_API_KEY`를 바꿨다(요청자, 2026-11-10). 키 값은 레포에 두지 않는다.

### 무역 문서 추출용 OpenAI Responses 추가 (2026-11-11, 전체 전환 전 기록)
- 바꾼 것: 무역 도메인 AI 추출(PI·PO·CI·PL의 `POST /api/trade/{kind}/extract`)은 LangChain `ChatOpenAI(use_responses_api=True)`로 OpenAI Responses API를 기본 백엔드로 쓴다. 메일 그래프·견적 도구는 계속 Gemini를 쓴다. [Request: 요청자가 방향을 정함]
- 까닭: 이식 원본(`reference/kekorea/Quotation_KEKOREA/agent/extractor.py`)이 OpenAI Responses API로 문서를 추출했다. 실제 Gemini 키 확인(2026-11-11)에서 도메인 추출 스키마의 HTTP 입력 제약(`pattern`·`maxLength`·`maxItems`)을 Gemini 구조화 출력이 400 INVALID_ARGUMENT로 거부했다(메일 그래프 스키마는 제약이 없어 동작). 또 숫자를 JSON number로 받으면 십진수 정밀도가 깨지므로 원본처럼 전부 문자열로 받는다.
- 방식: 백엔드 선택은 `app/trade/common/extraction.py`의 `trade_backend()`(환경변수 `TRADE_EXTRACT_BACKEND`, 기본 `openai_responses`, `gemini`로 복귀 가능). 모델은 원본 기본값 `gpt-6-luna`이고 `OPENAI_MODEL`로 덮어쓴다. LLM에는 제약을 떼고 숫자를 문자열로 바꾼 wire 스키마를 주고, 돌려받은 값은 원래 스키마로 다시 검증해 Decimal로 바꾼다. 재시도·오류 분류·기록은 그래프와 같은 `call_structured()`를 공유하며 OpenAI SDK 예외(429·400·연결 오류) 분류를 더했다.

### 설정 경로
1. OpenAI 플랫폼 API 키 화면(https://platform.openai.com/api-keys)에서 프로젝트 API 키를 만든다. 해당 프로젝트의 API 결제·사용 한도와 `OPENAI_MODEL`의 이용 권한을 확인한다. 키는 비밀번호처럼 다루고 레포에 넣지 않는다.
2. 환경변수 `OPENAI_API_KEY`를 등록하고, 기본 `gpt-6-luna`를 바꿀 때만 `OPENAI_MODEL`을 지정한다. 메일과 무역 추출이 같은 모델을 사용한다.
3. 키는 로컬 `.env`와 Render 환경변수에 둔다. Codex 환경에는 키를 넣지 않고 가짜 응답으로 테스트한다(`.work/TASK.md` 환경 줄). 등록 → PR 병합·자동 배포 → 가상 자료로 확인 → 예전 Gemini 환경변수 제거 순서다.

### 출처
- OpenAI SDK 설정·Responses API·오류 구분: https://github.com/openai/openai-python (실제 구현은 설치한 SDK 및 `langchain-openai` 소스와 대조)
- OpenAI 키·결제·데이터 안내: https://platform.openai.com/api-keys , https://platform.openai.com/settings/organization/billing/overview , https://platform.openai.com/docs/guides/your-data (계정·정책 확인 경로, 이 환경에서 콘솔·결제 설정이나 최신 정책 확인은 수행하지 않음)
- Gemini 한도: https://ai.google.dev/gemini-api/docs/rate-limits (2026-11-05)
- Gemini 무료 모델·데이터 사용: https://ai.google.dev/gemini-api/docs/pricing (도구로 못 열어 사용자가 붙여 줌, 2026-11-05)
- Gemini 무료 등급 데이터 사용: https://ai.google.dev/gemini-api/terms 'Unpaid Services' (2026-11-05)
- Groq 한도: https://console.groq.com/docs/rate-limits Free plan (2026-11-05)
- Groq 데이터: https://console.groq.com/docs/your-data (2026-11-05)
- 키 발급·환경변수 우선순위: 공식 GitHub `googleapis/python-genai` README, `google-gemini/cookbook` `quickstarts/Authentication.ipynb` (2026-11-05)
- 패키지·환경변수: PyPI `langchain-google-genai` 4.4.3, `langchain-groq` 1.1.3 소스 (2026-11-05)

## 외부 API
선택 갱신: 2026-11-09 · 콘솔 설정과 실제 API 시험은 별도 작업

### 고른 것 (2026-11-09)
| API | 쓰임 | 인증·설정 |
|---|---|---|
| Gmail API | 사용자별 메일 읽기, 감시 등록, 승인한 답장·견적서 첨부 발송 | 사용자별 Google OAuth 로그인 |
| Cloud Pub/Sub | Gmail의 메일함 변경 알림을 서비스로 푸시 전달 | Gmail 감시 토픽, 푸시 구독과 수신 요청 인증 |
| Google Calendar API | 도구 2(구글캘린더 등록)용으로 유지 | 사용자별 Google OAuth 로그인. 일정 도구 구현 때 연결 |

- 2026-11-09에는 LLM을 Gemini `gemini-3.8-flash`로 유지했다(이후 변경은 위 LLM 절). Gmail API·Cloud Pub/Sub를 추가하고 Calendar를 유지하는 것은 요청자가 정한 변경이다. [Request]
- 한국천문연구원 특일 정보·기상청 단기예보·네이버 지역 검색·네이버 길찾기는 MVP에서 뺀다. 아래 '일정 도구 추천 후보'에 보관하고, 현재 키 발급·환경변수 설정 대상에서는 제외한다. [Request]
- 체험자는 테스트용 Google 계정과 가상 메일을 쓴다. LLM에 실제 개인정보를 넣지 않으며, 일정 도구를 연결할 때도 일정 제목 없이 바쁜 시간대만 넘긴다.
- OAuth 게시·권한 설정과 푸시 수신 인증은 별도 Google Cloud·로그인·알림 수신 작업에서 처리한다. 이 문서 갱신으로 콘솔 설정이나 연동이 완료된 것은 아니다.

### 설정 경로
1. Google Cloud 콘솔의 프로젝트에서 Gmail API·Cloud Pub/Sub API를 사용 설정한다. Google Calendar API는 도구 2용으로 유지한다.
2. Google Auth Platform → Branding·Audience·Data Access에서 앱과 필요한 권한을 설정하고, Clients에서 OAuth 웹 애플리케이션 클라이언트를 만든다. `GOOGLE_OAUTH_CLIENT_ID`·`GOOGLE_OAUTH_CLIENT_SECRET`을 보관하고, 로컬·Render 각각의 콜백 주소를 등록해 `GOOGLE_OAUTH_REDIRECT_URI`에 맞춘다. 서비스 주소는 `APP_BASE_URL`이다.
3. Pub/Sub에서 토픽과 푸시 구독을 설정한다. Gmail 감시 등록에 쓰는 토픽 전체 이름을 `GMAIL_PUBSUB_TOPIC`에 둔다. 추천하는 OIDC 확인 방식은 `PUBSUB_PUSH_AUDIENCE`·`PUBSUB_PUSH_SERVICE_ACCOUNT`를 쓰며, 대체 비밀 토큰 방식을 택할 때만 `PUBSUB_PUSH_TOKEN`을 쓴다.
4. 앱 설정으로 Google 토큰 암호화 키 `TOKEN_ENCRYPTION_KEY`, 로그인 세션 쿠키 서명 키 `SESSION_SECRET`, Postgres 접속 주소 `DATABASE_URL`, 성찰 기본값 `REFLECTION_ENABLED_DEFAULT`를 준비한다. 로컬에서 `DATABASE_URL`을 비우면 SQLite 파일을 쓴다. 이름·뜻은 `docs/CONTRACT.md` 11절, 값 없는 설정 틀은 `.env.example`에 있다.
- 키와 설정값은 각자 로컬 `.env`와 Render 환경변수에만 둔다. 콘솔·계정 설정은 계획의 별도 작업에서 진행한다.

### 출처
- Calendar 한도·범위: https://developers.google.com/workspace/calendar/api/guides/quota , .../guides/auth
- OAuth 게시 상태: https://support.google.com/cloud/answer/15549945
- Gmail 메일함 푸시 알림·Pub/Sub 연결: https://developers.google.com/workspace/gmail/api/guides/push
- Pub/Sub 인증된 푸시: https://cloud.google.com/pubsub/docs/authenticate-push-subscriptions
- 선택 근거: `docs/plans/gmail-quote-mvp.md#3`(2026-11-09 요청), 환경변수 계약: `docs/CONTRACT.md` 11절

### 콘솔 설정 결과 (2026-11-10, 계획 5절)
- 정한 것 [Request]: Gmail·OAuth·Pub/Sub 전용 Google Cloud 프로젝트 `aio3-gmail-quote`를 따로 만들고 이 프로젝트에만 결제 계정을 연결한다. Gemini 키가 있는 프로젝트에는 결제를 연결하지 않는다. Google 검증(브랜딩·데이터 액세스)은 신청하지 않고, 확인되지 않은 앱 경고와 사용자 100명 상한을 감수한다.
- OAuth: 게시 상태 프로덕션 단계(검증 없음), 사용자 유형 외부. 범위 `openid`·`userinfo.email`·`gmail.readonly`·`gmail.send`(`app/config.py`의 `GOOGLE_SCOPES`와 같음). 웹 애플리케이션 클라이언트의 리디렉션 URI는 `https://aio3-gmail-quote.onrender.com/auth/google/callback`, `http://localhost:8000/auth/google/callback`.
- 브랜딩: 앱 이름 `Gmail 견적 도우미`(화면 이름과 같음), 홈페이지 `/about`·개인정보처리방침 `/privacy`·서비스 약관 `/terms`(서비스 주소 아래, #82), 승인된 도메인 `aio3-gmail-quote.onrender.com`(`onrender.com`은 Public Suffix List에 있어 서비스 주소가 최상위 개인 도메인).
- Pub/Sub: 토픽 `projects/aio3-gmail-quote/topics/gmail-notify`(게시자: `gmail-api-push@system.gserviceaccount.com`, 역할 Pub/Sub 게시자. 2026-11-10 실제 API 확인(#62) 때 이 권한이 빠져 있어 감시 등록이 HTTP 403으로 실패했고, 그때 추가했다), 푸시 구독 `gmail-notify-push` → `https://aio3-gmail-quote.onrender.com/gmail/push`, 인증 사용(서비스 계정 `gmail-push-auth@aio3-gmail-quote.iam.gserviceaccount.com`, 대상 = 엔드포인트 주소), 확인 기한 120초, 재시도 정책 지수 백오프(기본 10~600초).
- Render 환경변수(이름): `GOOGLE_OAUTH_CLIENT_ID`·`GOOGLE_OAUTH_CLIENT_SECRET`·`GOOGLE_OAUTH_REDIRECT_URI`·`GMAIL_PUBSUB_TOPIC`·`PUBSUB_PUSH_AUDIENCE`·`PUBSUB_PUSH_SERVICE_ACCOUNT`. 값은 레포에 두지 않는다.

### 공식 문서 확인 결과 (2026-11-09~10 조회, 계획 5절 항목별)
1. 결제: Free Tier 범위 안이라도 Cloud Billing 계정이 있어야 한다. Pub/Sub Free Tier는 결제 계정당 월 10 GiB. Gemini는 결제를 연결하지 않은 프로젝트에 둬야 무료 등급이 유지되며, 무료 키와 유료 키는 프로젝트를 나누라고 안내한다. 출처: https://docs.cloud.google.com/billing/docs , https://docs.cloud.google.com/free/docs/free-cloud-features , https://cloud.google.com/pubsub/pricing , https://ai.google.dev/gemini-api/docs/billing
2. 토큰 만료: 외부·테스트 상태면 갱신 토큰이 7일 뒤 만료된다(기본 신원 범위만 요청하면 예외). 프로덕션 상태에서는 갱신 토큰이 취소되거나 오래(보통 6개월) 쓰지 않을 때 말고는 대체로 만료되지 않는다(7일 만료 없음). 검증 안 된 게시 앱은 민감·제한 범위에 경고 화면과 전체 사용자 100명 상한이 있다. 출처: https://developers.google.com/identity/protocols/oauth2 , https://developers.google.com/health/setup , https://developers.google.com/identity/protocols/oauth2/production-readiness/overview , https://support.google.com/cloud/answer/15549945
3. 범위 구분: `gmail.send`는 민감, `gmail.readonly`·`gmail.modify`는 제한 범위다. 출처: https://developers.google.com/workspace/gmail/api/auth/scopes . 이 범위로 감시 등록·기록 조회·메일 읽기·발송이 실제로 되는지는 계획 16(#62)에서 확인한다.
4. 브랜딩: 외부 프로덕션 앱은 홈페이지·개인정보처리방침·서비스 약관 링크가 필요하고, 링크 도메인은 승인된 도메인이어야 한다. 도메인 소유 확인(Search Console)은 검증을 신청할 때 필요하다. 출처: https://support.google.com/cloud/answer/15549049 , https://developers.google.com/identity/protocols/oauth2/production-readiness/brand-verification
5. 토픽 권한: Gmail 문서는 `gmail-api-push@system.gserviceaccount.com`에 publish 권한을 주라고 하며 역할 이름은 적지 않는다(Pub/Sub 게시자 역할로 줌). 감시 등록은 최소 7일마다(하루 1번 권장) 다시 해야 하고, 사용자당 알림은 초당 1개까지다. 출처: https://developers.google.com/workspace/gmail/api/guides/push
6. 푸시 인증: 인증을 켜면 Pub/Sub가 서명한 JWT를 `Authorization` 헤더로 보내고, 받는 쪽은 대상과 서비스 계정 이메일(`email`, `email_verified`)을 확인한다. 서비스 계정은 구독과 같은 프로젝트에 있어야 한다. 출처: https://docs.cloud.google.com/pubsub/docs/authenticate-push-subscriptions , https://docs.cloud.google.com/pubsub/docs/create-push-subscription
7. 잠든 Render와 푸시: 푸시 요청 제한 시간은 확인 기한과 같고(기본 10초, 최대 600초), 기한 안에 성공 응답이 없으면 재시도 정책대로 다시 보낸다(지수 백오프 기본 10~600초). 확인되지 않은 메시지는 기본 7일 보관된다. Render 무료 서버는 15분 동안 요청이 없으면 잠들고 깨는 데 약 1분 걸리므로 확인 기한을 120초로 했다. 실제로 첫 푸시가 기다렸다 성공하는지, 재전송으로 처리되는지는 계획 16(#62)에서 확인한다. 출처: https://docs.cloud.google.com/pubsub/docs/subscription-properties , https://docs.cloud.google.com/pubsub/docs/subscription-retry-policy , https://docs.cloud.google.com/go/docs/reference/cloud.google.com/go/pubsub/latest , https://render.com/docs/faq

## 로그인·DB·파일 저장 — Supabase (2026-11-12)

`docs/plans/react-supabase/PLAN.md` 전환(React·JavaScript·Vite 화면)의 기반 선택이다. 요청자가 2026-11-12에 정했다. [Request] 콘솔 설정(계획 2절)·데이터 이전(계획 22절)은 별도 작업이며 이 문서 갱신으로 완료된 것이 아니다.

### 고른 것 (2026-11-12)
| 서비스 | 쓰임 | 인증·설정 |
|---|---|---|
| Supabase Auth | React 로그인. 시안의 Google 로그인부터 연결 | Google OAuth 코드 경로. 브라우저는 `VITE_SUPABASE_URL`·`VITE_SUPABASE_PUBLISHABLE_KEY`, 서버는 JWKS로 access token 검증(9.1절 계약) |
| Supabase PostgreSQL | 업무 DB. 기존 FastAPI·SQLAlchemy·Alembic 재사용 | 서버 `DATABASE_URL`. 업무 Data API 노출은 끔 |
| Supabase Storage | 사용자 첨부·회사 이미지·발급 파일 | 서버 `SUPABASE_URL`·`SUPABASE_SECRET_KEY`·`SUPABASE_STORAGE_BUCKET`(비공개 버킷 `trade-files`). 사용자 직접 정책은 기본 거부 |

- 기존 FastAPI 백엔드·Gmail·Pub/Sub·OpenAI 설정은 유지한다. Supabase 프로젝트는 요청자가 만든 `AIO_TEST`를 재사용한다(2026-11-12 확정). 실제 공급자·redirect·키 설정은 계획 2절에서 사용자와 함께 확인한다.
- 로그인 공급자는 Google OAuth 코드 경로만 먼저 연결한다. 이메일 가입·다른 공급자는 별도 요구 때 추가한다.
- 인증 경계·사용자 매핑·파일 저장 계약은 `docs/CONTRACT.md` 7.1·9.1·16.3절, 환경변수 이름은 11절과 `.env.example`이다.
- [미확정] 기존 SQLite·Render Postgres 데이터의 보존 대상·기간(계획 2절), 첨부 내용 자동 읽기 범위(보류). 사람이 확인한 뒤 이 파일을 고친다.

### 설정 경로
1. Supabase 콘솔 프로젝트 설정 → API에서 프로젝트 URL·publishable 키·secret 키를 확인한다.
2. 브라우저용 설정(`frontend/.env`)에는 `VITE_SUPABASE_URL`·`VITE_SUPABASE_PUBLISHABLE_KEY`만 둔다.
3. 서버 `.env`·Render 환경변수에는 `DATABASE_URL`(PostgreSQL 주소)·`SUPABASE_URL`·`SUPABASE_SECRET_KEY`·`SUPABASE_STORAGE_BUCKET`을 둔다. `SUPABASE_SECRET_KEY`는 브라우저·빌드 산출물에 넣지 않는다.
4. Auth → Providers에서 Google 공급자를 켜고 개발·배포 redirect 주소를 등록한다. 기존 앱 Gmail OAuth(`GOOGLE_OAUTH_*`)의 callback과는 별개로 등록한다(계획 2절).

### 출처
- 선택 근거: `docs/plans/react-supabase/PLAN.md`(2026-11-12 요청), 계약: `docs/CONTRACT.md` 7.1·9.1·11·16.3절
- Supabase 키 종류·JWKS 검증·private bucket·Data API 비활성화: 계획 '공식 확인 자료'의 Supabase 문서 링크(2026-11-12 확인 목록)

## 일정 도구 추천 후보
MVP에서 제외한 보조 API다(2026-11-09). 일정(캘린더) 도구 작업 때 AI가 아래 후보를 요청자에게 추천하고, 채택 여부를 확인한 뒤 API·환경변수를 추가한다. 현재 연동이나 키 발급은 하지 않는다. [Request]

아래 형식·한도는 세팅 때 공식 문서를 확인한 기록(2026-11-05)이다. 채택할 때 최신 한도·요금·설정 경로를 다시 확인한다.

| 후보 | 일정 도구에서의 쓰임 | 인증·형식 | 당시 확인한 한도 |
|---|---|---|---|
| 한국천문연구원 특일 정보 | 공휴일·절기를 고려한 일정 | 공공데이터포털 활용신청(자동승인), 인증키·XML | 개발계정 10,000회 |
| 기상청 단기예보 | 날씨를 고려한 일정 | 공공데이터포털 활용신청(자동승인), 인증키·JSON/XML | 개발계정 하루 10,000회 |
| 네이버 지역 검색(NAVER API HUB) | 장소→주소·좌표(WGS84), 1회 1~5개 | 네이버 클라우드 콘솔 API HUB Application 인증 정보·JSON | 하루 25,000회. 한시적 무료, 유료 전환 전 공지 |
| 네이버 Maps Directions 5 | 장소 간 이동·길찾기 | 네이버 클라우드 콘솔 Maps Application 인증 정보·JSON | Directions 5의 정확한 무료 건수는 미확인. 채택 때 확인하고 이용 한도를 무료량 이하로 설정 |

- 지역 검색 결과에 좌표가 있어 당시 Geocoding은 제외했고, 카카오 로컬도 고르지 않았다. 네이버 개발자센터 검색 API의 API HUB 이관 내용도 채택 시 다시 확인한다.

### 출처
- 특일 정보·단기예보: https://data.go.kr/data/15012690/openapi.do , https://www.data.go.kr/data/15084084/openapi.do
- 지역 검색: https://api.ncloud-docs.com/docs/naver-api-hub-search-local
- API HUB 무료·이관·콘솔 경로: https://guide.ncloud-docs.com/docs/apihub-overview , .../apihub-application
- Maps 목록·헤더: https://api.ncloud-docs.com/docs/application-maps-overview , 무료 한도: https://www.ncloud.com/support/faq/prod/2828 (사용자가 붙여 줌)
