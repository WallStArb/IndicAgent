---
phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service
plan: 03C
type: execute
wave: 3
depends_on: ["64-03A", "64-03B"]
deferred: true
deferred_reason: |
  Gated on prerequisite IC validation only (NOT FX data — EURUSD/GBPUSD/USDJPY/USDCHF are already defined
  in settings.py as AssetClass.FX non-futures instruments, so get_active_contracts() returns them).
  Unblock: yield_curve (Plan 03A) AND ftq_score (Plan 03B) both validate IC > 0.05, p < 0.01, N >= 30.
  If either fails, abandon macro direction. Target: ~May 10 data gate.
files_modified:
  - src/intelligence/macro/usd_strength.py
  - services/macro_compute_agent.py
  - production/migrations/076_macro_features_usd.sql
  - tests/unit/intelligence/test_usd_strength.py
autonomous: true
requirements: []

must_haves:
  truths:
    - "USD strength factor computed from FX pairs (EURUSD, GBPUSD, USDJPY, USDCHF)"
    - "USD strength extends MacroComputeAgent with new factor computation"
    - "USD strength output published to existing topic_macro_signals"
    - "Unit tests pass for USD strength computation"
  artifacts:
    - path: "src/intelligence/macro/usd_strength.py"
      provides: "USD strength macro factor (DXY-like composite from FX pairs)"
      contains: "compute_usd_strength()"
    - path: "services/macro_compute_agent.py"
      provides: "Extended with USD strength computation"
      contains: "compute_usd_strength() call in _run()"
  key_links:
    - from: "services/macro_compute_agent.py"
      to: "src/intelligence/macro/usd_strength.py"
      via: "imports compute_usd_strength()"
      pattern: "from src.intelligence.macro.usd_strength import compute_usd_strength"
    - from: "src/intelligence/macro/usd_strength.py"
      to: "src/intelligence/macro/constants.py"
      via: "imports MACRO_FX_PAIRS"
      pattern: "MACRO_FX_PAIRS"

---

<objective>
USD strength macro factor — third macro factor for MacroComputeAgent.

Purpose: USD strength from FX pairs (EURUSD, GBPUSD, USDJPY, USDCHF). Composite DXY-like signal: inverse EURUSD + inverse GBPUSD + USDJPY change + USDCHF change, normalized via tanh.

FX pairs are already tracked via IDEALPRO (EURUSD, GBPUSD, USDJPY, USDCHF defined in settings.py).

All macro factors run in shadow mode for data collection; validation occurs when approaching production.

Output: USD strength factor published to topic_macro_signals, captured to macro_features hypertable.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-CONTEXT.md
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-RENAISSANCE-REVIEW-R&D.md
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-03A-PLAN.md
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-03B-PLAN.md

@src/intelligence/macro/constants.py (from Plan 01)
@services/macro_compute_agent.py (from Plan 03A)

<interfaces>
<!-- Implementation when prerequisites met -->

From src/intelligence/macro/usd_strength.py (CREATE only when prerequisites pass):
```python
"""USD strength macro factor.

Computes USD strength from FX pairs (EURUSD, GBPUSD, USDJPY, USDCHF).
DXY-like composite: inverse EURUSD + inverse GBPUSD + USDJPY + USDCHF.

USD strengthening = All pairs move in USD's favor:
- EURUSD down (EUR weakens)
- GBPUSD down (GBP weakens)
- USDJPY up (USD strengthens)
- USDCHF up (USD strengthens)

Outputs:
    usd_strength_score: float [-1, +1]
        - Positive: USD strengthening
        - Negative: USD weakening
        - Near 0: Flat
    usd_strength_regime: str
        - strong_up: USD strong up (>2% weighted move)
        - up: USD up (strengthening)
        - flat: USD flat
        - down: USD down (weakening)
        - strong_down: USD strong down (>2% weighted move)
"""

from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np

from src.intelligence.macro.constants import MACRO_FX_PAIRS


def compute_usd_strength(
    bars: dict[str, deque],
    lookback: int = 10,
) -> dict[str, Any]:
    """Compute USD strength from FX pairs.
    
    Args:
        bars: Dict mapping symbol → deque of recent bars (OHLCV dicts)
        lookback: Number of bars to average (default: 10)
    
    Returns:
        dict with usd_strength_score (float) and usd_strength_regime (str)
    
    Implementation:
        1. Extract close prices for EURUSD, GBPUSD, USDJPY, USDCHF
        2. Compute USD contribution per pair:
           - EURUSD: USD down when EURUSD down (inverse)
           - GBPUSD: USD down when GBPUSD down (inverse)
           - USDJPY: USD up when USDJPY up (direct)
           - USDCHF: USD up when USDCHF up (direct)
        3. Weighted composite: sum(contributions) / 4
        4. Normalize via tanh for gradient in [-1, +1]
        5. Classify regime based on magnitude
    """
    contributions = []
    
    for symbol in MACRO_FX_PAIRS:
        if symbol not in bars or len(bars[symbol]) < lookback:
            continue
        
        # Get current vs previous close
        current_close = bars[symbol][-1]["close"]
        prev_close = bars[symbol][-lookback]["close"] if len(bars[symbol]) >= lookback else current_close
        
        # Compute return
        ret = (current_close - prev_close) / prev_close
        
        if symbol in ("EURUSD", "GBPUSD"):
            # Inverse: USD down when pair down (USD is quote currency)
            contribution = -ret
        else:  # USDJPY, USDCHF
            # Direct: USD up when pair up (USD is base currency)
            contribution = ret
        
        contributions.append(contribution)
    
    if not contributions:
        return {
            "usd_strength_score": 0.0,
            "usd_strength_regime": "flat",
        }
    
    # Weighted average
    avg_contribution = np.mean(contributions)
    
    # Normalize: 0.01 = 1% weighted USD move -> tanh(0.01 * 100) ≈ 0.76
    usd_strength = np.tanh(avg_contribution * 100.0)  # [-1, +1]
    
    # Regime classification
    if usd_strength > 0.8:
        regime = "strong_up"
    elif usd_strength > 0.3:
        regime = "up"
    elif usd_strength < -0.8:
        regime = "strong_down"
    elif usd_strength < -0.3:
        regime = "down"
    else:
        regime = "flat"
    
    return {
        "usd_strength_score": float(usd_strength),
        "usd_strength_regime": regime,
    }
```
</interfaces>
</context>

<tasks>

**NO TASKS — PLAN DEFERRED**

This plan will only be executed if:
1. FX pair data sources are added to the system
2. Plan 03A (yield curve) validates with IC > 0.05
3. Plan 03B (flight-to-quality) validates with IC > 0.05

If either 03A or 03B fails validation, this plan is ABANDONED and FX data is NOT purchased.

**Renaissance discipline:** Don't invest in data feeds for unproven signals. Validate macro approach first with available data (yield curve from rate futures, FTQ from ETFs). Only if both prove signal value, invest in FX data for USD strength.

</tasks>

<checkout>
<checklist>
- [ ] PREREQUISITE: Plan 03A validates (IC > 0.05)
- [ ] PREREQUISITE: Plan 03B validates (IC > 0.05)
- [ ] PREREQUISITE: FX pairs added to data feed (EURUSD, GBPUSD, USDJPY, USDCHF)
- [ ] If prerequisites met: Implement usd_strength.py
- [ ] If prerequisites met: Extend MacroComputeAgent with USD strength
- [ ] If prerequisites met: Backtest on 6 months data
- [ ] If prerequisites met: Validate IC > 0.05, p < 0.01
- [ ] If prerequisites FAILED: ABANDON this plan, DO NOT purchase FX data
</checklist>
</checkout>

---

*Plan 64-03C: USD Strength Macro Factor (DEFERRED)*
*Renaissance R&D Approach: Don't build infrastructure for unproven signals. Validate macro approach with available data first (yield curve, FTQ). Only invest in FX data if both prove signal value.*
