"""Ranker pipeline stage — pure function.

Computes adjusted_rank = SETUP_PRIORITY * perf_multiplier for each signal.
No Kafka, no DB, no service dependencies.
"""

from __future__ import annotations

from src.intelligence.trading.aggregator import SETUP_PRIORITY


def rank_signals(
    signals: list[dict],
    perf_weights: dict[tuple[str, str, str], float],
    tf: str,
    symbol: str = "*",
) -> list[dict]:
    """Compute adjusted_rank for all signals.

    Parameters
    ----------
    signals:
        List of signal dicts. Each must have "setup_plugin".
    perf_weights:
        Dict keyed by (plugin_name, tf, symbol) → perf_multiplier float.
        Loaded from setup_performance table by the caller.
        Missing entries default to 1.0 (neutral).
        symbol='*' is the global sentinel (cross-instrument aggregate).
    tf:
        Current timeframe string (e.g. "1m").
    symbol:
        Instrument symbol for per-symbol lookup (e.g. "ES", "NQ").
        Falls back to global '*' sentinel. Default '*' for backward compatibility.

    Lookup hierarchy:
        1. (plugin_name, tf, symbol)  -- symbol-specific
        2. (plugin_name, tf, '*')     -- global sentinel
        3. 1.0                        -- neutral fallback

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
        _key_specific = (plugin_name, tf, symbol)
        _key_global = (plugin_name, tf, "*")
        perf_multiplier = perf_weights.get(_key_specific, perf_weights.get(_key_global, 1.0))
        adjusted_rank = round(priority * perf_multiplier, 4)

        s["adjusted_rank"] = adjusted_rank
        s["perf_multiplier"] = perf_multiplier
        result.append(s)

    return result
