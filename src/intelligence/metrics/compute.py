# src/intelligence/metrics/compute.py
"""Pure compute functions for signal performance metrics.

No I/O. Called by SignalMetricsComputeAgent after data quality validation.
Two tracks: 'zone' (structural setup quality) and 'market' (tradeable alpha).
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

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
class SignalMetricsResult:
    track: str
    setup_plugin: str
    tf: str
    regime_type: str
    window_days: int
    symbol: str  # '*' = global sentinel (cross-instrument aggregate)
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
            track=track, setup_plugin=setup_plugin, tf=tf,
            regime_type=regime_type, window_days=window_days, symbol=symbol,
            n=0, n_outliers=n_outliers,
            never_activated_pct=never_act_pct,
            win_rate=None, avg_r=None, std_r=None, sharpe=None,
            p_value=None, avg_mae=None, avg_mfe=None, computed_at=now,
        )

    avg_r = sum(pnl_rs) / n
    variance = sum((r - avg_r) ** 2 for r in pnl_rs) / (n - 1) if n > 1 else 0.0
    std_r = math.sqrt(variance) if variance > 0 else 0.0
    sharpe = round(avg_r / std_r, 4) if std_r > 1e-9 else None
    p_val = _p_value(avg_r, std_r, n)
    win_rate = sum(1 for w in win_flags if w) / len(win_flags) if win_flags else None
    avg_mae = sum(maes) / len(maes) if maes else None
    avg_mfe = sum(mfes) / len(mfes) if mfes else None

    return SignalMetricsResult(
        track=track, setup_plugin=setup_plugin, tf=tf,
        regime_type=regime_type, window_days=window_days, symbol=symbol,
        n=n, n_outliers=n_outliers,
        never_activated_pct=never_act_pct,
        win_rate=round(win_rate, 4) if win_rate is not None else None,
        avg_r=round(avg_r, 4),
        std_r=round(std_r, 4),
        sharpe=sharpe,
        p_value=round(p_val, 4) if p_val is not None else None,
        avg_mae=round(avg_mae, 4) if avg_mae is not None else None,
        avg_mfe=round(avg_mfe, 4) if avg_mfe is not None else None,
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
    with n >= MIN_SAMPLE_SIZE, plus an 'all' rollup row per (setup, tf, symbol).

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

    for row in rows:
        plugin = row.get("setup_plugin")
        tf_val = row.get("tf") or row.get("timeframe")
        hmm = row.get("hmm_regime_at_fire")
        if not plugin or not tf_val:
            continue

        symbol_val = row.get("symbol") or "*"

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

    result: list[SignalMetricsResult] = []

    for (plugin, tf_val, regime_label, sym), acc in regime_accs.items():
        if len(acc["pnl_rs"]) < MIN_SAMPLE_SIZE:
            continue
        result.append(_build_metrics_result(acc, track, plugin, tf_val, regime_label, window_days, symbol=sym))

    for (plugin, tf_val, sym), acc in all_accs.items():
        if len(acc["pnl_rs"]) < MIN_SAMPLE_SIZE:
            continue
        result.append(_build_metrics_result(acc, track, plugin, tf_val, "all", window_days, symbol=sym))

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
