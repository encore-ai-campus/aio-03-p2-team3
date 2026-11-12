# 프론트엔드·Supabase 전환 문서 모음

요청한 React + JavaScript + Vite 화면과 Supabase Auth·PostgreSQL·비공개 Storage 전환 자료를 이 폴더에 모은다. 현재 브랜치에는 1·3~12절 구현이 있으며, 실제 운영 DB/파일 이전은 미착수다. 단계별 구현·검증 범위는 PROGRESS.md에서 구분한다.

| 문서 | 담긴 내용 |
|---|---|
| [PLAN.md](PLAN.md) | 현 코드 검토, 목표 구조, 폴더·패키지 최소안, 인증/파일 계약 초안, 화면 범위, 보류 사항, 22개 작업의 선행 조건·범위·완료 기준·Issue |
| [PROGRESS.md](PROGRESS.md) | 현재 코드의 구현 범위·확인 결과·환경 설정·남은 단계 |
| [REQUESTS.md](REQUESTS.md) | 각 단계의 새 작업에 붙여넣을 요청문. 한 작업에서 한 단계만 맡긴다 |

### 계획의 핵심

1. 루트 `frontend/`에서 React·JavaScript·Vite로 시안 화면을 구현한다.
2. 로그인은 Supabase Auth, 업무 규칙은 기존 FastAPI에서 처리한다.
3. SQLAlchemy·Alembic을 재사용해 DB를 Supabase PostgreSQL로 옮긴다. 앱/테스트의 SQLite 의존성도 단계적으로 없앤다.
4. 첨부·직인/로고·승인 PDF/XLSX는 private Storage에 저장하고 소유자·문서 버전·해시·파일 참조는 DB에서 관리한다.
5. 먼저 로그인→회사 설정→PI 검토/발급을 연결하고, PO→CI→PL→문서함/현황→첨부→메일→실행 기록 순으로 확장한다.
6. 데이터와 승인 파일은 보존·복사·검증한 뒤 전환한다. 원본 삭제/바이너리 열 제거는 검증 뒤 별도로 결정한다.

### 착수 조건

- 이 계획 PR 병합 뒤 1절부터 시작한다. 관련 담당 조율과 선행 작업 병합은 각 Issue·PLAN의 조건을 따른다.
- 1절은 공동 계약을 확정한다. 그 뒤 2절(사람의 콘솔 준비)과 3절(PostgreSQL 테스트 환경)은 독립적으로 시작할 수 있다.
- Supabase 프로젝트·비공개 버킷·Google OAuth 준비는 사용자 확인을 받았으며 환경변수는 미설정이다. 실제 연결·데이터 보존 대상·운영 이전 완료를 구분한다.
- 기존 규칙은 상위 `AGENTS.md`·`.work/RULES.md`·`.work/TASK.md`를 따른다. 이 폴더는 그 규칙을 복제하지 않는다.

### 범위를 작게 유지하는 기준

- 기존 문서 업무·가격 계산·검토·승인·Gmail 발송 서비스 재사용.
- 화면은 로컬 상태·기본 폼·기존 CSS를 사용하고 초기 상태 관리/폼/UI 프레임워크 추가를 피함.
- 첨부 저장과 PDF/Excel 내용 추출·이미지 OCR은 구분. 시안의 계약서·독립 USD 견적·범용 챗봇은 이번 계획의 구현 범위에서 제외.
- 클린코드는 명확한 함수/책임/오류 처리로 적용하고 폴더 계층·추상 클래스·범용 엔진 추가로 대신하지 않음.

### 스킬과 이번 검토 기록

- 요청한 React 스킬의 파생 상태·Effect 정리·구독 해제·조기 최적화 방지 원칙과 Ponytail의 기존 코드 재사용·최소 의존성 원칙을 계획에 적용했다. React 스킬 중 Server Components/Server Actions 전용 항목은 Vite SPA에 적용하지 않는다.
- `mattpocock/skills`는 사용자 환경에 38개 설치했다. 기존 `tdd`와 충돌하는 것은 `mattpocock-tdd`로 별도 설치했고, 원본의 잘못된 YAML을 가진 `software-factory`는 설치 도구가 제외했다. 현재 frontend/의 React·Vite 의존성은 버전 고정과 lockfile로 관리한다.
- React 스킬의 버전 탐지는 루트에 `package.json`이 없어 사용법 오류로 종료했다. 이후 frontend/ 탐지에서 React 19.3.1과 스킬 대상 버전 일치를 확인했다.
- 문서 폴더 구성은 사용자의 추가 요청을 반영했다. 레포의 기존 공통 계약·현재 흐름·파일 지도는 원래 위치에 두고 이 폴더를 연결한다.

### 검증과 제한

- 계획의 22개 작업과 필수 항목을 확인했다. `python3 .work/check.py`는 경고 0개로 통과했고, 실제 LLM 키를 비운 `uv run pytest`는 639 passed·1 skipped였다. skipped는 선택 PostgreSQL 검증 모듈이며 PostgreSQL 전환 완료를 뜻하지 않는다.
- 처음 로컬 테스트에서 LLM 키 설정의 영향을 받는 기존 테스트 1개가 실패했다. 실제 키를 비운 환경에서 전체 검사를 다시 수행하며, 근본적인 테스트 격리는 PLAN 3절에 포함했다.
- 실제 Supabase/Gmail/OpenAI·운영 DB·Render 연동과 성능은 이 문서 작업으로 검증한 것이 아니다.
