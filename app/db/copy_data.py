"""기존 DB 데이터를 앱 PostgreSQL로 복사·대조하는 일회성 명령(계획 4절).

사용:
    uv run python -m app.db.copy_data --source app/db/local.sqlite3            # 계획 확인만
    uv run python -m app.db.copy_data --source app/db/local.sqlite3 --dry-run  # 쓰기 없이 행 수 확인
    uv run python -m app.db.copy_data --source app/db/local.sqlite3 --yes      # 복사 실행

정책:
- 원본: `--source`에 SQLite 파일 경로를 주면 원본은 고치지 않고 임시 사본을 최신 스키마로
  갱신해 읽는다. DB URL을 주면 그대로 읽고, 스키마가 앱보다 오래면 실패한다.
- 대상: PostgreSQL만 받는다(`--target`, 비우면 DATABASE_URL). 쓰기에는 `--yes`가 필요하다.
- 반복 실행: 대상이 비어 있으면 복사하고, 원본과 같으면 다시 쓰지 않고 대조만 통과한다.
  원본과 다른 데이터가 대상에 이미 있으면 합쳐 쓰지 않고 실패한다(기준 원본은 사람이 정한다).
- 중단 지점: 복사·시퀀스 정렬은 대상의 한 트랜잭션에서만 일어난다. 실패하면 전부 롤백되고
  다시 실행할 수 있다.
"""
from argparse import ArgumentParser
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from shutil import copy2
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import BigInteger, Integer, func, inspect, select, text
from sqlalchemy.engine import Connection, Engine

from app.config import POSTGRES_URL_SCHEMES, get_settings
from app.db.engine import Database
from app.db.migrations import upgrade_database
from app.db.models import Base

BATCH_SIZE = 500


def _masked(url: str) -> str:
    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.hostname or ""
    netloc = f"{parts.username}:***@{host}" if parts.username else host
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit(parts._replace(netloc=netloc))


def _postgres_target(url: str) -> str:
    url = url.strip()
    if url.split(":", 1)[0].lower() not in POSTGRES_URL_SCHEMES:
        raise ValueError(f"대상은 PostgreSQL 주소여야 합니다: {_masked(url) or '(값 없음)'}")
    return url


def _resolve_source(source: str, workdir: Path) -> tuple[str, bool]:
    """원본 URL. 파일 경로면 임시 사본을 만들어 갱신해 읽는다(원본은 고치지 않는다)."""
    source = source.strip()
    if "://" in source:
        return source, False
    path = Path(source)
    if not path.is_file():
        raise ValueError(f"원본 파일이 없습니다: {source}")
    copied = workdir / path.name
    copy2(path, copied)
    upgrade_database(Database(f"sqlite:///{copied}").engine)
    return f"sqlite:///{copied}", True


def _source_gaps(engine: Engine) -> dict[str, list[str]]:
    """원본 스키마가 앱보다 오래면 부족한 열을 표별로 돌려준다. 없는 표는 0행 취급한다."""
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    gaps: dict[str, list[str]] = {}
    for table in Base.metadata.sorted_tables:
        if table.name not in existing:
            continue
        columns = {column["name"] for column in inspector.get_columns(table.name)}
        missing = sorted(column.name for column in table.columns if column.name not in columns)
        if missing:
            gaps[table.name] = missing
    return gaps


def _table_counts(engine: Engine) -> tuple[dict[str, int], list[str]]:
    """표별 행 수. 앱 표가 아직 없으면 그 이름을 따로 돌려준다."""
    existing = set(inspect(engine).get_table_names())
    counts: dict[str, int] = {}
    missing: list[str] = []
    with engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing:
                missing.append(table.name)
                continue
            counts[table.name] = connection.execute(select(func.count()).select_from(table)).scalar_one()
    return counts, missing


def _normalized(value):
    if isinstance(value, datetime):
        moment = value.replace(tzinfo=UTC) if value.tzinfo is None else value
        return moment.astimezone(UTC).isoformat()
    if isinstance(value, bytes):
        return f"sha256:{sha256(value).hexdigest()}"
    if isinstance(value, Decimal):
        return str(value)
    return value


def _rows(engine: Engine, table) -> list[tuple]:
    """PK 순서로 모든 행을 비교 가능한 값으로 정규해 돌려준다."""
    primary_key = list(table.primary_key.columns)
    statement = select(table).order_by(*primary_key) if primary_key else select(table)
    with engine.connect() as connection:
        return [tuple(_normalized(row[column]) for column in table.columns)
                for row in connection.execute(statement).mappings()]


@dataclass
class TableDiff:
    table: str
    source_rows: int
    target_rows: int
    keys: list[str]


def _compare(source: Engine, target: Engine) -> list[TableDiff]:
    """행 수·모든 열 값(소유자·외래 키·timestamp·JSON·금액 포함)을 표별로 비교한다."""
    diffs: list[TableDiff] = []
    for table in Base.metadata.sorted_tables:
        source_rows = _rows(source, table)
        target_rows = _rows(target, table)
        if source_rows == target_rows:
            continue
        indices = [list(table.columns).index(column) for column in table.primary_key.columns]
        source_map = {tuple(row[index] for index in indices): row for row in source_rows}
        target_map = {tuple(row[index] for index in indices): row for row in target_rows}
        changed = [key for key in source_map.keys() | target_map.keys()
                   if source_map.get(key) != target_map.get(key)]
        diffs.append(TableDiff(table.name, len(source_rows), len(target_rows),
                               [str(key) for key in sorted(changed, key=str)[:5]]))
    return diffs


def _integer_pk_tables():
    for table in Base.metadata.sorted_tables:
        columns = list(table.primary_key.columns)
        if len(columns) == 1 and columns[0].autoincrement and isinstance(columns[0].type, (Integer, BigInteger)):
            yield table, columns[0].name


def _sync_sequences(connection: Connection) -> None:
    """복사한 PK 값 뒤로 자동 증가 시퀀스를 맞춘다(PostgreSQL)."""
    for table, column in _integer_pk_tables():
        connection.execute(text(
            f"SELECT setval(pg_get_serial_sequence(:table_name, :column_name),"
            f" COALESCE((SELECT MAX({column}) FROM {table.name}), 1),"
            f" (SELECT MAX({column}) FROM {table.name}) IS NOT NULL)"),
            {"table_name": table.name, "column_name": column})


def _sequence_problems(engine: Engine) -> list[str]:
    """시퀀스가 PK 최댓값과 어긋나면 표별 문제를 돌려준다."""
    problems: list[str] = []
    with engine.connect() as connection:
        for table, column in _integer_pk_tables():
            sequence = connection.execute(
                text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                {"table_name": table.name, "column_name": column}).scalar()
            if sequence is None:
                continue
            last_value, is_called = connection.execute(
                text(f"SELECT last_value, is_called FROM {sequence}")).one()
            maximum = connection.execute(text(f"SELECT MAX({column}) FROM {table.name}")).scalar()
            expected = (1, False) if maximum is None else (maximum, True)
            if (int(last_value), bool(is_called)) != expected:
                problems.append(
                    f"{table.name}: sequence {sequence}이(가) {last_value}(is_called={is_called})인데 기대값은 {expected}")
    return problems


def _insert_rows(connection: Connection, table, rows: list[dict]) -> None:
    for start in range(0, len(rows), BATCH_SIZE):
        connection.execute(table.insert(), rows[start:start + BATCH_SIZE])


def _copy(source: Engine, target: Engine) -> None:
    """대상 한 트랜잭션으로 전체를 복사한다. 실패하면 전부 롤백된다(중단 지점)."""
    with target.begin() as connection:
        for table in Base.metadata.sorted_tables:
            with source.connect() as source_connection:
                rows = [{column.name: row[column] for column in table.columns}
                        for row in source_connection.execute(table.select()).mappings()]
            _insert_rows(connection, table, rows)
            print(f"  {table.name}: {len(rows)}행 복사")
        _sync_sequences(connection)
    print("복사 커밋: 복사·시퀀스 정렬까지 한 트랜잭션이었다(이 전 실패는 전부 롤백).")


def _print_plan(source_counts: dict[str, int], target_counts: dict[str, int], missing: list[str]) -> None:
    print(f"복사할 행 합계: {sum(source_counts.values())}")
    for table in Base.metadata.sorted_tables:
        note = " (대상에 표 없음)" if table.name in missing else ""
        print(f"  {table.name}: 원본 {source_counts.get(table.name, 0)}행 / 대상 {target_counts.get(table.name, 0)}행{note}")


def _print_diffs(diffs: list[TableDiff]) -> None:
    for diff in diffs:
        print(f"  {diff.table}: 원본 {diff.source_rows}행 / 대상 {diff.target_rows}행,"
              f" 다른 키(최대 5): {', '.join(diff.keys) or '없음'}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = ArgumentParser(description="기존 DB 데이터를 앱 PostgreSQL로 복사·대조한다(일회성, 계획 4절).")
    parser.add_argument("--source", required=True, help="원본: SQLite 파일 경로 또는 DB URL")
    parser.add_argument("--target", default="", help="대상 PostgreSQL 주소(비우면 DATABASE_URL)")
    parser.add_argument("--dry-run", action="store_true", help="쓰기 없이 행 수·계획만 확인한다")
    parser.add_argument("--yes", action="store_true", help="대상을 확인했음을 선언하고 복사를 실행한다")
    args = parser.parse_args(argv)

    try:
        target_url = _postgres_target(args.target) if args.target.strip() else get_settings().resolved_database_url
    except ValueError as error:
        print(f"대상 오류: {error}")
        return 2

    with TemporaryDirectory(prefix="app-db-copy-") as workdir:
        try:
            source_url, upgraded_copy = _resolve_source(args.source, Path(workdir))
        except ValueError as error:
            print(f"원본 오류: {error}")
            return 2
        source = Database(source_url)
        target = Database(target_url)
        try:
            if str(source.engine.url) == str(target.engine.url):
                print("원본 오류: 원본과 대상이 같은 DB입니다.")
                return 2
            gaps = _source_gaps(source.engine)
            if gaps:
                print("원본 오류: 스키마가 앱보다 오래합니다. SQLite 파일은 경로로 지정하면 임시 사본을 갱신해 복사합니다.")
                for name, missing in gaps.items():
                    print(f"  {name}에 없는 열: {', '.join(missing)}")
                return 2
            print(f"원본: {_masked(source_url)}" + (" (원본은 그대로 두고 임시 사본을 갱신해 읽음)" if upgraded_copy else ""))
            print(f"대상: {_masked(target_url)}")
            source_counts, _ = _table_counts(source.engine)
            target_counts, target_missing = _table_counts(target.engine)
            _print_plan(source_counts, target_counts, target_missing)
            if args.dry_run:
                print("dry-run: 쓰지 않고 끝낸다.")
                return 0
            if not args.yes:
                print("대상 확인: 위 대상이 맞으면 --yes를 주어 복사한다.")
                return 2
            if any(target_counts.values()):
                diffs = _compare(source.engine, target.engine)
                if diffs:
                    print("대상 오류: 대상에 원본과 다른 데이터가 있어 합쳐 쓰지 않는다."
                          " 기준 원본을 정한 뒤 대상을 비우고 다시 실행한다.")
                    _print_diffs(diffs)
                    return 1
                problems = _sequence_problems(target.engine)
                if problems:
                    print("대조 실패: 시퀀스가 PK와 어긋난다.")
                    for problem in problems:
                        print(f"  {problem}")
                    return 1
                print("이미 복사됨: 대조 통과(다시 쓰지 않음).")
                return 0
            upgrade_database(target.engine)
            try:
                _copy(source.engine, target.engine)
            except Exception as error:
                print(f"복사 실패({type(error).__name__}): 트랜잭션을 롤백했다. 원본은 그대로고 다시 실행할 수 있다.")
                return 1
            diffs = _compare(source.engine, target.engine)
            problems = _sequence_problems(target.engine)
            if diffs or problems:
                print("복사했지만 대조가 실패했다. 대상을 비우고 다시 실행한다.")
                _print_diffs(diffs)
                for problem in problems:
                    print(f"  {problem}")
                return 1
            print("대조 통과: 행 수·모든 열 값·PK/시퀀스가 원본과 같다.")
            return 0
        finally:
            source.close()
            target.close()


if __name__ == "__main__":
    raise SystemExit(main())
