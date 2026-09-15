"""Unit tests: cross-sectional cell memory-bound guard (Phase 174 Plan 05, D-04a/D-04c,
todo 371).

No live database and no real multi-GB allocation -- `_compute_cross_sectional_tf`'s own
DB connection is replaced with a fake `short_lived_conn` backed by an in-memory fake
cursor/connection, and its two per-cell compute functions
(`_compute_one_cross_sectional_cell` / `_compute_one_broadcast_cell`) are monkeypatched
to trivial fakes wherever the test's own assertions don't require them (they are real
consumers of the memmap view only in the premature-close guard test, case 7b, where the
whole point is to prove close() cannot run before they return).

Coverage: the pre-flight guard fires before any fetch (D-04a), the guard's error message
identifies itself, under-ceiling cells proceed unchanged, accumulator mode selection
(threshold + the disk_backed_min_rows=0 always-disk override), scratch-file cleanup on
both the success and exception paths, the premature-close ordering guard, the two-file
disk-headroom check, the no-automatic-degrade module-source assertion (D-04 / T-174-06),
and disk-backed accumulation's memory bound (D-04c, @pytest.mark.performance).
"""

from __future__ import annotations

import re
import resource
import sys
import tracemalloc
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import services.ic_engine as ic_module
from services._batch_utils import Float32ChunkAccumulator
from services.ic_engine import (
    _FEATURE_NAMES,
    CellTooLargeError,
    ICEngineConfig,
    _compute_cross_sectional_tf,
)

_N_FEATURES = len(_FEATURE_NAMES)
_TF = "1h"


# ---------------------------------------------------------------------------
# Shared fakes/helpers
# ---------------------------------------------------------------------------


def _make_config(
    *,
    max_cell_rows: int = 15_000_000,
    disk_backed_min_rows: int = 2_000_000,
    memmap_scratch_dir: str,
    cs_chunk_ts: int = 1_000_000,
) -> ICEngineConfig:
    """Minimal direct ICEngineConfig construction -- mirrors test_hac_ic_sharpe.py's
    established pattern for the ~19 fields with no dataclass default."""
    return ICEngineConfig(
        min_observations=500,
        fdr_alpha=0.05,
        walk_forward_folds=3,
        sharpe_window_size=50,
        sharpe_window_size_subsampled=50,
        sharpe_min_windows=3,
        subsample_min_stride=5,
        min_reliable_n=100,
        cluster_max_corr=0.70,
        lookahead_fast={"5m": 1, "15m": 1, "1h": 1, "1d": 1},
        lookahead_mid={"5m": 6, "15m": 2, "1h": 2, "1d": 2},
        lookahead_slow={"5m": 12, "15m": 5, "1h": 20, "1d": 5},
        lookahead_extended={"5m": 39, "15m": 10, "1h": 60, "1d": 10},
        active_scales={
            "5m": ("fast",),
            "15m": ("fast",),
            "1h": ("fast",),
            "1d": ("fast",),
        },
        equity_model_enabled=True,
        hac_max_lag=3,
        cs_chunk_ts=cs_chunk_ts,
        symbol_fetch_chunk_rows=5000,
        n_workers=1,
        blas_threads_per_worker=1,
        max_cell_rows=max_cell_rows,
        disk_backed_min_rows=disk_backed_min_rows,
        memmap_scratch_dir=memmap_scratch_dir,
    )


def _ts_rows(n: int) -> list[tuple[datetime]]:
    """n synthetic market_regimes.ts rows -- content is irrelevant to every test here
    except row count (which drives the pre-flight estimate), so one repeated value is
    fine and avoids an O(n) datetime-construction cost for the larger counts."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [(base,)] * n


def _batch_rows(n_rows: int, n_scales: int = 1, start: int = 0) -> list[tuple[Any, ...]]:
    """n_rows synthetic feature_vectors JOIN forward_returns rows, column order matching
    _compute_cross_sectional_tf's chunk_sql: bar_ts, {n_features feature floats},
    {n_scales returns}, {n_scales completes}."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(n_rows):
        bar_ts = base + timedelta(minutes=start + i)
        features = [0.1 + 0.001 * i] * _N_FEATURES
        returns = [0.01] * n_scales
        completes = [True] * n_scales
        rows.append((bar_ts, *features, *returns, *completes))
    return rows


class _FakeCursor:
    """Routes execute() by SQL shape (the only signal available -- these are plain
    positional-cursor calls, not named prepared statements) and records every chunk
    fetch on the shared fake connection for the "zero fetch before pre-flight raises"
    assertion."""

    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn
        self._result: list[tuple[Any, ...]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        return False

    def execute(self, sql: str, params: dict | None = None) -> None:
        self._conn.executed_sql.append(sql)
        if "FROM market_regimes" in sql:
            self._result = self._conn.regime_timestamp_rows
        elif "FROM feature_vectors fv" in sql:
            self._conn.chunk_fetch_count += 1
            self._result = self._conn.next_chunk_batch()
        else:
            self._result = []

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._result


class _FakeConn:
    def __init__(
        self,
        regime_timestamp_rows: list[tuple[datetime]],
        chunk_batches: list[list[tuple[Any, ...]]] | None = None,
    ) -> None:
        self.executed_sql: list[str] = []
        self.regime_timestamp_rows = regime_timestamp_rows
        self._chunk_batches = list(chunk_batches or [])
        self.chunk_fetch_count = 0
        self.commit_count = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        self.commit_count += 1

    def close(self) -> None:
        pass

    def next_chunk_batch(self) -> list[tuple[Any, ...]]:
        if self._chunk_batches:
            return self._chunk_batches.pop(0)
        return []


def _patch_short_lived_conn(monkeypatch: pytest.MonkeyPatch, fake_conn: _FakeConn) -> None:
    @contextmanager
    def _fake_short_lived_conn(dsn: str):
        yield fake_conn

    monkeypatch.setattr(ic_module, "short_lived_conn", _fake_short_lived_conn)


def _patch_trivial_cell_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both per-cell compute functions are the two SYNCHRONOUS consumers of the
    memmap view inside the try/finally -- stubbing them to a trivial (empty-rows,
    zero-skipped) return lets tests that don't care about the real clustering/
    bootstrap machinery reach the fetch/accumulate/cleanup phases without needing a
    fully realistic synthetic corpus."""

    def _fake_cell(*args: Any, **kwargs: Any) -> tuple[list[dict], int]:
        return [], 0

    monkeypatch.setattr(ic_module, "_compute_one_cross_sectional_cell", _fake_cell)
    monkeypatch.setattr(ic_module, "_compute_one_broadcast_cell", _fake_cell)


def _call(
    config: ICEngineConfig,
    *,
    symbol_list: list[str] | None = None,
    regime_label: str = "calm",
) -> tuple[list[dict], dict[str, Any]]:
    return _compute_cross_sectional_tf(
        dsn="postgresql://fake-dsn",
        tf=_TF,
        regime_label=regime_label,
        regime_group="equity",
        symbol_list=symbol_list or ["SPY", "QQQ", "IWM"],
        training_window_end=datetime(2026, 1, 1, tzinfo=UTC),
        config=config,
        tracer=None,
        run_ts=datetime(2026, 1, 1, tzinfo=UTC),
        rng=np.random.default_rng(0),
        feature_status_map={},
        broadcast_features=frozenset(),
    )


# ---------------------------------------------------------------------------
# Case 1 + 2: pre-flight fires before any fetch (D-04a), message identifies itself
# ---------------------------------------------------------------------------


def test_preflight_raises_before_any_fetch(tmp_path, monkeypatch):
    config = _make_config(max_cell_rows=2, memmap_scratch_dir=str(tmp_path))
    fake_conn = _FakeConn(regime_timestamp_rows=_ts_rows(5))
    _patch_short_lived_conn(monkeypatch, fake_conn)
    _patch_trivial_cell_functions(monkeypatch)

    with pytest.raises(CellTooLargeError):
        _call(config, symbol_list=["SPY", "QQQ", "IWM"])

    assert (
        fake_conn.chunk_fetch_count == 0
    ), "pre-flight guard must raise BEFORE the chunk-fetch SQL executes even once"


def test_preflight_error_message_identifies_guard(tmp_path, monkeypatch):
    config = _make_config(max_cell_rows=2, memmap_scratch_dir=str(tmp_path))
    fake_conn = _FakeConn(regime_timestamp_rows=_ts_rows(5))
    _patch_short_lived_conn(monkeypatch, fake_conn)
    _patch_trivial_cell_functions(monkeypatch)

    with pytest.raises(CellTooLargeError) as exc_info:
        _call(config, symbol_list=["SPY", "QQQ", "IWM"], regime_label="calm")

    message = str(exc_info.value)
    assert "pre-flight estimate" in message
    assert "tf=1h" in message
    assert "regime=calm" in message


# ---------------------------------------------------------------------------
# Case 3: under-ceiling cells proceed unchanged
# ---------------------------------------------------------------------------


def test_under_ceiling_cell_proceeds_and_executes_chunk_fetch(tmp_path, monkeypatch):
    config = _make_config(max_cell_rows=15_000_000, memmap_scratch_dir=str(tmp_path))
    fake_conn = _FakeConn(regime_timestamp_rows=_ts_rows(5), chunk_batches=[[]])
    _patch_short_lived_conn(monkeypatch, fake_conn)
    _patch_trivial_cell_functions(monkeypatch)

    all_results, stats = _call(config, symbol_list=["SPY", "QQQ", "IWM"])

    assert all_results == []
    assert stats == {"n_committed": 0, "n_skipped": 0}
    assert fake_conn.chunk_fetch_count == 1


# ---------------------------------------------------------------------------
# Case 4: mode selection threshold
# ---------------------------------------------------------------------------


def test_mode_selection_below_threshold_stays_in_ram(tmp_path, monkeypatch):
    captured: dict[str, Any] = {}
    original_acc = ic_module.Float32ChunkAccumulator

    def _spy_ctor(*args: Any, **kwargs: Any) -> Float32ChunkAccumulator:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return original_acc(*args, **kwargs)

    monkeypatch.setattr(ic_module, "Float32ChunkAccumulator", _spy_ctor)

    # n_estimated = 5 * 3 = 15, well under disk_backed_min_rows.
    config = _make_config(
        max_cell_rows=15_000_000, disk_backed_min_rows=1_000, memmap_scratch_dir=str(tmp_path)
    )
    fake_conn = _FakeConn(regime_timestamp_rows=_ts_rows(5), chunk_batches=[[]])
    _patch_short_lived_conn(monkeypatch, fake_conn)
    _patch_trivial_cell_functions(monkeypatch)

    _call(config, symbol_list=["SPY", "QQQ", "IWM"])

    assert captured["kwargs"] == {}, (
        f"in-RAM mode must construct Float32ChunkAccumulator() with no kwargs, got "
        f"{captured['kwargs']!r}"
    )


def test_mode_selection_at_or_above_threshold_goes_disk_backed(tmp_path, monkeypatch):
    captured: dict[str, Any] = {}
    original_acc = ic_module.Float32ChunkAccumulator

    def _spy_ctor(*args: Any, **kwargs: Any) -> Float32ChunkAccumulator:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return original_acc(*args, **kwargs)

    monkeypatch.setattr(ic_module, "Float32ChunkAccumulator", _spy_ctor)

    # n_estimated = 5 * 3 = 15, at the (deliberately tiny) disk_backed_min_rows.
    config = _make_config(
        max_cell_rows=15_000_000, disk_backed_min_rows=15, memmap_scratch_dir=str(tmp_path)
    )
    fake_conn = _FakeConn(regime_timestamp_rows=_ts_rows(5), chunk_batches=[[]])
    _patch_short_lived_conn(monkeypatch, fake_conn)
    _patch_trivial_cell_functions(monkeypatch)

    _call(config, symbol_list=["SPY", "QQQ", "IWM"])

    assert captured["kwargs"].get("disk_backed") is True
    assert captured["kwargs"].get("estimated_rows") == 15
    assert captured["kwargs"].get("n_cols") == _N_FEATURES
    assert captured["kwargs"].get("scratch_dir") == str(tmp_path)


def test_disk_backed_min_rows_zero_means_always_disk_backed(tmp_path, monkeypatch):
    captured: dict[str, Any] = {}
    original_acc = ic_module.Float32ChunkAccumulator

    def _spy_ctor(*args: Any, **kwargs: Any) -> Float32ChunkAccumulator:
        captured["kwargs"] = kwargs
        return original_acc(*args, **kwargs)

    monkeypatch.setattr(ic_module, "Float32ChunkAccumulator", _spy_ctor)

    # n_estimated = 1 * 1 = 1 -- tiny, but disk_backed_min_rows=0 must still force disk mode.
    config = _make_config(
        max_cell_rows=15_000_000, disk_backed_min_rows=0, memmap_scratch_dir=str(tmp_path)
    )
    fake_conn = _FakeConn(regime_timestamp_rows=_ts_rows(1), chunk_batches=[[]])
    _patch_short_lived_conn(monkeypatch, fake_conn)
    _patch_trivial_cell_functions(monkeypatch)

    _call(config, symbol_list=["SPY"])

    assert captured["kwargs"].get("disk_backed") is True


# ---------------------------------------------------------------------------
# Case 6 + 7: cleanup on the success and exception paths
# ---------------------------------------------------------------------------


def test_cleanup_on_success_path_removes_scratch_file(tmp_path, monkeypatch):
    config = _make_config(
        max_cell_rows=15_000_000, disk_backed_min_rows=0, memmap_scratch_dir=str(tmp_path)
    )
    batch = _batch_rows(3)
    fake_conn = _FakeConn(regime_timestamp_rows=_ts_rows(3), chunk_batches=[batch])
    _patch_short_lived_conn(monkeypatch, fake_conn)
    _patch_trivial_cell_functions(monkeypatch)

    all_results, stats = _call(config, symbol_list=["SPY"])

    assert stats["n_committed"] == 0
    assert list(tmp_path.glob("*.memmap")) == []


def test_cleanup_on_row_count_mismatch_exception_path(tmp_path, monkeypatch):
    config = _make_config(
        max_cell_rows=15_000_000, disk_backed_min_rows=0, memmap_scratch_dir=str(tmp_path)
    )
    batch = _batch_rows(3)
    fake_conn = _FakeConn(regime_timestamp_rows=_ts_rows(3), chunk_batches=[batch])
    _patch_short_lived_conn(monkeypatch, fake_conn)
    _patch_trivial_cell_functions(monkeypatch)

    original_finalize = Float32ChunkAccumulator.finalize

    def _truncating_finalize(self: Float32ChunkAccumulator) -> np.ndarray | None:
        real = original_finalize(self)
        if real is None:
            return None
        return real[:-1]  # drop one row -> forces a bar_ts/X_raw length mismatch

    monkeypatch.setattr(Float32ChunkAccumulator, "finalize", _truncating_finalize)

    with pytest.raises(RuntimeError, match="row-count mismatch"):
        _call(config, symbol_list=["SPY"])

    assert list(tmp_path.glob("*.memmap")) == [], (
        "scratch file must be cleaned up even when the row-count-mismatch RuntimeError "
        "fires after finalize()"
    )


# ---------------------------------------------------------------------------
# Case 7b: close() happens strictly after the cell consumer returns
# ---------------------------------------------------------------------------


def test_close_happens_strictly_after_consumer_returns(tmp_path, monkeypatch):
    config = _make_config(
        max_cell_rows=15_000_000, disk_backed_min_rows=0, memmap_scratch_dir=str(tmp_path)
    )
    batch = _batch_rows(3)
    fake_conn = _FakeConn(regime_timestamp_rows=_ts_rows(3), chunk_batches=[batch])
    _patch_short_lived_conn(monkeypatch, fake_conn)

    sequence = {"n": 0}
    order: dict[str, Any] = {}

    def _spy_cell(regime_label: str, *, X_raw: Any, **kwargs: Any) -> tuple[list[dict], int]:
        order["cell_entry"] = sequence["n"]
        sequence["n"] += 1
        # Real read through the mapping -- a closed mmap raises here, not a shape check.
        order["cell_read_value"] = float(np.asarray(X_raw[-1]).sum())
        order["cell_exit"] = sequence["n"]
        sequence["n"] += 1
        return [], 0

    def _fake_broadcast(*args: Any, **kwargs: Any) -> tuple[list[dict], int]:
        return [], 0

    monkeypatch.setattr(ic_module, "_compute_one_cross_sectional_cell", _spy_cell)
    monkeypatch.setattr(ic_module, "_compute_one_broadcast_cell", _fake_broadcast)

    original_close = Float32ChunkAccumulator.close

    def _spy_close(self: Float32ChunkAccumulator) -> None:
        order["close_call"] = sequence["n"]
        sequence["n"] += 1
        original_close(self)

    monkeypatch.setattr(Float32ChunkAccumulator, "close", _spy_close)

    _call(config, symbol_list=["SPY"])

    assert "cell_read_value" in order, "the spy must have run and read through X_raw"
    assert order["cell_exit"] < order["close_call"], (
        "X_acc.close() ran before the cell consumer returned -- the finally is scoped "
        "too narrowly (T-174-43)"
    )


# ---------------------------------------------------------------------------
# Case 7c: disk-headroom check reserves for two scratch files (2.2x, not 1.0x)
# ---------------------------------------------------------------------------


def test_disk_headroom_check_reserves_for_two_scratch_files(tmp_path, monkeypatch):
    n_symbols = 1
    n_ts = 1000
    config = _make_config(
        max_cell_rows=15_000_000, disk_backed_min_rows=0, memmap_scratch_dir=str(tmp_path)
    )
    fake_conn = _FakeConn(regime_timestamp_rows=_ts_rows(n_ts))
    _patch_short_lived_conn(monkeypatch, fake_conn)
    _patch_trivial_cell_functions(monkeypatch)

    n_estimated = n_ts * n_symbols
    one_file_bytes = n_estimated * _N_FEATURES * 4
    two_file_bytes = int(2.2 * one_file_bytes)
    # Free space clears a single-array accounting but not the real 2.2x requirement.
    free_bytes = one_file_bytes + (two_file_bytes - one_file_bytes) // 2

    class _FakeDiskUsage:
        total = two_file_bytes * 10
        used = 0
        free = free_bytes

    monkeypatch.setattr(ic_module.shutil, "disk_usage", lambda path: _FakeDiskUsage())

    with pytest.raises(RuntimeError) as exc_info:
        _call(config, symbol_list=["SPY"])

    message = str(exc_info.value)
    assert str(two_file_bytes) in message
    assert str(free_bytes) in message
    assert fake_conn.chunk_fetch_count == 0


# ---------------------------------------------------------------------------
# Case 8: no automatic degrade (D-04 / T-174-06) -- machine-checked over module source
# ---------------------------------------------------------------------------


def test_no_except_cell_too_large_error_handler_degrades():
    source_path = Path(ic_module.__file__)
    lines = source_path.read_text().splitlines()

    except_line_indices = [
        i for i, line in enumerate(lines) if re.search(r"except\s+CellTooLargeError\b", line)
    ]
    assert len(except_line_indices) == 1, (
        f"expected exactly one 'except CellTooLargeError' handler, found "
        f"{len(except_line_indices)}"
    )

    idx = except_line_indices[0]
    except_indent = len(lines[idx]) - len(lines[idx].lstrip())

    body_lines: list[str] = []
    for line in lines[idx + 1 :]:
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= except_indent:
            break
        if line.strip().startswith("#"):
            continue
        body_lines.append(line)

    assert body_lines, "the except CellTooLargeError handler must have a real body"
    forbidden = re.compile(r"subsample|sample|stride|reduce", re.IGNORECASE)
    for line in body_lines:
        assert not forbidden.search(
            line
        ), f"except CellTooLargeError handler body must not degrade/subsample: {line!r}"


# ---------------------------------------------------------------------------
# Case 9: memory-bounded accumulation (D-04c)
# ---------------------------------------------------------------------------


@pytest.mark.performance
def test_disk_backed_accumulator_bounds_peak_growth_and_matches_in_ram(tmp_path):
    """D-04c: disk-backed accumulation's PEAK ANONYMOUS allocation (Plan 01's own
    docstring term) must stay bounded by one chunk's size, not the whole stream's --
    that is the actual OOM fix (an mmap's touched pages are backed by a real file and
    reclaimable by the kernel under memory pressure; a Python list of chunks plus a
    final np.vstack copy are anonymous heap that cannot be reclaimed and is exactly
    what OOM-killed ic_engine at scale, todo 371).

    `resource.getrusage(...).ru_maxrss` (whole-process peak RESIDENT set, sampled
    before/after as a coarse diagnostic below) is NOT the right instrument to assert
    against here and would be flaky either way: it is a lifetime high-water mark that
    never decreases, and -- empirically confirmed while writing this test -- it counts
    a memmap's own touched-but-clean-and-evictable pages the same as true anonymous
    memory in an unstressed test process with no memory pressure to trigger eviction,
    so its delta tracks TOTAL bytes written regardless of accumulation strategy. The
    real, structural claim ("no Python/numpy-level buffer proportional to total size")
    is instead machine-checked via `tracemalloc`, which traces only Python/numpy heap
    allocations and correctly excludes the memmap's mmap()-backed data buffer.
    """
    rng = np.random.default_rng(11)
    n_chunks = 40
    chunk_rows = 200
    n_cols = 50
    chunks = [rng.standard_normal((chunk_rows, n_cols)).astype(np.float32) for _ in range(n_chunks)]
    total_rows = n_chunks * chunk_rows
    one_chunk_bytes = chunk_rows * n_cols * 4

    in_ram_acc = Float32ChunkAccumulator()
    for chunk in chunks:
        in_ram_acc.append_chunk(chunk)
    in_ram_result = in_ram_acc.finalize()

    # Coarse whole-process diagnostic (see docstring above for why this is not the
    # pass/fail signal) -- still sampled before/after so a future investigation has
    # the number on hand.
    before_maxrss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    disk_acc = Float32ChunkAccumulator(
        disk_backed=True,
        estimated_rows=total_rows,
        n_cols=n_cols,
        scratch_dir=str(tmp_path),
    )
    try:
        tracemalloc.start()
        try:
            for chunk in chunks:
                disk_acc.append_chunk(chunk)
            disk_result = disk_acc.finalize()
            _current_bytes, peak_traced_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        after_maxrss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        assert after_maxrss_kb >= before_maxrss_kb  # monotonic high-water mark, sanity only

        # Generous multiple (catches "peak grew with total accumulated size" without
        # being flaky about interpreter/allocator overhead) -- empirically, disk-backed
        # mode traces just over one chunk (~40KB here); in-RAM mode traces ~2x the
        # total stream (chunks list + vstacked result coexisting, ~3.2MB here).
        assert peak_traced_bytes < 10 * one_chunk_bytes, (
            f"disk-backed accumulation traced {peak_traced_bytes} bytes of Python/"
            f"numpy-level (anonymous) allocation, more than 10x a single chunk's "
            f"{one_chunk_bytes} bytes -- peak anonymous allocation must be bounded by "
            "chunk size, not total accumulated size"
        )
        np.testing.assert_array_equal(disk_result, in_ram_result)
    finally:
        disk_acc.close()
