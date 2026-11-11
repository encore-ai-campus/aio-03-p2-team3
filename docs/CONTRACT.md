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
    format.py              메일·스레드·선호를 프롬프트 변수 텍스트로 바꾸기(8에서 더함, 10도 씀)
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
      common.py            업무 노드 공통: failure_update()(한도 오류 → 대체 후보, 그 밖 → 실패, 8에서 더함), call_tool()(tool_call·tool_result 기록, ToolResult → 상태)·retry_feedback()(10에서 더함)
  tools/
    base.py                ToolResult(공통 결과 형식) — 4.1절 (공통 부분)
    registry.py            도구 등록 목록 — 4.2절 (공통 부분)
    fallback.py            fallback_candidates(email, kind=, asks_fields=, preferences=) — 한도 오류 때 기본 답장 틀(도구 아님, 등록하지 않음)
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
    logger.py              traced_node 감싸기, log_event(), current_database()(실행 중인 DB)
    export.py              실행 하나를 파일로 내보내기
    mask.py                개인정보 가리기 — 8.3절
  web/
    routes/                auth.py · inbox.py · candidates.py · quotes.py · settings.py · runs.py · gmail_push.py
    deps.py                current_user_id(로그인한 사용자 id) — 9절
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
| `deal_terms` | 거래 항목 | `DealTerms \| TradeDocTerms \| None`(판별 `doc_kind`, 없으면 "quote" — 15.2절) | `None` | `check_required`, `make_quote`, 후보 노드, `reflect` | `extract_deal` |
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
- 한도 오류(`rate_limit`)가 난 노드는 `fallback_candidates(email, *, kind, asks_fields, preferences) -> list[ReplyCandidate]`(`app/tools/fallback.py`, LLM 없이 고정 문구. 재질문 노드는 `kind="followup"`, `asks_fields`=빠진 항목)로 기본 답장 틀 후보 1개를 `candidates`에 넣고 `needs_review=True`, `notice="rate_limit"`, `step_status="rate_limit"`을 돌려준다. 이 경로는 성찰을 건너뛴다(성찰도 LLM을 부를 수 있어서). [Request · Claude proposal]

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
| `source` | `str` | 출처. 예: `gemini:gemini-3.6-flash`(`model_source()`), `gmail`, `db:price_list_items`, `code`, `rag:data/quote-rules/<파일>` |
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
    doc_kind: NotRequired[Literal["quote"]]  # 문서 종류 판별 키. 없으면 "quote"(15.2절)
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
| `draft_replies` | 답장 후보 만들기 | `email`, `thread_context`, `reply_mode`("general"/"quote"), `quote_draft`(quote일 때), `preferences`, `feedback`(성찰 재실행 때) | `{"candidates": list[ReplyCandidate]}` 2~3개 | LLM 1회 | `draft_replies.v2` |
| `extract_deal_terms` | 거래 항목 추출 | `email`, `thread_context`, `feedback`, `user_id`, `counterparties`(무역 경로 거래처 프로필), `company`(발행 회사 설정 — 15.6절) | `DealTerms \| TradeDocTerms`(15.2절, 도구가 `doc_kind`로 판별) | LLM 1회. 원문에 없는 값은 `None`. 무역 경로 프롬프트는 `extract_trade_terms.v1` | `extract_deal_terms.v1` / `extract_trade_terms.v1` |
| `check_required_fields` | 필수 항목 검토 | `deal_terms`, `required_fields`(`RequiredFields`) | `{"missing_fields": list[str]}` | 코드(LLM 없음). 단가는 검사하지 않음. 무역 형식 대응은 15.3절 | 없음 |
| `draft_followup_replies` | 재질문 후보 만들기 | `email`, `thread_context`, `deal_terms`, `missing_fields`, `field_labels`, `preferences`, `feedback` | `{"candidates": list[ReplyCandidate]}` 2~3개, 모두 `asks_fields`=빠진 항목 전부 | LLM 1회 | `draft_followup_replies.v1` |
| `create_quote` | 견적서 만들기 | `user_id`, `thread_id`, `deal_terms`, `company`, `price_list` | `QuoteDraft`(DB 저장, `quote_id` 채움) | 코드. 단가: 스레드 합의 → 단가표 → 없으면 `missing_prices` | 없음 |
| `send_email` | 메일 보내기 | `user_id`, `thread_id`, `to_addrs`, `subject`, `body`, `in_reply_to`, `references`, `attachments`(list `{"filename","mime_type","content_b64"}`) | `{"sent_message_id": str}` | Gmail `users.messages.send`(같은 threadId) | 없음 |

- `send_email`은 승인 경로(3.1절)에서만 부른다. 그래프 노드는 부르지 않는다(승인 없이 보내지 않음). [Request]
- 필수 항목 검사 규칙: `customer_name`·`due_date`는 값이 있어야 하고, `items`가 하나 이상이며 품목마다 `item_name`·`quantity`가 있어야 한다. 빠진 키는 5절의 키로 돌려준다. [Request · Claude proposal]
- 견적서 PDF는 `app/quote/pdf.py`의 `render_quote_pdf(quote_draft) -> bytes`가 만든다. 견적서 확인 화면 미리보기와 승인 뒤 첨부에 쓴다. 첨부 파일 이름은 `견적서_<quote_no>.pdf`. [Claude proposal]
  - 11 구현: `fpdf2==2.9.0`·저장소의 NanumGothic TTF(SIL OFL 1.1, `app/quote/fonts/OFL.txt`)로 한글 글꼴을 부분 포함하고 메모리에서 만든다. 단가 미입력 PDF에는 미완성 표시와 미정 금액을 보여 준다. `draft_replies.v2`는 이후 단가 입력으로 숫자가 바뀔 수 있어 본문에 금액·날짜를 복사하지 않고 첨부 견적서를 안내한다.

## 5. 필수 항목 출처 (`app/quote/required_fields.py`)
- `get_required_fields(user_id: int, doc_kind: str = "quote") -> RequiredFields` 하나로 둔다(15.3절 확장). 필수 항목 검토 노드는 이 함수만 부르고, 목록을 직접 갖지 않는다. [Request]
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
- 모델: Google Gemini `gemini-3.6-flash`(`app/llm/client.py`의 `DEFAULT_MODEL`, 환경변수 `GEMINI_MODEL`로 덮어씀. 2026-11-10 #62에서 무료 등급 `gemini-3.8-flash`의 503 반복으로 바꿈), 패키지 `langchain-google-genai`, 키 `GEMINI_API_KEY`. 실제 개인정보를 넣지 않는다(무료 등급 입력은 Google 제품 개선에 쓰임). [Request]
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

- 견적서(11): `create_quote`는 사용자 행을 잠그고 같은 날짜의 사용자별 일련번호로 저장한다(유일 제약 충돌은 최대 3회 시도). `make_quote`가 현재 실행의 `run_id`·`deal_terms_id`를 연결한다. 회사 정보·단가표는 새 견적서 생성 때 복사하며 설정 변경으로 기존 견적서를 바꾸지 않는다. `send_approved_quote()`는 일반 승인과 같은 사용자 잠금·후보의 조건부 UPDATE·승인 기록·결과 키를 쓰고, 성공 때 `quotes.status`·`draft.status`를 `sent`, `sent_at`을 UTC로 저장한다. Gmail 발송 자동 재시도는 없고 실패 후 같은 후보를 명시적으로 재승인할 수 있다.

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
- 내용: 첫 줄 `{"type": "run", …runs 열}`, 그 뒤 `{"type": "event", …run_events 열(DB 줄 번호 `id`는 뺀다)}`을 `seq` 순서로. 시험 실행기(17)의 준비된 응답·고의 실패 주입은 `detail.injected: true`로 표시해 실제 API 결과와 구분한다. [Request · Claude proposal]

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
- 이름 열·키(`from_name`·`display_name`·`contact_name`)에서 모은 이름은 오류 문구·시험 본문 같은 다른 글에 섞여 있어도 같은 `<이름N>`으로 바꾼다. 실행 id·메시지 id·시각처럼 기록을 따라가는 값은 가리지 않는다. [Claude proposal]

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
| 공개 페이지(로그인 없이) | `about.html`, `privacy.html`, `terms.html` | `GET /about`(앱 소개, Google 브랜딩 홈페이지), `GET /privacy`(개인정보처리방침), `GET /terms`(서비스 약관). 모든 페이지 아래쪽에 세 링크, 로그인 화면 본문 아래에도 세 링크 | #82 |
| 상태 확인 | 없음 | `GET /healthz` → `{"status": "ok"}` | 2 |
| 알림 수신 | 없음 | `POST /gmail/push` | 7 |

- `kind=quote` 후보는 `/candidates/{id}/approve`로 보내지 않고 견적서 확인 화면의 승인으로만 보낸다(견적서를 확인해야 첨부해 보냄). [Request · Claude proposal]
  - 11 구현: 스레드의 견적 후보에서 확인 화면으로 연결한다. `needs_price`는 빠진 단가 입력 폼만 열며 승인 요청도 거부한다. `/prices`는 `price_<행 번호>`로 빠진 단가 전부를 받고 기존 단가는 바꾸지 않는다. 미리보기·승인 첨부는 같은 PDF 함수를 사용한다. 승인 결과는 일반 후보와 같은 `ApprovalResult.outcome` 안내 키(`needs_price` 추가)로 303 이동해 표시한다.
  - 설정(11): `/settings/company`는 `company_name`·`business_no`·`ceo_name`·`contact`, `/settings/prices`는 `item_name`·`unit`·`unit_price`를 받고 본인 행만 저장한다. 같은 품목명 저장은 단가·단위 갱신이다. 성찰 설정은 12가 구현한다.
- 로그인 화면에 '테스트용 Gmail로 등록하세요'를 안내한다. [Request]
- 본인 확인: 로그인(6)이 세션(`SESSION_SECRET`으로 서명한 쿠키 `gq_session`, 14일)에 `user_id`만 넣는다. 로그인이 필요한 경로는 둘 중 하나를 `Depends`로 받고, 로그인 안 했으면 둘 다 `/login`으로 보낸다(303). ① `app/web/deps.py`의 `current_user_id`: id만 필요할 때(14가 씀). ② `app/web/routes/auth.py`의 `require_user`(없으면 `/login`, HTMX면 `HX-Redirect`)·`current_user`(없으면 None): `User` 행이 필요하거나 화면 요청 때 감시 갱신까지 걸 때(응답 뒤, 받은 메일 화면이 씀). id로 행 하나를 열 때는 `app/services/auth.py`의 `get_owned(session, 표, id, user_id)`가 None이면 404로 답한다. 연결 상태 안내는 `connection_status()`. 라우터는 `request.app.state.templates`(`app.web`의 `templates`와 같은 객체)·`request.app.state.database`를 쓴다. [Claude proposal]

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
| `GEMINI_MODEL` | 쓸 Gemini 모델 이름(비우면 `gemini-3.6-flash`) | 16 |
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
  - 12 구현(`app/graph/nodes/reflect.py`): 감지 규칙 — `hallucination`: 후보 본문의 금액(`원`·`만원`·`₩` 등)·수량(숫자+`개`·`박스`·`EA` 등 단위)·날짜(`YYYY-MM-DD`·`M월 D일`·`M/D`)가 원문·스레드 기억·`deal_terms`·`quote_draft`·단가표·회사 정보·선호에 없음(상대방 과거 거래 기록은 근거로 보지 않음, 단위 없는 숫자는 보지 않음). `wrong_tool`: 견적서 경로인데 `missing_fields`가 있음 → `followup`(`draft_followup`, `reply_mode="followup"`), 견적서 경로인데 거래 항목을 다시 검사하면 빠진 항목이 있음 → `reroute`(`extract_deal`), 일반 답장인데 메일에 거래 표현(견적·발주·주문·구매·납품·단가)과 수량이 함께 있음 → `reroute`(`extract_deal`, `intent="deal"`). `missing_param`: 견적서·재질문 경로인데 `deal_terms`(견적서는 품목 포함)가 빔 → `extract_deal`, 견적서 경로인데 `quote_draft`가 빔 → `make_quote`. `inconsistent`: 후보 수가 2~3개가 아님, 후보 종류·제목(`Re: 원래 제목`)이 맞지 않음, 본문에 원문·기억에 없는 메일 주소, 재질문 후보의 `asks_fields`나 본문에 빠진 항목 이름이 없음 → 후보 노드 재실행. 실행 스레드와 메일 스레드가 다르면 고칠 길이 없어 바로 대체 경로. [Claude proposal]
  - 여러 유형이 함께 나오면 `wrong_tool` → `missing_param` → `inconsistent` → `hallucination` 순으로 앞 유형을 먼저 고친다. 전체 한도나 그 유형 한도를 이미 다 썼으면 LLM을 부르지 않고 대체 경로로 끝낸다(마지막 후보 최대 3개에 `needs_review`·`reflection_limit`, 후보가 없으면 기본 답장 틀). `reflect_fix`가 실패하면(한도·통신 등) 규칙 검사 결과로 원인·수정 지시를 대신 쓰고 재실행한다. 재실행 노드에 넘기는 `feedback`은 LLM 지시와 규칙 검사로 찾은 문제를 함께 담는다. 성찰 노드 자체 오류는 `errors`에 `internal`로 남기고 대체 경로로 끝낸다. [Claude proposal]
  - 실행 기록(8.1절 `reflection`): `detect`(`issues`: 유형·설명·근거, `rechecking`) → 재실행 뒤면 `verify`(`verified`, `after_strategy`, `retried`) → 문제가 있으면 `analyze`(`cause`, `llm`·`llm_ok`·`error_kind`) → `strategy`(`strategy`, `retry_target`, `issue_type`, 누적 횟수, 대체 경로면 `reason`=`limit`/`no_fix`). 경로를 바꾸면 `tool_select`(`by: reflection`)도 남긴다. 본문은 남기지 않고, 근거에는 찾은 값 조각만 적는다. [Claude proposal]
### 12.2 단가 채우기 순서 (11)
- 스레드에서 합의된 단가(`price_source="thread"`) → 단가표(`price_list`) → 없으면 `status="needs_price"`로 두고 견적서 확인 화면에서 입력(`user`). 단가는 상대방에게 묻는 필수 항목이 아니다. [Request]
  - 11 구현: 단가표는 품목명과 단위가 모두 같은 행을 적용한다(단위가 다르면 사용자 입력). 0원도 합의·입력 단가로 인정한다. 단가는 0 이상의 원 단위 정수, 수량은 양의 정수다. 한 줄이라도 단가가 없으면 공급가액·부가세·합계는 모두 `None`, 다 채우면 `sum(수량×단가)`·`공급가액 // 10`·두 금액의 합으로 계산한다.
### 12.3 성찰 켬/끔 (12)
- 우선순위: 시험 실행기 옵션 → 사용자 설정(`users.reflection_enabled`) → `REFLECTION_ENABLED_DEFAULT`. `start_run()`이 정해 `reflection_enabled`로 넣는다. [Request · Claude proposal]
  - 12 구현: 환경변수는 새 사용자 행의 `reflection_enabled` 기본값이 되고, 설정 화면 `/settings`의 '자가 성찰' 체크박스(`POST /settings/reflection`, 폼 `enabled=on`)가 본인 행을 바꿔 다음 실행부터 적용된다. 시험 실행기(17)는 `start_run(reflection_enabled=True/False)`로 같은 입력을 성찰 켬·끔으로 돌린다. [Claude proposal]
### 12.4 기억 우선순위 (13, R-06~R-08)
- 사용자·스레드로 구분해 읽는다. 현재 메일의 조건이 과거 기억과 충돌하면 현재 메일을 따른다. 과거 외부 데이터는 `Source.fetched_at`을 함께 넘겨 최신처럼 쓰지 않는다. [Request]
- 구현(13): `load_memory`는 `thread_memory`의 요약·확인한 조건·직전 결과와 `thread_messages`의 아직 요약하지 않은 원문을 읽는다. 현재 메일은 별도로 전달하고, 같은 메시지 ID와 현재 메일보다 미래의 메시지는 문맥에서 뺀다. `save_pending`은 후보와 같은 트랜잭션에 현재 수신 원문(이미 있으면 생략), 확인한 거래 조건, `last_result`(`end_reason`·`reply_mode`·`missing_fields`)를 저장한다. [Claude proposal]
- 모델 입력: 분석·거래 추출·일반/재질문 후보 노드는 `context_for_model()`로 현재 메일 우선 지시와 같은 상대방의 최근 거래 기록 최대 5건을 기존 `ThreadContext` 입력에 붙인다(상태 자체의 `thread_context`는 바꾸지 않음). 다른 스레드의 기록은 과거 참고로 표시하며 이번 수량·납기·합의 단가로 복사하지 않는다. 선호·회사·단가표·상대방 기록은 모두 본인 자료만 `long_term`으로 읽고, `sources`에는 자료별 저장/발송 시점과 출처를 남긴다. [Claude proposal]
- 요약: 현재 메일을 포함한 아직 요약하지 않은 메시지가 8개 또는 본문 합계 12000자를 **넘을 때**, 최근 원문 4개를 제외한 오래된 원문과 기존 요약으로 `summarize_thread.v1`을 부른다. 거래 조건·확인 항목·미답변 질문을 구조화 출력으로 받고 전체 4000자 이하만 저장한다. 확인한 조건과 직전 미답변 항목은 모델 입력에 따로도 남긴다. 원문은 삭제하지 않으며 성공한 요약만 `summarized_until`을 옮긴다. 같은 시각의 메시지가 경계에 걸리면 누락을 막기 위해 그 시각의 메시지 전부를 원문 쪽에 남긴다(이때 4개보다 많을 수 있음). [Claude proposal]
- 요약 오류: 기존 `call_structured()`의 재시도를 따르고 `call_retries`에 센다. 한도 오류는 기본 후보·확인 필요 표시로 승인 대기하며, 그 밖의 오류는 실패 종료한다. `analyze_email`은 앞 노드의 실패 상태를 유지해 업무 LLM을 더 부르지 않는다. 실패한 요약은 기존 요약·커서를 바꾸지 않고 미답변 항목도 유지한다. [Claude proposal]
- 발송 뒤 저장: 승인 서비스의 `_finish()`가 성공 상태(`reply_candidates.status="sent"`, `approvals.send_status="sent"`, `sent_message_id` 있음)를 반영한 같은 DB 세션에서 `save_sent_memory(session, user_id=..., candidate_id=..., sent_at=..., to_addrs=...)`를 부른다. 훅은 본인 소유와 성공 상태를 다시 검사해 발송 원문(Reply-To를 반영한 실제 수신자 포함)·승인한 문체 예시(`user_preferences.approved_reply_style`, 기존 `tone`·`signature`는 유지)·스레드별 최신 상대방 거래 기록을 저장한다. 같은 발송을 다시 저장해도 원문·거래 기록을 중복하지 않고, 승인 전·발송 실패는 장기 기억에 쓰지 않는다. 문체 예시의 사실·약속을 다음 거래로 옮기지 않도록 모델에 명시한다. 기억 저장만 실패하면 세이브포인트를 되돌리고 예외 종류만 서버 로그에 남기며, 이미 보낸 메일의 성공 상태는 유지한다(자동 재발송·기억 저장 재시도는 하지 않음). [Claude proposal]

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
| kekorea-port 1~6 | 15 (2~5는 4.3·5·7절도) | 15절 전부: `DocKind`·`TradeDocTerms`·`TradeDocDraft`·`PackingTotals`·무역 필수 키·`app/trade/*` 대응표·`create_trade_document`·`extract_trade_terms.v1`·`send_approved_trade_document`·15.7절 표 |

- 4·16·18·19는 이름을 새로 쓰지 않는다(배포 설정, 실제 실행, 보고서). [Claude proposal]

## 14. 2가 더할 패키지 (이름만, 버전은 2가 `pip index versions`로 확인해 고정)
- `fastapi`, `uvicorn`, `jinja2`, `python-multipart`(폼), `itsdangerous`(세션 쿠키), `sqlalchemy`, `psycopg[binary]`(Postgres), `cryptography`(토큰 암호화, 6과 맞춤). 테스트용: `httpx`(이미 있음, `TestClient`). PDF·글꼴 패키지는 11이, RAG 패키지는 21·22가 정한다. [Claude proposal]
- `pyproject.toml`의 `[tool.pytest.ini_options]`에 `pythonpath = ["."]`를 더해 테스트가 `app`을 불러오게 한다(2). [Claude proposal]

## 15. 무역서류 (kekorea-port)
- 2026-11-11 후속 구현: `docs/plans/trade-domain-api.md`의 1~4절을 요청받았다. 15.9절은 기존 이식본의 DB/수정/발송 규칙을 보완한다. React용 독립 API와 문서별 모듈은 해당 계획의 후속 단계다.
- 이 절은 `docs/plans/kekorea-port.md` 하위 작업 2~6이 따르는 이름과 형식이다. 근거는 원본 사본 `reference/kekorea/`(README·SPEC.md·PRESERVED_BEHAVIOR.md·KNOWN_ERRORS.md)이고, 이식한 코드는 옮긴 함수 위에 원본 경로를 주석으로 남긴다. 관련 요구사항: R-02·R-03·R-04·R-11. [Request]
- 팀 협의(계획 '팀 협의 항목' 표 0~14번) 결과가 아직 없다(2026-11-10). 이 절의 협의 관련 값은 표의 '추천'값을 임시로 적용했고 `[임시]`로 표시했다. 협의 결과가 나오면 이 절과 코드를 함께 고친다. [Request · Claude proposal]
- 범위는 백엔드다. 상태·도구·서비스 함수·DB 표 형식만 정의하고 화면(템플릿·경로)은 정의하지 않는다. RAG 근거 표시(21·22)도 이번 범위 밖이라 `get_required_fields()`는 `source="config"`를 유지한다. PDF·이미지 첨부 읽기(`attachments.py`)·계약서 이식도 범위 밖이다(15.8절). [Request]
- 이 절과 원본 `PRESERVED_BEHAVIOR.md`가 어긋나면 이 절을 고쳐 맞추고 차이를 PR에 적는다. 옮기지 않기로 한 `KNOWN_ERRORS.md`의 오류는 6이 점검표로 남긴다. [Claude proposal]

### 15.1 문서 종류 키와 정하는 곳
- 문서 종류 키는 `Literal["quote", "PI", "PO", "CI", "PL"]`이다. `quote`는 기존 국내 견적서(2절 그대로), `PI`·`PO`·`CI`·`PL`은 무역서류(원본 표기 그대로 대문자)다. 국내 견적서를 유지하고 무역서류 4종을 더한다[임시: 협의 0-a]. [Request · Claude proposal]
- 문서 종류는 `extract_deal_terms` 도구가 정한다(메일 분석·라우팅은 고치지 않는다).
  1. 코드로 `recognize_doc_kind(text) -> str | None`(15.4절 `app/trade/postprocess.py`, 원본 `_requested_document_type` 규칙 **그대로만**: 문서 별칠과 작성 동사의 근접성으로 명시적 생성 요청만 인정). `is_ci_conversion_request`는 문서 종류 인식에 쓰지 않는다 — 그 함수는 `app/trade/ci_import.py`(15.4절) 안에 CI 변환 구분용으로만 남고, 2절(A)가 5절(D) 모듈을 import하지 않게 하기 위해서다. 'PI를 CI로 작성' 같은 표현도 `CI`/`PI` 별칭+동사 규칙으로 판별한다. 입력 텍스트는 메일 제목+본문이다.
  2. `PI`·`PO`·`CI`·`PL`로 인식되면 무역 추출 경로(15.2절)로 `TradeDocTerms`를 만들고 `doc_kind`를 확정한다. 인식되지 않으면 기존 `DealTerms` 경로이고 `doc_kind="quote"`다.
  3. `analyze_email`(intent="deal" → extract_deal)·`routing.py`·`build.py`는 바꾸지 않는다(3.2절).
- 문서는 `make_quote` 노드 안에서 나눈다(노드·전이 이름은 그대로). `doc_kind="quote"`면 기존 `create_quote` 도구(그대로), 무역서류면 새 도구 `create_trade_document`(15.5절)를 부른다. 노드가 `deal_terms["doc_kind"]`로 고른다. [Claude proposal]

### 15.2 추출 형식(`TradeDocTerms`)과 금액 자료형
- 기존 `DealTerms`(4.3절)와 **별도 형식**이다. `DealTerms`는 국내 견적서 전용으로 그대로 두고 `doc_kind` 키만 더한다(값 "quote"; 없으면 "quote"로 본다). 무역서류 값은 원본 `extractor.py`의 스키마 키를 그대로 쓴다(사본·이식본 결과 비교 검증 때문). 금액 자료형(원 단위 정수 vs Decimal 문자열)과 품목 필드 수가 달라 하나로 합치지 않는다. [Claude proposal]
- 상태 `deal_terms`는 `DealTerms | TradeDocTerms | None`로 확장하고 `deal_terms["doc_kind"]`로 판별한다. 2절 표의 이 확장은 이식 코드가 들어가는 하위 작업 PR에서 이 절과 함께 고친다(공통 부분 변경 절차).

```python
TradeParty(TypedDict):    # legal_name·address·contact·phone·email·registration_details (모두 str | None)
TradePackage(TypedDict):  # package_type·package_count·net_weight_kg·gross_weight_kg·dimensions·shipping_marks (모두 str | None)
TradeItem(TypedDict):     # product_name·product_code·capacity·quantity·unit·unit_price·price_basis·
                         # discount_percent·paid_quantity·free_quantity·shipped_quantity·promotion·
                         # price_source·source·package_type·package_count·net_weight_kg·gross_weight_kg·
                         # volume_cbm·hs_code·source_line_total (모두 str | None.
                         # source_line_total은 CI 확장 키: 원본 PI에 인쇄된 행 금액, 재계산 금지)
TradeDocTerms(TypedDict, total=False):   # 원본 스키마 + 이식 판별 키
    doc_kind: Literal["PI", "PO", "CI", "PL"]   # document_type과 같은 값. 도구가 추출 직후 채운다
    document_type: str                          # 원본 파이프라인이 읽는 키("PI"/"PO"/"CI"/"PL")
    product_family: str | None                  # cosmetics·polysilicon·wafer·solar_cell·solar_module·other
    currency: str | None                        # ISO 3자리(USD·KRW·EUR·CNY)
    buyer: TradeParty
    seller: TradeParty
    items: list[TradeItem]
    # incoterms·payment_terms·remarks·document_number·issue_date·ship_to·bill_to·shipment_reference·
    # country_of_origin·hs_code·actual_package_count·container_count·declared_total_quantity·
    # declared_total_quantity_unit·declared_net_weight_kg·declared_gross_weight_kg·declared_volume_cbm
    # : 모두 str | None. ship_to_source는 후처리가 꺼내(pop) SHIP TO 명시 확인에 쓰고
    # 최종 초안에는 남기지 않는다(원본과 같다)
    packages: list[TradePackage]
    source_document_type: str | None   # CI 확장 키: 추출이 원본 문서를 PI로 식별하면 "PI", 아니면 None
    source_total: str | None           # CI 확장 키: 원본 PI에 인쇄된 총액(재계산 금지)
    missing_fields: list[str]      # 원본 추출의 자기 보고(원본 파이프라인이 blocking_issues로 반영)
    conflicts: list[str]
    source_notes: list[str]         # 근거(원문 인용)
    # 원본 후처리·가격 적용이 더하는 키(pending_confirmations·_ci_from_pi·is_sample·master_price·
    # price_override_confirmed·product_id·_packing_* 등)는 원본 이름 그대로 따라온다(total=False).
```

- CI-from-PI 입력 정의: 원본 `prepare_ci_import(draft, *, requested_type, has_attachments)`의 `has_attachments`는 이식본에서 항상 참으로 부른다. 첨부 파일 읽기는 범위 밖(15.8절)이라 CI 변환의 원문 근거는 메일 본문에 인용된 PI 내용이고, `_ci_from_pi` 판정은 원본 그대로 추출 결과의 `source_document_type == "PI"`만으로 한다. PI 근거가 없는 CI는 `is_pi_import`가 거짓이 되어 카탈로그 가격 대체 금지·생성 차단(15.5절)이 그대로 걸린다. CI 확장 키(`source_document_type`·`source_total`·품목 `source_line_total`)는 **추출 문서 종류가 `CI`일 때** 스키마에 포함한다(변환 요청 표현과 무관). 원본 조건은 `requested_document_type == 'CI' and images`(첨부 있음)인데 이식본은 `has_attachments`를 항상 참으로 부르므로 CI 추출은 항상 이 키를 받는다 — 첨부 여부 조건이 사라진 것만 원본과 다르다.

- LLM 호출은 기존 `call_structured`(6절)만 쓴다. 원본 `extractor.py`의 OpenAI 요청 형식은 옮기지 않고, `SYSTEM_PROMPT`의 지시 규칙(발행일을 원문에서 복사하지 않음, 없는 값을 지어내지 않음, 같은 뜻의 라벨·통화 기호, 다국어 입력·영문 출력, 프로모션 N+M, SHIP TO 명시 라벨만)을 **새 프롬프트 이름 `extract_trade_terms.v1`**(`app/prompts/extract_trade_terms.py`, 6절 규칙대로 이름당 NAME·VERSION·TEMPLATE 하나)로 옮긴다. 구조화 출력 pydantic 모델 `ExtractedTradeDoc`은 도구 파일 안에 둔다. quote 경로는 기존 `extract_deal_terms.v1`(모델 `ExtractedDealTerms`)을 그대로 쓰고, `extract_deal_terms` 도구가 `recognize_doc_kind` 결과로 둘 중 하나를 골라 부른다(무역 → `extract_trade_terms.v1`). [Request(계획 2절) · Claude proposal]
- 숫자·금액 표기(원본 `trade_documents.py` 그대로):
  - 무역서류의 모든 수량·금액 필드는 **Decimal 문자열**이다(천단위 콤마 허용, 검증에서 제거). int·float를 쓰지 않는다. 국내 견적서(`QuoteDraft`)의 원 단위 정수는 그대로다.
  - 통화별 자릿수: KRW는 소수 없이(quantum 1), USD·EUR·CNY는 소수 둘째 자리(quantum 0.01). 단가 quantum은 화장품(cosmetics)은 통화 quantum, 그 밖 제품군은 0.000001(`PRICE_QUANTUM`).
  - 반올림은 ROUND_HALF_UP. 계산 순서: 할인 적용 단가를 단가 quantum으로 quantize → 수량을 곱함 → 행 금액을 통화 quantum으로 quantize → 합계 quantize.
  - 명시적 수량 0은 유효하다(행 유지, 행 금액 0). 음수·비숫자·NaN/Infinity는 오류이다.
- 발행일 `issue_date`는 생성 시점 Asia/Seoul 날짜의 영문 표기(`current_issue_date()`)다. 주문·메일의 날짜를 복사하지 않는다.
- 후처리는 2가 15.4절 대응표대로 `app/trade/postprocess.py`로 옮긴다(수량 동기화·수량/통화 별칭·할인 지시·REMARK/SHIP TO 명시 확인·문서 종류 인식·발행사 기본값·PI 샘플 행·프로모션 명령·근거 검증 `verify_item_quotes`·거래처 프로필 적용). 빈 값은 추측하지 않고 재질문(15.3절)로 넘긴다.

### 15.3 문서 종류별 필수 항목 (5절 확장)
- `get_required_fields(user_id: int, doc_kind: str = "quote") -> RequiredFields`로 입력을 확장한다. 반환 형식은 그대로(`source="config"`, RAG는 범위 밖). `check_required` 노드가 `deal_terms["doc_kind"]`를 넘긴다. [Claude proposal]
- 무역 필수 키는 상대방에게 재질문할 항목만 담는다[임시: 협의 13-사용]. 문서번호(사용자가 DRAFT로 표시 가능)·단가(카탈로그·PI 원문·화면 입력이 채움)·발행 회사 정보(설정)는 재질문 목록에서 빼고 `create_trade_document`의 `blocking_issues`로 다룬다. [Claude proposal]

| `doc_kind` | 키 |
|---|---|
| `PI` | `incoterms` `payment_terms` `currency` `counterparty_legal_name` `counterparty_address` `item_name` `unit` `quantity` `discount_percent` |
| `PO` | `incoterms` `payment_terms` `currency` `counterparty_legal_name` `counterparty_address` `item_name` `unit` `quantity` |
| `CI` | `incoterms` `currency` `country_of_origin` `shipment_reference` `counterparty_legal_name` `counterparty_address` `item_name` `unit` `quantity` `discount_percent` |
| `PL` | `incoterms` `shipment_reference` `container_count` `counterparty_legal_name` `counterparty_address` `item_name` `unit` `quantity` |

- `FIELD_LABELS`(같은 파일)에 더할 한국어 이름: `incoterms` 인코텀즈(인도조건·지정장소) · `payment_terms` 결제조건 · `currency` 통화 · `counterparty_legal_name` 상대방 법인명 · `counterparty_address` 상대방 주소 · `item_name` 품목명 · `unit` 수량 단위 · `quantity` 수량 · `discount_percent` 할인율 · `country_of_origin` 원산지 · `shipment_reference` 선적번호 · `container_count` 컨테이너 수. `discount_percent`는 값이 None이면 빠짐이고 "0"(할인 없음)은 있음이다. PL은 통화·단가·할인을 요구하지 않는다.
- `check_required_fields` 도구는 무역 형식이면 다음 대응으로 찾는다. `counterparty_legal_name`·`counterparty_address`는 PO는 `seller`, 그 밖은 `buyer`의 `legal_name`·`address`다. 품목 키는 품목마다 값이 있어야 하고(기존 `ITEM_KEYS` 확장), 무역 형식에서 `item_name`은 `TradeItem`의 `product_name`을 본다(키 이름만 quote와 공유하고 조회 필드가 다르다), `quantity`는 `quantity`·`paid_quantity`(PL이면 `shipped_quantity`도) 중 하나라도 있으면 있다.
- 상태 `missing_fields`는 이 절의 키 기준(`check_required` 결과)이다. `TradeDocTerms.missing_fields`(원본 추출의 자기 보고)과 다르다.

### 15.4 모듈 경계 대응표 (원본 → `app/trade/`)
- 계산·검사 모듈은 원본을 복사한 뒤 고친다[임시: 협의 전 일반 규칙]. 원본 import 경로(`Quotation_KEKOREA.agent...`)는 `app.trade...`로 바꾼다. [Request]

| 원본(`reference/kekorea/Quotation_KEKOREA/`) | 이식 위치 | 함수(원본 → 이식)와 입출력 |
|---|---|---|
| `agent/trade_documents.py` | `app/trade/trade_documents.py` | `validate_and_calculate(data: dict, *, issuer_key: str) -> dict`(검증+Decimal 계산. 반환에 행별 계산 결과·`subtotal`·`total`·`blocking_issues`·`ready_for_issue` 포함. 발행사 역할 검사의 `"KE KOREA" in 이름` 부분 매칭을 이름 키끼리의 **부분 매칭**으로 바꾼다: PO는 buyer의, PI/CI는 seller의 이름 키에 `issuer_key`가 포함돼야 통과('KE KOREA'↔'KE KOREA AMERICA' 같은 원본 허용 범위 유지)하고 발행사 키가 반대 역할 이름 키에 포함되면 차단한다. `issuer_key`가 빈 값이면 '발행 회사 이름 미설정'으로 차단한다. 검사 문구는 원본 'must be KE KOREA' 대신 'must be the issuing company' 등으로 일반화한다. `create_trade_document`가 넘긴다) · `normalize_quantity_unit(value) -> str` · `apply_promotion(paid_quantity, promotion) -> dict`(`paid_quantity`·`free_quantity`·`shipped_quantity`) · `current_issue_date() -> str`. 상수 `DOC_TYPES`·`FAMILIES`·`MONEY_QUANTUM`·`PRICE_QUANTUM` 그대로. `issuer_key`는 발행 회사 이름(`company_profiles`의 `legal_name_en`, 없으면 `company_name`)을 `counterparties`의 이름 키 규칙(법인 접미사·공백 제거, 대소문자 무시)으로 정규화한 값이다[임시: 협의 1] |
| `agent/pricing.py` | `app/trade/pricing.py` | `apply_verified_eclado_prices` → `apply_verified_catalog_prices(draft, catalog) -> dict`(이식 규칙 '코드에 ECLADO 문자열 금지'가 우선해 개명했다. `ci_import`의 지연 import도 이 이름을 쓴다) · `apply_catalog_product_matches(draft, catalog) -> dict` · `match_eclado_product` → `match_catalog_product(name, capacity, products, product_code=None) -> dict` · `resolve_price(product_id, prices, role, currency, party_key)` · `is_eclado_supplier` → `is_supplier_alias(name, aliases)`(회사 고정 별칭 → 사용자 거래처 별칭[임시: 협의 5]) · 신규 `build_trade_catalog(rows: list[dict]) -> dict`(아래 '카탈로그 자료 구조'). `load_local_seed`·`load_local_catalog`·`load_supabase_catalog`는 없애고 카탈로그는 아래 변환으로 |
| `agent/product_matching.py` | `app/trade/product_matching.py` | `match_product(name, capacity, products, product_code=None) -> dict`(`status`: matched/suggested/ambiguous/not_found). 진입의 `brand == 'ECLADO'` 필터와 product `brand` 키를 없애고(카탈로그 전체가 그 사용자의 것) `_LABELS`의 회사 브랜드 라벨어(eclado·에끌라도·에끌라두)도 뺀다. 나머지 그대로 |
| `agent/promotions.py` | `app/trade/promotions.py` | `apply_promotion_commands(draft, prompt, products=()) -> dict` · `recalculate_order_promotions(draft) -> dict` · `normalize_promotion(value) -> str \| None` |
| `agent/samples.py` | `app/trade/samples.py` | `has_sample_keyword`·`is_manual_sample`·`new_sample`·`update_sample`·`ensure_sample_rows`(PI 샘플 행, 단가 0 허용[임시: 협의 12]). `edit_sample_rows`는 화면 코드라 옮기지 않는다 |
| `agent/counterparties.py` | `app/trade/counterparties.py` | `apply_company_profiles(draft, profiles, prompt=...) -> dict`(주문 값 우선, 빈 값만 채움) 그대로. `load_company_profiles`·`save_local_profile`·`upsert_company_profile`·Supabase 접근은 없애고 `counterparties` 표(15.7절) 조회·저장으로 |
| `agent/ci_import.py` | `app/trade/ci_import.py` | `prepare_ci_import`·`is_pi_import`·`is_ci_conversion_request`·`apply_document_prices`·`pi_source_zero_price`·`ci_import_issues(result) -> list[str]`·`ci_render_data(result) -> dict`(CI 렌더 입력 준비) 그대로 |
| `agent/packing.py` | `app/trade/packing.py` | `reconcile_packing(data) -> dict`(`quantities`·`quantity_complete`·`calculated`·`issues`·`discrepancies`) — **코어**. `packing_review.py`에 같은 이름의 래퍼가 있고 15.5절·15.6절에서 부르는 `reconcile_packing`은 그 래퍼다(아래 행). `normalize_quantity_unit`은 `app/trade/trade_documents`에서 import(D가 B의 함수를 씀 — 원본 관계 유지) |
| `agent/packing_review.py` | `app/trade/packing_review.py` | `reconcile_packing`(래퍼) · `normalize_packing_inputs` · `packing_total_changes(data, check=None) -> list[dict]` · `apply_approved_packing_totals(data) -> dict`(승인 시 원본 합계 보존) · `PACKING_SOURCE_FIELDS` |
| `agent/review_fields.py` | `app/trade/review_fields.py` | `missing_review_fields(data) -> list[ReviewField]` · `apply_review_value(data, field, value)`(빠진 값 서술·검토 입력. 입력 경로는 5·6이 잇는다) |
| `app_postprocess.py` | `app/trade/postprocess.py` | `_synchronize_extracted_quantities`→`synchronize_quantities` · `_format_quantity_display`→`format_quantity_display` · `_explicit_remark`→`explicit_remark` · `_has_explicit_ship_to`→`has_explicit_ship_to` · `_discount_instruction`→`discount_instruction` · `_normalize_quantity_aliases`→`normalize_quantity_aliases` · `_normalize_currency_alias`→`normalize_currency_alias` · `_requested_document_type`→`recognize_doc_kind` · `_keep_delivery_note_in_terms`→`keep_delivery_note_in_terms` · `_apply_ke_korea_company_defaults`→`apply_issuer_defaults(draft, doc_kind, company)`(KE KOREA 고정값 → `company_profiles` 설정 스냅샷[임시: 협의 1]. 영문 법인명은 스냅샷의 `legal_name_en` → `legal_name` → `company_name` 순으로 읽고, 설정이 없거나 비어 있으면 채우지 않고 검토 입력(15.5절 `needs_input`)으로 넘긴다). `_extract_draft`의 호출 순서는 `extract_deal_terms` 도구가 같은 순서로 따른다(가격 적용 제외 — 위 의존 문단) |
| `agent/extractor.py`의 `verify_item_quotes` | `app/trade/verify_quotes.py` | `verify_item_quotes(draft, prompt, *, image_context=False) -> dict`(숫자·당사자·조건의 원문 근거 검증) |
| `agent/renderers.py` | `app/trade/renderers.py` | `format_currency_amount`·`amount_in_english`·`document_lines`·`_pdf_bytes`·`_xlsx_bytes`·`render_files`를 **모두 옮긴다** — 원본 테스트의 출력 부분(`test_trade_documents.py` 등)이 이 함수들을 직접 시험해 4절 완료 기준에 필요하기 때문이다. 단 서비스 경로(발송 첨부·미리보기)가 쓰는 PDF는 `pi_pdf.render_trade_document`뿐이고 renderers 출력(XLSX·HTML·검토 PDF)은 테스트·사본 비교 검증용이다(15.8절). `document_lines`·`_xlsx_bytes` 안의 PL `reconcile_packing` 호출은 없애고 `doc["packing_totals"]`(15.5절)를 읽는다(pi_pdf와 같은 반전) |
| `agent/pi_pdf.py` | `app/trade/pi_pdf.py` | `render_trade_document(data, bank_details=None, *, logo=None, seal=None) -> bytes`. 입력을 파일 경로에서 PNG bytes로 바꾸고, PL 합계는 `data["packing_totals"]`을 읽는다(아래 import 관계). PL PDF의 `TOTAL QUANTITY` 줄은 원본 그대로 렌더러 안의 `_total_quantity_summary`(품목 직접 합산, 단위 정규화 안 함)로 만든다 — D를 부르지 않는 C 내부 계산이라 15.5절 '합계를 다시 계산하지 않는다' 규칙의 대상이 아니다. 원본 파일 뒤쪽의 중복 정의(덮어쓰는 죽은 코드: 프리미엄 PI 1페이지 레이아웃·회사 로고 crop 값)는 옮기지 않는다(실제 동작인 뒤쪽 `render_trade_document`만 옮긴다) |
| `agent/branding.py`·`agent/seal_storage.py` | `app/trade/branding.py` | `resolve_company_seal` → `resolve_company_seal(user_id, ...) -> tuple[bytes \| None, str \| None]`(직인 bytes, 오류 문구). `seal_storage.py`는 없애고 `company_branding` 표(15.7절)에서 읽는다. PNG 매직 검사와 SHA-256 대조를 유지한다: `company_branding.seal_sha256`은 **업로드할 때 seal bytes의 SHA-256을 저장한 값**이고 `resolve_company_seal`은 조회한 bytes의 해시와 이 저장값이 같은지 확인한다(업로드 뒤 변조·저장 오류 감지가 목적 — 원본의 고정 상수 비교를 사용자별 저장값 기준으로 일반화) |

- import 관계(원본 유지·변경): `renderers`·`pi_pdf`(C 묶음)는 `trade_documents`(B)의 `current_issue_date`를 쓴다(유지). `packing`·`packing_review`·`ci_import`(D 묶음)는 `trade_documents`(B)의 `normalize_quantity_unit` 등을 쓴다(유지). **C는 D의 PL 합계 함수를 부르지 않는다(변경)**: PL 렌더링에 필요한 합계는 `TradeDocDraft["packing_totals"]`(15.5절)로 받고, CI 렌더 입력은 D의 `ci_render_data` 결과를 받는다. 그래서 C(문서 출력)와 D(CI·PL)가 서로를 기다리지 않는다. [Claude proposal]
- 모듈 간 런타임 의존과 일정 대응(원본 유지): 원본 `validate_and_calculate`는 품목 루프에서 `ci_import`·`promotions`을, PL 검사에서 `packing`을 함수 안(지연) import하고(B), 원본 `_extract_draft`의 추출 순서는 `counterparties`·`promotions`·`samples`·`pricing`·`ci_import`를 차례로 부른다(A). 이식본은 **가격 적용(`pricing`)을 추출 파이프라인에서 빼고 `create_trade_document`(15.5절)로 옮겼으므로** A의 추출 순서는 `counterparties`·`promotions`·`samples`·`ci_import`만 따르고, B의 지연 import는 그대로 둔다(모듈 top import로 올리지 않는다). 즉 2절(A)의 추출 순서는 3절(B 소관: `counterparties`·`promotions`·`samples`)과 5절(D 소관: `ci_import`) 모듈을, 3절(B)의 `trade_documents.py`는 `promotions.py`(3절)와 `ci_import.py`·`packing.py`(5절)를 실행 시점에 쓴다. 일정 대응(계획 순서 '2·3·4 동시, 5는 3 뒤'): 먼저 들어가는 2절(A)·3절(B) 이식 PR에는 아직 없는 의존 모듈(5절 소관 `ci_import.py`·`packing.py` 등)의 **원본 복사본(고침 없음)**을 함께 넣어 자기 완료 기준 테스트가 돌게 하고, 5절(D)은 그 복사본 위에서 CI·PL 흐름(`packing_review`·승인·렌더 연결)을 이식하고 사용자 일반화 수정을 적용한다. A의 완료 기준 '같은 입력에 사본·이식본 후처리 결과가 같다'는 **개별 후처리 함수 기준**이고, 전체 추출 순서 등가는 6절 대표 흐름 테스트로 확인한다. [Claude proposal]
- 카탈로그 자료 구조(원본 seed를 사용자 표로): `build_trade_catalog(rows)`(`app/trade/pricing.py`)가 `make_quote` 노드에서 받은 `price_list_items` 무역 행(15.7절)을 원본 seed 구조로 바꾼다. **`products`는 `item_name` 기준으로 중복 제거한다** — 같은 품목의 매입·판매·통화별 가격 행(무역 행 유일 인덱스가 정상 데이터로 허용하는 조합)이 여러 개여도 product는 하나다. product는 `{"id": <그 품목 행들 중 가장 작은 행 id>, "item_name": item_name, "capacity": <행들 중 비어 있지 않은 첫 값>, "source_code": <행들 중 비어 있지 않은 첫 product_code>}`이고 모든 가격 행의 `product_id`는 그 id를 가리킨다(중복 product를 그대로 두면 원본 `match_product`가 이름 매칭 후 candidates가 여러 개라 항상 ambiguous를 돌려주기 때문이다). `purchase_prices`/`buyer_prices`는 행마다 `{"product_id": <위 id>, "currency": currency, "unit_price": unit_price_text, "price_basis": price_basis, "supplier_key"`/`"buyer_key": party_key}`이고 `source_row` 키는 없다(`price_list_items`에 행 출처 열이 없다). 올바르지 않은 행은 단가를 노출하지 않고 `ValueError`로 막는다(원본 카탈로그 불러오기의 오류 처리 규칙 유지). 원본의 회사 고정값은 일반화한다[임시: 협의 5·7·8]: `expected_party` "ECLADO"/"DEAR GLOW" 하드코딩은 없애고 카탈로그 가격 적용 여부는 문서 상대방(PO는 seller, 그 밖은 buyer)의 이름 키와 가격 행 `party_key`의 일치로 판정하며, 일치 행이 없으면 공통 가격 행(`party_key` 빈 문자열)으로 다시 찾는다(원본 `resolve_price`와 같이 유일해야 확정). PO의 통화 KRW 강제는 없애고 문서에 명시된 통화가 있으면 그 통화의 매입 행만 쓰고, 없을 때 매입 행 통화가 하나뿐이면 그 통화로 정한다(원본 `_catalog_currency_inferred` 표시 규칙 유지, 15.8절 '명시된 통화 임의 변경 금지'와 어긋나지 않는다). 회사 이름이 들어간 안내 문구도 같은 원칙으로 일반화한다: 'Exact ECLADO product match …' → 'Exact catalog product match …', 'Verified ECLADO catalog; source workbook row N' → 'Verified catalog price'(`source_row`가 없어 행 번호 표기는 붙지 않는다), '… local catalog price is only for DEAR GLOW' → 적용 가능한 `party_key` 목록 표기.

### 15.5 문서 생성 도구와 초안 형식
- 새 도구 `create_trade_document`(`app/tools/create_trade_document.py`, 4.2절 규칙대로 `TOOLS`에 등록).

| 도구 이름 | 입력(`Input`) | 성공 때 `value` | 방식 |
|---|---|---|---|
| `create_trade_document` | `user_id`·`thread_id`·`deal_terms`(`TradeDocTerms`)·`company`(dict \| None)·`bank`(dict \| None, PI용 계좌 — 스냅샷 키는 15.7절)·`price_list`(무역 카탈로그 행 목록) | `TradeDocDraft`(DB 저장, `trade_doc_id` 채움) | 코드. `build_trade_catalog`(15.4절) → `apply_document_prices`(가격 출처 아래) → `validate_and_calculate`(발행사 이름 키 `issuer_key` 전달, 15.4절) → (PL) `normalize_packing_inputs`·`reconcile_packing`(`app/trade/packing_review.py`의 **래퍼**, `_packing_input_issues` 포함)·`packing_total_changes` → `packing_totals`(아래 `packages_total` 포함) → (CI) `ci_import_issues` |

- 문서별 가격 출처[임시: 협의 8-사용]: PO는 매입가(`role="purchase"`), PI는 구매처별 판매가(`role="sale"`), CI는 첨부 PI의 거래가격 그대로(PI 없으면 카탈로그 가격 대체 금지·생성 차단), PL은 가격 없음(제품 매칭만). 명시된 통화를 임의로 바꾸지 않는다.
- `TradeDocDraft`(계산된 문서 초안이자 렌더러 입력):

```python
PackingTotals(TypedDict):
    quantities: dict[str, str]           # 정규화 단위 → 행 합계(다른 단위는 합치지 않음)
    quantity_complete: bool
    calculated: dict[str, str | None]    # package_count·net_weight_kg·gross_weight_kg·volume_cbm
    packages_total: dict[str, str | None]  # packages 배열 net/gross 합계(원본 pi_pdf 폴백 식 그대로.
                                         #     calculated·선언값이 모두 없을 때 렌더러가 쓰는 값)
    issues: list[str]                    # 승인으로 해소할 수 없는 오류
    discrepancies: list[str]             # 원본/계산 합계 차이(승인 대상)
    changes: list[dict]                  # packing_total_changes() 제안 {field, label, source, calculated}
    approved: bool                       # apply_approved_packing_totals()를 지났는지

TradeDocDraft(TypedDict, total=False):
    trade_doc_id: int | None             # DB 저장 뒤 채움
    doc_kind: str                        # document_type과 같은 값
    doc_no: str                          # <doc_kind>-YYYYMMDD-NNN(사용자별 일련번호, create_quote와 같은 채번·잠금 방식.
                                         #     내부 관리 번호로 문서에 인쇄되는 document_number와 무관)
    # …원본 validate_and_calculate 반환 전체(document_type·product_family·currency·buyer·seller·
    #   items(행마다 base_unit_price·final_unit_price·line_total·display_quantity 등 계산 결과 포함)·
    #   incoterms·payment_terms·remarks·document_number·issue_date·ship_to·bill_to·shipment_reference·
    #   country_of_origin·hs_code·포장 선언값·packages·missing_fields·conflicts·source_notes·
    #   pending_confirmations·subtotal·total·blocking_issues·ready_for_issue)…
    issuer: dict                         # 발행 회사 스냅샷(company_profiles에서 복사)
    bank: dict | None                    # 계좌 스냅샷(PI만. 키는 원본 렌더러가 읽는 대문자 6키 — 15.7절)
    packing_totals: PackingTotals | None # PL만. 렌더러는 이 값을 calculated → 선언값 → packages_total
                                         #     순서로 읽고 합계·폴백 합산을 다시 계산하지 않는다
    status: Literal["needs_input", "ready", "sent"]  # blocking_issues·PL 합계 미승인이면 needs_input
```

- 원본 `validate_and_calculate`의 `status`("DRAFT"/"READY_FOR_USER_CONFIRMATION")는 원본 조건 `not blocking and not issues` 그대로 이식 `status`로 옮긴다: 합산 반환값 `blocking_issues`(blocking+issues)가 비어 있으면 `ready`, 하나라도 있으면 `needs_input`(issues-only 경고만 있어도 `needs_input`이다). `ready_for_issue`(bool)는 원본 키 그대로 남는다.
- 문서번호·채번 순서: `doc_no`는 저장 시 채번하는 내부 관리 번호이고 문서에 인쇄되는 `document_number`와 무관하다. `create_trade_document`는 `document_number`에 값을 넣지 않은 채 `validate_and_calculate`를 부른다 — 원본 검사 그대로 비면 blocking → `needs_input`이 된다(발행사·문서번호·단가는 재질문이 아니라 이 검토 입력으로 채운다, 15.3절). 빠진 값 보충은 `app/trade/review_fields.py`의 `apply_review_value`로 값을 넣은 뒤 서비스 함수 `revise_trade_document(user_id: int, trade_doc_id: int, values: dict) -> TradeDocDraft | None`(`app/services/`, 5·6이 구현)가 `validate_and_calculate`를 다시 돌려 status를 다시 정해 저장한다(절차는 `approve_packing_totals` (3)·(4)와 같다).
- CI 렌더 입력 시점(원본 보존): 저장하는 `TradeDocDraft`는 `ci_render_data`를 적용하지 않은 값을 유지하고, PDF 렌더러를 부르는 모든 경로(발송 첨부·미리보기)는 렌더 직전에 `is_pi_import`일 때 `ci_render_data(draft)`를 한 번 통과시킨 값으로 만든다(원본 `render_files(ci_render_data(result), ...)`와 같은 시점, FOC 품목 수량 표시 조정). 두 경로가 같은 변환을 쓰므로 사본·이식본 PDF가 같아야 한다는 4절 완료 기준이 지켜진다.
- PL 합계 승인(원본 보존): 원본/계산 합계 비교표(`discrepancies`·`changes`)와 명시적 승인을 유지한다. 승인은 서비스 함수 `approve_packing_totals(user_id: int, trade_doc_id: int, *, database) -> TradeDocDraft | None`(`app/services/trade_docs.py`, 5가 구현)가 순서대로 한다. (1) 저장된 draft를 `normalize_packing_inputs`과 래퍼 `reconcile_packing`(`app/trade/packing_review.py`)으로 다시 확인해 `issues`가 있거나 `quantity_complete`가 거짓이면 `None`을 돌려준다 — 문서는 `needs_input` 그대로이고 원인 문구는 `blocking_issues`·`packing_totals.issues`가 이미 담는다(원본 `apply_approved_packing_totals`의 ValueError를 이 반환 규칙으로 바꾼다). (2) `apply_approved_packing_totals(draft)`를 적용한다(원본 합계 보존, 계산 가능한 합계만 적용). (3) `validate_and_calculate`를 다시 돌려(15.4절 `issuer_key` 전달) `blocking_issues`를 재계산하고 `status`를 다시 정한다. (4) `packing_totals`을 다시 계산해(`packages_total` 포함) `approved=True`로 채우고 DB에 저장한 뒤 draft를 돌려준다. 승인 전 발송은 불가하다. 화면 경로는 정의하지 않는다(범위 밖).
- `app/services/trade_docs.py`(5가 구현): 문서 초안 검증·저장과 PL 합계 비교 제안·승인·취소·수정의 백엔드다(화면 없음). `save_trade_document(database, *, user_id, thread_id, draft, run_id="", deal_terms_id=None)`는 `finalize_draft`(검증 + PL `packing_totals` 제안 확정)을 돌려 문서번호(`doc_no`, 사용자별 채번·잠금은 `create_quote`와 같은 방식)와 함께 `trade_documents` 표에 저장한다. PL 합계 비교 제안은 저장 때 `packing_totals`(`changes`·`discrepancies`, `approved=False`)로 남고, 원본/계산 합계 차이와 래퍼(`_packing_input_issues`) 오류는 `blocking_issues`에 이어져 `needs_input`이 된다(차이가 없는 PL은 승인 없이 `ready`이되 발송 조건은 15.6절대로 `packing_totals.approved`를 본다). `cancel_packing_approval`은 승인 전 원본 합계(`_packing_original_totals`)로 되돌려 다시 승인 대상으로 만들고, `revise_trade_document`(값 키는 점 표기 `document_number`·`buyer.legal_name`·`items.0.unit_price`)는 `apply_review_value`로 값을 넣어 재검증·저장하며 품목·원본 합계 값이 바뀌면 승인을 다시 받게 한다. 승인·취소·수정 이력은 초안의 `packing_approval_log`(PL만, `{action, at[, fields]}` 목록)에 남는다. 중복 방지는 `app/services/approval.py`와 같은 사용자별 잠금과 조건부 UPDATE(`status != 'sent'`, rowcount 확인), 이미 승인된 문서의 재승인은 현재 초안을 그대로 돌려주는 방식이다. `issuer_key`는 초안의 발행 회사 스냅숏(`issuer`)에서 정한다(15.7절 스냅숏 규칙: 설정 변경이 기존 문서를 바꾸지 않는다).

### 15.6 상태·노드·도구 확장 (2·3·4절에 더하는 것)
- 상태(2절 표에 더하는 행; 코드는 이식 하위 작업 PR에서 함께 고친다):

| 이름 | 의미 | 자료형 | 초기값 | 읽는 노드 | 고치는 노드 |
|---|---|---|---|---|---|
| `trade_doc_draft` | 무역서류 초안 | `TradeDocDraft \| None` | `None` | `draft_replies`(quote), `reflect`, `save_pending` | `make_quote` |

- `deal_terms` 자료형: `DealTerms | TradeDocTerms | None`(판별 `doc_kind`, 없으면 "quote"). `reply_mode="quote"`는 국내·무역 문서 동봉 답장에 공통으로 쓴다.
- 노드 확장(이름·전이는 그대로):
  - `extract_deal`: 무역 경로면 추출·후처리(15.2절)를 끝낸 `TradeDocTerms`를 `deal_terms`에 넣는다. 거래처 자동 채움과 발행사 기본값[임시: 협의 1·5·6]을 위해 노드가 `counterparties` 표(15.7절)와 발행 회사 설정 스냅샷을 읽어 도구에 넘긴다 — `extract_deal_terms` 도구 입력에 `user_id`·`counterparties`·`company`(발행 회사 스냅샷, `apply_issuer_defaults`가 씀)을 더한다(quote 경로는 빈 목록·None).
  - `check_required`: `get_required_fields(user_id, doc_kind)`로 무역 필수 키(15.3절)를 검사한다.
  - `make_quote`: `doc_kind`로 도구를 고른다(15.1절). 무역 분기는 `company`(`company_profiles`)·`bank`(`company_bank_accounts`, 문서 통화 행 우선)·`price_list`(`price_list_items` 무역 행)를 읽어 넘긴다.
  - `draft_replies`(quote): 무역일 때 `quote_draft` 대신 `trade_doc_draft`를 받아 문서 안내 후보를 만든다(입력 확장). 프롬프트는 `draft_replies.v2`를 고쳐 `draft_replies.v3`으로 올리고 입력 변수에 `trade_doc`(무역일 때 문서 종류·문서번호·합계 요약 텍스트)를 더하며 `app/prompts/VERSIONS.md`에 기록한다(6절 규칙, 6이 구현).
- 서비스(3.1절 승인 경로에 더하는 것, 6이 구현): `send_approved_trade_document(user_id, trade_doc_id, candidate_id, *, access) -> ApprovalResult`(`app/services/approval.py`). PDF는 `app/trade/pi_pdf.render_trade_document(draft, bank, logo=..., seal=...)`로 만들되 CI(`is_pi_import`)는 렌더 직전에 `ci_render_data(draft)`를 통과시킨 값을 쓴다(15.5절). 첨부 파일 이름은 `<doc_no>.pdf`. 발송 조건: `status="ready"`(PL은 `packing_totals.approved` 포함)이고, CI는 PI 원문 근거가 있어야 한다(`is_pi_import`, 15.2절 CI-from-PI 입력 정의). 성공 때 `trade_documents.status="sent"`·`sent_at`(UTC)·`draft["status"]="sent"`. 자동 발송은 없다(승인만).

### 15.7 DB 표 (7절에 더하는 것, 정의만)
- 새 환경변수는 없다(Supabase 의존을 없애고 이 서비스 DB로 바꾼다). 모든 조회는 `user_id`로 거른다.

| 표 | 뜻 | 주요 열 | 쓰는 하위 작업 |
|---|---|---|---|
| `trade_documents` | 무역서류 | `id` PK · `user_id` · `thread_id` · `run_id` · `deal_terms_id` FK 없을 수 있음 · `doc_kind` · `doc_no` (`user_id`,`doc_no`) 유일 · `draft` JSON(`TradeDocDraft`) · `status`(`needs_input`/`ready`/`sent`) · `created_at` · `sent_at` | kekorea-port 2~6 |
| `company_bank_accounts` | 사용자별 계좌(PI 하단 6항목) | `id` PK · `user_id` · `currency` (`user_id`,`currency`) 유일 · `beneficiary` · `bank_name` · `branch` · `swift` · `account_number` · `bank_address` · `updated_at`. 무역 렌더러·초안 스냅샷(`TradeDocDraft.bank`·도구 입력 `bank`)의 dict 키는 원본 렌더러가 읽는 대문자 6키 `BENEFICIARY`·`BANK_NAME`·`BRANCH`·`SWIFT`·`ACCOUNT_NUMBER`·`BANK_ADDRESS`이고 `make_quote` 노드가 이 표의 소문자 열을 그 키로 바꿔 담는다 | kekorea-port 3·4 [임시: 협의 2, 시연은 가상 계좌] |
| `company_branding` | 사용자별 직인·로고 | `user_id` PK · `logo`(BYTES, 없을 수 있음) · `seal`(BYTES, 없을 수 있음) · `seal_sha256`(업로드할 때 seal bytes의 SHA-256을 저장한 값 — 15.4절 branding 행의 대조 기준) · `updated_at` | kekorea-port 4 [임시: 협의 3·4] |
| `counterparties` | 거래처(별칭·기본 정보) | `id` PK · `user_id` · `company_key` (`user_id`,`company_key`) 유일 · `legal_name` · `aliases` JSON · `address` · `contact` · `phone` · `email` · `registration_details` · `default_ship_to` 없을 수 있음 · `ship_to_phone` 없을 수 있음 · `updated_at` | kekorea-port 2·3 [임시: 협의 5·6] |

- 기존 표 변경:
  - `company_profiles`: `legal_name_en`(영문 법인명)·`address`·`phone`·`email`·`registration_details` 열을 더한다[임시: 협의 1 — 기존 공급자 정보 설정으로 같은 방식]. 무역서류 발행사 이름은 `legal_name_en`(없으면 `company_name`, 영문 규칙은 15.8절).
  - `price_list_items`: `role`(`purchase`/`sale`, 없으면 국내 견적서 행)·`currency`(ISO 3자리)·`price_basis`·`product_code`·`capacity`·`unit_price_text`(무역 Decimal 문자열 단가)·`party_key`(그 가격이 적용되는 거래처 `company_key` — 매입 행은 공급처, 판매 행은 구매처. 모든 거래처 공통 가격은 빈 문자열, 무역 행은 항상 채운다[임시: 협의 8]) 열을 더하고 `unit_price`는 없을 수 있음으로 바꾼다[임시: 협의 7, 시연은 가상 가격표]. 유일성은 하나의 제약으로 바꾸지 않는다 — 유니크 제약에서 NULL은 서로 다른 값으로 취급되어 국내 행(`role`·`currency` NULL)의 기존 보증 "같은 품목명은 한 행"이 사라지기 때문이다. 대신 **부분 유니크 인덱스 두 개**로 정의한다: 국내 행(`role IS NULL`)은 (`user_id`,`item_name`) 유일, 무역 행(`role IS NOT NULL`)은 (`user_id`,`item_name`,`role`,`currency`,`party_key`) 유일(Postgres `postgresql_where`·SQLite `sqlite_where`). 국내 견적서 행은 `unit_price`(원 단위 정수)를 항상 채워 기존 동작을 유지하고, 무역 행은 `unit_price`가 NULL이고 단가는 `unit_price_text`에 있다.
  - `reply_candidates`: `trade_doc_id`(FK 없을 수 있음) 열을 더한다(quote 후보의 `quote_id`와 같은 역할).
- 새 문서 생성 때 회사·계좌·카탈로그·거래처 값을 초안에 복사해 스냅샷으로 남기고, 설정 변경이 기존 문서를 바꾸지 않는다(기존 `quotes` 규칙과 같다).

### 15.8 보존 규칙과 이번 범위 밖
- 보존 규칙(`reference/kekorea/PRESERVED_BEHAVIOR.md`, 이식 코드가 지킨다):
  - 명시적 수량 0 유효 · 빈 값 추측 금지(→ 재질문) · SHIP TO는 명시 라벨만(추측 금지) · 발행일은 생성 시점 서울 날짜 · 자동 발송 금지(승인만) · 명시된 통화 임의 변경 금지 · PL/CIPL 합계 비교·명시적 승인(원본 합계 보존, 다른 단위 합침 금지) · 계좌 6항목과 회사 명판·직인은 한 페이지 묶음으로 분할하지 않음(현행 합계·REMARK 하단 묶음 포함) · 상품은 실제 공간이 부족할 때만 다음 페이지 · CI는 첨부 PI 가격 그대로.
  - 영문 문서 규칙[임시: 협의 14 — 무역서류에만 적용]: 한글이면 차단, 중국어 회사 이름·주소는 원문에 영어를 병기.
  - 직인: 원본 이미지 확인(PNG 매직·SHA-256)을 유지하고 직인·키를 Git·로그에 넣지 않는다. 직인이 없으면 PDF 생성을 차단한다(원본 동작 유지[임시: 협의 3 '차단은 선택' — 협의에서 재확인]).
- `KNOWN_ERRORS.md` 반영 원칙: ERR-13(null·목록 당사자로 인한 구조 예외)은 빈 값을 안전하게 취급하는 이식 규칙에 따라 **고쳤고**(빈 dict 취급, 전용 테스트 있음), ERR-04·ERR-08 그 밖의 ERR은 사본·이식본 동일성 비교(각 절 완료 기준)를 위해 **원본 재현 상태로 둔다** — 6절 ERR 점검표에서 하나씩 확인한다. [Claude proposal]
- 이번 범위 밖: 화면 정의(템플릿·경로 — React 프론트·PL 합계 승인 화면은 별도 작업) · RAG 근거 표시(21·22) · PDF·이미지 첨부 읽기(`attachments.py`, 이미지→견적서에서 정함) · renderers 출력(XLSX·HTML·검토 PDF)의 화면·메일 노출(이식은 15.4절대로 하되 테스트·검증용이다) · 계약서 이식 · `KNOWN_ERRORS.md` 재현 점검(6이 PR에 표로 남긴다).

### 15.9 기존 DB 갱신과 수정·발송 일관성 (2026-11-11)
- `Database.create_tables()`는 `app/db/migrations/`의 Alembic 리비전을 적용한다. 기존 국내 견적 표의 새 열·nullable 단가·부분 유니크 인덱스와 무역 문서 버전(`trade_documents.revision`, 기본값 1)을 데이터 보존 방식으로 갱신한다. 기존 이식본처럼 새 표만 생성한 DB에도 적용된다. PostgreSQL은 트랜잭션/스키마 잠금, SQLite는 `BEGIN IMMEDIATE`/배치 복사로 처리하며 갱신 실패는 시작 실패로 돌려준다. 데이터 삭제 방식의 역방향 갱신은 제공하지 않는다.
- 문서 초안의 `revision`은 DB 열과 같다. 수정·PL 합계 승인·취소는 읽은 버전과 일치할 때만 갱신하고 버전을 1 올린다. `revise_trade_document(..., expected_revision=...)`가 명시된 요청은 오래된 버전을 거부한다. 기존 내부 호출 호환용 생략값은 유지하되 후속 JSON API는 기준 버전을 필수로 받는다.
- 검토 입력은 명시된 일반 항목·당사자 항목·품목 항목만 허용한다. 승인 표시·가격 인증·계산 결과·원본 PI 근거는 수정할 수 없다. 통화·거래처·상품·단가 기준 변경은 이전 가격 인증을 해제하고 본인 카탈로그로 재검증한다. 품목별 거래처 가격이 없으면 그 품목의 공통 가격으로 찾는다.
- 발송 서비스는 PDF를 만든 버전을 후보 승인과 같은 트랜잭션에서 조건부 확보한다(`ready` → `sending`). 버전이 바뀌었으면 후보 승인도 되돌리고 `document_changed`를 반환하며 발송하지 않는다. `sending`/`sent` 문서는 수정·PL 승인·취소가 차단된다. 발송 성공은 `sent`, 실패는 기존 명시적 재승인을 위해 `ready`로 돌아간다(자동 재발송 없음).
- 동일 프로세스의 수정·발송은 `app/services/locks.py`의 같은 사용자 잠금을 사용한다. 프로세스 사이의 보호 근거는 이 잠금이 아닌 DB 버전·상태 조건이다.
- 확인: `tests/test_trade_upgrade.py`(기존 SQLite 데이터 보존·가격 재검증·버전/서버 필드 보호·PDF 준비/발송 중 수정), `uv run --with pgserver==0.1.4 pytest tests/test_trade_postgres.py`(가상 데이터만 사용하는 실제 임시 PostgreSQL).


## 16. 독립 문서 API와 사용자 검토

- JSON API는 기존 메일 그래프 밖의 `app/trade/` 도메인 업무를 호출한다. PI 경로는 `/api/trade/pi`이며 상세 입력·응답은 FastAPI OpenAPI(`/docs`)가 코드와 함께 제공한다. 모든 조회/다운로드는 세션 소유자 범위이며 변경 요청은 `/api/session`에서 발급한 CSRF 토큰을 요구한다.
- 입력에는 서버의 상태·계산 결과·가격 인증·승인 표시를 허용하지 않는다. 정확한 숫자는 Decimal 문자열이다. 직접 입력과 LangChain 추출은 같은 업무 계산을 거친다. AI는 거래 단가 변경을 승인할 수 없다.
- `trade_document_versions`는 문서 revision별 불변 초안을 저장한다. 문서 수정은 기대 revision을 조건으로 갱신하며 대기 제안을 무효화한다. `trade_proposals`는 확인할 문서·버전·출력 형식·직인/로고 bytes 및 해시를 고정한다. 선택 요청의 문서 ID·제안 ID·revision·내용 해시가 모두 일치해야 한다.
- `approve`: ready/current인 문서를 issued로 만들고 PDF/XLSX bytes를 `trade_artifacts`에 같은 트랜잭션으로 저장한다. 중복·동시 승인은 같은 파일을 반환한다. `cancel`: 제안을 cancelled로 종료하며 문서나 파일을 발급하지 않는다. `modify`: 기존 제안을 superseded/modify로 기록하고 문서를 새 revision으로 만든 뒤 새 검토를 요구한다. 미완성 수정은 needs_input으로 돌아온다.
- 계좌·회사·이미지 설정 변경은 이미 제안한 내용과 승인 파일을 바꾸지 않는다. 출력 실패 시 pending/ready를 보존해 명시적으로 재시도할 수 있다. 문서 확정 API는 Gmail을 호출하지 않는다. 기존 메일 발송 승인과 문서 발급은 서로 다른 동작이다.
- 서버 기동의 Alembic 갱신은 기존 문서의 현재 버전을 버전 표에 채운다. `FRONTEND_ORIGINS`는 명시한 출처만 허용하고, `SESSION_SAME_SITE=none`은 HTTPS 설정에서만 허용한다.
