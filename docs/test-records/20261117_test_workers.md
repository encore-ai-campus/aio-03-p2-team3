# 8 workers 실행 기반 검증 — 2026-11-17

- 관련: `docs/plans/test-speed-improvement.md` 0절, #223. 요구사항 R-09·R-10·R-11·D-02.
- 범위: pytest 분류·8-worker 실행·DB 표식·실패 정리와 CI 실행 단계. 제품 코드·운영 환경·실제 AI/Google/Storage는 변경/사용하지 않았다.
- 기준 코드: upstream/main `4a833a3` 위 계획 PR #222와 이번 테스트 실행 기반 변경. 두 실행은 동일한 제품 코드·테스트 집합·의존성·DB 환경을 사용했다.

## 환경과 자원

- 일회용 Linux 컨테이너, Python 3.12.12, Node 24.21.0, pytest 9.2.0, pytest-xdist 3.8.0. 잠금 파일 설치·LibreOffice·한글 폰트·Playwright Chromium을 준비했다.
- 테스트 컨테이너 상한: 8 CPU/메모리 5GiB, `/tmp` tmpfs 2GiB. DB 컨테이너 상한: 메모리 1.5GiB, DB 디렉터리 tmpfs 1GiB. 메모리/CPU 상한은 직렬 실행 중에 설정했고 두 실행 모두 그 한도 이내였다.
- PostgreSQL 16/pgvector는 CI와 같은 고정 이미지 digest를 사용했다. `aio_test`와 테스트 DB 주석을 확인하고, 테스트마다 UUID DB를 생성/삭제했다. 호스트 포트를 공개하지 않았다. 다른 개발/운영 DB·실행 중인 개발 프로세스를 사용하지 않았다.

## 실행 결과

| 실행 | 결과 | pytest 보고 시간 | uv 시작/단계 전환 포함 시간 |
|---|---|---:|---:|
| 기본 전체 `uv run pytest --durations=10 -ra` | 1116 passed, 2 skipped | 760.68초 | 별도 측정하지 않음 |
| 정책 파일 `-n 0` | 5 passed | 13.77초 | 16.23초 |
| 독립 집합 `-n 8 -m parallel` | 1000 passed | 144.68초 | 147.42초 |
| 순차 집합 `-n 0 -m serial --ignore=tests/test_parallel.py` | 111 passed, 2 skipped | 349.92초 | 356.12초 |
| 정책 → 병렬 → 순차 전체 파이프라인 | 1116 passed, 2 skipped | 합계 508.37초 | **519.76초** |

제외 2건은 기존 Linux 조건에 따른 실제 Windows DPAPI/DACL 검사다. 실패를 skip으로 바꾸지 않았다. 정책 파일은 먼저 검사하고 마지막 순차 단계에서만 제외하여 중첩 8-worker 실행과 중복 검증을 피한다.

각 단계의 JUnit `(classname, name)`을 대조했다. 5·1000·113건의 합계와 고유 합집합은 모두 **1118건**이며 단계 사이 중복은 0건이다. 수집 전체 1118건과 일치한다. 실행 후 전용 서버의 `test_%` DB 잔여 수는 **0개**였다.

이번 한 쌍에서는 전체 수행 시간이 줄었다. 다만 직렬 값은 pytest 자체 시간, 파이프라인 값은 uv 시작/단계 전환을 포함한 벽시계 시간이므로 측정 경계가 다르다. 직렬을 먼저 실행한 캐시 순서 효과·다른 호스트 작업 부하도 분리하지 않았다. 3회 중앙값·flaky 비율·항상 유지되는 개선율을 입증한 결과가 아니다. 이전 계획 작성의 783.44초나 다른 Linux CI의 424.18초와 개선율을 계산하지 않는다.

## 격리·정책·자원 확인

- 회귀 검사에서 실제 8개 worker가 독립 샘플 32건을 분배했다. 미분류 샘플 4건은 병렬 실행에서 제외되고 별도 직렬 실행에서만 통과했다.
- auto·9 workers·병렬에서 serial 집합 선택은 실행 전에 거부됐다. `-n=auto` 별칭도 별도로 거부를 확인했다. worker 충돌 후 자동 재시작은 비활성화했다.
- 실제 임시 PostgreSQL에서 표식 없는 DB 거부와 표식 있는 DB 허용을 검증했다. 외부 URL의 DB 이름도 `aio_test`로 제한한다. 공유/운영 DB에 표식을 추가해 우회하는 사용은 허용하지 않는다.
- fixture setup/본문 실패 시 DB 엔진과 UUID DB를 finally에서 정리하도록 바꿨다. 기존 소유권·동시 승인·키·실패·권한 경계 검증은 유지한다.
- 검증 컨테이너 수명 전체 cgroup 메모리 peak는 테스트 **3,688,488,960 bytes**, DB **380,555,264 bytes**였다. 준비·직렬·병렬 실행과 파일 캐시를 포함하는 값이며 단계별 프로세스 RSS 최대값이 아니다. 두 컨테이너의 memory.events에서 max/oom/oom_kill은 모두 0이었다.
- Windows에서는 DB를 쓰지 않는 신규 정책 검사 4건이 통과했다. 전체 Windows 회귀는 로컬에서 수행하지 않았으며 CI의 Windows 전용 검사를 유지한다.
- Linux의 `python3 .work/check.py`와 Windows의 `uv run python .work/check.py`는 경고 0개로 통과했다. 마지막 정책 재확인은 5 passed/10.95초였다. workflow YAML 파싱과 Windows 준비 스크립트의 PowerShell 구문, Linux 준비 스크립트의 `bash -n` 검사를 통과했다.

## 오류와 조정

- 동적 xdist_group 배분을 실제 8-worker 샘플로 확인하자 순차 대상이 여러 worker로 분배됐다. 그룹 구현은 제거하고 pytest marker 선택을 이용한 별도 실행 단계로 순차 경계를 보장했다. 검사 assertion을 완화해 통과시키지 않았다.
- Windows pytester가 자식의 CP949 오류 출력을 UTF-8로 읽어 실패했다. 정책 검사 subprocess에만 `PYTHONIOENCODING=utf-8`을 지정해 표준 입출력을 맞췄다. 제품 렌더러나 전역 `PYTHONUTF8`은 변경하지 않았다.
- 벤치마크 임시 파일을 컨테이너에서 찾지 못한 시작 시도는 테스트 실행 이전에 중단됐다. 스크립트를 stdin으로 전달해 위 파이프라인을 한 번 실행했다.

## 남은 작업

계획 1~5절의 상세 자원/변경 영향 매핑, 기본 네트워크 차단, 반복 중앙값과 단계별 최대 RSS, 빌드 재사용·DB 초기화 최적화는 남아 있다. 이번 변경은 8 workers 실행 기반이며 전체 최적화 완료가 아니다. 무거운 순차 단계가 약 350초로 남으므로 workers를 더 늘리는 대신 기존 후속 작업에서 해당 비용을 조사한다.
