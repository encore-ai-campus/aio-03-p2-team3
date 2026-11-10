# CONTRACT — gmail-quote-mvp 공통 계약

`docs/plans/gmail-quote-mvp.md`의 하위 작업 2~22가 모두 따르는 이름과 형식이다. 이 파일은 정의만 담고 코드는 담지 않는다(코드는 2에서 이 파일대로 만든다). [Request]
- 이 파일의 2·3·4절(상태·노드·도구)은 `.work/TASK.md`의 공통 부분이다. 고치기 전에 관련 팀원과 조율하고, 코드와 이 파일을 같은 PR에서 함께 고친다. 코드와 이 파일이 다르면 코드를 기준으로 이 파일을 고치고 PR에 차이를 적는다(`.work/RULES.md` 1절). [Request · Past work: aio3]
- 하위 작업은 자기 일에 필요한 절만 읽는다. 13절에 하위 작업별로 읽을 절을 적었다. [Claude proposal]
- 항목 끝 태그는 출처다: [Request] 팀(요청자)이 정함 · [Claude proposal] Claude가 정함(바꿔도 됨, 바꾸면 이 파일을 고친다).
- 관련 요구사항: R-01·R-02·R-05·R-11·R-14(`docs/REQUIREMENTS.md`).

## 1. 구조와 폴더
- 서버 하나(FastAPI) 안에 화면(Jinja2 템플릿 + HTMX), LangGraph 그래프, 도구, DB를 둔다. 도구는 같은 서버 안의 LangGraph 도구 함수이고, 그 안에서 실제 외부 API(Gemini·Gmail)를 부른다. 별도 서버로 떼지 않는다(왕복 지연이 늘어 속도 요구와 부딪침). [Request]
- 알림 수신 경로는 Pub/Sub 요청을 확인하고 바로 응답한 뒤, 같은 프로세스의 백그라운드 작업(FastAPI `BackgroundTasks`)에서 그래프를 돌린다. 결과는 DB에 저장하고 화면은 저장된 결과만 읽는다. [Request · Claude proposal]
- DB 연결, LLM 클라이언트, Gmail 클라이언트 생성 준비물, 컴파일한 그래프는 서버가 뜰 때 한 번 만들어 재사용한다(속도). [Request]
- 파이썬 패키지 이름은 `app`이다. 테스트는 `tests/`에 둔다. [Claude proposal]

```text
app/
  main.py                  FastAPI 앱 만들기, 라우터 등록, 정적 파일, /healthz
  config.py                환경변수 읽기(Settings), GOOGLE_SCOPES, 한도 값(LIMITS), 기본 필수 항목
  db/
    engine.py              엔진·세션을 한 번 만들어 재사용 (DATABASE_URL, 테스트는 SQLite)
    models.py              7절의 표
  llm/
    client.py              call_structured() — 6절
  prompts/
    <프롬프트 이름>.py      NAME·VERSION·TEMPLATE (6절)
    VERSIONS.md            프롬프트 버전과 변경 이유 표
  clients/
    gmail.py               사용자별 Gmail API 클라이언트 만들기(토큰 갱신 포함), 재시도
  graph/
    state.py               AgentState와 자료 형식 — 2절, 4.3절 (공통 부분)
    build.py               build_graph(): 노드·엣지 연결 — 3절 (공통 부분, 2 뒤로는 고치지 않음)
    routing.py             조건부 엣지 함수 — 3.2절 (공통 부분)
    run.py                 start_run(): 그래프 실행 시작, 실행 기록 묶기
    nodes/
      load_memory.py       기억 불러오기
      analyze_email.py     메일 분석
      draft_replies.py     답장 후보 만들기 노드
      extract_deal.py      거래 항목 추출 노드
      check_required.py    필수 항목 검토 노드
      draft_followup.py    재질문 후보 만들기 노드
      make_quote.py        견적서 만들기 노드
      reflect.py           성찰
      save_pending.py      승인 대기 저장
      finish_failed.py     실패 종료
  tools/
    base.py                ToolResult(공통 결과 형식) — 4.1절 (공통 부분)
    registry.py            도구 등록 목록 — 4.2절 (공통 부분)
    fallback.py            fallback_candidates() — 한도 오류 때 기본 답장 틀
    draft_replies.py       도구 하나 = 파일 하나 (4.4절)
    extract_deal_terms.py
    check_required_fields.py
    draft_followup_replies.py
    create_quote.py
    send_email.py
  quote/
    required_fields.py     get_required_fields() — 5절
    calc.py                견적번호·금액 계산
    pdf.py                 render_quote_pdf()
    fonts/                 한글 글꼴(11에서 라이선스 확인 뒤 넣음)
  services/
    auth.py                Google 로그인, 토큰 암호화 저장
    watch.py               감시 등록·갱신·중지
    gmail_push.py          알림 처리(새 메일 가져오기·거르기·중복 제거·실행 시작)
    approval.py            승인 뒤 보내기 경로(그래프 밖)
    memory.py              기억 저장(발송 뒤 거래 기록, 선호, 요약)
  runlog/
    logger.py              traced_node 감싸기, log_event()
    export.py              실행 하나를 파일로 내보내기
    mask.py                개인정보 가리기 — 8.3절
  web/
    routes/                auth.py · inbox.py · candidates.py · quotes.py · settings.py · runs.py · gmail_push.py
    templates/
      base.html            기본 레이아웃
      components/          화면 조각 — 9절
      pages/               페이지 — 9절
    static/
      css/tokens.css       디자인 토큰(색·글꼴·간격) 한 곳
      css/app.css          토큰만 쓰는 화면 스타일
      js/htmx.min.js       레포에 넣은 htmx(외부 CDN에 기대지 않음)
data/
  quote-rules/             견적서 필수 항목 규칙 파일(21에서 올림, 22의 RAG가 읽음)
tests/
  fakes/                   가짜 LLM·가짜 Gmail·가짜 Google 응답
```

- 위 폴더와 파일 이름은 [Claude proposal], 폴더 경계(서버 하나·도구 함수·DB)는 [Request]. 파일을 더하면 그 하위 작업이 `.work/TASK.md` 파일 지도를 고친다.
- 서버 실행 명령(2에서 README에 더함): `uv run uvicorn app.main:app --reload`(로컬), Render 시작 명령 `uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT`. [Claude proposal]

## 2. 그래프 상태 (`app/graph/state.py`의 `AgentState`)
- `TypedDict`로 둔다. 자료형의 `X | None`은 값이 없을 수 있다는 뜻이다. '쌓기'는 LangGraph 리듀서 `operator.add`로 노드가 돌려준 값을 뒤에 덧붙이는 필드다. 나머지는 노드가 돌려준 값으로 바꾼다. [Claude proposal]
- 시작 입력(7의 `start_run()`이 넣음): `run_id`·`user_id`·`mode`·`message_id`·`thread_id`·`email`·`reflection_enabled`. 나머지는 초기값으로 시작한다. [Claude proposal]

| 이름 | 의미 | 자료형 | 초기값 | 읽는 노드 | 고치는 노드 |
|---|---|---|---|---|---|
| `run_id` | 실행 ID(실행 기록을 묶음) | `str`(uuid4 hex) | 시작 입력 | 모두(실행 기록기) | 없음 |
| `user_id` | 서비스 사용자 | `int` | 시작 입력 | 모두 | 없음 |
| `mode` | 실제 실행 / 시험 실행기 실행 | `Literal["live","test"]` | 시작 입력 | 실행 기록기, `save_pending` | 없음 |
| `message_id` | 처리할 Gmail 메시지 ID | `str` | 시작 입력 | `load_memory`, `save_pending`, `finish_failed` | 없음 |
| `thread_id` | Gmail threadId | `str` | 시작 입력 | 모두 | 없음 |
| `email` | 처리할 메일 | `EmailMessage` | 시작 입력 | `analyze_email`, `extract_deal`, 후보 노드, `reflect` | 없음 |
| `thread_context` | 단기 기억: 스레드 요약·최근 메시지·확인한 조건·직전 결과 | `ThreadContext \| None` | `None` | `analyze_email`, `extract_deal`, 후보 노드, `reflect` | `load_memory` |
| `long_term` | 장기 기억: 선호·회사 정보·단가표·상대방 거래 기록 | `LongTermMemory \| None` | `None` | 후보 노드, `make_quote` | `load_memory` |
| `intent` | 메일 의도 | `Literal["general","deal","ignore"] \| None` | `None` | `routing`, `reflect` | `analyze_email`, `reflect`(경로 바꿀 때) |
| `selected_tool` | 메일 분석이 고른 다음 도구 | `str \| None`(4.2절 등록 이름) | `None` | `routing`, `reflect` | `analyze_email`, `reflect` |
| `tool_reason` | 그 도구를 고른 이유(한 문장) | `str \| None` | `None` | 실행 기록기 | `analyze_email`, `reflect` |
| `tools_called` | 이번 실행에서 부른 도구 기록(쌓기) | `list[ToolCallRecord]` | `[]` | `reflect`, 17의 지표 | 도구를 부르는 노드 모두 |
| `step_status` | 직전 노드 결과(라우팅용) | `Literal["ok","rate_limit","failed"]` | `"ok"` | `routing` | 모든 노드 |
| `deal_terms` | 거래 항목 | `DealTerms \| None` | `None` | `check_required`, `make_quote`, 후보 노드, `reflect` | `extract_deal` |
| `required_fields` | 이번 검토에 쓴 필수 항목 | `RequiredFields \| None` | `None` | `reflect`, 실행 기록기 | `check_required` |
| `missing_fields` | 빠진 필수 항목 키(5절) | `list[str]` | `[]` | `routing`, `draft_followup`, `reflect` | `check_required` |
| `reply_mode` | 지금 만드는 후보 종류 | `Literal["general","followup","quote"] \| None` | `None` | 후보 노드, `save_pending`, `reflect` | `analyze_email`(general), `check_required`(followup), `make_quote`(quote), `reflect` |
| `candidates` | 답장 후보 | `list[ReplyCandidate]` | `[]` | `reflect`, `save_pending` | `draft_replies`, `draft_followup`, 한도 오류 때 그 노드, `reflect`(확인 필요 표시) |
| `quote_draft` | 견적서 초안 | `QuoteDraft \| None` | `None` | `draft_replies`(quote), `reflect`, `save_pending` | `make_quote` |
| `reflection_enabled` | 성찰 켬/끔 | `bool` | 시작 입력(12.3절) | `routing` | 없음 |
| `reflection` | 직전 성찰 결과 | `ReflectionResult \| None` | `None` | `routing`, 재실행할 노드(`feedback`) | `reflect` |
| `reflection_history` | 성찰 결과 기록(쌓기) | `list[ReflectionResult]` | `[]` | 실행 기록기, 17의 지표 | `reflect` |
| `call_retries` | 통신·형식 재시도 횟수 합(쌓기, 6절) | `int` | `0` | 17의 지표 | LLM·Gmail을 부르는 노드 |
| `reflection_retries` | 성찰 재실행 횟수 합 | `int` | `0` | `reflect` | `reflect` |
| `reflection_retries_by_type` | 오류 유형별 성찰 재실행 횟수 | `dict[str,int]` | `{}` | `reflect` | `reflect` |
| `errors` | 오류 기록(쌓기) | `list[AgentError]` | `[]` | `finish_failed`, `save_pending`, 실행 기록기 | 모든 노드 |
| `needs_review` | '확인 필요' 표시(대체 경로로 끝남) | `bool` | `False` | `save_pending`, 화면 | 한도 오류 노드, `reflect` |
| `notice` | 화면 안내 종류 | `Literal["rate_limit","reflection_limit"] \| None` | `None` | `save_pending`, 화면 | 한도 오류 노드, `reflect` |
| `end_reason` | 종료 이유(3.3절) | `Literal["awaiting_approval","followup_question","ignored","failed"] \| None` | `None` | `start_run`, 실행 기록 | `analyze_email`(ignored), `save_pending`, `finish_failed` |

- '후보 노드'는 `draft_replies`·`draft_followup`이다. 위 자료 형식(`EmailMessage` 등)은 4.3절에 정의한다. [Claude proposal]
- 통신 실패 재시도(`call_retries`)와 성찰 재실행(`reflection_retries`)은 따로 센다(R-11, `docs/REQUIREMENTS.md` 2절 추가 조건). [Request]

## 3. 노드와 전이
### 3.1 노드
| 노드 이름 | 뜻 | 하는 일 | 부르는 도구 | 채우는 하위 작업 |
|---|---|---|---|---|
| `load_memory` | 기억 불러오기 | 단기·장기 기억과 긴 스레드 요약을 읽어 `thread_context`·`long_term`을 채운다. 기준을 넘으면 요약을 만든다(3.4절) | 없음(LLM 요약 1회 가능) | 13 |
| `analyze_email` | 메일 분석 | LLM 1회로 `intent`를 정하고 `selected_tool`·`tool_reason`을 남긴다 | 없음 | 8 |
| `draft_replies` | 답장 후보 만들기 | 일반 문의·견적서 동봉 답장 후보 2~3개 | `draft_replies` | 8(general), 11(quote) |
| `extract_deal` | 거래 항목 추출 | 스레드에서 거래 항목을 뽑는다 | `extract_deal_terms` | 10 |
| `check_required` | 필수 항목 검토 | `get_required_fields()` 결과로 빠진 항목을 코드로 찾는다 | `check_required_fields` | 10 |
| `draft_followup` | 재질문 후보 만들기 | 빠진 항목을 모두 묻는 후보 2~3개 | `draft_followup_replies` | 10 |
| `make_quote` | 견적서 만들기 | 견적서 초안을 만들어 DB에 저장한다 | `create_quote` | 11 |
| `reflect` | 성찰 | 오류 감지 → 원인 분석 → 수정 전략 선택. 재실행할 노드를 정한다 | 없음(문제가 있을 때만 LLM) | 12 |
| `save_pending` | 승인 대기 저장 | 후보·견적서·처리 상태를 DB에 저장하고 `end_reason`을 정한다 | 없음 | 2(틀), 8·9 |
| `finish_failed` | 실패 종료 | 오류를 처리 상태에 저장하고 `end_reason="failed"` | 없음 | 2 |

- 승인은 그래프 밖에서 받는다. 화면의 승인 요청이 `app/services/approval.py`의 `send_approved_candidate(user_id, candidate_id)` 또는 `send_approved_quote(user_id, quote_id, candidate_id)`를 부르고, 그 안에서 `send_email` 도구를 부른다. 이 경로도 같은 `run_id`로 실행 기록을 남긴다. [Request · Claude proposal]

### 3.2 전이 (`app/graph/routing.py`)
```text
START → load_memory → analyze_email
analyze_email   --route_after_analyze-->  draft_replies   (intent=general, reply_mode=general)
                                          extract_deal    (intent=deal)
                                          END             (intent=ignore, end_reason=ignored)
                                          save_pending    (step_status=rate_limit, 대체 후보)
                                          finish_failed   (step_status=failed)
extract_deal    --route_after_extract-->  check_required | save_pending(rate_limit) | finish_failed(failed)
check_required  --route_after_check-->    draft_followup  (missing_fields 있음, reply_mode=followup)
                                          make_quote      (missing_fields 없음)
                                          finish_failed   (failed)
make_quote      --route_after_quote-->    draft_replies   (reply_mode=quote) | finish_failed(failed)
draft_replies, draft_followup
                --route_after_draft-->    reflect         (ok, reflection_enabled=True)
                                          save_pending    (ok, reflection_enabled=False 또는 rate_limit)
                                          finish_failed   (failed)
reflect         --route_after_reflect-->  save_pending    (통과, 또는 한도를 넘어 대체 경로)
                                          extract_deal | draft_replies | draft_followup | make_quote
                                                          (reflection.retry_target, 한도 안)
save_pending → END
finish_failed → END
```
- 라우팅 함수는 `step_status`·`intent`·`missing_fields`·`reflection_enabled`·`reflection`만 읽고 상태를 고치지 않는다. 2에서 모두 만들고, 뒤 하위 작업은 `build.py`·`routing.py`를 고치지 않는다. 고쳐야 하면 공통 부분 변경으로 조율한다. [Request · Claude proposal]
- 한도 오류(`rate_limit`)가 난 노드는 `fallback_candidates()`로 기본 답장 틀 후보 1개를 `candidates`에 넣고 `needs_review=True`, `notice="rate_limit"`, `step_status="rate_limit"`을 돌려준다. 이 경로는 성찰을 건너뛴다(성찰도 LLM을 부를 수 있어서). [Request · Claude proposal]

### 3.3 종료 조건 (R-11)
| `end_reason` | 뜻 | 언제 | 처리 상태(7절 `processed_messages.status`) |
|---|---|---|---|
| `awaiting_approval` | 정상 종료 | 일반·견적서 답장 후보를 저장함(한도 오류 대체 후보 포함) | `awaiting_approval` |
| `followup_question` | 추가 질문 종료 | 재질문 후보를 저장함 | `awaiting_approval` |
| `ignored` | 처리 안 함 | 메일 분석이 `ignore`로 판단 | `ignored` |
| `failed` | 실패 종료 | 통신 재시도를 다 쓴 실패, 형식 오류 재시도 실패, 내부 오류 | `error` |

- 성찰 재실행 한도를 넘으면 실패가 아니라 대체 경로로 끝낸다: 마지막 후보에 `needs_review=True`, `notice="reflection_limit"`를 달고 `save_pending`으로 간다. [Request · Claude proposal]

### 3.4 한도 값 (`app/config.py`의 `LIMITS`)
| 이름 | 값 | 뜻 |
|---|---|---|
| `LLM_MAX_RETRIES` | 2 | 통신 실패 때 추가 시도 횟수(처음 포함 최대 3번). 대기 1초 → 2초 |
| `LLM_INVALID_OUTPUT_RETRIES` | 1 | 구조화 출력이 형식에 맞지 않을 때 추가 시도 |
| `LLM_TIMEOUT_SECONDS` | 20 | LLM 호출 1번의 제한 시간 |
| `GMAIL_MAX_RETRIES` | 2 | Gmail API 통신 실패·5xx 때 추가 시도(대기 1초 → 2초) |
| `REFLECTION_MAX_RETRIES_TOTAL` | 3 | 실행 하나에서 성찰 재실행 합계 상한 |
| `REFLECTION_MAX_RETRIES_BY_TYPE` | `hallucination` 2 · `wrong_tool` 1 · `missing_param` 1 · `inconsistent` 2 | 오류 유형별 상한(12.1절) |
| `CANDIDATE_MIN` / `CANDIDATE_MAX` | 2 / 3 | 답장 후보 수(대체 후보는 예외로 1개) |
| `SUMMARY_TRIGGER_MESSAGES` | 8 | 스레드 메시지가 이보다 많으면 요약 |
| `SUMMARY_TRIGGER_CHARS` | 12000 | 또는 스레드 본문 합이 이 글자 수를 넘으면 요약 |
| `SUMMARY_KEEP_RECENT` | 4 | 요약할 때 원문으로 남길 최근 메시지 수 |
| `WATCH_RENEW_AFTER_HOURS` | 24 | 감시 등록 마지막 갱신이 이보다 오래면 다시 등록 |
| `INBOX_POLL_SECONDS` | 90 | 목록 화면이 새로 읽는 간격(1~2분) |
| `QUOTE_VALID_DAYS` | 30 | 견적서 유효기간 |
| `VAT_RATE` | 0.10 | 부가세율 |

- 값은 모두 [Claude proposal]이다(유효기간 30일·부가세 10%·후보 2~3개·요약·하루 갱신은 [Request]). 바꾸면 이 표와 코드를 함께 고친다.
- 요약에는 거래 조건, 확인한 항목, 답이 안 된 질문을 남긴다(13). [Request]

## 4. 도구
### 4.1 공통 결과 형식 (`app/tools/base.py`의 `ToolResult`, pydantic)
| 필드 | 자료형 | 뜻 |
|---|---|---|
| `ok` | `bool` | 성공 여부 |
| `value` | 도구마다 다름(4.4절) \| `None` | 결과 값. 실패면 `None` |
| `error_kind` | `None \| "rate_limit" \| "network" \| "invalid_output" \| "invalid_input" \| "auth" \| "not_found" \| "internal"` | 오류 종류 |
| `error_message` | `str \| None` | 사람이 읽을 오류 설명(비밀값·본문 넣지 않음) |
| `source` | `str` | 출처. 예: `gemini:gemini-3.8-flash`, `gmail`, `db:price_list_items`, `code`, `rag:data/quote-rules/<파일>` |
| `fetched_at` | `str`(ISO 8601, UTC) | 조회·계산 시점(기억에 저장된 외부 데이터를 최신처럼 쓰지 않으려고) |
| `attempts` | `int` | 실제 시도 횟수(재시도 포함) |
| `duration_ms` | `int` | 걸린 시간 |

- 오류 종류: `rate_limit` 한도 초과(재시도 안 함) · `network` 통신 실패·제한 시간 초과·5xx(재시도 다 씀) · `invalid_output` LLM 출력 형식 오류 · `invalid_input` 필수 입력이 빔 · `auth` 토큰 만료·권한 없음 · `not_found` 메일·스레드 없음 · `internal` 그 밖의 코드 오류. [Claude proposal]
- 도구는 예외를 밖으로 던지지 않고 `ToolResult(ok=False, …)`로 돌려준다. 노드는 `ToolResult`를 보고 `step_status`와 `errors`를 정한다. [Claude proposal]

### 4.2 등록 (`app/tools/registry.py`)
- 도구 하나 = `app/tools/<도구 이름>.py` 파일 하나 + `TOOLS` 목록 한 줄이다. 파일은 입력 스키마 `Input`(pydantic)과 `langchain_core.tools.tool(args_schema=Input)`로 감싼 함수 하나를 두고, 함수 이름이 도구 이름이다. [Request · Claude proposal]
- 노드는 도구를 `TOOLS["<이름>"].invoke({...})`로 부른다. 노드가 도구 함수를 직접 import하지 않는다(가짜로 바꿔 끼우기 쉽게). [Claude proposal]
- 나중에 팀원이 더할 도구의 자리: 이미지→견적서(`image_to_quote`), 구글캘린더 등록(`register_calendar_event`), 검토(`review_draft`). 더할 때 노드·전이가 바뀌면 공통 부분 변경으로 조율한다. 이름은 [Claude proposal]이다.

### 4.3 자료 형식 (`app/graph/state.py`)
```python
class EmailMessage(TypedDict):
    gmail_message_id: str
    thread_id: str
    rfc_message_id: str | None   # 답장의 In-Reply-To·References에 씀
    from_addr: str
    from_name: str | None
    to_addrs: list[str]
    subject: str
    body_text: str               # 텍스트 본문(HTML은 텍스트로 바꿈)
    received_at: str             # ISO 8601
    direction: Literal["in", "out"]

class ThreadContext(TypedDict):
    summary: str | None          # 긴 스레드 요약(거래 조건·확인한 항목·답 안 된 질문)
    recent_messages: list[EmailMessage]
    confirmed_terms: dict        # 앞서 확인한 거래 조건(DealTerms 일부)
    last_result: dict | None     # 직전 실행 결과 요약(end_reason, 후보 종류)

class Source(TypedDict):
    kind: str                    # 예: "counterparty_history", "price_list"
    fetched_at: str
    note: str | None

class LongTermMemory(TypedDict):
    preferences: dict            # 예: {"tone": "정중", "signature": "…"}
    company: dict | None         # 공급자 정보: company_name, business_no, ceo_name, contact
    price_list: list[dict]       # {"item_name", "unit", "unit_price"}
    counterparty_history: list[dict]  # {"thread_id", "summary", "deal_terms", "sent_at"}
    sources: list[Source]

class DealItem(TypedDict):
    item_name: str | None
    quantity: int | None
    unit: str | None
    unit_price: int | None       # 스레드에서 합의된 단가만. 없으면 None

class DealTerms(TypedDict):
    customer_name: str | None    # 거래처명
    items: list[DealItem]
    due_date: str | None         # 납기(희망일). 날짜로 읽히면 YYYY-MM-DD, 아니면 원문
    contact_name: str | None
    contact_phone: str | None
    delivery_place: str | None
    note: str | None
    evidence: dict[str, str]     # 필드 → 원문 조각(할루시네이션 검사용)

class RequiredField(TypedDict):
    key: str                     # 5절의 키
    label: str                   # 화면·재질문에 쓰는 한국어 이름

class RequiredFields(TypedDict):
    fields: list[RequiredField]
    source: Literal["config", "rag"]
    evidence: list[dict]         # rag일 때 {"file", "chunk_id", "excerpt"}

class ReplyCandidate(TypedDict):
    label: str                   # 후보 성격 한 줄. 예: "바로 수락"
    subject: str
    body: str
    kind: Literal["general", "followup", "quote"]
    asks_fields: list[str]       # followup이면 묻는 필수 항목 키
    needs_review: bool
    notice: str | None

class QuoteLine(TypedDict):
    item_name: str
    quantity: int
    unit: str | None
    unit_price: int | None
    amount: int | None
    price_source: Literal["thread", "price_list", "user"] | None

class QuoteDraft(TypedDict):
    quote_id: int | None         # DB 저장 뒤 채움
    quote_no: str                # Q-YYYYMMDD-NNN(사용자별 일련번호)
    quote_date: str
    valid_until: str             # quote_date + QUOTE_VALID_DAYS
    supplier: dict               # LongTermMemory.company
    customer_name: str
    lines: list[QuoteLine]
    supply_amount: int | None    # 공급가액(원)
    vat: int | None              # 부가세(1원 미만 버림)
    total: int | None
    missing_prices: list[str]    # 단가가 없는 품목 이름
    status: Literal["needs_price", "ready", "sent"]

class ToolCallRecord(TypedDict):
    tool: str
    ok: bool
    error_kind: str | None
    attempts: int
    duration_ms: int

class ReflectionIssue(TypedDict):
    type: Literal["hallucination", "wrong_tool", "missing_param", "inconsistent"]
    detail: str
    evidence: str

class ReflectionResult(TypedDict):
    passed: bool
    issues: list[ReflectionIssue]
    cause: str | None            # 원인 분석
    strategy: Literal["reprompt", "reroute", "followup", "fallback"] | None
    retry_target: str | None     # 재실행할 노드 이름(3.2절)
    feedback: str | None         # 재실행 노드의 프롬프트에 더할 오류 이유
    verified: bool | None        # 재실행 뒤 같은 기준으로 다시 검사한 결과

class AgentError(TypedDict):
    node: str
    kind: str                    # ToolResult.error_kind와 같은 값
    message: str
    at: str
```
- 금액은 원 단위 정수다. 부가세는 1원 미만을 버린다. 견적번호 형식과 버림 방식은 [Claude proposal]. [Claude proposal]

### 4.4 도구 목록과 입출력
| 도구 이름 | 뜻 | 입력(`Input`) | 성공 때 `value` | 방식 | 프롬프트 |
|---|---|---|---|---|---|
| `draft_replies` | 답장 후보 만들기 | `email`, `thread_context`, `reply_mode`("general"/"quote"), `quote_draft`(quote일 때), `preferences`, `feedback`(성찰 재실행 때) | `{"candidates": list[ReplyCandidate]}` 2~3개 | LLM 1회 | `draft_replies.v1` |
| `extract_deal_terms` | 거래 항목 추출 | `email`, `thread_context`, `feedback` | `DealTerms` | LLM 1회. 원문에 없는 값은 `None` | `extract_deal_terms.v1` |
| `check_required_fields` | 필수 항목 검토 | `deal_terms`, `required_fields`(`RequiredFields`) | `{"missing_fields": list[str]}` | 코드(LLM 없음). 단가는 검사하지 않음 | 없음 |
| `draft_followup_replies` | 재질문 후보 만들기 | `email`, `thread_context`, `deal_terms`, `missing_fields`, `field_labels`, `preferences`, `feedback` | `{"candidates": list[ReplyCandidate]}` 2~3개, 모두 `asks_fields`=빠진 항목 전부 | LLM 1회 | `draft_followup_replies.v1` |
| `create_quote` | 견적서 만들기 | `user_id`, `thread_id`, `deal_terms`, `company`, `price_list` | `QuoteDraft`(DB 저장, `quote_id` 채움) | 코드. 단가: 스레드 합의 → 단가표 → 없으면 `missing_prices` | 없음 |
| `send_email` | 메일 보내기 | `user_id`, `thread_id`, `to_addrs`, `subject`, `body`, `in_reply_to`, `references`, `attachments`(list `{"filename","mime_type","content_b64"}`) | `{"sent_message_id": str}` | Gmail `users.messages.send`(같은 threadId) | 없음 |

- `send_email`은 승인 경로(3.1절)에서만 부른다. 그래프 노드는 부르지 않는다(승인 없이 보내지 않음). [Request]
- 필수 항목 검사 규칙: `customer_name`·`due_date`는 값이 있어야 하고, `items`가 하나 이상이며 품목마다 `item_name`·`quantity`가 있어야 한다. 빠진 키는 5절의 키로 돌려준다. [Request · Claude proposal]
- 견적서 PDF는 `app/quote/pdf.py`의 `render_quote_pdf(quote_draft) -> bytes`가 만든다. 견적서 확인 화면 미리보기와 승인 뒤 첨부에 쓴다. 첨부 파일 이름은 `견적서_<quote_no>.pdf`. [Claude proposal]

## 5. 필수 항목 출처 (`app/quote/required_fields.py`)
- `get_required_fields(user_id: int) -> RequiredFields` 하나로 둔다. 필수 항목 검토 노드는 이 함수만 부르고, 목록을 직접 갖지 않는다. [Request]
- MVP: `app/config.py`의 `DEFAULT_REQUIRED_FIELDS`를 돌려준다(`source="config"`). [Request]

| 키 | 이름 |
|---|---|
| `customer_name` | 거래처명 |
| `item_name` | 품목 |
| `quantity` | 수량 |
| `due_date` | 납기 |

- 22: 함수 본문만 `data/quote-rules/`의 규칙 파일 검색(RAG) 결과로 바꾼다(`source="rag"`, `evidence`에 규칙 조각). 검색이 실패하면 위 목록으로 대체하고 실행 기록에 남긴다. 규칙 파일은 실제 개인정보·비밀값 없이 `data/quote-rules/`에 둔다(21). [Request]
- 새 키가 생기면 `DealTerms`와 `FIELD_LABELS`(같은 파일)에 함께 더한다(공통 부분 변경). [Claude proposal]

## 6. LLM 호출 (`app/llm/client.py`)
- 모델: Google Gemini `gemini-3.8-flash`, 패키지 `langchain-google-genai`, 키 `GEMINI_API_KEY`. 실제 개인정보를 넣지 않는다(무료 등급 입력은 Google 제품 개선에 쓰임). [Request]
- 호출은 모두 `call_structured(prompt: Prompt, schema: type[BaseModel], variables: dict) -> LLMResult` 하나로 한다. 구조화 출력(`with_structured_output(schema)`)만 쓴다. [Request · Claude proposal]
- `LLMResult`: `ok`, `value`(schema 객체), `error_kind`(`rate_limit`/`network`/`invalid_output`/`invalid_input`/`internal`), `attempts`, `prompt_version`, `duration_ms`. 노드는 이것을 `ToolResult`로 옮긴다. [Claude proposal]
- 오류 구분: HTTP 429·`RESOURCE_EXHAUSTED`는 `rate_limit`(재시도 안 함) · 제한 시간 초과·연결 오류·HTTP 500/503(`UNAVAILABLE`)은 `network`(`LLM_MAX_RETRIES`까지 재시도) · 스키마 검증 실패는 `invalid_output`(`LLM_INVALID_OUTPUT_RETRIES`까지) · HTTP 400은 `invalid_input`(재시도 안 함). 정확한 예외 클래스는 2가 패키지 문서로 확인해 코드에 적는다. [Request · Claude proposal]
- 재시도한 횟수(`attempts - 1`)는 노드가 `call_retries`에 더한다. [Claude proposal]
- 프롬프트: `app/prompts/<이름>.py`에 `NAME`, `VERSION`(`v1`, `v2` …), `TEMPLATE`을 둔다. 버전 이름은 `<이름>.<VERSION>`(예: `draft_replies.v1`)이고 호출마다 실행 기록에 남긴다. 고치면 `VERSION`을 올리고 `app/prompts/VERSIONS.md`에 날짜·버전·변경 이유를 한 줄 적는다(12, R-10). [Request · Claude proposal]
- 프롬프트 이름: `analyze_email`, `draft_replies`, `extract_deal_terms`, `draft_followup_replies`, `summarize_thread`, `reflect_fix`. [Claude proposal]
- 테스트는 `app.llm.client.use_backend(fake)`로 `tests/fakes/llm.py`의 `FakeLLM`을 끼운다. 실제 API를 부르지 않는다(Codex 환경에 키 없음). [Request · Claude proposal]

## 7. DB 표 (Render Postgres, `app/db/models.py`)
- `DATABASE_URL`로 연결하고, 테스트는 SQLite(메모리)로 같은 표를 만든다. 시각은 UTC로 저장한다. JSON 열은 Postgres `JSONB`, SQLite `JSON`. 모든 조회는 `user_id`로 거른다(본인 데이터만). [Request · Claude proposal]
- 표가 바뀌면 2 뒤로는 그 하위 작업이 이 절과 코드를 함께 고친다(공통 부분은 아니지만 여럿이 쓰는 표라 조율한다). MVP는 이주 도구 없이 서버 시작 때 없는 표만 만든다. [Claude proposal]

| 표 | 뜻 | 주요 열 | 쓰는 하위 작업 |
|---|---|---|---|
| `users` | 사용자 | `id` PK · `google_sub` 유일 · `email` · `display_name` · `reflection_enabled`(bool, 기본은 환경변수) · `created_at` · `last_login_at` | 6, 11, 12 |
| `google_tokens` | 암호화한 Google 토큰 | `user_id` PK·FK · `refresh_token_enc` · `access_token_enc` · `expires_at` · `scopes` · `updated_at` | 6, 7, 9 |
| `gmail_watches` | 감시 등록 | `user_id` PK·FK · `topic` · `history_id`(마지막 처리 historyId) · `expiration` · `last_renewed_at` · `status`(`active`/`stopped`/`error`) · `last_error` | 6, 7 |
| `processed_messages` | 처리한 메일 | `id` PK · `user_id` · `gmail_message_id` · (`user_id`,`gmail_message_id`) 유일 · `thread_id` · `history_id` · `status`(`processing`/`awaiting_approval`/`sent`/`ignored`/`error`) · `skip_reason` · `notice` · `run_id` · `received_at` · `created_at` | 7, 9 |
| `thread_messages` | 스레드 메시지(단기 기억 원문) | `id` PK · `user_id` · `thread_id` · `gmail_message_id` · `direction` · `from_addr` · `to_addrs` · `subject` · `body_text` · `sent_at` | 7, 13 |
| `thread_memory` | 스레드 단기 기억·요약 | (`user_id`,`thread_id`) PK · `counterparty_email` · `summary` · `summarized_until`(요약에 들어간 마지막 메시지 시각) · `confirmed_terms` JSON · `last_result` JSON · `updated_at` | 13 |
| `reply_candidates` | 답장 후보 | `id` PK · `user_id` · `run_id` · `thread_id` · `source_message_id` · `kind` · `label` · `subject` · `body` · `asks_fields` JSON · `needs_review` · `notice` · `quote_id` FK 없을 수 있음 · `status`(`pending`/`approved`/`sent`/`send_failed`/`superseded`) · `created_at` | 8, 9, 10, 11 |
| `approvals` | 승인 기록 | `id` PK · `user_id` · `candidate_id` 유일(두 번 눌러도 한 번만 보냄) · `approved_at` · `sent_message_id` · `send_status`(`sending`/`sent`/`failed`) · `error` | 9, 11 |
| `deal_terms` | 거래 항목 | `id` PK · `user_id` · `thread_id` · `source_message_id` · `run_id` · `terms` JSON(`DealTerms`) · `missing_fields` JSON · `required_source` · `created_at` | 10 |
| `quotes` | 견적서 | `id` PK · `user_id` · `thread_id` · `run_id` · `deal_terms_id` · `quote_no` (`user_id`,`quote_no`) 유일 · `draft` JSON(`QuoteDraft`) · `status`(`needs_price`/`ready`/`sent`) · `created_at` · `sent_at` | 11 |
| `user_preferences` | 장기 기억: 사용자 선호 | (`user_id`,`key`) PK · `value` JSON · `updated_at` | 13 |
| `company_profiles` | 장기 기억: 회사(공급자) 정보 | `user_id` PK · `company_name` · `business_no` · `ceo_name` · `contact` · `updated_at` | 11 |
| `price_list_items` | 장기 기억: 품목 단가표 | `id` PK · `user_id` · `item_name` · (`user_id`,`item_name`) 유일 · `unit` · `unit_price` · `updated_at` | 11 |
| `counterparty_history` | 장기 기억: 상대방별 거래 기록 | `id` PK · `user_id` · `counterparty_email` · `thread_id` · `summary` · `deal_terms` JSON · `quote_id` · `sent_at` | 13 |
| `runs` | 실행 | `run_id` PK · `user_id` · `mode` · `message_id` · `thread_id` · `reflection_enabled` · `started_at` · `ended_at` · `end_reason` · `duration_ms` · `scenario`(시험 실행기만) | 2, 14, 17 |
| `run_events` | 실행 기록 한 줄 | `id` PK · `run_id` · `seq` · `at` · `event` · `node` · `tool` · `detail` JSON · `duration_ms` | 2, 12, 14, 17 |

- Google 토큰은 `TOKEN_ENCRYPTION_KEY`로 암호화해 저장한다(방식은 6이 정하고 이 절에 적는다). [Request]
  - 방식(6): `cryptography`의 Fernet(AES-128-CBC + HMAC-SHA256). `TOKEN_ENCRYPTION_KEY`는 Fernet 키(만드는 명령은 `.env.example`)이고, 키를 바꾸면 저장된 토큰을 못 읽어 사용자가 다시 로그인해야 한다. 암호화·복호화는 `app/services/auth.py`의 `TokenCipher`, 토큰 꺼내기·갱신은 `get_access_token()`만 쓴다. [Claude proposal]
- `gmail_watches`(6): `status`가 `error`일 때 `last_error`는 `token_expired`(갱신 토큰 만료·취소·읽기 실패: 저장한 토큰을 지우고 다시 로그인을 안내) 또는 `watch_failed: <HTTP 상태 등>`(감시 등록 실패: 다음 갱신 때 다시 시도). `history_id`는 처음 등록하거나 `stopped`에서 다시 등록할 때만 watch 응답 값으로 정하고, 켜져 있는 감시를 갱신할 때는 그대로 둔다(7이 이어 읽음). `stopped`(로그아웃) 사용자의 알림은 처리하지 않는다. [Claude proposal]
- 처리 상태와 화면 표시: `processing` 처리 중 · `awaiting_approval` 승인 대기 · `sent` 보냄 · `error` 오류(`notice=rate_limit`이면 '한도 초과' 표시) · `ignored`는 목록에 보이지 않는다. [Request · Claude proposal]

## 8. 실행 기록
### 8.1 한 줄 형식 (`run_events`, R-12)
- 실행마다 한 줄씩 남기고 `run_id`로 묶는다. `seq`는 실행 안의 순서(0부터). [Request]

| `event` | 언제 | `node` | `tool` | `detail` |
|---|---|---|---|---|
| `run_start` | 실행 시작 | — | — | `mode`, `reflection_enabled`, `message_id`, `thread_id` |
| `node_start` / `node_end` | 노드 앞뒤(실행 기록기가 자동) | 노드 이름 | — | `node_end`: `step_status`, 바뀐 상태 필드 이름 목록 |
| `route` | 조건부 엣지 | 출발 노드 | — | `to`(다음 노드), `reason`(어떤 값으로 골랐나) |
| `tool_select` | 도구를 고름 | 고른 노드 | 고른 도구 | `reason`(`tool_reason`) |
| `tool_call` / `tool_result` | 도구 앞뒤 | 부른 노드 | 도구 이름 | `tool_call`: 입력 요약 · `tool_result`: `ok`, `error_kind`, 값 요약, `source`, `attempts` |
| `llm_call` | LLM 호출 | 부른 노드 | — | `prompt_version`, `ok`, `error_kind`, `attempts` |
| `retry` | 통신·형식 재시도 | 부른 노드 | 있으면 | `error_kind`, `attempt` |
| `reflection` | 성찰 단계 | `reflect` | — | `stage`(`detect`/`analyze`/`strategy`/`verify`), `issues`, `cause`, `strategy`, `retry_target`, `verified` |
| `required_source` | 필수 항목 출처 | `check_required` | — | `source`, `fields`, `evidence`(22) |
| `error` | 오류 | 난 노드 | 있으면 | `kind`, `message` |
| `approval` / `send` | 승인 경로 | — | `send_email` | `candidate_id`, `quote_id`, `ok`, `error_kind` |
| `run_end` | 실행 끝 | — | — | `end_reason`, `call_retries`, `reflection_retries`, 총 `duration_ms` |

- '입력 요약·값 요약'에는 본문 대신 길이와 키 이름만 적는다(예: `{"body_chars": 412, "fields": ["customer_name"]}`). 토큰·키는 어떤 줄에도 넣지 않는다. [Claude proposal]
- 실행 기록기는 `app/runlog/logger.py`의 `traced_node(name)`으로 노드를 감싸 `node_start`/`node_end`·소요 시간·예외를 자동으로 남긴다. 나머지 줄은 `log_event(run_id, event, …)`로 남긴다. [Request · Claude proposal]

### 8.2 내보내기 파일 (`docs/test-records/`)
- 실행 하나 = 파일 하나. 이름: `<YYYYMMDD-HHMM>_<scenario 또는 live>_<refl-on|refl-off>_<run_id 앞 8자>.jsonl`. [Claude proposal]
- 내용: 첫 줄 `{"type": "run", …runs 열}`, 그 뒤 `{"type": "event", …run_events 열}`을 `seq` 순서로. 시험 실행기(17)의 준비된 응답·고의 실패 주입은 `detail.injected: true`로 표시해 실제 API 결과와 구분한다. [Request · Claude proposal]

### 8.3 개인정보 가리기 (`app/runlog/mask.py`, 내보낼 때와 실행 기록 화면에 적용)
| 대상 | 바꾸는 값 |
|---|---|
| 이메일 주소 | `<이메일1>`, `<이메일2>` … (한 파일 안에서 같은 주소는 같은 번호) |
| 보낸 사람 표시 이름·`contact_name` | `<이름1>` … |
| 전화번호 모양 | `<전화>` |
| 사업자등록번호 모양 | `<사업자번호>` |
| 메일 본문·후보 본문(`mode=live`) | `<본문 N자>` |
| 메일 본문·후보 본문(`mode=test`, 지어낸 메일) | 위 규칙만 적용하고 남긴다 |

- 기록에 실제 개인정보가 남지 않게 하는 것이 목적이다(`.work/RULES.md` 3절). [Request · Claude proposal]

## 9. 화면 (R-14)
- 디자인 토큰: `app/web/static/css/tokens.css` 한 파일에 CSS 변수로 둔다(`--color-*`, `--font-*`, `--space-*`, `--radius-*`, `--shadow-*`). 다른 CSS와 템플릿은 색·글꼴·간격 값을 직접 쓰지 않고 토큰만 쓴다(한 곳을 고쳐도 다른 곳이 깨지지 않게). [Request]
- 화면 조각: `app/web/templates/components/`에 `button.html`, `card.html`, `banner.html`(안내 띠: 한도 초과·확인 필요·오류), `status_badge.html`, `candidate_card.html`, `quote_table.html`. Jinja2 매크로로 만든다. [Request · Claude proposal]
- 페이지(`app/web/templates/pages/`)와 경로:

| 페이지 | 템플릿 | 경로 | 하위 작업 |
|---|---|---|---|
| 로그인 | `login.html` | `GET /login`, `GET /auth/google/start`, `GET /auth/google/callback`, `POST /logout` | 6 |
| 받은 메일·후보 목록 | `inbox.html` | `GET /` → `/inbox`, `GET /inbox`, `GET /inbox/list`(HTMX 조각, `INBOX_POLL_SECONDS`마다) | 9 |
| 스레드·후보 고르기 | `thread.html` | `GET /threads/{thread_id}`, `POST /candidates/{candidate_id}/approve` | 9 |
| 견적서 확인 | `quote.html` | `GET /quotes/{quote_id}`, `POST /quotes/{quote_id}/prices`, `GET /quotes/{quote_id}/preview.pdf`, `POST /quotes/{quote_id}/approve`(폼에 `candidate_id`) | 11 |
| 설정 | `settings.html` | `GET /settings`, `POST /settings/company`, `POST /settings/prices`, `POST /settings/reflection` | 11, 12 |
| 실행 기록 | `runs.html`, `run_detail.html` | `GET /runs`, `GET /runs/{run_id}`, `GET /runs/{run_id}/export` | 14 |
| 상태 확인 | 없음 | `GET /healthz` → `{"status": "ok"}` | 2 |
| 알림 수신 | 없음 | `POST /gmail/push` | 7 |

- `kind=quote` 후보는 `/candidates/{id}/approve`로 보내지 않고 견적서 확인 화면의 승인으로만 보낸다(견적서를 확인해야 첨부해 보냄). [Request · Claude proposal]
- 로그인 화면에 '테스트용 Gmail로 등록하세요'를 안내한다. [Request]
- 로그인 확인(6): 세션은 `SESSION_SECRET`으로 서명한 쿠키(`gq_session`, 14일)에 사용자 id만 둔다. 화면 경로는 `app/web/routes/auth.py`의 `require_user`(로그인 안 했으면 `/login`으로 303, HTMX면 `HX-Redirect`) 또는 `current_user`(없으면 None)를 쓰고, 둘 다 응답 뒤 감시 갱신을 건다. id로 행 하나를 열 때는 `app/services/auth.py`의 `get_owned(session, 표, id, user.id)`가 None이면 404로 답한다. 연결 상태 안내는 `connection_status()`. 화면 틀은 `app/web`의 `templates` 하나를 함께 쓴다. [Claude proposal]

## 10. Google
- OAuth 범위는 `app/config.py`의 `GOOGLE_SCOPES` 한 곳에서만 읽는다. 후보: `openid`, `email`, `https://www.googleapis.com/auth/gmail.readonly`, `https://www.googleapis.com/auth/gmail.send`. 이 범위로 감시 등록·기록 조회·메일 읽기·발송이 되는지와 민감·제한 범위 구분은 5에서 공식 문서로 확인하고, 다르면 5의 결과대로 이 줄과 코드를 고친다. [Request]
- 동의 요청은 `access_type=offline`(갱신 토큰), `include_granted_scopes=true`로 한다. 나중에 캘린더 범위(`register_calendar_event` 도구)를 더하면 기존 사용자는 다시 동의해야 한다: 로그인 때 저장된 `scopes`에 `GOOGLE_SCOPES`가 다 없으면 `prompt=consent`로 다시 동의를 받는다. [Request · Claude proposal]
- 알림 수신 경로: `POST /gmail/push`. 요청을 확인한 뒤 본문의 `emailAddress`·`historyId`만 읽고 바로 204로 응답한다. 처리는 백그라운드에서 한다. [Request]
- 푸시 요청 확인 방식(후보, 공식 확인은 5):
  1. 추천: Pub/Sub 푸시 구독의 인증(OIDC 토큰)을 켜고, `Authorization: Bearer` 토큰을 `google-auth`로 검증한다(대상 `PUBSUB_PUSH_AUDIENCE`, 서비스 계정 이메일 `PUBSUB_PUSH_SERVICE_ACCOUNT`). 이유: 주소가 새도 위조 요청을 막고, 이미 있는 `google-auth`로 검증할 수 있다. 검증 공개 키는 캐시해 속도를 지킨다.
  2. 대체: 엔드포인트 주소에 `?token=<PUBSUB_PUSH_TOKEN>`을 붙이고 같은지 비교한다. 이유: 설정이 단순하다. 주소가 새면 막지 못한다. 1이 콘솔 설정에서 막히면 이것을 쓴다.
  - 어느 쪽이든 확인에 실패하면 403으로 응답하고 실행 기록 없이 서버 로그에만 남긴다. [Claude proposal]
- 감시 등록 토픽은 `GMAIL_PUBSUB_TOPIC`(`projects/<프로젝트>/topics/<토픽>`). [Request]
- Google 호출(6): 실제 호출은 `app/clients/gmail.py`의 `GoogleClient` 하나(로그인 주소·코드 교환(PKCE)·토큰 갱신·`gmail(접근 토큰)`·`watch`·`stop`)이고 서버가 뜰 때 `app.state.google`, 준비물 묶음은 `app.state.google_access`(`GoogleAccess`)에 둔다. 테스트는 `tests/fakes/google.py`의 `FakeGoogle`을 `create_app(settings, google=...)`로 넣는다. 감시 등록은 `labelIds: ["INBOX"]`로 받은편지함 변경만 알린다. 7은 알림을 받을 때 `renew_watch_if_due(access, user_id)`, Gmail을 읽을 때 `get_access_token()` → `google.gmail(토큰)`을 쓴다. `TokenExpired`·`GoogleUnavailable`·`WatchFailed`는 모두 `GoogleError`다. [Claude proposal]

## 11. 환경변수 이름 (값은 `.env`와 Render 환경변수에만 둔다)
| 이름 | 뜻 | 쓰는 하위 작업 |
|---|---|---|
| `GEMINI_API_KEY` | Gemini API 키 | 2, 8, 10, 12, 13 |
| `GOOGLE_OAUTH_CLIENT_ID` | OAuth 클라이언트 ID | 6 |
| `GOOGLE_OAUTH_CLIENT_SECRET` | OAuth 클라이언트 비밀번호 | 6 |
| `GOOGLE_OAUTH_REDIRECT_URI` | OAuth 리디렉션 주소(로컬·Render 각각) | 6 |
| `GMAIL_PUBSUB_TOPIC` | 감시 등록 토픽 전체 이름 | 6 |
| `PUBSUB_PUSH_AUDIENCE` | 푸시 OIDC 토큰의 대상(추천 방식) | 7 |
| `PUBSUB_PUSH_SERVICE_ACCOUNT` | 푸시 OIDC 토큰의 서비스 계정 이메일(추천 방식) | 7 |
| `PUBSUB_PUSH_TOKEN` | 대체 방식의 비밀 토큰(대체 방식을 쓸 때만) | 7 |
| `DATABASE_URL` | Postgres 접속 주소(로컬은 비우면 SQLite 파일) | 2, 4 |
| `TOKEN_ENCRYPTION_KEY` | Google 토큰 암호화 키 | 6 |
| `SESSION_SECRET` | 로그인 세션 쿠키 서명 키 | 6 |
| `APP_BASE_URL` | 서비스 주소(링크·리디렉션 확인용) | 6, 7 |
| `REFLECTION_ENABLED_DEFAULT` | 성찰 기본값(`true`/`false`) | 12 |

- `.env.example` 반영은 3이 한다(이 PR은 이름만 정함). 빼는 API의 변수(`DATA_GO_KR_SERVICE_KEY`, `NAVER_HUB_*`, `NCP_MAPS_*`)도 3이 지운다. [Request]
- 이름은 [Claude proposal]. 21에서 임베딩 모델을 정하면 그 키 이름을 이 표에 더한다.

## 12. 하위 작업이 정할 것과 미리 정한 기준
### 12.1 성찰 오류 유형 (12가 채움, R-09·R-10)
| 유형 키 | 뜻 | 감지 예 | 수정 전략 |
|---|---|---|---|
| `hallucination` | 원문·추출 항목에 없는 금액·수량·날짜 | 후보 본문의 숫자가 `deal_terms`·`quote_draft`·원문에 없음 | `reprompt` |
| `wrong_tool` | 도구 선택 오류 | 빠진 필수 항목이 있는데 견적서 경로, 거래 내용이 있는데 일반 답장 경로 | `reroute` 또는 `followup` |
| `missing_param` | 파라미터 누락 | 도구 필수 입력이 빔 | `reprompt`(앞 노드 재실행) |
| `inconsistent` | 응답 불일치 | 후보가 2~3개가 아님, 재질문에 빠진 항목이 다 없음, 받는 사람·스레드 불일치 | `reprompt` |

- 감지는 규칙 검사(LLM 없음)로 하고, 문제가 있을 때만 `reflect_fix` 프롬프트로 원인을 적는다. 재실행 뒤 같은 기준으로 다시 검사해 `verified`를 남긴다. 한도는 3.4절. [Request]
### 12.2 단가 채우기 순서 (11)
- 스레드에서 합의된 단가(`price_source="thread"`) → 단가표(`price_list`) → 없으면 `status="needs_price"`로 두고 견적서 확인 화면에서 입력(`user`). 단가는 상대방에게 묻는 필수 항목이 아니다. [Request]
### 12.3 성찰 켬/끔 (12)
- 우선순위: 시험 실행기 옵션 → 사용자 설정(`users.reflection_enabled`) → `REFLECTION_ENABLED_DEFAULT`. `start_run()`이 정해 `reflection_enabled`로 넣는다. [Request · Claude proposal]
### 12.4 기억 우선순위 (13, R-06~R-08)
- 사용자·스레드로 구분해 읽는다. 현재 메일의 조건이 과거 기억과 충돌하면 현재 메일을 따른다. 과거 외부 데이터는 `Source.fetched_at`을 함께 넘겨 최신처럼 쓰지 않는다. [Request]

## 13. 하위 작업별로 읽을 절과 쓰는 이름
| 하위 작업 | 읽을 절 | 쓰는 이름 |
|---|---|---|
| 2 앱 뼈대 | 1~11 | 모든 파일·상태·노드·도구(빈 틀)·표·`call_structured`·`traced_node`·`LIMITS`·`/healthz` |
| 3 API·문서 정리 | 11 | 환경변수 이름 |
| 5 Google Cloud | 10, 11 | `GOOGLE_SCOPES`, `/gmail/push`, 확인 방식, `GMAIL_PUBSUB_TOPIC` |
| 6 로그인·감시 | 1, 7, 9, 10, 11 | `users`·`google_tokens`·`gmail_watches`, `app/services/auth.py`·`watch.py`, `login.html`, `WATCH_RENEW_AFTER_HOURS` |
| 7 알림 수신 | 1, 2(시작 입력), 4.3(`EmailMessage`), 7, 10 | `processed_messages`·`thread_messages`·`gmail_watches`, `app/services/gmail_push.py`, `start_run()`, `/gmail/push` |
| 8 메일 분석·후보 | 2, 3, 4, 6 | `analyze_email`·`draft_replies` 노드, `draft_replies` 도구, `intent`·`selected_tool`·`candidates`, `fallback_candidates()`, `reply_candidates` |
| 9 승인·발송 | 3.1, 4.4(`send_email`), 7, 9 | `send_approved_candidate()`, `approvals`, `inbox.html`·`thread.html`, `INBOX_POLL_SECONDS` |
| 10 거래 항목·검토·재질문 | 2, 3, 4, 5 | `extract_deal`·`check_required`·`draft_followup` 노드, `extract_deal_terms`·`check_required_fields`·`draft_followup_replies` 도구, `deal_terms`·`missing_fields`, `deal_terms` 표 |
| 11 견적서·설정·첨부 | 4, 7, 9, 12.2 | `make_quote` 노드, `create_quote` 도구, `QuoteDraft`, `render_quote_pdf()`, `quotes`·`company_profiles`·`price_list_items`, `quote.html`·`settings.html`, `send_approved_quote()` |
| 12 성찰 | 2, 3, 6, 8.1, 12.1, 12.3 | `reflect` 노드, `reflection`·`reflection_history`·`reflection_retries*`·`needs_review`, `REFLECTION_*`, `reflect_fix`, `app/prompts/VERSIONS.md` |
| 13 기억 | 2, 3.4, 4.3, 7, 12.4 | `load_memory` 노드, `thread_context`·`long_term`, `thread_memory`·`user_preferences`·`counterparty_history`, `summarize_thread`, `SUMMARY_*`, `app/services/memory.py` |
| 14 실행 기록 화면 | 7(`runs`·`run_events`), 8, 9 | `runs.html`·`run_detail.html`, `/runs/*`, `app/runlog/export.py`·`mask.py` |
| 15·20 설계서 | 전체 | 상태·노드·도구·전이 이름 그대로 |
| 17 시험 실행기 | 2, 7(`runs`), 8, 12.3 | `start_run(mode="test")`, `runs.scenario`, `detail.injected`, `tools_called`, `call_retries`·`reflection_retries` |
| 21·22 규칙 파일 RAG | 5, 8.1 | `data/quote-rules/`, `get_required_fields()`, `RequiredFields`, `required_source` 기록 |

- 4·16·18·19는 이름을 새로 쓰지 않는다(배포 설정, 실제 실행, 보고서). [Claude proposal]

## 14. 2가 더할 패키지 (이름만, 버전은 2가 `pip index versions`로 확인해 고정)
- `fastapi`, `uvicorn`, `jinja2`, `python-multipart`(폼), `itsdangerous`(세션 쿠키), `sqlalchemy`, `psycopg[binary]`(Postgres), `cryptography`(토큰 암호화, 6과 맞춤). 테스트용: `httpx`(이미 있음, `TestClient`). PDF·글꼴 패키지는 11이, RAG 패키지는 21·22가 정한다. [Claude proposal]
- `pyproject.toml`의 `[tool.pytest.ini_options]`에 `pythonpath = ["."]`를 더해 테스트가 `app`을 불러오게 한다(2). [Claude proposal]
