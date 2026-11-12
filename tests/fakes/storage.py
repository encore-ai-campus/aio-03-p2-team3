"""가짜 비공개 Storage 버킷 — `StorageClient`와 같은 메서드만 제공한다(계획 8절 검증).

실패 주입(`upload_error`·`download_error`·`delete_error`)으로 업로드 성공+SQL 실패·삭제 실패를
시험한다. 실제 Supabase HTTP는 부르지 않는다.
"""
from datetime import UTC, datetime, timedelta

from app.files.storage import StorageError


def storage_error(message="파일 저장소에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.") -> StorageError:
    return StorageError("storage_unavailable", message)


class FakeStorage:
    def __init__(self, bucket="trade-files"):
        self.bucket = bucket
        self.objects: dict[str, bytes] = {}
        self.created_at: dict[str, datetime] = {}
        self.content_types: dict[str, str] = {}
        self.upload_error: Exception | None = None
        self.download_error: Exception | None = None
        self.delete_error: Exception | None = None
        self.calls: list[tuple] = []

    def upload(self, object_key, data, content_type):
        self.calls.append(("upload", object_key))
        if self.upload_error is not None:
            raise self.upload_error
        self.objects[object_key] = data
        self.content_types[object_key] = content_type
        self.created_at[object_key] = datetime.now(UTC)

    def download(self, object_key):
        self.calls.append(("download", object_key))
        if self.download_error is not None:
            raise self.download_error
        if object_key not in self.objects:
            raise StorageError("storage_http_error", "파일 저장소 오류입니다(HTTP 404). 잠시 후 다시 시도해 주세요.")
        return self.objects[object_key]

    def delete(self, object_key):
        self.calls.append(("delete", object_key))
        if self.delete_error is not None:
            raise self.delete_error
        self.objects.pop(object_key, None)  # 없는 객체 삭제는 성공(멱등)
        self.created_at.pop(object_key, None)
        self.content_types.pop(object_key, None)

    def list_objects(self, prefix=""):
        entries = []
        for key, data in sorted(self.objects.items()):
            if not key.startswith(prefix):
                continue
            entry = {"name": key, "metadata": {"size": len(data)}}
            if key in self.created_at:  # 생성 시각을 알 수 없는 객체도 있다(정리 명령이 보수적으로 다룬다)
                entry["created_at"] = self.created_at[key].isoformat()
            entries.append(entry)
        return entries

    def age_object(self, object_key, hours):
        """정리 명령의 '충분히 오래된' 조건을 시험하기 위해 생성 시각을 되돌린다."""
        self.created_at[object_key] = datetime.now(UTC) - timedelta(hours=hours)
