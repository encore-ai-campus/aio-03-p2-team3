"""공식 PostgresSaver 조립. 공개 브라우저 역할은 체크포인트를 읽을 수 없다."""
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


@contextmanager
def checkpoints(database):
    conninfo = database.engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with ConnectionPool(conninfo, min_size=1, max_size=3, timeout=10,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row,
                    "options": "-c search_path=public"}) as pool:
        pool.wait(timeout=10)
        with pool.connection() as connection:
            connection.execute("SELECT pg_advisory_lock(2026111801)")
            try:
                PostgresSaver(connection).setup()
                for name in ("checkpoint_migrations", "checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                    connection.execute(f"ALTER TABLE public.{name} ENABLE ROW LEVEL SECURITY")
                    connection.execute(f"REVOKE ALL ON public.{name} FROM PUBLIC")
                    for role in ("anon", "authenticated"):
                        if connection.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                            connection.execute(f"REVOKE ALL ON public.{name} FROM {role}")
            finally:
                connection.execute("SELECT pg_advisory_unlock(2026111801)")
        yield PostgresSaver(pool)
