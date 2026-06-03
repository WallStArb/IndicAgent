"""Ranker pipeline stage — pure function.

Phase 112 D-16: Data-driven ranking. adjusted_rank = perf_multiplier.
- Setups with sample_size >= 100: adjusted_rank = perf_multiplier from Sharpe rank [0.5, 1.5]
- Setups with sample_size < 30 (unvalidated): adjusted_rank = 0.5 (warm-up penalty, D-16)
  Below-neutral ranking ensures unvalidated setups do not out-rank validated ones.

No SETUP_PRIORITY: priority dict removed (2-C). Ranking is fully data-driven.
No Kafka, no DB, no service dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.ml.transform_recorder import TransformRecorder

# Minimum 100 samples required; values below 200 are statistically unreliable on fat-tailed returns
# Warm-up penalty for setups with sample_size < 100 (D-16).
# Below 0.5 so unvalidated setups rank below the lowest eligible multiplier (0.5).
WARMUP_PENALTY_MULTIPLIER: float = 0.5


async def rank_signals(
    signals: list[dict],
    perf_weights: dict[tuple[str, str, str], float | tuple[float, int]],
    tf: str,
    symbol: str = "*",
    recorder: TransformRecorder | None = None,
) -> list[dict]:
    """Compute adjusted_rank for all signals.

    adjusted_rank = perf_multiplier (data-driven; no SETUP_PRIORITY factor).

    Warm-up penalty (D-16): setups with sample_size < 30 get perf_multiplier = 0.5,
    placing them below the lowest ranked validated setup.

    Parameters
    ----------
    signals:
        List of signal dicts. Each must have "setup_plugin".
    perf_weights:
        Dict keyed by (plugin_name, tf, symbol) → perf_multiplier float OR
        (perf_multiplier: float, sample_size: int) tuple.
        Loaded from setup_performance table by the caller.
        Missing entries: neutral fallback (1.0) with sample_size=0 → warm-up penalty.
        symbol='*' is the global sentinel (cross-instrument aggregate).
    tf:
        Current timeframe string (e.g. "1m").
    symbol:
        Instrument symbol for per-symbol lookup (e.g. "ES", "NQ").
        Falls back to global '*' sentinel. Default '*' for backward compatibility.
    recorder:
        Optional TransformRecorder. When provided, emits one perf_weight record
        per signal. When None, behavior is unchanged.

    Lookup hierarchy:
        1. (plugin_name, tf, symbol)  -- symbol-specific
        2. (plugin_name, tf, '*')     -- global sentinel
        3. warm-up penalty 0.5        -- sample_size < 30 fallback

    Returns
    -------
    list[dict]
        Copies of input signals with "adjusted_rank", "perf_multiplier", and
        "sample_size" set. Lower adjusted_rank = higher priority under ascending sort.
        Input dicts are never mutated.
    """
    result = []

    for sig in signals:
        s = dict(sig)
        plugin_name = s.get("setup_plugin", "unknown")

        _key_specific = (plugin_name, tf, symbol)
        _key_global = (plugin_name, tf, "*")
        raw_entry = perf_weights.get(_key_specific, perf_weights.get(_key_global))

        # Unpack (perf_multiplier, sample_size) tuple or plain float
        if raw_entry is None:
            # No perf data: apply warm-up penalty (treated as sample_size=0)
            perf_multiplier = WARMUP_PENALTY_MULTIPLIER
            sample_size = 0
        elif isinstance(raw_entry, tuple):
            perf_multiplier, sample_size = raw_entry
        else:
            # Plain float (backward compat with old callers that don't include sample_size)
            perf_multiplier = float(raw_entry)
            sample_size = 100  # assume validated if caller provides plain float

        # Minimum 100 samples required; values below 200 are statistically unreliable on fat-tailed returns
        # D-16 warm-up penalty: force 0.5 for sample_size < 100
        if sample_size < 100:
            perf_multiplier = WARMUP_PENALTY_MULTIPLIER

        adjusted_rank = round(perf_multiplier, 4)

        s["adjusted_rank"] = adjusted_rank
        s["perf_multiplier"] = perf_multiplier
        s["sample_size"] = sample_size

        if recorder is not None and s.get("signal_id"):
            seg = f"{plugin_name}.{tf}"
            await recorder.record(
                signal_id=s["signal_id"],
                transform_id="perf_weight",
                dag_order=5,
                multiplier=perf_multiplier,
                segment_key=seg,
                metadata={"perf_multiplier": perf_multiplier, "sample_size": sample_size},
            )

        result.append(s)

    return result
