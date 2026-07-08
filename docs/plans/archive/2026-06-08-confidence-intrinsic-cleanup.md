# Plan: Strip Signal-Extrinsic Factors from I7 Confidence

**Date:** 2026-06-08
**Branch:** confidence-intrinsic-cleanup
**Scope:** 17 I7 plugin files + exhaustion_utils.py
**Tests:** `.venv/bin/pytest tests/unit/ -q` must stay green after each task

## Goal

Remove all signal-extrinsic factors from I7 confidence calculations. Confidence must reflect
only the intrinsic quality of the detected pattern. Extrinsic data (regime, CTF, exhaustion, zone,
SMC events) already travels in `capture_signal_features()` and the feature vector — removing it
from confidence does not discard it.

Four extrinsic categories to strip:
1. **HMM regime weights** (`hmm_regime_weight`, `hmm_trending_weight`)
2. **CTF (I6) scores** (`ctf_score`, `ctf_structure_alignment`, `ctf_trend_alignment`)
3. **Exhaustion boost/guard** (`apply_exhaustion_boost`, `apply_exhaustion_guard`)
4. **Zone context** (supply/demand zone penalties/boosts)
5. **SMC layer outputs** (FVG, OB, CHoCH, BOS, price_in_premium in `liquidity_hunt`)

Two plugins also need structural redesign (not just removal):
- `momentum_breakout`: redistribute weights after removing `regime_score` (15%)
- `squeeze_expansion`: redistribute weights after removing `regime_score` (20%)
- `trend_following`: redesign composite — 60% is currently extrinsic

See full audit rationale: `docs/research/signal-07-signal-ranker.md`

---

## Task 1: Simple HMM + CTF additive trims

**Files:** `ofi_continuation.py`, `gap_analysis_setup.py`, `cvd_divergence.py`

### ofi_continuation.py

Remove:
```python
regime_w = hmm_regime_weight(features, "up" if direction == 1 else "down")
raw_conf += 0.10 * (regime_w - 0.5)
```
Remove ctf_score block:
```python
ctf_score = float(features.get("ctf_score", 0.0))
if abs(ctf_score) > 0.3:
    raw_conf += 0.15 * min(1.0, abs(ctf_score) / 0.7)
    supporting.append(f"ctf_score={ctf_score:.3f}")
```
Remove unused import: `from ..utils.gradient_utils import hmm_regime_weight`

### gap_analysis_setup.py

Remove:
```python
regime_w = hmm_regime_weight(features, "up" if direction == 1 else "down")
base += 0.10 * (regime_w - 0.5)
```
Remove unused import: `from ..utils.gradient_utils import hmm_regime_weight`

### cvd_divergence.py

Remove:
```python
regime_w = hmm_regime_weight(features, "up" if direction == 1 else "down")
raw_conf += 0.10 * (regime_w - 0.5)
```
Remove ctf_score block:
```python
ctf_score = float(features.get("ctf_score", 0.0))
if abs(ctf_score) > 0.3:
    raw_conf += 0.15 * min(1.0, abs(ctf_score) / 0.7)
```
Remove the ctf_score supporting.append reference in the later block too (check around line 166).
Remove unused import: `from ..utils.gradient_utils import hmm_regime_weight`

---

## Task 2: HMM additive boosts on mean-reversion and ORB plugins

**Files:** `failed_breakout.py`, `ofi_divergence.py`, `orb15.py`, `orb30.py`, `prev_day_level_test.py`

### failed_breakout.py

Remove:
```python
ranging_w = hmm_regime_weight(features, "ranging")
trending_w = max(hmm_regime_weight(features, "up"), hmm_regime_weight(features, "down"))
confidence += 0.15 * ranging_w
confidence -= 0.10 * trending_w
```
Remove unused import: `from ..utils.gradient_utils import hmm_regime_weight`

### ofi_divergence.py

Remove the entire hmm_regime block (lines ~151-158):
```python
hmm_regime = features.get("hmm_regime")
if hmm_regime is not None:
    r = float(hmm_regime)
    ranging_w = hmm_regime_weight(features, "ranging")
    trending_w = max(hmm_regime_weight(features, "up"), hmm_regime_weight(features, "down"))
    confidence += 0.06 * ranging_w
    confidence -= 0.06 * trending_w
```
Keep the `hmm_regime` read at line ~170 (`is_ranging = hmm_regime is not None and ...`) and at line
~185 (supporting.append) — those are logging only, not confidence. Re-read `hmm_regime` locally
there if the earlier assignment is removed.
Remove unused import: `from ..utils.gradient_utils import hmm_regime_weight`

### orb15.py and orb30.py (same change in both)

Remove:
```python
trending_w = max(hmm_regime_weight(features, "up"), hmm_regime_weight(features, "down"))
confidence += 0.10 * trending_w
```
Keep `gap_boost` line — that is intrinsic.
Remove unused import: `from ..utils.gradient_utils import hmm_regime_weight`

### prev_day_level_test.py

Remove:
```python
ranging_w = hmm_regime_weight(features, "ranging")
trending_w = max(hmm_regime_weight(features, "up"), hmm_regime_weight(features, "down"))
```
And the conditional boosts:
```python
if setup_variant == "fade":
    confidence += 0.12 * ranging_w
    confidence -= 0.05 * trending_w
else:
    confidence += 0.12 * trending_w
    confidence -= 0.05 * ranging_w
```
`confidence` starts at `0.50` after removal — that is the correct clean baseline.
Remove unused import: `from ..utils.gradient_utils import hmm_regime_weight`

---

## Task 3: choch_reversal — HMM boost (semantically inverted) + CTF boosts

**File:** `choch_reversal.py`

Remove the HMM block (direction-aligned boost — semantically wrong for a reversal signal):
```python
up_w = hmm_regime_weight(features, "up")
down_w = hmm_regime_weight(features, "down")
if direction == 1:
    raw_conf += 0.2 * up_w
    supporting.append("hmm_regime_bullish")
elif direction == -1:
    raw_conf += 0.2 * down_w
    supporting.append("hmm_regime_bearish")
```

Remove the three CTF boosts:
```python
ctf_structure = float(features.get("ctf_structure_alignment", 0.0))
if ctf_structure > 0.3:
    structure_boost = 0.08 * min(1.0, ctf_structure / 0.7)
    raw_conf += structure_boost
    if structure_boost > 0.04:
        supporting.append("multi_tf_structure_aligned")

ctf_trend = float(features.get("ctf_trend_alignment", 0.0))
if ctf_trend > 0.3:
    trend_boost = 0.06 * min(1.0, ctf_trend / 0.7)
    raw_conf += trend_boost
    if trend_boost > 0.03:
        supporting.append("multi_tf_trend_aligned")

ctf_score = float(features.get("ctf_score", 0.0))
if abs(ctf_score) > 0.3 and math.copysign(1, ctf_score) == direction:
    overall_boost = 0.05 * min(1.0, abs(ctf_score) / 0.7)
    raw_conf += overall_boost
    if overall_boost > 0.03:
        supporting.append("ctf_directionally_aligned")
```

Remove unused import: `from ..utils.gradient_utils import hmm_regime_weight`
Check if `import math` is still needed after removal — keep if used elsewhere in the file.

---

## Task 4: supply_demand_setup + liquidity_sweep_reclaim — ranging weight + CTF + exhaustion

**Files:** `supply_demand_setup.py`, `liquidity_sweep_reclaim.py`

### supply_demand_setup.py

Remove ranging_w boost:
```python
ranging_w = hmm_regime_weight(features, "ranging")
confidence += 0.05 * ranging_w
```

Remove CTF boost block (around line 176):
```python
ctf = float(features.get("ctf_score", 0.0))
if ...:
    ctf_boost = 0.05 * min(2.0, abs(ctf) / 0.5)
    confidence += ctf_boost
    if ctf_boost > 0.04:
        supporting.append("strong_ctf_aligned")
    else:
        supporting.append("ctf_aligned")
```

Remove exhaustion boost call:
```python
confidence, supporting = apply_exhaustion_boost(features, direction, confidence, supporting)
```

Remove unused imports: `from ..utils.gradient_utils import hmm_regime_weight`
and `from .exhaustion_utils import apply_exhaustion_boost` if no longer used.

### liquidity_sweep_reclaim.py

Remove ranging_w boost:
```python
ranging_w = hmm_regime_weight(features, "ranging")
confidence += 0.10 * ranging_w
```

Remove CTF boost block:
```python
ctf_score = features.get("ctf_score", 0.0)
if abs(ctf_score) > 0.3:
    ...
    ctf_boost = 0.05 * min(2.0, abs(ctf_score) / 0.5)
    confidence += ctf_boost
    ...
```

Remove exhaustion boost call:
```python
confidence, supporting = apply_exhaustion_boost(features, direction, confidence, supporting)
```

Remove unused imports: `from ..utils.gradient_utils import hmm_regime_weight, linear_ramp` →
keep `linear_ramp` if still used elsewhere in the file; remove `hmm_regime_weight` only.
Remove `from .exhaustion_utils import apply_exhaustion_boost` if no longer used.

---

## Task 5: liquidity_hunt — HMM + CTF + zone + SMC + exhaustion

**File:** `liquidity_hunt.py`

This plugin has the most removals. Read the full file before editing.

Remove HMM weight:
```python
trending_w = max(hmm_regime_weight(features, "up"), hmm_regime_weight(features, "down"))
confidence += 0.10 * trending_w
```

Remove CTF boost:
```python
ctf = float(features.get("ctf_score", 0.0))
if abs(ctf) > 0.3 and ...:
    confidence += 0.05
    supporting.append("ctf_aligned")
```

Remove zone alignment boost AND opposing penalty:
```python
in_demand = float(features.get("in_demand_zone", 0.0))
in_supply = float(features.get("in_supply_zone", 0.0))
if direction == -1 and in_supply == 1.0:
    confidence += 0.05
    supporting.append("supply_zone_aligned")
elif direction == 1 and in_demand == 1.0:
    confidence += 0.05
    supporting.append("demand_zone_aligned")
if direction == -1 and in_demand == 1.0:
    confidence -= 0.10
    supporting.append("penalty_demand_zone_opposing")
elif direction == 1 and in_supply == 1.0:
    confidence -= 0.10
    supporting.append("penalty_supply_zone_opposing")
```

Remove SMC event boosts (FVG, OB, CHoCH, BOS, price_in_premium):
```python
price_in_premium = float(features.get("price_in_premium", -1))
if direction == -1 and price_in_premium == 1.0:
    confidence += 0.06
    supporting.append("premium_aligned")
elif direction == 1 and price_in_premium == 0.0:
    confidence += 0.06
    supporting.append("discount_aligned")

fvg_type = float(features.get("fvg_type", 0.0))
if fvg_type == float(direction):
    confidence += 0.08
    supporting.append("fvg_aligned")

ob_type = float(features.get("ob_type", 0.0))
if ob_type == float(direction):
    confidence += 0.06
    supporting.append("order_block_aligned")

choch = float(features.get("choch_detected", 0.0))
bos = float(features.get("bos_detected", 0.0))
bos_dir = float(features.get("bos_direction", 0.0))
if choch == 1.0:
    confidence += 0.10
    supporting.append("choch_confirmed")
elif bos == 1.0 and bos_dir == float(direction):
    confidence += 0.05
    supporting.append("bos_confirmed")
```

Remove exhaustion boost:
```python
confidence, supporting = apply_exhaustion_boost(features, direction, confidence, supporting)
```

Remove unused imports: `from ..utils.gradient_utils import hmm_regime_weight`
and `from .exhaustion_utils import apply_exhaustion_boost` if no longer used.

---

## Task 6: momentum_breakout — composite restructure + zone + exhaustion

**File:** `momentum_breakout.py`

Remove `regime_score` component and replace composite formula.

Current:
```python
if regime_aligns:
    regime_score = max(
        hmm_regime_weight(features, "up"), hmm_regime_weight(features, "down")
    )
else:
    regime_score = 0.1

raw_conf = 0.35 * roc_score + 0.30 * vol_score + 0.20 * break_margin + 0.15 * regime_score
```

Replace with:
```python
raw_conf = 0.40 * roc_score + 0.35 * vol_score + 0.25 * break_margin
```

Remove zone friction penalty:
```python
in_supply = float(features.get("in_supply_zone", 0.0))
in_demand = float(features.get("in_demand_zone", 0.0))
supply_str = float(features.get("supply_strength", 0.0))
demand_str = float(features.get("demand_strength", 0.0))
if direction == 1 and in_supply == 1.0:
    raw_conf -= 0.12 * supply_str
    supporting.append("penalty_supply_zone_friction")
elif direction == -1 and in_demand == 1.0:
    raw_conf -= 0.12 * demand_str
    supporting.append("penalty_demand_zone_friction")
```

Remove exhaustion guard:
```python
raw_conf, supporting = apply_exhaustion_guard(features, raw_conf, supporting)
```

Remove `regime_aligns` variable and check (no longer needed).
Keep `trend_regime` read if used in `supporting` append — check. If it is only used for
`regime_aligns`, remove it too.

Remove unused imports: `from ..utils.gradient_utils import hmm_regime_weight`
and `from .exhaustion_utils import apply_exhaustion_guard` if no longer used.

---

## Task 7: squeeze_expansion — composite restructure + exhaustion

**File:** `squeeze_expansion.py`

Remove `regime_score` component and replace composite formula.

Current:
```python
if trend_regime != 0.0:
    regime_agrees = (trend_regime > 0 and direction == 1) or (
        trend_regime < 0 and direction == -1
    )
    if regime_agrees:
        regime_score = 0.2 + 0.6 * max(
            hmm_regime_weight(features, "up"), hmm_regime_weight(features, "down")
        )
    else:
        regime_score = 0.2
else:
    regime_score = 0.5

raw_conf = (
    0.3 * squeeze_bars_score
    + 0.3 * vol_expansion_score
    + 0.2 * momentum_score
    + 0.2 * regime_score
)
```

Replace with:
```python
raw_conf = (
    0.35 * squeeze_bars_score
    + 0.35 * vol_expansion_score
    + 0.30 * momentum_score
)
```

Remove exhaustion guard:
```python
raw_conf, supporting = apply_exhaustion_guard(features, raw_conf, supporting)
```

Remove unused imports: `from ..utils.gradient_utils import hmm_regime_weight`
and `from .exhaustion_utils import apply_exhaustion_guard` if no longer used.
Check if `trend_regime` variable is still used in supporting factors — keep the read if so,
remove if only used for regime_score.

---

## Task 8: trend_following — full composite redesign + zone + exhaustion

**File:** `trend_following.py`

This is the deepest structural fix. Read the full file before editing.

Current composite (60% extrinsic):
```python
raw_conf = (
    0.35 * min(1.0, abs(trend_regime))
  + 0.25 * min(1.0, trend_conf)
  + 0.20 * min(1.0, abs(trend_strength))
  + 0.20 * min(1.0, abs(ctf_score))
)
```

`trend_regime` (35%) and `ctf_score` (20%) are extrinsic. `trend_conf` and `trend_strength` are
Kalman filter quality metrics — these ARE intrinsic to a trend-following signal.

Before editing, read the file to identify what `swing_pattern` contains (it is read earlier in the
function but not currently in the composite). If `swing_pattern` is available, include it.

Replace with (adjust if `swing_pattern` is not available):
```python
raw_conf = (
    0.45 * min(1.0, trend_conf)
  + 0.35 * min(1.0, abs(trend_strength))
  + 0.20 * min(1.0, abs(swing_pattern))
)
```

If `swing_pattern` is not present or always zero, use:
```python
raw_conf = (
    0.55 * min(1.0, trend_conf)
  + 0.45 * min(1.0, abs(trend_strength))
)
```

Remove zone friction penalty (same pattern as momentum_breakout — see Task 6).

Remove exhaustion guard:
```python
raw_conf, supporting = apply_exhaustion_guard(features, raw_conf, supporting)
```

Remove unused imports. Check if `ctf_score` variable is used anywhere else in the function
(supporting factors) — keep the read if so, remove from composite only.

---

## Shared Cleanup Rules

Apply across all tasks:

1. **Unused imports**: After each file edit, verify `hmm_regime_weight`, `hmm_trending_weight`,
   `apply_exhaustion_boost`, `apply_exhaustion_guard` imports are removed if no longer called.
   `linear_ramp` may be imported alongside `hmm_regime_weight` — keep if still used.

2. **`hmm_regime` reads for logging**: Do NOT remove reads like
   `hmm_regime = features.get("hmm_regime")` that feed into `regime_context` strings or
   `supporting.append(f"hmm_regime={hmm_regime}")`. These are metadata, not confidence modifiers.

3. **`regime_aligns` / `regime_agrees` variables**: Remove if they were only used to gate
   `regime_score`. Keep if used in `supporting.append` or other logic.

4. **`ruff check --fix`**: Run after each file edit to catch any lingering unused variable warnings.

---

## Verification

After all tasks:
```bash
.venv/bin/pytest tests/unit/ -q
.venv/bin/ruff check . --fix
.venv/bin/black .
```

Grep to confirm no `hmm_regime_weight` calls remain in confidence-modifying positions
(calls inside logging strings or `regime_context` assignments are fine):
```bash
grep -n "hmm_regime_weight\|apply_exhaustion_boost\|apply_exhaustion_guard" \
  src/intelligence/trading/*.py
```

Expected: only imports in `gradient_utils.py` definition file and `exhaustion_utils.py` definition.
All call sites in trading plugins should be gone.
