# Timeframe Propagation Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Propagate `"timeframe"` into the `features` dict inside every I7 plugin (and `detect_spike_signal`) so `frame_trade`'s `features.get("timeframe", "")` returns the correct TF string rather than `""`, enabling TF-aware stop caps and VP selection.

**Architecture:** The live executor already passes `"timeframe": tf` in the `plugin_input` dict (executor.py:853). However, I7 plugins build a local `features` dict by merging tier sub-dicts (`frames["i1"]`, etc.), which do not carry `"timeframe"`. Adding one line — `features["timeframe"] = frames.get("timeframe") or frames.get("__timeframe__", "")` — after each such merge is the minimal fix. Replay scripts also lack `"timeframe"` in their frames dict; add it there too.

**Tech Stack:** Python 3.12, asyncpg, pytest

## Global Constraints

- No changes to `frame_trade` signature or any function signature in `trade_framer.py`
- No new imports required in any file
- One line injected per plugin after the `features = {...}` merge
- Replay scripts: add two keys (`"timeframe"` and `"__timeframe__"`) for consistency with live executor pattern
- All tests must pass: `.venv/bin/pytest tests/unit/ -q`

---

### Task 1: Update bug todo with corrected diagnosis

**Files:**
- Modify: `.planning/todos/pending/2026-06-18-htf-atr-alignment-bug.md`

**Context:** The original diagnosis said "ATR scale is wrong." The real bug is narrower: `features["timeframe"]` is never populated (tier merge does not include it), so `frame_trade`'s TF-aware stop-cap branch always hits the default. ATR values themselves (from I1) are correct for the bar's native TF because the live pipeline processes HTF bars via `topic_market_bars_htf`.

- [ ] **Step 1: Rewrite the bug title and "The Bug" section**

Replace the content of `.planning/todos/pending/2026-06-18-htf-atr-alignment-bug.md` with:

```markdown
---
name: htf-atr-alignment-bug
type: bug
priority: high
created: 2026-06-18
resolves_phase: null
---

# Bug: timeframe not propagated into features dict — TF-aware stop caps always use default

## The Bug

I7 plugins build a local `features` dict by merging tier sub-dicts:

```python
features = {
    **(frames.get("i1") or {}),
    ...
    **(frames.get("i6") or {}),
}
```

None of the tier dicts carry a `"timeframe"` key. When `frame_trade` calls
`features.get("timeframe", "")` it always gets `""`, so:
- `MAX_STOP_ATR_MULTIPLIER_BY_TF.get("", default)` → always the default stop cap
- `_cfg(f"feature.trade_framer.target_max_atr_{tf}", default)` where `tf=""` → always default
- `_select_vp(features, ...)` which branches on `tf` → always uses the 1m VP track

The ATR values from I1 are correct (live pipeline processes HTF bars with HTF ATR). The
problem is the TF string is not reaching `frame_trade`.

## Evidence

The live executor already sets `"timeframe": tf` in `plugin_input` (executor.py:853), so
`frames.get("timeframe")` is available. It just isn't injected into the local `features` dict.

Replay scripts (`run_historical_pipeline.py`, `feature_replay.py`) also omit `"timeframe"`
from their frames dict, doubling the problem during backfill.

## Fix

1. Add `features["timeframe"] = frames.get("timeframe") or frames.get("__timeframe__", "")`
   after each features merge in every I7 plugin and in `detect_spike_signal`.
2. Add `"__timeframe__": timeframe, "timeframe": timeframe` to the frames dict in both
   replay scripts.

## Key Code Locations

- `src/intelligence/pipeline/executor.py:847-857` — live frames dict (already has "timeframe")
- `src/intelligence/trading/trade_framer.py:1075` — `features.get("timeframe", "")`
- `src/intelligence/trading/trade_framer.py:729` — same in `_collect_target_candidates`
- `src/intelligence/trading/microstructure_utils.py:70-78` — features merge in detect_spike_signal
- `production/scripts/run_historical_pipeline.py:1284` — I7 frames dict (missing "timeframe")
- `production/scripts/feature_replay.py:236` — replay frames dict (missing "timeframe")

## Impact on Phase 132 APR Keys

ATR values are already correct per TF. The stop-cap and target-cap multipliers (`MAX_STOP_ATR_MULTIPLIER_BY_TF`, `feature.trade_framer.target_max_atr_<tf>`) will now
be selected by the actual TF. Phase 132 APR seeds were calibrated against live data and
remain valid; they are per-TF seeds indexed by TF suffix.

## Do Not

- Do not change `frame_trade` signature
- Do not tune `stop_multiplier_floor.*` APR keys until after a 30-day replay with this fix
- Do not run stopped_at_entry verification on FX or futures (spread/roll contamination)
```

- [ ] **Step 2: Verify file saved correctly**

Run: `head -5 .planning/todos/pending/2026-06-18-htf-atr-alignment-bug.md`
Expected: shows `---` frontmatter

---

### Task 2: Fix replay scripts

**Files:**
- Modify: `production/scripts/run_historical_pipeline.py` (~line 1284)
- Modify: `production/scripts/feature_replay.py` (~line 236)

**Context:** Both scripts build a `frames` dict for I7 plugins. Neither includes `"timeframe"` or `"__timeframe__"`. Without these keys, even the Task 3 fix (`frames.get("timeframe") or frames.get("__timeframe__", "")`) returns `""` during replay.

- [ ] **Step 1: Fix run_historical_pipeline.py**

In `run_historical_pipeline.py`, find the frames dict starting at ~line 1284 that looks like:

```python
frames: dict[str, Any] = {
    "main": df,
    "features": features,
    "i1": features,
    "i2": features,
    "i3": features,
    "i4": features,
    "i5": features,
    "smc": features,
    "i6": features,
    "symbol": symbol,
}
```

Add two keys so it becomes:

```python
frames: dict[str, Any] = {
    "main": df,
    "features": features,
    "i1": features,
    "i2": features,
    "i3": features,
    "i4": features,
    "i5": features,
    "smc": features,
    "i6": features,
    "symbol": symbol,
    "__timeframe__": timeframe,
    "timeframe": timeframe,
}
```

- [ ] **Step 2: Fix feature_replay.py**

In `feature_replay.py`, find the frames dict at ~line 236 that looks like:

```python
frames: dict[str, Any] = {
    "features": flat_features,
    "symbol": symbol,
    "tf": tf,
    "i1": flat_features,
    "i2": flat_features,
    "i3": flat_features,
    "i4": flat_features,
    "i5": flat_features,
    "smc": flat_features,
    "i6": flat_features,
}
```

Add:

```python
frames: dict[str, Any] = {
    "features": flat_features,
    "symbol": symbol,
    "tf": tf,
    "__timeframe__": tf,
    "timeframe": tf,
    "i1": flat_features,
    "i2": flat_features,
    "i3": flat_features,
    "i4": flat_features,
    "i5": flat_features,
    "smc": flat_features,
    "i6": flat_features,
}
```

- [ ] **Step 3: Verify with grep**

Run: `grep -n '"timeframe"' production/scripts/run_historical_pipeline.py production/scripts/feature_replay.py`
Expected: both files show `"timeframe": timeframe` and `"timeframe": tf` lines respectively.

---

### Task 3: Fix microstructure_utils.py

**Files:**
- Modify: `src/intelligence/trading/microstructure_utils.py`

**Context:** `detect_spike_signal` builds its own `features` dict (lines 70-78). Both `ofi_spike.py` and `cvd_spike.py` delegate to it. Adding `features["timeframe"]` here fixes both spike plugins in one place.

- [ ] **Step 1: Add timeframe injection**

After the features merge block (lines 70-78), which ends with `}`, add:

```python
features["timeframe"] = frames.get("timeframe") or frames.get("__timeframe__", "")
```

The result should look like:

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
features["timeframe"] = frames.get("timeframe") or frames.get("__timeframe__", "")
```

- [ ] **Step 2: Verify**

Run: `grep -n 'features\["timeframe"\]' src/intelligence/trading/microstructure_utils.py`
Expected: one match

---

### Task 4: Fix all remaining I7 plugins (batch)

**Files** (all in `src/intelligence/trading/`):
- Modify: `anchored_vwap_reversion.py`
- Modify: `candlestick_pattern_setup.py`
- Modify: `choch_reversal.py`
- Modify: `cross_asset_divergence.py`
- Modify: `cvd_divergence.py`
- Modify: `delta_exhaustion.py`
- Modify: `divergence_stack.py`
- Modify: `dual_divergence.py`
- Modify: `failed_breakout.py`
- Modify: `fvg_fill.py`
- Modify: `gap_analysis_setup.py`
- Modify: `hvn_rejection.py`
- Modify: `liquidity_hunt.py`
- Modify: `liquidity_sweep_reclaim.py`
- Modify: `lvn_breakout.py`
- Modify: `mean_reversion.py`
- Modify: `momentum_breakout.py`
- Modify: `mtf_alignment.py`
- Modify: `ofi_continuation.py`
- Modify: `ofi_divergence.py`
- Modify: `orb15.py`
- Modify: `orb30.py`
- Modify: `pattern_completion.py`
- Modify: `poc_rejection.py`
- Modify: `prev_day_level_test.py`
- Modify: `regime_transition.py`
- Modify: `second_leg_continuation.py`
- Modify: `session_extremes_setup.py`
- Modify: `squeeze_expansion.py`
- Modify: `supply_demand_setup.py`
- Modify: `trend_following.py`
- Modify: `vcp.py`
- Modify: `vwap_deviation.py`
- Modify: `vwap_reclaim.py`

**Context:** Every I7 plugin has a `compute_full(self, frames)` method that builds a local `features` dict by merging tier sub-dicts. The pattern is always:

```python
features = {
    **(frames.get("i1") or {}),
    **(frames.get("i2") or {}),
    ...
    **(frames.get("i6") or {}),
}
```

After this block, inject:
```python
features["timeframe"] = frames.get("timeframe") or frames.get("__timeframe__", "")
```

Some plugins also have a secondary features merge or re-assign; only inject after the FIRST primary merge (before the first `features.get(...)` call that consumes feature values).

Some plugins (orb15, orb30, vcp, poc_rejection, anchored_vwap_reversion) already extract `tf = frames.get("__timeframe__", "")` for their own use. Still inject `features["timeframe"]` — the two uses are independent.

- [ ] **Step 1: Use sed to inject the line after each i6 merge closing brace**

Run:
```bash
cd /home/bg/dev/indicagent
for f in \
  src/intelligence/trading/anchored_vwap_reversion.py \
  src/intelligence/trading/candlestick_pattern_setup.py \
  src/intelligence/trading/choch_reversal.py \
  src/intelligence/trading/cross_asset_divergence.py \
  src/intelligence/trading/cvd_divergence.py \
  src/intelligence/trading/delta_exhaustion.py \
  src/intelligence/trading/divergence_stack.py \
  src/intelligence/trading/dual_divergence.py \
  src/intelligence/trading/failed_breakout.py \
  src/intelligence/trading/fvg_fill.py \
  src/intelligence/trading/gap_analysis_setup.py \
  src/intelligence/trading/hvn_rejection.py \
  src/intelligence/trading/liquidity_hunt.py \
  src/intelligence/trading/liquidity_sweep_reclaim.py \
  src/intelligence/trading/lvn_breakout.py \
  src/intelligence/trading/mean_reversion.py \
  src/intelligence/trading/momentum_breakout.py \
  src/intelligence/trading/mtf_alignment.py \
  src/intelligence/trading/ofi_continuation.py \
  src/intelligence/trading/ofi_divergence.py \
  src/intelligence/trading/orb15.py \
  src/intelligence/trading/orb30.py \
  src/intelligence/trading/pattern_completion.py \
  src/intelligence/trading/poc_rejection.py \
  src/intelligence/trading/prev_day_level_test.py \
  src/intelligence/trading/regime_transition.py \
  src/intelligence/trading/second_leg_continuation.py \
  src/intelligence/trading/session_extremes_setup.py \
  src/intelligence/trading/squeeze_expansion.py \
  src/intelligence/trading/supply_demand_setup.py \
  src/intelligence/trading/trend_following.py \
  src/intelligence/trading/vcp.py \
  src/intelligence/trading/vwap_deviation.py \
  src/intelligence/trading/vwap_reclaim.py; do
  echo "--- $f ---"
  grep -n 'frames.get("i6") or {}' "$f" || echo "  (no i6 line found)"
done
```

This shows the line numbers of the `i6` merge in each file. Each plugin closes the features dict on the line after `**(frames.get("i6") or {})`.

- [ ] **Step 2: Apply the injection to each file**

For each plugin, use the Edit tool to add `features["timeframe"] = frames.get("timeframe") or frames.get("__timeframe__", "")` on the line immediately after `}` that closes the features dict.

The pattern to find (example from choch_reversal.py):
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

Replace with:
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
        features["timeframe"] = frames.get("timeframe") or frames.get("__timeframe__", "")
```

Apply this to every file in the list. The indentation is 8 spaces (inside `compute_full` method body).

Some plugins may have a slightly different merge order or missing tiers — use the actual content of the file as the source of truth for the old_string. The key invariant: the injection always goes after the closing `}` of the merge dict.

- [ ] **Step 3: Verify injection count**

Run:
```bash
grep -rl 'features\["timeframe"\]' src/intelligence/trading/ | wc -l
```
Expected: 35 (34 plugins + microstructure_utils.py from Task 3).

---

### Task 5: Write unit tests

**Files:**
- Modify: `tests/unit/intelligence/test_trade_framer.py` (or create if it doesn't exist)

**Context:** Verify that `frame_trade` receives a non-empty `tf` string when a plugin processes a 5m or 1h bar. The test should construct a minimal `features` dict with `"timeframe": "5m"` and verify the TF-specific stop cap (`MAX_STOP_ATR_MULTIPLIER_BY_TF`) is applied.

- [ ] **Step 1: Check if test file exists**

Run: `ls tests/unit/intelligence/test_trade_framer.py 2>/dev/null && echo "exists" || echo "missing"`

- [ ] **Step 2: Write the test**

If the file exists, add to it. If not, create it. Add:

```python
from src.intelligence.trading.trade_framer import frame_trade, MAX_STOP_ATR_MULTIPLIER_BY_TF


def test_frame_trade_uses_timeframe_for_stop_cap():
    """frame_trade must respect the TF-specific stop cap when features["timeframe"] is set."""
    # 5m has a tighter stop cap than the default ("") which allows wider stops.
    # Build an artificial scenario where a structural stop exceeds the 5m cap
    # so the cap fires and produces a tighter ATR-fallback stop.
    tf = "5m"
    cap_5m = MAX_STOP_ATR_MULTIPLIER_BY_TF.get(tf, 3.0)
    cap_default = MAX_STOP_ATR_MULTIPLIER_BY_TF.get("", 5.0)  # wider
    # Only meaningful if caps differ
    assert cap_5m != cap_default or tf in MAX_STOP_ATR_MULTIPLIER_BY_TF, (
        "Test requires 5m to have a distinct cap in MAX_STOP_ATR_MULTIPLIER_BY_TF"
    )

    entry = 100.0
    atr = 1.0
    # Provide a structural stop that exceeds the 5m cap but not the default cap
    # by spoofing a swing_low well below entry
    far_stop_distance = (cap_5m + 0.5) * atr  # guaranteed to exceed 5m cap
    swing_low = entry - far_stop_distance

    features = {
        "timeframe": tf,
        "swing_low_[-1]": swing_low,
        "swing_high_[-1]": entry + 5.0,
    }

    result = frame_trade("trend_long", 1, entry, features, atr)
    stop_distance = abs(result.entry - result.stop)
    # With the 5m cap applied, stop must be ≤ cap_5m × ATR + epsilon
    assert stop_distance <= cap_5m * atr + 0.001, (
        f"Expected stop distance ≤ {cap_5m * atr:.4f} (5m cap) but got {stop_distance:.4f}"
    )


def test_frame_trade_empty_timeframe_uses_default_cap():
    """frame_trade with features['timeframe']='' must fall back to the default cap."""
    entry = 100.0
    atr = 1.0
    features = {
        "timeframe": "",
        "swing_low_[-1]": entry - 10.0,  # extremely far stop
    }
    result = frame_trade("trend_long", 1, entry, features, atr)
    assert result is not None  # just verify it doesn't crash
```

- [ ] **Step 3: Run the test**

Run: `.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py -v -k "timeframe" 2>&1 | tail -20`

If the test fails because `MAX_STOP_ATR_MULTIPLIER_BY_TF` doesn't have a `"5m"` entry with a distinct value, adjust the test to use whichever TF has a defined cap in the dict. First run:

```bash
python3 -c "from src.intelligence.trading.trade_framer import MAX_STOP_ATR_MULTIPLIER_BY_TF; print(MAX_STOP_ATR_MULTIPLIER_BY_TF)"
```

Then update the `tf` variable in the test to match an entry that exists.

---

### Task 6: Run full unit test suite and commit

**Files:** None

- [ ] **Step 1: Run full unit test suite**

Run: `.venv/bin/pytest tests/unit/ -q 2>&1 | tail -20`
Expected: all green. Fix any failures before proceeding.

- [ ] **Step 2: Run ruff and black**

Run: `.venv/bin/ruff check . --fix && .venv/bin/black .`

- [ ] **Step 3: Commit**

```bash
git add \
  .planning/todos/pending/2026-06-18-htf-atr-alignment-bug.md \
  production/scripts/run_historical_pipeline.py \
  production/scripts/feature_replay.py \
  src/intelligence/trading/microstructure_utils.py \
  src/intelligence/trading/anchored_vwap_reversion.py \
  src/intelligence/trading/candlestick_pattern_setup.py \
  src/intelligence/trading/choch_reversal.py \
  src/intelligence/trading/cross_asset_divergence.py \
  src/intelligence/trading/cvd_divergence.py \
  src/intelligence/trading/delta_exhaustion.py \
  src/intelligence/trading/divergence_stack.py \
  src/intelligence/trading/dual_divergence.py \
  src/intelligence/trading/failed_breakout.py \
  src/intelligence/trading/fvg_fill.py \
  src/intelligence/trading/gap_analysis_setup.py \
  src/intelligence/trading/hvn_rejection.py \
  src/intelligence/trading/liquidity_hunt.py \
  src/intelligence/trading/liquidity_sweep_reclaim.py \
  src/intelligence/trading/lvn_breakout.py \
  src/intelligence/trading/mean_reversion.py \
  src/intelligence/trading/momentum_breakout.py \
  src/intelligence/trading/mtf_alignment.py \
  src/intelligence/trading/ofi_continuation.py \
  src/intelligence/trading/ofi_divergence.py \
  src/intelligence/trading/orb15.py \
  src/intelligence/trading/orb30.py \
  src/intelligence/trading/pattern_completion.py \
  src/intelligence/trading/poc_rejection.py \
  src/intelligence/trading/prev_day_level_test.py \
  src/intelligence/trading/regime_transition.py \
  src/intelligence/trading/second_leg_continuation.py \
  src/intelligence/trading/session_extremes_setup.py \
  src/intelligence/trading/squeeze_expansion.py \
  src/intelligence/trading/supply_demand_setup.py \
  src/intelligence/trading/trend_following.py \
  src/intelligence/trading/vcp.py \
  src/intelligence/trading/vwap_deviation.py \
  src/intelligence/trading/vwap_reclaim.py
git commit -m "fix: propagate timeframe into I7 plugin features dict for TF-aware stop caps"
```
