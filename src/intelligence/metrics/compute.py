# src/intelligence/metrics/compute.py
"""Pure compute functions for signal performance metrics.

No I/O. Called by SignalMetricsAnalyzer after data quality validation.
Two tracks: 'zone' (structural setup quality) and 'market' (tradeable alpha).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from scipy.stats import kurtosis as _scipy_kurtosis
from scipy.stats import skew as _scipy_skew
from scipy.stats import t as _scipy_t

from src.intelligence.metrics.validator import validate_signal_row
from src.intelligence.ml.information_coefficient import (
    IC_MIN_SAMPLE_SIZE,
    compute_ic,
    is_ic_significant,
)
from src.intelligence.trading.signal_outcome import WIN_OUTCOMES

# Minimum N gate — FEED-02: setups with fewer samples use multiplier=1.0 (neutral)
MIN_SAMPLE_SIZE: int = 30

# Rolling windows to compute metrics for
WINDOWS: tuple[int, ...] = (7, 30, 90)

# HMM regime integer -> regime_type label in signal_metrics
# 0 = ranging market (mean-reversion conditions)
# 1 = uptrend, 2 = downtrend (both are 'trend' for metric segmentation)
HMM_TO_REGIME: dict[int, str] = {
    0: "mean_reversion",
    1: "trend",
    2: "trend",
}


@dataclass
class DistributionShape:
    """Distribution shape metrics derived from pnl_rs list."""

    skewness: float | None
    kurtosis: float | None
    min_r: float | None
    p5_r: float | None
    recovery_factor: float | None
    cvar_5: float | None


def _distribution_shape(pnl_rs: list[float], avg_mfe: float) -> DistributionShape:
    """Compute distribution shape metrics from a list of pnl_r values.

    Threshold gates (CONTEXT.md D-01/D-02):
      skewness, kurtosis: NULL when n < 3
      p5_r, cvar_5:       NULL when n < 20
      min_r:              NULL when n < 30
      recovery_factor:    NULL when n < 20 or p5_r >= -1e-9 (no real tail loss)

    CRITICAL: recovery_factor uses strict `p5 < -1e-9` (NOT abs()) per D-01.
    Positive or near-zero p5 means no tail loss exists — ratio is undefined.
    """
    from statistics import mean as _mean

    n = len(pnl_rs)

    # skewness and kurtosis: require n >= 3
    if n >= 3:
        skewness: float | None = round(float(_scipy_skew(pnl_rs, bias=False)), 4)
        kurtosis: float | None = round(float(_scipy_kurtosis(pnl_rs, fisher=True, bias=False)), 4)
    else:
        skewness = None
        kurtosis = None

    # min_r: require n >= 30
    min_r: float | None = round(min(pnl_rs), 4) if n >= 30 else None

    # p5_r, cvar_5, recovery_factor: require n >= 20
    if n >= 20:
        p5 = float(np.percentile(pnl_rs, 5))
        p5_r: float | None = round(p5, 4)
        tail = [r for r in pnl_rs if r < p5]
        cvar_5: float | None = round(_mean(tail), 4) if tail else None
        # STRICT `<` per CONTEXT.md D-01: positive/zero p5 means no tail loss -> undefined ratio
        recovery_factor: float | None = round(avg_mfe / abs(p5), 4) if p5 < -1e-9 else None
    else:
        p5_r = None
        cvar_5 = None
        recovery_factor = None

    return DistributionShape(
        skewness=skewness,
        kurtosis=kurtosis,
        min_r=min_r,
        p5_r=p5_r,
        recovery_factor=recovery_factor,
        cvar_5=cvar_5,
    )


@dataclass
class SignalMetricsResult:
    track: str
    setup_plugin: str
    tf: str
    regime_type: str
    window_days: int
    symbol: str  # '*' = global sentinel (cross-instrument aggregate)
    entry_type: str  # '*' = global sentinel (all entry types aggregated)
    n: int
    n_outliers: int
    never_activated_pct: float | None
    win_rate: float | None
    avg_r: float | None
    std_r: float | None
    sharpe: float | None
    p_value: float | None
    avg_mae: float | None
    avg_mfe: float | None
    skewness: float | None
    kurtosis: float | None
    min_r: float | None
    p5_r: float | None
    recovery_factor: float | None
    cvar_5: float | None
    computed_at: datetime


# Row alias for backward compatibility with plan references
SignalMetricsRow = SignalMetricsResult


@dataclass
class ICMetricsResult:
    setup_plugin: str
    tf: str
    regime_type: str
    window_days: int
    n: int
    ic: float | None
    p_value: float | None
    is_significant: bool
    computed_at: datetime


# Row alias for backward compatibility with plan references
ICMetricsRow = ICMetricsResult


def _p_value(avg_r: float, std_r: float, n: int) -> float | None:
    """Two-sided one-sample t-test: H0 = avg_r == 0."""
    if n < 2 or std_r < 1e-9 or math.isnan(std_r):
        return None
    t_stat = avg_r / (std_r / math.sqrt(n))
    return float(_scipy_t.sf(abs(t_stat), df=n - 1) * 2)


def _build_metrics_result(
    acc: dict,
    track: str,
    setup_plugin: str,
    tf: str,
    regime_type: str,
    window_days: int,
    symbol: str = "*",
    entry_type: str = "*",
) -> SignalMetricsResult:
    """Compute statistics from an accumulated group dict and return a SignalMetricsResult."""
    pnl_rs = acc["pnl_rs"]
    maes = acc["maes"]
    mfes = acc["mfes"]
    win_flags = acc["win_flags"]
    n_never_activated = acc["n_never_activated"]
    n_total = acc["n_total"]
    n_outliers = acc["n_outliers"]

    n = len(pnl_rs)
    now = datetime.now(UTC)
    never_act_pct = round(n_never_activated / n_total, 4) if n_total > 0 else None

    if n == 0:
        return SignalMetricsResult(
            track=track,
            setup_plugin=setup_plugin,
            tf=tf,
            regime_type=regime_type,
            window_days=window_days,
            symbol=symbol,
            entry_type=entry_type,
            n=0,
            n_outliers=n_outliers,
            never_activated_pct=never_act_pct,
            win_rate=None,
            avg_r=None,
            std_r=None,
            sharpe=None,
            p_value=None,
            avg_mae=None,
            avg_mfe=None,
            skewness=None,
            kurtosis=None,
            min_r=None,
            p5_r=None,
            recovery_factor=None,
            cvar_5=None,
            computed_at=now,
        )

    avg_r = sum(pnl_rs) / n
    variance = sum((r - avg_r) ** 2 for r in pnl_rs) / (n - 1) if n > 1 else 0.0
    std_r = math.sqrt(variance) if variance > 0 else 0.0
    sharpe = round(avg_r / std_r, 4) if std_r > 1e-9 else None
    p_val = _p_value(avg_r, std_r, n)
    win_rate = sum(1 for w in win_flags if w) / len(win_flags) if win_flags else None
    avg_mae = sum(maes) / len(maes) if maes else None
    avg_mfe = sum(mfes) / len(mfes) if mfes else None

    shape = _distribution_shape(pnl_rs, avg_mfe or 0.0)

    return SignalMetricsResult(
        track=track,
        setup_plugin=setup_plugin,
        tf=tf,
        regime_type=regime_type,
        window_days=window_days,
        symbol=symbol,
        entry_type=entry_type,
        n=n,
        n_outliers=n_outliers,
        never_activated_pct=never_act_pct,
        win_rate=round(win_rate, 4) if win_rate is not None else None,
        avg_r=round(avg_r, 4),
        std_r=round(std_r, 4),
        sharpe=sharpe,
        p_value=round(p_val, 4) if p_val is not None else None,
        avg_mae=round(avg_mae, 4) if avg_mae is not None else None,
        avg_mfe=round(avg_mfe, 4) if avg_mfe is not None else None,
        skewness=shape.skewness,
        kurtosis=shape.kurtosis,
        min_r=shape.min_r,
        p5_r=shape.p5_r,
        recovery_factor=shape.recovery_factor,
        cvar_5=shape.cvar_5,
        computed_at=now,
    )


def _empty_acc() -> dict:
    return {
        "pnl_rs": [],
        "maes": [],
        "mfes": [],
        "win_flags": [],
        "n_never_activated": 0,
        "n_total": 0,
        "n_outliers": 0,
    }


def compute_signal_metrics(
    rows: list[dict],
    track: str,
    window_days: int,
    tick_sizes: dict[str, float] | None = None,
) -> list[SignalMetricsResult]:
    """Compute per-segment metrics for one track and window.

    Applies DataQualityValidator to each row. Invalid rows increment
    n_outliers and are excluded from avg_r/win_rate/sharpe.
    NULL pnl_r (zone never activated) counts toward never_activated_pct.

    Returns one SignalMetricsResult per (setup_plugin, tf, regime_type, symbol) group
    with n >= MIN_SAMPLE_SIZE, plus an 'all' rollup row per (setup, tf, symbol), and
    per-entry_type rows (symbol='*') gated at n >= 30.

    Args:
        rows:       list of signal_ledger row dicts (already fetched from DB)
        track:      'zone' or 'market'
        window_days: rolling window (7, 30, or 90)
        tick_sizes: dict mapping base symbol → minimum tick size
    """
    # Per-regime accumulators keyed by (plugin, tf, regime_label, symbol)
    regime_accs: dict[tuple, dict] = defaultdict(_empty_acc)
    # Rollup accumulators keyed by (plugin, tf, symbol)
    all_accs: dict[tuple, dict] = defaultdict(_empty_acc)
    # Per-entry_type accumulators keyed by (plugin, tf, regime_label, entry_type)
    # NULL entry_type rows fold into global only — NOT accumulated here (D-10 / threat_model)
    by_entry_type: dict[tuple, dict] = defaultdict(_empty_acc)

    for row in rows:
        plugin = row.get("setup_plugin")
        tf_val = row.get("tf") or row.get("timeframe")
        hmm = row.get("hmm_regime_at_fire")
        if not plugin or not tf_val:
            continue

        symbol_val = row.get("symbol") or "*"

        # entry_type: NULL/empty folds to global only; unknown literals pass through unchanged
        entry_type_raw = row.get("entry_type")
        entry_type_val = entry_type_raw or None

        if track == "zone":
            pnl_r = row.get("pnl_r")
            mae = row.get("mae")
            mfe = row.get("mfe")
            outcome = row.get("outcome")
        else:  # market
            pnl_r = row.get("market_entry_pnl_r")
            mae = row.get("market_entry_mae")
            mfe = row.get("market_entry_mfe")
            outcome = row.get("market_entry_outcome")

        regime_label = HMM_TO_REGIME.get(hmm) if hmm is not None else None
        if not regime_label:
            continue

        regime_key = (plugin, tf_val, regime_label, symbol_val)
        all_key = (plugin, tf_val, symbol_val)

        for acc in (regime_accs[regime_key], all_accs[all_key]):
            acc["n_total"] += 1

        if pnl_r is None:
            for acc in (regime_accs[regime_key], all_accs[all_key]):
                acc["n_never_activated"] += 1
            continue

        vr = validate_signal_row(
            direction=row.get("direction"),
            entry_price=row.get("entry_price"),
            stop_loss=row.get("stop_loss"),
            pnl_r=pnl_r,
            hmm_regime_at_fire=hmm,
            symbol=row.get("symbol"),
            tick_sizes=tick_sizes,
        )
        if not vr.is_valid:
            for acc in (regime_accs[regime_key], all_accs[all_key]):
                acc["n_outliers"] += 1
            continue

        for acc in (regime_accs[regime_key], all_accs[all_key]):
            acc["pnl_rs"].append(float(pnl_r))
            if mae is not None:
                acc["maes"].append(float(mae))
            if mfe is not None:
                acc["mfes"].append(float(mfe))
            acc["win_flags"].append(outcome in WIN_OUTCOMES)

        # No whitelist — unknown entry_type literals flow to their own accumulator key
        if entry_type_val is not None:
            et_key = (plugin, tf_val, regime_label, entry_type_val)
            et_acc = by_entry_type[et_key]
            et_acc["n_total"] += 1
            et_acc["pnl_rs"].append(float(pnl_r))
            if mae is not None:
                et_acc["maes"].append(float(mae))
            if mfe is not None:
                et_acc["mfes"].append(float(mfe))
            et_acc["win_flags"].append(outcome in WIN_OUTCOMES)

    result: list[SignalMetricsResult] = []

    for (plugin, tf_val, regime_label, sym), acc in regime_accs.items():
        if len(acc["pnl_rs"]) < MIN_SAMPLE_SIZE:
            continue
        result.append(
            _build_metrics_result(
                acc,
                track,
                plugin,
                tf_val,
                regime_label,
                window_days,
                symbol=sym,
                entry_type="*",
            )
        )

    for (plugin, tf_val, sym), acc in all_accs.items():
        if len(acc["pnl_rs"]) < MIN_SAMPLE_SIZE:
            continue
        result.append(
            _build_metrics_result(
                acc,
                track,
                plugin,
                tf_val,
                "all",
                window_days,
                symbol=sym,
                entry_type="*",
            )
        )

    # Per-entry_type result emission: symbol='*', entry_type=actual value, gated at n >= 30
    for (plugin, tf_val, regime_label, et_val), acc in by_entry_type.items():
        if len(acc["pnl_rs"]) < 30:
            continue
        result.append(
            _build_metrics_result(
                acc,
                track,
                plugin,
                tf_val,
                regime_label,
                window_days,
                symbol="*",
                entry_type=et_val,
            )
        )

    return result


def compute_ic_metrics(
    rows: list[dict],
    window_days: int,
) -> list[ICMetricsResult]:
    """Compute IC per (setup_plugin, tf, regime_type) group.

    Uses src.intelligence.ml.information_coefficient.compute_ic().
    Returns rows with n >= IC_MIN_SAMPLE_SIZE (30).
    Also emits 'all' regime rollup per (setup, tf).

    Args:
        rows:       signal_ledger row dicts with 'confidence' and 'outcome' fields
        window_days: rolling window
    """
    # Per-regime IC accumulators keyed by (plugin, tf, regime_label)
    ic_accs: dict[tuple, tuple[list, list, list]] = defaultdict(lambda: ([], [], []))
    # Rollup IC accumulators keyed by (plugin, tf)
    all_ic_accs: dict[tuple, tuple[list, list, list]] = defaultdict(lambda: ([], [], []))

    for row in rows:
        plugin = row.get("setup_plugin")
        tf_val = row.get("tf") or row.get("timeframe")
        hmm = row.get("hmm_regime_at_fire")
        conf = row.get("confidence")
        outcome = row.get("outcome")
        pnl_r = row.get("pnl_r")  # None for never_activated

        if not plugin or not tf_val or conf is None or outcome is None:
            continue

        regime_label = HMM_TO_REGIME.get(hmm) if hmm is not None else None
        if not regime_label:
            continue

        ic_accs[(plugin, tf_val, regime_label)][0].append(float(conf))
        ic_accs[(plugin, tf_val, regime_label)][1].append(outcome)
        ic_accs[(plugin, tf_val, regime_label)][2].append(pnl_r)
        all_ic_accs[(plugin, tf_val)][0].append(float(conf))
        all_ic_accs[(plugin, tf_val)][1].append(outcome)
        all_ic_accs[(plugin, tf_val)][2].append(pnl_r)

    result: list[ICMetricsResult] = []
    now = datetime.now(UTC)

    def _make_ic_result(
        plugin: str,
        tf_val: str,
        regime_label: str,
        confs: list[float],
        outcomes: list[str],
        pnl_rs: list[float | None],
    ) -> ICMetricsResult | None:
        ic_score, p_val, n_used = compute_ic(confs, pnl_rs)
        if n_used < IC_MIN_SAMPLE_SIZE:
            return None
        sig = is_ic_significant(ic_score, p_val, n_used)
        return ICMetricsResult(
            setup_plugin=plugin,
            tf=tf_val,
            regime_type=regime_label,
            window_days=window_days,
            n=n_used,
            ic=round(ic_score, 4) if ic_score is not None else None,
            p_value=round(p_val, 4) if p_val is not None else None,
            is_significant=sig,
            computed_at=now,
        )

    for (plugin, tf_val, regime_label), (confs, outcomes, pnl_rs) in ic_accs.items():
        r = _make_ic_result(plugin, tf_val, regime_label, confs, outcomes, pnl_rs)
        if r:
            result.append(r)

    for (plugin, tf_val), (confs, outcomes, pnl_rs) in all_ic_accs.items():
        r = _make_ic_result(plugin, tf_val, "all", confs, outcomes, pnl_rs)
        if r:
            result.append(r)

    return result
