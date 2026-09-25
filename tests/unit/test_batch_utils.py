"""Unit tests for services/_batch_utils.py's async APR-loading helpers (todo 048).

cfg() and load_apr_dict_async() consolidate a pattern previously copy-pasted verbatim
across ensemble_trainer.py, alpha_publisher.py, and ensemble_ic_engine.py: load
alpha.* (+ each service's own infra.<name>.* keys) into a raw dict, then cast with a
small type-inferring helper.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import services._batch_utils as _batch_utils_module
from services._batch_utils import (
    _COMPRESS_ALL_DECOMPRESSED_CHUNKS_ASYNCPG_SQL,
    _DECOMPRESS_ALL_COMPRESSED_CHUNKS_ASYNCPG_SQL,
    _FIND_COMPRESSION_JOBS_ASYNCPG_SQL,
    _REAL_MAX_MAGNITUDE,
    _REAL_MIN_MAGNITUDE,
    Float32ChunkAccumulator,
    _active_write_session_hypertable,
    _clamp_to_real_range,
    _known_compressed_hypertables,
    _known_compressed_hypertables_async,
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

    # -- Phase 174 D-04 / todo 371: disk-backed mode coverage -----------------
    #
    # Every test below uses pytest's tmp_path fixture as scratch_dir -- none may
    # write into the real APR-configured production scratch directory
    # (infra.ic_engine.memmap_scratch_dir, migration 336).

    @staticmethod
    def _ragged_batches() -> list[list[list[float]]]:
        """3 ragged append_chunk batches (7, 3, 11 rows) of 5 float columns,
        including negative values and a 0.0. 21 rows total."""
        batches: list[list[list[float]]] = []
        row_id = 0
        for n_rows in (7, 3, 11):
            batch = []
            for _ in range(n_rows):
                row_id += 1
                batch.append(
                    [
                        float(row_id),
                        -float(row_id),
                        0.0,
                        float(row_id) * 1.5,
                        float(-row_id) * 0.25,
                    ]
                )
            batches.append(batch)
        return batches

    def test_disk_backed_append_chunk_matches_in_ram_result(self, tmp_path) -> None:
        batches = self._ragged_batches()

        in_ram = Float32ChunkAccumulator()
        for batch in batches:
            in_ram.append_chunk(batch)
        in_ram_result = in_ram.finalize()

        disk_acc = Float32ChunkAccumulator(
            disk_backed=True, estimated_rows=64, n_cols=5, scratch_dir=str(tmp_path)
        )
        try:
            for batch in batches:
                disk_acc.append_chunk(batch)
            disk_result = disk_acc.finalize()

            assert disk_result.shape == in_ram_result.shape
            assert disk_result.dtype == in_ram_result.dtype
            assert np.array_equal(disk_result, in_ram_result)
        finally:
            disk_acc.close()

    def test_disk_backed_append_row_matches_in_ram_result(self, tmp_path) -> None:
        rows = [row for batch in self._ragged_batches() for row in batch]

        in_ram = Float32ChunkAccumulator(flush_at=2)
        for row in rows:
            in_ram.append_row(row)
        in_ram_result = in_ram.finalize()

        disk_acc = Float32ChunkAccumulator(
            flush_at=2,
            disk_backed=True,
            estimated_rows=64,
            n_cols=5,
            scratch_dir=str(tmp_path),
        )
        try:
            for row in rows:
                disk_acc.append_row(row)
            disk_result = disk_acc.finalize()

            assert disk_result.shape == in_ram_result.shape
            assert disk_result.dtype == in_ram_result.dtype
            assert np.array_equal(disk_result, in_ram_result)
        finally:
            disk_acc.close()

    def test_disk_backed_finalize_trims_over_estimated_rows(self, tmp_path) -> None:
        acc = Float32ChunkAccumulator(
            disk_backed=True, estimated_rows=1000, n_cols=5, scratch_dir=str(tmp_path)
        )
        try:
            for batch in self._ragged_batches():
                acc.append_chunk(batch)
            result = acc.finalize()
            assert result.shape == (21, 5)
        finally:
            acc.close()

    def test_disk_backed_under_estimate_raises_value_error(self, tmp_path) -> None:
        acc = Float32ChunkAccumulator(
            disk_backed=True, estimated_rows=5, n_cols=5, scratch_dir=str(tmp_path)
        )
        try:
            nine_rows = [[float(i)] * 5 for i in range(9)]
            with pytest.raises(ValueError):
                acc.append_chunk(nine_rows)
        finally:
            acc.close()

    def test_disk_backed_missing_params_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            Float32ChunkAccumulator(disk_backed=True)

    def test_disk_backed_empty_accumulation_returns_none_and_cleans_up(self, tmp_path) -> None:
        acc = Float32ChunkAccumulator(
            disk_backed=True, estimated_rows=10, n_cols=5, scratch_dir=str(tmp_path)
        )
        result = acc.finalize()
        assert result is None
        assert list(tmp_path.glob("*.memmap")) == []

    def test_disk_backed_close_removes_scratch_file(self, tmp_path) -> None:
        acc = Float32ChunkAccumulator(
            disk_backed=True, estimated_rows=10, n_cols=5, scratch_dir=str(tmp_path)
        )
        acc.append_chunk([[1.0, 2.0, 3.0, 4.0, 5.0]])
        acc.finalize()
        acc.close()
        assert list(tmp_path.glob("*.memmap")) == []

    def test_disk_backed_context_manager_removes_scratch_file(self, tmp_path) -> None:
        with Float32ChunkAccumulator(
            disk_backed=True, estimated_rows=10, n_cols=5, scratch_dir=str(tmp_path)
        ) as acc:
            acc.append_chunk([[1.0, 2.0, 3.0, 4.0, 5.0]])
            acc.finalize()
        assert list(tmp_path.glob("*.memmap")) == []

    def test_disk_backed_scratch_file_exists_while_live(self, tmp_path) -> None:
        acc = Float32ChunkAccumulator(
            disk_backed=True, estimated_rows=10, n_cols=5, scratch_dir=str(tmp_path)
        )
        try:
            acc.append_chunk([[1.0, 2.0, 3.0, 4.0, 5.0]])
            assert len(list(tmp_path.glob("*.memmap"))) == 1
        finally:
            acc.close()

    def test_disk_backed_close_does_not_leak_file_descriptors(self, tmp_path) -> None:
        """Regression test for the NamedTemporaryFile handle leak (T-174-39): a
        version of close() that closes only the mmap and never the tmpfile handle
        leaks one fd per accumulator -- a delta near 50 across this loop."""
        pid = os.getpid()
        fd_dir = f"/proc/{pid}/fd"
        baseline = len(os.listdir(fd_dir))

        for _ in range(50):
            acc = Float32ChunkAccumulator(
                disk_backed=True, estimated_rows=10, n_cols=5, scratch_dir=str(tmp_path)
            )
            acc.append_chunk([[1.0, 2.0, 3.0, 4.0, 5.0]])
            acc.finalize()
            acc.close()

        after = len(os.listdir(fd_dir))
        assert after - baseline <= 2

    def test_disk_backed_ownership_contract(self, tmp_path) -> None:
        acc = Float32ChunkAccumulator(
            disk_backed=True, estimated_rows=10, n_cols=5, scratch_dir=str(tmp_path)
        )
        acc.append_chunk([[1.0, 2.0, 3.0, 4.0, 5.0], [6.0, 7.0, 8.0, 9.0, 10.0]])
        result = acc.finalize()

        # Readable BEFORE close() -- a real read through the mapping, not just a
        # shape/dtype check that could pass against a stale/unmapped handle.
        np.testing.assert_array_equal(
            result, [[1.0, 2.0, 3.0, 4.0, 5.0], [6.0, 7.0, 8.0, 9.0, 10.0]]
        )
        assert float(result.sum()) == pytest.approx(55.0)

        acc.close()
        # Second close() is the documented post-close state: a no-op, does not raise.
        acc.close()
        assert list(tmp_path.glob("*.memmap")) == []

    def test_disk_backed_creates_missing_scratch_dir(self, tmp_path) -> None:
        missing_dir = tmp_path / "does" / "not" / "exist"
        assert not missing_dir.exists()

        acc = Float32ChunkAccumulator(
            disk_backed=True, estimated_rows=10, n_cols=5, scratch_dir=str(missing_dir)
        )
        try:
            acc.append_chunk([[1.0, 2.0, 3.0, 4.0, 5.0]])
            result = acc.finalize()
            np.testing.assert_array_equal(result, [[1.0, 2.0, 3.0, 4.0, 5.0]])
        finally:
            acc.close()

        assert missing_dir.exists()


class TestValidateCompressedHypertable:
    """This is the hand-curated allow-list for compressed_hypertable_write_session's own
    heavy machinery, deliberately NOT the live-queried `_known_compressed_hypertables` set
    below (code review, 2026-09-17): the live DB has 26 compressed hypertables today, but
    this mechanism has only been built/incident-hardened for 2 of them -- a pure static
    check, no conn involved."""

    def test_known_hypertables_do_not_raise(self) -> None:
        _validate_compressed_hypertable("feature_vectors")
        _validate_compressed_hypertable("feature_ic_scores")

    def test_unknown_hypertable_raises_with_name_in_message(self) -> None:
        with pytest.raises(ValueError, match="market_data_ohlcv"):
            _validate_compressed_hypertable("market_data_ohlcv")

    def test_a_live_compressed_table_outside_the_hardened_set_still_raises(self) -> None:
        """The regression this class exists to prevent (code review, 2026-09-17): a table
        that IS genuinely compressed in production -- market_data_ohlcv, confirmed live to
        be one of the DB's other 24 compressed hypertables -- must still be rejected here.
        This allow-list answers "has this mechanism been validated for this table," not "is
        this table compressed" -- those are different questions with opposite-direction
        risk, and must never share one live-queried set."""
        with pytest.raises(ValueError, match="market_data_ohlcv"):
            _validate_compressed_hypertable("market_data_ohlcv")


class TestKnownCompressedHypertablesCache:
    """Todo 308: the live-cached replacement for the old hardcoded frozenset, used by
    bulk_update_by_key's "did you forget a session" guard specifically -- NOT by
    _validate_compressed_hypertable (see TestValidateCompressedHypertable above, a
    deliberately separate, still-static allow-list with the opposite risk direction).
    These tests explicitly reset the cache to None first (undoing the autouse prewarm
    fixture above) to exercise the actual cache-population path, which every other test
    in this file deliberately never touches."""

    def test_sync_accessor_queries_once_then_reuses_cache(self) -> None:
        _batch_utils_module._compressed_hypertable_names_cache = None
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [("feature_vectors",), ("feature_ic_scores",)]

        result_1 = _known_compressed_hypertables(conn)
        result_2 = _known_compressed_hypertables(conn)

        assert result_1 == frozenset({"feature_vectors", "feature_ic_scores"})
        assert result_2 == result_1
        cur.execute.assert_called_once_with(_batch_utils_module._LIVE_COMPRESSED_HYPERTABLES_SQL)

    @pytest.mark.asyncio
    async def test_async_accessor_queries_once_then_reuses_cache(self) -> None:
        _batch_utils_module._compressed_hypertable_names_cache = None
        conn = MagicMock()
        conn.fetch = AsyncMock(
            return_value=[
                {"hypertable_name": "feature_vectors"},
                {"hypertable_name": "feature_ic_scores"},
            ]
        )

        result_1 = await _known_compressed_hypertables_async(conn)
        result_2 = await _known_compressed_hypertables_async(conn)

        assert result_1 == frozenset({"feature_vectors", "feature_ic_scores"})
        assert result_2 == result_1
        conn.fetch.assert_called_once_with(_batch_utils_module._LIVE_COMPRESSED_HYPERTABLES_SQL)

    @pytest.mark.asyncio
    async def test_sync_and_async_accessors_share_one_cache(self) -> None:
        """Whichever driver populates the cache first, the other reuses it without its
        own query -- the underlying fact doesn't depend on which driver asked."""
        _batch_utils_module._compressed_hypertable_names_cache = None
        sync_conn = MagicMock()
        cur = sync_conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [("feature_vectors",), ("feature_ic_scores",)]

        sync_result = _known_compressed_hypertables(sync_conn)

        async_conn = MagicMock()
        async_conn.fetch = AsyncMock(side_effect=AssertionError("must not query -- cache is warm"))
        async_result = await _known_compressed_hypertables_async(async_conn)

        assert async_result == sync_result == frozenset({"feature_vectors", "feature_ic_scores"})
        async_conn.fetch.assert_not_called()

    def test_a_table_missing_from_the_live_result_is_correctly_unknown(self) -> None:
        """The whole point of todo 308, for bulk_update_by_key's guard specifically: a
        table absent from the live query's result is unknown, full stop -- no hand-
        maintained list to fall out of sync with reality. (Not `_validate_compressed_
        hypertable` -- that's a separate, deliberately-static allow-list, see
        TestValidateCompressedHypertable above.)"""
        _batch_utils_module._compressed_hypertable_names_cache = None
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value = [("feature_vectors",)]  # feature_ic_scores NOT returned

        known = _known_compressed_hypertables(conn)

        assert known == frozenset({"feature_vectors"})
        assert "feature_ic_scores" not in known


def _mock_sync_conn(
    n_decompressed: int = 0,
    n_recompressed: int = 0,
    compression_jobs: list[tuple[int, bool]] | None = None,
) -> MagicMock:
    """A psycopg-shaped connection mock: `cursor()` returns the same cursor mock on every
    call (so all cur.execute() calls across the session land in one call_args_list).
    `cur.rowcount` is scripted by which collapsed statement was just executed (decompress-
    all vs. compress-all) -- matching how compressed_hypertable_write_session actually
    reads the affected-row count (a single server-side statement per phase, not a
    list-then-loop), not an assumption about it. `compression_jobs` seeds the
    (job_id, scheduled) rows returned for the hypertable's compression-policy lookup --
    defaults to none found (todo 314's pause/resume logic is then a no-op, matching every
    pre-existing test that doesn't care about it)."""
    conn = MagicMock()
    conn.autocommit = False
    cur = conn.cursor.return_value.__enter__.return_value

    def _execute(sql: str, params: tuple | None = None) -> None:
        if sql.startswith("SELECT job_id, scheduled FROM timescaledb_information.jobs"):
            cur.fetchall.return_value = compression_jobs or []
        elif sql.startswith("SELECT config_key, config_value FROM config_state"):
            # No rows seeded -- the session falls back to its own defaults for every GUC
            # in _SESSION_GUC_OVERRIDES (combined into one ANY(%s) lookup, not one query
            # per key).
            cur.fetchall.return_value = []
        elif sql.startswith("SELECT current_setting("):
            # One combined round trip reads all _SESSION_GUC_OVERRIDES priors at once, in
            # (statement_timeout, idle_session_timeout, idle_in_transaction_session_timeout)
            # order -- values are arbitrary but distinguishable, only their round-trip
            # (captured, restored) is tested.
            cur.fetchone.return_value = ("30min", "1h", "1h")
        elif sql.startswith("SELECT decompress_chunk"):
            cur.rowcount = n_decompressed
        elif sql.startswith("SELECT compress_chunk"):
            cur.rowcount = n_recompressed
        # SELECT set_config(...), set_config(...), set_config(...) (both the entry
        # override and the exit restore use this identical shape): no return value
        # consumed by the real code, nothing to script here.

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
        -- exactly 8 execute() calls total for the whole session regardless of how many
        chunks are actually affected: the compression-policy-jobs lookup (1, todo 314 --
        zero jobs found here, so no pause/restore alter_job() calls follow), the combined
        _SESSION_GUC_OVERRIDES APR lookup (1), one combined current_setting() read for all
        3 GUCs (1), one combined set_config() write for all 3 GUCs (1), decompress-all (1),
        compress-all (1), VACUUM (1), and one combined set_config() restore for all 3 GUCs
        at exit (1)."""
        conn = _mock_sync_conn(n_decompressed=40, n_recompressed=40)
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_vectors"):
            pass

        assert cur.execute.call_count == 8

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

    def test_compression_policy_job_paused_for_duration_and_restored_after(self) -> None:
        """todo 314: a live compression-policy job racing this session's own decompress/
        recompress deadlocked in production (Columnstore Policy [1065] vs. regime_writer.py,
        2026-08-14). The job must be paused (alter_job(scheduled => false)) before this
        session touches any chunk, and restored to its PRIOR scheduled value (not
        unconditionally re-enabled -- a job an operator had already paused for other
        reasons must stay paused) once this session is done."""
        conn = _mock_sync_conn(compression_jobs=[(1065, True)])
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_vectors"):
            calls_at_entry = [c.args for c in cur.execute.call_args_list]
            assert ("SELECT alter_job(%s, scheduled => false)", (1065,)) in calls_at_entry
            assert not any(a[0] == "SELECT alter_job(%s, scheduled => %s)" for a in calls_at_entry)

        all_calls = [c.args for c in cur.execute.call_args_list]
        assert ("SELECT alter_job(%s, scheduled => %s)", (1065, True)) in all_calls

    def test_compression_policy_job_already_paused_stays_paused(self) -> None:
        """The restore step must write back the job's actual prior `scheduled` value, not
        assume it was always true -- an operator-paused job (scheduled=False before this
        session ever started) must not get silently re-enabled on exit."""
        conn = _mock_sync_conn(compression_jobs=[(1065, False)])
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_vectors"):
            pass

        all_calls = [c.args for c in cur.execute.call_args_list]
        assert ("SELECT alter_job(%s, scheduled => %s)", (1065, False)) in all_calls

    def test_entry_phase_failure_restores_paused_job_before_raising(self) -> None:
        """Code review finding (2026-08-20): the job is paused at the very start of the
        entry phase -- if the decompress that follows it fails (statement-timeout kill
        2026-08-14, idle-session kill 2026-08-15 are both documented as having actually
        happened at exactly this call), the exception used to propagate straight out of
        the function, before `try: yield` was ever reached, so the normal exit `finally`
        never ran and the job stayed at scheduled=false forever. Must now be restored by
        the entry-phase except-clause instead."""
        conn = _mock_sync_conn(compression_jobs=[(1065, True)])
        cur = conn.cursor.return_value.__enter__.return_value
        original_execute = cur.execute.side_effect

        def _fail_on_decompress(sql: str, params: tuple | None = None) -> None:
            if sql.startswith("SELECT decompress_chunk"):
                raise RuntimeError("statement timeout")
            original_execute(sql, params)

        cur.execute.side_effect = _fail_on_decompress

        with pytest.raises(RuntimeError, match="statement timeout"):
            with compressed_hypertable_write_session(conn, "feature_vectors"):
                pytest.fail("body must never run -- entry phase failed first")

        all_calls = [c.args for c in cur.execute.call_args_list]
        assert ("SELECT alter_job(%s, scheduled => %s)", (1065, True)) in all_calls
        conn.rollback.assert_called_once()

    def test_no_compression_policy_job_is_a_safe_no_op(self) -> None:
        """A hypertable with no compression policy at all (or one already covered by the
        default empty-list mock) must not error -- the lookup finds zero jobs, pause/
        restore loops do nothing."""
        conn = _mock_sync_conn()
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_vectors"):
            pass

        assert not any("alter_job" in str(c.args[0]) for c in cur.execute.call_args_list)

    # Expected combined set_config() call shape -- both the entry override and the exit
    # restore use this identical SQL text, differing only in the bound values, matching
    # _SESSION_GUC_OVERRIDES's (statement_timeout, idle_session_timeout,
    # idle_in_transaction_session_timeout) order.
    _SET_CONFIG_SQL = "SELECT " + ", ".join("set_config(%s, %s, false)" for _ in range(3))

    def test_idle_timeouts_set_at_entry_and_restored_at_exit(self) -> None:
        """todo 318: idle_session_timeout AND idle_in_transaction_session_timeout must both
        be overridden for the session's duration (default disabled -- '0') and restored to
        the connection's prior values on exit -- the exact protection the missing form of
        this let regime_writer.py's connection get killed mid-run (confirmed live
        2026-08-15, see this function's docstring). One combined set_config() call covers
        all three GUCs (statement_timeout too) per direction, not one call per GUC."""
        conn = _mock_sync_conn()
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_vectors"):
            calls_at_entry = [
                (c.args[0], c.args[1] if len(c.args) > 1 else None)
                for c in cur.execute.call_args_list
            ]
            assert (
                self._SET_CONFIG_SQL,
                (
                    "statement_timeout",
                    "14400000",
                    "idle_session_timeout",
                    "0",
                    "idle_in_transaction_session_timeout",
                    "0",
                ),
            ) in calls_at_entry

        all_calls = [
            (c.args[0], c.args[1] if len(c.args) > 1 else None) for c in cur.execute.call_args_list
        ]
        assert (
            self._SET_CONFIG_SQL,
            (
                "statement_timeout",
                "30min",
                "idle_session_timeout",
                "1h",
                "idle_in_transaction_session_timeout",
                "1h",
            ),
        ) in all_calls

    def test_idle_timeouts_set_before_decompress_and_restored_after_vacuum(self) -> None:
        """Ordering matters: the override must be active for the ENTIRE bracket (including
        the caller's own work between decompress and compress), not just around the
        decompress/compress calls themselves -- restoring too early would reopen the exact
        idle-kill window this fix exists to close."""
        conn = _mock_sync_conn(n_decompressed=1, n_recompressed=1)
        cur = conn.cursor.return_value.__enter__.return_value

        with compressed_hypertable_write_session(conn, "feature_vectors"):
            pass

        sqls = [c.args[0] for c in cur.execute.call_args_list]
        set_config_indices = [i for i, s in enumerate(sqls) if s == self._SET_CONFIG_SQL]
        decompress_idx = next(i for i, s in enumerate(sqls) if s.startswith("SELECT decompress"))
        vacuum_idx = next(i for i, s in enumerate(sqls) if s.startswith("VACUUM"))

        assert len(set_config_indices) == 2  # entry override, exit restore
        entry_idx, restore_idx = set_config_indices
        assert entry_idx < decompress_idx
        assert restore_idx > vacuum_idx

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
        """The guard only fires for known compressed hypertables -- an ordinary table's
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


class TestClampToRealRange:
    """todo 312: an HMM posterior probability underflowing float4's representable range
    made Postgres reject the write outright rather than round it -- these are the pure
    boundary-condition tests for the clamp that fixes it."""

    def test_underflowing_positive_value_clamps_to_zero(self) -> None:
        assert _clamp_to_real_range(1e-50) == 0.0

    def test_underflowing_negative_value_clamps_to_zero(self) -> None:
        assert _clamp_to_real_range(-1e-50) == 0.0

    def test_smallest_representable_subnormal_passes_through_unchanged(self) -> None:
        assert _clamp_to_real_range(_REAL_MIN_MAGNITUDE) == _REAL_MIN_MAGNITUDE

    def test_overflowing_positive_value_clamps_to_real_max(self) -> None:
        assert _clamp_to_real_range(1e50) == _REAL_MAX_MAGNITUDE

    def test_overflowing_negative_value_clamps_to_negative_real_max(self) -> None:
        assert _clamp_to_real_range(-1e50) == -_REAL_MAX_MAGNITUDE

    def test_ordinary_probability_passes_through_unchanged(self) -> None:
        assert _clamp_to_real_range(0.5) == 0.5

    def test_exact_zero_passes_through_unchanged(self) -> None:
        assert _clamp_to_real_range(0.0) == 0.0

    def test_none_passes_through_unchanged(self) -> None:
        assert _clamp_to_real_range(None) is None

    def test_nan_passes_through_unchanged(self) -> None:
        result = _clamp_to_real_range(float("nan"))
        assert result != result  # NaN != NaN is the only valid NaN check

    def test_infinity_passes_through_unchanged(self) -> None:
        assert _clamp_to_real_range(float("inf")) == float("inf")

    def test_non_float_value_passes_through_unchanged(self) -> None:
        assert _clamp_to_real_range("trending_up") == "trending_up"
        assert _clamp_to_real_range(5) == 5


class TestBulkUpdateByKeyRealClamping:
    def _written_csv(self, conn: MagicMock) -> str:
        cur = conn.cursor.return_value.__enter__.return_value
        copy_ctx = cur.copy.return_value.__enter__.return_value
        return "".join(c.args[0] for c in copy_ctx.write.call_args_list)

    def test_underflowing_value_in_a_real_column_is_clamped_before_copy(self) -> None:
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.copy.return_value.__enter__.return_value = MagicMock()
        bulk_update_by_key(
            conn,
            table="some_table",
            temp_table="_t",
            key_cols=["symbol"],
            set_cols=["hmm_entropy"],
            col_types={"symbol": "text", "hmm_entropy": "real"},
            rows=[(1e-50, "SPY")],
        )
        csv_text = self._written_csv(conn)
        assert "1e-50" not in csv_text
        assert csv_text.startswith("0.0") or csv_text.startswith("0,")

    def test_double_precision_column_is_never_clamped_regression(self) -> None:
        """Regression: before this fix, col_types said 'double precision' for columns
        migrations 201/312 had already narrowed to 'real' in the live schema, so this
        clamp silently never fired for them. A genuinely double-precision column must
        still pass an underflowing-for-float4 value through untouched -- double
        precision can represent it fine."""
        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.copy.return_value.__enter__.return_value = MagicMock()
        bulk_update_by_key(
            conn,
            table="some_table",
            temp_table="_t",
            key_cols=["symbol"],
            set_cols=["some_double_col"],
            col_types={"symbol": "text", "some_double_col": "double precision"},
            rows=[(1e-50, "SPY")],
        )
        csv_text = self._written_csv(conn)
        assert "1e-50" in csv_text


def _mock_async_conn(
    n_decompressed: int = 0,
    n_recompressed: int = 0,
    compression_jobs: list[dict[str, object]] | None = None,
) -> MagicMock:
    """asyncpg-shaped connection mock. `execute()` returns the command tag string asyncpg
    itself returns for a plain SELECT ("SELECT <n>") -- confirmed live 2026-08-14 -- since
    async_compressed_hypertable_write_session parses the affected-row count from that tag
    rather than a separate count(*) query. `compression_jobs` seeds the rows returned for
    the hypertable's compression-policy lookup (todo 314) -- defaults to none found."""
    conn = MagicMock()

    async def _execute(sql: str, *args: object) -> str:
        if sql.startswith(_DECOMPRESS_ALL_COMPRESSED_CHUNKS_ASYNCPG_SQL):
            return f"SELECT {n_decompressed}"
        if sql.startswith(_COMPRESS_ALL_DECOMPRESSED_CHUNKS_ASYNCPG_SQL):
            return f"SELECT {n_recompressed}"
        return "VACUUM"

    conn.execute = AsyncMock(side_effect=_execute)

    async def _fetch(sql: str, *args: object) -> list[dict[str, object]]:
        if sql.startswith(_FIND_COMPRESSION_JOBS_ASYNCPG_SQL):
            return compression_jobs or []
        return []  # load_apr_dict_async's config lookup -- no APR rows configured.

    conn.fetch = AsyncMock(side_effect=_fetch)
    # The combined-GUC-priors read's conn.fetchrow. A plain dict stands in for
    # asyncpg.Record here -- .values() preserves insertion order the same way Record
    # preserves SELECT column order, which is all list(prior_row.values()) in the real
    # code relies on.
    conn.fetchrow = AsyncMock(
        return_value={
            "statement_timeout": "30min",
            "idle_session_timeout": "1h",
            "idle_in_transaction_session_timeout": "1h",
        }
    )
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
    async def test_compression_policy_job_paused_for_duration_and_restored_after(self) -> None:
        """Async sibling of the sync test with the same name -- see its docstring for the
        todo 314 incident rationale."""
        conn = _mock_async_conn(compression_jobs=[{"job_id": 1065, "scheduled": True}])

        async with async_compressed_hypertable_write_session(conn, "feature_ic_scores"):
            calls_at_entry = [c.args for c in conn.execute.call_args_list]
            assert ("SELECT alter_job($1, scheduled => false)", 1065) in calls_at_entry
            assert not any(a[0] == "SELECT alter_job($1, scheduled => $2)" for a in calls_at_entry)

        all_calls = [c.args for c in conn.execute.call_args_list]
        assert ("SELECT alter_job($1, scheduled => $2)", 1065, True) in all_calls

    @pytest.mark.asyncio
    async def test_compression_policy_job_already_paused_stays_paused(self) -> None:
        conn = _mock_async_conn(compression_jobs=[{"job_id": 1065, "scheduled": False}])

        async with async_compressed_hypertable_write_session(conn, "feature_ic_scores"):
            pass

        all_calls = [c.args for c in conn.execute.call_args_list]
        assert ("SELECT alter_job($1, scheduled => $2)", 1065, False) in all_calls

    @pytest.mark.asyncio
    async def test_sets_active_session_contextvar_for_duration_only(self) -> None:
        conn = _mock_async_conn()
        assert _active_write_session_hypertable.get() is None

        async with async_compressed_hypertable_write_session(conn, "feature_ic_scores"):
            assert _active_write_session_hypertable.get() == "feature_ic_scores"

        assert _active_write_session_hypertable.get() is None

    # Expected combined set_config() call shape for the async sibling -- one call covers
    # all 3 GUCs (statement_timeout, idle_session_timeout,
    # idle_in_transaction_session_timeout) per direction, asyncpg $N-numbered.
    _SET_CONFIG_SQL = "SELECT " + ", ".join(
        f"set_config(${2 * i + 1}, ${2 * i + 2}, false)" for i in range(3)
    )

    @pytest.mark.asyncio
    async def test_idle_timeouts_set_at_entry_and_restored_at_exit(self) -> None:
        """todo 318 async sibling: idle_session_timeout AND
        idle_in_transaction_session_timeout must both be overridden for the session's
        duration (default disabled -- '0') and restored to the connection's prior values
        on exit -- same protection as the sync version, same live incident."""
        conn = _mock_async_conn()

        async with async_compressed_hypertable_write_session(conn, "feature_ic_scores"):
            calls_at_entry = [c.args for c in conn.execute.call_args_list]
            assert (
                self._SET_CONFIG_SQL,
                "statement_timeout",
                "14400000",
                "idle_session_timeout",
                "0",
                "idle_in_transaction_session_timeout",
                "0",
            ) in calls_at_entry

        all_calls = [c.args for c in conn.execute.call_args_list]
        # _mock_async_conn's fetchrow returns fixed prior values per GUC (dict insertion
        # order mirrors asyncpg.Record's column order) -- restore uses those, not the
        # entry override values.
        assert (
            self._SET_CONFIG_SQL,
            "statement_timeout",
            "30min",
            "idle_session_timeout",
            "1h",
            "idle_in_transaction_session_timeout",
            "1h",
        ) in all_calls

    @pytest.mark.asyncio
    async def test_entry_phase_failure_restores_paused_job_before_raising(self) -> None:
        """Async sibling of the sync test with the same name -- see its docstring."""
        conn = _mock_async_conn(compression_jobs=[{"job_id": 1065, "scheduled": True}])
        original_execute_side_effect = conn.execute.side_effect

        async def _fail_on_decompress(sql: str, *args: object) -> str:
            if sql.startswith(_DECOMPRESS_ALL_COMPRESSED_CHUNKS_ASYNCPG_SQL):
                raise RuntimeError("statement timeout")
            return await original_execute_side_effect(sql, *args)

        conn.execute = AsyncMock(side_effect=_fail_on_decompress)

        with pytest.raises(RuntimeError, match="statement timeout"):
            async with async_compressed_hypertable_write_session(conn, "feature_ic_scores"):
                pytest.fail("body must never run -- entry phase failed first")

        all_calls = [c.args for c in conn.execute.call_args_list]
        assert ("SELECT alter_job($1, scheduled => $2)", 1065, True) in all_calls


class TestAsyncCompressedHypertableWriteSessionOrNoop:
    @pytest.mark.asyncio
    async def test_returns_noop_when_apply_false(self) -> None:
        conn = _mock_async_conn()
        async with async_compressed_hypertable_write_session_or_noop(
            conn, "feature_ic_scores", apply=False
        ):
            pass
        conn.execute.assert_not_called()


def test_disk_backed_append_row_without_flush_at_fails_loudly(tmp_path):
    """174 review IN-07: row mode with no flush_at buffers the whole cell in RAM."""
    acc = Float32ChunkAccumulator(
        disk_backed=True, estimated_rows=10, n_cols=2, scratch_dir=str(tmp_path)
    )
    try:
        with pytest.raises(ValueError, match="requires flush_at"):
            acc.append_row(np.zeros(2, dtype=np.float32))
    finally:
        acc.close()


def test_disk_backed_append_row_with_flush_at_still_works(tmp_path):
    acc = Float32ChunkAccumulator(
        2, disk_backed=True, estimated_rows=10, n_cols=2, scratch_dir=str(tmp_path)
    )
    try:
        for i in range(5):
            acc.append_row(np.full(2, i, dtype=np.float32))
        out = np.asarray(acc.finalize())
        assert out[:, 0].tolist() == [0, 1, 2, 3, 4]
    finally:
        acc.close()


class TestDecompressHeadroomGuard:
    """Todo 426: refuse before decompressing when the disk can't hold the decompressed chunks."""

    _TB = 10**12

    def _usage(self, total, free):
        import shutil as _shutil

        return _shutil._ntuple_diskusage(total, total - free, free)

    def test_raises_when_decompress_would_eat_the_reserve(self):
        from services._batch_utils import check_decompress_headroom

        with patch(
            "services._batch_utils.shutil.disk_usage", return_value=self._usage(914e9, 414e9)
        ):
            with pytest.raises(RuntimeError, match="refused"):
                check_decompress_headroom("feature_vectors", int(491e9), "/", 0.10)

    def test_passes_with_room_to_spare(self):
        from services._batch_utils import check_decompress_headroom

        with patch(
            "services._batch_utils.shutil.disk_usage", return_value=self._usage(914e9, 414e9)
        ):
            check_decompress_headroom("feature_vectors", int(6e9), "/", 0.10)

    @pytest.mark.real_headroom_check
    def test_sync_session_refuses_before_touching_anything(self):
        from services._batch_utils import compressed_hypertable_write_session

        conn = MagicMock()
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = (int(491e9),)
        cur.fetchall.return_value = []
        with patch(
            "services._batch_utils.shutil.disk_usage", return_value=self._usage(914e9, 414e9)
        ):
            with pytest.raises(RuntimeError, match="refused"):
                with compressed_hypertable_write_session(conn, "feature_vectors"):
                    pass
        sql = " ".join(str(c.args[0]) for c in cur.execute.call_args_list)
        assert "alter_job" not in sql and "decompress_chunk" not in sql

    @pytest.mark.real_headroom_check
    async def test_async_session_refuses_before_touching_anything(self):
        from services._batch_utils import async_compressed_hypertable_write_session

        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=int(491e9))
        conn.fetch = AsyncMock(return_value=[])
        conn.execute = AsyncMock()
        with patch(
            "services._batch_utils.shutil.disk_usage", return_value=self._usage(914e9, 414e9)
        ):
            with pytest.raises(RuntimeError, match="refused"):
                async with async_compressed_hypertable_write_session(conn, "feature_vectors"):
                    pass
        conn.execute.assert_not_called()
