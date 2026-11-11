# 에이전트 시험 결과 보고서 (D-02)

- 상태: **틀**(계획 17절, 2026-11-10). 1~5절의 시나리오·판정 기준·시험 환경은 측정 전에 정했다. 6절 이후는 실제 API 시험(계획 18절) 뒤 시험 결과 보고서 작업(계획 19절)이 채운다. 아직 측정하지 않은 값은 `미측정`으로 둔다. [Request · Claude proposal]
- 관련 요구사항: R-12(실제 API 정상·오류 시나리오 실행), R-13(성찰 전후를 같은 기준으로 비교), D-02(시험 결과 보고서). `docs/REQUIREMENTS.md` 참고.
- 시나리오·판정 코드: `app/evaluation/scenarios.py`(시나리오·기대 결과·주입), `app/evaluation/metrics.py`(판정·지표), `app/evaluation/runner.py`(시험 실행기). 이 문서의 3·4절과 코드가 다르면 코드를 기준으로 고치고, 측정 뒤에 기준을 바꾸면 바꾼 날짜·이유를 7절에 적는다. [Claude proposal]

## 1. 대표 사용 흐름
1. 사용자가 테스트용 Gmail로 로그인해 감시를 등록한다.
2. 상대방(시험 계정)이 메일을 보내면 Gmail 푸시 알림으로 그래프가 시작된다: `load_memory` → `analyze_email` → (일반 문의) `draft_replies` / (거래) `extract_deal` → `check_required` → (필수 항목 빠짐) `draft_followup` / (다 있음) `make_quote` → `draft_replies` → (성찰 켬) `reflect` ↺ 재실행 → `save_pending`.
3. 사용자가 답장 후보 2~3개 중 하나를 골라 승인하면 같은 스레드로 보낸다. 견적서 후보는 견적서를 확인한 뒤 PDF를 첨부해 보낸다.

시험 실행기는 2번의 그래프를 알림 대신 저장된 시험 메일로 바로 시작하고(`start_run(mode="test", scenario=…)`), 승인 발송 시나리오만 3번의 승인 경로(`send_approved_candidate()`)까지 이어서 돈다.

## 2. 시험 환경·조건 (측정 전에 정함)
- 같은 입력: 시나리오마다 같은 제목·본문·보낸 사람의 지어낸 메일을 성찰 끔(`reflection_enabled=False`)과 켬(`True`)으로 돌린다. 성찰 말고는 모델(`gemini-3.8-flash`)·프롬프트 버전·도구·한도 값(`app/config.py`의 `LIMITS`)을 같게 둔다. 다르면 6절에 적는다. [Request]
- 반복: 시나리오·성찰 설정마다 기본 3번(`--repeat 3`). 같은 반복 번호의 끔/켬을 번갈아 돌려 시간에 따른 차이가 한쪽에 몰리지 않게 한다. [Claude proposal]
- 기억 섞임 막기: 실행마다 새 메일·스레드 ID를 써서 앞 실행의 단기 기억이 다음 실행에 들어가지 않게 한다. 승인 발송 성공은 장기 기억(상대방 거래 기록·승인 문체)을 남기므로 승인 발송 시나리오는 다른 보낸 사람 주소로 맨 끝에 돌린다. 실제 API 시험은 새 시험 사용자(테스트용 Google 계정)로 한다. [Claude proposal]
- 실제 API와 주입 구분: 가짜 LLM 실행은 시나리오의 준비된 응답만 쓴다(Codex·CI용, 키 없음). 실제 API 실행은 시나리오의 주입 목록(고의 실패, 판단 오류를 일으키는 준비된 응답) 말고는 실제 Gemini·Gmail이 답한다. 주입한 호출의 실행 기록 줄(`llm_call`·`retry`·`send`)에는 `detail.injected: true`와 `detail.injection`(`prepared` 준비된 응답 / `failure` 고의 실패 / `mixed` 둘 다)을 단다(`docs/CONTRACT.md` 8.2절). [Request · Claude proposal]
- 기록: 실행마다 `docs/test-records/`에 `.jsonl` 한 파일(이름 `<YYYYMMDD-HHMM>_<시나리오>_<refl-on|refl-off>_<run_id 앞 8자>.jsonl`, 개인정보 가림)을 남기고, 판정·지표 결과는 실행기의 `--out` JSON으로 남긴다. 판정 결과에는 메일·후보 본문을 넣지 않는다. [Claude proposal]
- 개선 판단: 같은 시나리오를 다시 돌릴 때의 편차보다 큰 차이만 개선으로 본다. [Past work: aio3]

## 3. 시나리오: 정상·오류 유형, 시험 입력과 기대 결과
시험 메일은 모두 지어낸 내용이다(가상상사·가상오피스, `@example.invalid` 주소). 거래 메일 본문 예: '가상상사입니다. 가상 복사용지 100박스 견적 부탁드립니다. 11월 20일까지 필요합니다.' [Request · Claude proposal]

| 키 | 유형 | 시험 입력 | 주입 | 기대 결과(완료 조건) | 정답 도구 조합 |
|---|---|---|---|---|---|
| `normal_general` | 정상 | 제품 안내 자료 일반 문의 | 없음 | 종료 `awaiting_approval`, 일반 후보 2~3개, 확인 필요 없음 | `draft_replies` |
| `normal_quote` | 정상 | 거래처·품목·수량·납기를 다 갖춘 견적 요청 | 없음 | 종료 `awaiting_approval`, 견적서 후보 2~3개, 이 실행의 견적서 초안 저장 | `extract_deal_terms`, `check_required_fields`, `create_quote`, `draft_replies` |
| `missing_info` | 정보 부족 | 납기가 빠진 견적 요청 | 없음 | 종료 `followup_question`, 재질문 후보 2~3개가 모두 납기(`due_date`)를 물음 | `extract_deal_terms`, `check_required_fields`, `draft_followup_replies` |
| `gmail_error` | 도구 실패 | 제목 `[evalsend] 제품 안내 자료 문의`의 일반 문의 → 첫 후보 승인 발송 | 첫 발송에 Gmail `HTTP 503` | 종료 `awaiting_approval`, 일반 후보 2~3개, 승인 결과가 차례로 `failed_unknown`(자동 재시도 없이 안내) → 다시 승인해 `sent` | `draft_replies` |
| `gemini_rate_limit` | 도구 실패 | 일반 문의 | 답장 후보 생성에 Gemini 429(한도) | 종료 `awaiting_approval`, 기본 답장 틀 1개, 확인 필요·`rate_limit` 안내 | `draft_replies` |
| `wrong_tool` | 판단 오류(성찰로 고침) | 필수 항목을 다 갖춘 견적 요청 | 메일 분석을 '일반 문의'로 준비 | `normal_quote`와 같음(성찰이 거래 경로로 고쳐야 완료) | `extract_deal_terms`, `check_required_fields`, `create_quote`, `draft_replies` |
| `hallucination` | 판단 오류(성찰로 고침) | 일반 문의 | 첫 답장 후보에 원문에 없는 '500만원'·'11월 30일' | `normal_general`과 같고, 어느 후보에도 '500만원'·'11월 30일'이 없음 | `draft_replies` |

- 공통 완료 조건: 종료 이유, 후보 개수(기본 2~3개), 후보 종류(`general`/`followup`/`quote`), 확인 필요 표시, 안내 종류가 위 표와 같다. 표에 적힌 추가 조건(재질문 항목·견적서·금지 표현·승인 결과)도 모두 맞아야 완료다. [Claude proposal]
- 판단 오류 두 시나리오는 실제 API 실행에서도 같은 오류가 나도록 오류를 일으키는 응답을 주입하고, 그 뒤 호출(성찰의 원인 분석, 재실행)은 실제 Gemini가 답한다. [Claude proposal]
- 승인 발송 시나리오(`gmail_error`)는 Gmail 연결이 있어야 돈다. 실제 실행에서는 상대방 역할 계정이 시험 계정으로 같은 제목·본문의 메일을 실행마다 한 통씩(반복 수 × 끔/켬) 보내 두고, 실행기가 `--gmail-search`로 시험 계정 Gmail을 검색해(기본 `in:inbox subject:evalsend newer_than:30d`) 받은 메일·같은 제목·본문 포함·앞 실행에 안 쓴 메일만 오래된 순으로 쓴다(메일 ID를 직접 줄 때는 `--gmail-source 메일ID:스레드ID`). 두 번째 승인은 실제로 상대방 역할 계정에 답장을 보낸다. 메일이 모자라면 남은 실행은 건너뛰고 이유를 남긴다. [Request · Claude proposal]

## 4. 판정 기준: 4개 필수 지표 (측정 전에 정함, 2026-11-10)
성찰 끔과 켬을 따로 세고, 판정한 실행(건너뛴 실행 제외)을 분모로 한다. 계산은 실행 기록(`runs`·`run_events`·`reply_candidates`·`quotes`)으로 한다(`app/evaluation/metrics.py`). [Request · Claude proposal]

| 지표 | 정의 | 산정 정보 |
|---|---|---|
| 태스크 완료율 | 3절의 완료 조건을 모두 채운 실행 수 / 판정한 실행 수 | 시나리오별 완료 조건(3절), 완료 건수, 총 시험 건수 |
| 도구 선택 정확도 | 실행에서 부른 도구 집합(`tool_call` 기록)이 정답 도구 조합과 같은 실행 수 / 판정한 실행 수 | 정답 조합(3절). 정답에 없는 도구를 부르면 불필요한 호출, 정답에 있는데 안 부르면 누락으로 세고 둘 다 없어야 적중. 성찰이 같은 도구를 다시 부른 것은 집합이라 한 번으로 본다. 승인 경로의 `send_email`은 그래프 밖이라 세지 않는다 |
| 응답 일관성 점수 | 같은 시나리오·같은 성찰 설정을 반복한 실행들의 모든 쌍에서 ① 사실(후보 본문의 숫자+단위 조각, 견적서 품목·수량·합계) ② 사용자 조건(종료 이유·재질문 항목·확인 필요·안내 종류) ③ 응답 구조(후보 수·종류·`Re:` 제목·견적서 유무)가 같은 비율을 각각 구해 평균(0~1). 전체는 시나리오 점수의 평균 | 반복 횟수(2절, 기본 3번 → 쌍 3개), 비교 항목 ①~③, 반복 2번 미만인 시나리오는 빼고 측정한 시나리오 수를 적음 |
| 평균 재시행 횟수 | (통신·형식 재시도 `call_retries` + 성찰 재실행 `reflection_retries` + 사용자 재승인 발송) 합 / 판정한 실행 수 | 최초 실행(첫 시도·첫 승인)은 세지 않고 그 뒤 추가 실행만 센다. 세 종류를 따로도 적는다 |

- 일관성 점수는 정답 여부가 아니라 같은 입력에 같은 답을 내는지만 본다(틀린 답도 매번 같으면 높다). 정답 여부는 완료율이 본다. [Claude proposal]

## 5. 실행 방법
- 가짜 LLM(키 없음, 메모리 DB, 승인 발송 시나리오는 건너뜀): `uv run python -m app.evaluation.runner --fake --repeat 3 --out <결과.json>`
- 실제 API(로컬, 키 있음, 로컬 서버에서 시험 계정으로 로그인한 뒤): `uv run python -m app.evaluation.runner --real --user-email <시험 계정 이메일> --repeat 3 --gmail-search --export-dir docs/test-records --out <결과.json>`. 시험 사용자는 이메일로 찾는다(`--user-id`도 됨). `--gmail-search` 뒤에 검색어를 주면 기본 검색어 대신 쓴다.
- 출력: 4개 지표의 성찰 끔/켬 표와 시나리오별 표(6절에 붙여넣음), 건너뛴 실행과 이유.
- 테스트(`tests/test_evaluation.py`)가 가짜 LLM·가짜 Gmail로 위 실행기를 돌려 4개 지표 계산과 주입 표시를 확인한다.

## 6. 결과: 성찰 전후 비교 (계획 18·19절에서 채움)
| 지표 | 성찰 끔 | 성찰 켬 |
|---|---|---|
| 태스크 완료율 | 미측정 | 미측정 |
| 도구 선택 정확도 | 미측정 | 미측정 |
| 응답 일관성 점수 | 미측정 | 미측정 |
| 평균 재시행 횟수 | 미측정 | 미측정 |

- 시험 일시·환경(모델, 프롬프트 버전, 반복 횟수, 다른 점): 미측정
- 시나리오별 결과: 미측정

## 7. 초기 버전 기록·수정 버전·사례·한계 (계획 19절에서 채움)
- 초기 버전의 실제 도구 선택·상태 전이·오류·최종 결과: 미측정
- 고친 프롬프트·인자·정책의 버전, 변경 이유, 적용 결과: 미측정
- 대표 성공·실패 사례(피드백 루프 단계별 입력·출력·수정·검증과 실행 기록 연결): 미측정
- 개선되지 않은 부분과 한계: 미측정
- 판정 기준 변경 기록: 없음
