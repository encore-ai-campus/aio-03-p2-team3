# 대화형 마스터 검증 — 2026-11-18

관련: `docs/plans/master-agent.md` 1~3절, 계약 17.4절, R-01·R-02·R-04·R-05·R-06·R-09·R-10·R-11·R-12. 사용자 요청으로 PR·push·병합은 하지 않았다.

## 확인 범위

- 실제 StateGraph·PostgresSaver·임시 pgvector PostgreSQL·FastAPI·React·Chromium과 가짜 모델/Google/Storage를 사용했다. 운영 DB·Google 실제 발송·실제 OpenAI 요청은 하지 않았다.
- 본인 키를 암호화 DB에서 읽고 실제 ChatOpenAI/Responses SDK의 도구 바인딩→function_call→기존 메일 검색→function_call_output→모델 재판단을 모의 HTTP로 확인했다. local_worker는 공용 키 대체 없이 거부했고 추가 요청은 발생하지 않았다.
- API: 본인 메일 검색/원문→자연어 질문→새 앱/saver 인스턴스 재시작→질문 응답→후보 직접 선택→본문/헤더 고정 승인→기존 Gmail 승인 서비스. 같은 승인의 오래된 revision 재전달은 409이며 가짜 Gmail 발송은 1회다. 타인 대화 읽기/재개는 404, 익명 요청은 401, 실제 ToolMessage에 결과가 전달된다.
- 문서: 실제 PI 입력 스키마→결제 조건 누락 초안→자연어 보완→같은 문서 revision 2→사용자 발급 승인→실제 PDF/XLSX bytes와 본인 다운로드를 확인했다. 메일 발송은 발생하지 않았다. 기존 명시적 Plan의 PI/PO/CI/PL 발급·버전 충돌·승인/복구 회귀도 포함한다.
- 브라우저: 1440px에서 요청/질문·포커스/새로고침/후보 직접 선택/수신자·본문 확인, 390px에서 승인 발송·후속 대화/기존 결과 보존·PI 문서 스냅샷/발급/PDF 다운로드를 확인했다. 가로 넘침/JS 오류가 없었고 모바일 스냅샷을 직접 확인했다. 질문 선택창의 접근성 이름을 명시해 수정했고 실제 렌더된 수신자 문구에 맞춰 시험을 보완했다.
- 반복 판단은 요청당 최대 12회에서 종료한다. 잘못된 도구 입력을 전달해도 다른 사용자의 자료를 읽거나 메일을 보내지 않는다.

## 최종 실행 결과

- `AI_RUNTIME=server uv run pytest tests/test_master_agent.py tests/test_master_agent_browser.py tests/test_domain_graph.py tests/test_domain_graph_adapters.py tests/test_db.py tests/test_auth.py tests/test_react_settings.py -q --tb=short`: **85 passed, 42.55초**. 전체 저장소 테스트를 반복하지 않고 변경 영역/기존 승인·인증·DB 회귀에 집중했다.
- 프론트 lint·입력 helper test 12개·build 통과. 단일 JS 번들 500kB 안내 경고는 남아 있다.
- `python3 .work/check.py`: 경고 0개. `git diff --check` 통과. 개인 output.log 두 파일은 내용을 바꾸지 않고 로컬 Git 제외 목록에만 등록했다.

## 제한

실제 모델의 판단 품질·개인 계정/운영 DB/Render 연결은 미확인이다. 단일 앱 프로세스·사용자별 진행 1건·요청당 12회 범위다. PC local_worker 도구 대화·지식 문서 검색·Calendar 실행·SSE는 연결하지 않았다. 중단/불명 실행은 외부 쓰기를 자동 재생하지 않고 본인 상태 확인으로 기존 영수증을 읽는다.
