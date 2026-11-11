"""단일 프로세스의 사용자별 DB 접근 직렬화. 프로세스 사이는 DB 버전 조건으로 보호한다."""
from threading import Lock, RLock
from weakref import WeakKeyDictionary

_guard = Lock()
_locks = WeakKeyDictionary()


def user_lock(database, user_id: int):
    with _guard:
        return _locks.setdefault(database, {}).setdefault(user_id, RLock())
