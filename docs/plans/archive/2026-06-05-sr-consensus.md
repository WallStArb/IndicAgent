# SR Consensus: Multi-Method Support/Resistance Synthesis

**Date:** 2026-06-05
**Status:** archived
**Type:** Design Specification
**Last Updated:** 2026-06-08
**Resolution:** Implemented — see Phase 116 commits

---

## Execution Summary (2026-06-08)

This design was implemented via Phase 116 commits:
- `2a177463` feat(116-03): add ctx_SRConsensus I4 plugin — zone_engine consensus layer
- `e922ee65` fix(phase-116): expose find_best_level as public zone_engine API
- `bcfb8c32` fix(116): add _round_candidates dedup, add 7 missing sr_consensus tests
- `8ba284f2` docs(phase-116): complete phase execution — SR consensus layer shipped

The SR consensus layer is now production code. This document is preserved for historical reference.

---



Three independent failures cause bad stop and target levels on short timeframes:

1. **`struct_SupportResistance` produces bad inputs.** `cluster_pct = 0.005` is a fixed 0.5% price
   tolerance (37pts on ES at 7400 — two pivots 37pts apart cluster together). The 120-bar lookback
   is timeframe-blind (120 bars of 5m = 10h, 120 bars of 1h = 5 days — same rule applied to both).
   When no real pivot exists the plugin synthesizes `price * 0.98` as a fallback, injecting a
   phantom level 148pts below price that becomes the stop anchor for five I7 plugins.

2. **`zone_engine._SUPPORT_SPECS/_RESISTANCE_SPECS` is incomplete.** Eight sources per direction.
   Missing: fib retracements, prior session H/L, Asian session H/L, VP HVN above/below, AVWAP
   bands, Keltner midline. The existing synthesis engine is sound; its input set is not.

3. **Zone engine result never persists as a feature.** The multi-source synthesis that runs inside
   `frame_trade()` produces `zone_low/zone_high` for entry activation but dies there. Nothing writes
   `sr_nearest_support/resistance` to `intelligence_features`. `trade_framer` and `zone_engine`
   already check `sr_nearest_*` first (Priority 5 in stop resolver, first lookup in zone candidate
   specs) — but the field is always null, so both silently fall back to the raw pivot.

The stop cap (4×ATR per TF) shipped separately and prevents the worst cases. These three steps
improve the quality of the structural stops that fall within the cap.

---

## Design

### Step 1 — Fix `struct_SupportResistance` (I3)

**File:** `src/intelligence/features/i3_structure/support_resistance.py`

**Changes:**

**ATR-proportional clustering.** Replace:
```python
if abs(price - current_cluster[-1][0]) <= current_price * self.cluster_pct
```
with:
```python
if abs(price - current_cluster[-1][0]) <= atr_14 * self.cluster_atr_mult
```
where `cluster_atr_mult: float = 0.5`. The ATR is read from `frames["i1"]` via `get_atr()`. This
makes the cluster radius instrument- and volatility-aware: on ES at ATR=9, clusters within 4.5pts;
on NQ at ATR=20, within 10pts. No per-instrument configuration needed.

**TF-proportional lookback.** Replace the fixed `lookback=120` with a per-TF table:

| TF | Bars | Real time |
|----|------|-----------|
| 1m | 60   | 1h        |
| 5m | 60   | 5h        |
| 15m| 80   | 20h       |
| 1h | 120  | 5 days    |
| 4h | 120  | 20 days   |
| 1d | 60   | 3 months  |

The `timeframe` field is in `frames["i1"]` (from the feature pipeline context injected at bar
processing time). Fall back to 120 if timeframe is absent or unrecognized.

**Kill the synthetic fallback.** Replace:
```python
else:
    nearest_s = {"level": current_price * 0.98, "strength": 0, "latest_idx": 0}
```
with:
```python
else:
    nearest_s = None
```
Return `{}` for `nearest_support` when no real pivot exists. Downstream `trade_framer` falls
through to ATR fallback naturally. Same for `nearest_resistance` when no pivot above price.

**Add volume weighting to pivot strength.** At each pivot bar index `i`, compute:
```python
vol_ratio = volume[i] / mean_volume  # relative volume at the pivot bar
strength = len(cluster_members) * min(2.0, vol_ratio)  # cap at 2× to prevent outlier dominance
```
A pivot formed on 3× average volume scores 3× higher than a thin-air pivot. Uses `volume` column
from `df`.

**No new outputs.** Existing output fields (`nearest_support`, `nearest_resistance`,
`support_strength`, `resistance_strength`, `support_dist_pct`, etc.) are preserved.

---

### Step 2 — Extend `zone_engine` candidate specs

**File:** `src/intelligence/trading/zone_engine.py`

Add missing sources to `_SUPPORT_SPECS` and `_RESISTANCE_SPECS`. Each entry follows the existing
tuple format: `(feature_key, display_name, default_strength, source_tier, source_family)`.

**`_SUPPORT_SPECS` additions:**

```python
("nearest_fib_level",      "fib",          0.6, "i3",  "fib"),      # fib retracement (if below price)
("prior_session_low",      "prior_sess_l",  0.7, "i3",  "session"),
("asian_session_low",      "asian_l",       0.6, "i3",  "session"),
("nearest_hvn_below",      "hvn_below",     0.8, "i4",  "vp_hvn"),  # high-volume node below price
("avwap_lower_band",       "avwap_lower",   0.6, "i4",  "avwap"),
("kc_mid_20",              "kc_mid",        0.5, "i1",  "ma_kc"),    # Keltner midline as dynamic support
```

**`_RESISTANCE_SPECS` additions:**

```python
("nearest_fib_level",      "fib",          0.6, "i3",  "fib"),      # fib retracement (if above price)
("prior_session_high",     "prior_sess_h",  0.7, "i3",  "session"),
("asian_session_high",     "asian_h",       0.6, "i3",  "session"),
("nearest_hvn_above",      "hvn_above",     0.8, "i4",  "vp_hvn"),
("avwap_upper_band",       "avwap_upper",   0.6, "i4",  "avwap"),
("kc_mid_20",              "kc_mid",        0.5, "i1",  "ma_kc"),
```

**Fib directionality.** `nearest_fib_level` is a single value — it could be above or below price.
Add a direction gate in `collect_candidates()`: only include `nearest_fib_level` if the price is on
the correct side (support candidates require `price < current_price`, resistance requires
`price > current_price`). This is consistent with the existing `lo < price < hi` filter that
already handles this automatically.

**`_STRENGTH_FIELD` additions:**

```python
"fib":         "fib_cluster_strength",
"hvn_below":   "nearest_hvn_dist_atr",   # closer HVN = higher strength (invert: 1/(1+dist))
"hvn_above":   "nearest_hvn_dist_atr",
"prior_sess_l": None,                     # use default_strength
"prior_sess_h": None,
"asian_l":      None,
"asian_h":      None,
"avwap_lower":  None,
"avwap_upper":  None,
"kc_mid":       None,
```

For `hvn_below`/`hvn_above` strength: `_resolve_strength` already handles `"age_bars"` keys with
`1/(1 + val/50)`. Add a matching handler for `"dist_atr"` keys: `1/(1 + val)` — closer HVN scores
higher.

**No new zone_engine functions.** The existing `collect_candidates()`, `_find_clusters()`,
`_source_diversity()`, and `_pick_single_best()` functions are unchanged.

---

### Step 3 — New `ctx_SRConsensus` plugin (I4 Wave-B)

**File:** `src/intelligence/context/sr_consensus.py`

**Purpose:** Run the extended zone_engine candidate collection against `current_price ± max_dist`
(not `stop..entry`), find the best support and resistance within the TF stop cap, write
`sr_nearest_support` and `sr_nearest_resistance` to `intelligence_features` so all downstream
consumers see real confluenced levels.

**Placement:** `I4_WAVE_B`. This ensures all I4_WAVE_A outputs (VP HVN, AVWAP bands, Kalman) are
available in `frames["i4"]` at compute time.

**Round number candidates.** The consensus plugin is the correct home for round number detection
since it requires no bar history — only `current_price` and `atr_14`. Compute the price-magnitude
grid:

```python
magnitude = 10 ** math.floor(math.log10(current_price))
grids = [
    (magnitude,       0.8),   # major: 1000 for ES@7400
    (magnitude / 10,  0.6),   # minor: 100
    (magnitude / 20,  0.4),   # sub-minor: 50
]
for grid_size, strength in grids:
    nearest_below = math.floor(current_price / grid_size) * grid_size
    nearest_above = math.ceil(current_price  / grid_size) * grid_size
    # add as ZoneCandidate with source_tier="round", source_family="round_number"
```

These are added to the candidate lists alongside the structural candidates before clustering.

**Max proximity gate.** Use `MAX_STOP_ATR_MULTIPLIER_BY_TF` (already defined in `trade_framer.py`,
re-import or move to a shared constants module). Only candidates within `atr × max_mult` of
`current_price` are included. For 5m this is 4×ATR; for 1h, 6×ATR.

**Logic:**

```python
def compute_full(self, frames):
    features = {**(frames.get("i1") or {}), **(frames.get("i3") or {}),
                **(frames.get("i4") or {}), **(frames.get("smc") or {})}
    current_price = features.get("close_price") or ...
    atr = get_atr(features)
    tf = features.get("timeframe", "")
    max_dist = atr * MAX_STOP_ATR_MULTIPLIER_BY_TF.get(tf, 5.0)

    # Collect support candidates (below current_price, within max_dist)
    support_candidates = collect_sr_candidates(features, direction=-1,
                                               price=current_price, atr=atr,
                                               max_dist=max_dist)
    support_candidates += _round_number_candidates(current_price, atr, max_dist, direction=-1)

    # Collect resistance candidates (above current_price, within max_dist)
    resistance_candidates = collect_sr_candidates(features, direction=1,
                                                  price=current_price, atr=atr,
                                                  max_dist=max_dist)
    resistance_candidates += _round_number_candidates(current_price, atr, max_dist, direction=1)

    sr_support = _best_level(support_candidates, atr)
    sr_resistance = _best_level(resistance_candidates, atr)

    return {
        "sr_nearest_support":            sr_support.price if sr_support else None,
        "sr_nearest_resistance":         sr_resistance.price if sr_resistance else None,
        "sr_support_confluence_score":   sr_support.score if sr_support else 0.0,
        "sr_resistance_confluence_score":sr_resistance.score if sr_resistance else 0.0,
        "sr_support_dist_atr":           abs(current_price - sr_support.price) / atr
                                         if sr_support else None,
        "sr_resistance_dist_atr":        abs(sr_resistance.price - current_price) / atr
                                         if sr_resistance else None,
    }
```

`_best_level()` uses the existing zone_engine clustering: prefer the highest-diversity cluster
(2+ source tiers); fall back to `_pick_single_best()`. Returns a named result with `price` and
`score = source_diversity_count`. No arbitrary weights — source diversity is the score.

**`collect_sr_candidates()`** is a new zone_engine function:

```python
def collect_sr_candidates(features, direction, price, atr, max_dist):
    # direction=-1 → support (below price): lo=price-max_dist, hi=price
    # direction=+1 → resistance (above price): lo=price, hi=price+max_dist
    # Reuses existing _SUPPORT_SPECS/_RESISTANCE_SPECS and _dedup()
```

This is a thin wrapper over the existing `collect_candidates()` logic — same specs, same dedup,
different bounds.

**Schema additions** to `I4Context` in `src/intelligence/schemas.py`:

```python
sr_nearest_support:             float | None = None
sr_nearest_resistance:          float | None = None
sr_support_confluence_score:    float | None = None
sr_resistance_confluence_score: float | None = None
sr_support_dist_atr:            float | None = None
sr_resistance_dist_atr:         float | None = None
```

**Register** in `register_plugins.py`: add `sr_consensus_plugin` to `I4_WAVE_B` and `TIER_I4`.

---

## What Does NOT Change

- `trade_framer.py` — already checks `sr_nearest_support` at Priority 5, `sr_nearest_resistance`
  for shorts. No changes needed; it will simply start receiving real values.
- `zone_engine.py` entry zone path — `collect_candidates()` (bounds = `stop..entry`) is unchanged.
  `collect_sr_candidates()` is additive.
- All I7 plugin logic — unchanged.
- All SMC plugins — unchanged.
- `MAX_STOP_ATR_MULTIPLIER_BY_TF` — already in `trade_framer.py`. Referenced by the consensus
  plugin; if it should be shared, move to `src/intelligence/trading/constants.py` as a separate
  step.

---

## Validation Criteria (post-ship)

Before adding confluence-score-based weights to the stop resolver:

1. **Stop type distribution:** `SELECT stop_type, COUNT(*) FROM signal_ledger GROUP BY stop_type` —
   verify `"atr"` stops decrease as SR consensus starts producing real values.
2. **Outcome by confluence tier:** compare `pnl_r` where `sr_support_confluence_score >= 2` vs
   `= 1` vs `= 0`. If confluence-2 levels produce better outcomes, weight by score in the stop
   resolver. If not, leave it equal.
3. **Synthetic fallback elimination:** `SELECT COUNT(*) FROM intelligence_features WHERE
   (pattern_detections->>'support_dist_pct')::float = 2.0` should drop to near zero after Step 1.

---

## Sequence

Steps are ordered by impact:

1. Step 1 (`struct_SupportResistance`) — fixes the bad input at source. Immediate improvement.
2. Step 2 (zone_engine specs) — extends synthesis coverage. Builds on clean I3 inputs.
3. Step 3 (`ctx_SRConsensus`) — persists the consensus result. Completes the data flow.

Each step is independently shippable and testable.
