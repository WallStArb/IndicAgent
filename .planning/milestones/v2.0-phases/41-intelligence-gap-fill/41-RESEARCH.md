# Phase 41: Intelligence Gap Fill - Research

**Researched:** 2026-03-20
**Domain:** Intelligence layer — cross-TF scoring, volume profile targets, HTF context injection, VWAP/session plugin guards
**Confidence:** HIGH — all findings verified directly against source files

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **INTEL-04 (roll premium) is deferred to Phase 44** — requires back-month IBKR subscriptions. No new IBKR subscriptions in Phase 41.
- **FVG/OB alignment formula**: `score = direction_match_fraction × proximity_decay` per TF, then TF-authority-weighted sum. Proximity: within 1 ATR = full weight, linear decay 1–3 ATR, beyond 3 ATR = zero. ATR already in frames.
- **TF scope for FVG/OB**: higher TFs only. 1m bar uses 5m/15m/1h. 5m bar uses 15m/1h. Lower TFs excluded.
- **Same formula for FVG and OB** with separate output fields. Phase 46 calibration may diverge them if data supports it.
- **Per-TF contributions logged in i6 JSONB** — fully decomposable.
- **TF authority weights**: reuse `_TF_MINUTES` structure already in `cross_timeframe.py`.
- **VP target priority override**: when `distance_to_vah_atr < 0.5` or `distance_to_val_atr < 0.5`, VP candidates elevated to front of ranking. Implemented as `_vp_regime_active(features)` predicate.
- **Near VA boundary**: T1 = POC, T2 = VAH (long) or VAL (short).
- **Inside value area** (`price_in_value_area == 1.0`): T1 = far VA boundary (VAH for longs, VAL for shorts), no T2.
- **TF-based VP source** via `_select_vp(features, tf)` helper: 1m/5m → session VP (`poc_price`, `vah`, `val`); 15m/1h → rolling VP (`poc_price_rolling`, `vah_rolling`, `val_rolling`).
- **HTF pattern**: identical to `_cross_asset_cache` — `signal_generator_service` maintains `_htf_intel_cache: dict[str, dict]` keyed by `"{symbol}:1h"`.
- **HTF injection**: for 1m/5m/15m bars, inject `frames["htf_1h"]` before `compute_full()`. 1h bars need no injection.
- **Zero new subscriptions**: cache populated from existing `intelligence:SYMBOL:TF` stream.
- **trade_framer uses htf_1h for targets only** — not stops.
- **I7 plugins unchanged** — routing logic stays in `signal_generator_service`.
- **VWAP/session TF guard**: `if timeframe not in ("1m", "5m", "15m"): return self._no_signal()` at top of `compute_full()` for `AnchoredVWAPReversion`, `VWAPReclaim`, `POCRejection`, `ORB15`, `ORB30`, `PrevDayLevelTest`.
- **Aggregator guard**: comment + assertion — documentation-only, zero behavioral impact.
- **Plugin state write-back**: comment in both `market_analysis_service.py` and `indicator_service.py` — documentation-only.

### Claude's Discretion

- Exact TF authority weight values for FVG/OB cross-TF scoring (reuse `_TF_MINUTES` ratio or define explicit weights)
- Whether `_vp_regime_active()` is a module-level function or inline predicate in trade_framer
- How `timeframe` is extracted in VWAP plugins (from `frames` dict key or plugin `InputSpec`)

### Deferred Ideas (OUT OF SCOPE)

- **INTEL-04 (roll premium)**: deferred to Phase 44 alongside `ROLL_MONITOR_ENABLED=true`.
- **trade_framer ATR cap tightening**: per-TF caps captured as separate todo.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INTEL-01 | `i6_fvg_tf_alignment` computed from real cross-TF FVG alignment data (replaces `0.0` stub) | `cross_timeframe.py` line 140 confirmed stub; FVG output fields `fvg_type/fvg_top/fvg_bottom` confirmed in `fair_value_gap.py`; `intel_*` frames already flowing through `compute_full()`; `_TF_MINUTES` authority weights already present |
| INTEL-02 | `i6_ob_tf_alignment` computed from real cross-TF Order Block alignment data (replaces `0.0` stub) | `cross_timeframe.py` line 141 confirmed stub; OB output fields `ob_type/ob_top/ob_bottom` confirmed in `order_blocks.py`; same formula and same frame iteration as INTEL-01 |
| INTEL-03 | `trade_framer.py` uses POC/VAH/VAL as primary T1/T2 when near value area boundary | VP fields confirmed in `I4Context` schema (lines 374–388); `_collect_targets_long/short` candidate system confirmed extensible; `_pick_targets()` sorts by ascending RR — VP candidates can be pre-inserted at front |
| INTEL-04 | Roll premium stored in `intelligence_features` | **DEFERRED to Phase 44** per CONTEXT.md |
| INTEL-05 | HTF S/R levels (1h POC/VAH/VAL + I6 CTF data) available to I7 plugins via `trade_framer` context | `_cross_asset_cache` pattern confirmed at line 599–601; frame injection confirmed at lines 1466–1470; `_select_vp()` can read from `htf_1h` when current-TF VP absent |
</phase_requirements>

---

## Summary

Phase 41 fills five intelligence stubs left hardcoded in the codebase. All five changes are contained within the intelligence layer with no new external dependencies, no schema changes, and no new Kafka subscriptions.

The two largest changes — FVG/OB cross-TF alignment scoring in `cross_timeframe.py` and VP targets in `trade_framer.py` — are self-contained additions to existing scoring/candidate systems. The HTF context injection in `signal_generator_service` follows an exact existing pattern (`_cross_asset_cache`). The six VWAP/session plugin TF guards are one-line additions each. The aggregator and plugin state write-back items are documentation-only with no behavioral impact.

The phase is primarily a refactoring and stub-completion exercise over existing code that is already architecturally correct. The key risk is the VP target insertion logic in `trade_framer.py` — the priority override must insert VP candidates before the `min_level < price < max_level` filter runs, or VP levels inside the ATR band will be silently filtered out as too close.

**Primary recommendation:** Implement in five focused plans matching the five areas: (1) FVG/OB alignment, (2) VP targets in trade_framer, (3) HTF context injection, (4) VWAP/session TF guards, (5) aggregator + state write-back documentation.

---

## Standard Stack

### Core

| Component | File | Current State | What Changes |
|-----------|------|---------------|-------------|
| `CrossTimeframeConfluencePlugin` | `src/intelligence/confluence/cross_timeframe.py` | Lines 140–141 return `0.0` stubs | Add `_score_fvg_alignment()` and `_score_ob_alignment()` private methods |
| `frame_trade()` / `_collect_targets_long/short()` | `src/intelligence/trading/trade_framer.py` | No VP candidates in target lists | Add `_select_vp()` helper + `_vp_regime_active()` predicate; insert VP candidates |
| `SignalGeneratorService.__init__` | `services/signal_generator_service.py` | Has `_cross_asset_cache` pattern | Add `_htf_intel_cache: dict[str, dict]` alongside it; populate from existing stream; inject `frames["htf_1h"]` |
| Six VWAP/session plugins | `src/intelligence/trading/anchored_vwap_reversion.py`, `vwap_reclaim.py`, `poc_rejection.py`, `orb15.py`, `orb30.py`, `prev_day_level_test.py` | No TF guard | Add 2-line TF guard at top of each `compute_full()` |
| Aggregator | `src/intelligence/trading/aggregator.py` | Has correct `active = [s for s in all_ranked ...]` at line 189 but no explanatory comment | Add CRITICAL comment |

### No New Dependencies

All functionality is implemented with existing project libraries. No new packages to install.

---

## Architecture Patterns

### Pattern 1: FVG/OB Cross-TF Alignment Scoring

**What:** Add two private scoring methods to `CrossTimeframeConfluencePlugin`. Each iterates `other_intel` frames, reads `fvg_type/fvg_top/fvg_bottom` (or `ob_type/ob_top/ob_bottom`) from each higher-TF frame, and computes `direction_match × proximity_decay` weighted by TF authority.

**Key insight from code review:** `other_intel` is populated from `intel_<tf>` frame keys at line 88–92. These frames contain the full flat features dict from each TF's `intelligence:SYMBOL:TF` event. FVG fields are already in those dicts because `smc_FairValueGap` and `smc_OrderBlocks` are part of the I6 SMC tier that runs in `market_analysis_service` before the intelligence event is published. So the data is already flowing — only the scoring function is missing.

**TF scope filter:** For a 1m bar, `other_intel` contains 5m, 15m, 1h. The filter `_TF_MINUTES.get(tf, 0) > _TF_MINUTES.get(current_tf, 0)` restricts to higher TFs only.

**Proximity decay formula (direction from CONTEXT.md):**
```python
# Source: 41-CONTEXT.md — locked decision
def _proximity_decay(price: float, level_top: float, level_bottom: float, atr: float) -> float:
    """1.0 within 1 ATR of zone midpoint; linear decay to 0 at 3 ATR."""
    if atr <= 0:
        return 0.0
    midpoint = (level_top + level_bottom) / 2.0
    dist_atr = abs(price - midpoint) / atr
    if dist_atr <= 1.0:
        return 1.0
    if dist_atr >= 3.0:
        return 0.0
    return 1.0 - (dist_atr - 1.0) / 2.0
```

**TF authority weighting (Claude's discretion):** The simplest approach reuses `_TF_MINUTES` as raw authority weights normalized across higher TFs present. This matches how `_score_trend_alignment()` handles weights in the existing code.

**Per-TF contribution logging in i6 JSONB:** The decision says "fully decomposable" — this means the raw result dict returned from `compute_full()` can include per-TF breakdown as additional fields. Since `i6_fvg_tf_alignment` and `i6_ob_tf_alignment` are already in the `I6Confluence` schema, per-TF breakdown fields are best stored in the i6 JSONB blob rather than top-level schema fields (no schema migration needed). The per-TF breakdown can be logged via `structlog` at DEBUG level as an alternative that requires no schema change.

### Pattern 2: VP Target Insertion in trade_framer

**What:** The `_collect_targets_long/short` functions build a `candidates` list, filter by `min_level < price < max_level`, sort by distance, then pass to `_pick_targets()` which selects T1/T2/T3 by RR threshold. VP candidates are inserted into this list with priority override.

**Critical sequencing issue:** The current filter `min_level < price < max_level` where `min_level = entry + atr * 0.5` may exclude VP levels that are very close to entry (< 0.5 ATR away). The VP priority override must handle this correctly — when `_vp_regime_active()` is True, the VP candidate should be inserted into the list before filtering, and the proximity condition should be relaxed for VP specifically (the "near VA boundary" condition itself guarantees the level is meaningful even if close).

**Recommended approach:** Insert VP candidates into a separate high-priority list that bypasses the standard `min_level` filter. Then prepend to `valid` after filtering. This keeps the existing filter logic intact while ensuring VP candidates are not silently dropped.

**`_select_vp()` helper reads:**
- 1m/5m: `features.get("poc_price")`, `features.get("vah")`, `features.get("val")` (session VP)
- 15m/1h: `features.get("poc_price_rolling")`, `features.get("vah_rolling")`, `features.get("val_rolling")` (rolling VP)
- For HTF context: `features.get("htf_1h", {})` — falls back to 1h fields from injected HTF frame

**`_vp_regime_active()` reads:** `features.get("distance_to_vah_atr")` and `features.get("distance_to_val_atr")`. Returns True if either is < 0.5. Returns False if both are None (no VP data available).

### Pattern 3: HTF Context Injection

**Exact template** from `signal_generator_service.py` lines 599–601 and 1466–1470:

```python
# In __init__ (alongside _cross_asset_cache):
self._htf_intel_cache: dict[str, dict] = {}  # "{symbol}:1h" -> latest 1h intel payload

# In stream consumer (alongside cross_asset_cache update):
# When processing a "1h" intelligence event, update _htf_intel_cache[f"{symbol}:1h"]

# In frame injection (alongside cross_asset injection):
if timeframe in ("1m", "5m", "15m"):
    frames["htf_1h"] = self._htf_intel_cache.get(f"{symbol}:1h", {})
```

**Zero new subscriptions:** The service already consumes `intelligence:SYMBOL:TF` for all TFs to build `bar_history`. The 1h events are already being consumed — cache population is just an additional dict write per 1h event.

**trade_framer receives `htf_1h` via `features`:** The `_select_vp()` helper in trade_framer receives the full `features` dict (which is already the flat features from the current bar). The `htf_1h` frame needs to be either merged into `features` before calling `frame_trade()` or passed separately. Given `frame_trade()` only takes `features: dict`, the HTF VP fields should be extracted from `frames["htf_1h"]` and merged into `features` with `htf_1h_` prefix before calling `frame_trade()`. This avoids changing `frame_trade()`'s signature.

Alternatively, `_select_vp()` can be a helper called from within `signal_generator_service` before calling `frame_trade()`, passing the merged features. The CONTEXT.md decision "trade_framer uses htf_1h for targets only" implies the merging happens before `frame_trade()` is called.

### Pattern 4: VWAP/Session Plugin TF Guards

**How `timeframe` is available in plugins (Claude's discretion):** Looking at `VWAPReclaimPlugin`, `AnchoredVWAPReversionPlugin`, etc. — none of them currently receive `timeframe` as a parameter. The `frames` dict passed to `compute_full()` does not have a `"timeframe"` key by default. However, `signal_generator_service` has `timeframe` in scope when building `frames` — it can inject `frames["timeframe"] = timeframe` before calling plugin compute. This is the cleanest approach and keeps the guard readable:

```python
# In compute_full():
timeframe = (frames.get("features") or {}).get("timeframe") or frames.get("timeframe", "")
if timeframe not in ("1m", "5m", "15m"):
    return self._no_signal()
```

OR: `signal_generator_service` already passes `timeframe` in `_process_bar` — it can inject `frames["timeframe"] = timeframe` in the frame-building block alongside other injections. This is the simpler path and matches how cross-asset injection works.

**Plugins requiring TF guard (6 total):**
1. `anchored_vwap_reversion.py` — `AnchoredVWAPReversionPlugin`
2. `vwap_reclaim.py` — `VWAPReclaimPlugin`
3. `poc_rejection.py` — `POCRejectionPlugin` (POC-based, session context required)
4. `orb15.py` — `ORB15Plugin` (opening range; meaningless on 1h)
5. `orb30.py` — `ORB30Plugin`
6. `prev_day_level_test.py` — `PrevDayLevelTest` (session-level test; 1h bars are too coarse)

### Anti-Patterns to Avoid

- **Passing `htf_1h` as a top-level `features` key without prefix:** HTF VP fields have the same names as current-TF VP fields (`poc_price`, `vah`, `val`). Merging without prefix would overwrite current-TF values. Always prefix: `htf_1h_poc_price`, `htf_1h_vah`, `htf_1h_val`.
- **VP candidate inside `min_level` filter block:** If `_vp_regime_active()` returns True, VP candidates may be < 0.5 ATR from entry. They must be inserted before the range filter or exempt from it.
- **FVG/OB scoring using current-TF `fvg_*` fields:** The alignment score must only read from `other_intel` (higher TF frames), not from current-TF `features`. The current TF's FVG is the setup being scored — higher-TF FVGs are the confluence confirmation.
- **Not checking for None VP fields:** `poc_price`, `vah`, `val` are `float | None` in `I4Context`. `_select_vp()` must return `None` if any required field is None.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-TF frame access | Custom TF frame fetcher | Existing `intel_<tf>` frame keys in `compute_full(frames)` | Already flowing; accessing other TFs is just `frames.get("intel_5m", {})` |
| ATR reference for proximity decay | Recalculate ATR | `features.get("atr_14")` already in current-bar features | ATR computed by I1, available in every bar's features dict |
| HTF subscription | New Kafka consumer group | Reuse existing `intelligence:SYMBOL:TF` consumer in signal_generator_service | Zero new infrastructure; cache populated from existing message stream |
| VP field availability | New VP computation | `poc_price/vah/val` already in I4Context, computed by `ctx_VolumeProfile` | Phase 34-02 added all required fields; confirmed in schema at lines 374–388 |

---

## Common Pitfalls

### Pitfall 1: FVG/OB Data Not in intel_* Frames for All Symbols
**What goes wrong:** `smc_FairValueGap` and `smc_OrderBlocks` run in `market_analysis_service`. If a symbol is early in its lifecycle or has insufficient bar history, these plugins return `{}` and the intel frame won't have `fvg_type`/`ob_type` fields. The scoring function receives 0/None and scores 0.0 — which is correct behavior, not a bug.
**How to avoid:** `_score_fvg_alignment()` must check `is_num(fvg_type) and fvg_type != 0` before attempting scoring. Return 0.0 if no FVG data. Do not raise exceptions.

### Pitfall 2: VP Candidate Filtered by ATR Range Before Priority Override
**What goes wrong:** `_vp_regime_active()` triggers when `distance_to_vah_atr < 0.5`. The VP level is within 0.5 ATR of current price. The standard `min_level = entry + atr * 0.5` filter will exclude it (target is too close). Priority override has no effect if the VP candidate was already filtered out.
**How to avoid:** Insert VP candidates into a separate `priority_candidates` list. Prepend `priority_candidates` to `valid` after the normal filter runs. `_pick_targets()` scans `candidates` in order and picks by RR — the priority prepend ensures VP comes first if it meets the RR gate.
**Warning signs:** Tests show VP T1 equal to ATR fallback T1 instead of POC. Check that `_vp_regime_active()` is True in the test features and that the VP level passes RR >= 1.5.

### Pitfall 3: HTF VP Fields Overwriting Current-TF VP Fields
**What goes wrong:** Merging `htf_1h` dict directly into `features` causes `poc_price` in features to become the 1h POC, not the current-TF POC. `_select_vp()` for 1m bars would then read the 1h POC as if it were the session POC.
**How to avoid:** Prefix all HTF fields: `features["htf_1h_poc_price"] = htf.get("poc_price")`. `_select_vp()` reads `htf_1h_poc_price` explicitly when `htf_1h` context is needed.

### Pitfall 4: `_no_signal()` Not Defined on All Plugin Classes
**What goes wrong:** ORB15, ORB30, PrevDayLevelTest may define `_no_signal()` differently from `AnchoredVWAPReversionPlugin`. Before adding TF guard, verify the method is available on each plugin class.
**How to avoid:** Check each plugin's `_no_signal()` or equivalent exit pattern before adding the guard. `FVGFillPlugin` returns `{"signal_type": "none", "direction": 0, "confidence": 0.0}` as its no-signal return. Each plugin may differ.

### Pitfall 5: `timeframe` Not Injected Into `frames` Dict
**What goes wrong:** VWAP/session plugins call `frames.get("timeframe")` but the key is not present — returns None. Guard `if None not in ("1m", "5m", "15m")` is True → no-signal fires for every bar including 1m bars.
**How to avoid:** Confirm `signal_generator_service` injects `frames["timeframe"] = timeframe` before any plugin calls `compute_full(frames)`. Add this injection in the frame-building block (line ~1460) alongside other frame injections.

---

## Code Examples

### FVG alignment scoring skeleton
```python
# Source: 41-CONTEXT.md locked formula + existing _score_trend_alignment() pattern
def _score_fvg_alignment(
    self,
    features: dict[str, Any],
    other_intel: dict[str, dict[str, Any]],
    current_tf: str,
) -> float:
    """Direction-weighted FVG proximity score across higher TFs."""
    current_price = features.get("close") or features.get("entry_price") or 0.0
    atr = features.get("atr_14") or 0.0
    cur_trend = self._extract_trend_sign(features)
    if cur_trend == 0 or atr <= 0:
        return 0.0

    cur_tf_min = _TF_MINUTES.get(current_tf, 0)
    total_weight = 0.0
    weighted_sum = 0.0

    for tf, intel in other_intel.items():
        tf_min = _TF_MINUTES.get(tf, 0)
        if tf_min <= cur_tf_min:
            continue  # Only higher TFs
        fvg_type = intel.get("fvg_type") or 0.0
        fvg_top = intel.get("fvg_top") or 0.0
        fvg_bottom = intel.get("fvg_bottom") or 0.0
        if not fvg_type or fvg_top <= 0 or fvg_bottom <= 0:
            continue
        direction_match = 1.0 if int(fvg_type) == cur_trend else -1.0
        decay = _proximity_decay(current_price, fvg_top, fvg_bottom, atr)
        if decay <= 0:
            continue
        w = float(tf_min)  # _TF_MINUTES value as authority weight
        total_weight += w
        weighted_sum += w * direction_match * decay

    if total_weight == 0.0:
        return 0.0
    return clamp(weighted_sum / total_weight)
```

### VP candidate insertion in _collect_targets_long
```python
# Source: 41-CONTEXT.md locked decision + existing _collect_targets_long() pattern
def _select_vp(features: dict[str, Any], tf: str) -> tuple[float, float, float] | None:
    """Return (poc, vah, val) for the appropriate VP track, or None if unavailable."""
    if tf in ("1m", "5m"):
        poc = features.get("poc_price")
        vah = features.get("vah")
        val = features.get("val")
    else:
        poc = features.get("poc_price_rolling")
        vah = features.get("vah_rolling")
        val = features.get("val_rolling")
    # HTF fallback
    if poc is None:
        poc = features.get("htf_1h_poc_price")
        vah = features.get("htf_1h_vah")
        val = features.get("htf_1h_val")
    if poc is None or vah is None or val is None:
        return None
    return float(poc), float(vah), float(val)

def _vp_regime_active(features: dict[str, Any]) -> bool:
    d_vah = features.get("distance_to_vah_atr")
    d_val = features.get("distance_to_val_atr")
    if d_vah is None and d_val is None:
        return False
    return (d_vah is not None and d_vah < 0.5) or (d_val is not None and d_val < 0.5)
```

### TF guard insertion in VWAP/session plugins
```python
# In compute_full() — first lines after df/features extraction
timeframe = frames.get("timeframe", "")
if timeframe not in ("1m", "5m", "15m"):
    return self._no_signal()
```

### `frames["timeframe"]` injection in signal_generator_service
```python
# In _handle_intelligence_event(), around line 1460, alongside other frame injections:
frames = {
    "main": self._get_df(key),
    "features": features,
    "timeframe": timeframe,  # Add this
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `i6_fvg_tf_alignment = 0.0` hardcoded | Real alignment score from FVG data across TFs | Phase 41 | i6_fvg_tf_alignment becomes informative for CIS and CONF-04 weighting |
| `i6_ob_tf_alignment = 0.0` hardcoded | Real alignment score from OB data across TFs | Phase 41 | Same |
| ATR-fallback targets dominant | VP POC/VAH/VAL as primary targets near value area | Phase 41 | Targets anchor to institutional volume levels instead of pure ATR multiples |
| I7 plugins receive only current-TF features | 1m/5m/15m bars receive injected `htf_1h` context | Phase 41 | trade_framer can use 1h VP levels as T2/T3 even on 1m signals |
| VWAP/ORB plugins fire on 1h bars | TF guard blocks non-intraday TFs | Phase 41 | Eliminates meaningless 1h VWAP signals that fire against no real session structure |

---

## Open Questions

1. **`current_price` source in `_score_fvg_alignment()`**
   - What we know: `features` dict contains indicator outputs including `close` price implicitly via bar data, but `features` is the flat output of I1–I6 plugins (not the raw bar). The close price is available as the last row of `frames["main"]` DataFrame, but `_score_fvg_alignment()` only receives `features` (not `frames`).
   - What's unclear: Does the flat features dict include `close_price` or similar? Or should the scoring method receive `frames` instead?
   - Recommendation: Pass `frames` to the scoring method, or extract `close` from `frames["main"].iloc[-1]["close"]` inside `compute_full()` before calling the helper. Alternatively, proximity decay can use `poc_price` from current-TF features as a price proxy (it's already ATR-normalized).

2. **`_no_signal()` method consistency across six VWAP/ORB plugins**
   - What we know: `FVGFillPlugin._no_signal()` returns `{"signal_type": "none", "direction": 0, "confidence": 0.0}`. `AnchoredVWAPReversionPlugin` inherits from no base class — the method is not confirmed to exist.
   - Recommendation: Verify before implementing. If `_no_signal()` is not defined on a given plugin, use `return {"signal_type": "none", "direction": 0, "confidence": 0.0}` directly inline, or add the method.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (confirmed in `.venv/bin/pytest`) |
| Config file | `pytest.ini` / `pyproject.toml` (project standard) |
| Quick run command | `.venv/bin/pytest tests/unit/intelligence/ -x -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INTEL-01 | `i6_fvg_tf_alignment` is non-zero when FVG present on higher TFs | unit | `.venv/bin/pytest tests/unit/intelligence/test_cross_timeframe.py -x` | Yes |
| INTEL-01 | `i6_fvg_tf_alignment` is 0.0 when no FVG data in higher TFs | unit | `.venv/bin/pytest tests/unit/intelligence/test_cross_timeframe.py -x` | Yes |
| INTEL-02 | `i6_ob_tf_alignment` is non-zero when OB present on higher TFs | unit | `.venv/bin/pytest tests/unit/intelligence/test_cross_timeframe.py -x` | Yes |
| INTEL-02 | `i6_ob_tf_alignment` respects direction match | unit | `.venv/bin/pytest tests/unit/intelligence/test_cross_timeframe.py -x` | Yes |
| INTEL-03 | VP T1=POC when `distance_to_vah_atr < 0.5` | unit | `.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py -x` | Yes |
| INTEL-03 | VP T2=VAH for longs near VA boundary | unit | `.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py -x` | Yes |
| INTEL-03 | Inside VA: T1=VAH for longs, no T2 | unit | `.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py -x` | Yes |
| INTEL-03 | `_select_vp()` returns session VP for 1m/5m, rolling for 15m/1h | unit | `.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py -x` | Yes |
| INTEL-05 | HTF VP fields visible in trade_framer when `htf_1h` injected | unit | `.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py -x` | Yes |
| INTEL-01/02 (guard) | VWAP plugins return `_no_signal()` on 1h bar | unit | `.venv/bin/pytest tests/unit/intelligence/trading/ -x` | Yes |
| Aggregator guard | `adjusted_rank` present on all `active` signals | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -x` | Yes |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/intelligence/ -x -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
New test cases must be added to existing test files (not new files):
- [ ] `tests/unit/intelligence/test_cross_timeframe.py` — add `test_fvg_alignment_nonzero_when_fvg_present`, `test_fvg_alignment_zero_no_fvg`, `test_ob_alignment_nonzero_when_ob_present`, `test_fvg_alignment_direction_mismatch_reduces_score`
- [ ] `tests/unit/intelligence/test_trade_framer.py` — add `test_vp_target_near_vah_boundary_long`, `test_vp_target_inside_value_area_long`, `test_select_vp_session_for_short_tf`, `test_select_vp_rolling_for_long_tf`, `test_htf_vp_fallback_when_current_tf_absent`
- [ ] `tests/unit/intelligence/trading/test_anchored_vwap_reversion.py` — add `test_tf_guard_returns_no_signal_on_1h`
- [ ] `tests/unit/intelligence/trading/test_vwap_reclaim.py` — add `test_tf_guard_returns_no_signal_on_1h`
- [ ] `tests/unit/intelligence/trading/test_poc_rejection.py` — add `test_tf_guard_returns_no_signal_on_1h`
- [ ] `tests/unit/intelligence/trading/test_orb15.py` — add `test_tf_guard_returns_no_signal_on_1h`
- [ ] `tests/unit/intelligence/trading/test_orb30.py` — add `test_tf_guard_returns_no_signal_on_1h`
- [ ] `tests/unit/intelligence/trading/test_prev_day_level_test.py` — add `test_tf_guard_returns_no_signal_on_1h`
- [ ] `tests/unit/intelligence/test_aggregator.py` — add `test_active_signals_have_adjusted_rank_from_all_ranked`

---

## Sources

### Primary (HIGH confidence)
- `src/intelligence/confluence/cross_timeframe.py` — confirmed stub locations (lines 140–141), `_TF_MINUTES` weights, `intel_*` frame iteration pattern, `other_intel` dict structure
- `src/intelligence/trading/trade_framer.py` — confirmed `_collect_targets_long/short()` candidate system, `_pick_targets()` RR selection, VP field names expected from features dict
- `src/intelligence/schemas.py` — confirmed VP fields in `I4Context` (lines 374–388), `i6_fvg_tf_alignment/i6_ob_tf_alignment` in `I6Confluence` (lines 684–685)
- `services/signal_generator_service.py` — confirmed `_cross_asset_cache` pattern (lines 599–601), frame injection pattern (lines 1466–1470)
- `src/intelligence/smart_money/fair_value_gap.py` — confirmed `fvg_type`, `fvg_top`, `fvg_bottom` outputs
- `src/intelligence/smart_money/order_blocks.py` — confirmed `ob_type`, `ob_top`, `ob_bottom` outputs, unmitigated filter
- `src/intelligence/trading/anchored_vwap_reversion.py`, `vwap_reclaim.py`, `poc_rejection.py`, `orb15.py`, `orb30.py` — confirmed no TF guard exists; confirmed `_no_signal()` pattern varies by plugin
- `src/intelligence/trading/aggregator.py` — confirmed `active` derived from `all_ranked` at line 189, comment already partially present but insufficient
- `.planning/phases/41-intelligence-gap-fill/41-CONTEXT.md` — all design decisions

### Secondary (MEDIUM confidence)
- `src/intelligence/CLAUDE.md` — confirmed plugin tier structure, aggregator invariant documentation
- `.planning/STATE.md` — confirmed VP field count (I4Context 93 fields), phase rationale

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all files read directly; no external libraries involved
- Architecture: HIGH — all integration points confirmed in source code; patterns are exact copies of existing code
- Pitfalls: HIGH — identified from direct code inspection of filter logic and field naming conflicts
- Test infrastructure: HIGH — test files confirmed to exist; test cases identified as gaps needing new test methods in existing files

**Research date:** 2026-03-20
**Valid until:** 2026-04-20 (stable domain — no external dependencies, no fast-moving libraries)
