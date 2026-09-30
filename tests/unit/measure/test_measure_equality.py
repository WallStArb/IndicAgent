"""The block-wise measure implementations equal the straightforward ones they replaced, bit for
bit: each reference below is the earlier code kept as a slow oracle."""

from __future__ import annotations

import dataclasses
import warnings

import numpy as np
import pytest

from src.intelligence.measure import ic as ic_module
from src.intelligence.measure.ic import (
    align_features,
    map_slots,
    observation_rows,
    pooled_rank_ic,
    scatter_features,
)
from src.intelligence.measure.monitoring import member_ic_over_time
from src.intelligence.measure.proposer import propose
from src.intelligence.measure.regime_disclosure import regime_volatility_disclosure
from src.intelligence.measure.targets import stack_targets, stride
from src.intelligence.measure.term_structure import term_structure
from src.intelligence.statistics.ic_math import (
    _circular_block_bootstrap_ic,
    _p_values_from_ic,
    compute_ic_vectorized,
)
from tests.unit.measure.conftest import make_panel

# ---------------------------------------------------------------- pooled_rank_ic


def _reference_pooled(X, y, stride_, params, names=None):
    k = X.shape[1]
    with np.errstate(invalid="ignore"):
        std = np.nanstd(X, axis=0, dtype=np.float64) if X.shape[0] else np.full(k, np.nan)
    live = std >= params.degenerate_std
    ic = np.full(k, np.nan)
    p_value = np.full(k, np.nan)
    lower, upper = np.full(k, np.nan), np.full(k, np.nan)
    n_obs, n_ind = np.zeros(k, dtype=np.int64), np.zeros(k, dtype=np.int64)
    reliable = np.zeros(k, dtype=bool)

    def complete(x, target):
        return np.isfinite(target) & np.isfinite(x[:, live]).all(axis=1)

    if live.any():
        n_full = int(complete(X, y).sum())
        Xs, ys = X[0::stride_], y[0::stride_]
        valid = complete(Xs, ys)
        n_valid = int(valid.sum())
        n_obs[live], n_ind[live] = n_full, n_valid
        if n_valid >= params.min_obs and n_valid > 2:
            Xv, yv = Xs[valid][:, live], ys[valid]
            ic_live = compute_ic_vectorized(Xv, yv)
            lo, hi = _circular_block_bootstrap_ic(
                Xv,
                yv,
                params.bootstrap_block_size,
                params.bootstrap_resamples,
                np.random.default_rng(params.rng_seed),
            )
            ic[live], p_value[live] = ic_live, _p_values_from_ic(ic_live, n_valid)
            lower[live], upper[live] = lo, hi
            reliable[live] = np.isfinite(ic_live)
    return ic, n_obs, n_ind, p_value, lower, upper, reliable, int((~live).sum())


def _matrix(seed, n, k, order="C", dtype=np.float64):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, k)) * rng.uniform(0.5, 50.0, k)
    if n > 10 and k > 1:
        X[:, 1] = np.round(X[:, 1], 1)  # ties
        X[rng.choice(n, n // 8, replace=False), k - 1] = np.nan
        X[rng.choice(n, 2, replace=False), 0] = np.inf
    if n > 10 and k > 4:
        X[:, 3], X[:, 4] = 5.0, np.nan  # degenerate and all missing
    y = 0.2 * X[:, 0] + rng.normal(size=n)
    if n > 10:
        y[rng.choice(n, n // 10, replace=False)] = np.nan
    return np.array(X, dtype=dtype, order=order), y


@pytest.mark.parametrize("order", ["C", "F"])
@pytest.mark.parametrize("dtype", [np.float64, np.float32])
@pytest.mark.parametrize("k", [1, 2, 3, 5, 11, 40])
@pytest.mark.parametrize("stride_", [1, 4])
def test_pooled_rank_ic_bit_identical(params, order, dtype, k, stride_):
    for n in (0, 4, 90, 700):
        X, y = _matrix(k * 100 + n, n, k, order, dtype)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            want = _reference_pooled(X, y, stride_, params)
            cell = pooled_rank_ic(X, y, stride=stride_, params=params)
        got = (
            cell.ic,
            cell.n_obs,
            cell.n_independent,
            cell.p_value,
            cell.ci_lower,
            cell.ci_upper,
            cell.reliable,
            cell.n_degenerate,
        )
        for g, w in zip(got, want, strict=True):
            assert np.asarray(g).tobytes() == np.asarray(w).tobytes(), (order, dtype, k, n)


def test_column_blocks_partition_without_single_columns():
    for k in range(1, 300):
        blocks = list(ic_module._column_blocks(k))
        assert blocks[0][0] == 0 and blocks[-1][1] == k
        assert all(a[1] == b[0] for a, b in zip(blocks, blocks[1:], strict=False))
        assert k == 1 or all(stop - first >= 2 for first, stop in blocks)


def test_blockwise_nanstd_equals_whole_matrix_nanstd():
    for n, k in ((5, 3), (1000, 64), (30000, 9), (7, 200)):
        X, _ = _matrix(n + k, n, k)
        whole = np.nanstd(X, axis=0, dtype=np.float64)
        blocked = np.empty(k)
        for first, stop in ic_module._column_blocks(k):
            blocked[first:stop] = np.nanstd(X[:, first:stop], axis=0, dtype=np.float64)
        assert whole.tobytes() == blocked.tobytes(), (n, k)


# ---------------------------------------------------------------- term structure


def _panels(symbols, tag):
    if tag == "daily":
        return [
            make_panel(symbols[:5], 80, 1, seed=1, nan_open_rows=(7, 30)),
            make_panel(symbols[5:], 80, 1, seed=2),
        ], (1, 2, 5)
    return [
        make_panel(symbols[:6], 12, 26, seed=3, nan_open_rows=(77,)),
        make_panel(symbols[6:], 12, 26, seed=4),
    ], (1, 3, 8)


@pytest.mark.parametrize("tag", ["daily", "intraday"])
@pytest.mark.parametrize("min_stride", [1, 3])
def test_term_structure_equals_per_horizon_proposer(symbols, params, tag, min_stride):
    panels, horizons = _panels(symbols, tag)
    prm = dataclasses.replace(params, min_stride=min_stride, min_obs=10)
    end = "2027-01-01"
    n, m = stack_targets(panels, horizons[0], end).targets.shape
    rng = np.random.default_rng(9)
    feats = rng.normal(size=(n, m, 5))
    feats[rng.random((n, m, 5)) < 0.07] = np.nan
    feats[:, :, 3] = 1.0
    names = tuple(f"f{i}" for i in range(5))
    present = rng.random((n, m)) > 0.1  # some (bar, symbol) rows do not exist
    got = term_structure(feats, names, panels, horizons, end, prm, present=present)
    for h_idx, horizon in enumerate(horizons):
        cell = propose(feats, names, stack_targets(panels, horizon, end), prm, present=present).cell
        assert got.ic[:, h_idx].tobytes() == cell.ic.tobytes()
        assert got.n_obs[:, h_idx].tobytes() == cell.n_independent.tobytes()
        assert got.p_value[:, h_idx].tobytes() == cell.p_value.tobytes()


# ---------------------------------------------------------------- align_features


def _reference_align(stack, bar_ts, symbols, values):
    values = np.asarray(values, dtype=float)
    if values.ndim == 1:
        values = values[:, None]
    grid = np.full((len(stack.timestamps), len(stack.symbols), values.shape[1]), np.nan)
    if len(values) == 0:
        return grid, 0
    stamps = np.asarray(stack.timestamps).astype("datetime64[ns]")
    ts = np.asarray(bar_ts).astype("datetime64[ns]")
    pos = np.clip(np.searchsorted(stamps, ts), 0, len(stamps) - 1)
    ts_ok = stamps[pos] == ts
    col_of = {s: j for j, s in enumerate(stack.symbols)}
    col = np.fromiter((col_of.get(str(s), -1) for s in symbols), dtype=np.int64, count=len(symbols))
    ok = ts_ok & (col >= 0)
    rows, cols = pos[ok], col[ok]
    flat = rows.astype(np.int64) * len(stack.symbols) + cols
    if len(np.unique(flat)) != len(flat):
        raise ValueError("duplicate (timestamp, symbol) rows in the feature input")
    grid[rows, cols] = values[ok]
    return grid, int((~ok).sum())


@pytest.mark.parametrize("tag", ["daily", "intraday"])
def test_align_features_equals_per_row_lookup(symbols, tag):
    panels, horizons = _panels(symbols, tag)
    stack = stack_targets(panels, horizons[0], "2027-01-01")
    n, m = stack.targets.shape
    rng = np.random.default_rng(4)
    flat = np.unique(rng.integers(0, n * m, 500))
    rows, cols = flat // m, flat % m
    bar_ts = np.asarray(stack.timestamps)[rows].copy()
    sym_obj = np.array([stack.symbols[c] for c in cols], dtype=object)
    values = rng.normal(size=(len(rows), 3))
    unknown_sym, unknown_ts = sym_obj.copy(), bar_ts.copy()
    unknown_sym[::9] = "ZZZ"
    unknown_ts[::11] = np.datetime64("1999-01-01")
    cases = [
        (bar_ts, sym_obj, values),
        (bar_ts, sym_obj.astype(str), values[:, 0]),
        (unknown_ts, unknown_sym, values),
        (bar_ts[:0], sym_obj[:0], values[:0]),
    ]
    for ts, sy, vals in cases:
        want_grid, want_missing = _reference_align(stack, ts, sy, vals)
        got_grid, got_missing = align_features(stack, ts, sy, vals)
        assert got_grid.tobytes() == want_grid.tobytes() and got_missing == want_missing
        slots = map_slots(stack, ts, sy)  # one mapping, reused for another block of values
        again, _ = scatter_features(stack, slots, np.asarray(vals, dtype=float) * 2.0)
        assert (
            again.tobytes() == _reference_align(stack, ts, sy, np.asarray(vals) * 2.0)[0].tobytes()
        )
    dup_ts, dup_sym = np.concatenate([bar_ts, bar_ts[:3]]), np.concatenate([sym_obj, sym_obj[:3]])
    for fn in (_reference_align, align_features):
        with pytest.raises(ValueError, match="duplicate"):
            fn(stack, dup_ts, dup_sym, np.concatenate([values, values[:3]]))


# ---------------------------------------------------------------- regime disclosure


def _reference_labelled(labels):
    if labels.dtype.kind in "fc":
        return ~np.isnan(labels)
    if labels.dtype.kind in "iub":
        return np.ones(labels.shape, dtype=bool)
    return np.array(
        [
            [not (v is None or v == "" or (isinstance(v, float) and v != v)) for v in row]
            for row in labels
        ],
        dtype=bool,
    ).reshape(labels.shape)


def _reference_disclosure(features, names, stack, labels, params, exists):
    valid = stack.valid_grid() & exists
    labelled = _reference_labelled(labels)
    n_unlabelled = int((valid & ~labelled).sum())
    cells = {}
    seen = np.unique(labels[valid & labelled].astype(str))
    as_text = labels.astype(str)
    for label in seen:
        mask = valid & labelled & (as_text == label)
        X, y = observation_rows(features, stack.targets, mask)
        cells[str(label)] = pooled_rank_ic(
            X, y, stride=stride(stack, params), params=params, feature_names=names
        )
    return cells, n_unlabelled


@pytest.mark.parametrize(
    "kind", ["int", "float", "object", "unicode", "numeric_strings", "signed_zero"]
)
def test_regime_disclosure_equals_string_mask_loop(symbols, params, kind):
    panels, horizons = _panels(symbols, "daily")
    stack = stack_targets(panels, horizons[0], "2027-01-01")
    n, m = stack.targets.shape
    rng = np.random.default_rng(6)
    feats = rng.normal(size=(n, m, 3))
    base = rng.integers(0, 12, size=(n, m))
    if kind == "int":
        labels = base
    elif kind == "float":
        labels = base.astype(float)
        labels[rng.random((n, m)) < 0.1] = np.nan
    elif kind == "signed_zero":
        labels = np.where(base % 2 == 0, 0.0, -0.0)
        labels[rng.random((n, m)) < 0.2] = 1.5
    elif kind == "numeric_strings":
        labels = base.astype(str).astype(object)  # '10' sorts before '2'
    else:
        labels = np.array([["lo", "mid", "hi"][v % 3] for v in base.ravel()], dtype=object).reshape(
            n, m
        )
        labels[rng.random((n, m)) < 0.1] = None
        labels[rng.random((n, m)) < 0.05] = ""
        labels[rng.random((n, m)) < 0.05] = float("nan")
        if kind == "unicode":
            labels = np.where(labels == None, "", labels).astype(str)  # noqa: E711
    names = ("a", "b", "c")
    exists = rng.random((n, m)) > 0.1  # some (bar, symbol) rows do not exist
    want_cells, want_missing = _reference_disclosure(feats, names, stack, labels, params, exists)
    got_cells, got_missing = regime_volatility_disclosure(
        feats, names, stack, labels, params, present=exists
    )
    assert got_missing == want_missing and list(got_cells) == list(want_cells)
    for label, want in want_cells.items():
        for field in ("ic", "n_obs", "n_independent", "p_value", "ci_lower", "ci_upper"):
            assert getattr(got_cells[label], field).tobytes() == getattr(want, field).tobytes()


# ---------------------------------------------------------------- monitoring


def _reference_member_ic(feature, stack, params, exists):
    n = len(stack.timestamps)
    per_window = params.monitor_window_sessions
    n_sessions = int(stack.session[-1]) + 1 if n else 0
    valid_grid = stack.valid_grid() & exists
    out = []
    for first in range(0, n_sessions, per_window):
        last = min(first + per_window, n_sessions)
        rows = np.flatnonzero((stack.session >= first) & (stack.session < last))
        X, y = observation_rows(feature[rows][:, :, None], stack.targets[rows], valid_grid[rows])
        cell = pooled_rank_ic(X, y, stride=stride(stack, params), params=params)
        out.append((stack.timestamps[rows[0]], last - first, cell.ic[0], cell.n_independent[0]))
    return out


@pytest.mark.parametrize("tag", ["daily", "intraday"])
@pytest.mark.parametrize("window", [1, 3, 7, 10, 500])
def test_member_windows_equal_row_scan(symbols, params, tag, window):
    panels, horizons = _panels(symbols, tag)
    stack = stack_targets(panels, horizons[0], "2027-01-01")
    n, m = stack.targets.shape
    feature = np.random.default_rng(8).normal(size=(n, m))
    feature[np.random.default_rng(9).random((n, m)) < 0.05] = np.nan
    prm = dataclasses.replace(params, monitor_window_sessions=window, min_obs=5)
    exists = np.random.default_rng(10).random((n, m)) > 0.1  # some (bar, symbol) rows do not exist
    series = member_ic_over_time(feature, "m", stack, prm, present=exists)
    want = _reference_member_ic(feature, stack, prm, exists)
    assert [w[0] for w in want] == series.window_start.tolist()
    assert [w[1] for w in want] == series.n_sessions.tolist()
    assert np.array([w[2] for w in want]).tobytes() == series.ic.tobytes()
    assert [int(w[3]) for w in want] == series.n_obs.tolist()


def test_monitor_degenerate_std_is_a_separate_validated_param(params):
    assert params.monitor_degenerate_std == 1e-10 and params.degenerate_std == 1e-8
    with pytest.raises(ValueError, match="monitor_degenerate_std"):
        dataclasses.replace(params, monitor_degenerate_std=0.0)
