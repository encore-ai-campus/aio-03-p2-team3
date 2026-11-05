# LLM·외부 API 선택 (세팅 3-2단계)

세팅 3-2-1(LLM)·3-2-2(외부 API)에서 사용자가 고른 것과 그 근거다. 3-2-3에서 `.env.example`·`pyproject.toml`·README에 옮긴다. [Request]
나중에 기능을 더하며 다른 LLM·API를 더하거나 바꾸면 요청자에게 묻고 이 파일을 고친다(FLOW.md '3-2단계 정한 것'). [Request]

## LLM
확인일: 2026-11-05 (작성 중)

### 후보
| 항목 | Google Gemini API | Groq |
|---|---|---|
| 무료 한도 | 문서에 숫자 없음. AI Studio에서 내 프로젝트 한도 확인. 프로젝트 단위, 하루 한도는 태평양 시간 자정 초기화 | Free plan: `openai/gpt-oss-120b`·`openai/gpt-oss-20b`·`qwen/qwen3.8-27b` 각 분당 30회·하루 1,000회·분당 8K 토큰·하루 200K 토큰. 조직 단위 |
| 무료 모델 | (확인 중: 가격 페이지) | 위 표의 모델 |
| 무료 등급 데이터 사용 | 입력·응답을 Google 제품·모델 개선에 쓸 수 있고 사람이 검토할 수 있다. 민감·기밀·개인 정보를 넣지 말 것. 만 18세 이상 | 기본적으로 추론 요청 데이터를 보관하지 않는다. 오류·남용 조사용 로그는 최대 30일, Data Controls에서 끌 수 있다. 학습 사용 여부는 문서에 없음 |
| LangChain 패키지 | `langchain-google-genai` (`ChatGoogleGenerativeAI`) | `langchain-groq` (`ChatGroq`) |
| 환경변수 | `GOOGLE_API_KEY` 또는 `GEMINI_API_KEY` | `GROQ_API_KEY` |

### 고른 것
미정

### 출처
- Gemini 한도: https://ai.google.dev/gemini-api/docs/rate-limits (2026-11-05)
- Gemini 무료 등급 데이터 사용: https://ai.google.dev/gemini-api/terms 'Unpaid Services' (2026-11-05)
- Groq 한도: https://console.groq.com/docs/rate-limits Free plan (2026-11-05)
- Groq 데이터: https://console.groq.com/docs/your-data (2026-11-05)
- 패키지·환경변수: PyPI `langchain-google-genai` 4.4.3, `langchain-groq` 1.1.3 소스 (2026-11-05)
