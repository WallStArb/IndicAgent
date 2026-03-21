"""Regime Gate pipeline stage — pure function.

Applies HMM regime compatibility check to signals.
No Kafka, no DB, no service dependencies.
"""

from __future__ import annotations

from src.intelligence.trading.aggregator import (
    _REGIME_DUR_MIN,
    _REGIME_MAP,
    _REGIME_PROB_MIN,
)


def apply_regime_gate(
    signals: list[dict],
    regime_data: dict | None,
) -> list[dict]:
    """Apply regime gating to all signals.

    Parameters
    ----------
    signals:
        List of signal dicts. Each may have a "regime_type" key.
    regime_data:
        Dict with HMM regime info, or None for graceful degradation.
        Expected keys: "hmm_regime", "hmm_regime_prob", "hmm_regime_duration".

    Returns
    -------
    list[dict]
        Copies of input signals with "regime_eligible" and "suppression_reason" set.
        Input dicts are never mutated.
    """
    result = []

    if regime_data is None:
        # No regime data → pass all through (graceful degradation)
        for sig in signals:
            s = dict(sig)
            s["regime_eligible"] = True
            s["suppression_reason"] = None
            result.append(s)
        return result

    hmm_regime = regime_data.get("hmm_regime")
    hmm_regime_prob = float(regime_data.get("hmm_regime_prob", 0.0))
    hmm_regime_duration = int(regime_data.get("hmm_regime_duration", 0))

    for sig in signals:
        s = dict(sig)
        plugin_regime_type = s.get("regime_type", "any")
        allowed = _REGIME_MAP.get(plugin_regime_type, [0, 1, 2])

        regime_eligible = True
        suppression_reason = None

        if hmm_regime_prob < _REGIME_PROB_MIN:
            regime_eligible = False
            suppression_reason = "regime_prob"
        elif hmm_regime_duration < _REGIME_DUR_MIN:
            regime_eligible = False
            suppression_reason = "regime_duration"
        elif hmm_regime is not None and int(hmm_regime) not in allowed:
            regime_eligible = False
            suppression_reason = "regime_type"

        s["regime_eligible"] = regime_eligible
        s["suppression_reason"] = suppression_reason
        result.append(s)

    return result
