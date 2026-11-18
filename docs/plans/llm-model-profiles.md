# llm-model-profiles 계획

- 목표: 기능마다 LLM 모델·노력치·시간 제한·출력 상한을 하나의 비밀 없는 프로필로 묶고, 서버·개인 PC 실행기·큐·HTTP·프런트 기한과 함께 맞춘다. 이 문서는 **계약과 영향 경계, 무료 모의 검증 준비**만 다룬다. 운영 코드·모델 기본값은 바꾸지 않았다. [Request]
- 관련 Issue: 없음 (R-03, R-09·R-10, R-12·R-13, D-02). [Request]
- 조율함: 해당 없음(이 PR은 문서·무료 검사만). 구현 PR은 공통 기반(`app/llm/`, `app/worker/`, `docs/CONTRACT.md` 6.4) 변경이므로 김민성과 조율한다. [Claude proposal]
- 기계가 읽는 원본: [`llm-model-profiles.contract.json`](llm-model-profiles.contract.json). 표의 값은 이 파일과 같고, 어긋나면 `scripts/check_model_profile_contract.py`가 알려 준다. [Claude proposal]
- 원래 계획: `feat/llm-usage-benchmark`(a24e2d5)의 `docs/plans/llm-quality-and-cost.md` 4절. 같은 PR에서 main에 함께 올린다. 그 계획·측정기는 다시 쓰지 않았다. [Past work: llm-quality-and-cost]
- 분석 기준: main `428139a`. 2번 세션(카탈로그 후보)은 이 계약의 `catalog_candidates`를 소비하고 별도 설정·워커·재시도 체계를 만들지 않는다. [Request]

## 상태: 구현 · 실측 · 미확인

| 구분 | 내용 |
|---|---|
| 구현(준비) | 계약 JSON, 이 문서, 무료 검사기와 테스트 17개. 운영 코드·`.env.example`·README·`CONTRACT.md`는 그대로다. |
| 실측 | 이 작업의 유료 호출 0회. 1번 세션(측정)의 카탈로그 후보 PC 선별 40회(2026-11-18, `catalog_candidates`의 측정 준비값 90초/2048 · Luna medium 30·Sol medium 10)는 모두 completed·시간 초과 0건이고 Sol medium의 `reasoning_effort` 요청도 수락됐다. 질의 10개 선별이라 품질 게이트 통과가 아니며 이 계약의 값을 승인하지 않는다. 기한 표의 "최악" 값은 코드 상수에서 계산한 산술이며 측정이 아니다. |
| 미확인 | 후보 모델의 품질·비용·지연(품질 게이트 미통과), 실제 청구, Render/프록시의 요청 시간 상한, 후보 모델의 `reasoning_effort` API 수락(카탈로그 Sol medium 외), 거래 추출·이미지 전사의 대표 반복. |

## 프로필 키 확정 [Request: 제안 키 · Claude proposal: 코드 대조와 추가]

제안 키 네 개를 기존 코드에 맞춰 그대로 확정했다. 호출 지점은 `docs/CONTRACT.md` 6.4의 설치된 정의 13개(프롬프트 12종)에서 나눴다.

| 키 | 실제 호출 지점 | 실행 방식 |
|---|---|---|
| `default_structured` | `analyze_email` `draft_replies` `draft_followup_replies` `extract_deal_terms` `summarize_thread` `reflect_fix` (`call_structured`) | 서버 저장 키 · PC |
| `trade_extraction` | `extract_trade_terms` `pi_extract` `po_extract` `ci_extract` `ci_standalone_extract` `pl_extract` (`extract_facts`) | 서버 저장 키 · PC |
| `catalog_candidates` | 2번 세션이 정의(아직 없음). 지금은 키와 측정 준비 프로필만 예약 | 서버 저장 키(PC는 설치 정의 뒤) |
| `vision_transcription` | `app/knowledge/extract.py`의 페이지 전사 | 서버 저장 키만(PC는 현재 명시적 미지원) |
| `mail_gate` (추가) | `app/llm/mail_gate.py`(Decisions API). 모델이 코드 상수 `MODEL`이라 `OPENAI_MODEL`로 바뀌지 않는다 | 서버 저장 키 |

- `mail_gate`는 이번에 baseline 고정으로만 기록한다(후보 없음). 임베딩은 effort·출력 상한이 없고 차원이 저장 데이터를 정하므로 이 계약 밖이다. [Claude proposal]
- 새 프롬프트가 생기면 `check_model_profile_contract.py`가 매핑 누락을 알려 준다(어느 기능 키인지 정해야 한다).

## 프로필 계약 [Request: 4개 필드·금지 조건 · Claude proposal: 이름·선택 방식]

프로필 하나 = `model` + `reasoning_effort` + 실행 방식별 `timeout_seconds` / `max_output_tokens` / SDK·서버 재시도 예산 / 기한(`logical_deadline_seconds`는 서버, `queue_deadline_seconds`는 PC) + `status` + `model_source`. 비밀값·키·토큰 필드는 두지 않는다(검사기가 필드 이름과 `sk-` 값을 거부).

| 프로필 | 모델 · 노력치 | 상태 | 비고 |
|---|---|---|---|
| `<기능>.baseline` | `gpt-6-luna` · 기본(요청에 노력치 미전송, 공식 기본 medium) | baseline | 현재 요청 내용을 그대로 보존. 기존 `OPENAI_MODEL`/`KNOWLEDGE_VISION_MODEL` 덮어쓰기는 **이 프로필에만** 적용 |
| `<기능>.luna-medium` | `gpt-6-luna` · medium(고정 모델) | explicit_return | 명시적 복귀 대상. 환경 변수로 모델이 바뀌지 않음 |
| `trade_extraction.sol-medium` | `gpt-6.1-sol` · medium | candidate | 90초/8192는 측정 준비값 |
| `vision_transcription.terra-low` | `gpt-6.1-terra` · low | candidate | 180초/10000. 가림 표시는 품질 부족 근거가 아니며 Terra medium은 제시하지 않음 |
| `catalog_candidates.luna-medium` / `.sol-medium` | Luna·Sol · medium | measurement_prep | 90초/2048은 측정 준비값. `production_available: false` |

- 허용 조합은 위 표뿐이다. `high/xhigh/max`(와 `none/minimal`)는 계약 검사에서 오류다. 일반 구조화에는 Luna만 허용한다. [Request]
- 운영에서 고를 수 있는 상태는 `baseline`·`explicit_return`·`approved`뿐이다. 후보는 자동 승격하지 않는다(`never_auto_promote`). 프로필 선택은 서버 설정(`LLM_PROFILE_<기능>`, 비우면 baseline)이며 사용자별 선택이 아니다. 키·실행 방식은 계속 사용자별이다. [Claude proposal]
- 처리 기록마다 `profile_id`와 해석된 값(모델·노력치·timeout·출력 상한·실행 방식)을 남긴다. 이미 발급된 파일·이전 처리 결과는 설정을 바꿔도 소급해서 바꾸지 않고, 새 시도에만 새 프로필을 쓴다. [Request]

## 현재 기한·한도 지도(main 428139a, 코드 대조 완료)

| 층 | 현재 값 | 위치 |
|---|---|---|
| 서버 LLM 1회 | timeout 20초, SDK 재시도 0, 출력 상한·노력치 미지정 | `app/config.py` `LIMITS`, `app/llm/client.py` |
| 서버 재시도 예산 | network 2회(1·2초 대기) + invalid_output 1회, **전체 기한 없음** | `call_structured` |
| PC 1회 | timeout 20초, 출력 상한 기본 2048(1~32768, PC가 강제), 모델은 PC `.env` | `app/worker/pc.py` |
| 큐 전체 기한 | 120초(adapter·service·protocol 세 곳에 따로 있음) | `adapter.py` `deadline = started + 120`, `service.py`, `protocol.py` |
| claim/임대/heartbeat/오프라인 | claim ≤25초, 임대 30초, heartbeat 10초 간격, 45초 무응답 | `service.py`, CONTRACT 6.4 |
| PC 최소 잔여 기한 | 남은 시간 ≤ 20초면 `expired`(상수 20이 LLM timeout과 같은 값) | `pc.py` `execute` |
| 성공 응답 `duration_ms` | 0~30000 | `protocol.py` |
| 비전 | timeout 180초, SDK 재시도 3(최초 포함 최대 4번), 출력 10000, 1시간 임대 | `app/knowledge/extract.py`, `repository.py` |
| 프런트 | `apiFetch`는 `signal`만 전달. 요청 기한 없음 | `frontend/src/api.js`, `pages/PIPage.jsx` 등 |
| HTTP/프록시(Render) | **미확인** | 구현 전 공식 문서로 확인 |

## 영향 경계와 발견 사항

1. **`OPENAI_MODEL` 하나로 끝나지 않는다.** 모델은 서버(`model_name`), PC `.env`, 비전 설정(`KNOWLEDGE_VISION_MODEL`/처리 스냅샷), `mail_gate` 상수 네 곳이 따로 정한다. PC는 서버 `requested_model`과 PC 목록이 같아야만 받는다(`unsupported_version`). [코드 확인]
2. **실행 방식마다 출력 상한이 다르다.** 서버 저장 키는 상한이 없고 PC는 2048이다. 같은 기능이 다른 프로필처럼 동작하므로 계약은 실행 방식별 값을 가진다. 출력 상한에는 추론 토큰이 포함되므로 낮은 상한은 JSON 잘림(`incomplete`)으로 나타날 수 있다. [코드 확인 · Past work: 계획 2절]
3. **시간 초과가 지금은 같은 모델 재시도를 쓴다.** `classify_error`가 timeout을 `network`로 분류하고 최대 2회 재시도한다(서버 최악 4회 호출·83초). 계획 4절은 "timeout은 자동 재요청하지 않고 입력 보존"을 우선한다. 그래서 baseline은 현재 동작을 보존하고 **새 프로필에서만** timeout을 재시도하지 않는다. 다른 모델 자동 호출은 어느 경우에도 없다. [코드 확인 · Request]
4. **서버 저장 키 경로에는 논리 기한이 없다.** 동기 HTTP 요청이 재시도 포함 `4 × timeout` 이상 길어질 수 있고 프런트는 기한이 없다. timeout 90초 후보를 그대로 넣으면 요청 최악이 6분을 넘는다. 계약은 서버 경로에도 `logical_deadline_seconds`를 두고 시도 timeout을 `min(timeout, 남은 기한)`으로 줄이도록 한다. [코드 확인 · Claude proposal]
5. **PC 경로는 90초 후보를 재시도 없이 겨우 받는다.** 큐 기한 상한 120초(세 곳 고정)와 claim 여유 30초 때문에 `trade_extraction.sol-medium`은 120초 = 상한으로 **여유 0·재시도 0**이다. 이보다 길게 하려면 상한 세 곳과 PC 잔여 기한 상수 20을 프로필 값으로 연동해야 한다. `duration_ms` 상한 30000도 90초 호출의 실제 시간을 잘라 진단 정보를 잃는다. (`check_model_profile_contract.py`가 산출) [계산]
6. **서버는 수치를 PC로 보내지 못한다**(CONTRACT: 토큰/URL/헤더 필드 불허, 모델은 PC가 강제). 따라서 프로필은 서버가 값을 보내는 방식이 아니라 **PC가 설치된 프로필 표(해시 교환)로 해석**하는 방식이어야 한다. `JobRequest`·`Capabilities`가 `extra=forbid`라 현재 PC 프로그램과 호환되지 않으므로 프로토콜 버전 협상이 필요하다. 구현 단계에서 정할 사항이며 추천은 "v2 협상 + v1 PC는 baseline만"이다. [코드 확인 · Claude proposal]
7. **비전은 페이지마다 최악 720초**(4번 × 180초, SDK 백오프 제외)이고 1시간 임대 안에는 최악 5페이지다. 재시도 정책을 바꾸면 처리 시간과 과금이 함께 바뀐다. PC 실행은 비전을 명시적으로 지원하지 않는다. [계산 · 코드 확인]
8. **`ModelProfile`에 필드를 추가하면 안 된다.** `fingerprint`가 `model_dump()` 해시이고 임베딩 청크의 `profile_id`로 쓰여, 필드를 추가하면 기존 청크와 지문이 달라진다. 비전 프로필 메타(`profile_id`, 노력치, timeout, 출력 상한)는 처리 스냅샷의 별도 선택 필드로 남긴다. 저장 형식의 실제 호환은 구현 전 확인한다. [코드 확인 · 미확인]
9. **오류 종류가 부족하다.** `LLMResult.error_kind`는 5종이다. 계획은 시간 초과·JSON 미완료·근거 오류·권한/잔액 오류의 구분을 요구한다. 공통 계약(`CONTRACT.md`)을 깨지 않도록 기존 5종은 두고 `error_detail`(`timeout`, `incomplete_output`, `grounding_failed`, `access_denied`)을 **추가 필드**로 둔다. [Claude proposal]
10. **사용량이 기록되지 않는다.** `llm_call` 이벤트는 시간·시도만 남긴다. 비용 누락을 막으려면 프로필 호출마다 입력/캐시/출력/추론 토큰과 시도 수(실패·재시도 포함)를 `work_unit_id`로 묶어 남겨야 한다. 사용량을 알 수 없는 시도는 0이 아니라 미상으로 센다. [Past work: 계획 2절 기록 계약]
11. 파라미터 대응: `langchain-openai==1.7.4`의 `ChatOpenAI`는 `reasoning_effort`를 Responses의 `reasoning.effort`로, `max_tokens`를 `max_output_tokens`로 보낸다(설치 소스 확인). 비전은 `OpenAI().responses.parse(reasoning=...)`를 쓴다. 후보 모델이 이 값을 실제로 받는지는 **미확인**이다. [소스 확인]

## 실패·재시도·복귀 규칙(실행 가능한 기준: `route_failure`, `accept_result`) [Request]

| 상황 | 동작 |
|---|---|
| 시간 초과(새 프로필) | 입력·원문 보존, 같은 프로필 자동 재요청 없음, 다른 모델 호출 없음. 사용자의 명시적 재시도만 새 시도 |
| `incomplete_output`/`grounding_failed`/`invalid_output`/`rate_limit`/`access_denied` | 입력 보존 후 정지. 기존 예산이 남은 `network`·`invalid_output`만 같은 프로필 새 attempt(baseline 동작 유지) |
| 다른 프로필(기존 Luna 포함) | 사용자의 명시적 선택으로만. 새 attempt·새 revision·새 검토로 보고 **이전 시도 비용과 합산** |
| 지연 결과 | `work_unit_id`·`attempt_id`·`revision`·`profile_id`가 현재와 모두 같고 취소/만료가 아닐 때만 적용(PC 큐의 attempt 조건부 갱신을 일반화) |
| 외부 효과 | 승인·발급·메일 발송은 어떤 재시도·복귀로도 재생하지 않는다. 단가 검증·문서 승인·소유권/키 격리는 그대로 |
| 복귀 | `luna-medium` 프로필의 명시적 선택. 복귀 이유·시각·프로필 ID를 남기고 키는 파일·로그·Git에 복사하지 않는다. 기존 Luna 결과·보고서는 보존 |

기존 PC 큐의 attempt 조건부 갱신·지연 결과 거부는 `tests/test_worker_queue.py`·`tests/test_worker_execution.py`가 이미 다룬다. 이 계약은 같은 원칙을 서버 저장 키·비전·카탈로그 후보까지 넓힌다.

## 2번 세션(`catalog_candidates`)이 소비하는 방법 [Request]

- 이 계약이 소유: 프로필 키·모델·노력치·timeout·출력 상한, 선택 설정, 호출 어댑터와 PC·서버 기한, 오류·사용량 기록.
- 2번이 소유: 조회 범위, 실제 ID·회원/소유권·카탈로그 버전 검증, 후보 API/UI, 행별 최종 선택. 이 작업은 후보 API/UI·SKU 회원 검색을 만들지 않았다.
- 2번이 **지금** 해도 되는 것: `catalog_candidates` 키로 프로필을 요청하는 어댑터 경계(인터페이스)와 가짜 응답 모의 검증. 호출 형태는 아래 제안을 쓴다. 실제 통합은 프로필 계약 병합과 품질 게이트 뒤다.
- 2번이 정의할 것: 설치 프롬프트·스키마(`prompt_ids`를 채운 뒤 PC 지원), `request_revision`(사용자·카탈로그 버전·질의 revision), 호출 한도/캐시.
- 프로필이 `production_available: false`인 동안 호출은 **미사용 상태로 실패**해야 하며 Luna 기본으로 조용히 대체하지 않는다. 입력마다 호출하지 않고 명시적 "AI 후보 찾기" 때만 호출한다.

제안 형태(미구현): `call_profiled(feature, prompt, schema, variables, *, work_unit_id, revision) -> ProfiledResult(ok, value, error_kind, error_detail, profile_id, attempt_id, revision, usage)`. `ProfiledResult`는 기존 `LLMResult`를 감싸며 모델을 직접 고르는 인자를 받지 않는다. [Claude proposal]

## 하위 작업 개요(구현은 품질 게이트 통과 뒤)

모든 하위 작업의 공통 선행 조건: 계획 2절의 대표 자료 작업별 10건 이상·조건당 3회, 실제 마스킹/오류·권한/버전/선택·복귀 회귀가 통과한 근거. **현재 전체 통과 설정은 없다.** [Request]

## 1. 계약 확정과 무료 검증 (이 문서)
- 할 일: 키·프로필 필드·허용 조합·기한 산식·실패 규칙을 정하고 현재 코드와 대조한다.
- 완료 기준: 계약 JSON 검사·코드 baseline 대조·기한 산식·실패 규칙 테스트 통과, 미확인 목록. (초안 완료, 병합 전)
- 영향받는 상태·도구·노드: 없음(문서·검사 스크립트·테스트만).
- 섞지 않을 것: 운영 모델 변경, 유료 호출, 후보 API/UI.
- 선행 작업: 없음.
- 하는 사람: Claude.

## 2. 서버 프로필 해석기와 호출 경로
- 할 일: 프로필 표를 읽는 설정, `call_structured`/`ChatOpenAI`에 모델·노력치·timeout·출력 상한 적용, 서버 경로 `logical_deadline_seconds`, 처리별 `profile_id` 기록.
- 완료 기준: baseline 선택 시 현재와 같은 요청, 명시 복귀 후 동일 실패 자료 재시험, 후보는 운영 선택 시 거부.
- 영향받는 상태·도구·노드: `app/llm/client.py`, `app/config.py`, `.env.example`, `docs/CONTRACT.md` LLM 호출·환경변수 절.
- 섞지 않을 것: 모델 기본값 변경, 자동 승격.
- 선행 작업: 1과 품질 게이트.
- 하는 사람: Codex.

## 3. PC 프로토콜·실행기·큐 기한
- 할 일: 프로필 해시 교환(버전 협상), 프로필별 큐 기한·잔여 기한·`duration_ms` 상한 연동, PC 출력 상한/모델 일치 검사 유지.
- 완료 기준: 모델/스키마/프로필 불일치는 `unsupported_version`, 기한 부족은 호출 전 거부, 지연 결과 거부, 기존 PC 시험 통과.
- 영향받는 상태·도구·노드: `app/worker/*`, `docs/CONTRACT.md` 6.4, README PC 실행 절.
- 섞지 않을 것: 서버가 PC에 수치·URL·헤더 전달.
- 선행 작업: 2.
- 하는 사람: Codex.

## 4. 비전 프로필과 기존 문서 보존
- 할 일: 비전 프로필 적용, 처리 스냅샷의 별도 메타, 명시적 재처리만 새 프로필 적용.
- 완료 기준: 기존 문서·청크 불변, 새 문서만 후보 프로필, 모델 변경 뒤 진행 중 시도는 섞지 않음.
- 영향받는 상태·도구·노드: `app/knowledge/extract.py`·`router.py`·스냅샷.
- 섞지 않을 것: `ModelProfile` 필드 추가, SDK 재시도 정책의 암묵적 변경.
- 선행 작업: 2.
- 하는 사람: Codex.

## 5. 오류 구분·사용량·복귀 기록
- 할 일: `error_detail`, 호출별 사용량·시도 기록, 복귀 이유·시각·프로필 ID 기록, 프런트 대기·취소 안내.
- 완료 기준: 시간 초과·미완료·근거 오류·권한/잔액 오류가 화면·기록에서 구분, 미상 사용량은 미상으로 집계, 키 미기록.
- 영향받는 상태·도구·노드: `app/llm/client.py`, `app/runlog/`, 프런트 오류 안내.
- 섞지 않을 것: 외부 효과 재실행.
- 선행 작업: 2.
- 하는 사람: Codex.

## 무료 검증 실행법

```powershell
# 레포 루트에서(읽기 전용, API·키·DB 불필요)
python .\scripts\check_model_profile_contract.py
python -m pytest tests/test_model_profile_contract.py --noconftest -p no:cacheprovider -q
```

검사기는 계약 파일과 현재 소스의 baseline 값을 대조하므로 코드가 바뀌면 어긋난 항목을 알려 준다. 후보 값은 이 검사로 승인되지 않는다.
