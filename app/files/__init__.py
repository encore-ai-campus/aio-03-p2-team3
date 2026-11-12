"""비공개 Supabase Storage 첨부 API(계획 8절, CONTRACT 16.3절).

- `storage.py`: httpx 기반 Storage 호출(timeout·오류 변환만 담당).
- `validation.py`: 파일당 크기 한도·시그니처 형식 판별·안전한 다운로드 파일명.
- `service.py`: 업로드→Storage→`file_assets` 확정, 조회·다운로드·삭제 업무.
- `sources.py`: 문서 출처 연결(파일 ID 목록·기대 revision 검증).
- `router.py`: Bearer 전용 `/api/files` 경로.
- `cleanup.py`: 미참조 객체 목록·수동 정리 명령(크론·큐 없음).
"""
