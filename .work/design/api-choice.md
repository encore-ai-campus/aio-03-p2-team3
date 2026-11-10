# LLM·외부 API 선택

세팅 3-2-1(LLM)·3-2-2(외부 API)의 선택과, 요청자가 2026-11-09에 정한 Gmail 견적 MVP의 API 변경을 기록한다(`docs/plans/gmail-quote-mvp.md#3`, R-04·D-03). 환경변수는 `docs/CONTRACT.md` 11절을 기준으로 `.env.example`·README에 반영한다. [Request]
나중에 기능을 더하며 다른 LLM·API를 더하거나 바꾸면 요청자에게 묻고 이 파일을 고친다(`.work/TASK.md` 이 레포의 규칙). [Request]

## LLM
확인일: 2026-11-05

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

### 설정 경로
1. Google AI Studio의 API 키 화면(https://aistudio.google.com/app/apikey)에서 API 키를 만든다. 키는 비밀번호처럼 다루고 레포에 넣지 않는다.
2. 환경변수는 `GEMINI_API_KEY` 하나만 쓴다. Google SDK는 `GEMINI_API_KEY`·`GOOGLE_API_KEY`를 모두 읽고 둘 다 있으면 `GOOGLE_API_KEY`가 앞서므로 하나만 둔다. [Claude proposal]
3. 키는 로컬 `.env`와 Render 환경변수에 둔다. Codex 환경에는 키를 넣지 않고 가짜 응답으로 테스트한다(`.work/TASK.md` 환경 줄).

### 출처
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

- LLM은 Gemini `gemini-3.8-flash`를 그대로 쓴다. Gmail API·Cloud Pub/Sub를 추가하고 Calendar를 유지하는 것은 요청자가 정한 변경이다. [Request]
- 한국천문연구원 특일 정보·기상청 단기예보·네이버 지역 검색·네이버 길찾기는 MVP에서 뺀다. 아래 '일정 도구 추천 후보'에 보관하고, 현재 키 발급·환경변수 설정 대상에서는 제외한다. [Request]
- 체험자는 테스트용 Google 계정과 가상 메일을 쓴다. Gemini 무료 등급에 실제 개인정보를 넣지 않으며, 일정 도구를 연결할 때도 LLM에는 일정 제목 없이 바쁜 시간대만 넘긴다.
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
