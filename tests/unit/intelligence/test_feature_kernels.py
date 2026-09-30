"""Registered feature kernels against compute_batch and the causality probe (186-12, D-25, D-26).

(a) every registered feature column is a persisted FeatureVector column;
(b) each kernel output equals the compute_batch column on the 500-bar synthetic fixture;
    the regime kernels (HMM fit cost, per-tf schedule) are covered by test_regime_kernel.py;
(c) compute_batch no longer calls the moved scalar helpers;
(d) the causality probe and memory check pass every kernel under two configs.
"""

from __future__ import annotations

import inspect
import re
from datetime import UTC, datetime
from functools import lru_cache

import numpy as np
import pytest

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import FeatureFactory, _macro_kernel_inputs
from src.intelligence.features.contract.causality_probe import (
    CausalityViolation,
    causality_probe,
    memory_check,
    probe_registry,
)
from src.intelligence.features.contract.derived_inputs import with_derived_inputs
from src.intelligence.features.contract.registry import compute_kernels, default_registry
from src.intelligence.features.feature_vector_persistence import (
    _ALL_COLUMN_NAMES,
    REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES,
    REGIME_WRITER_OWNED_COLUMN_NAMES,
)
from tests.unit.intelligence import kernel_parity_reference as ref
from tests.unit.intelligence.regime_kernel_fixtures import (
    non_regime_kernels,
    non_regime_outputs,
    registry_without_regime,
)

MANIFEST = ref.load_manifest()
PROBE_ROWS = np.array([700, 1200, 1800, 2400, 2999])
PROBE_BARS = 3000

# Kernels whose output depends on where the series starts (registry path_dependent).
PATH_DEPENDENT = {
    "calendar_above_wk_vwap",
    "ret_autocorr",
    "abs_ret_autocorr",
    "streak_z",
    "variance_ratio",
    "bar_statistics_refresh",
    "vwap_dev_sigma",
    "session_vp",
    "session_levels",
    "amd_cycle",
}
ACAUSAL_CONTROLS = {"canary_acausal_placebo"}

# compute_batch calls none of these helpers by name any more; it reads registry outputs.
DELEGATED_HELPERS = (
    "_in_ny_session",
    "_in_london_kz",
    "_in_overlap",
    "_power_hour",
    "_opening_range",
    "_session_time_pos",
    "_dow_encoding",
    "_month_position",
    "_quarter_position",
    "_days_to_month_end_fraction",
    "_quarter_cycle_encoding",
    "_tdom_encoding",
    "_minute_of_hour_encoding",
    "_hour_of_day_sin",
    "_hour_of_day_cos",
    "_week_of_month_sin",
    "_week_of_month_cos",
    "_day_of_month_sin",
    "_day_of_month_cos",
    "_week_of_year_sin",
    "_week_of_year_cos",
    "_month_sin",
    "_month_cos",
    "_opex_flag",
    "_quad_witching_flag",
    "_earnings_season_flag",
    "_days_since_quarter_end",
    "_canary_noise_gaussian",
    "_canary_noise_uniform",
    "_canary_near_constant",
    "_canary_acausal_placebo",
    "_bar_close_pos",
    "_range_position",
    "_vol_ratio",
    "_body_ratio",
    "_upper_wick_ratio",
    "_lower_wick_ratio",
    "_range_vs_atr",
    "_close_vs_open_direction",
    "_overnight_gap",
    "_range_efficiency",
    "_ret_lag_1",
    "_ret_lag_2",
    "_ret_lag_3",
    "_ret_lag_fast",
    "_ret_lag_mid",
    "_ret_lag_slow",
    "_open_ret",
    "_intraday_ret",
    "_open_vs_intraday",
    "_cci",
    "_aroon_osc",
    "_ret_vol_ratio",
    "_informed_flow",
    "_cmf",
    "_product",
    "_up_vol_body_diff",
    "_rolling_poc_price",
    "_compute_sr_dist_atr",
    "_compute_swing_structure",
    "_compute_trend_structure",
    "_compute_swing_momentum",
    "_compute_fib_zones",
    "_compute_order_blocks",
    "_compute_fvg",
    "_compute_liquidity_sweeps",
    "_compute_liquidity_pools",
    "_compute_supply_demand_zones",
    "_compute_bos_choch",
)


# Numeric persisted columns no kernel owns after this step: CTF, the three ret_div columns and
# the cross-sectional rank columns. The HMM
# regime columns are owned by the regime kernels (186-13). A column
# that is dropped or left unowned changes this set and fails the test below.
REMAINING_COLUMNS = frozenset(
    {
        "ctf_momentum",
        "ctf_regime_align",
        "ctf_vwap_align",
        "momentum_rank_z",
        "ret_div_1h_1d",
        "ret_div_1m_5m",
        "ret_div_5m_1h",
        "volatility_rank_z",
        "volume_rank_z",
    }
)


REGIME_COLUMNS = frozenset(
    (*REGIME_WRITER_OWNED_COLUMN_NAMES, *REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES)
)


def test_every_numeric_column_is_owned_by_a_kernel_or_listed_as_remaining():
    numeric = set(MANIFEST["numeric_columns"])
    owned = set(default_registry().feature_columns())
    # The regime kernels own 16 persisted columns; the parity manifest's numeric set holds the
    # three that FeatureVector carries (the labels and the other numeric ones are not in it).
    assert REGIME_COLUMNS <= owned
    assert REGIME_COLUMNS & numeric == {"hmm_regime_prob", "hmm_entropy", "hmm_duration"}
    assert (owned - (REGIME_COLUMNS - numeric)) | REMAINING_COLUMNS == numeric
    assert not owned & REMAINING_COLUMNS


def synthetic_bars(n: int, seed: int = 42) -> dict[str, np.ndarray]:
    """Same generator order as the parity fixture's synthetic case, for any length."""
    rng = np.random.default_rng(seed)
    closes = np.cumprod(1.0 + rng.normal(0, 0.005, n)) * 100.0
    spread = closes * rng.uniform(0.001, 0.008, n)
    highs = closes + spread
    lows = closes - spread
    opens = closes + rng.normal(0, 0.003, n) * closes
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))
    volumes = rng.uniform(1e5, 1e7, n)
    base = ref.dt_to_ns(datetime(2023, 1, 3, 14, 30, tzinfo=UTC))
    ts = base + np.arange(n, dtype=np.int64) * 5 * 60 * 1_000_000_000
    return {
        "ts": ts,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "symbol": np.array(["SPY"] * n, dtype=object),
        "tf": np.array(["5m"] * n, dtype=object),
        **{
            external.name: rng.normal(0.0, 1.0, n)
            for external in default_registry().external_inputs
            if external.name.startswith("ext_")
        },
    }


@lru_cache(maxsize=1)
def _synthetic_case():
    inputs, config = ref.synthetic_inputs()
    bars = ref._bars_from_arrays(
        *(inputs[f] for f in ("ts", "open", "high", "low", "close", "volume"))
    )
    results = FeatureFactory.compute_batch(
        bars, "SPY", "5m", FeatureCache(), config, warm_up_bars=0
    )
    inputs = {
        **inputs,
        "symbol": np.array(["SPY"] * len(inputs["ts"]), dtype=object),
        "tf": np.array(["5m"] * len(inputs["ts"]), dtype=object),
        # the live-cache branch compute_batch took above: cache values broadcast, SPY beta None
        **_macro_kernel_inputs(inputs["ts"], "SPY", "5m", FeatureCache(), None, None),
    }
    batch = {
        name: np.array([getattr(fv, name) for _, fv in results], dtype=np.float64)
        for name in _ALL_COLUMN_NAMES
        if hasattr(results[0][1], name)
    }
    kernels = compute_kernels(
        default_registry(), inputs, config, outputs=non_regime_outputs(default_registry())
    )
    return kernels, batch, len(inputs["ts"])


def test_feature_columns_are_persisted_columns():
    columns = default_registry().feature_columns()
    assert columns
    assert set(columns) <= set(_ALL_COLUMN_NAMES) | REGIME_COLUMNS


def test_kernel_outputs_equal_compute_batch_rows_1_onward():
    kernels, batch, n = _synthetic_case()
    columns = [c for c in default_registry().feature_columns() if c in kernels]  # no regime
    for name in columns:
        assert name in batch, f"{name} is not a FeatureVector field"
        got = kernels[name][1:].astype(np.float32)
        want = batch[name].astype(np.float32)
        assert len(got) == len(want) == n - 1
        bad = ~((got == want) | (np.isnan(got) & np.isnan(want)))
        assert (
            not bad.any()
        ), f"{name}: row {int(np.argmax(bad)) + 1} got {got[bad][0]!r} want {want[bad][0]!r}"


def test_stateless_structure_kernels_equal_direct_helper_calls():
    """The batch loop now reads these columns from the kernels, so (b) alone compares a kernel
    with itself. This calls the moved helpers directly on the loop's windows, every 7th row."""
    from src.intelligence.features.kernels import smc, vp_sr

    kernels, _batch, n = _synthetic_case()
    inputs, config = ref.synthetic_inputs()
    o, h, lo, c, v = (inputs[f] for f in ("open", "high", "low", "close", "volume"))
    atr = kernels["_atr_raw_padded"]
    for i in range(1, n, 7):
        a = float(atr[i])
        s = max(0, i - config.smc_order_blocks_lookback + 1)
        ob = smc._compute_order_blocks(
            o[s : i + 1],
            h[s : i + 1],
            lo[s : i + 1],
            c[s : i + 1],
            v[s : i + 1],
            float(c[i]),
            a,
            config,
        )
        s = max(0, i - config.sr_lookback_by_tf.get("5m", 120) + 1)
        sr = vp_sr._compute_sr_dist_atr(
            h[s : i + 1], lo[s : i + 1], float(c[i]), a, v[s : i + 1], "5m", config
        )
        s = max(0, i - config.swing_lookback_bars + 1)
        swing = vp_sr._compute_swing_structure(h[s : i + 1], lo[s : i + 1], float(c[i]), a, config)
        trend = vp_sr._compute_trend_structure(
            h[s : i + 1], lo[s : i + 1], float(c[i]), a, swing, config
        )
        for name, want in {**ob, **sr, **trend}.items():
            expected = np.nan if want is None else want
            assert np.float32(kernels[name][i]) == np.float32(expected) or (
                np.isnan(kernels[name][i]) and np.isnan(expected)
            ), (name, i)
        for name in vp_sr.SWING_KEYS:
            want = swing[name]
            expected = np.nan if want is None else want
            got = kernels[name][i]
            assert got == expected or (np.isnan(got) and np.isnan(expected)), (name, i)


def _code_lines(func) -> str:
    return "\n".join(
        line for line in inspect.getsource(func).splitlines() if not line.lstrip().startswith("#")
    )


def test_compute_batch_calls_no_delegated_helper():
    body = _code_lines(FeatureFactory.compute_batch)
    called = [name for name in DELEGATED_HELPERS if re.search(rf"(?<![A-Za-z0-9_]){name}\(", body)]
    assert called == []


@lru_cache(maxsize=2)
def _probe_case(config_key: str):
    config = ref.build_config(MANIFEST[config_key])
    available = with_derived_inputs(synthetic_bars(PROBE_BARS))
    available.update(
        compute_kernels(
            default_registry(), available, config, outputs=non_regime_outputs(default_registry())
        )
    )
    return available, config


# The regime kernels are skipped here: REGIME_SKIP_REASON.
@pytest.mark.parametrize("config_key", ["synthetic_config", "real_config"])
@pytest.mark.parametrize("kernel", non_regime_kernels(default_registry()), ids=lambda k: k.name)
def test_probe_and_memory_check_per_kernel(kernel, config_key):
    available, config = _probe_case(config_key)
    if kernel.acausal_control:
        with pytest.raises(CausalityViolation):
            causality_probe(kernel, available, config, PROBE_ROWS)
        return
    causality_probe(kernel, available, config, PROBE_ROWS)
    if kernel.path_dependent:
        assert kernel.name in PATH_DEPENDENT
        return
    assert kernel.name not in PATH_DEPENDENT
    memory_check(kernel, available, config, PROBE_ROWS)


def test_the_path_dependent_allow_list_is_the_reviewed_ten():
    """A new kernel that declares path_dependent skips the memory check; that needs a review,
    so it has to be added to PATH_DEPENDENT here (and this count changed) by a person."""
    declared = {k.name for k in non_regime_kernels(default_registry()) if k.path_dependent}
    assert declared == PATH_DEPENDENT
    assert len(PATH_DEPENDENT) == 10


@pytest.mark.parametrize("config_key", ["synthetic_config", "real_config"])
def test_probe_registry_statuses(config_key):
    config = ref.build_config(MANIFEST[config_key])
    registry = registry_without_regime(default_registry())  # REGIME_SKIP_REASON
    statuses = probe_registry(registry, synthetic_bars(PROBE_BARS), config, PROBE_ROWS)
    expected = {
        kernel.name: (
            "acausal_control_detected"
            if kernel.name in ACAUSAL_CONTROLS
            else "path_dependent_skipped_memory" if kernel.name in PATH_DEPENDENT else "ok"
        )
        for kernel in registry.kernels
    }
    assert statuses == expected
    assert set(statuses) == {k.name for k in registry.kernels}  # no kernel opts out


def _gap_z(config, opens_override=None, n=400):
    inputs = synthetic_bars(n)
    if opens_override is not None:
        inputs["open"] = opens_override(inputs["open"].copy())
    return compute_kernels(default_registry(), inputs, config, outputs=["gap_z"])["gap_z"]


def test_gap_z_row_ignores_the_next_bars_open():
    """RED before the fix: row 300 moved when bar 301's open changed (off-by-one alignment)."""
    config = ref.build_config(MANIFEST["synthetic_config"])

    def bump(opens):
        opens[301] *= 1.02
        return opens

    base, alt = _gap_z(config), _gap_z(config, bump)
    assert base[300] == alt[300]
    assert base[301] != alt[301]  # the bar whose open changed does read it


def test_gap_z_last_row_is_computed():
    """The old alignment left the final row at 0.0 in every batch (and in every live call)."""
    config = ref.build_config(MANIFEST["synthetic_config"])
    assert _gap_z(config)[-1] != 0.0


def _short_gap_z(n):
    from src.intelligence.features.kernels.price import _gap_z_series_full

    opens = np.array([100.0, 101.0, 103.0, 102.0])[:n]
    closes = np.array([100.5, 101.5, 102.0, 102.5])[:n]
    atr_padded = np.full(n, 2.0)
    atr_valid = np.ones(n, dtype=bool)
    return _gap_z_series_full(opens, closes, atr_padded, atr_valid, 20), opens, closes


def test_gap_z_three_bars_scores_bar_two_gap():
    """gap at bar 2 = (103 - 101.5) / 2 = 0.75; z against [0, 0.75] (mean .375, sd .375)
    is exactly +1. It was 0.0 before the guard admitted len == 2."""
    out, _, _ = _short_gap_z(3)
    assert out[:2].tolist() == [0.0, 0.0]
    assert out[2] == pytest.approx(1.0)


def test_gap_z_four_bars_scores_each_gap_against_its_trailing_window():
    out, opens, closes = _short_gap_z(4)
    g = [(opens[2] - closes[1]) / 2.0, (opens[3] - closes[2]) / 2.0]  # 0.75, 0.0
    series = np.array([0.0, g[0], g[1]])
    expected_bar3 = (series[2] - series[:3].mean()) / series[:3].std()
    assert out[2] == pytest.approx(1.0)
    assert out[3] == pytest.approx(expected_bar3)
    assert np.isfinite(out).all()
