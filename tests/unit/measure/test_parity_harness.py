"""Synthetic tests of the 186-20 parity replay core (stride order, mask order, attribution)."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest
from scipy.stats import rankdata

from src.intelligence.measure.ic import SlotMap
from tests.unit.measure.parity_replay import (
    ObservationRows,
    classify_target_diffs,
    compare_point_ic,
    float32_pipeline_tolerance,
    legacy_arithmetic_ic,
    rebuild_observation_set,
    replay_kernel_targets,
    replay_table_targets,
)


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    rx, ry = rankdata(x), rankdata(y)
    rx, ry = rx - rx.mean(), ry - ry.mean()
    return float((rx * ry).sum() / np.sqrt((rx**2).sum() * (ry**2).sum()))


def _chunk(bar_ts, symbols, x, returns=None, complete=None, gap=None) -> ObservationRows:
    r = len(bar_ts)
    return ObservationRows(
        bar_ts=np.asarray(bar_ts, dtype="datetime64[ns]"),
        symbols=np.asarray(symbols),
        X=np.asarray(x, dtype=float).reshape(r, -1),
        returns=np.zeros((r, 1)) if returns is None else np.asarray(returns, float).reshape(r, -1),
        complete=np.ones((r, 1), dtype=bool) if complete is None else complete,
        has_gap=np.zeros(r, dtype=bool) if gap is None else gap,
    )


def test_rebuild_orders_label_bars_by_peer_symbols_and_keeps_missing_rows_missing():
    days = np.arange("2026-01-05", "2026-01-12", dtype="datetime64[D]").astype("datetime64[ns]")
    label_bars = [days[0], days[2], days[3], days[5]]
    peers = ["B", "A", "C"]
    calls = []

    def fetch(ts_chunk, symbols):
        calls.append((list(ts_chunk), sorted(symbols)))
        rows = [
            (t, s) for t in ts_chunk for s in sorted(symbols) if not (t == days[2] and s == "B")
        ]
        return _chunk([t for t, _ in rows], [s for _, s in rows], np.arange(len(rows)))

    obs = rebuild_observation_set(label_bars, peers, fetch, chunk_ts=2)
    assert len(calls) == 2 and calls[0][0] == label_bars[:2]  # chunked over label bars in order
    assert len(obs.bar_ts) == 4 * 3 - 1  # cross product minus the one missing (bar, symbol)
    order = list(zip(obs.bar_ts.tolist(), obs.symbols.tolist(), strict=True))
    assert order == sorted(order)
    assert ("B" not in obs.symbols[obs.bar_ts == days[2]]) and set(obs.symbols) == {"A", "B", "C"}


def test_rebuild_refuses_a_row_outside_the_label_bars_or_peers():
    day = np.datetime64("2026-01-05", "ns")
    other = np.datetime64("2026-01-06", "ns")
    with pytest.raises(ValueError, match="label bar"):
        rebuild_observation_set(
            [day], ["A"], lambda t, s: _chunk([other], ["A"], [1.0]), chunk_ts=5
        )
    with pytest.raises(ValueError, match="peer"):
        rebuild_observation_set([day], ["A"], lambda t, s: _chunk([day], ["Z"], [1.0]), chunk_ts=5)


def test_table_replay_matches_hand_rankdata_with_stride_over_flattened_order(params):
    rng = np.random.default_rng(11)
    n_bars, m = 40, 3
    bar_ts = np.repeat(np.arange(n_bars), m).astype("datetime64[D]").astype("datetime64[ns]")
    symbols = np.tile(np.array(["A", "B", "C"]), n_bars)
    x = rng.normal(size=n_bars * m)
    y = 0.4 * x + rng.normal(size=n_bars * m)
    obs = rebuild_observation_set(
        list(np.unique(bar_ts)),
        ["A", "B", "C"],
        lambda ts, sy: _chunk(bar_ts, symbols, x, returns=y),
        chunk_ts=n_bars,
    )
    p = dataclasses.replace(params, min_stride=5, min_obs=10)
    cell = replay_table_targets(obs, scale_idx=0, horizon=2, params=p)  # stride max(5, 2) = 5
    rows = np.arange(0, n_bars * m, 5)  # the flattened (bar_ts, symbol) order, not per bar
    assert cell.stride == 5 and cell.n_independent.tolist() == [len(rows)]
    assert cell.ic[0] == pytest.approx(_spearman(x[rows], y[rows]), abs=1e-12)
    wide = replay_table_targets(obs, scale_idx=0, horizon=9, params=p)  # stride max(5, 9) = 9
    assert wide.stride == 9


def test_stride_slice_precedes_the_target_mask(params):
    rng = np.random.default_rng(12)
    r = 90
    bar_ts = np.arange(r).astype("datetime64[D]").astype("datetime64[ns]")
    x = rng.normal(size=r)
    y = rng.normal(size=r)
    complete = np.ones((r, 1), dtype=bool)
    complete[[3, 10, 11, 40]] = False
    y[[7, 25]] = np.nan
    obs = rebuild_observation_set(
        list(bar_ts),
        ["A"],
        lambda ts, sy: _chunk(bar_ts, ["A"] * r, x, returns=y, complete=complete),
        chunk_ts=r,
    )
    p = dataclasses.replace(params, min_stride=3, min_obs=5)
    cell = replay_table_targets(obs, scale_idx=0, horizon=1, params=p)
    valid = complete[:, 0] & np.isfinite(y)
    strided = np.arange(0, r, 3)
    expected_rows = strided[valid[strided]]  # stride first, then mask
    mask_first = np.flatnonzero(valid)[::3]  # mask first would pick other rows
    assert not np.array_equal(expected_rows, mask_first)
    assert cell.n_independent.tolist() == [len(expected_rows)]
    assert cell.ic[0] == pytest.approx(_spearman(x[expected_rows], y[expected_rows]), abs=1e-12)


def test_kernel_replay_strides_over_existing_rows_not_traded_bars(params):
    rng = np.random.default_rng(13)
    n, m, k = 50, 3, 1
    feats = rng.normal(size=(n, m, k))
    targets = 0.5 * feats[:, :, 0] + rng.normal(size=(n, m))
    valid_grid = np.ones((n, m), dtype=bool)
    present = np.ones((n, m), dtype=bool)
    present[2, 1] = False  # a traded bar with no feature_vectors row for symbol 1
    present[7, 0] = False
    feats = np.where(present[:, :, None], feats, np.nan)
    p = dataclasses.replace(params, min_stride=4, min_obs=10)
    kernel = replay_kernel_targets(
        feats, targets, valid_grid, present, horizon=2, params=p, feature_names=("f",)
    )
    # The table replay's rows: only the (bar, symbol) pairs that exist, in (bar_ts, symbol) order.
    bar_ts = np.repeat(np.arange(n), m).astype("datetime64[D]").astype("datetime64[ns]")
    sym = np.tile(np.array(["A", "B", "C"]), n)
    keep = present.reshape(-1)
    obs = rebuild_observation_set(
        list(np.unique(bar_ts)),
        ["A", "B", "C"],
        lambda ts, sy: _chunk(
            bar_ts[keep],
            sym[keep],
            feats[:, :, 0].reshape(-1)[keep],
            returns=targets.reshape(-1)[keep],
        ),
        chunk_ts=n,
    )
    table = replay_table_targets(obs, scale_idx=0, horizon=2, params=p)
    assert kernel.n_independent.tolist() == table.n_independent.tolist()
    assert kernel.ic[0] == pytest.approx(table.ic[0], abs=1e-12)
    # A selection by traded bar alone counts the empty slots in the stride and picks other rows.
    bar_level = replay_kernel_targets(
        feats,
        targets,
        valid_grid,
        np.ones((n, m), dtype=bool),
        horizon=2,
        params=p,
        feature_names=("f",),
    )
    assert bar_level.n_independent.tolist() != table.n_independent.tolist() or bar_level.ic[
        0
    ] != pytest.approx(table.ic[0], abs=1e-12)


def test_replay_core_takes_present_with_no_default():
    import inspect

    sig = inspect.signature(replay_kernel_targets)
    assert sig.parameters["present"].default is inspect.Parameter.empty


def test_classify_target_diffs_counts_each_cause_with_examples():
    nan = np.nan
    table_y = np.array([1.0, 2.0, 3.0, 4.0, 5.0, nan, 7.0, 8.0])
    table_complete = np.array([True, True, True, True, True, False, True, True])
    kernel_y = np.array([1.0, 2.0, nan, nan, 5.5, 6.0, 7.0, nan])
    has_gap = np.array([False, False, False, True, False, False, False, False])
    in_grid = np.array([True, True, True, True, True, True, True, False])
    grid_row = np.array([0, 1, 18, 5, 6, 7, 8, 9])  # row 2 sits in the last 1 + horizon rows
    counts = classify_target_diffs(
        table_y,
        table_complete,
        kernel_y,
        has_gap=has_gap,
        in_grid=in_grid,
        grid_row=grid_row,
        n_grid=20,
        horizon=1,
        atol=1e-12,
    )
    assert counts.n_equal == 3  # rows 0, 1, 6
    assert counts.n_end_of_window == 1  # row 2: kernel NaN at row 18 >= 20 - 1 - 1
    assert counts.n_gap == 2  # row 3 flagged has_gap_before_entry, row 7 absent from the grid
    assert counts.n_other == 2  # row 4 finite but different, row 5 kernel finite where table NaN
    assert counts.n_equal + counts.n_end_of_window + counts.n_gap + counts.n_other == len(table_y)
    assert len(counts.examples["other"]) == 2 and len(counts.examples["gap"]) == 2


def test_classify_examples_are_capped_at_five():
    r = 12
    counts = classify_target_diffs(
        np.ones(r),
        np.ones(r, dtype=bool),
        np.full(r, 2.0),
        has_gap=np.zeros(r, dtype=bool),
        in_grid=np.ones(r, dtype=bool),
        grid_row=np.arange(r),
        n_grid=100,
        horizon=1,
    )
    assert counts.n_other == r and len(counts.examples["other"]) == 5


def test_compare_point_ic_nan_tolerance_and_float32_bound():
    assert compare_point_ic(float("nan"), None).match
    assert compare_point_ic(0.25, 0.25 + 9e-10).match
    miss = compare_point_ic(0.25, 0.25 + 2e-9)
    assert not miss.match and miss.delta == pytest.approx(-2e-9, abs=1e-12)
    assert not compare_point_ic(0.1, None).match and not compare_point_ic(float("nan"), 0.1).match
    # The stored cells are float32 results; a replay is held to the float32 pipeline's error bound.
    bound = float32_pipeline_tolerance(6168)
    assert 1e-7 < bound < 1e-5
    assert compare_point_ic(0.25, 0.25 + bound / 2, tol=bound).match
    assert not compare_point_ic(0.25, 0.25 + 2 * bound, tol=bound).match
    assert float32_pipeline_tolerance(10**6) > float32_pipeline_tolerance(100)


def test_slotmap_present_is_what_the_kernel_replay_consumes():
    slots = SlotMap(ok=np.array([True, True, False]), rows=np.array([0, 1]), cols=np.array([0, 1]))
    present = slots.present(2, 2)
    assert present.tolist() == [[True, False], [False, True]]


def test_legacy_arithmetic_ranks_before_the_mask_and_stores_zero_for_a_missing_column(params):
    rng = np.random.default_rng(14)
    r = 400
    bar_ts = np.arange(r).astype("datetime64[D]").astype("datetime64[ns]")
    x = np.column_stack([rng.normal(size=r), np.full(r, np.nan), np.full(r, 3.0)])
    y = 0.3 * x[:, 0] + rng.normal(size=r)
    complete = np.ones((r, 1), dtype=bool)
    complete[rng.choice(r, 40, replace=False)] = False
    obs = rebuild_observation_set(
        list(bar_ts),
        ["A"],
        lambda ts, sy: _chunk(bar_ts, ["A"] * r, x, returns=y, complete=complete),
        chunk_ts=r,
    )
    p = dataclasses.replace(params, min_stride=1, min_obs=10)
    legacy = legacy_arithmetic_ic(obs, scale_idx=0, horizon=1, params=p)
    assert legacy[1] == 0.0  # all-missing column: denominator NaN, `_vectorized_ic` returns 0.0
    assert np.isnan(legacy[2])  # constant column: degenerate
    valid = complete[:, 0]
    rx = rankdata(x[:, 0].astype(np.float32))[valid]  # ranks over every strided row, then masked
    ry = rankdata(y[valid])
    rx, ry = rx - rx.mean(), ry - ry.mean()
    expected = (rx * ry).sum() / np.sqrt((rx**2).sum() * (ry**2).sum())
    assert legacy[0] == pytest.approx(expected, abs=1e-5)
    fresh = replay_table_targets(obs, scale_idx=0, horizon=1, params=p)
    assert np.isnan(fresh.ic[1]) and np.isnan(fresh.ic[2])
    assert abs(fresh.ic[0] - legacy[0]) > 1e-7  # the rank scope differs when targets are masked


def test_classify_attributes_a_refused_session_crossing_before_gap_and_other():
    nan = np.nan
    counts = classify_target_diffs(
        np.array([1.0, 2.0, 3.0, 4.0]),
        np.ones(4, dtype=bool),
        np.array([1.0, nan, nan, nan]),
        has_gap=np.array([False, False, True, False]),
        in_grid=np.ones(4, dtype=bool),
        grid_row=np.arange(4),
        n_grid=50,
        horizon=1,
        session_cross=np.array([False, True, True, False]),
    )
    assert (counts.n_equal, counts.n_session_cross, counts.n_gap, counts.n_other) == (1, 2, 0, 1)
    plain = classify_target_diffs(
        np.array([1.0, 2.0]),
        np.ones(2, dtype=bool),
        np.array([1.0, nan]),
        has_gap=np.zeros(2, dtype=bool),
        in_grid=np.ones(2, dtype=bool),
        grid_row=np.arange(2),
        n_grid=50,
        horizon=1,
    )
    assert plain.n_session_cross == 0 and plain.n_other == 1


def test_classify_attributes_an_absent_tradeable_open_before_gap_and_other():
    nan = np.nan
    counts = classify_target_diffs(
        np.array([1.0, 2.0, 3.0]),
        np.ones(3, dtype=bool),
        np.array([1.0, nan, nan]),
        has_gap=np.zeros(3, dtype=bool),
        in_grid=np.ones(3, dtype=bool),
        grid_row=np.arange(3),
        n_grid=50,
        horizon=1,
        open_missing=np.array([False, True, False]),
    )
    assert (counts.n_equal, counts.n_open_missing, counts.n_other) == (1, 1, 1)
