"""Every stored feature column has a declared warmup (186-31 review round 3).

`KernelRegistry.warmup_bars` is the declared memory, or a path-dependent kernel's declared anchor
warmup, composed over the inputs it reads. The pilot and corpus gates (G2 late start, G6 NULL
share) measure every column from it, so a column without one, or with one shorter than the
kernel's real first defined row, would either go unjudged or fail healthy data. The empirical
test computes every kernel on a healthy 5m series and checks each column's first finite row
against its declaration.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.features.contract.registry import (
    MEMORY_ANCHORS,
    KernelRegistryError,
    bars_per_session,
    compute_kernels,
    constant_volume_basis,
    default_registry,
)
from src.intelligence.features.feature_vector_persistence import feature_vectors_numeric_columns
from src.intelligence.features.kernels.regime import HmmConfig
from tests.unit.intelligence.regime_kernel_fixtures import SMALL_HMM_APR
from tests.unit.intelligence.test_swing_fib_trend_structure_primitives import _make_cfg

TFS = ("5m", "15m", "1h", "1d")
G2_GAP = 5  # threshold.pilot_gate.warmup_gap_bars seed


@pytest.fixture(scope="module")
def registry_and_config():
    return default_registry(), dataclasses.replace(
        _make_cfg(), hmm=HmmConfig.from_values(SMALL_HMM_APR.get)
    )


def test_every_applicable_feature_column_has_a_declared_warmup_on_every_tf(registry_and_config):
    registry, config = registry_and_config
    missing = []
    for tf in TFS:
        applicable = registry.applicable_outputs(tf)
        for column in feature_vectors_numeric_columns():
            if column not in applicable:
                continue
            try:
                warmup = registry.warmup_bars(column, config, tf)
            except KernelRegistryError as error:
                missing.append((tf, column, str(error)[:80]))
                continue
            assert isinstance(warmup, int) and warmup >= 0, (tf, column, warmup)
    assert missing == []


def test_every_path_dependent_kernel_behind_a_column_declares_its_anchor(registry_and_config):
    registry, _config = registry_and_config
    columns = set(feature_vectors_numeric_columns())
    for kernel in registry.kernels:
        if kernel.path_dependent and set(kernel.outputs) & columns:
            assert kernel.memory_anchor in MEMORY_ANCHORS, kernel.name
            assert kernel.warmup is not None, kernel.name


def test_an_undeclared_path_dependent_kernel_refuses(registry_and_config):
    registry, config = registry_and_config
    kernel = registry.by_output("ret_autocorr_1")
    bare = dataclasses.replace(kernel, warmup=None)
    with pytest.raises(KernelRegistryError, match="memory_anchor"):
        registry._warmup(bare, config, "5m", "ret_autocorr_1")


def test_a_product_reads_the_warmup_of_the_input_it_reads(registry_and_config):
    """momentum_trend_product reads adx: it is held to adx's warmup, not hma_slope_z's (both
    come from bar_statistics_refresh)."""
    registry, config = registry_and_config
    adx = registry.warmup_bars("adx", config, "5m")
    assert registry.warmup_bars("hma_slope_z", config, "5m") > adx
    product = registry.warmup_bars("momentum_trend_product", config, "5m")
    assert product == max(adx, registry.warmup_bars("momentum_z_fast", config, "5m"))


def test_anchors_scale_with_the_bars_of_a_session(registry_and_config):
    registry, config = registry_and_config
    assert bars_per_session(config, "5m") == 78 and bars_per_session(config, "1d") == 1
    week = {tf: registry.warmup_bars("above_wk_vwap", config, tf) for tf in ("5m", "1h", "1d")}
    assert week["5m"] > week["1h"] > week["1d"] > 0


def test_object_dependence_is_declared_for_the_object_columns(registry_and_config):
    registry, _config = registry_and_config
    declared = registry.object_dependent_outputs()
    for column in (
        "nearest_hvn_dist_atr",
        "nearest_lvn_above_dist_atr",
        "in_lvn",
        "distance_to_vah_atr",
        "opening_gap_pct",
        "sr_support_dist",
        "fvg_dist_atr",
        "swing_high_dist_atr",
    ):
        assert column in declared, column
    # a measured state is never an absent object, and the always-existing columns are measured
    zero_state = {o for k in registry.kernels for o in k.zero_is_state}
    assert not declared & zero_state
    for column in ("momentum_z_fast", "adx", "poc_rolling_dist_atr", "prior_session_high_dist_atr"):
        assert column not in declared, column


def _session_bars(n: int) -> dict[str, np.ndarray]:
    """A healthy 5m series inside NYSE regular sessions (14:30 to 21:00 UTC, weekdays): a
    random walk with volume, every bar real."""
    rng = np.random.default_rng(7)
    stamps: list[datetime] = []
    day = datetime(2023, 1, 3, tzinfo=UTC)
    while len(stamps) < n:
        if day.weekday() < 5:
            open_ = day.replace(hour=14, minute=30)
            stamps += [open_ + timedelta(minutes=5 * i) for i in range(78)]
        day += timedelta(days=1)
    stamps = stamps[:n]
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    spread = np.abs(rng.normal(0, 0.001, n)) * close
    return {
        "ts": np.array([int(t.timestamp() * 1e9) for t in stamps], dtype=np.int64),
        "open": np.r_[close[0], close[:-1]],
        "high": close + spread,
        "low": close - spread,
        "close": close,
        "volume": rng.integers(1_000, 50_000, n).astype(float),
        "volume_basis": constant_volume_basis(n),
        "symbol": np.array(["TEST"] * n, dtype=object),
        "tf": np.array(["5m"] * n, dtype=object),
    }


def test_no_column_starts_later_than_its_declared_warmup_on_healthy_bars(registry_and_config):
    """On a healthy series each column's first finite row is at most its declared warmup plus
    the G2 gap: a declaration shorter than the kernel's real cold start would fail G2 on healthy
    data. Columns that read external series (all NaN here) and object columns (their object may
    first appear late) are not judged; the HMM is judged where its first segment converges."""
    registry, config = registry_and_config
    n = 2400
    inputs = _session_bars(n)
    for ext in registry.external_inputs:
        inputs.setdefault(ext.name, np.full(n, np.nan))
    out = compute_kernels(registry, inputs, config)
    objects = registry.object_dependent_outputs()
    externals = {ext.name for ext in registry.external_inputs}
    late = []
    for column in feature_vectors_numeric_columns():
        if column not in registry.applicable_outputs("5m") or column in objects:
            continue
        kernel = registry.by_output(column)
        chain = [kernel, *registry._upstream(kernel)]
        if any(set(k.inputs) & externals for k in chain):
            continue
        values = np.asarray(out[column], dtype=float)
        finite = np.flatnonzero(np.isfinite(values))
        if not len(finite):
            continue  # never finite here: G1/G6 judge that, not this declaration test
        declared = registry.warmup_bars(column, config, "5m")
        if finite[0] > declared + G2_GAP:
            late.append((column, int(finite[0]), declared))
    assert late == []


def test_the_hmm_first_label_falls_on_a_refit_boundary_at_or_after_its_declared_warmup():
    """The HMM's declared warmup is its first refit boundary (valid_start + 1 + the boundary in
    observation rows). A degenerate first segment is not written, so a series may label later,
    but only at a later boundary: the declaration's offsets are exact."""
    from tests.unit.intelligence.regime_kernel_fixtures import regime_probe_case

    available, config = regime_probe_case()
    registry = default_registry()
    refit, _warmup = config.hmm.walk_forward_schedule("1d")
    judged = 0
    for column in ("hmm_regime_prob", "hmm_entropy", "hmm_vol_prob_calm"):
        finite = np.flatnonzero(np.isfinite(np.asarray(available[column], dtype=float)))
        if not len(finite):
            continue
        declared = registry.warmup_bars(column, config, "1d")
        assert finite[0] >= declared and (finite[0] - declared) % refit == 0, (column, finite[0])
        judged += 1
    assert judged  # the fixture labels at least the trend family
