"""The volume-basis guard's invariant (todo 560), as a property over random gaps and seams.

For every guarded kernel with finite memory M, an output row the guard leaves unmasked equals the
same kernel run on only its trailing M + 1 bars (volume NaN as 0.0): the guard changes which rows
exist, never what an existing row means. A row it masks is NaN (a none-mask row is 1).
"""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.features.contract.registry import (
    _compute_basis_guarded,
    _masked_until_reset,
    default_registry,
)
from tests.unit.intelligence import kernel_parity_reference as ref

_REGISTRY = default_registry()
_GUARDED = [
    k.name
    for k in _REGISTRY.kernels
    if "volume" in k.inputs and not k.nan_volume_safe and not k.path_dependent
]
# memory 479 against a 500-row fixture: every row is dirty or warmup, nothing finite to compare
_TOO_LONG_FOR_FIXTURE = {"rolling_poc"}


def _case(seed: int):
    inputs, config = ref.synthetic_inputs()
    n = len(inputs["ts"])
    rng = np.random.default_rng(seed)
    full = {
        **inputs,
        "symbol": np.array(["SPY"] * n, dtype=object),
        "tf": np.array(["5m"] * n, dtype=object),
    }
    volume = inputs["volume"].copy()
    basis = np.ones(n, dtype=np.int64)
    gaps = rng.choice(np.arange(5, n), size=6, replace=False)
    volume[gaps] = np.nan
    basis[gaps] = 0
    for seam in rng.choice(np.arange(30, n - 30), size=2, replace=False):
        basis[seam:] = 3 - basis[seam]  # flips 1 <-> 2 at the seam
        basis[gaps] = 0
    return full, config, volume, basis


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("name", _GUARDED)
def test_unmasked_rows_equal_the_kernel_on_their_trailing_window(name, seed):
    kernel = _REGISTRY.by_name(name)
    full, config, volume, basis = _case(seed)
    n = len(volume)
    cut = {k: full[k] for k in kernel.inputs if k in full}
    if "_atr_raw_padded" in kernel.inputs:
        pytest.skip("needs an upstream kernel output; covered by the end-to-end checks")
    cut["volume"] = volume
    got = _compute_basis_guarded(kernel, cut, basis, config)
    memory = int(kernel.memory(config))
    clean_volume = np.where(np.isfinite(volume), volume, 0.0)
    compared = 0
    for out_name, column in got.items():
        column = np.asarray(column, dtype=float)
        is_mask = out_name.startswith("_") and out_name.endswith("_is_none")
        for t in range(memory, n):
            span = slice(t - memory, t + 1)
            clean_window = bool(np.isfinite(volume[span]).all() and len(set(basis[span])) == 1)
            if not clean_window:
                # a dirty window is masked: NaN, or 1.0 for a none-mask row
                assert (column[t] == 1.0) if is_mask else np.isnan(column[t]), (out_name, t)
                continue
            if t % 5:
                continue  # the kernel re-run per row is the cost; every 5th clean row
            window = {
                k: (
                    (clean_volume if k == "volume" else v)[span]
                    if getattr(v, "ndim", 0) >= 1 and len(v) == n
                    else v
                )
                for k, v in cut.items()
            }
            want = np.asarray(kernel.compute(window, config)[out_name], dtype=float)[-1]
            assert column[t] == pytest.approx(want, rel=1e-6, abs=1e-8, nan_ok=True), (
                out_name,
                t,
            )
            compared += np.isfinite(want) and not is_mask
    if name not in _TOO_LONG_FOR_FIXTURE:
        assert compared, f"{name}: no clean finite row was compared, the test would pass vacuously"


def test_a_none_mask_column_is_never_nan_at_a_segment_start():
    kernel = _REGISTRY.by_name("swing_momentum")
    full, config, volume, _ = _case(0)
    n = len(volume)
    basis = np.ones(n, dtype=np.int64)
    basis[251] = 2
    cut = {k: full[k] for k in kernel.inputs if k in full}
    if "_atr_raw_padded" in kernel.inputs:
        pytest.skip("needs an upstream kernel output; covered by the end-to-end checks")
    cut["volume"] = volume
    got = _compute_basis_guarded(kernel, cut, basis, config)
    for out_name, column in got.items():
        if out_name.startswith("_") and out_name.endswith("_is_none"):
            assert not np.isnan(np.asarray(column, dtype=float)).any(), out_name


@pytest.mark.parametrize("name", ["vwap_dev_sigma", "ctf_source"])
def test_a_path_dependent_kernel_runs_through_a_seam_and_masks_only_dropped_bars(name):
    kernel = _REGISTRY.by_name(name)
    full, config, volume, basis = _case(0)
    cut = {k: full[k] for k in kernel.inputs if k in full}
    cut["volume"] = volume
    got = _compute_basis_guarded(kernel, cut, basis, config)
    dropped = ~np.isfinite(volume)
    whole = kernel.compute({**cut, "volume": np.where(dropped, 0.0, volume)}, config)
    for out_name, column in got.items():
        column = np.asarray(column, dtype=float)
        is_mask = out_name.startswith("_") and out_name.endswith("_is_none")
        assert (column[dropped] == 1.0).all() if is_mask else np.isnan(column[dropped]).all()
        np.testing.assert_array_equal(
            column[~dropped], np.asarray(whole[out_name], dtype=float)[~dropped]
        )


def _bars_ts(n: int) -> np.ndarray:
    """n 15m RTH-ish bars from Monday 2023-01-02 14:30 UTC, 26 bars a day, weekdays only."""
    from datetime import UTC, datetime, timedelta

    out, day = [], datetime(2023, 1, 2, 14, 30, tzinfo=UTC)
    while len(out) < n:
        if day.weekday() < 5:
            out.extend(day + timedelta(minutes=15 * k) for k in range(26))
        day += timedelta(days=1)
    return np.array(out[:n], dtype=object)


@pytest.mark.parametrize(
    ("anchor", "bars_to_reset"), [("week", 5 * 26 - 30 + 1), ("session", 26 - 30 % 26)]
)
def test_masked_until_reset_covers_the_dropped_bar_to_the_next_anchor(anchor, bars_to_reset):
    from dataclasses import replace

    kernel = replace(_REGISTRY.by_name("vwap_dev_sigma"), volume_reset=anchor)
    ts = _bars_ts(400)
    dropped = np.zeros(400, dtype=bool)
    dropped[30] = True
    masked = _masked_until_reset(kernel, {"ts_dt": ts}, dropped)
    assert not masked[:30].any()
    assert masked[30 : 30 + bars_to_reset].all()
    assert not masked[30 + bars_to_reset :].any()


def test_no_reset_anchor_masks_only_the_dropped_row():
    kernel = _REGISTRY.by_name("vwap_dev_sigma")
    dropped = np.zeros(50, dtype=bool)
    dropped[7] = True
    assert (_masked_until_reset(kernel, {}, dropped) == dropped).all()


def test_weekly_vwap_flag_recovers_exactly_after_the_week_with_a_dropped_bar():
    kernel = _REGISTRY.by_name("calendar_above_wk_vwap")
    full, config, volume, _ = _case(0)
    n = len(volume)
    ts = _bars_ts(n)
    volume = full["volume"].astype(float).copy()
    cut = {**{k: full[k] for k in kernel.inputs if k in full}, "ts_dt": ts, "volume": volume.copy()}
    truth = kernel.compute(dict(cut), config)["above_wk_vwap"]
    cut["volume"][40] = np.nan
    got = _compute_basis_guarded(kernel, cut, np.ones(n, dtype=np.int64), config)["above_wk_vwap"]
    week_end = 5 * 26  # bars 0..129 are week 1
    # the flag at row i reads bars < i, so the first row of the next week is still corrupted
    assert np.isnan(got[40 : week_end + 1]).all()
    assert not np.isnan(got[:40]).any() and not np.isnan(got[week_end + 1 :]).any()
    np.testing.assert_array_equal(got[week_end + 1 :], truth[week_end + 1 :])
    np.testing.assert_array_equal(got[:40], truth[:40])


def test_session_levels_ignores_nan_volume_so_it_is_declared_nan_volume_safe():
    kernel = _REGISTRY.by_name("session_levels")
    assert kernel.nan_volume_safe
    full, config, volume, _ = _case(0)
    n = len(volume)
    x = {**full, "tf": np.array(["15m"] * n, dtype=object), "ts_dt": _bars_ts(n)}
    x["_atr_raw_padded"] = np.full(n, 1.5)
    cut = {k: x[k] for k in kernel.inputs}
    want = kernel.compute(dict(cut), config)
    got = kernel.compute({**cut, "volume": volume}, config)  # `_case` volume holds NaN bars
    assert np.isnan(volume).any()
    for out_name, column in want.items():
        np.testing.assert_array_equal(
            np.asarray(got[out_name], dtype=float), np.asarray(column, dtype=float)
        )
