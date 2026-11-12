"""Supabase Storage 비공개 버킷 호출(httpx). timeout·오류 변환만 담당한다(계획 8절).

서버 비밀 키로 표준 업로드·다운로드·삭제·목록만 부르고 재시도·캐시·큐는 만들지 않는다.
비밀 키는 Storage 정책을 우회하므로 소유권 검사는 이 호출을 쓰는 업무 쪽(service.py)에서 한다.
엔드포인트는 공식 Storage API(/storage/v1/object/…)를 따른다.
"""
from logging import getLogger

import httpx

log = getLogger(__name__)

STORAGE_TIMEOUT_SECONDS = 20.0
LIST_PAGE_SIZE = 100


class StorageError(Exception):
    """Storage 호출 실패. `code`는 오류 종류, 비밀값·응답 원문은 message에 넣지 않는다."""

    def __init__(self, code: str, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class StorageClient:
    """서버 비밀 키로 private 버킷 하나를 다루는 호출기. 앱마다 하나를 만들어 재사용한다."""

    def __init__(self, supabase_url: str, secret_key: str, bucket: str, *,
                 timeout: float = STORAGE_TIMEOUT_SECONDS):
        self.base_url = supabase_url.strip().rstrip("/") + "/storage/v1"
        self.secret_key = secret_key
        self.bucket = bucket
        self.timeout = timeout

    def _request(self, method: str, path: str, *, content=None, json=None,
                 extra_headers=None) -> httpx.Response:
        headers = {"apikey": self.secret_key, "Authorization": f"Bearer {self.secret_key}"}
        headers.update(extra_headers or {})
        try:
            response = httpx.request(method, self.base_url + path, timeout=self.timeout,
                                     content=content, json=json, headers=headers)
        except httpx.HTTPError as error:
            log.warning("Storage 호출 실패: %s %s(%s)", method, path, type(error).__name__)
            raise StorageError("storage_unavailable",
                               "파일 저장소에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.") from error
        if response.status_code >= 400:
            log.warning("Storage 오류 응답: %s %s -> HTTP %s", method, path, response.status_code)
            try:
                body = response.json()
            except ValueError:
                body = {}
            reason = body.get("code", body.get("error")) if isinstance(body, dict) else None
            code = "storage_http_error"
            if reason in {"ResourceAlreadyExists", "KeyAlreadyExists", "Duplicate"}:
                code = "object_exists"
            elif reason in {"NoSuchKey", "not_found"} or response.status_code == 404:
                code = "object_not_found"
            raise StorageError(code,
                               f"파일 저장소 오류입니다(HTTP {response.status_code}). 잠시 후 다시 시도해 주세요.",
                               status_code=response.status_code)
        return response

    def upload(self, object_key: str, data: bytes, content_type: str) -> None:
        """표준 업로드. object key는 서버가 만든 값만 받는다(원래 파일명·`..` 금지)."""
        self._request("POST", f"/object/{self.bucket}/{object_key}", content=data,
                      extra_headers={"Content-Type": content_type}).read()

    def download(self, object_key: str) -> bytes:
        return self._request("GET", f"/object/{self.bucket}/{object_key}").content

    def delete(self, object_key: str) -> None:
        """객체 삭제. 이미 없는 객체는 성공으로 본다(멱등). 그 외 실패는 StorageError."""
        try:
            self._request("DELETE", f"/object/{self.bucket}/{object_key}")
        except StorageError as error:
            if error.code == "object_not_found":
                return
            raise

    def list_objects(self, prefix: str = "") -> list[dict]:
        """폴더와 페이지를 순회해 전체 object key·생성 시각·크기를 돌려준다."""
        entries: list[dict] = []
        folders, visited = [prefix], set()
        while folders:
            folder = folders.pop()
            if folder in visited:
                continue
            visited.add(folder)
            offset = 0
            while True:
                page = self._request("POST", f"/object/list/{self.bucket}", json={
                    "prefix": folder, "limit": LIST_PAGE_SIZE, "offset": offset,
                    "sort_by": {"column": "name", "order": "asc"},
                }).json()
                if not isinstance(page, list):
                    raise StorageError("storage_http_error", "파일 저장소의 객체 목록을 읽지 못했습니다.")
                for entry in page:
                    if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                        continue
                    name = entry["name"]
                    if not name or name in {".", ".."} or "/" in name:
                        raise StorageError("storage_http_error", "파일 저장소의 객체 경로를 읽지 못했습니다.")
                    key = f"{folder}/{name}" if folder else name
                    if entry.get("id") is None and entry.get("metadata") is None:
                        folders.append(key)
                    else:
                        entries.append({**entry, "name": key})
                if len(page) < LIST_PAGE_SIZE:
                    break
                offset += LIST_PAGE_SIZE
        return entries
