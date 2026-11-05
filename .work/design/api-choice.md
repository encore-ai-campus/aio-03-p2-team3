# LLM·외부 API 선택 (세팅 3-2단계)

세팅 3-2-1(LLM)·3-2-2(외부 API)에서 사용자가 고른 것과 그 근거다. 3-2-3에서 `.env.example`·`pyproject.toml`·README에 옮긴다. [Request]
나중에 기능을 더하며 다른 LLM·API를 더하거나 바꾸면 요청자에게 묻고 이 파일을 고친다(FLOW.md '3-2단계 정한 것'). [Request]

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

### 설정 경로
1. Google AI Studio의 API 키 화면(https://aistudio.google.com/app/apikey)에서 API 키를 만든다. 키는 비밀번호처럼 다루고 레포에 넣지 않는다.
2. 환경변수는 `GEMINI_API_KEY` 하나만 쓴다. Google SDK는 `GEMINI_API_KEY`·`GOOGLE_API_KEY`를 모두 읽고 둘 다 있으면 `GOOGLE_API_KEY`가 앞서므로 하나만 둔다. [Claude proposal]
3. 키는 로컬 `.env`, Render 환경변수, Codex 환경 비밀값에 둔다(TASK.md 환경 줄). 3-2-3에서 `.env.example`·`pyproject.toml`에 옮긴다.

### 출처
- Gemini 한도: https://ai.google.dev/gemini-api/docs/rate-limits (2026-11-05)
- Gemini 무료 모델·데이터 사용: https://ai.google.dev/gemini-api/docs/pricing (도구로 못 열어 사용자가 붙여 줌, 2026-11-05)
- Gemini 무료 등급 데이터 사용: https://ai.google.dev/gemini-api/terms 'Unpaid Services' (2026-11-05)
- Groq 한도: https://console.groq.com/docs/rate-limits Free plan (2026-11-05)
- Groq 데이터: https://console.groq.com/docs/your-data (2026-11-05)
- 키 발급·환경변수 우선순위: 공식 GitHub `googleapis/python-genai` README, `google-gemini/cookbook` `quickstarts/Authentication.ipynb` (2026-11-05)
- 패키지·환경변수: PyPI `langchain-google-genai` 4.4.3, `langchain-groq` 1.1.3 소스 (2026-11-05)

## 외부 API
확인일: 2026-11-05

### 후보 (공식 문서 확인)
| 항목 | Google Calendar | 특일 정보(천문연) | 단기예보(기상청) | 네이버 지역 검색(API HUB) | 네이버 Maps(네이버 클라우드) |
|---|---|---|---|---|---|
| 쓰임 | 일정 읽기·만들기 | 공휴일·절기 | 초단기·단기 예보 | 장소→주소·좌표(WGS84), 1회 1~5개 | 길찾기 Directions 5·15, 주소↔좌표, 지도 이미지 |
| 무료 한도 | 프로젝트 분당 10,000회, 사용자 분당 600회 | 개발계정 10,000회 | 개발계정 하루 10,000회 | 하루 25,000회. 한시적 무료, 유료 전환 전 공지 | API마다 3,000~1억 건. 대표 계정 하나만 |
| 인증 | OAuth 2.0(민감 범위) | 공공데이터포털 키, 자동승인 | 같음 | 헤더 `X-NCP-APIGW-API-KEY-ID`·`X-NCP-APIGW-API-KEY` | 헤더 `x-ncp-apigw-api-key-id` 등 |
| 형식 | JSON, `google-api-python-client`·`google-auth` | XML | JSON·XML | JSON | JSON |
- 네이버 개발자센터 검색 API는 NAVER API HUB로 옮겨 갔으므로 HUB로 쓴다. [Claude proposal]
- Google OAuth 게시 상태: 테스트는 등록한 테스트 사용자 100명만, 승인 7일 뒤 만료. 프로덕션(검증 전)은 누구나 로그인하지만 '확인되지 않은 앱' 경고가 뜨고, 경고를 본 새 사용자는 프로젝트 전체 기간 100명까지.

### 고른 것 (2026-11-05)
- 캘린더는 B(사용자별 OAuth 로그인). 체험자는 자기 Google 계정으로 자기 캘린더를 쓴다. [Request]
- OAuth는 프로덕션으로 게시하고 검증은 받지 않는다. 체험자는 경고 화면에서 '고급 → 이동'을 누른다. 100명을 넘으면 테스트 상태 등록 방식으로 바꾼다. [Request: 추천안]
- 체험 화면에 '테스트용 Google 계정으로 로그인하세요'를 안내하고, LLM에는 일정 제목 없이 바쁜 시간대만 넘긴다(Gemini 무료 등급 입력은 Google 개선에 쓰임). 구체 방법은 11/13 설계에서 정한다. [Request: 추천안]
- 보조 API: 특일 정보, 단기예보, 네이버 지역 검색 + Directions 5. 지역 검색 결과에 좌표가 있어 Geocoding은 쓰지 않는다. 카카오 로컬은 쓰지 않는다. [Request]
- Directions 5의 정확한 무료 건수는 미확인. 키를 만든 사람이 콘솔에서 보고 이 줄을 고치고, '이용 한도 설정'을 무료량 이하로 둔다. [Claude proposal]

### 설정 경로
1. Google Cloud 콘솔: 프로젝트 → Google Calendar API 사용 설정 → Google Auth Platform에서 Branding·Audience(외부, 앱 게시)·Data Access(캘린더 범위) → Clients에서 웹 애플리케이션 클라이언트를 만들고 Render 주소의 리디렉션 URI를 넣는다. 비밀번호는 만들 때만 보인다. 환경변수 `GOOGLE_OAUTH_CLIENT_ID`·`GOOGLE_OAUTH_CLIENT_SECRET`.
2. 공공데이터포털: 두 API 페이지에서 '활용신청'(자동승인) → 마이페이지에서 인증키 확인. 환경변수 `DATA_GO_KR_SERVICE_KEY`(메뉴 이름은 화면에서 확인).
3. 네이버 클라우드 콘솔(대표 계정): All Services → Application Services → NAVER API HUB → Application 등록 → 인증 정보. 환경변수 `NAVER_HUB_CLIENT_ID`·`NAVER_HUB_CLIENT_SECRET`.
4. 같은 콘솔의 Maps → Application 등록(Directions 5 선택) → 인증 정보 → '이용 한도 설정'. 환경변수 `NCP_MAPS_CLIENT_ID`·`NCP_MAPS_CLIENT_SECRET`.
- 환경변수 이름은 [Claude proposal]. 3-2-3에서 `.env.example`에 옮긴다.

### 출처
- Calendar 한도·범위: https://developers.google.com/workspace/calendar/api/guides/quota , .../guides/auth
- OAuth 게시 상태: https://support.google.com/cloud/answer/15549945
- 특일 정보·단기예보: https://data.go.kr/data/15012690/openapi.do , https://www.data.go.kr/data/15084084/openapi.do
- 지역 검색: https://api.ncloud-docs.com/docs/naver-api-hub-search-local
- API HUB 무료·이관·콘솔 경로: https://guide.ncloud-docs.com/docs/apihub-overview , .../apihub-application
- Maps 목록·헤더: https://api.ncloud-docs.com/docs/application-maps-overview , 무료 한도: https://www.ncloud.com/support/faq/prod/2828 (사용자가 붙여 줌)
