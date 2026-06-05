---
phase: 116-sr-consensus
reviewed: 2026-06-05T18:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - src/intelligence/features/i3_structure/support_resistance.py
  - src/intelligence/trading/zone_engine.py
  - src/intelligence/context/sr_consensus.py
  - src/intelligence/schemas.py
  - src/intelligence/register_plugins.py
  - tests/unit/intelligence/test_sr_shared_peaks.py
  - tests/unit/trading/test_zone_engine.py
  - tests/unit/intelligence/context/test_sr_consensus.py
  - tests/unit/intelligence/test_structure_plugins.py
findings:
  critical: 2
  warning: 5
  info: 3
  total: 10
status: issues_found
---

# Phase 116: Code Review Report

**Reviewed:** 2026-06-05T18:00:00Z
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

Phase 116 introduces `ctx_SRConsensus` — a new I4 plugin that fuses structural SR levels, VP levels, and round numbers into unified support/resistance consensus fields. The plugin correctly integrates with the schema and registration system. Two blockers were found: a sort-order violation that causes `_find_clusters` to produce incorrect clusters in `find_best_level`, and a `>` comparison instead of `abs()` in the clustering kernel that has existed in the shared `zone_engine.py` but is now exploited by the new unsorted call path. Both bugs can produce silently wrong SR consensus values without any error signal.

---

## Critical Issues

### CR-01: `_find_clusters` uses non-absolute comparison — produces incorrect clusters on unsorted input

**File:** `src/intelligence/trading/zone_engine.py:325`

**Issue:** The clustering kernel computes `c.price - current[-1].price <= radius` without `abs()`. This is correct only when `candidates` is sorted ascending. `_resolve_zone` (the existing call path) always passes sorted candidates from `collect_candidates`, so this was never triggered. However, `sr_consensus.py` appends `_round_candidates(...)` output directly to the sorted result of `collect_sr_candidates(...)` — and `_round_candidates` generates floor/ceil values in grid order, not price order. For support direction, floor values (lower prices) are appended after higher prices in the already-sorted segment. When those lower-priced round candidates are evaluated by `_find_clusters`, the expression `lower_price - higher_price = negative_value <= radius` is vacuously true, grouping levels that may be 40+ points apart into the same cluster.

**Verified with a concrete case:**

```
collect_sr_candidates: [ZC(7380), ZC(7390)]
_round_candidates:     [ZC(7350)]
combined (unsorted):   [ZC(7380), ZC(7390), ZC(7350)]
_find_clusters result: [[ZC(7390), ZC(7350)]]  <- 40-point spread, clustered incorrectly
```

The `7350` and `7390` candidates are 40 points apart (4.4 ATR at atr=9), far beyond the 0.5 ATR cluster radius. Yet they cluster because `-40 <= 4.5`. This can cause `sr_nearest_support` or `sr_nearest_resistance` to be set to an averaged price of two structurally unrelated levels, with no error raised.

**Fix:** Two changes required together:

1. Sort the combined candidate list in `sr_consensus.py` before passing to `find_best_level`:
```python
# sr_consensus.py lines 60-65
s_cands = sorted(
    collect_sr_candidates(features, -1, current_price, atr, max_dist)
    + _round_candidates(current_price, atr, max_dist, -1),
    key=lambda c: c.price,
)
r_cands = sorted(
    collect_sr_candidates(features, 1, current_price, atr, max_dist)
    + _round_candidates(current_price, atr, max_dist, 1),
    key=lambda c: c.price,
)
```

2. Add defensive `abs()` to `_find_clusters` so callers never need to know about this invariant:
```python
# zone_engine.py line 325
if abs(c.price - current[-1].price) <= radius:
```

---

### CR-02: Duplicate entry of `ctx_SRConsensus` in `I4_WAVE_B`

**File:** `src/intelligence/register_plugins.py:582-586`

**Issue:** `sr_consensus_plugin.name` appears twice in `I4_WAVE_B`:

```python
I4_WAVE_B: list[str] = [
    kalman_trend_plugin.name,
    sr_consensus_plugin.name,  # line 584
    sr_consensus_plugin.name,  # line 585 — duplicate
]
```

The wave lists are the execution schedule used by the intelligence pipeline to dispatch plugins in dependency order. A duplicate name causes the plugin to be dispatched (and executed) twice per bar. Depending on how the pipeline consumer deduplicates, this either wastes compute on a second identical invocation or — if results are merged — overwrites the valid output with a second identical copy. Either way, this is a defect introduced in this phase. The union of `I4_WAVE_A + I4_WAVE_B` still equals `TIER_I4` (set equality holds due to dedup), so `validate_schema_coverage` does not catch this.

**Fix:**
```python
I4_WAVE_B: list[str] = [
    kalman_trend_plugin.name,
    sr_consensus_plugin.name,  # remove the second occurrence
]
```

---

## Warnings

### WR-01: `resistance_age_bars` and `support_age_bars` are off-by-one when `latest_idx == 0`

**File:** `src/intelligence/features/i3_structure/support_resistance.py:93-107`

**Issue:** Both the resistance and support age calculations use a conditional that returns `float(n_bars)` when `latest_idx == 0`, instead of the correct `float(n_bars - 1 - 0) = float(n_bars - 1)`:

```python
# lines 93-97 (resistance) and 104-107 (support)
r_age = (
    float(n_bars - 1 - nearest_r["latest_idx"])
    if nearest_r["latest_idx"] > 0
    else float(n_bars)   # <- should be float(n_bars - 1)
)
```

`latest_idx = 0` is a valid index — it means the pivot is at the earliest bar of the sliced window. The correct age for index 0 in an `n_bars`-length slice is `n_bars - 1` bars. The `> 0` guard was probably intended as a "was this field set?" sentinel, but `latest_idx` is always set from `_finalize_cluster` via `max(idx for _, idx in members)` — there is no unset state. For the `latest_idx == 0` case, the reported age is 1 bar too large. Any consumer that gates on age (e.g., "is this level recent enough?") will see a stale-looking level that is actually one bar fresher.

**Fix:**
```python
r_age = float(n_bars - 1 - nearest_r["latest_idx"])
s_age = float(n_bars - 1 - nearest_s["latest_idx"])
```

---

### WR-02: `find_best_level` consensus `strength` violates the `ZoneCandidate` field contract (`0.0–1.0`)

**File:** `src/intelligence/trading/zone_engine.py:302-308`

**Issue:** `ZoneCandidate.strength` is documented as `# 0.0–1.0 quality weight`. However, when `find_best_level` creates the synthetic consensus result, it sets `strength = float(_source_diversity(best))`. `_source_diversity` counts distinct `source_tier` values — an integer that can be 2, 3, 4, or 5 for a diverse cluster. This value is then exposed as `sr_support_confluence_score` / `sr_resistance_confluence_score` in `I4Context`.

Any downstream I7 plugin that reads `sr_support_confluence_score` and treats it as a 0-1 score will receive a value >= 2 whenever consensus is found. This will feed incorrectly into any confidence formula that expects a normalized score.

```python
# zone_engine.py lines 302-308
return ZoneCandidate(
    price=avg_price,
    name="consensus",
    strength=float(_source_diversity(best)),  # <- can be 2, 3, 4, 5
    source_tier="consensus",
    source_family="consensus",
)
```

**Fix:** Normalize to [0, 1] using the maximum possible diversity (5 distinct tiers: i1, i3, i4, smc, round):
```python
MAX_TIER_DIVERSITY = 5
strength = min(1.0, float(_source_diversity(best)) / MAX_TIER_DIVERSITY)
```

Or alternatively document the confluence score as unbounded and update the `ZoneCandidate` field comment to remove the `0.0–1.0` claim for the consensus case.

---

### WR-03: `sr_nearest_support` / `sr_nearest_resistance` in `_SUPPORT_SPECS` / `_RESISTANCE_SPECS` are labeled as tier `i3` but are I4 outputs

**File:** `src/intelligence/trading/zone_engine.py:65, 82`

**Issue:**
```python
_SUPPORT_SPECS = (
    ("nearest_support",    "support",   0.7, "i3", "sr"),
    ("sr_nearest_support", "sr_support", 0.7, "i3", "sr"),  # <- wrong tier
    ...
)
_RESISTANCE_SPECS = (
    ("nearest_resistance",    "resistance", 0.7, "i3", "sr"),
    ("sr_nearest_resistance", "sr_resist",  0.7, "i3", "sr"),  # <- wrong tier
    ...
)
```

`sr_nearest_support` and `sr_nearest_resistance` are outputs of `ctx_SRConsensus`, which is an I4 plugin. Labeling them `source_tier="i3"` means `_source_diversity` undercounts distinct tiers in clusters where both `nearest_support` (real I3) and `sr_nearest_support` (I4 reprocessed) appear. Both will share `source_tier="i3"`, reducing the diversity count. Since they are also in the same `source_family="sr"`, dedup within the `sr` family will collapse them to one before clustering — so the incorrect tier label has no runtime effect on diversity counts. Still, the label is factually wrong and misleads any future reader or tool that inspects `source_tier`.

**Fix:**
```python
("sr_nearest_support", "sr_support", 0.7, "i4", "sr"),
("sr_nearest_resistance", "sr_resist",  0.7, "i4", "sr"),
```

---

### WR-04: `_round_candidates` produces duplicate levels at same price from different grids

**File:** `src/intelligence/context/sr_consensus.py:85-88`

**Issue:** For some prices, `math.ceil(price / g) * g` evaluates to the same value for two different grid sizes `g`. For example, at `price=4567.25` with `direction=1` (resistance): both `g=100` and `g=50` produce `ceil=4600.0`. Both are added to `res` with `source_family="round_number"` but different names (`round_100` and `round_50`). Since they share the same family, they will pass through `_find_clusters` as a 2-member cluster — but both have `source_tier="round"`, so diversity is 1, and they will NOT create a spurious consensus. However, the duplicate inflates the candidate count and creates unnecessary noise in the level list.

The same case occurs in `collect_candidates` and `collect_sr_candidates` for the VP block: `nearest_hvn_below` appears both from `_SUPPORT_SPECS` (family `vp_hvn`) and from the VP block (family `vp_hvn_below`). These two families are different strings, so they are NOT deduped across families. Two candidates at the same price with different families pass to `find_best_level` / `_find_clusters` — but both share `source_tier="i4"`, so diversity is still 1 (no spurious consensus). The bug is mainly cosmetic but inflates candidate counts in ZoneResult and metrics.

**Fix for `_round_candidates`:**
```python
def _round_candidates(price, atr, max_dist, direction):
    if price <= EPSILON:
        return []
    mag = 10 ** math.floor(math.log10(price))
    lo, hi = (price - max_dist, price) if direction == -1 else (price, price + max_dist)
    seen: set[float] = set()
    res = []
    for g, s in [(mag, 0.8), (mag / 10, 0.6), (mag / 20, 0.4)]:
        for lvl in (math.floor(price / g) * g, math.ceil(price / g) * g):
            if lvl > EPSILON and lo < lvl < hi and lvl not in seen:
                seen.add(lvl)
                res.append(ZoneCandidate(lvl, f"round_{g:.0f}", s, "round", "round_number"))
    return res
```

**Fix for VP block family names:** unify the family name in `_SUPPORT_SPECS`/`_RESISTANCE_SPECS` to match the VP block:
```python
# In _SUPPORT_SPECS:
("nearest_hvn_below", "hvn_below", 0.8, "i4", "vp_hvn_below"),
# In _RESISTANCE_SPECS:
("nearest_hvn_above", "hvn_above", 0.8, "i4", "vp_hvn_above"),
```

---

### WR-05: `SupportResistancePlugin.inputs` annotation is `list[InputSpec]` but default is a tuple

**File:** `src/intelligence/features/i3_structure/support_resistance.py:41`

**Issue:**
```python
inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=120),)
```

The type annotation says `list[InputSpec]` but the default value is a tuple literal `(InputSpec(...),)`. Per `CLAUDE.md`: `tuple[InputSpec, ...]` is the required type for `inputs`. The runtime value is a tuple (as dataclass defaults are not coerced), so any consumer doing `isinstance(plugin.inputs, list)` will get `False`. The `SRConsensusPlugin` in `sr_consensus.py` correctly uses `tuple[InputSpec, ...]`.

**Fix:**
```python
inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=120),)
```

---

## Info

### IN-01: `test_compute_full_delegation` in `test_sr_consensus.py` is a trivial no-op test

**File:** `tests/unit/intelligence/context/test_sr_consensus.py:19-21`

**Issue:** The test creates a 1-row DataFrame (`close=[100.0]`), which fails the `min_lookback=5` guard immediately, returning `{}` from both `compute_full` and `compute_next`. The test asserts `{} == {}`. This passes trivially without exercising any actual logic. The delegation contract (`compute_next` calls `compute_full`) is not tested with real data.

**Fix:** Provide a DataFrame with at least 5 rows and real feature data to exercise the actual computation path.

---

### IN-02: `ctx_SRConsensus` test suite lacks round-number candidate and VP direction tests

**File:** `tests/unit/intelligence/context/test_sr_consensus.py`

**Issue:** The test file contains only 2 tests: metadata assertion and the trivial delegation no-op. No tests cover: actual compute_full output with real features, round-number candidate inclusion/exclusion, VP direction semantics (support vs resistance), consensus vs single-level fallback, or the `sr_support_dist_atr` / `sr_resistance_dist_atr` computation. The `test_zone_engine.py` tests cover `collect_sr_candidates` and `find_best_level` in isolation, but the end-to-end path through `SRConsensusPlugin.compute_full` with non-trivial feature data is untested.

**Fix:** Add integration-level tests that feed realistic feature dicts (i1+i3+i4+smc) and assert on specific output values, edge cases (atr missing, no levels in range), and VP direction correctness.

---

### IN-03: `find_best_level` documentation does not state sorted-input requirement

**File:** `src/intelligence/trading/zone_engine.py:284`

**Issue:** `find_best_level` calls `_find_clusters` internally. `_find_clusters` requires ascending-sorted input for correct results. Neither the `find_best_level` docstring nor its signature documents this invariant. The pre-existing `collect_candidates` and `collect_sr_candidates` callers happen to satisfy the requirement (they return sorted output), but the new `sr_consensus.py` caller broke it by appending `_round_candidates` without resorting. Once CR-01 is fixed (sort before call + abs() in _find_clusters), this invariant can be relaxed — but it should be documented either way.

**Fix:** Add to `find_best_level` docstring: `Candidates must be sorted by price ascending.` (or remove the requirement by applying fix 2 of CR-01).

---

_Reviewed: 2026-06-05T18:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
