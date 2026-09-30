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
from tests.integration.conftest import connect

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

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
    with connect() as conn:
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
    with connect() as conn:
        conn.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(name)))


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
        with connect(autocommit=False) as conn, conn.cursor() as cur:
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
        with connect(autocommit=False) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM timescaledb_information.chunks "
                "WHERE hypertable_name = %s AND is_compressed",
                (table,),
            )
            (count,) = cur.fetchone()
            return int(count)

    def _provenance(self, spec: BulkLoadSpec) -> tuple[str, int | None, int, str | None]:
        with connect(autocommit=False) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT status, row_count, attempts, error FROM provenance_batch "
                "WHERE batch_key = %s",
                (spec.batch_key,),
            )
            return cur.fetchone()  # type: ignore[no-any-return]

    def test_case_1_load_two_days_and_compress_both_chunks(self, table: str) -> None:
        spec = _spec(table, _DAY1, _RANGE_END)
        rows = _day_rows(_DAY1) + _day_rows(_DAY2)
        with connect(autocommit=False) as conn:
            result = bulk_load(conn, spec, _COLUMNS, rows, compress_before=_RANGE_END)
        assert result.status == "loaded"
        assert result.batch_key == spec.batch_key
        assert result.row_count == 8
        assert result.chunks_compressed == 2
        assert self._compressed_chunks(table) == 2
        assert self._count_rows(table) == 8
        with connect(autocommit=False) as conn, conn.cursor() as cur:
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
        with connect(autocommit=False) as conn:
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
        with connect(autocommit=False) as conn:
            with pytest.raises(BulkLoadRefused, match="compressed chunk"):
                bulk_load(conn, spec, _COLUMNS, _day_rows(_DAY1) + _day_rows(_DAY2))
        assert self._count_rows(table) == 8, "a refused load must add nothing"

    def test_case_4_out_of_order_day_fails_clean_and_retries(self, table: str) -> None:
        spec = _spec(table, _DAY3_START, _DAY3_END)
        out_of_order = [
            ("AAA", "1d", _DAY3_START.replace(hour=3), 1.0, 2.0),
            ("AAA", "1d", _DAY3_START.replace(hour=1), 1.0, 2.0),  # earlier than row 0
        ]
        with connect(autocommit=False) as conn:
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
        with connect(autocommit=False) as conn:
            result = bulk_load(conn, spec, _COLUMNS, ordered)
        assert result.status == "loaded"
        assert result.row_count == 4
        status, row_count, attempts, error = self._provenance(spec)
        assert (status, row_count, attempts, error) == ("completed", 4, 2, None)

    def test_case_5_real_clamped_double_precision_unchanged(self, table: str) -> None:
        spec = _spec(table, _DAY4_START, _DAY4_END)
        rows = [("AAA", "1d", _DAY4_START.replace(hour=1), 1e-50, 1e-50)]
        with connect(autocommit=False) as conn:
            result = bulk_load(conn, spec, _COLUMNS, rows)
        assert result.status == "loaded"
        with connect(autocommit=False) as conn, conn.cursor() as cur:
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
            with connect(autocommit=False) as conn, conn.cursor() as cur:
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
            with connect(autocommit=False) as conn:
                with pytest.raises(BulkLoadRefused, match="compression policy"):
                    bulk_load(conn, spec, _COLUMNS, rows)
            with connect(autocommit=False) as conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT job_id FROM timescaledb_information.jobs "
                    "WHERE hypertable_name = %s AND proc_name = 'policy_compression'",
                    (table,),
                )
                (job_id,) = cur.fetchone()
                cur.execute("SELECT alter_job(%s, scheduled => false)", (job_id,))
                conn.commit()
            with connect(autocommit=False) as conn:
                result = bulk_load(conn, spec, _COLUMNS, rows)
            assert result.status == "loaded"
            assert result.row_count == 2
        finally:
            _drop_table(table)

    def test_case_7_guard_triggers_refuse_edit_and_delete(self, table: str) -> None:
        completed_key = _spec(table, _DAY1, _RANGE_END).batch_key
        with connect(autocommit=False) as conn, conn.cursor() as cur:
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    "UPDATE provenance_batch SET row_count = 0 WHERE batch_key = %s",
                    (completed_key,),
                )
            conn.rollback()
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute("DELETE FROM provenance_batch")
            conn.rollback()


class TestBulkLoadReplaceIntegration:
    """replace_where on a real hypertable (186-14): the unit's old rows go, the new rows land,
    and the previous key's provenance row flips to superseded, in one transaction."""

    @pytest.fixture(scope="class")
    def table(self) -> str:
        name = _name()
        _create_scratch_hypertable(name)
        yield name
        _drop_table(name)

    def _rows(self, table: str) -> list[tuple]:
        with connect(autocommit=False) as conn, conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT symbol, bar_ts, x FROM {} ORDER BY symbol, bar_ts").format(
                    sql.Identifier(table)
                )
            )
            return cur.fetchall()

    def _status(self, spec: BulkLoadSpec) -> str:
        with connect(autocommit=False) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM provenance_batch WHERE batch_key = %s", (spec.batch_key,)
            )
            return cur.fetchone()[0]

    def test_replace_swaps_the_unit_and_supersedes_the_previous_key(self, table: str) -> None:
        where = {"symbol": ["AAA", "BBB"], "tf": "1d"}
        first = _spec(table, _DAY1, _RANGE_END, apr_snapshot={"v": "1"}, replace_where=where)
        with connect(autocommit=False) as conn:
            bulk_load(conn, first, _COLUMNS, _day_rows(_DAY1, x=1.0) + _day_rows(_DAY2, x=1.0))
        # rows outside the predicate (another symbol) that must survive
        other = _spec(table, _DAY1, _RANGE_END, symbols=("CCC",), writer="other_unit")
        with connect(autocommit=False) as conn:
            bulk_load(conn, other, _COLUMNS, [("CCC", "1d", _DAY1.replace(hour=1), 9.0, 9.0)])
        second = _spec(table, _DAY1, _RANGE_END, apr_snapshot={"v": "2"}, replace_where=where)
        with connect(autocommit=False) as conn:
            result = bulk_load(
                conn, second, _COLUMNS, _day_rows(_DAY1, x=5.0) + _day_rows(_DAY2, x=5.0)
            )
        assert result.status == "loaded"
        assert result.rows_replaced == 8
        assert result.row_count == 8
        rows = self._rows(table)
        assert [r for r in rows if r[0] != "CCC"] and all(
            r[2] == 5.0 for r in rows if r[0] != "CCC"
        )
        assert [r for r in rows if r[0] == "CCC"][0][2] == 9.0
        assert self._status(first) == "superseded"
        assert self._status(second) == "completed"
        assert self._status(other) == "completed"  # a different writer is never flipped

    def test_a_superseded_identity_cannot_come_back(self, table: str) -> None:
        first = _spec(
            table,
            _DAY1,
            _RANGE_END,
            apr_snapshot={"v": "1"},
            replace_where={"symbol": ["AAA", "BBB"], "tf": "1d"},
        )
        with connect(autocommit=False) as conn:
            with pytest.raises(BulkLoadRefused, match="superseded"):
                bulk_load(conn, first, _COLUMNS, _day_rows(_DAY1))

    def test_a_different_symbol_set_replaces_the_unit_instead_of_loading_beside_it(
        self, table: str
    ) -> None:
        where = {"tf": "1d", "symbol": ["AAA", "BBB", "CCC"]}
        narrow = _spec(
            table, _DAY3_START, _DAY3_END, writer="unit_key_symbols", replace_where=where
        )
        wide = _spec(
            table,
            _DAY3_START,
            _DAY3_END,
            writer="unit_key_symbols",
            replace_where=where,
            symbols=("AAA", "BBB", "CCC"),
        )
        assert narrow.unit_key == wide.unit_key and narrow.batch_key != wide.batch_key
        rows = _day_rows(_DAY3_START, x=1.0)
        with connect(autocommit=False) as conn:
            bulk_load(conn, narrow, _COLUMNS, rows)
        with connect(autocommit=False) as conn:
            result = bulk_load(
                conn,
                wide,
                _COLUMNS,
                [*rows, ("CCC", "1d", _DAY3_START.replace(hour=5), 1.0, 2.0)],
            )
        assert result.rows_replaced == 4
        assert self._status(narrow) == "superseded" and self._status(wide) == "completed"
        with connect(autocommit=False) as conn, conn.cursor() as cur:
            cur.execute(
                sql.SQL("SELECT count(*) FROM {} WHERE bar_ts >= %s").format(sql.Identifier(table)),
                (_DAY3_START,),
            )
            assert cur.fetchone()[0] == 5


class TestBarContentDigestsIntegration:
    def test_composition_changes_only_for_the_changed_symbol(self) -> None:
        from services._batch_utils import bar_content_digests

        tag = uuid4().hex[:6].upper()
        s1, s2, s3 = f"DG1{tag}", f"DG2{tag}", f"DG3{tag}"
        jan, feb, mar = (datetime(2031, m, 1, tzinfo=UTC) for m in (1, 2, 3))
        end = datetime(2031, 4, 1, tzinfo=UTC)

        def _insert(conn: psycopg.Connection, symbol: str, month: datetime, digest: str) -> None:
            nxt = (month + timedelta(days=32)).replace(day=1)
            conn.execute(
                "INSERT INTO bar_content_digest (symbol, timeframe, range_start, range_end, "
                "digest, algorithm, rule_version, n_rows) VALUES (%s, '1d', %s, %s, %s, "
                "'sha256-bars-v1', 'test', 1)",
                (symbol, month, nxt, digest),
            )

        with connect(autocommit=False) as conn:
            for symbol in (s1, s2):
                for month, digest in ((jan, "a"), (mar, "c")):  # February is a hole
                    _insert(conn, symbol, month, digest)
            conn.commit()
            before = bar_content_digests(conn, "1d", [s1, s2, s3], jan, end)
            assert before[s3] == "absent"
            assert before[s1] == before[s2]
            _insert(conn, s1, mar, "C")  # a later row supersedes March for s1 only
            conn.commit()
            after = bar_content_digests(conn, "1d", [s1, s2, s3], jan, end)
            assert after[s1] != before[s1]
            assert after[s2] == before[s2]
            _insert(conn, s2, feb, "b")  # the hole gains a row: the digest flips
            conn.commit()
            filled = bar_content_digests(conn, "1d", [s1, s2, s3], jan, end)
            assert filled[s2] != after[s2]
