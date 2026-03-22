"""Regime Gate pipeline stage — pure function.

Applies HMM regime compatibility check to signals.
No Kafka, no DB, no service dependencies.
"""

from __future__ import annotations

from src.intelligence.trading.aggregator import _REGIME_MAP


def apply_regime_gate(
    signals: list[dict],
    regime_data: dict | None,
    *,
    prob_min: float = 0.30,
    dur_min: int = 1,
) -> list[dict]:
    """Apply regime gating to all signals.

    Parameters
    ----------
    signals:
        List of signal dicts. Each may have a "regime_type" key.
    regime_data:
        Dict with HMM regime info, or None for graceful degradation.
        Expected keys: "hmm_regime", "hmm_regime_prob", "hmm_regime_duration".
    prob_min:
        Minimum HMM regime probability to trust the regime label.
        Default 0.30 is a safety floor (D-02, SHADOW-01) — not a quality filter.
        Set via REGIME_PROB_MIN env var in Settings.
    dur_min:
        Minimum number of bars the regime must have been stable.
        Default 1 is a safety floor (D-02, SHADOW-01).
        Set via REGIME_DUR_MIN env var in Settings.

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

        if hmm_regime_prob < prob_min:
            regime_eligible = False
            suppression_reason = "regime_prob"
        elif hmm_regime_duration < dur_min:
            regime_eligible = False
            suppression_reason = "regime_duration"
        elif hmm_regime is not None and int(hmm_regime) not in allowed:
            regime_eligible = False
            suppression_reason = "regime_type"

        s["regime_eligible"] = regime_eligible
        s["suppression_reason"] = suppression_reason
        result.append(s)

    return result
