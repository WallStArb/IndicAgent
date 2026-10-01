"""Registered feature kernels against compute_batch and the causality probe (186-12, D-25, D-26).

(a) every registered feature column is a persisted FeatureVector column;
(b) each kernel output equals the compute_batch column on the 500-bar synthetic fixture;
    the regime kernels are probed on their own short series and covered by test_regime_kernel.py;
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

from src.intelligence.feature_factory import (
    FeatureFactory,
    _cross_tf_kernel_inputs,
    _macro_kernel_inputs,
)
from src.intelligence.features.contract.causality_probe import (
    CausalityViolation,
    causality_probe,
    memory_check,
    probe_registry,
)
from src.intelligence.features.contract.derived_inputs import with_derived_inputs
from src.intelligence.features.contract.registry import (
    UNOWNED_COLUMNS,
    KernelRegistry,
    compute_kernels,
    default_registry,
)
from src.intelligence.features.feature_vector_persistence import (
    _ALL_COLUMN_NAMES,
    REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES,
    REGIME_WRITER_OWNED_COLUMN_NAMES,
)
from src.intelligence.features.kernels._cache_state import FeatureCache
from tests.unit.intelligence import kernel_parity_reference as ref
from tests.unit.intelligence.daily_grid_fixtures import (
    DAILY_GRID_KERNELS,
    daily_grid_inputs,
    daily_grid_kernels,
    intraday_kernels,
)
from tests.unit.intelligence.regime_kernel_fixtures import (
    REGIME_PROBE_ROWS,
    regime_kernels,
    regime_probe_case,
)

MANIFEST = ref.load_manifest()
PROBE_ROWS = np.array([700, 1200, 1800, 2400, 2999])
PROBE_BARS = 3000

# Kernels whose output depends on where the series starts (registry path_dependent).
PATH_DEPENDENT = {
    "cross_asset_daily",
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
    "ctf_source",
    # the regime kernels: the walk-forward fits run from the series start (kernels/regime.py)
    "hmm_trend_walk_forward",
    "hmm_trend_label",
    "hmm_volatility_walk_forward",
    "hmm_volatility_label",
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


REGIME_COLUMNS = frozenset(
    (*REGIME_WRITER_OWNED_COLUMN_NAMES, *REGIME_VOLATILITY_WRITER_OWNED_COLUMN_NAMES)
)


def test_every_numeric_column_is_owned_by_a_kernel_or_listed_as_unowned():
    numeric = set(MANIFEST["numeric_columns"])
    owned = set(default_registry().feature_columns())
    # The regime kernels own 16 persisted columns; the parity manifest's numeric set holds the
    # three that FeatureVector carries (the labels and the other numeric ones are not in it).
    assert REGIME_COLUMNS <= owned
    assert REGIME_COLUMNS & numeric == {"hmm_regime_prob", "hmm_entropy", "hmm_duration"}
    assert (owned - (REGIME_COLUMNS - numeric)) | set(UNOWNED_COLUMNS) == numeric
    assert not owned & set(UNOWNED_COLUMNS)


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


def _intraday_outputs() -> list[str]:
    """Outputs of the kernels that run on the intraday row grid (not regime, not daily-grid)."""
    return [o for k in intraday_kernels(default_registry().kernels) for o in k.outputs]


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
        **_cross_tf_kernel_inputs(
            inputs["ts"],
            "5m",
            FeatureCache(),
            None,
            None,
        ),
    }
    batch = {
        name: np.array([getattr(fv, name) for _, fv in results], dtype=np.float64)
        for name in _ALL_COLUMN_NAMES
        if hasattr(results[0][1], name)
    }
    kernels = compute_kernels(default_registry(), inputs, config, outputs=_intraday_outputs())
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
        for name in vp_sr.SWING.keys:
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
        compute_kernels(default_registry(), available, config, outputs=_intraday_outputs())
    )
    return available, config


PROBE_DAILY_ROWS = 3000


@lru_cache(maxsize=2)
def _daily_probe_case(config_key: str):
    config = ref.build_config(MANIFEST[config_key])
    return with_derived_inputs(daily_grid_inputs(PROBE_DAILY_ROWS)), config


@lru_cache(maxsize=1)
def _regime_probe_case(_config_key: str):
    return regime_probe_case()


def _case_for(kernel, config_key: str):
    """(inputs, config, probed rows) of the grid the kernel runs on: daily, regime or intraday."""
    if kernel.name in DAILY_GRID_KERNELS:
        return (*_daily_probe_case(config_key), PROBE_ROWS)
    if kernel.origin == "regime":
        return (*_regime_probe_case("regime"), REGIME_PROBE_ROWS)
    return (*_probe_case(config_key), PROBE_ROWS)


@pytest.mark.parametrize("config_key", ["synthetic_config", "real_config"])
@pytest.mark.parametrize("kernel", default_registry().kernels, ids=lambda k: k.name)
def test_probe_and_memory_check_per_kernel(kernel, config_key):
    available, config, rows = _case_for(kernel, config_key)
    if kernel.acausal_control:
        with pytest.raises(CausalityViolation):
            causality_probe(kernel, available, config, rows)
        return
    causality_probe(kernel, available, config, rows)
    if kernel.path_dependent:
        assert kernel.name in PATH_DEPENDENT
        return
    assert kernel.name not in PATH_DEPENDENT
    memory_check(kernel, available, config, rows)


def test_the_path_dependent_allow_list_is_the_reviewed_sixteen():
    """A new kernel that declares path_dependent skips the memory check; that needs a review,
    so it has to be added to PATH_DEPENDENT here (and this count changed) by a person. Twelve
    feature kernels plus the four regime kernels (two walk-forward fits and their labels)."""
    declared = {k.name for k in default_registry().kernels if k.path_dependent}
    assert declared == PATH_DEPENDENT
    assert len(PATH_DEPENDENT) == 16


@pytest.mark.parametrize("config_key", ["synthetic_config", "real_config"])
def test_probe_registry_statuses(config_key):
    config = ref.build_config(MANIFEST[config_key])
    registry = KernelRegistry.from_kernels(
        intraday_kernels(default_registry().kernels), default_registry().external_inputs
    )
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


def test_probe_registry_statuses_on_the_regime_series():
    """The regime kernels go through probe_registry on their own short series under the small HMM
    configuration, like every other kernel; none is exempt."""
    available, config = _regime_probe_case("regime")
    registry = KernelRegistry.from_kernels(
        regime_kernels(default_registry().kernels), default_registry().external_inputs
    )
    inputs = {name: available[name] for name in ("ts", "close", "volume", "tf")}
    statuses = probe_registry(registry, inputs, config, REGIME_PROBE_ROWS)
    assert statuses == dict.fromkeys(
        (k.name for k in registry.kernels), "path_dependent_skipped_memory"
    )
    assert set(statuses) == {k.name for k in default_registry().kernels if k.origin == "regime"}


def test_every_registered_kernel_is_probed_by_exactly_one_registry_probe():
    """The intraday, daily-grid and regime probes partition the registry: a kernel added to a new
    origin that none of them runs fails here rather than going unprobed."""
    kernels = default_registry().kernels
    intraday = {k.name for k in intraday_kernels(kernels)}
    daily = {k.name for k in daily_grid_kernels(kernels)}
    regime = {k.name for k in regime_kernels(kernels)}
    assert not (intraday & daily or intraday & regime or daily & regime)
    assert intraday | daily | regime == {k.name for k in kernels}


@pytest.mark.parametrize("config_key", ["synthetic_config", "real_config"])
def test_probe_registry_statuses_on_the_daily_grid(config_key):
    """The daily-grid kernels are probed on one row per date (see daily_grid_fixtures)."""
    config = ref.build_config(MANIFEST[config_key])
    registry = KernelRegistry.from_kernels(
        daily_grid_kernels(default_registry().kernels), default_registry().external_inputs
    )
    rows = np.array([700, 1200, 1800, 2400, 2999])
    statuses = probe_registry(registry, daily_grid_inputs(PROBE_DAILY_ROWS), config, rows)
    assert statuses == {
        "cross_asset_daily": "path_dependent_skipped_memory",
        "factor_beta_daily": "ok",
    }


@pytest.mark.parametrize("symbol", ["SPY", "TLT", "QQQ"])
def test_daily_grid_kernels_reproduce_the_builders_on_real_daily_bars(symbol):
    """Each registered daily kernel, run on the grid built from the stored real 1d bars, gives
    back exactly the dict the builder returns (SPY has no equity beta, TLT no rate beta)."""
    from src.intelligence.features.kernels.macro import (
        _BETA_OUTPUTS,
        _XA_OUTPUTS,
        CROSS_ASSET_SYMBOLS,
        beta_records,
        build_cross_asset_series,
        build_symbol_beta_series,
        cross_asset_records,
        daily_reference_grid,
    )

    npz = np.load(ref.FIXTURE_DIR / "real_inputs.npz")
    config = ref.build_config(MANIFEST["real_config"])
    names = {symbol, *CROSS_ASSET_SYMBOLS}
    if any(f"d1/{s}/ts" not in npz.files for s in names):
        pytest.skip(f"real_inputs.npz has no 1d bars for {sorted(names)}")
    d1 = {s: ref._series_bars(npz, f"d1/{s}") for s in names}
    grid = daily_reference_grid(
        {
            **{f"ref_{s.lower()}_close": d1[s] for s in CROSS_ASSET_SYMBOLS},
            "ref_sym_close": d1[symbol],
        }
    )
    n = len(grid["ts"])
    out = compute_kernels(
        default_registry(),
        {**grid, "symbol": np.array([symbol] * n, dtype=object)},
        config,
        outputs=[*_XA_OUTPUTS, *_BETA_OUTPUTS],
    )
    dates = [ref.ns_to_dt(ns).date() for ns in grid["ts"]]
    want_cross = build_cross_asset_series(*(d1[s] for s in CROSS_ASSET_SYMBOLS), config)
    want_beta = build_symbol_beta_series(d1[symbol], d1["SPY"], d1["TLT"], symbol, config)
    got_cross = cross_asset_records(dates, out)
    got_beta = beta_records(dates, out)
    assert want_cross and want_beta
    assert got_cross.keys() == want_cross.keys()
    for d, record in want_cross.items():
        np.testing.assert_array_equal(np.array(got_cross[d]), np.array(record), err_msg=str(d))
    assert got_beta == want_beta


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


# ---------------------------------------------------------------------------
# Ragged symbol starts, NaN holes and the daily as-of index (186-15 review)
# ---------------------------------------------------------------------------

RAGGED_PROBE_ROWS = np.array([150, 199, 201, 260, 330, 449, 452, 700, 1800, 2999])


@pytest.mark.parametrize("config_key", ["synthetic_config", "real_config"])
def test_daily_grid_kernels_are_causal_when_symbols_start_late_and_have_holes(config_key):
    """TIP, HYG and LQD start at rows 200, 320 and 450 and each has NaN holes, so the
    cross-asset coverage guard (a spread is NaN, the rest of the record is not) runs both ways.
    The probe rows sit on both sides of every start."""
    config = ref.build_config(MANIFEST[config_key])
    available = with_derived_inputs(daily_grid_inputs(PROBE_DAILY_ROWS, ragged=True))
    registry = KernelRegistry.from_kernels(
        daily_grid_kernels(default_registry().kernels), default_registry().external_inputs
    )
    statuses = probe_registry(registry, available, config, RAGGED_PROBE_ROWS)
    assert statuses == {
        "cross_asset_daily": "path_dependent_skipped_memory",
        "factor_beta_daily": "ok",
    }
    out = default_registry().by_name("cross_asset_daily").compute(available, config)
    # the guard branches were taken: the record exists from row 1 while each late spread is NaN
    assert np.isfinite(out["_xa_vix_z"][1:]).all()
    assert np.isnan(out["_xa_tip_tlt_ret_z"][1:201]).all()
    assert np.isfinite(out["_xa_tip_tlt_ret_z"][260])
    assert np.isnan(out["_xa_hyg_lqd_ret_z"][1:451]).all()
    assert np.isfinite(out["_xa_hyg_lqd_ret_z"][700])


ASOF_TFS = ("1m", "5m", "15m", "1h", "1d")


def _asof_case(tf: str):
    """Rows on a (ts, tf) grid over ~14 sessions with a weekend and a holiday gap, and ragged
    daily records: the first 25 dates have no value (a late-starting symbol), every 7th is a NaN
    hole, and two weekdays have no record at all."""
    from datetime import date, timedelta

    from src.intelligence.features.kernels.macro import daily_close_availability

    sessions, d = [], date(2022, 6, 1)
    while len(sessions) < 60:
        if d.weekday() < 5 and d not in (date(2022, 6, 20), date(2022, 7, 4)):
            sessions.append(d)
        d += timedelta(days=1)
    dates = sessions[:40] + sessions[42:]
    values = np.arange(len(dates), dtype=np.float64) + 1.0
    values[:25] = np.nan
    values[25::7] = np.nan
    step = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1d": 1440}[tf]
    rows = []
    for day in sessions[30:44]:
        start = datetime(
            day.year,
            day.month,
            day.day,
            0 if tf == "1d" else 13,
            0 if tf == "1d" else 30,
            tzinfo=UTC,
        )
        count = 1 if tf == "1d" else 390 // step
        rows += [ref.dt_to_ns(start + timedelta(minutes=step * k)) for k in range(count)]
    return np.array(rows, dtype=np.int64), dates, values, daily_close_availability(dates)


@pytest.mark.parametrize("tf", ASOF_TFS)
def test_daily_asof_index_is_causal_and_needs_no_memory_on_a_ragged_grid(tf):
    from src.intelligence.features.contract.registry import Kernel
    from src.intelligence.features.kernels.macro import daily_asof_index, daily_asof_indices

    ts, _dates, values, available = _asof_case(tf)
    column = np.append(values, np.nan)  # the trailing default is what index -1 reads

    def compute(x, _config):
        idx = daily_asof_indices(x["ts"], tf, available)
        return {"idx": idx.astype(np.float64), "value": column[idx]}

    kernel = Kernel(
        name="daily_asof_probe",
        outputs=("idx", "value"),
        inputs=("ts",),
        memory=lambda config: 0,
        compute=compute,
    )
    rows = np.unique(np.linspace(0, len(ts) - 1, 8).astype(int))
    causality_probe(kernel, {"ts": ts}, object(), rows)
    memory_check(kernel, {"ts": ts}, object(), rows)
    # the vector form is the scalar rule row by row
    scalar = [daily_asof_index(int(t), tf, available) for t in ts.tolist()]
    assert scalar == daily_asof_indices(ts, tf, available).tolist()
    # records that become available after row t's bar end do not change rows <= t
    full = daily_asof_indices(ts, tf, available)
    duration_ns = {"1m": 0, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}[tf] * 1_000_000_000
    for t in rows:
        known = [a for a in available if a <= int(ts[t]) + duration_ns]
        np.testing.assert_array_equal(daily_asof_indices(ts[: t + 1], tf, known), full[: t + 1])
