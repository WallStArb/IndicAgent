"""Integration test: bulk_load on a real TimescaleDB scratch hypertable (phase 186, D-24).

Proves in the database, not only against fakes: COPY lands rows, per-chunk
compress_chunk keeps the primary key, the provenance batch makes a rerun a no-op,
refusals fire for real (compression policy, compressed chunk in range), per-unit
failure isolation leaves zero rows and a failed provenance row, the float32 clamp
follows the live schema, and migration 386's guard triggers refuse edits and
deletes.

Runs against indicagent_test (migrations replayed by tests/integration/conftest.py,
so migration 386 is exercised here too). The scratch table is dropped in a
finalizer; provenance rows are left in place because the table forbids DELETE and
the test database is rebuilt per session.

Run: pytest tests/integration/test_bulk_load.py -m integration
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from services._batch_utils import BulkLoadRefused, BulkLoadSpec, bulk_load

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"

_DAY1 = datetime(2027, 1, 4, tzinfo=UTC)
_DAY2 = datetime(2027, 1, 5, tzinfo=UTC)
_RANGE_END = datetime(2027, 1, 6, tzinfo=UTC)
_DAY3_START = datetime(2027, 1, 7, tzinfo=UTC)
_DAY3_END = datetime(2027, 1, 8, tzinfo=UTC)
_DAY4_START = datetime(2027, 1, 9, tzinfo=UTC)
_DAY4_END = datetime(2027, 1, 10, tzinfo=UTC)

_COLUMNS = ["symbol", "tf", "bar_ts", "x", "y"]


def _name() -> str:
    return f"_bulk_load_{uuid4().hex[:8]}"


def _create_scratch_hypertable(name: str) -> None:
    with psycopg.connect(_TEST_DB_URL, autocommit=True) as conn:
        conn.execute(
            sql.SQL(
                "CREATE TABLE {} (symbol text, tf text, bar_ts timestamptz, "
                "x real, y double precision, PRIMARY KEY (symbol, tf, bar_ts))"
            ).format(sql.Identifier(name))
        )
        conn.execute(
            "SELECT create_hypertable(%s::regclass, 'bar_ts', "
            "chunk_time_interval => INTERVAL '1 day')",
            (name,),
        )
        conn.execute(
            sql.SQL(
                "ALTER TABLE {} SET (timescaledb.compress, "
                "timescaledb.compress_segmentby = 'symbol,tf')"
            ).format(sql.Identifier(name))
        )


def _drop_table(name: str) -> None:
    with psycopg.connect(_TEST_DB_URL, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(name)))


def _connect() -> psycopg.Connection:
    return psycopg.connect(_TEST_DB_URL, autocommit=False)


def _spec(table: str, start: datetime, end: datetime, **overrides: object) -> BulkLoadSpec:
    fields: dict[str, object] = dict(
        writer="bulk_load_integration_test",
        target_table=table,
        time_column="bar_ts",
        tf="1d",
        range_start=start,
        range_end=end,
        symbols=("AAA", "BBB"),
        code_key="a" * 64,
        apr_snapshot={"infra.bulk_load.integration": "1"},
        input_digest="b" * 64,
    )
    fields.update(overrides)
    return BulkLoadSpec(**fields)  # type: ignore[arg-type]


def _day_rows(day: datetime, *, x: float = 1.0, y: float = 2.0) -> list[tuple]:
    return [
        ("AAA", "1d", day.replace(hour=1), x, y),
        ("BBB", "1d", day.replace(hour=1), x, y),
        ("AAA", "1d", day.replace(hour=3), x, y),
        ("BBB", "1d", day.replace(hour=3), x, y),
    ]


class TestBulkLoadIntegration:
    @pytest.fixture(scope="class")
    def table(self) -> str:
        name = _name()
        _create_scratch_hypertable(name)
        yield name
        _drop_table(name)

    def _count_rows(self, table: str, since: datetime | None = None) -> int:
        with _connect() as conn, conn.cursor() as cur:
            if since is None:
                cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
            else:
                cur.execute(
                    sql.SQL("SELECT count(*) FROM {} WHERE bar_ts >= %s").format(
                        sql.Identifier(table)
                    ),
                    (since,),
                )
            (count,) = cur.fetchone()
            return int(count)

    def _compressed_chunks(self, table: str) -> int:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM timescaledb_information.chunks "
                "WHERE hypertable_name = %s AND is_compressed",
                (table,),
            )
            (count,) = cur.fetchone()
            return int(count)

    def _provenance(self, spec: BulkLoadSpec) -> tuple[str, int | None, int, str | None]:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT status, row_count, attempts, error FROM provenance_batch "
                "WHERE batch_key = %s",
                (spec.batch_key,),
            )
            return cur.fetchone()  # type: ignore[no-any-return]

    def test_case_1_load_two_days_and_compress_both_chunks(self, table: str) -> None:
        spec = _spec(table, _DAY1, _RANGE_END)
        rows = _day_rows(_DAY1) + _day_rows(_DAY2)
        with _connect() as conn:
            result = bulk_load(conn, spec, _COLUMNS, rows, compress_before=_RANGE_END)
        assert result.status == "loaded"
        assert result.batch_key == spec.batch_key
        assert result.row_count == 8
        assert result.chunks_compressed == 2
        assert self._compressed_chunks(table) == 2
        assert self._count_rows(table) == 8
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pg_constraint con JOIN pg_class rel "
                "ON rel.oid = con.conrelid WHERE rel.relname = %s AND con.contype = 'p'",
                (table,),
            )
            (pk_count,) = cur.fetchone()
        assert pk_count == 1, "the primary key must survive per-chunk compression"
        status, row_count, _attempts, error = self._provenance(spec)
        assert (status, row_count, error) == ("completed", 8, None)

    def test_case_2_rerun_identical_spec_is_a_no_op(self, table: str) -> None:
        spec = _spec(table, _DAY1, _RANGE_END)
        rows = _day_rows(_DAY1) + _day_rows(_DAY2)
        with _connect() as conn:
            result = bulk_load(conn, spec, _COLUMNS, rows, compress_before=_RANGE_END)
        assert result.status == "skipped"
        assert result.row_count == 8
        assert self._count_rows(table) == 8, "rerun must not add rows"
        assert result.chunks_compressed == 0
        status, _row_count, attempts, _error = self._provenance(spec)
        assert attempts == 1, "a skipped rerun must not touch the provenance row"

    def test_case_3_changed_apr_hits_compressed_chunk_and_refuses(self, table: str) -> None:
        spec = _spec(table, _DAY1, _RANGE_END, apr_snapshot={"infra.bulk_load.integration": "2"})
        assert spec.batch_key != _spec(table, _DAY1, _RANGE_END).batch_key
        with _connect() as conn:
            with pytest.raises(BulkLoadRefused, match="compressed chunk"):
                bulk_load(conn, spec, _COLUMNS, _day_rows(_DAY1) + _day_rows(_DAY2))
        assert self._count_rows(table) == 8, "a refused load must add nothing"

    def test_case_4_out_of_order_day_fails_clean_and_retries(self, table: str) -> None:
        spec = _spec(table, _DAY3_START, _DAY3_END)
        out_of_order = [
            ("AAA", "1d", _DAY3_START.replace(hour=3), 1.0, 2.0),
            ("AAA", "1d", _DAY3_START.replace(hour=1), 1.0, 2.0),  # earlier than row 0
        ]
        with _connect() as conn:
            with pytest.raises(ValueError, match="row 1"):
                bulk_load(conn, spec, _COLUMNS, out_of_order)
        assert self._count_rows(table, since=_DAY3_START) == 0, "failed unit adds zero rows"
        status, row_count, attempts, error = self._provenance(spec)
        assert status == "failed"
        assert row_count is None
        assert attempts == 1
        assert error is not None and "row 1" in error

        ordered = [
            ("AAA", "1d", _DAY3_START.replace(hour=1), 1.0, 2.0),
            ("BBB", "1d", _DAY3_START.replace(hour=1), 1.0, 2.0),
            ("AAA", "1d", _DAY3_START.replace(hour=3), 1.0, 2.0),
            ("BBB", "1d", _DAY3_START.replace(hour=3), 1.0, 2.0),
        ]
        with _connect() as conn:
            result = bulk_load(conn, spec, _COLUMNS, ordered)
        assert result.status == "loaded"
        assert result.row_count == 4
        status, row_count, attempts, error = self._provenance(spec)
        assert (status, row_count, attempts, error) == ("completed", 4, 2, None)

    def test_case_5_real_clamped_double_precision_unchanged(self, table: str) -> None:
        spec = _spec(table, _DAY4_START, _DAY4_END)
        rows = [("AAA", "1d", _DAY4_START.replace(hour=1), 1e-50, 1e-50)]
        with _connect() as conn:
            result = bulk_load(conn, spec, _COLUMNS, rows)
        assert result.status == "loaded"
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT x, y FROM {} WHERE bar_ts >= %s").format(sql.Identifier(table)),
                (_DAY4_START,),
            )
            x, y = cur.fetchone()
        assert x == 0.0, "real column must land clamped to the float32 range"
        assert y == pytest.approx(1e-50), "double precision column must be unchanged"

    def test_case_6_compression_policy_refuses_paused_policy_allows(self) -> None:
        table = _name()
        _create_scratch_hypertable(table)
        try:
            with _connect() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT add_compression_policy(%s, compress_after => INTERVAL '1 day')",
                    (table,),
                )
                conn.commit()
            old_start = datetime.now(UTC) - timedelta(days=10)
            spec = _spec(table, old_start, old_start + timedelta(days=2))
            rows = [
                ("AAA", "1d", old_start + timedelta(hours=1), 1.0, 2.0),
                ("BBB", "1d", old_start + timedelta(hours=2), 3.0, 4.0),
            ]
            with _connect() as conn:
                with pytest.raises(BulkLoadRefused, match="compression policy"):
                    bulk_load(conn, spec, _COLUMNS, rows)
            with _connect() as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT job_id FROM timescaledb_information.jobs "
                    "WHERE hypertable_name = %s AND proc_name = 'policy_compression'",
                    (table,),
                )
                (job_id,) = cur.fetchone()
                cur.execute("SELECT alter_job(%s, scheduled => false)", (job_id,))
                conn.commit()
            with _connect() as conn:
                result = bulk_load(conn, spec, _COLUMNS, rows)
            assert result.status == "loaded"
            assert result.row_count == 2
        finally:
            _drop_table(table)

    def test_case_7_guard_triggers_refuse_edit_and_delete(self, table: str) -> None:
        completed_key = _spec(table, _DAY1, _RANGE_END).batch_key
        with _connect() as conn, conn.cursor() as cur:
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    "UPDATE provenance_batch SET row_count = 0 WHERE batch_key = %s",
                    (completed_key,),
                )
            conn.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("DELETE FROM provenance_batch")
            conn.rollback()
