"""Unit tests for services/_batch_utils.py's async APR-loading helpers (todo 048).

cfg() and load_apr_dict_async() consolidate a pattern previously copy-pasted verbatim
across ensemble_trainer.py, alpha_publisher.py, and ensemble_ic_engine.py: load
alpha.* (+ each service's own infra.<name>.* keys) into a raw dict, then cast with a
small type-inferring helper.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services._batch_utils import (
    _COMPRESS_ALL_DECOMPRESSED_CHUNKS_ASYNCPG_SQL,
    _DECOMPRESS_ALL_COMPRESSED_CHUNKS_ASYNCPG_SQL,
    Float32ChunkAccumulator,
    _active_write_session_hypertable,
    _validate_compressed_hypertable,
    async_compressed_hypertable_write_session,
    async_compressed_hypertable_write_session_or_noop,
    bars_to_scale_map,
    bulk_update_by_key,
    cfg,
    compressed_hypertable_write_session,
    compressed_hypertable_write_session_or_noop,
    connect_db_from_url,
    limit_blas_threads,
    load_apr_dict_async,
    make_worker_pool,
    resolve_per_tf,
)


class TestBarsToScaleMap:
    def test_inverts_scale_to_bars(self) -> None:
        result = bars_to_scale_map({"fast": 1, "mid": 6, "slow": 12, "extended": 39})
        assert result == {1: "fast", 6: "mid", 12: "slow", 39: "extended"}

    def test_raises_on_collision(self) -> None:
        """Todo 211 part 2: this collision check was missing from two prior
        independent reimplementations of this reverse-map (ops_ic_shrinkage.py,
        ops_ic_null_calibration.py), which would silently drop a cell (last write
        wins) instead of failing loudly -- CLAUDE.md: silent wrong answers are worse
        than loud crashes."""
        with pytest.raises(ValueError, match="collides"):
            bars_to_scale_map({"fast": 5, "mid": 5})

    def test_collision_error_includes_context_label(self) -> None:
        with pytest.raises(ValueError, match="tf='1h'"):
            bars_to_scale_map({"fast": 5, "mid": 5}, context="1h")


class TestCfg:
    def test_returns_float_when_present(self) -> None:
        cfg_dict = {"alpha.ensemble.max_feature_weight": "0.20"}
        result = cfg(cfg_dict, "alpha.ensemble.max_feature_weight", 0.5)
        assert result == 0.20
        assert isinstance(result, float)

    def test_returns_float_default_when_missing(self) -> None:
        result = cfg({}, "alpha.ensemble.max_feature_weight", 0.25)
        assert result == 0.25

    def test_returns_int_when_present(self) -> None:
        cfg_dict = {"alpha.ensemble.min_passing_features": "5"}
        result = cfg(cfg_dict, "alpha.ensemble.min_passing_features", 3)
        assert result == 5
        assert isinstance(result, int)

    def test_returns_str_when_present(self) -> None:
        cfg_dict = {"alpha.ensemble.weight_version": "v2"}
        result = cfg(cfg_dict, "alpha.ensemble.weight_version", "v1")
        assert result == "v2"
        assert isinstance(result, str)

    def test_type_inferred_from_default_not_from_raw_value(self) -> None:
        """config_state values are always text; cfg() must cast via type(default),
        not assume the raw string is already the right type."""
        cfg_dict = {"infra.workers": "12"}
        result = cfg(cfg_dict, "infra.workers", 1)
        assert result == 12
        assert isinstance(result, int)

    def test_bool_false_string_parses_to_false(self) -> None:
        """Regression: bool("false") is True in Python (non-empty string is truthy).
        A naive type(default)(val) cast would silently invert every falsy bool APR
        flag -- found live in alpha.ensemble.sign_symmetric (stored 'false', read as
        True) while wiring alpha.publisher.is_shadow (todo 011)."""
        cfg_dict = {"alpha.ensemble.sign_symmetric": "false"}
        result = cfg(cfg_dict, "alpha.ensemble.sign_symmetric", False)
        assert result is False

    def test_bool_true_string_parses_to_true(self) -> None:
        cfg_dict = {"alpha.publisher.is_shadow": "true"}
        result = cfg(cfg_dict, "alpha.publisher.is_shadow", True)
        assert result is True

    def test_bool_default_used_when_key_absent(self) -> None:
        assert cfg({}, "alpha.publisher.is_shadow", True) is True
        assert cfg({}, "alpha.ensemble.sign_symmetric", False) is False

    def test_bool_case_and_whitespace_insensitive(self) -> None:
        assert cfg({"k": " True "}, "k", False) is True
        assert cfg({"k": "FALSE"}, "k", True) is False

    def test_list_default_json_loads_raw_string(self) -> None:
        """Regression (todo 187): a naive type(default)(val) cast against a list default
        splits a raw JSON-array string into individual characters --
        list("[1,3,5,10]") != [1, 3, 5, 10] -- found live in
        alpha.construction.cost_hurdle_bps_round_trip, worked around locally in
        cross_sectional_spread_tracker.py before being fixed here at the shared layer."""
        cfg_dict = {"alpha.construction.cost_hurdle_bps_round_trip": "[1,3,5,10]"}
        result = cfg(cfg_dict, "alpha.construction.cost_hurdle_bps_round_trip", [1, 3, 5, 10])
        assert result == [1, 3, 5, 10]

    def test_list_default_used_when_key_absent(self) -> None:
        assert cfg({}, "alpha.construction.cost_hurdle_bps_round_trip", [1, 3, 5, 10]) == [
            1,
            3,
            5,
            10,
        ]

    def test_dict_default_json_loads_raw_string(self) -> None:
        cfg_dict = {"alpha.regime.groups": '{"equity": true}'}
        result = cfg(cfg_dict, "alpha.regime.groups", {})
        assert result == {"equity": True}

    def test_dict_default_passthrough_when_already_parsed(self) -> None:
        """ConfigService's json.loads() may already have parsed the value before it
        reaches cfg() in some call paths -- must not double-decode a dict that's no
        longer a raw string."""
        cfg_dict = {"alpha.regime.groups": {"equity": True}}
        result = cfg(cfg_dict, "alpha.regime.groups", {})
        assert result == {"equity": True}


class TestResolvePerTf:
    """Relocated from services/ensemble_trainer.py (todo 009 Part D Item 4) -- direct
    test at the new canonical home, in addition to the coverage that already runs
    through ensemble_trainer.py's re-exported _resolve_per_tf alias
    (test_ensemble_trainer.py)."""

    def test_uses_global_default_when_no_per_tf_override(self) -> None:
        assert resolve_per_tf({}, "alpha.ensemble.min_passing_features", "1h", 5) == 5

    def test_uses_per_tf_override_when_present(self) -> None:
        cfg_dict = {"alpha.ensemble.min_passing_features.1h": "3"}
        assert resolve_per_tf(cfg_dict, "alpha.ensemble.min_passing_features", "1h", 5) == 3

    def test_per_tf_override_scoped_to_its_own_tf(self) -> None:
        cfg_dict = {"alpha.ensemble.min_passing_features.1h": "3"}
        assert resolve_per_tf(cfg_dict, "alpha.ensemble.min_passing_features", "15m", 5) == 5


class TestLoadAprDictAsync:
    @pytest.mark.asyncio
    async def test_default_pattern_is_alpha_only(self) -> None:
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])

        await load_apr_dict_async(conn)

        args, _ = conn.fetch.call_args
        sql, params = args[0], args[1:]
        assert "config_key LIKE ANY($1::text[])" in sql
        assert params == (["alpha.%"],)

    @pytest.mark.asyncio
    async def test_extra_patterns_are_bound_as_one_array_param(self) -> None:
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])

        await load_apr_dict_async(conn, extra_like_patterns=["infra.ensemble_ic_engine.%"])

        args, _ = conn.fetch.call_args
        sql, params = args[0], args[1:]
        assert "config_key LIKE ANY($1::text[])" in sql
        assert params == (["alpha.%", "infra.ensemble_ic_engine.%"],)

    @pytest.mark.asyncio
    async def test_returns_key_value_dict_from_fetched_rows(self) -> None:
        conn = MagicMock()
        conn.fetch = AsyncMock(
            return_value=[
                {"config_key": "alpha.ic.fdr_alpha", "config_value": "0.05"},
                {"config_key": "alpha.ensemble.weight_version", "config_value": "v1"},
            ]
        )

        result = await load_apr_dict_async(conn)

        assert result == {
            "alpha.ic.fdr_alpha": "0.05",
            "alpha.ensemble.weight_version": "v1",
        }


class TestConnectDbFromUrl:
    def test_disables_autocommit(self) -> None:
        with patch("services._batch_utils.psycopg.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_connect.return_value = mock_conn

            result = connect_db_from_url("postgresql://fake")

            mock_connect.assert_called_once_with("postgresql://fake")
            assert result is mock_conn
            assert mock_conn.autocommit is False


class TestLimitBlasThreads:
    """Todo 216: real-effect test (not mocked) proving limit_blas_threads() actually
    caps every detected BLAS/OpenMP thread pool, not just that it calls some API.
    Restores the original limits afterward so this test can't leak state into any
    test that runs later in the same pytest session."""

    def test_caps_thread_count_for_every_detected_pool(self) -> None:
        import threadpoolctl

        original = threadpoolctl.threadpool_limits()  # no-op snapshot, for restore below
        try:
            limit_blas_threads(1)
            info = threadpoolctl.threadpool_info()
            assert info, "no BLAS/OpenMP thread pools detected -- can't exercise the cap"
            assert all(entry["num_threads"] == 1 for entry in info)
        finally:
            original.restore_original_limits()


class TestMakeWorkerPool:
    """Todo 216: every ProcessPoolExecutor construction site was converted to this
    wrapper so the BLAS thread cap can never be silently omitted (see the CI guard in
    test_no_bare_process_pool_executor.py, which enforces that _batch_utils.py stays
    the only file constructing one directly)."""

    def test_wires_limit_blas_threads_as_initializer(self) -> None:
        with patch("services._batch_utils.ProcessPoolExecutor") as mock_pool_cls:
            make_worker_pool(4, 2)

            mock_pool_cls.assert_called_once_with(
                max_workers=4,
                initializer=limit_blas_threads,
                initargs=(2,),
            )

    def test_forwards_extra_kwargs_to_process_pool_executor(self) -> None:
        with patch("services._batch_utils.ProcessPoolExecutor") as mock_pool_cls:
            make_worker_pool(4, 2, mp_context="fake_ctx")

            mock_pool_cls.assert_called_once_with(
                max_workers=4,
                initializer=limit_blas_threads,
                initargs=(2,),
                mp_context="fake_ctx",
            )


class TestFloat32ChunkAccumulator:
    """todo 087: shared 'buffer rows -> float32 chunk -> vstack once' idiom behind
    ic_engine.py's per-symbol (row-by-row, threshold-flushed) and cross-sectional
    (whole-batch-per-query-chunk) OOM-mitigation fetch loops."""

    def test_finalize_with_no_rows_returns_none(self) -> None:
        acc = Float32ChunkAccumulator(flush_at=2)
        assert acc.finalize() is None

    def test_append_row_flushes_at_threshold(self) -> None:
        acc = Float32ChunkAccumulator(flush_at=2)
        acc.append_row([1.0, 2.0])
        acc.append_row([3.0, 4.0])
        acc.append_row([5.0, 6.0])

        result = acc.finalize()

        assert result.dtype == np.float32
        np.testing.assert_array_equal(result, [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])

    def test_append_row_flushes_remainder_on_finalize(self) -> None:
        acc = Float32ChunkAccumulator(flush_at=10)
        acc.append_row([1.0, 2.0])

        result = acc.finalize()

        np.testing.assert_array_equal(result, [[1.0, 2.0]])

    def test_append_chunk_appends_whole_batch_immediately(self) -> None:
        acc = Float32ChunkAccumulator()
        acc.append_chunk([[1.0, 2.0], [3.0, 4.0]])
        acc.append_chunk([[5.0, 6.0]])

        result = acc.finalize()

        assert result.dtype == np.float32
        np.testing.assert_array_equal(result, [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])

    def test_append_chunk_ignores_empty_batch(self) -> None:
        acc = Float32ChunkAccumulator()
        acc.append_chunk([])
        assert acc.finalize() is None

    def test_finalize_frees_internal_chunk_list(self) -> None:
        acc = Float32ChunkAccumulator()
        acc.append_chunk([[1.0, 2.0]])
        acc.finalize()
        assert acc._chunks == []


class TestValidateCompressedHypertable:
    def test_known_hypertables_do_not_raise(self) -> None:
        _validate_compressed_hypertable("feature_vectors")
        _validate_compressed_hypertable("feature_ic_scores")

    def test_unknown_hypertable_raises_with_name_in_message(self) -> None:
        with pytest.raises(ValueError, match="market_data_ohlcv"):
            _validate_compressed_hypertable("market_data_ohlcv")


def _mock_sync_conn(n_decompressed: int = 0, n_recompressed: int = 0) -> MagicMock:
    """A psycopg-shaped connection mock: `cursor()` returns the same cursor mock on every
    call (so all cur.execute() calls across the session land in one call_args_list).
    `cur.rowcount` is scripted by which collapsed statement was just executed (decompress-
    all vs. compress-all) -- matching how compressed_hypertable_write_session actually
    reads the affected-row count (a single server-side statement per phase, not a
    list-then-loop), not an assumption about it."""
    conn = MagicMock()
    conn.autocommit = False
    cur = conn.cursor.return_value.__enter__.return_value

    def _execute(sql: str, params: tuple | None = None) -> None:
        if sql.startswith("SELECT config_value FROM config_state"):
            # No row seeded -- the session falls back to its own default. Content-
            # dispatched (not a shared cur.fetchone.return_value) because this call and
            # "SHOW statement_timeout" below both read via fetchone() and must return
            # different shapes.
            cur.fetchone.return_value = None
        elif sql == "SHOW statement_timeout":
            # Value is arbitrary; only its round-trip (captured, restored) is tested.
            cur.fetchone.return_value = ("30min",)
        elif sql.startswith("SELECT decompress_chunk"):
            cur.rowcount = n_decompressed
        elif sql.startswith("SELECT compress_chunk"):
            cur.rowcount = n_recompressed

    cur.execute.side_effect = _execute
    return conn


class TestCompressedHypertableWriteSession:
    def test_decompresses_on_entry_before_yield(self) -> None:
        conn = _mock_sync_conn(n_decompressed=1)
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_vectors"):
            calls_at_entry = [c.args[0] for c in cur.execute.call_args_list]
            assert any(sql.startswith("SELECT decompress_chunk") for sql in calls_at_entry)
            assert not any(sql.startswith("SELECT compress_chunk") for sql in calls_at_entry)
            assert not any(sql.startswith("VACUUM") for sql in calls_at_entry)

    def test_decompress_and_compress_are_single_collapsed_statements_not_per_chunk(self) -> None:
        """Regression: the original design listed chunks then issued one execute() per
        chunk (N round trips). The fix collapses each phase into one server-side statement
        -- exactly 7 execute() calls total for the whole session regardless of how many
        chunks are actually affected: the APR config load (1), SHOW + SET statement_timeout
        at entry (2), decompress-all, compress-all, VACUUM (3), and SET statement_timeout
        restored at exit (1)."""
        conn = _mock_sync_conn(n_decompressed=40, n_recompressed=40)
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_vectors"):
            pass

        assert cur.execute.call_count == 7

    def test_recompresses_and_vacuums_on_clean_exit(self) -> None:
        conn = _mock_sync_conn(n_decompressed=1, n_recompressed=2)
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_vectors"):
            pass

        sqls = [c.args[0] for c in cur.execute.call_args_list]
        decompress_idx = next(i for i, s in enumerate(sqls) if s.startswith("SELECT decompress"))
        compress_idx = next(i for i, s in enumerate(sqls) if s.startswith("SELECT compress"))
        vacuum_idx = next(i for i, s in enumerate(sqls) if s.startswith("VACUUM"))

        assert decompress_idx < compress_idx < vacuum_idx
        assert sqls[vacuum_idx] == "VACUUM feature_vectors"

    def test_recompresses_and_vacuums_even_when_body_raises(self) -> None:
        """The finally guarantee -- a caller's write loop raising mid-batch must not leave
        the hypertable stuck decompressed."""
        conn = _mock_sync_conn(n_recompressed=1)
        cur = conn.cursor.return_value.__enter__.return_value

        with pytest.raises(RuntimeError, match="boom"):
            with compressed_hypertable_write_session(conn, "feature_vectors"):
                raise RuntimeError("boom")

        sqls = [c.args[0] for c in cur.execute.call_args_list]
        assert any(s.startswith("SELECT compress_chunk") for s in sqls)
        assert any(s.startswith("VACUUM") for s in sqls)

    def test_rolls_back_before_recompressing_when_body_raises(self) -> None:
        """Regression (2026-08-14 code review): without a rollback here, a body that
        raised a real DB-level error would leave the connection in Postgres's aborted-
        transaction state, and the very next statement (the recompress attempt) would
        itself raise (psycopg.errors.InFailedSqlTransaction in production, not
        reproducible with this mock -- what IS reproducible and asserted here is that
        rollback() happens, and happens before compress_chunk is attempted)."""
        conn = _mock_sync_conn(n_recompressed=1)
        cur = conn.cursor.return_value.__enter__.return_value
        call_order: list[str] = []
        conn.rollback.side_effect = lambda: call_order.append("rollback")
        original_execute = cur.execute.side_effect

        def _tracked_execute(sql: str, *args: object) -> None:
            original_execute(sql, *args)
            if sql.startswith("SELECT compress_chunk"):
                call_order.append("compress")

        cur.execute.side_effect = _tracked_execute

        with pytest.raises(RuntimeError, match="boom"):
            with compressed_hypertable_write_session(conn, "feature_vectors"):
                raise RuntimeError("boom")

        assert call_order == ["rollback", "compress"]

    def test_rolls_back_on_clean_exit_too_defensively_harmless(self) -> None:
        """rollback() runs unconditionally in `finally`, including the success path --
        must not raise/misbehave when there's nothing to roll back (the caller's own
        conn.commit() already ran)."""
        conn = _mock_sync_conn()

        with compressed_hypertable_write_session(conn, "feature_vectors"):
            pass

        conn.rollback.assert_called_once()

    def test_vacuum_runs_with_autocommit_true_then_restores_prior_value(self) -> None:
        conn = _mock_sync_conn()
        cur = conn.cursor.return_value.__enter__.return_value
        autocommit_during_vacuum: list[bool] = []
        original_execute = cur.execute.side_effect

        def _record_autocommit_and_pass(sql: str, *args: object) -> None:
            original_execute(sql, *args)
            if sql.startswith("VACUUM"):
                autocommit_during_vacuum.append(conn.autocommit)

        cur.execute.side_effect = _record_autocommit_and_pass

        with compressed_hypertable_write_session(conn, "feature_vectors"):
            pass

        assert autocommit_during_vacuum == [True]
        assert conn.autocommit is False  # restored

    def test_no_chunks_is_a_safe_no_op(self) -> None:
        """A fully-uncompressed (or already-clean) table must not error -- the collapsed
        statements simply affect zero rows, VACUUM still runs (cheap on a small/empty
        table)."""
        conn = _mock_sync_conn(n_decompressed=0, n_recompressed=0)
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_vectors"):
            pass

        sqls = [c.args[0] for c in cur.execute.call_args_list]
        assert any(s.startswith("VACUUM") for s in sqls)

    def test_rejects_unknown_hypertable_before_touching_connection(self) -> None:
        conn = MagicMock()
        with pytest.raises(ValueError, match="not_a_real_table"):
            with compressed_hypertable_write_session(conn, "not_a_real_table"):
                pass
        conn.cursor.assert_not_called()

    def test_sets_active_session_contextvar_for_duration_only(self) -> None:
        """bulk_update_by_key's guard (see TestBulkUpdateByKeyCompressedHypertableGuard)
        depends on this being set exactly for the bracketed duration, not before or after."""
        conn = _mock_sync_conn()
        assert _active_write_session_hypertable.get() is None

        with compressed_hypertable_write_session(conn, "feature_vectors"):
            assert _active_write_session_hypertable.get() == "feature_vectors"

        assert _active_write_session_hypertable.get() is None

    def test_contextvar_cleared_even_when_body_raises(self) -> None:
        conn = _mock_sync_conn()
        with pytest.raises(RuntimeError):
            with compressed_hypertable_write_session(conn, "feature_vectors"):
                raise RuntimeError("boom")
        assert _active_write_session_hypertable.get() is None


class TestCompressedHypertableWriteSessionOrNoop:
    def test_returns_real_session_when_apply_true(self) -> None:
        conn = _mock_sync_conn()
        with compressed_hypertable_write_session_or_noop(conn, "feature_vectors", apply=True):
            assert _active_write_session_hypertable.get() == "feature_vectors"

    def test_returns_noop_when_apply_false(self) -> None:
        conn = MagicMock()
        with compressed_hypertable_write_session_or_noop(conn, "feature_vectors", apply=False):
            assert _active_write_session_hypertable.get() is None
        conn.cursor.assert_not_called()


class TestBulkUpdateByKeyCompressedHypertableGuard:
    def test_raises_when_no_session_active_for_compressed_hypertable(self) -> None:
        conn = MagicMock()
        with pytest.raises(RuntimeError, match="feature_vectors"):
            bulk_update_by_key(
                conn,
                table="feature_vectors",
                temp_table="_t",
                key_cols=["symbol"],
                set_cols=["regime"],
                col_types={"symbol": "text", "regime": "text"},
                rows=[("SPY", "trending")],
            )
        conn.cursor.assert_not_called()

    def test_succeeds_when_session_active_for_this_table(self) -> None:
        conn = _mock_sync_conn()
        with compressed_hypertable_write_session(conn, "feature_vectors"):
            bulk_update_by_key(
                conn,
                table="feature_vectors",
                temp_table="_t",
                key_cols=["symbol"],
                set_cols=["regime"],
                col_types={"symbol": "text", "regime": "text"},
                rows=[("SPY", "trending")],
            )  # must not raise

    def test_raises_when_session_active_for_a_different_table(self) -> None:
        conn = _mock_sync_conn()
        with compressed_hypertable_write_session(conn, "feature_ic_scores"):
            with pytest.raises(RuntimeError, match="feature_vectors"):
                bulk_update_by_key(
                    conn,
                    table="feature_vectors",
                    temp_table="_t",
                    key_cols=["symbol"],
                    set_cols=["regime"],
                    col_types={"symbol": "text", "regime": "text"},
                    rows=[("SPY", "trending")],
                )

    def test_uncompressed_table_needs_no_session(self) -> None:
        """The guard only fires for _KNOWN_COMPRESSED_HYPERTABLES -- an ordinary table's
        bulk_update_by_key callers (e.g. this module's other, non-compressed-hypertable
        consumers) are unaffected."""
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.copy.return_value.__enter__.return_value = MagicMock()
        bulk_update_by_key(
            conn,
            table="some_ordinary_table",
            temp_table="_t",
            key_cols=["id"],
            set_cols=["value"],
            col_types={"id": "int", "value": "text"},
            rows=[(1, "x")],
        )  # must not raise


def _mock_async_conn(n_decompressed: int = 0, n_recompressed: int = 0) -> MagicMock:
    """asyncpg-shaped connection mock. `execute()` returns the command tag string asyncpg
    itself returns for a plain SELECT ("SELECT <n>") -- confirmed live 2026-08-14 -- since
    async_compressed_hypertable_write_session parses the affected-row count from that tag
    rather than a separate count(*) query."""
    conn = MagicMock()

    async def _execute(sql: str, *args: object) -> str:
        if sql.startswith(_DECOMPRESS_ALL_COMPRESSED_CHUNKS_ASYNCPG_SQL):
            return f"SELECT {n_decompressed}"
        if sql.startswith(_COMPRESS_ALL_DECOMPRESSED_CHUNKS_ASYNCPG_SQL):
            return f"SELECT {n_recompressed}"
        return "VACUUM"

    conn.execute = AsyncMock(side_effect=_execute)
    # load_apr_dict_async's conn.fetch (no APR rows configured -- callers fall back to
    # each key's default) and the statement_timeout capture/restore's conn.fetchval.
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchval = AsyncMock(return_value="30min")
    return conn


class TestAsyncCompressedHypertableWriteSession:
    @pytest.mark.asyncio
    async def test_decompresses_on_entry_before_yield(self) -> None:
        conn = _mock_async_conn(n_decompressed=1)

        async with async_compressed_hypertable_write_session(conn, "feature_ic_scores"):
            calls_at_entry = [c.args[0] for c in conn.execute.call_args_list]
            assert any(sql.startswith("SELECT decompress_chunk") for sql in calls_at_entry)
            assert not any(sql.startswith("SELECT compress_chunk") for sql in calls_at_entry)
            assert not any(sql.startswith("VACUUM") for sql in calls_at_entry)

    @pytest.mark.asyncio
    async def test_recompresses_and_vacuums_on_clean_exit(self) -> None:
        conn = _mock_async_conn(n_decompressed=0, n_recompressed=1)

        async with async_compressed_hypertable_write_session(conn, "feature_ic_scores"):
            pass

        sqls = [c.args[0] for c in conn.execute.call_args_list]
        decompress_idx = next(i for i, s in enumerate(sqls) if s.startswith("SELECT decompress"))
        compress_idx = next(i for i, s in enumerate(sqls) if s.startswith("SELECT compress"))
        vacuum_idx = next(i for i, s in enumerate(sqls) if s.startswith("VACUUM"))

        assert decompress_idx < compress_idx < vacuum_idx
        assert sqls[vacuum_idx] == "VACUUM feature_ic_scores"

    @pytest.mark.asyncio
    async def test_recompresses_and_vacuums_even_when_body_raises(self) -> None:
        conn = _mock_async_conn(n_decompressed=0, n_recompressed=1)

        with pytest.raises(RuntimeError, match="boom"):
            async with async_compressed_hypertable_write_session(conn, "feature_ic_scores"):
                raise RuntimeError("boom")

        sqls = [c.args[0] for c in conn.execute.call_args_list]
        assert any(s.startswith("SELECT compress_chunk") for s in sqls)
        assert any(s == "VACUUM feature_ic_scores" for s in sqls)

    @pytest.mark.asyncio
    async def test_rejects_unknown_hypertable_before_touching_connection(self) -> None:
        conn = _mock_async_conn()
        with pytest.raises(ValueError, match="not_a_real_table"):
            async with async_compressed_hypertable_write_session(conn, "not_a_real_table"):
                pass
        conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_sets_active_session_contextvar_for_duration_only(self) -> None:
        conn = _mock_async_conn()
        assert _active_write_session_hypertable.get() is None

        async with async_compressed_hypertable_write_session(conn, "feature_ic_scores"):
            assert _active_write_session_hypertable.get() == "feature_ic_scores"

        assert _active_write_session_hypertable.get() is None


class TestAsyncCompressedHypertableWriteSessionOrNoop:
    @pytest.mark.asyncio
    async def test_returns_noop_when_apply_false(self) -> None:
        conn = _mock_async_conn()
        async with async_compressed_hypertable_write_session_or_noop(
            conn, "feature_ic_scores", apply=False
        ):
            pass
        conn.execute.assert_not_called()
