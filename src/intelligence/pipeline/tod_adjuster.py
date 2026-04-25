"""Time-of-Day Adjuster pipeline stage — pure function.

Applies Bayesian TOD win-rate multipliers to signal confidence.
No Kafka, no DB, no service dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.ml.transform_recorder import TransformRecorder

# TOD session priors — mirrored from signal_generator_service.py
# Key: (regime_type, hour_et) → prior win-rate ratio (>1.0 = favourable, <1.0 = avoid)
_TOD_SESSION_PRIORS: dict[tuple[str, int], float] = {
    ("trend", 9): 1.10,
    ("mean_reversion", 9): 1.00,
    ("any", 9): 1.00,
    ("trend", 11): 0.90,
    ("mean_reversion", 11): 0.90,
    ("any", 11): 0.90,
    ("trend", 12): 0.90,
    ("mean_reversion", 12): 0.90,
    ("any", 12): 0.90,
    ("mean_reversion", 14): 1.08,
    ("any", 15): 1.10,
}

_TOD_ALPHA: float = 20.0  # Bayesian prior weight (virtual observations)
_TOD_CLAMP: tuple[float, float] = (0.7, 1.3)  # Hard multiplier bounds


async def apply_tod_adjustment(
    signals: list[dict],
    tod_table: dict[tuple[str, str, int, str], float],
    tf: str,
    hour_et: int,
    symbol: str = "*",
    recorder: TransformRecorder | None = None,
) -> list[dict]:
    """Apply TOD multiplier to all signals.

    Parameters
    ----------
    signals:
        List of signal dicts. Each may have "regime_type_at_fire" and "confidence".
    tod_table:
        Dict keyed by (regime_type, tf, hour_et, symbol) → multiplier float.
        Loaded from DB by the caller. Empty dict falls back to session priors.
        symbol='*' is the global sentinel (cross-instrument aggregate).
    tf:
        Current timeframe string (e.g. "1m").
    hour_et:
        Current ET hour of the bar (0-23).
    symbol:
        Instrument symbol for per-symbol lookup (e.g. "ES", "NQ").
        Falls back to global '*' sentinel when no symbol-specific row exists.
        Default '*' preserves backward compatibility with call sites that omit it.
    recorder:
        Optional TransformRecorder. When provided, emits one tod record per signal.
        When None, behavior is unchanged.

    Lookup hierarchy:
        1. (regime_type, tf, hour_et, symbol)  -- symbol-specific
        2. (regime_type, tf, hour_et, '*')      -- global sentinel
        3. _TOD_SESSION_PRIORS[(regime_type, hour_et)]  -- hardcoded prior
        4. 1.0 -- neutral fallback

    Returns
    -------
    list[dict]
        Copies of input signals with updated "confidence" and "tod_multiplier" set.
        Input dicts are never mutated.
    """
    result = []

    for sig in signals:
        s = dict(sig)
        before = float(s.get("confidence", 0.0))
        regime_type = s.get("regime_type_at_fire", "any")

        # 2-level DB lookup, then session priors
        specific_key = (regime_type, tf, hour_et, symbol)
        global_key = (regime_type, tf, hour_et, "*")
        tod_multiplier = tod_table.get(specific_key) or tod_table.get(global_key)

        if tod_multiplier is None:
            # Fall back to session priors
            tod_multiplier = _TOD_SESSION_PRIORS.get((regime_type, hour_et), 1.0)

        # Clamp to prevent extreme adjustments
        tod_multiplier = max(_TOD_CLAMP[0], min(_TOD_CLAMP[1], tod_multiplier))

        s["confidence"] = round(before * tod_multiplier, 4)
        s["tod_multiplier"] = tod_multiplier

        if recorder is not None and s.get("signal_id"):
            seg = f"{s.get('regime_type', 'any')}.{tf}.{hour_et}"
            await recorder.record(
                signal_id=s["signal_id"],
                transform_id="tod",
                dag_order=3,
                multiplier=tod_multiplier,
                segment_key=seg,
                metadata={"tod_multiplier": tod_multiplier, "hour_et": hour_et},
            )

        result.append(s)

    return result
