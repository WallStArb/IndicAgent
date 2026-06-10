# Phase 119: Remaining 16 Setup Refactoring - Pattern Map

**Mapped:** 2026-06-10
**Files analyzed:** 20 (17 target plugins + validate_tier + test_i6_confluence_enforcement + test_i7_extrinsic_contract)
**Analogs found:** 20 / 20

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/intelligence/trading/ofi_divergence.py` | plugin (batch A) | request-response | `src/intelligence/trading/ofi_continuation.py` | exact |
| `src/intelligence/trading/failed_breakout.py` | plugin (batch A) | request-response | `src/intelligence/trading/ofi_continuation.py` | role-match |
| `src/intelligence/trading/ofi_spike.py` | plugin (batch C) | request-response | `src/intelligence/trading/microstructure_utils.py` | exact (delegate) |
| `src/intelligence/trading/cvd_spike.py` | plugin (batch C) | request-response | `src/intelligence/trading/microstructure_utils.py` | exact (delegate) |
| `src/intelligence/trading/microstructure_utils.py` | utility (shared helper) | request-response | `src/intelligence/trading/ofi_continuation.py` | role-match |
| `src/intelligence/trading/candlestick_pattern_setup.py` | plugin (batch B) | request-response | `src/intelligence/trading/momentum_breakout.py` | role-match |
| `src/intelligence/trading/session_extremes_setup.py` | plugin (batch B) | request-response | `src/intelligence/trading/momentum_breakout.py` | role-match |
| `src/intelligence/trading/liquidity_hunt.py` | plugin (batch D) | request-response | `src/intelligence/trading/lvn_breakout.py` | role-match |
| `src/intelligence/trading/delta_exhaustion.py` | plugin (batch E) | request-response | `src/intelligence/trading/ofi_continuation.py` | role-match |
| `src/intelligence/trading/lvn_breakout.py` | plugin (batch F) | request-response | `src/intelligence/trading/ofi_continuation.py` | exact |
| `src/intelligence/trading/orb15.py` | plugin (batch B) | request-response | `src/intelligence/trading/momentum_breakout.py` | role-match |
| `src/intelligence/trading/orb30.py` | plugin (batch B) | request-response | `src/intelligence/trading/momentum_breakout.py` | role-match |
| `src/intelligence/trading/second_leg_continuation.py` | plugin (batch H) | request-response | `src/intelligence/trading/lvn_breakout.py` | role-match |
| `src/intelligence/trading/vcp.py` | plugin (batch H) | request-response | `src/intelligence/trading/lvn_breakout.py` | role-match |
| `src/intelligence/trading/vwap_reclaim.py` | plugin (batch G) | request-response | `src/intelligence/trading/vwap_deviation.py` | exact |
| `src/intelligence/trading/dual_divergence.py` | plugin (batch I) | request-response | `src/intelligence/trading/ofi_divergence.py` | role-match |
| `src/intelligence/trading/vwap_deviation.py` | plugin (batch G) | request-response | `src/intelligence/trading/ofi_continuation.py` | role-match |
| `src/intelligence/trading/momentum_breakout.py` | plugin (batch J) | request-response | `src/intelligence/trading/lvn_breakout.py` | role-match |
| `src/intelligence/plugins/base.py` | architecture enforcer | request-response | self (modify validate_tier) | exact |
| `tests/unit/intelligence/test_i6_confluence_enforcement.py` | test | request-response | self (extend existing) | exact |

---

## Pattern Assignments

### PATTERN 1 — Reference Implementation
**File:** `src/intelligence/trading/ofi_continuation.py`

This is the canonical GOOD pattern. All 17 plugins are refactored to match this structure.

**ClassVar declarations** (lines 54-73):
```python
name: str = "trad_OFIContinuation"
shadow_only: bool = True
# ...
regime_type: str = "trend"
requires_i6_confluence: bool = True
```

**Features dict assembly** (lines 78-86) — always before any gate:
```python
features = {
    **(frames.get("i1") or {}),
    **(frames.get("i2") or {}),
    **(frames.get("i3") or {}),
    **(frames.get("i4") or {}),
    **(frames.get("i5") or {}),
    **(frames.get("smc") or {}),
    **(frames.get("i6") or {}),
}
```

**Domain gate then expensive extraction** (lines 87-121) — cheap checks fire before ATR/OHLCV:
```python
if df is None or len(df) < self.min_lookback:
    return no_signal()

# [domain-specific cheap gates here — ofi_ewma_20 None/zero check, consecutive count]

# Gate: require N consecutive bars (cheap state check)
if count < _MIN_CONSECUTIVE_BARS:
    return no_signal()

# Gate: require minimum OFI magnitude (cheap float comparison)
if abs(ofi_ewma) < mag_threshold:
    return no_signal()

# Expensive: OHLCV extraction only AFTER all cheap gates pass
atr = get_atr_with_floor_from_frames(frames)
```

**4-factor intrinsic confidence composite** (lines 138-164):
```python
magnitude_score = clamp01(
    (abs(ofi_ewma) - mag_threshold) / max(1e-9, upper_ref - mag_threshold)
)
# ... 3 more named score variables ...

raw_conf = (
    0.40 * magnitude_score
    + 0.25 * alignment_score
    + 0.20 * persistence_score
    + 0.15 * volume_score
)
confidence = compose_confidence(raw_conf)
```

---

### PATTERN 2 — Dual Gate Insertion (D-03)

**What to insert before any OHLCV extraction in all 17 plugins.**

Imports to add (if not already present):
```python
from ..utils.gradient_utils import hmm_regime_weight, hmm_trending_weight
```

Module-level constants (add near top with other `_MIN_*` constants):
```python
_MIN_REGIME_WEIGHT: float = 0.30
_MIN_CTF_SCORE: float = 0.25
```

For plugins with `regime_type="trend"` (LVNBreakout, SecondLegContinuation, VCP, MomentumBreakout, FailedBreakout, CandlestickPatternSetup with trend direction):
```python
# Gate 1 (regime — cheap):
if hmm_regime_weight(features, "up") < _MIN_REGIME_WEIGHT and \
   hmm_regime_weight(features, "down") < _MIN_REGIME_WEIGHT:
    return no_signal()
```

For plugins with `regime_type="mean_reversion"` (VWAPDeviation, DeltaExhaustion, SessionExtremesSetup):
```python
# Gate 1 (regime — cheap):
if hmm_regime_weight(features, "ranging") < _MIN_REGIME_WEIGHT:
    return no_signal()
```

For plugins with `regime_type="any"` (OFIDivergence, OFISpike, CVDSpike, VWAPReclaim, DualDivergence, CandlestickPatternSetup):
```python
# Gate 1 (regime — cheap): use trending probability for either direction
if hmm_trending_weight(features) < _MIN_REGIME_WEIGHT:
    return no_signal()
```

Gate 2 (I6 — cheap, applies to ALL plugins regardless of regime_type):
```python
# Gate 2 (I6 — cheap):
ctf_score = float(features.get("ctf_score") or 0.0)
if abs(ctf_score) < _MIN_CTF_SCORE:
    return no_signal()
```

**Insertion point rule:** After features dict assembly and null/length check on `df`, and BEFORE any `extract_ohlcv()`, `get_atr_with_floor_from_frames()`, `df["close"].to_numpy()`, or `df["volume"]` access.

---

### PATTERN 3 — ClassVar Changes (applies to all 17 plugins)

**Before (current state in all 17 plugins):**
```python
requires_i6_confluence: bool = False  # TODO(phase-118): integrate I6 confluence
# shadow_only is absent
```

**After (target state):**
```python
shadow_only: bool = True  # shadow mode until Phase 120 promotes
requires_i6_confluence: bool = True
```

`shadow_only` is NOT inherited — it must be explicitly declared as shown. Source: `ofi_continuation.py` line 55.

---

### PATTERN 4 — Batch F/G/J: Gates Only (no confidence rewrite)

**Analog:** `src/intelligence/trading/lvn_breakout.py`

LVNBreakout already has a correct 4-factor confidence formula (lines 186-188):
```python
raw_conf = (
    0.30 * vol_score + 0.25 * trend_clarity + 0.25 * lvn_inverse + 0.20 * close_strength
)
```

The existing binary regime gate (lines 84-91) must be **replaced** with the D-03 dual gate:
```python
# BEFORE (binary equality check — remove this):
hmm = features.get("hmm_regime")
if hmm is None:
    return no_signal()
hmm = int(hmm)
if hmm not in (1, 2):
    return no_signal()

# AFTER (continuous probability gate — insert instead):
if hmm_regime_weight(features, "up") < _MIN_REGIME_WEIGHT and \
   hmm_regime_weight(features, "down") < _MIN_REGIME_WEIGHT:
    return no_signal()
ctf_score = float(features.get("ctf_score") or 0.0)
if abs(ctf_score) < _MIN_CTF_SCORE:
    return no_signal()
```

Note: `trend_clarity` in the confidence formula still uses `hmm_probability` (line 173-174) — this is an intrinsic confidence factor, not a gate, so it stays.

VWAPReclaim (batch G) has the same pattern: existing binary `trend_align` scoring (lines 189-195) stays as an intrinsic confidence factor; the new dual gate is added BEFORE `close = df["close"].to_numpy()` at line 97.

VWAPDeviation (batch G) — `extract_ohlcv` is called FIRST at line 60. Move the dual gate before it:
```python
# BEFORE (current top of compute_full):
result = extract_ohlcv(frames, self.min_lookback)
if result is None:
    return no_signal()
open_, high, low, close = result
features = { ... }

# AFTER (reorder):
df = frames.get("main")
if df is None or len(df) < self.min_lookback:
    return no_signal()
features = { ... }
# [dual gate here]
result = extract_ohlcv(frames, self.min_lookback)  # now after gates
```

MomentumBreakout (batch J) — `extract_ohlcv` is called FIRST at line 58. Same reorder as VWAPDeviation. Confidence formula is unchanged (D-04).

---

### PATTERN 5 — Batch C: detect_spike_signal Refactor

**File:** `src/intelligence/trading/microstructure_utils.py`

OFISpike and CVDSpike delegate entirely to `detect_spike_signal()`. Both plugins require zero code changes — only the helper changes.

**Current (bad) pattern** (lines 80-91 in microstructure_utils.py):
```python
# Build raw confidence then fold in I6/HMM contributions (additive)
raw = 0.50 + abs(spike_z) * 0.05

# I6 ctf_score contribution
ctf_score = float(features.get("ctf_score", 0.0))
if abs(ctf_score) > 0.3:
    raw += 0.15 * min(1.0, abs(ctf_score) / 0.7)

# HMM regime contribution (additive, centered at 0.5 neutral)
regime_w = hmm_regime_weight(features, "up" if direction == 1 else "down")
raw += 0.10 * (regime_w - 0.5)

confidence = compose_confidence(raw)
```

**Target (good) pattern** — add dual gate BEFORE `atr = get_atr_with_floor_from_frames(frames)` at line 70:
```python
# Gate 1 (regime — cheap): spike signals fire in any direction
if hmm_trending_weight(features) < _MIN_REGIME_WEIGHT:
    return no_signal()

# Gate 2 (I6 — cheap):
ctf_score = float(features.get("ctf_score") or 0.0)
if abs(ctf_score) < _MIN_CTF_SCORE:
    return no_signal()

atr = get_atr_with_floor_from_frames(frames)
```

Then replace the additive confidence block with 4-factor intrinsic composite:
```python
# 4-factor intrinsic: z_score_score + volume_score + ctf_factor + persistence_score
z_score_score = clamp01((abs(spike_z) - _SPIKE_THRESHOLD) / 3.0)
rel_vol = features.get("rel_volume")
volume_score = clamp01((float(rel_vol) - 1.0) / 1.5) if rel_vol is not None else 0.3
ctf_factor = clamp01((abs(ctf_score) - _MIN_CTF_SCORE) / (1.0 - _MIN_CTF_SCORE))
# persistence: spike vs. z-score gap (price not yet responded)
price_return_z = features.get("price_return_z")
persistence_score = clamp01(abs(spike_z) / max(1.0, abs(float(price_return_z)) if price_return_z else 1.0) - 1.0)

raw = (
    0.45 * z_score_score
    + 0.25 * volume_score
    + 0.20 * ctf_factor
    + 0.10 * persistence_score
)
confidence = compose_confidence(raw)
```

Also add `clamp01` to imports (line 13 currently imports `compose_confidence` but not `clamp01`):
```python
from .confidence_utils import capture_signal_features, clamp01, compose_confidence
```

And add `hmm_trending_weight` import (line 11 already imports `hmm_regime_weight`):
```python
from ..utils.gradient_utils import hmm_regime_weight, hmm_trending_weight
```

Module-level constants to add:
```python
_MIN_REGIME_WEIGHT: float = 0.30
_MIN_CTF_SCORE: float = 0.25
```

---

### PATTERN 6 — Batch A: New 4-factor Confidence Formula

**For OFIDivergence** — replace the additive confidence block (lines 125-152 of ofi_divergence.py):

**Current (bad) pattern:**
```python
confidence = 0.42
confidence += 0.25 * math.tanh(peak_abs / 3.0)  # principled soft cap

# [EWMA additive bonuses/penalties ±0.04-0.08]
# [rel_volume additive +0.06]

confidence = compose_confidence(confidence)
```

**Target (good) pattern** — 4 named scores with weights summing to 1.0:
```python
magnitude_score = clamp01(math.tanh(peak_abs / 3.0))  # tanh gives principled [0,1]
# EWMA alignment: short + long both agree with direction
ewma5_aligned = ewma5_sign == direction
ewma20_aligned = ewma20_sign == direction
alignment_score = clamp01(
    (1.0 if ewma5_aligned else 0.3) * 0.6
    + (1.0 if ewma20_aligned else 0.3) * 0.4
)
persistence_score = clamp01((count - _MIN_PERSISTENCE) / 5.0)
rel_vol = features.get("rel_volume")
volume_score = clamp01((float(rel_vol) - 1.0) / 1.5) if rel_vol is not None else 0.3

raw_conf = (
    0.40 * magnitude_score
    + 0.25 * alignment_score
    + 0.20 * persistence_score
    + 0.15 * volume_score
)
confidence = compose_confidence(raw_conf)
```

Add `clamp01` to imports (line 28 currently missing it).

---

### PATTERN 7 — validate_tier() Enforcement Change

**File:** `src/intelligence/plugins/base.py`

**Current code** (lines 148-153):
```python
if not hasattr(plugin, "requires_i6_confluence"):
    raise ArchitectureViolation(
        f"I7 plugin '{name}' missing requires_i6_confluence declaration. "
        f"Add: requires_i6_confluence: bool = True  "
        f"(or False with TODO comment if I6 not yet integrated)"
    )
```

**Target code** — add the value check AFTER the existing hasattr check:
```python
if not hasattr(plugin, "requires_i6_confluence"):
    raise ArchitectureViolation(
        f"I7 plugin '{name}' missing requires_i6_confluence declaration. "
        f"Add: requires_i6_confluence: bool = True  "
        f"(or False with TODO comment if I6 not yet integrated)"
    )
if not getattr(plugin, "requires_i6_confluence", None):
    raise ArchitectureViolation(
        f"I7 plugin '{name}' must have requires_i6_confluence=True. "
        f"Phase 119 requires all I7 setups consume I6 cross-timeframe data."
    )
```

This is a two-line addition after line 153 — no existing code is deleted.

---

### PATTERN 8 — Test File Extension

**File:** `tests/unit/intelligence/test_i6_confluence_enforcement.py`

**Current tests (lines 23-67):** parametrize over `TIER_I7` asserting attribute EXISTS and is bool. The `test_false_values_have_todo_rationale` test currently accepts `False` values.

**Changes needed:**
1. `test_false_values_have_todo_rationale` must become `test_all_i7_require_i6_confluence` — assert all plugins have `requires_i6_confluence=True` (no False values expected after Phase 119 completes)
2. Add parametrized test for `shadow_only=True` on all 17 target plugins (or all TIER_I7 plugins)

Pattern for new assertion (copy structure from lines 22-35):
```python
@pytest.mark.parametrize("plugin_name", TIER_I7)
def test_requires_i6_confluence_true(self, plugin_name: str):
    """After Phase 119, every TIER_I7 plugin must have requires_i6_confluence=True."""
    plugin = registry.patterns.get(plugin_name)
    assert plugin is not None
    assert getattr(plugin, "requires_i6_confluence", False) is True, (
        f"I7 plugin {plugin_name!r} has requires_i6_confluence != True. "
        f"Phase 119 requires all I7 setups to have True."
    )

@pytest.mark.parametrize("plugin_name", TIER_I7)
def test_shadow_only_declared(self, plugin_name: str):
    """After Phase 119, all 17 refactored I7 plugins must have shadow_only=True."""
    plugin = registry.patterns.get(plugin_name)
    assert plugin is not None
    assert getattr(plugin, "shadow_only", False) is True, (
        f"I7 plugin {plugin_name!r} missing shadow_only=True. "
        f"Phase 119 requires shadow mode until Phase 120 promotes."
    )
```

**Note:** `test_validate_tier_raises_no_architecture_violation` at lines 37-42 becomes the primary regression test after the D-02 change to `validate_tier()`. It will catch any plugin with `requires_i6_confluence=False` at the architecture level.

**Also update:** `tests/unit/intelligence/test_i7_extrinsic_contract.py` — the `_EXTRINSIC_KEYS` dict at lines 45-54 currently includes `ctf_score: 0.9`. After Phase 119, `ctf_score` IS a gate (not captured-only). The perturbation set for Phase 119 plugins must NOT include `ctf_score` since perturbing it would block the signal at the gate level. The test will need per-plugin perturbation sets or a conditional skip for Phase 119 plugins.

---

## Shared Patterns

### A. 4-Factor Confidence Template (all 17 plugins)
**Source:** `src/intelligence/trading/ofi_continuation.py` lines 138-164
**Apply to:** All 17 plugins that need new confidence formulas (all except MomentumBreakout per D-04)

Core structure:
```python
factor_a_score = clamp01(...)  # primary signal strength
factor_b_score = clamp01(...)  # secondary confirmation
factor_c_score = clamp01(...)  # tertiary signal quality
factor_d_score = clamp01(...)  # volume or regime alignment

raw_conf = (
    W_A * factor_a_score
    + W_B * factor_b_score
    + W_C * factor_c_score
    + W_D * factor_d_score
)  # W_A + W_B + W_C + W_D == 1.0
confidence = compose_confidence(raw_conf)
```

### B. Imports Pattern (all 17 plugins)
**Source:** `src/intelligence/trading/ofi_continuation.py` lines 13-24

Required imports that may be missing in some plugins:
```python
from ..utils.gradient_utils import hmm_regime_weight, hmm_trending_weight
from .confidence_utils import capture_signal_features, clamp01, compose_confidence
from .plugin_utils import no_signal
```

### C. features dict assembly (all 17 plugins)
**Source:** `src/intelligence/trading/ofi_continuation.py` lines 78-86
**Rule:** Must include `**(frames.get("i6") or {})` — this is what `requires_i6_confluence=True` means at the code level. All 17 plugins already do this; verify it stays after any reordering.

### D. OHLCV order invariant (affected: VWAPDeviation, MomentumBreakout, CandlestickPatternSetup, LiquidityHunt, SessionExtremesSetup)
**Rule:** features dict assembly → dual gate → extract_ohlcv/ATR
**Pitfall:** These 5 plugins currently call `extract_ohlcv()` or `df["close"]` before assembling features. The reorder must move the features assembly and dual gate before the first OHLCV access.

---

## No Analog Found

All files have close analogs. No entries.

---

## Per-Plugin Summary Table

| Plugin | Batch | Confidence rewrite? | Gate reorder needed? | regime_type | shadow_only | Notes |
|---|---|---|---|---|---|---|
| OFIDivergence | A | YES — additive → 4-factor | No (features-first already) | `"any"` → use `hmm_trending_weight` | Add | Remove `math.tanh` additive; keep as `magnitude_score` factor |
| FailedBreakout | A | YES | No (features-first already) | `"trend"` | Add | |
| OFISpike | C | Via helper only | Via helper only | `"any"` | Add to plugin class | Helper `detect_spike_signal` carries the refactor |
| CVDSpike | C | Via helper only | Via helper only | `"any"` | Add to plugin class | Same as OFISpike |
| CandlestickPatternSetup | B | YES — binary regime → 4-factor | YES — OHLCV first | `"any"` → use `hmm_trending_weight` | Add | Remove `trend_regime` binary check from gate |
| SessionExtremesSetup | B | YES | YES — `df.close` before gate | `"mean_reversion"` | Add | |
| LiquidityHunt | D | YES | YES — `extract_ohlcv` at line 53 | (verify) | Add only | Already has `requires_i6_confluence=True` |
| DeltaExhaustion | E | YES | YES — `df` before regime check | `"mean_reversion"` | Add | Keep `exempt_exhaustion` profile; do NOT add `apply_exhaustion_boost` |
| LVNBreakout | F | NO (already 4-factor) | No (OHLCV after binary gate) | `"trend"` | Add | Replace binary `hmm in (1,2)` with `hmm_regime_weight` + add I6 gate |
| ORB15 | B | YES — single factor → 4-factor | YES | `"trend"` | Add | |
| ORB30 | B | YES — single factor → 4-factor | YES | `"trend"` | Add | Mirrors ORB15 |
| SecondLegContinuation | H | YES — partially intrinsic | No (OHLCV after binary gate) | `"trend"` | Add | Replace binary `hmm not in (1.0,2.0)` + `hmm_regime_prob < 0.60` |
| VCP | H | YES — single factor | No (state/regime gate before OHLCV) | `"trend"` | Add | Replace binary `hmm not in (1.0,2.0)` |
| VWAPReclaim | G | NO (already 4-factor) | NO (VWAP check before OHLCV is ok) | `"any"` → use `hmm_trending_weight` | Add | Add dual gate after session_vwap null check; trend_align in confidence stays |
| DualDivergence | I | YES — additive magnitudes | No | `"mean_reversion"` (verify) | Add | |
| VWAPDeviation | G | NO (already 4-factor) | YES — `extract_ohlcv` at line 60 | `"mean_reversion"` | Add | Move dual gate before `extract_ohlcv` call |
| MomentumBreakout | J | NO — D-04 keep 3-factor | YES — `extract_ohlcv` at line 58 | `"trend"` | Add | Gates only: add dual gate, `shadow_only=True`, `requires_i6_confluence=True` |

---

## Metadata

**Analog search scope:** `src/intelligence/trading/`, `src/intelligence/plugins/`, `src/intelligence/utils/`, `tests/unit/intelligence/`
**Files scanned:** 7 source files read directly + grep for function signatures
**Pattern extraction date:** 2026-06-10
