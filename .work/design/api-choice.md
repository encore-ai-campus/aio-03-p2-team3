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

### 후보
| 항목 | Google Calendar API | 한국천문연구원_특일 정보 (공공데이터포털) | 기상청_단기예보 조회서비스 (공공데이터포털) |
|---|---|---|---|
| 쓰임 | 일정 읽기·만들기·바꾸기 | 공휴일·국경일·기념일·24절기, 공공기관 휴일 여부 | 초단기실황·초단기예보·단기예보(야외 일정 판단) |
| 무료 한도 | 표준 사용 무료. 기본 한도 프로젝트당 분당 10,000회, 사용자당 분당 600회. 한도 초과분 과금은 2026년 뒤에 도입 예정 | 무료. 개발계정 10,000회(운영계정은 활용사례 등록 시 증가) | 무료. 개발계정 하루 10,000회 |
| 승인 | Google Cloud 프로젝트에서 API 사용 설정 | 개발·운영 모두 자동승인 | 개발·운영 모두 자동승인 |
| 인증 | OAuth 2.0(사용자 캘린더) 또는 서비스 계정. 민감 범위는 앱 검증 필요. Google은 서비스 계정을 데이터 소유자로 쓰지 말라고 권한다(캘린더는 사람 계정이 만들고 공유) | 서비스 키(URL 파라미터) | 서비스 키(URL 파라미터) |
| 형식 | JSON | XML(가이드상 `_type=json` 가능, 미확인) | JSON·XML |
| Python 패키지 | `google-api-python-client`, `google-auth` (3-2-3에서 PyPI로 확인) | 없음, HTTP 요청 | 없음, HTTP 요청 |

- 확인 못 한 것: 카카오 로컬(장소·좌표) API는 공식 문서를 도구로 열지 못해 후보에서 뺐다. OAuth 동의 화면 '테스트' 상태의 테스트 사용자 수 제한은 확인하지 못했다. [Claude proposal]

### 출처
- Calendar 한도·무료: https://developers.google.com/workspace/calendar/api/guides/quota (2026-11-05)
- Calendar 서비스 계정 주의: https://developers.google.com/workspace/calendar/api/concepts/events-calendars (2026-11-05)
- 민감·제한 범위 검증: https://developers.google.com/workspace/calendar/api/guides/auth (2026-11-05)
- 특일 정보: https://data.go.kr/data/15012690/openapi.do (검색 결과 요약, 2026-11-05)
- 단기예보: https://www.data.go.kr/data/15084084/openapi.do (2026-11-05)
