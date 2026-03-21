"""Ranker pipeline stage — pure function.

Computes adjusted_rank = SETUP_PRIORITY * perf_multiplier for each signal.
No Kafka, no DB, no service dependencies.
"""

from __future__ import annotations

from src.intelligence.trading.aggregator import SETUP_PRIORITY


def rank_signals(
    signals: list[dict],
    perf_weights: dict[tuple[str, str], float],
    tf: str,
) -> list[dict]:
    """Compute adjusted_rank for all signals.

    Parameters
    ----------
    signals:
        List of signal dicts. Each must have "setup_plugin".
    perf_weights:
        Dict keyed by (plugin_name, tf) → perf_multiplier float.
        Loaded from setup_performance table by the caller.
        Missing entries default to 1.0 (neutral).
    tf:
        Current timeframe string (e.g. "1m").

    Returns
    -------
    list[dict]
        Copies of input signals with "adjusted_rank" and "perf_multiplier" set.
        Lower adjusted_rank = higher priority in WinnerSelector sort.
        Input dicts are never mutated.
    """
    result = []

    for sig in signals:
        s = dict(sig)
        plugin_name = s.get("setup_plugin", "unknown")

        priority = SETUP_PRIORITY.get(plugin_name, 999)
        perf_multiplier = perf_weights.get((plugin_name, tf), 1.0)
        adjusted_rank = round(priority * perf_multiplier, 4)

        s["adjusted_rank"] = adjusted_rank
        s["perf_multiplier"] = perf_multiplier
        result.append(s)

    return result
