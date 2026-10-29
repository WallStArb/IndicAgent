"""amihud_illiq_z after todo 555: ln(illiq) z-score, volume-basis segments, NaN volume."""

from __future__ import annotations

import math

import numpy as np
import pytest

from src.intelligence.bars.vendor_kind import (
    VOLUME_BASIS_CONSOLIDATED as CONSOLIDATED,
)
from src.intelligence.bars.vendor_kind import (
    VOLUME_BASIS_NONE as NONE,
)
from src.intelligence.bars.vendor_kind import (
    VOLUME_BASIS_SMART as SMART,
)
from src.intelligence.features.contract.registry import compute_kernels, default_registry
from src.intelligence.features.kernels.volume import (
    _amihud_illiq_z_series_full,
    volume_basis_segment_starts,
)
from tests.unit.intelligence import kernel_parity_reference as ref


def _series(n: int, seed: int = 3, price: float = 100.0, volume: float = 1e6):
    rng = np.random.default_rng(seed)
    closes = price * np.cumprod(1.0 + rng.normal(0, 0.01, n))
    volumes = volume * rng.uniform(0.5, 1.5, n)
    return closes, volumes


def _z(closes, volumes, basis=None, window=20, fraction=0.8):
    basis = np.full(len(closes), CONSOLIDATED) if basis is None else np.asarray(basis)
    return _amihud_illiq_z_series_full(closes, volumes, basis, window, fraction)


def _reference(closes, volumes, window):
    """A per-row loop: z of ln(|ln(C[i]/C[i-1])| / (C[i] V[i])) over the last `window` bars."""
    obs = np.full(len(closes), np.nan)
    obs[1:] = np.log(np.abs(np.log(closes[1:] / closes[:-1])) / (closes[1:] * volumes[1:]))
    out = np.full(len(closes), np.nan)
    for i in range(window - 1, len(closes)):
        w = obs[i - window + 1 : i + 1]
        if np.isnan(w).any():
            continue
        out[i] = (obs[i] - w.mean()) / w.std()
    return out


def test_liquid_name_z_is_not_dead():
    # Raw illiq is about 1e-10 here, far below the old absolute std floor: the old z was 0.
    closes, volumes = _series(400)
    out = _z(closes, volumes, window=252)
    live = out[~np.isnan(out)]
    assert live.size > 100
    assert (live != 0.0).mean() > 0.99
    assert abs(live.mean()) < 0.2 and 0.5 < live.std() < 1.5


def test_matches_a_direct_loop_when_every_observation_is_valid():
    closes, volumes = _series(120)
    np.testing.assert_allclose(
        _z(closes, volumes, fraction=1.0), _reference(closes, volumes, 20), rtol=1e-9, atol=1e-9
    )


def test_one_null_volume_session_does_not_blank_the_following_rows():
    closes, volumes = _series(400)
    volumes = volumes.copy()
    volumes[200] = np.nan
    out = _z(closes, volumes, window=100, fraction=0.8)
    assert np.isnan(out[200])
    assert np.isfinite(out[201:]).all()
    strict = _z(closes, volumes, window=100, fraction=1.0)
    assert np.isnan(strict[200:300]).all()


def test_rows_below_the_minimum_valid_count_are_nan():
    closes, volumes = _series(60)
    out = _z(closes, volumes, window=20, fraction=0.8)
    assert np.isnan(out[:16]).all()  # 16 observations needed: first at row 16
    assert np.isfinite(out[16:]).all()


def test_zero_return_and_zero_close_bars_are_missing_never_inf():
    closes, volumes = _series(80)
    closes = closes.copy()
    closes[30] = closes[29]  # zero return: ln(0)
    closes[50] = 0.0
    with np.errstate(all="raise"):
        out = _z(closes, volumes, window=10, fraction=1.0)
    assert not np.isinf(out).any()
    assert np.isnan(out[30]) and np.isnan(out[50]) and np.isnan(out[51])


def test_window_restarts_at_a_basis_change_and_matches_a_series_started_there():
    closes, volumes = _series(300)
    k = 150
    volumes = volumes.copy()
    volumes[:k] *= 0.6  # the SMART seam: volume counts about 0.4 to 0.9 of consolidated
    basis = np.where(np.arange(300) < k, SMART, CONSOLIDATED)
    window, fraction = 40, 0.8
    out = _z(closes, volumes, basis, window, fraction)
    tail = _z(closes[k - 1 :], volumes[k - 1 :], None, window, fraction)
    needed = math.ceil(fraction * window)
    # rows k .. k + needed - 2 are NaN until the new segment holds enough observations
    assert np.isnan(out[k : k + needed - 1]).all()
    assert np.isfinite(out[k + needed - 1 :]).all()
    np.testing.assert_allclose(
        out[k + needed - 1 :], tail[needed:][: len(out) - k - needed + 1], rtol=1e-9
    )
    # without the basis, the rows just after the seam are scored against a window of pre-seam
    # bars: volume rose by 1/0.6, ln(illiq) fell, and their z sits lower (the level shift)
    spanned = _z(closes, volumes, None, window, fraction)
    assert spanned[k + 1 : k + 20].mean() < out[k + needed - 1 :].mean() - 0.15


def test_a_basis_change_is_per_row_not_a_date():
    basis = np.array([SMART] * 5 + [CONSOLIDATED] * 3 + [SMART] * 2)
    assert volume_basis_segment_starts(basis).tolist() == [0] * 5 + [5] * 3 + [8] * 2


def test_no_volume_rows_carry_no_basis_and_never_reset():
    basis = np.array([CONSOLIDATED, NONE, NONE, CONSOLIDATED, NONE, CONSOLIDATED])
    assert volume_basis_segment_starts(basis).tolist() == [0] * 6
    leading = np.array([NONE, NONE, SMART, NONE, CONSOLIDATED])
    assert volume_basis_segment_starts(leading).tolist() == [0, 0, 0, 0, 4]


def test_all_null_volume_series_is_all_nan_not_a_crash():
    closes, _ = _series(50)
    assert np.isnan(_z(closes, np.full(50, np.nan), np.zeros(50, dtype=int))).all()


def test_null_volume_on_a_bar_leaves_every_price_feature_bit_unchanged():
    inputs, config = ref.synthetic_inputs()
    registry = default_registry()
    price_outputs = ["momentum_z_fast", "atr_z", "roll_spread", "high_low_spread", "rsi_fast"]
    names = [o for o in price_outputs if o in registry.feature_columns()]
    assert names
    clean = compute_kernels(registry, dict(inputs), config, outputs=names)
    nulled = dict(inputs)
    nulled["volume"] = inputs["volume"].copy()
    nulled["volume"][100] = np.nan
    nulled["volume_basis"] = inputs["volume_basis"].copy()
    nulled["volume_basis"][100] = NONE
    got = compute_kernels(registry, nulled, config, outputs=names)
    for name in names:
        assert np.array_equal(clean[name], got[name], equal_nan=True), name


@pytest.mark.parametrize("bad", [(), (1,)])
def test_short_series_is_all_nan(bad):
    closes = np.array(bad, dtype=float) + 100.0
    assert np.isnan(_z(closes, np.full(len(closes), 1e6))).all()


def test_a_null_volume_bar_is_masked_within_memory_for_kernels_that_are_not_nan_safe():
    inputs, config = ref.synthetic_inputs()
    registry = default_registry()
    n = len(inputs["ts"])
    clean = compute_kernels(registry, dict(inputs), config, outputs=["volume_z", "obv_z"])
    nulled = dict(inputs)
    nulled["volume"] = inputs["volume"].copy()
    nulled["volume"][100] = np.nan
    nulled["volume_basis"] = inputs["volume_basis"].copy()
    nulled["volume_basis"][100] = NONE
    got = compute_kernels(registry, nulled, config, outputs=["volume_z", "obv_z"])
    for name in ("volume_z", "obv_z"):
        memory = registry.by_output(name).memory(config)
        assert np.isnan(got[name][100 : 101 + memory]).all(), name
        # past its memory the row equals the clean run (obv_z to cumulative-sum rounding)
        np.testing.assert_allclose(
            got[name][102 + memory :], clean[name][102 + memory :], rtol=1e-5, atol=1e-6
        )
        assert np.isfinite(got[name][102 + memory :]).all() and len(got[name]) == n


def test_a_basis_change_restarts_a_rolling_volume_kernel_like_a_series_started_there():
    inputs, config = ref.synthetic_inputs()
    registry = default_registry()
    k = 150
    mixed = dict(inputs)
    mixed["volume"] = inputs["volume"].copy()
    mixed["volume"][:k] *= 0.5
    mixed["volume_basis"] = np.where(np.arange(len(inputs["ts"])) < k, SMART, CONSOLIDATED)
    got = compute_kernels(registry, mixed, config, outputs=["volume_z"])["volume_z"]
    tail = {name: np.asarray(v)[k:] for name, v in inputs.items() if np.ndim(v) == 1}
    alone = compute_kernels(registry, tail, config, outputs=["volume_z"])["volume_z"]
    memory = registry.by_output("volume_z").memory(config)
    assert np.isnan(got[k : k + memory]).all()
    np.testing.assert_allclose(got[k + memory :], alone[memory:], rtol=1e-9)
