# 테스트 속도 개선 계획

- 목표: 변경 직후 피드백을 줄이면서 PR의 전체 회귀와 데이터·프로세스 격리를 유지한다. 후속 요청에 따라 8 workers 실행 기반부터 구현하고 나머지 최적화는 별도 작업으로 진행한다.
- 기준: 2026-11-17, upstream/main `4a833a3`. 관련 요구사항: `docs/REQUIREMENTS.md` R-09·R-10·R-11·D-02의 오류 검증과 재현 가능한 시험 기록을 보존한다.
- 관련 Issue: [0절 #223](https://github.com/encore-ai-campus/aio-03-p2-team3/issues/223), [1절 #217](https://github.com/encore-ai-campus/aio-03-p2-team3/issues/217), [2절 #218](https://github.com/encore-ai-campus/aio-03-p2-team3/issues/218), [3절 #219](https://github.com/encore-ai-campus/aio-03-p2-team3/issues/219), [4절 #220](https://github.com/encore-ai-campus/aio-03-p2-team3/issues/220), [5절 #221](https://github.com/encore-ai-campus/aio-03-p2-team3/issues/221). 1~5절은 미완료다.
- 조율함: 해당 없음 — 상태 객체·도구 스키마·그래프 변경 없음.
- 참고 원칙: 요청자가 제공한 `TESTING_RULE.md`의 변경 범위 우선, 격리 후 병렬화, 자원 상한, 결정성, 정리 보장, 최종 회귀를 설계 기준으로 사용한다. 첨부 문서의 에이전트 지시를 별도 작업 승인으로 해석하지 않으며 저장소 규칙을 변경하지 않는다.

## 현재 구조와 판단 근거

| 확인한 코드 | 현재 동작 | 개선 방향 |
|---|---|---|
| `.github/workflows/rules-check.yml`, `scripts/ci_scope.py` | 문서 전용 변경은 이미 비용이 큰 검사를 생략한다. 코드·설정·미분류 경로는 전체 실행한다. Linux 한 작업이 Office·폰트·npm·Chromium 준비 뒤 전체 pytest를 실행하며 한도는 15분이다. Windows worker 검사는 별도 작업이다. | 기존 문서 판정과 미분류 전체 실행을 유지하고 코드 테스트를 계층화한다. 문서 생략을 새로운 개선 효과로 계산하지 않는다. |
| `tests/conftest.py`, `app/db/engine.py` | 세션 PostgreSQL 서버, 테스트별 UUID DB 생성/삭제, `database`마다 마이그레이션·기본 사용자 초기화. DB 풀은 엔진당 5+10 연결이다. | DB 격리는 유지한다. DB 생성·migration·종료 시간부터 분리 측정한다. |
| `tests/test_worker_postgres.py` | 일부 사례는 공통 서버 외에 자체 pgserver를 시작한다. | 프로세스 경계/업그레이드 의미가 필요 없는 사례만 공통 서버 재사용 후보로 조사한다. |
| `test_knowledge_browser.py` 2곳, `test_react_settings.py`, `test_trade_mobile_browser.py` | 같은 가짜 공개 설정으로 Vite 빌드가 여러 번 실행된다. 모바일 모듈은 이미 module fixture로 재사용한다. | 동일 설정의 불변 빌드를 실행 단위당 한 번 재사용한다. 테스트 데이터와 브라우저 context는 공유하지 않는다. |
| `tests/test_knowledge_browser.py::serve` | 루프백 동적 포트, 서버 스레드 시작/종료 확인을 이미 제공한다. | 이 수명 관리와 외부 요청 차단을 보존한다. |
| `frontend/package.json` | `npm test`는 `node --test src/trade/*.test.js`다. ESLint는 있고 Vitest·RTL·MSW는 없다. TypeScript 프로젝트가 아니다. | 기존 helper 검사를 먼저 활용한다. 도구 교체를 속도 개선의 선행 조건으로 만들지 않는다. |
| `pyproject.toml`, `tests/parallel.py` | pytest-xdist 3.8.0과 parallel/serial 분류를 추가했다. 기본 pytest는 모든 테스트를 직렬 실행하며 CI는 독립 집합을 8 workers로 실행한다. Ruff는 없다. | 기본 분류 외의 상세 자원/영향 매핑과 부하 측정은 1·5절에서 계속한다. |

위 항목은 정적 확인이며 시간 비중을 증명하지 않는다. Windows 최초 `uv run pytest --collect-only -q`는 **1113개, 44.63초**였다. 설치 직후 단일 관측이며 일반적인 수집 시간이나 실행 시간으로 일반화하지 않는다. 전체 실행 시간·상위 병목·개선율은 아래 검증 기록과 후속 1절의 반복 측정으로 판단한다.

최신 main을 만든 PR #215의 head `deba6188`에 대한 [CI tests 로그](https://github.com/encore-ai-campus/aio-03-p2-team3/actions/runs/44008904741/job/133790907636)를 직접 확인했다. 2026-11-17 한 번의 Linux 실행이며 로컬 Windows나 반복 중앙값과 비교하지 않는다.

| CI 관측 | 값 | 해석 |
|---|---|---|
| 전체 pytest | 1111 passed·2 skipped, 424.18초 | 준비 비용만 줄여도 테스트 본체 7분은 남는다. setup/call별 측정이 필요하다. |
| Office 설치 단계 시작 → 다음 단계 시작 | 약 45.07초 | Office가 필요 없는 빠른 계층에서 준비를 생략할 근거다. |
| npm/Chromium 준비 단계 시작 → pytest 단계 시작 | 약 20.30초 | 한 단계의 합산값이며 npm과 Chromium 각각의 비중은 미측정이다. |

단계 사이 간격에는 작업 전환 비용이 포함될 수 있다. 최대 메모리·반복 분산·Windows 전체 실행과 CI의 수집/setup/call/teardown 비중은 아직 확정하지 않았다.

## 적용 순서와 검증 계층

0. 사용자 요청에 따라 8 workers 실행 기반과 DB 표식/실패 정리부터 적용한다(0절).
1. 실행 대상·네트워크·정리 안전성과 상세 기준 시간을 확정한다(1절).
2. 중복 빌드를 제거한다(2절). 이후 빠른 실패를 먼저 알리는 CI 계층을 구성한다(3절).
3. 측정상 DB 초기화가 유의미한 병목인 경우에만 격리를 유지하는 최적화를 한다(4절).
4. 마지막으로 8 workers의 반복 측정과 자원 예산을 검증한다(5절). 모든 단계에서 직렬 실행으로 복귀할 수 있어야 한다.

| 계층 | 이 레포 적용안 | 초기 자원 상한 |
|---|---|---|
| L0 | 규칙 검사, frontend ESLint, 공개 환경 검사. Python lint/타입 도구 추가는 별도 필요성 판단 | DB·브라우저 없음 |
| L1 | DB/서버가 없는 Python 계산·검증과 기존 Node helper 검사 | 검토한 Python 집합 8 workers |
| L2 | FastAPI 직접 호출·테스트별 UUID PostgreSQL DB·가짜 외부 서비스 | 검토한 집합 8 workers, 공유 가변 DB 없음 |
| L3 | 컴포넌트 동작 검사가 필요한 변경에서만 Vitest/RTL/MSW 도입 검토 | 신규 도입 시 2, 현재 구현 아님 |
| L4 | SQL/마이그레이션/권한 경계 회귀. 가짜 JWT API 소유권 검사와 실제 Supabase RLS 검사를 구분 | 초기화·migration 1 |
| L5 | 기존 Playwright Python 브라우저 완주, 실제 FastAPI·가짜 외부 공급자 | 1 |
| L6 | 코드 PR의 모든 기존 테스트를 계층별 합집합으로 검증하고 필수 `tests`로 집계 | 작업별 전용 DB/출력 사용 |

변경 중에는 L0 → L1 → 관련 L2~L5를 실행한다. PR 최종 단계에서는 코드 변경의 전체 회귀를 유지한다. 선택 실행은 반복 개발 비용을 줄이는 용도다. 문서 전용 예외는 기존 CI 판정을 따른다. 현재 AGENTS.md의 로컬 전체 `uv run pytest` 의무도 유지하며, 이를 선택 실행으로 대체하려면 별도 규칙 변경 요청이 필요하다.

현재 도구로 바로 사용할 선택 실행 예시는 다음과 같다. 변경한 기능에 맞는 항목만 먼저 실행하고, 이것만으로 PR 검증 완료로 표시하지 않는다.

```text
uv run pytest tests/test_trade_pricing.py -q -x
uv run pytest tests/test_pi_api.py -q -x
uv run pytest tests/test_parallel.py -n 0 -q
uv run pytest -n 8 -m parallel
uv run pytest -n 0 -m serial --ignore=tests/test_parallel.py
npm test --prefix frontend
npm run lint --prefix frontend
uv run pytest --durations=20 --durations-min=0.5 -ra
```

`-x`는 첫 실패 중단이다. 정책 검사 → 8 workers 독립 집합 → 순차 집합을 모두 통과해야 CI 전체 회귀가 완료된다. 각 집합은 겹치지 않으며 미분류 모듈은 항상 serial이다. 정책 검사의 내부 8-worker 회귀가 다른 workers와 중첩되지 않도록 정책 파일은 먼저 직렬로 검사하고 마지막 단계에서는 제외한다. 기본 `uv run pytest`도 전체를 그대로 실행한다. 병렬 DB 검사에는 README의 일회용 `aio_test` DB와 표식이 필요하다.

## 0. 8 workers 실행 기반과 자원 격리 (완료)

- 할 일: 사용자 요청에 따라 2 workers 제안을 8 workers 방식으로 변경하고 실행 기반을 먼저 구현한다. pytest-xdist를 고정하고 검토한 모듈은 parallel, 브라우저/Office/실제 프로세스/미분류는 serial로 분리한다. CI에서 정책 검사 후 8-worker 단계와 직렬 단계를 실행한다.
- 완료 기준: 실제 8개 worker의 분배와 순차 집합 미실행/별도 실행, auto·9 workers·잘못된 집합 거부, DB 표식 거부/허용 검사 및 전체 회귀 통과. 모든 기존 테스트를 유지한다. 실제 시간은 기록하되 반복 중앙값/최대 메모리 검증을 완료했다고 표현하지 않는다.
- 영향받는 상태·도구·노드: 테스트 plugin/fixture·pytest 의존성·CI·README. 제품 상태·도구·그래프 변경 없음.
- 섞지 않을 것: 빌드 재사용·DB template 최적화·기존 assertion 삭제·외부 API·운영 환경 변경.
- 선행 작업: 없음 — 사용자 후속 요청으로 앞당긴 실행 기반. 원래 1~5절 전체 완료를 뜻하지 않는다.
- 하는 사람: Codex.

`tests/parallel.py`의 명시적 모듈 목록만 병렬화한다. 테스트별 UUID DB와 임시 파일·가짜 공급자를 유지하며 같은 DB의 기존 migration 잠금도 유지한다. 외부 URL은 `aio_test` DB와 `aio pytest disposable` DB 주석을 확인해야 하며, 표식 없는 대상은 CREATE DATABASE 이전에 거부한다. 로컬 직렬 실행은 기존 임베디드 서버를 사용하고, 병렬 실행은 준비된 전용 서버 하나를 공유하되 데이터베이스는 테스트마다 분리한다. fixture setup/실행 예외에도 엔진과 DB를 finally에서 정리한다. worker 자동 증설·충돌 후 자동 재시작은 사용하지 않는다.

처음 시도한 동적 xdist_group 배분은 현재 pytest/xdist 조합에서 실제 분배 회귀를 통과하지 못했다. 그룹에 의존하는 구현은 제거하고 별도 pytest 단계로 순차 실행을 보장했다. 전체 Windows 회귀와 8 workers의 반복 중앙값·엄밀한 최대 메모리 측정은 별도 확인이다.

Windows PowerShell에서 로컬 테스트 DB를 새로 준비하는 예시다. Docker·의존성·Office·Chromium 준비가 필요하다. 지정 포트 충돌을 피하기 위해 Docker가 loopback 포트를 할당하고, 고유 이름으로 이번 컨테이너만 정리한다. DB URL/암호는 로컬 일회용 값이며 운영 설정을 복사하지 않는다.

```powershell
$testDbName = 'aio-pytest-' + [guid]::NewGuid().ToString('N')
docker run --rm -d --name $testDbName -p 127.0.0.1::5432 -e POSTGRES_PASSWORD=pytest-local-only -e POSTGRES_DB=aio_test pgvector/pgvector:0.8.7-pg16@sha256:484e838076e04939d27d3e176e91c86eea96236126023be8d3059761122e579f
docker exec $testDbName pg_isready -U postgres
# accepting connections가 나올 때까지 기다린 뒤, 이번에 만든 컨테이너에만 표식을 둔다.
docker exec $testDbName psql -U postgres -d aio_test -c "COMMENT ON DATABASE aio_test IS 'aio pytest disposable'"
$testPort = (docker port $testDbName 5432).Split(':')[-1]
$previousTestDatabaseUrl = $env:TEST_DATABASE_URL
$env:TEST_DATABASE_URL = "postgresql://postgres:pytest-local-only@127.0.0.1:${testPort}/aio_test"
try {
    uv run pytest tests/test_parallel.py -n 0 -q
    if ($LASTEXITCODE -ne 0) { throw '정책 검사 실패' }
    uv run pytest -n 8 -m parallel
    if ($LASTEXITCODE -ne 0) { throw '병렬 검사 실패' }
    uv run pytest -n 0 -m serial --ignore=tests/test_parallel.py
    if ($LASTEXITCODE -ne 0) { throw '순차 검사 실패' }
} finally {
    if ($null -eq $previousTestDatabaseUrl) {
        Remove-Item Env:TEST_DATABASE_URL -ErrorAction SilentlyContinue
    } else {
        $env:TEST_DATABASE_URL = $previousTestDatabaseUrl
    }
    docker stop $testDbName
}
```

병렬/순차 집합의 합집합과 정책 파일은 전체 수집 집합을 모두 포함한다. 8 workers의 Python 프로세스에 DB·브라우저 자식 프로세스 메모리가 더해지므로 로컬/CI 메모리를 따로 확인한다. 이 실행 기반은 브라우저 빌드 재사용이나 DB template 최적화를 포함하지 않는다.

검증: 기본 전체 pytest 1116 passed·2 skipped/760.68초. 정책 5건 → 8-worker 독립 1000건 → 순차 113건의 중복 없는 합집합 1118건을 통과했고 파이프라인 벽시계 시간은 519.76초였다. 한 번의 관측이며 반복 중앙값/단계별 최대 RSS는 미확정이다. 환경·메모리 상한·정리 확인과 오류 조정은 [8-worker 검증 기록](../test-records/20261117_test_workers.md)에 둔다.

## 1. 안전한 분류와 기준 시간 확정
- 할 일: 전체 node ID를 `unit`·`db`·`render`·`browser`·`process`·`migration`의 주 실행 계층에 빠짐없이 배정한다. 한 파일에 여러 자원이 섞이면 함수 단위로 분류하고, 테스트 간 import와 fixture의 전이 의존성까지 확인한다. 테스트별 자원 목록·변경 경로 매핑·실행 방법·측정값을 이 계획의 해당 절에 남긴다. 먼저 격리/네트워크/정리 가드를 마련하고 직렬 기준을 측정한다.
- 완료 기준: 전체 수집 집합과 분류 합집합이 일치하고 누락·중복 실행 정책이 검증된다. 불명확한 경로는 전체 실행한다. 폐기 가능한 DB만 허용하고 외부 네트워크 차단·loopback 가짜 서버 예외·실패 시 정리 검증이 통과한다. 동일 커밋·장비·의존성에서 최초 준비/수집/setup/call/teardown 시간을 구분하고 최소 3회 정상 실행의 중앙값과 프로세스 트리 최대 메모리, skip 사유를 기록한다.
- 영향받는 상태·도구·노드: 테스트 설정·fixture·선택 집합과 실행 기록. 제품 상태·도구·그래프 노드 변경 없음.
- 섞지 않을 것: 0절 실행 기반의 무관한 재설계, 가변 DB 공유, 운영/개발 DB 연결, 기존 assertion 제거, 무조건적인 skip 추가.
- 선행 작업: 0절 구현 PR 병합.
- 하는 사람: Codex.

안전 가드의 구체 조건:

- `TEST_DATABASE_URL`은 현재 지정값을 그대로 신뢰한다. 향후 전용 테스트 명시값과 테스트 서버 식별 검증을 함께 요구하고, 공유 환경/불명확한 대상이면 CREATE/DROP 이전에 실패시킨다. loopback 주소만으로 안전하다고 판단하지 않는다. URL·자격증명은 로그에 남기지 않는다.
- 현재 LLM 키 비우기는 전체 네트워크 차단을 보장하지 않는다. Python 외부 요청과 브라우저 외부 요청을 각각 차단하고, 해당 테스트가 소유한 루프백 가짜 HTTP/HTTPS 서버만 예외로 둔다. PostgreSQL 통신은 별도 허용 목록으로 관리한다.
- DB 엔진 종료 → DB 삭제 → 세션 서버 종료를 실패 경로에서도 보장한다. fixture setup 중 예외도 정리 대상이다. 프로세스는 생성 핸들/PID로만 종료한다. 기존 실행 중인 개발 서버·Office 등 다른 작업의 프로세스는 종료하지 않는다.
- 시간/재시도 규칙은 주입 가능한 시계·대기 함수로 검사한다. 실제 HTTPS·프로세스 기한 회귀와 경합 검사는 남기고 운영 타임아웃을 단축하지 않는다.
- 로케일/인코딩도 결정성 점검에 포함한다. 이번 Windows 확인에서 부모에만 `PYTHONUTF8=1`이 적용되고 렌더러 자식의 환경 허용 목록에서 제외되어, 자식이 쓴 CP949 manifest를 부모가 UTF-8로 읽는 `UnicodeDecodeError`를 재현했다. 기본 환경의 동일 합성 PDF 변환은 통과했다. 제품 렌더러 수정은 별도 요청 범위이며, 이 계획에서 성공으로 숨기거나 해당 검사를 삭제하지 않는다.

## 2. 브라우저용 프론트 빌드 재사용
- 할 일: 1절의 분류와 실행 기록을 읽는다. 동일 가짜 Supabase URL/공개 키/빌드 옵션을 사용하는 브라우저 테스트를 공통 session 범위 불변 빌드 fixture로 연결한다. 임시 출력 디렉터리를 사용하고 명시적 Windows npm 실행 방식을 유지한다. 설정 조합이 다르면 별도 빌드로 분리한다.
- 완료 기준: 직렬 브라우저 실행에서 같은 설정의 Vite 빌드 호출이 1회이며 기존 모든 브라우저 사례·다운로드 해시·409 입력 보존 검증이 통과한다. 각 테스트는 독립 DB·앱·브라우저 context·Storage를 사용한다. 오류 종료 시 서버/context가 정리되고 외부 요청이 차단된다. 빌드 횟수와 시간을 전후 비교한다.
- 영향받는 상태·도구·노드: `tests/conftest.py` 및 기존 브라우저 테스트의 빌드 fixture. 제품 상태·도구·노드 없음.
- 섞지 않을 것: UI 변경, 브라우저 사례 삭제, 공유 `frontend/dist` 쓰기, 실제 키를 사용한 빌드, worker 증설.
- 선행 작업: 1절.
- 하는 사람: Codex.

session fixture도 xdist에서는 프로세스마다 실행될 수 있다. 5절에서 병렬화할 때 빌드 1회를 자동 보장한다고 가정하지 않는다. 브라우저는 초기 직렬로 유지하며, CI 간 아티팩트 재사용을 추가한다면 커밋·lockfile·가짜 공개 설정이 같은 결과만 전달한다.

## 3. 빠른 실패와 CI 준비 비용 분리
- 할 일: 1절의 분류/변경 매핑과 2절의 빌드를 읽고 CI를 빠른 검사 → DB 회귀·렌더/브라우저 회귀로 분리한다. Windows worker 작업과 독립 `pr-check`를 유지한다. uv/npm/Playwright 다운로드 캐시는 lockfile·OS·도구 버전에 맞춰 사용하고 DB 데이터/실제 키/사용자 파일은 캐시하지 않는다. Office·폰트·Chromium은 해당 계층에만 준비한다.
- 완료 기준: L0/L1 실패 시 고비용 후속 작업이 시작되지 않는다. 코드 PR의 분류 합집합이 전체 수집 집합을 포함하고, `tests` 집계는 필요한 작업 실패·취소·예상 밖 skip·분류 실패를 성공으로 처리하지 않는다. 문서 변경·보고서 변경·코드 변경·미분류 경로·이름 변경·비교 실패의 정책이 검증된다. 캐시 miss도 통과하며 전체 소요 시간과 Actions 총 실행 시간을 함께 보고한다.
- 영향받는 상태·도구·노드: `.github/workflows/rules-check.yml`, `scripts/ci_scope.py`, 관련 CI 검사. 필수 `rules-check`·`tests`·`pr-check` 이름 유지. 제품 상태·도구·노드 없음.
- 섞지 않을 것: 필수 검사/Ruleset 완화, 코드 PR을 관련 테스트만으로 최종 통과, 실패 숨기기, 운영 배포 변경.
- 선행 작업: 2절 — 공통 fixture와 분류 기준을 확정한 뒤 실행.
- 하는 사람: Codex.

변경 중 선택 예: 무역 순수 계산은 해당 `test_trade_pricing.py`의 node ID부터, 지식 문서 렌더러는 실제 형식별 렌더 검사부터 실행한다. 공통 DB 모델·설정·인증·conftest·의존성·CI·이동/삭제 또는 매핑 미확인 변경은 전체 영향으로 취급한다. 파일명 prefix만으로 안전한 테스트 집합을 추정하지 않는다. 선택기가 고장 나면 전체 실행한다.

## 4. DB 초기화 비용의 조건부 개선
- 할 일: 1절의 setup/teardown 측정에서 DB 생성/migration이 병목인지 확인한다. 우선 불필요한 자체 서버 시작을 공통 세션 서버+테스트별 DB로 바꿀 수 있는지 조사한다. 그래도 병목이면 일반 CRUD 테스트에 한해 같은 세션에서 준비한 읽기 전용 migration 완료 template DB 복제를 비교한다. 템플릿 연결을 닫고 테스트마다 UUID DB를 만들어 지우는 격리는 유지한다.
- 완료 기준: 이득이 없거나 복제 안전성을 증명하지 못하면 현 구조를 유지하고 측정 결과로 결론낸다. 적용 시 사용자·시퀀스·pgvector·제약·FK·트랜잭션·서로 다른 연결의 쓰기와 동시 실행이 이전과 동일하다. migration/upgrade/복사/스키마 경계 검사는 빈 DB에서 실제 migration을 실행한다. setup 실패·assertion 실패에도 DB/연결/서버가 정리되고 속도와 메모리의 전후 비교가 남는다.
- 영향받는 상태·도구·노드: 테스트 DB fixture와 자체 pgserver 테스트. 운영 DB 스키마·제품 상태·도구·노드 변경 없음.
- 섞지 않을 것: SQLite 대체, 테스트끼리 가변 DB 공유, 전체를 세션 DB 하나로 통합, 서로 다른 연결을 포함한 시험을 단순 rollback으로 대체, migration 회귀 삭제.
- 선행 작업: 3절 — 동일 fixture/분류/CI 변경의 충돌을 피한다.
- 하는 사람: Codex.

## 5. 8 workers 부하 검증과 최적화
- 할 일: 0~4절의 결과를 읽고 같은 집합의 직렬과 8 workers를 비교한다. DB는 독립 UUID DB를 유지하고 같은 DB migration·실제 프로세스·브라우저/Office는 순차 경계를 유지한다. 여러 CI 작업과 내부 ThreadPool·브라우저 자식 프로세스까지 합친 자원 상한을 정한다.
- 완료 기준: 같은 테스트 집합의 직렬/병렬 결과와 skip 사유가 같고 각 조건을 최소 3회 비교한다. 실행 시간 중앙값이 줄고 최대 메모리·DB 연결·프로세스 수가 정한 예산 안에 있어야 채택한다. 충돌/간헐 실패/잔여 리소스는 0건이며 반복 성공만으로 flaky 0%를 입증했다고 표현하지 않는다. 새 회귀나 자원 초과 시 1 worker로 복귀한다. 최종 전체 회귀와 Windows 전용 검사를 포함한다.
- 영향받는 상태·도구·노드: `pyproject.toml`·`uv.lock`, 검증된 테스트 실행 옵션과 CI 자원 설정. 제품 상태·도구·노드 없음.
- 섞지 않을 것: `-n auto`, 8 workers 초과, 같은 DB migration 병렬 실행, 실패 skip/자동 재시도로 녹색 만들기, 운영 풀 설정 변경.
- 선행 작업: 4절 — 최적화 채택 또는 현 구조 유지 판단이 기록된 뒤 시작.
- 하는 사람: Codex.

엔진 하나가 최대 15개 연결을 가질 수 있으므로 worker 수만으로 DB 부하를 계산하지 않는다. 활성 엔진 수·작업별 내부 경합 테스트·기본 연결을 합쳐 DB의 연결 예산 이내로 제한한다. 8 workers가 느리거나 메모리를 초과하면 원인을 기록하고 직렬로 복귀한다. 각 테스트 프로세스는 별도 환경/전역 상태를 가지지만 외부 DB·파일·포트를 자동 격리해 주지는 않는다.

## 측정·채택 기준

- 최초 설치 시간과 준비된 환경의 반복 시간을 분리한다. Python/Node/OS/CPU/RAM·커밋·캐시 상태·선택 node ID·worker 수와 함께 DB 서버 방식과 데이터 디렉터리의 저장소 유형도 기록한다. 임베디드 DB/CI service, Windows 디스크/컨테이너 디스크/tmpfs의 차이를 코드 최적화 효과로 계산하지 않는다. 이 PR의 1회 관측은 속도 개선 전후 벤치마크가 아니다.
- `pytest --durations=20 --durations-min=0.5`로 느린 setup/call/teardown을 찾되 수집/의존성 설치/CI 대기는 별도 기록한다. 최대 RSS는 Python 부모만이 아닌 PostgreSQL·Node·Office·Chromium을 포함한 프로세스 트리로 샘플링한다. 측정 도구·간격·메모리 상한을 1절에서 정한다.
- 초기 채택 목표는 **동일 집합의 반복 실행 중앙값 20% 이상 단축**으로 제안한다. 보장 수치가 아니며 1절 기준선 후 조정한다. 안전성·검증 범위가 같지 않으면 속도 수치와 무관하게 채택하지 않는다. CI 분리로 벽시계 시간이 줄어도 총 실행 시간/비용이 늘었으면 함께 보고한다.
- 오류 재현 시 해당 테스트만 먼저 재실행하고 원인을 고친 뒤 계층과 최종 전체 검증으로 확대한다. 전체 회귀의 불필요한 반복이나 무제한 worker 증설은 하지 않는다.
- 실제 Supabase의 익명/일반 사용자 권한·RLS·Storage 검증은 가짜 JWT/Storage·관리자 PostgreSQL 검사와 다르다. 필요한 권한 회귀는 명시적 일회용 로컬 환경에서 수행하고 기존 미확인 운영 검증을 완료 처리하지 않는다. 실제 OpenAI/Google 과금·운영 DB 변경은 이 계획의 속도 측정에서 제외한다.

## 이번 계획 작성의 확인 결과

- `uv sync` 완료. frontend 의존성과 Playwright Chromium을 준비했다.
- `python3 .work/check.py`는 Windows 실행 별칭 문제로 시작하지 못했다. 같은 스크립트를 `uv run python .work/check.py`로 실행해 통과했다(경고 0개). 문서 수정 후 다시 확인한다.
- 최종 전체 `uv run pytest --durations=20 --durations-min=0.5 -ra`: **1111 passed·2 skipped, 783.44초**. 제외는 Linux에서 실행하지 않는 실제 Windows DPAPI/DACL 2건이다. Python 3.12.12·Node 24.21.0·LibreOffice·Playwright Chromium을 준비한 일회용 Linux 컨테이너와 CI의 고정 pgvector PostgreSQL 16 이미지를 사용했다. DB 데이터는 이번 실행 전용 tmpfs 1GiB에 두고 외부 포트는 공개하지 않았다. Windows 전체와 Linux 임베디드 DB 실행은 중단했으며, 환경이 다른 실행 사이의 개선율은 계산하지 않았다.
- 느린 단일 항목은 worker 지연 503 응답 32.09초, 지식 문서 업로드 브라우저 26.96초, 실제 PC 프로세스 정상 흐름 26.95초, 키 교체/삭제/해제 26.83초였다. worker의 실제 지연·권한 경계 검증은 보존한다. `test_worker_postgres.py`의 자체 서버 fixture setup은 상위 항목에서 13.17초·12.59초로 관측되어 4절의 재사용 후보 조사 근거로 삼는다. 순위에 오른 테스트 시간만으로 전체 DB 초기화 비중을 단정하지 않는다.
- Windows의 `PYTHONUTF8=1` 실패는 원인을 좁힌 뒤 기본 환경에서 해당 테스트 **1 passed, 21.11초**를 확인했다. 최종 Linux 전체 회귀는 위와 같이 통과했다. Linux에서도 `python3 .work/check.py`를 직접 실행해 경고 0개로 통과했다.
- 위 결과는 현재 코드의 1회 관측이며 개선 전후 성능·반복 중앙값·최대 메모리는 미측정이다. 이번 문서 변경으로 테스트가 빨라졌다고 주장하지 않는다.

## 도구 동작의 참고 근거

- [pytest 선택 실행·소요 시간 보고](https://docs.pytest.org/en/stable/how-to/usage.html): 현재 가능한 파일/node ID 선택과 durations 보고 근거.
- [pytest-xdist 배분 방식](https://pytest-xdist.readthedocs.io/en/stable/distribution.html): worker 수 고정과 파일/그룹 배분의 근거. 같은 worker에 배치하는 것과 외부 자원 격리는 별개다.

## 다음 작업 요청문

계획 PR 병합 후 새 작업에서 1절만 시작한다. Issue 번호는 이 계획 PR에 생성된 1절 Issue를 사용한다.

> `docs/plans/test-speed-improvement.md`의 1절만 수행해 주세요. 관련 대상은 pytest 분류·DB/네트워크/프로세스 격리 fixture·실행 시간 기록이며 제품 상태·도구·그래프 변경은 없습니다. 수정 범위는 테스트 설정/안전 가드/필요한 테스트와 계획 1절 기록·최신 흐름입니다. 전체 수집 집합의 누락 없는 분류, 일회용 DB 검증, 외부 통신 차단, 실패 시 정리와 직렬 3회 기준 측정을 확인해 주세요. 병렬화·빌드 재사용·운영 자원 변경은 섞지 마세요. Issue: #217.
