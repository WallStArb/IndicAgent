"""Every stored feature column has a declared first storable row (186-31 review rounds 3 and 4).

The rebuild stores a column with a finite memory as missing inside it (no_fill), so its first
storable row is that memory; a path-dependent column is stored from its definition warmup, the
first row its value can exist, composed over the definitions of the inputs it reads
(`KernelRegistry.definition_warmup`, never their seed-independence memory). G2 and G6 measure
stored rows from `backfill_feature_factory.stored_first_row`. On a healthy series the first
stored finite row of every series-start-anchored column must sit within the G2 tolerance of
that declaration, in both directions (too long hides a late start, too short fails healthy
data); session- and week-anchored columns sit within one anchor period. Object and event columns
are judged on the rows where their object exists (unit_stats), not here.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from services.backfill_feature_factory import _compute_series_columns, stored_first_row
from src.intelligence.features.contract.registry import (
    ANCHOR_SERIES_START,
    ANCHOR_SESSION_OPEN,
    ANCHOR_WEEK_OPEN,
    MEMORY_ANCHORS,
    KernelRegistryError,
    bars_per_session,
    constant_volume_basis,
    default_registry,
)
from src.intelligence.features.feature_vector_persistence import feature_vectors_numeric_columns
from src.intelligence.features.kernels.regime import HmmConfig
from tests.unit.intelligence.regime_kernel_fixtures import SMALL_HMM_APR
from tests.unit.intelligence.test_swing_fib_trend_structure_primitives import _make_cfg

TFS = ("5m", "15m", "1h", "1d")
TOLERANCE = 5  # threshold.pilot_gate.warmup_gap_bars seed (migration 557)


@pytest.fixture(scope="module")
def registry_and_config():
    return default_registry(), dataclasses.replace(
        _make_cfg(), hmm=HmmConfig.from_values(SMALL_HMM_APR.get)
    )


def test_every_applicable_feature_column_has_a_first_storable_row_on_every_tf(
    registry_and_config,
):
    registry, config = registry_and_config
    missing = []
    for tf in TFS:
        applicable = registry.applicable_outputs(tf)
        for column in feature_vectors_numeric_columns():
            if column not in applicable:
                continue
            try:
                first = stored_first_row(registry, column, config, tf)
            except KernelRegistryError as error:
                missing.append((tf, column, str(error)[:80]))
                continue
            assert isinstance(first, int) and first >= 0, (tf, column, first)
    assert missing == []


def test_every_path_dependent_kernel_behind_a_column_declares_its_anchor(registry_and_config):
    registry, _config = registry_and_config
    columns = set(feature_vectors_numeric_columns())
    for kernel in registry.kernels:
        if kernel.path_dependent and set(kernel.outputs) & columns:
            for output in set(kernel.outputs) & columns:
                assert registry.anchor_of_kernel(kernel, output) in MEMORY_ANCHORS, output
            assert kernel.definition is not None, kernel.name


def test_an_undeclared_path_dependent_kernel_refuses(registry_and_config):
    registry, config = registry_and_config
    kernel = registry.by_output("ret_autocorr_1")
    bare = dataclasses.replace(kernel, definition=None)
    with pytest.raises(KernelRegistryError, match="memory_anchor"):
        registry._definition(bare, config, "5m", "ret_autocorr_1")


def test_definitions_compose_the_inputs_definitions_not_their_memory(registry_and_config):
    """prior_session_high_dist_atr reads the ATR: it is defined once one session completes and
    the ATR exists (row adx_period), never after the ATR's Wilder seed-independence memory."""
    registry, config = registry_and_config
    atr_memory = registry.effective_memory_bars("atr_wilder", config)
    first = stored_first_row(registry, "prior_session_high_dist_atr", config, "1d")
    assert first < atr_memory
    # max (a path-dependent definition is absolute), not a sum: two sessions bound it on 1d
    assert first == max(2 * bars_per_session(config, "1d"), config.adx_period)
    # a product of adx is held to adx's definition, not hma_slope_z's (one kernel emits both)
    adx = registry.definition_warmup("adx", config, "5m")
    assert registry.definition_warmup("hma_slope_z", config, "5m") > adx
    product = registry.definition_warmup("momentum_trend_product", config, "5m")
    assert product == max(adx, registry.definition_warmup("momentum_z_fast", config, "5m"))


def test_a_masked_column_is_stored_from_its_memory(registry_and_config):
    registry, config = registry_and_config
    atr_z = stored_first_row(registry, "atr_z", config, "5m")
    assert atr_z == registry.effective_memory_bars("atr_z", config)


def test_object_dependence_is_declared_with_a_presence_mask(registry_and_config):
    registry, _config = registry_and_config
    declared = registry.object_dependent_outputs()
    for column in (
        "nearest_hvn_dist_atr",
        "in_lvn",
        "distance_to_vah_atr",
        "opening_gap_pct",
        "sr_support_dist",
        "fvg_dist_atr",
        "swing_high_dist_atr",
        "bars_since_vol_spike_fast",
        "bars_since_extreme_move_slow",
    ):
        assert column in declared, column
        assert f"_{column}_is_none" in registry.by_output(column).outputs, column
    zero_state = {o for k in registry.kernels for o in k.zero_is_state}
    assert not declared & zero_state
    for column in ("momentum_z_fast", "adx", "poc_rolling_dist_atr", "prior_session_high_dist_atr"):
        assert column not in declared, column


def _session_bars(n: int, seed: int = 7) -> dict[str, np.ndarray]:
    """A healthy 5m series inside NYSE regular sessions (14:30 to 21:00 UTC, weekdays): a
    random walk with volume and an overnight gap at each session open, every bar real."""
    rng = np.random.default_rng(seed)
    stamps: list[datetime] = []
    day = datetime(2023, 1, 3, tzinfo=UTC)
    while len(stamps) < n:
        if day.weekday() < 5:
            open_ = day.replace(hour=14, minute=30)
            stamps += [open_ + timedelta(minutes=5 * i) for i in range(78)]
        day += timedelta(days=1)
    stamps = stamps[:n]
    steps = rng.normal(0, 0.002, n)
    session_open = np.array([t.hour == 14 and t.minute == 30 for t in stamps])
    steps[session_open] += rng.normal(0, 0.006, int(session_open.sum()))
    close = 100 * np.exp(np.cumsum(steps))
    # every bar opens near the prior close (real prints), the session open with the gap
    opens = np.r_[close[0], close[:-1]] * np.exp(
        np.where(session_open, steps * 0.5, rng.normal(0, 0.0003, n))
    )
    spread = np.abs(rng.normal(0, 0.001, n)) * close
    return {
        "ts": np.array([int(t.timestamp() * 1e9) for t in stamps], dtype=np.int64),
        "open": opens,
        "high": np.maximum(close, opens) + spread,
        "low": np.minimum(close, opens) - spread,
        "close": close,
        "volume": rng.integers(1_000, 50_000, n).astype(float),
        "volume_basis": constant_volume_basis(n),
        "symbol": np.array(["TEST"] * n, dtype=object),
        "tf": np.array(["5m"] * n, dtype=object),
    }


def _anchor(registry, column) -> str:
    return registry.anchor_of(column) or ANCHOR_SERIES_START


def _boundary_row(stamps: np.ndarray, anchor: str, periods: int) -> int:
    """The first row after `periods` anchor boundaries of the series (a session open, or the
    first bar of an ISO week): where an output needing that many complete periods first exists
    on a series that starts at a period's first bar."""
    times = [datetime.fromtimestamp(t / 1e9, tz=UTC) for t in stamps]
    key = (lambda t: t.date()) if anchor == ANCHOR_SESSION_OPEN else (lambda t: t.isocalendar()[:2])
    seen, boundaries = key(times[0]), 0
    for i, t in enumerate(times):
        if key(t) != seen:
            seen, boundaries = key(t), boundaries + 1
            if boundaries == periods:
                return i
    raise AssertionError("the series holds too few periods")


@pytest.mark.parametrize("seed", [7, 11])
def test_every_column_is_first_stored_at_its_declared_row_on_healthy_bars(
    registry_and_config, seed
):
    """Through the writer's own masking (_compute_series_columns): a series-start-anchored
    column's first stored finite row is within TOLERANCE of stored_first_row in both directions;
    a session- or week-anchored one lies within one anchor period below its declaration (the
    declaration covers a series starting anywhere in a period). The HMM is judged on its refit
    boundaries below; object and event columns by their unit_stats; columns reading external
    series (all NaN here) are not judged."""
    registry, config = registry_and_config
    n = 2400
    inputs = _session_bars(n, seed)
    for ext in registry.external_inputs:
        inputs.setdefault(ext.name, np.full(n, np.nan))
    series = _compute_series_columns(inputs, config, registry)
    names = feature_vectors_numeric_columns()
    objects = registry.object_dependent_outputs()
    externals = {ext.name for ext in registry.external_inputs}
    period = {
        ANCHOR_SESSION_OPEN: bars_per_session(config, "5m"),
        ANCHOR_WEEK_OPEN: 5 * bars_per_session(config, "5m"),
    }
    off, judged = [], 0
    for j, column in enumerate(names):
        kernel = registry.by_output(column)
        if column not in registry.applicable_outputs("5m") or column in objects:
            continue
        if kernel.origin == "regime" or any(
            set(k.inputs) & externals for k in (kernel, *registry._upstream(kernel))
        ):
            continue
        finite = np.flatnonzero(np.isfinite(series.numeric[:, j]))
        declared = stored_first_row(registry, column, config, "5m")
        if not len(finite):
            off.append((column, None, declared))
            continue
        first, anchor = int(finite[0]), _anchor(registry, column)
        judged += 1
        periods = kernel.anchor_periods.get(column)
        if anchor == ANCHOR_SERIES_START or periods == 0:
            ok = abs(first - declared) <= TOLERANCE
        elif periods is None:
            ok = first <= declared + TOLERANCE  # anchored through an input: the bound only
        else:
            # exact on this series (it starts at a session's first bar), and never past the
            # declaration, which bounds a series starting anywhere in a period
            expected = _boundary_row(inputs["ts"], anchor, periods)
            ok = abs(first - expected) <= TOLERANCE and first <= declared + TOLERANCE
            assert declared <= (periods + 1) * period[anchor] + declared, column
        if not ok:
            off.append((column, first, declared))
    assert judged > 150
    assert off == [], "\n".join(map(str, off))


def test_the_hmm_first_label_falls_on_a_refit_boundary_at_or_after_its_declared_row():
    """The HMM's definition is its first refit boundary (valid_start + 1 + the boundary in
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
        declared = registry.definition_warmup(column, config, "1d")
        assert finite[0] >= declared and (finite[0] - declared) % refit == 0, (column, finite[0])
        judged += 1
    assert judged
