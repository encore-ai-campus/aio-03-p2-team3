# #157 준비 검증: worker 503 ReadTimeout

- 관련 요구사항: R-11(재시도 한도·종료 조건). R-04·R-12·R-14의 실제 API/배포 검증과 구분한다.
- 기준: 최신 main `6058b19`(PR #176 병합), Python 3.12, Linux, 실제 임시 PostgreSQL.
- 범위: 자체 서명 인증서의 루프백 HTTPS 서버·모의 OpenAI·별도 PC 프로세스·가짜 키/메일. 실제 키·Google 동의·개인 메일·Render·운영 DB는 사용/변경하지 않았다.

## 원인과 확인 범위

`tests/test_worker_process.py`의 서비스 HTTP 클라이언트는 15초만 응답을 기다렸다. 반면 `app/worker/adapter.py`는 한 논리 작업을 최대 120초 기다리며 통신/5xx 오류에 최대 3회 호출, 1·2초 backoff를 적용한다. PC의 개별 SDK 호출 제한은 20초이고 SDK 자체 재시도는 0회다. 따라서 허용된 재시도가 진행 중이어도 시험 요청이 먼저 `httpx.ReadTimeout`으로 종료될 수 있었다. 모의 OpenAI의 503은 시험이 의도적으로 주입한 오류이며, 외부 OpenAI 장애 관측이 아니다.

최초 기존 시험 5개는 모두 통과했다(91.79초). 빠른 503만으로는 원래 실패가 재현되지 않았다. 준비 검증 당시의 정확한 지연 요인(프로세스 시작/호스트 부하/DB·통신 지연)은 이번 결과만으로 특정하지 않는다.

시간 한도 불일치는 각 503 응답을 6초 늦추는 `SLOW503` 사례로 재현했다. 각 호출은 기존 20초 제한 이내지만 3회 지연 18초와 backoff 3초만으로 시험의 15초 제한을 넘는다. 수정 전 같은 `/api/trade/pi/extract` 요청에서 `httpcore.ReadTimeout` → `httpx.ReadTimeout`이 발생했다(1 failed, 5 deselected; call 16.26초, 전체 57.15초). 실패 뒤 프로세스 정리 시간도 전체 시간에 포함된다.

## 수정

- 서비스 시험 클라이언트 두 개의 공통 대기를 `httpx.Timeout(125, connect=5)`로 맞춘다. 서버 전체 기한 120초와 응답 여유 5초이며 연결 실패는 5초로 제한한다. 모의 서버 상태 조회는 기존 5초다.
- `SLOW503`은 모의 서버에서 비동기로 지연하므로 상태 조회·다른 요청을 막지 않는다. 기존 빠른 401·429·503 사례도 유지한다.
- 오류 HTTP 상태·오류 코드·호출 횟수(401/429 각 1회, 503 3회), 문서 미생성, 최종 작업 실패 종류와 payload/result 암호문 삭제를 함께 확인한다.
- 운영 코드·SDK 제한·재시도 예산·큐 전체 기한·키/장치 정책은 변경하지 않는다.

## 검증

- 수정 전: `uv run pytest tests/test_worker_process.py -k SLOW503 -q --tb=short --durations=3` → 의도한 ReadTimeout 재현.
- 수정 후: `uv run pytest tests/test_worker_process.py tests/test_worker_execution.py tests/test_worker_queue.py -q --tb=short --durations=8` → **106 passed**, 175.17초. 지연된 503 사례의 call은 30.38초였으며 HTTP 503 `WORKER_NETWORK`·정확히 3회 호출·문서 미생성·최종 실패와 전송 데이터 삭제 검증을 통과했다. 빠른 503 사례도 통과했다(call 11.17초).
- 전체 `uv run pytest` → **968 passed, 2 skipped**, 366.99초. 건너뛴 두 개는 Linux에서 실행할 수 없는 Windows DPAPI/DACL 검사다. Windows 실행 결과는 이 PR의 CI에서 별도 확인한다.
- `python3 .work/check.py` → 검사 통과(경고 0개). PR 본문 검사도 수행하며 그 결과는 이 PR의 확인 결과에 남긴다. 대상 회귀 실행에서 보인 platformdirs의 XDG_RUNTIME_DIR 미설정 경고는 임시 PostgreSQL 경로의 fallback 안내다.

## 남은 확인

#157은 열어 둔다. `docs/plans/local-openai-execution.md` 5절의 실제 PC·키 교체/삭제·두 사용자 과금 프로젝트·Gmail/Render 종단 간·운영 마이그레이션 확인은 사람이 별도로 수행해야 하며 이번 자동 시험 통과로 완료 처리하지 않는다.
