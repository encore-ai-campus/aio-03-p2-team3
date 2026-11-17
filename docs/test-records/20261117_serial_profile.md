# 순차 테스트 비용 계측 (#225)

관련 요구사항: R-09·R-10·R-11·D-02. [설계 1절](../plans/serial-test-speed.md#1)의 구현이다. 빌드 캐시·import 최적화·DB 공유·검사 이동은 후속 작업이다.

## 측정 계약

- 기준 소스: `b958f416fc251cd68dd009a002ffb6a3ff3621e1`. 같은 소스를 같은 일회용 Linux 컨테이너에서 순차 실행한다. 설치와 사전 관련 검사는 벽시계에서 제외한다.
- Python 3.12.12, Node 24.21.0, 잠금 의존성(`uv sync --locked`, `npm ci`), Playwright Chromium·LibreOffice Writer/Calc·Noto CJK를 준비한다. 준비 후 외부 네트워크 연결을 끊는다. 설치 시간과 준비된 시험 시간을 합쳐 비교하지 않는다.
- 장비: Intel Core i5-1135G7(물리 4코어/논리 8개), Docker WSL2 Linux 6.18.58.1, VM 메모리 8,184,819,712 bytes, overlayfs. 시험 컨테이너는 CPU 8개 상한, 메모리/스왑 합계 5 GiB, `/tmp` tmpfs 2 GiB다. 별도 일회용 pgvector PostgreSQL 16 컨테이너는 1.5 GiB 상한, 데이터 tmpfs 1 GiB다. DB 이미지는 기존 CI와 같은 고정 digest다. 두 컨테이너만 새 `docker network create --internal` 네트워크에 연결하고 기본 `bridge` 연결은 제거한다. 호스트 포트를 공개하지 않는다.
- `scripts/serial_benchmark.py`는 외부 기본 경로 존재 시 테스트 전에 거부하고 외부 IP의 TCP 차단·전용 DB 주석·기존 잔여 DB 없음도 확인한다. 실제 개발/운영 DB 주소를 사용하지 않는다. 이 격리는 Python뿐 아니라 Chromium·Node·libpq·PC 자식 프로세스에도 적용된다. 일반 로컬 pytest 자체가 모든 외부 통신을 차단한다는 뜻은 아니다.
- 같은 113건을 계측 끔/켬 각각 3회, `off1 → on1 → off2 → on2 → off3 → on3` 순서로 실행한다. 캐시는 강제로 비우지 않으며 첫 회도 설치 완료 후의 warm 실행이다. 실행 순서 효과와 단일 장비의 변동을 개선 효과로 해석하지 않는다.
- 벽시계는 각 실행기의 `subprocess.run(["uv", "run", "pytest", ...])` 직전부터 자식 종료 직후까지다. JUnit 기록은 양쪽에 동일하게 적용한다. 메모리 측정/검증은 양쪽에 동일하게 적용한다.
- 기존 113건의 node ID·검증 목적·이전→이후 대응은 [검증 목록](20261117_serial_cases.json)에 고정했다. 각 `old_nodeid`는 유지하고 향후 이동 시 `new_nodeid`만 갱신한다. 누락·중복·결과 차이를 허용하지 않는다. 이번에는 전부 1:1 동일하다.
- 정책 파일 `test_parallel.py` 5건과 새 계측기 회귀 `test_serial_profile.py` 1건은 측정 집합에서만 제외한다. 별도 관련 검사 및 최종 전체 pytest에서 실행한다. 기존 테스트의 삭제·skip 추가는 없다.

준비된 격리 컨테이너 내부의 명령:

```sh
uv run python scripts/serial_benchmark.py /task/bench-off-1
uv run python scripts/serial_benchmark.py /task/bench-on-1 --profile
# 같은 순서로 -2, -3 디렉터리를 새로 지정한다.
```

DB 연결은 컨테이너 시작/실행 시 테스트 전용 `TEST_DATABASE_URL`로만 지정한다. 실행기는 DB 이름·주석 검증을 fixture에서도 거치며 보고서에 접속 문자열을 저장하지 않는다. `--serial-profile=/임시경로/cost.json`은 Windows/일반 pytest에서도 사용할 수 있는 별도 옵션이며 `-n 0`에서만 허용한다. 외부 통신 격리는 측정 실행 환경의 책임이다.

## 기록 형식과 읽는 법

`cost.json`의 `schema=1`, `exitstatus`, `cases`, `events`를 사용한다. `cases`는 `old_nodeid/new_nodeid/purpose`, `events`는 `nodeid/phase/role/seconds/count`와 pytest 단계의 `outcome`만 담는다. 인자·반환값·예외 본문·환경변수·URL·헤더·키·메일/문서 본문·원문 로그는 직렬화하지 않는다. node ID는 검토한 가짜 사례의 ID만 사용한다.

| phase | 측정 경계·역할 | 해석 |
|---|---|---|
| collection | pytest 수집 hook | 수집 중 import 포함. 옵션 활성화 준비 import는 바깥 벽시계에 포함 |
| setup/call/teardown | pytest report.duration | 전체 비용 분류의 기준. 결과는 passed/failed/skipped |
| frontend.build | 기존 npm build 호출 직전~종료 | 네 곳을 그대로 실행. 설정·산출물 공유 없음 |
| tls.key / tls.certificate / tls.context | RSA 키 생성 / 인증서 서명 / SSL context 생성 | 공통 RSA hook이라 가짜 JWKS의 인증 키도 포함. worker TLS 키만 볼 때 `test_worker_process.py` node ID로 제한한다. HTTP handshake는 요청 시간에 포함 |
| process.spawn | Popen 호출 직전~반환 | 서버/openai/pc/local별 생성 횟수 |
| process.ready | 생성 직전~자식의 준비 checkpoint | server/openai는 Uvicorn startup 완료, pc는 실제 check_protocol 완료. 준비 실패 시 checkpoint 없음 |
| process.ready_wait | 부모의 기존 health 대기 루프 | 이미 함께 시작한 mock의 준비 대기는 짧을 수 있다. 전체 startup 시간과 다름 |
| http.request | 시험 부모의 httpx.Client.send | server/openai/local별 요청 시간·횟수. 부모/스레드의 실제 HTTP 대기 포함. PC 내부 SDK 호출별 시간은 미계측 |
| process.stop | terminate~communicate/wait 완료 | 실제 지출이다. 기존 35/5초 종료 상한·재시도/지연/키 교체 재시작은 유지 |
| db.server_start/stop | pgserver.get_server / 실제 _cleanup | 기존 테스트별 PostgreSQL 서버 생성·정리 그대로 |
| db.create/drop | UUID DB 연결~CREATE/DROP 완료 | 테스트 전용 외부 DB 서버 사용. 각 건의 DB 공유 없음 |
| db.schema/migration | create_tables / upgrade_database | migration은 schema에 포함. 자식 서버의 migration은 startup 시간에 포함 |

**중첩·동시 구간을 더해 전체 시간으로 만들지 않는다.** setup/call/teardown 안에 build/DB/HTTP 등이 포함되며, server/openai 준비는 동시에 진행된다. 부모 HTTP의 일부는 ready 대기 및 PC 시작·SDK 재시도와도 겹친다. process.ready는 실제 프로토콜 확인까지의 경과이며, call 중 겹쳐서 수행되는 PC 준비를 call에서 단순 차감하지 않는다.

`run.json`은 uv/pytest 전체 경과 초·종료 코드·113건 결과, canonical 일치, 잔여 DB/실행 프로세스 수, 100ms 간격 **cgroup memory.current 표본 최대값**·상한·OOM 증가량을 담는다. 이 값은 RSS가 아니며 페이지 캐시·tmpfs를 포함한다. 별도 DB 컨테이너 메모리는 포함하지 않는다. 종료된 좀비는 실행 중 프로세스 수에서 제외하고, 마지막 컨테이너 삭제로 정리한다. 원문 JUnit은 일회용 진단 파일이며 저장소에는 민감정보 없는 JSON만 보존한다.

## 검증 목적·자원 및 후속 영향 매핑

각 사례의 구체적인 검증 목적은 canonical 목록의 `purpose`다. 아래는 모듈 단위의 보수적인 자원 상한이며, 개별 사례를 병렬 이관할 근거로 그대로 사용하지 않는다. 5절에서 fixture·실제 호출별로 다시 검토한다.

| 모듈 | 건수 | 주요 검증·자원 | 후속 영향 |
|---|---:|---|---|
| test_knowledge | 31 | 문서 렌더·vector/소유권/실패 보존, Office·임시 DB·가짜 AI/Storage | DB/Office 회귀, 독립 사례 분류 |
| test_knowledge_browser | 2 | 업로드·수정/409·확정/모바일·로컬 키 복구, 빌드·브라우저·앱/DB | 설정별 빌드 재사용 |
| test_local_gmail | 43 | 수집·인증/커서·사용자/세대/중지 격리, DB·모의 SDK·실제 launcher 1건 | 프로세스 비용/독립 사례 분류 |
| test_react_settings | 4 | 설정 소유권/기존 문서 보존·Gmail callback 오류/모바일, API/DB·브라우저 | 설정별 빌드 재사용 |
| test_trade_mobile_browser | 12 | PI/PO/CI/PL 발급·후보·두 승인·409/입력/다운로드 보존, 빌드·브라우저·앱/DB | 설정별 빌드 재사용 |
| test_worker_credentials | 10 | 권한/파일 보존·DPAPI/DACL, 임시 파일·OS 권한 | Windows 전용 2건은 Linux에서 기존 skip |
| test_worker_postgres | 5 | 실제 연결 경합·사용자/장치 격리·기존 데이터 upgrade, 개별 pgserver | DB 서버 준비 분해 |
| test_worker_process | 6 | 실제 HTTPS·두 PC·401/429/503/6초×3·키 교체/삭제/해제, 실제 별도 프로세스/DB | 역할별 startup/정리 비용 |

## 실행 결과

집계·전체 113건의 결과 동등성·각 사례의 setup/call/teardown·단계별 호출 수는 [측정 JSON](20261117_serial_profile.json)에 보존했다. 원문 비용 파일의 SHA-256도 집계에 남겼다. 설치 시간은 수치로 계측하지 않았고 아래 벽시계에서 제외했다. 이 기록으로 설치 속도를 비교하지 않는다.

| 회차 | 계측 끔 벽시계(초) | 계측 켬 벽시계(초) | 켬−끔(초) | 끔/켬 메모리 표본 최대(GiB) |
|---|---:|---:|---:|---:|
| 1 | 342.934 | 338.762 | -4.172 | 3.234 / 3.217 |
| 2 | 333.206 | 326.216 | -6.990 | 3.200 / 3.191 |
| 3 | 318.592 | 308.997 | -9.594 | 3.178 / 3.174 |

- 끔: 중앙값 **333.206초**, 범위 318.592~342.934초, 표본 분산 150.130초²·표준편차 12.253초.
- 켬: 중앙값 **326.216초**, 범위 308.997~338.762초, 표본 분산 223.306초²·표준편차 14.943초.
- 계측 비용 비교: 3쌍의 켬−끔 차이 중앙값은 **-6.990초**다. 실행 순서에 따라 두 집합 모두 빨라지는 추세가 있어 캐시/순서/시스템 변동과 계측 비용을 분리하지 못했다. 이 음수를 계측의 속도 개선이나 음의 오버헤드로 해석하지 않으며, 0비용이라고 증명한 결과도 아니다.
- 6회 모두 **111 passed·2 skipped**, 113건 ID/순서/결과 동일·중복/누락 없음. 두 skip은 기존 Windows DPAPI/DACL 검사다. 각 실행의 OOM/강제 OOM 종료 증가량·잔여 UUID DB·잔여 실행 중 프로세스는 **0**이다. 시험 메모리 상한은 5 GiB다. 별도 DB 컨테이너도 순차 측정 후 OOM 0회, lifetime peak 135,835,648 bytes(상한 1.5 GiB), `OOMKilled=false`였다.

계측 켬 3회의 모듈별 중앙값(초):

| 모듈 | setup | call | teardown | 사례 전체 시간 |
|---|---:|---:|---:|---:|
| worker_process | 26.159 | 112.373 | 2.040 | **140.502** |
| trade_mobile_browser | 12.693 | 67.268 | 2.268 | **82.391** |
| local_gmail | 13.251 | 10.920 | 0.732 | 25.576 |
| knowledge_browser | 0.048 | 24.491 | 0.028 | 24.567 |
| knowledge | 4.325 | 18.896 | 0.260 | 23.343 |
| react_settings | 0.080 | 13.657 | 0.049 | 13.785 |
| worker_postgres | 2.848 | 2.621 | 0.484 | 5.955 |
| worker_credentials | 0.007 | 2.536 | 0.002 | 2.546 |

각 열은 독립적인 중앙값이므로 열/행을 더해 벽시계와 맞추지 않는다. 전체 pytest 단계 합의 중앙값은 setup 59.273초, call 253.292초, teardown 5.740초이며 collection hook은 2.566초다. 계측기 준비 import/uv 시작·종료 등 나머지는 벽시계에 포함한다.

상위 자원별 실제 지출과 횟수(계측 켬 3회 중앙값, 중첩 포함):

| 작업 | 합계 시간(초) | 회당 호출 수 | 해석 |
|---|---:|---:|---|
| PC terminate/communicate | **47.852** | 9 | 35초 상한과 다르다. 실제 종료·장기 poll 정리를 유지 |
| PC 생성→프로토콜 준비 | **24.896** | 9 | call/HTTP와 겹침. 실제 3회 키 교체 재시작 유지 |
| server 생성→ready / 부모 대기 | 22.720 / 23.523 | 각 6 | openai와 동시 시작. 두 값을 합하지 않음 |
| openai 생성→ready | 12.876 | 6 | 부모 대기 0.107초만 보면 이 비용을 놓침 |
| local launcher 준비 / 종료 | 3.778 / 0.215 | 각 1 | 실제 루프백 프로세스 유지 |
| server/openai 종료 | 0.935 / 0.942 | 각 6 | 정상 종료 확인 포함 |
| 모든 Popen 생성 | 역할별 0.001~0.004 | local 1, server 6, openai 6, pc 9 | 비싼 구간은 Popen 반환 이후 |
| 부모 server HTTP | **60.631** | 464~537 | ready poll·PC 준비·실제 재시도·업무 대기가 겹침 |
| 부모 openai HTTP / local HTTP | 0.132 / 1.198 | 13 / 113~121 | SDK 내부 요청별 시간과 구분 |
| DB schema / migration | 22.966 / 22.972 | 각 93 | 대부분 중첩. 자식 서버의 migration은 startup에 포함 |
| UUID DB 생성 / 삭제 | 1.888 / 1.140 | 각 87 | 매 사례 격리 유지 |
| 임베디드 DB 서버 시작 / 삭제 | 2.478 / 0.568 | 각 5 | 외부 일회용 DB 서버 설치/시작은 준비 시간으로 제외 |
| Vite 빌드 | **3.964** | 4 | 이번 환경에서는 전체 시간의 작은 부분 |
| RSA 키 생성 / 인증서 서명 / SSL context | 2.202 / 0.005 / 0.308 | 50 / 6 / 29 | RSA 50회에는 인증용 키가 포함. TLS용 6회는 JSON의 worker_tls_keys 참조 |

이 기준에서 다음 절의 빌드 재사용과 DB 서버 재시작 축소는 최대 절감 가능 시간이 각각 몇 초 규모다. 반복 비용을 줄일 수 있지만 전체 중앙값 20% 단축을 이 둘만으로 보장할 근거는 없다. 프로세스 준비/정리와 브라우저 사례의 비용을 우선 확인하되, 지연 6초×3회·실제 HTTPS·권한/키 교체 검증과 timeout은 유지한다. 끔 중앙값을 기준으로 20% 참고 목표는 약 **266.6초**며 달성하지 않았다. 기존 760초/520초·설계 검증 627.82초와 이번 수치로 단축률을 주장하지 않는다. 전체 8-worker 파이프라인 성능의 채택은 6절에서 따로 판단한다.

## 관련 검사·실패 정리·최종 확인

- 계측기 회귀: 합격 1·고의 실패 1·고의 skip 1인 하위 테스트를 끔/켬으로 실행해 같은 결과를 확인했다. 실패 인자/예외 원문을 비용 JSON에서 제외하고, 예외 구간도 시간을 기록하는지 검사한다. 상위 검사는 **1 passed**다.
- 실제 HTTPS·PC 프로세스 6건과 실제 로컬 launcher 1건은 **7 passed, 154.05초**였다. 이후 역할별 ready checkpoint 보완도 해당 실제 PC 오류 사례로 재확인했다(**1 passed, 15.99초**).
- 격리 거부: 테스트 컨테이너에 기본 bridge를 연결한 상태에서 실행기를 호출하면 `External default route exists`로 테스트 전에 거부했다. 다시 연결을 제거하고 6회 측정 모두 외부 IP TCP 차단을 확인했다.
- 고의 실패 정리: 일회용 probe에서 실제 system fixture를 준비한 뒤 assert 실패를 발생시켰다. **setup passed → call failed → teardown passed**, 종료 코드 **1**을 보존하고 서버/openai **2개** 종료·잔여 DB/실행 중 프로세스 **0개**를 확인했다. 정상 테스트 실패를 통과로 바꾼 것이 아니며 임시 probe 파일은 바로 삭제했다. 수치는 측정 JSON에 있다.
- 최종 기본 직렬 전체 `uv run pytest`: **1117 passed·2 skipped, pytest 604.15초**. 호스트에서 Docker exec까지 포함한 별도 벽시계는 615.916초다. 정책 5건과 새 계측기 회귀 1건을 포함했다. 기존 1118건에 신규 회귀 1건을 더한 1119건이며, 8-worker 전체 파이프라인의 새 실행 시간으로 쓰지 않는다.
- 전체 후 잔여 UUID DB·실행 중 프로세스·시험 컨테이너 OOM 증가량은 0이다. 이번 컨테이너의 PID 1은 sleep이어서 Chromium 등이 종료한 고아 좀비 323개가 남았다. 실행 중인 프로세스와 구분하며, 마지막에 이 작업의 두 컨테이너와 내부 네트워크를 삭제해 함께 정리했다. 삭제 후 해당 컨테이너/네트워크 조회는 0건이고 기존 개발용 Supabase 컨테이너는 그대로 실행 중이다. 재현 환경을 새로 준비할 때는 `docker run --init`으로 종료된 고아 자식도 회수하도록 권장한다.
- `python3 .work/check.py`: Linux 직접 실행 **통과, 경고 0개**. Windows `uv run python -X utf8 .work/check.py`도 **통과, 경고 0개**. Linux 첫 검사에서는 소스 루트의 계측용 임시 JSON 1개가 파일 지도에 없어 실패했다. 해당 산출물을 회수·삭제하고 재검사해 통과했으며 규칙/파일 지도는 바꾸지 않았다. `git diff --check`도 통과했다.
