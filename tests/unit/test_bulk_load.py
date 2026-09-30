"""Fake-connection unit tests of services._batch_utils.bulk_load (phase 186 plan 06, D-24).

Covers the statement sequence, idempotency through the provenance batch row, the
live-schema float32 clamp, every refusal, and per-unit failure isolation (todos 301,
343, 352 absorbed into this one primitive).

The connection is the shared tests/unit/_responder_fakes.FakeConn answering in order (`scripted`),
with an interleaved event log (executes, commits, rollbacks, COPY rows in one ordered stream);
the write-session double in tests/unit/_compressed_hypertable_write_session_fakes.py replays a fixed
call shape and is not reused here.

CI-clean: no DB, no network.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import services._batch_utils as batch_utils
from services._batch_utils import (
    BulkLoadRefused,
    BulkLoadSpec,
    bulk_load,
)
from tests.unit._responder_fakes import FakeConn, scripted


def _conn(responses: list[dict] | None = None) -> FakeConn:
    """The fake connection answering `responses` in order, one per fetched statement."""
    return FakeConn(scripted(responses))


# ---------------------------------------------------------------------------
# Shared scripting
# ---------------------------------------------------------------------------

_LOCKED = {"fetchone": (True,)}
_LOCK_REFUSED = {"fetchone": (False,)}
_COLUMNS = {
    "fetchall": [
        ("symbol", "text"),
        ("tf", "text"),
        ("bar_ts", "timestamptz"),
        ("x", "real"),
        ("y", "double precision"),
    ]
}
_IS_HYPERTABLE = {"fetchall": [("bar_ts",)]}
_NOT_HYPERTABLE = {"fetchall": []}
_NO_JOBS = {"fetchall": []}
_NO_COMPRESSED_CHUNKS = {"fetchone": (0,)}
_APR_COMPRESS_TRUE = {
    "fetchall": [
        ("infra.bulk_load.statement_timeout_ms", "14400000"),
        ("infra.bulk_load.compress_on_complete", "true"),
    ]
}
_APR_COMPRESS_FALSE = {
    "fetchall": [
        ("infra.bulk_load.statement_timeout_ms", "14400000"),
        ("infra.bulk_load.compress_on_complete", "false"),
    ]
}

_RANGE_START = datetime(2026, 1, 5, tzinfo=UTC)
_RANGE_END = datetime(2026, 1, 7, tzinfo=UTC)


def _spec(**overrides: Any) -> BulkLoadSpec:
    fields: dict[str, Any] = dict(
        writer="feature_vector_rebuild",
        target_table="feature_vectors",
        time_column="bar_ts",
        tf="1d",
        range_start=_RANGE_START,
        range_end=_RANGE_END,
        symbols=("SPY", "QQQ"),
        code_key="a" * 64,
        apr_snapshot={"alpha.ic.lookahead.fast": 1},
        input_digest="b" * 64,
    )
    fields.update(overrides)
    return BulkLoadSpec(**fields)


_COLUMNS_LIST = ["symbol", "tf", "bar_ts", "x", "y"]


def _ordered_rows() -> list[tuple]:
    return [
        ("SPY", "1d", datetime(2026, 1, 5, 14, 30, tzinfo=UTC), 1.0, 2.0),
        ("SPY", "1d", datetime(2026, 1, 5, 15, 0, tzinfo=UTC), 1.0, 2.0),
        ("QQQ", "1d", datetime(2026, 1, 6, 14, 30, tzinfo=UTC), 3.0, 4.0),
        ("QQQ", "1d", datetime(2026, 1, 6, 15, 0, tzinfo=UTC), 3.0, 4.0),
    ]


def _fresh_happy_responses(apr: dict | None = None) -> list[dict]:
    return [
        _LOCKED,
        {"fetchone": None},
        _COLUMNS,
        _IS_HYPERTABLE,
        _NO_JOBS,
        _NO_COMPRESSED_CHUNKS,
        apr or _APR_COMPRESS_TRUE,
    ]


# ---------------------------------------------------------------------------
# BulkLoadSpec identity and validation
# ---------------------------------------------------------------------------


class TestBulkLoadSpec:
    def test_symbols_stored_sorted_same_key_unsorted_input(self) -> None:
        sorted_spec = _spec(symbols=("AAA", "BBB"))
        unsorted_spec = _spec(symbols=("BBB", "AAA"))
        assert sorted_spec.symbols == ("AAA", "BBB")
        assert unsorted_spec.symbols == ("AAA", "BBB")
        assert sorted_spec.batch_key == unsorted_spec.batch_key

    def test_naive_datetimes_raise(self) -> None:
        with pytest.raises(ValueError, match="tz"):
            _spec(range_start=datetime(2026, 1, 5))
        with pytest.raises(ValueError, match="tz"):
            _spec(range_end=datetime(2026, 1, 7))

    def test_reversed_or_empty_range_raises(self) -> None:
        with pytest.raises(ValueError, match="range"):
            _spec(range_start=_RANGE_END, range_end=_RANGE_START)
        with pytest.raises(ValueError, match="range"):
            _spec(range_start=_RANGE_START, range_end=_RANGE_START)

    def test_empty_symbols_raise(self) -> None:
        with pytest.raises(ValueError, match="symbols"):
            _spec(symbols=())

    @pytest.mark.parametrize("field,value", [("code_key", "A" * 64), ("input_digest", "B" * 64)])
    def test_uppercase_hex_raises(self, field: str, value: str) -> None:
        with pytest.raises(ValueError, match="hex"):
            _spec(**{field: value})

    @pytest.mark.parametrize("field,value", [("code_key", "a" * 31), ("input_digest", "b" * 31)])
    def test_short_hex_raises(self, field: str, value: str) -> None:
        with pytest.raises(ValueError, match="hex"):
            _spec(**{field: value})

    def test_each_identity_field_changes_batch_key(self) -> None:
        base = _spec()
        mutations = {
            "writer": _spec(writer="other_writer"),
            "target_table": _spec(target_table="feature_ic_scores"),
            "tf": _spec(tf="15m"),
            "range_start": _spec(range_start=_RANGE_START - timedelta(days=1)),
            "range_end": _spec(range_end=_RANGE_END + timedelta(days=1)),
            "symbols": _spec(symbols=("SPY", "IWM")),
            "code_key": _spec(code_key="c" * 64),
            "apr_snapshot": _spec(apr_snapshot={"alpha.ic.lookahead.fast": 2}),
            "input_digest": _spec(input_digest="d" * 64),
        }
        for name, mutated in mutations.items():
            assert mutated.batch_key != base.batch_key, f"{name} must change batch_key"
        for mutated in mutations.values():
            assert len(mutated.batch_key) == 64

    def test_apr_hash_ignores_dict_insertion_order(self) -> None:
        a = _spec(apr_snapshot={"k1": 1, "k2": {"deep": [1, 2]}})
        b = _spec(apr_snapshot={"k2": {"deep": [1, 2]}, "k1": 1})
        assert a.apr_hash == b.apr_hash
        assert a.batch_key == b.batch_key

    def test_hashes_are_sha256_hex(self) -> None:
        spec = _spec()
        for digest in (spec.apr_hash, spec.symbols_hash, spec.batch_key):
            assert len(digest) == 64
            int(digest, 16)  # lowercase hex


# ---------------------------------------------------------------------------
# Idempotency: the completed provenance row short-circuits
# ---------------------------------------------------------------------------


class TestBulkLoadSkipsCompleted:
    def test_completed_row_returns_skipped_without_copy_or_insert(self) -> None:
        conn = _conn([_LOCKED, {"fetchone": ("completed", 4242, 1)}])
        result = bulk_load(conn, _spec(), _COLUMNS_LIST, _ordered_rows())
        assert result.status == "skipped"
        assert result.row_count == 4242
        assert result.chunks_compressed == 0
        assert conn.copied_rows == []
        assert conn.index_of("copy") is None
        assert conn.index_of("execute", "INSERT INTO provenance_batch") is None


# ---------------------------------------------------------------------------
# Fresh key: statement order and the loaded result
# ---------------------------------------------------------------------------


class TestBulkLoadFreshKey:
    def test_statement_order_lock_insert_commit_checks_copy_update_commit(self) -> None:
        conn = _conn(_fresh_happy_responses())
        result = bulk_load(conn, _spec(), _COLUMNS_LIST, _ordered_rows())
        assert result.status == "loaded"
        assert result.row_count == 4
        assert result.chunks_compressed == 0

        i_lock = conn.require_index("execute", "pg_try_advisory_lock")
        i_insert = conn.require_index("execute", "INSERT INTO provenance_batch")
        i_commit1 = conn.require_index("commit")
        i_columns = conn.require_index("execute", "information_schema.columns")
        i_dimensions = conn.require_index("execute", "timescaledb_information.dimensions")
        i_jobs = conn.require_index("execute", "policy_compression")
        i_chunks = conn.require_index("execute", "timescaledb_information.chunks")
        i_apr = conn.require_index("execute", "config_state")
        i_timeout = conn.require_index("execute", "statement_timeout")
        i_copy = conn.require_index("copy")
        i_update = conn.index_of("execute", "UPDATE provenance_batch")
        assert i_update is not None and "completed" in conn.events[i_update][1]
        i_commit2 = conn.require_index("execute", "pg_advisory_unlock")

        assert i_lock < i_insert < i_commit1 < i_columns < i_dimensions < i_jobs < i_chunks
        assert i_chunks < i_apr < i_timeout < i_copy < i_update < i_commit2
        assert conn.commits >= 2
        assert conn.index_of("execute", "compress_chunk") is None

    def test_rows_streamed_never_materialized(self) -> None:
        conn = _conn(_fresh_happy_responses())

        def _gen():
            yield from _ordered_rows()

        result = bulk_load(conn, _spec(), _COLUMNS_LIST, _gen())
        assert result.row_count == 4
        assert len(conn.copied_rows) == 4

    def test_stale_failed_row_is_taken_over_not_duplicated(self) -> None:
        conn = _conn([_LOCKED, {"fetchone": ("failed", None, 2)}] + _fresh_happy_responses()[2:])
        result = bulk_load(conn, _spec(), _COLUMNS_LIST, _ordered_rows())
        assert result.status == "loaded"
        takeover = conn.index_of("execute", "attempts = attempts + 1")
        assert takeover is not None, "takeover UPDATE with attempts increment missing"
        assert conn.index_of("execute", "INSERT INTO provenance_batch") is None

    def test_stale_started_row_is_taken_over(self) -> None:
        conn = _conn([_LOCKED, {"fetchone": ("started", None, 1)}] + _fresh_happy_responses()[2:])
        result = bulk_load(conn, _spec(), _COLUMNS_LIST, _ordered_rows())
        assert result.status == "loaded"
        assert conn.index_of("execute", "attempts = attempts + 1") is not None
        assert conn.index_of("execute", "INSERT INTO provenance_batch") is None

    def test_unlock_always_runs_on_success(self) -> None:
        conn = _conn(_fresh_happy_responses())
        bulk_load(conn, _spec(), _COLUMNS_LIST, _ordered_rows())
        assert conn.index_of("execute", "pg_advisory_unlock") is not None


# ---------------------------------------------------------------------------
# The live-schema float32 clamp (todo 312 drift class closed for this path)
# ---------------------------------------------------------------------------


class TestBulkLoadClamping:
    def test_real_column_clamped_double_precision_untouched(self) -> None:
        conn = _conn(_fresh_happy_responses())
        rows = [
            ("SPY", "1d", datetime(2026, 1, 5, 14, 30, tzinfo=UTC), 1e-50, 1e-50),
        ]
        bulk_load(conn, _spec(), _COLUMNS_LIST, rows)
        (written,) = conn.copied_rows
        assert written[3] == 0.0, "real column must carry the clamped value"
        assert written[4] == 1e-50, "double precision column must be unchanged"


# ---------------------------------------------------------------------------
# Per-unit failure isolation (todo 343)
# ---------------------------------------------------------------------------


class TestBulkLoadFailureIsolation:
    def test_out_of_order_row_raises_and_marks_failed(self) -> None:
        conn = _conn(_fresh_happy_responses())
        rows = _ordered_rows() + [
            ("SPY", "1d", datetime(2026, 1, 5, 14, 0, tzinfo=UTC), 9.0, 9.0),  # earlier than row 3
        ]
        with pytest.raises(ValueError, match="row 4"):
            bulk_load(conn, _spec(), _COLUMNS_LIST, rows)
        assert len(conn.copied_rows) == 4  # the bad row never reached the COPY buffer
        assert conn.rollbacks >= 1
        i_failed = conn.require_index("execute", "'failed'")
        assert "UPDATE provenance_batch" in conn.events[i_failed][1]
        assert conn.index_of("execute", "INSERT INTO provenance_batch") is not None  # started first

    def test_row_outside_range_raises(self) -> None:
        conn = _conn(_fresh_happy_responses())
        rows = [
            ("SPY", "1d", datetime(2026, 1, 4, 14, 30, tzinfo=UTC), 1.0, 2.0),  # before range_start
        ]
        with pytest.raises(ValueError, match="row 0"):
            bulk_load(conn, _spec(), _COLUMNS_LIST, rows)
        assert conn.copied_rows == []
        assert conn.rollbacks >= 1
        assert conn.index_of("execute", "'failed'") is not None

    def test_naive_row_timestamp_raises(self) -> None:
        conn = _conn(_fresh_happy_responses())
        rows = [("SPY", "1d", datetime(2026, 1, 5, 14, 30), 1.0, 2.0)]
        with pytest.raises(ValueError, match="row 0"):
            bulk_load(conn, _spec(), _COLUMNS_LIST, rows)
        assert conn.index_of("execute", "'failed'") is not None

    def test_copy_failure_rolls_back_marks_failed_and_reraises(self) -> None:
        conn = _conn(_fresh_happy_responses())

        def _exploding_rows():
            yield _ordered_rows()[0]
            yield _ordered_rows()[1]
            raise RuntimeError("connection dropped mid-COPY")

        with pytest.raises(RuntimeError, match="connection dropped"):
            bulk_load(conn, _spec(), _COLUMNS_LIST, _exploding_rows())
        assert conn.rollbacks >= 1
        i_failed = conn.require_index("execute", "'failed'")
        assert conn.events[i_failed][2] is not None  # error text bound as a parameter

    def test_failure_of_mark_failed_is_logged_once_original_still_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = _conn(_fresh_happy_responses())
        conn.execute_errors = {"'failed'": RuntimeError("could not mark failed")}

        class _Recorder:
            def __init__(self) -> None:
                self.warnings: list[tuple[str, dict]] = []

            def info(self, event: str, **kw: Any) -> None:
                pass

            def warning(self, event: str, **kw: Any) -> None:
                self.warnings.append((event, kw))

        recorder = _Recorder()
        monkeypatch.setattr(batch_utils, "_logger", recorder)

        def _bad_rows():
            yield ("SPY", "1d", datetime(2026, 1, 4, 14, 30, tzinfo=UTC), 1.0, 2.0)
            raise AssertionError("unreachable")

        with pytest.raises(ValueError, match="row 0"):
            bulk_load(conn, _spec(), _COLUMNS_LIST, _bad_rows())
        mark_failures = [w for w in recorder.warnings if "mark_failed" in w[0]]
        assert len(mark_failures) == 1, "the mark-failed failure must be logged exactly once"


# ---------------------------------------------------------------------------
# Refusals (BulkLoadRefused) and input validation
# ---------------------------------------------------------------------------


class TestTableColumnTypes:
    """The one information_schema column read, used by bulk_load and the IC writer."""

    def test_maps_columns_to_types_in_the_current_schema(self) -> None:
        conn = _conn([_COLUMNS])
        types = batch_utils.table_column_types(conn, "feature_vectors")
        assert types == {
            "symbol": "text",
            "tf": "text",
            "bar_ts": "timestamptz",
            "x": "real",
            "y": "double precision",
        }
        (text, params), *rest = conn.statements
        assert not rest and params == ("feature_vectors",)
        assert "information_schema.columns" in text and "current_schema()" in text

    def test_a_table_with_no_columns_does_not_exist_and_raises(self) -> None:
        with pytest.raises(ValueError, match="feature_nope does not exist"):
            batch_utils.table_column_types(_conn([{"fetchall": []}]), "feature_nope")

    def test_bulk_load_into_a_missing_table_raises_before_any_write(self) -> None:
        conn = _conn([_LOCKED, {"fetchone": None}, {"fetchall": []}])
        with pytest.raises(ValueError, match="feature_vectors does not exist"):
            bulk_load(conn, _spec(), _COLUMNS_LIST, _ordered_rows())
        assert conn.copied_rows == []


class TestBulkLoadRefusals:
    def test_scheduled_compression_policy_over_the_range_refuses(self) -> None:
        responses = _fresh_happy_responses()
        responses[4] = {"fetchall": [(101, True, timedelta(days=1))]}
        conn = _conn(responses)
        old_start = datetime.now(UTC) - timedelta(days=10)
        spec = _spec(range_start=old_start, range_end=old_start + timedelta(days=2))
        with pytest.raises(BulkLoadRefused, match="compression policy"):
            bulk_load(conn, spec, _COLUMNS_LIST, _ordered_rows())
        assert conn.index_of("copy") is None, "refusal must happen before any COPY"
        assert conn.index_of("execute", "'failed'") is None

    def test_paused_compression_policy_does_not_refuse(self) -> None:
        responses = _fresh_happy_responses()
        responses[4] = {"fetchall": [(101, False, timedelta(days=1))]}
        conn = _conn(responses)
        old_start = datetime.now(UTC) - timedelta(days=10)
        spec = _spec(range_start=old_start, range_end=old_start + timedelta(days=2))
        rows = [
            ("SPY", "1d", old_start + timedelta(hours=1), 1.0, 2.0),
            ("QQQ", "1d", old_start + timedelta(hours=2), 3.0, 4.0),
        ]
        result = bulk_load(conn, spec, _COLUMNS_LIST, rows)
        assert result.status == "loaded"

    def test_compressed_chunk_in_range_refuses(self) -> None:
        responses = _fresh_happy_responses()
        responses[5] = {"fetchone": (1,)}
        conn = _conn(responses)
        with pytest.raises(BulkLoadRefused, match="compressed chunk"):
            bulk_load(conn, _spec(), _COLUMNS_LIST, _ordered_rows())
        assert conn.index_of("copy") is None

    def test_unknown_column_raises_value_error(self) -> None:
        conn = _conn(_fresh_happy_responses())
        with pytest.raises(ValueError, match="not_a_col"):
            bulk_load(conn, _spec(), _COLUMNS_LIST + ["not_a_col"], _ordered_rows())
        assert conn.index_of("copy") is None

    def test_time_column_mismatch_with_dimension_refuses(self) -> None:
        responses = _fresh_happy_responses()
        # 'ts' exists in the live schema (so the column check passes) but the
        # hypertable's time dimension is 'bar_ts' (so the spec's pick is refused).
        responses[2] = {
            "fetchall": [
                ("symbol", "text"),
                ("tf", "text"),
                ("ts", "timestamptz"),
                ("bar_ts", "timestamptz"),
                ("x", "real"),
                ("y", "double precision"),
            ]
        }
        conn = _conn(responses)
        with pytest.raises(BulkLoadRefused, match="time dimension"):
            bulk_load(
                conn, _spec(time_column="ts"), ["symbol", "tf", "ts", "x", "y"], _ordered_rows()
            )
        assert conn.index_of("copy") is None

    def test_time_column_missing_from_columns_raises(self) -> None:
        conn = _conn(_fresh_happy_responses())
        with pytest.raises(ValueError, match="time column"):
            bulk_load(conn, _spec(), ["symbol", "tf", "x", "y"], _ordered_rows())
        assert conn.index_of("copy") is None

    def test_advisory_lock_not_acquired_refuses_without_unlock(self) -> None:
        conn = _conn([_LOCK_REFUSED])
        with pytest.raises(BulkLoadRefused, match="another session is loading unit"):
            bulk_load(conn, _spec(), _COLUMNS_LIST, _ordered_rows())
        assert conn.index_of("execute", "pg_advisory_unlock") is None
        assert conn.index_of("execute", "provenance_batch") is None


# ---------------------------------------------------------------------------
# compress_completed_chunks wiring
# ---------------------------------------------------------------------------


class TestBulkLoadCompressOnComplete:
    def test_compress_before_runs_after_data_commit_and_counts_chunks(self) -> None:
        responses = _fresh_happy_responses() + [
            {
                "fetchall": [
                    ("_timescaledb_internal", "_hyper_1_1_chunk"),
                    ("_timescaledb_internal", "_hyper_1_2_chunk"),
                ]
            }
        ]
        conn = _conn(responses)
        result = bulk_load(
            conn,
            _spec(),
            _COLUMNS_LIST,
            _ordered_rows(),
            compress_before=_RANGE_END,
        )
        assert result.status == "loaded"
        assert result.chunks_compressed == 2
        i_update = conn.require_index("execute", "UPDATE provenance_batch")
        compress_events = [
            i
            for i, (k, text, _p) in enumerate(conn.events)
            if k == "execute" and "compress_chunk" in text
        ]
        assert len(compress_events) == 2
        assert min(compress_events) > i_update
        assert conn.commits >= 4  # provenance, data, one per compressed chunk

    def test_apr_switch_false_skips_compress_entirely(self) -> None:
        responses = _fresh_happy_responses(_APR_COMPRESS_FALSE)
        conn = _conn(responses)
        result = bulk_load(
            conn,
            _spec(),
            _COLUMNS_LIST,
            _ordered_rows(),
            compress_before=_RANGE_END,
        )
        assert result.status == "loaded"
        assert result.chunks_compressed == 0
        assert conn.index_of("execute", "compress_chunk") is None

    def test_no_compress_before_means_no_compress_call(self) -> None:
        conn = _conn(_fresh_happy_responses())
        result = bulk_load(conn, _spec(), _COLUMNS_LIST, _ordered_rows())
        assert result.chunks_compressed == 0
        assert conn.index_of("execute", "compress_chunk") is None


# ---------------------------------------------------------------------------
# replace_where: atomic replacement of a unit's prior rows (phase 186 plan 14, D-24)
# ---------------------------------------------------------------------------


def _replace_responses(deleted: int = 7) -> list[dict]:
    # the DELETE's rowcount is the one fetch between the APR read and the COPY
    return _fresh_happy_responses() + [{"rowcount": deleted}]


class TestUnitKey:
    """unit_key = sha256(writer, target, tf, replace_where): one definition for the DELETE's owner
    and the supersede flip (migration 416)."""

    _WHERE = {"tf": "1d", "symbol": "POOLED", "feature_name": ["a", "b"]}

    def test_symbols_range_code_apr_and_input_do_not_change_it_but_do_change_batch_key(
        self,
    ) -> None:
        base = _spec(replace_where=self._WHERE)
        for name, mutated in {
            "symbols": _spec(replace_where=self._WHERE, symbols=("SPY", "IWM")),
            "range_start": _spec(
                replace_where=self._WHERE, range_start=_RANGE_START - timedelta(days=1)
            ),
            "range_end": _spec(replace_where=self._WHERE, range_end=_RANGE_END + timedelta(days=1)),
            "code_key": _spec(replace_where=self._WHERE, code_key="c" * 64),
            "apr_snapshot": _spec(replace_where=self._WHERE, apr_snapshot={"k": 2}),
            "input_digest": _spec(replace_where=self._WHERE, input_digest="d" * 64),
        }.items():
            assert mutated.unit_key == base.unit_key, name
            assert mutated.batch_key != base.batch_key, name

    def test_writer_target_tf_and_replace_where_change_it_and_the_batch_key(self) -> None:
        base = _spec(replace_where=self._WHERE)
        for name, mutated in {
            "writer": _spec(replace_where=self._WHERE, writer="other"),
            "target_table": _spec(replace_where=self._WHERE, target_table="feature_ic_scores"),
            "tf": _spec(replace_where=self._WHERE, tf="15m"),
            "replace_where": _spec(replace_where={**self._WHERE, "symbol": "OTHER"}),
            "append_only": _spec(),
        }.items():
            assert mutated.unit_key != base.unit_key, name
            assert mutated.batch_key != base.batch_key, name

    def test_list_value_order_never_matters(self) -> None:
        a = _spec(replace_where={"feature_name": ["a", "b"], "tf": "1d"})
        b = _spec(replace_where={"tf": "1d", "feature_name": ["b", "a"]})
        assert a.unit_key == b.unit_key and a.batch_key == b.batch_key

    def test_prior_completed_unit_looks_up_by_unit_key_only(self) -> None:
        spec = _spec(replace_where=self._WHERE)
        conn = _conn([{"fetchone": (1,)}])
        assert batch_utils.prior_completed_unit(conn, spec) is True
        _k, text, params = conn.events[0]
        assert "unit_key = %s" in text and "status = 'completed'" in text
        assert tuple(params) == (spec.unit_key, spec.batch_key)
        assert batch_utils.prior_completed_unit(_conn([{"fetchone": None}]), spec) is False


class TestBulkLoadReplaceWhere:
    def test_none_issues_no_delete_and_result_reports_zero_replaced(self) -> None:
        conn = _conn(_fresh_happy_responses())
        result = bulk_load(conn, _spec(), _COLUMNS_LIST, _ordered_rows())
        assert conn.index_of("execute", "DELETE FROM") is None
        assert result.rows_replaced == 0

    def test_delete_then_supersede_inside_the_data_transaction_before_copy(self) -> None:
        conn = _conn(_replace_responses(7))
        spec = _spec(replace_where={"tf": "1d", "symbol": ["SPY", "QQQ"]})
        result = bulk_load(conn, spec, _COLUMNS_LIST, _ordered_rows())
        assert result.status == "loaded"
        assert result.rows_replaced == 7
        i_timeout = conn.require_index("execute", "statement_timeout")
        i_delete = conn.require_index("execute", "DELETE FROM")
        i_supersede = conn.require_index("execute", "'superseded'")
        i_copy = conn.require_index("copy")
        i_complete = conn.require_index("execute", "'completed', row_count")
        assert i_timeout < i_delete < i_supersede < i_copy < i_complete
        # no commit between the DELETE and the completed update: one transaction
        between = [k for k, _t, _p in conn.events[i_delete:i_complete] if k == "commit"]
        assert between == []
        _k, delete_sql, delete_params = conn.events[i_delete]
        assert '"feature_vectors"' in delete_sql
        assert '"bar_ts" >=' in delete_sql and '"bar_ts" <' in delete_sql
        assert '"tf" = ' in delete_sql and '"symbol" = ANY' in delete_sql
        assert list(delete_params) == [_RANGE_START, _RANGE_END, "1d", ["SPY", "QQQ"]]
        _k, sup_sql, sup_params = conn.events[i_supersede]
        assert "unit_key = %s" in sup_sql and "batch_key <>" in sup_sql
        assert "status = 'completed'" in sup_sql
        assert tuple(sup_params) == (spec.unit_key, spec.batch_key)
        _k, insert_sql, insert_params = conn.events[conn.require_index("execute", "INSERT INTO")]
        assert "unit_key" in insert_sql and insert_params[-1] == spec.unit_key

    def test_unknown_replace_key_raises_before_the_data_transaction(self) -> None:
        conn = _conn(_replace_responses())
        with pytest.raises(ValueError, match="nope"):
            bulk_load(conn, _spec(replace_where={"nope": 1}), _COLUMNS_LIST, _ordered_rows())
        assert conn.index_of("execute", "DELETE FROM") is None
        assert conn.index_of("copy") is None

    def test_empty_mapping_raises(self) -> None:
        with pytest.raises(ValueError, match="replace_where"):
            _spec(replace_where={})

    def test_copy_failure_after_delete_rolls_everything_back(self) -> None:
        conn = _conn(_replace_responses())

        def _exploding_rows():
            yield _ordered_rows()[0]
            raise RuntimeError("connection dropped mid-COPY")

        with pytest.raises(RuntimeError, match="dropped"):
            bulk_load(conn, _spec(replace_where={"tf": "1d"}), _COLUMNS_LIST, _exploding_rows())
        i_delete = conn.require_index("execute", "DELETE FROM")
        after = [k for k, _t, _p in conn.events[i_delete:]]
        assert "rollback" in after
        assert "commit" not in after[: after.index("rollback")]

    def test_skipped_unit_issues_no_delete(self) -> None:
        conn = _conn([_LOCKED, {"fetchone": ("completed", 4, 1)}])
        result = bulk_load(conn, _spec(replace_where={"tf": "1d"}), _COLUMNS_LIST, _ordered_rows())
        assert result.status == "skipped"
        assert conn.index_of("execute", "DELETE FROM") is None

    def test_a_superseded_identity_is_refused_loudly(self) -> None:
        conn = _conn([_LOCKED, {"fetchone": ("superseded", 4, 1)}])
        with pytest.raises(BulkLoadRefused, match="superseded"):
            bulk_load(conn, _spec(), _COLUMNS_LIST, _ordered_rows())
        assert conn.index_of("copy") is None
