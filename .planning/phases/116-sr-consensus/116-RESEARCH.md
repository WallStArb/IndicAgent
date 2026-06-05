# Phase 116: SR Consensus — Multi-Method Support/Resistance Synthesis - Research

**Researched:** 2026-06-05
**Domain:** I3 plugin quality fix, zone_engine extension, I4 context plugin authoring
**Confidence:** HIGH

---

## Summary

Phase 116 has three independent, sequentially shippable steps. All required source feature
fields already exist in the codebase — no new upstream plugins are needed. The schema enforcement
system (`validate_schema_coverage`) will crash at startup if any new plugin outputs fields not
declared in its tier schema; the I4Context schema uses `extra="forbid"`, so the 6 new SR consensus
fields must be added there before the plugin is registered. The zone_engine's `collect_candidates()`
function bounds are `(stop, entry)` — the new `collect_sr_candidates()` public function needs
different bounds `(price - max_dist, price + max_dist)` for the proximity-gated consensus use case.

The existing `I4_WAVE_B` list contains only `kalman_trend` (one plugin). The new `ctx_SRConsensus`
plugin goes directly into that list, making it a two-plugin wave. The executor wave ordering
guarantees that `I4_WAVE_B` runs after `I4_WAVE_A`, which means VP HVN fields, AVWAP bands, and
all WAVE_A context are in `frames["i4"]` by the time `ctx_SRConsensus.compute_full()` executes.

`MAX_STOP_ATR_MULTIPLIER_BY_TF` is defined in `trade_framer.py` with no existing shared constants
module. The spec explicitly permits leaving it there and importing from `trade_framer`; a move to a
new `constants.py` is described as a separate step. The simplest implementation imports the dict
directly from `trade_framer`.

**Primary recommendation:** Implement steps in sequence — Step 1 (fix `struct_SupportResistance`),
Step 2 (extend zone_engine specs), Step 3 (new `ctx_SRConsensus`) — each independently committed
and unit-tested.

---

## Standard Stack

### Core (used by this phase, already in codebase)

| Component | Location | Purpose |
|-----------|----------|---------|
| `SupportResistancePlugin` | `src/intelligence/features/i3_structure/support_resistance.py` | I3 SR plugin to fix |
| `zone_engine` | `src/intelligence/trading/zone_engine.py` | `_SUPPORT_SPECS`, `_RESISTANCE_SPECS`, `ZoneCandidate`, `_dedup()` |
| `I4Context` | `src/intelligence/schemas.py` | Pydantic `extra="forbid"` — new fields must be declared |
| `register_plugins.py` | `src/intelligence/register_plugins.py` | `TIER_I4`, `I4_WAVE_B`, `validate_schema_coverage()` |
| `get_atr()` | `src/intelligence/trading/atr_utils.py` | Null-safe ATR accessor |
| `MAX_STOP_ATR_MULTIPLIER_BY_TF` | `src/intelligence/trading/trade_framer.py:92` | TF-keyed stop cap dict |
| `_fval()` | `src/intelligence/trading/plugin_utils.py` | Null-safe float feature accessor used by zone_engine |

---

## Architecture Patterns

### Plugin Execution Context for I4 Wave-B

The executor injects tier sub-dicts into `frames` as each wave completes. For an I4 Wave-B plugin:

```python
def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
    # All tiers available by Wave-B execution time:
    # frames["i1"] — ATR, kc_mid_20, all I1 indicators
    # frames["i3"] — nearest_fib_level, prior_session_high/low, asian_session_high/low,
    #                nearest_support, nearest_resistance, fib_cluster_strength
    # frames["i4"] — nearest_hvn_above/below, avwap_upper/lower_band (from Wave-A)
    # frames["smc"] — SMC fields (computed in parallel with Wave-A effectively)
    # frames.get("timeframe") is NOT in tier sub-dicts — comes from plugin_input root
```

**Critical:** `timeframe` and `symbol` are injected at the root plugin_input dict, not inside any
tier sub-dict. The executor sets `plugin_input["timeframe"] = tf` directly (executor.py:853).
I4 context plugins read it as `frames.get("timeframe", "")` from the flat frames dict.

The `ctx_SRConsensus.compute_full()` must merge tier sub-dicts manually to get a flat feature
dict for `get_atr()` (which reads `features.get("atr_14")`):

```python
features = {**(frames.get("i1") or {}), **(frames.get("i3") or {}), **(frames.get("i4") or {})}
current_price = features.get("close", 0.0)  # 'close' not 'close_price' in tier sub-dicts
```

Note: `close_price` is a field in `trade_framer.py` staleness-gate check context — it is NOT a
standard feature key from tier sub-dicts. The actual current price for an I4 plugin must be read
from `frames.get("main")["close"].iloc[-1]` (the OHLCV dataframe) OR from `features.get("close")`
if the pipeline injects it. Inspect `kalman_trend.py` for the canonical pattern: it reads
`float(df["close"].iloc[-1])` from `frames.get("main")`.

### Existing I4 Context Plugin Pattern

`kalman_trend.py` is the canonical Wave-B I4 plugin. Pattern:

```python
@dataclass
class MySRConsensusPlugin:
    name: str = "ctx_SRConsensus"
    outputs: frozenset[str] = frozenset({
        "sr_nearest_support", "sr_nearest_resistance",
        "sr_support_confluence_score", "sr_resistance_confluence_score",
        "sr_support_dist_atr", "sr_resistance_dist_atr",
    })
    min_lookback: int = 5
    supports_incremental: bool = False
    capability_tags: frozenset[str] = frozenset({"context"})
    inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=5),)

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        df = frames.get("main")
        if df is None or len(df) < self.min_lookback:
            return {}
        ...

    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        return self.compute_full(windows)
```

### Zone Engine Tuple Format

Confirmed from `zone_engine.py:62-83`:
```python
# (feature_key, display_name, default_strength, source_tier, source_family)
_SUPPORT_SPECS: tuple[tuple[str, str, float, str, str], ...] = (
    ("nearest_support", "support", 0.7, "i3", "sr"),
    ...
)
```

The `_STRENGTH_FIELD` dict maps `display_name` (second element) to a feature key that holds the
strength scalar. For new sources using `None` strength key, `_resolve_strength()` falls back to the
`default_strength` from the spec tuple. This is already handled: when `_STRENGTH_FIELD.get(name)`
returns `None`, the function returns `default`.

### `collect_sr_candidates()` — New Public Function

The existing `collect_candidates(entry, stop)` uses `lo, hi = stop, entry` (long) or `lo, hi = entry, stop` (short).
For the SR consensus use case, bounds are `price - max_dist` to `price + max_dist` split by direction:
- support (`direction=-1`): `lo=price - max_dist, hi=price`
- resistance (`direction=+1`): `lo=price, hi=price + max_dist`

This is a new function that shares `_SUPPORT_SPECS`/`_RESISTANCE_SPECS` and `_dedup()`.

### Schema Addition Pattern

`I4Context` is a Pydantic `BaseModel` with `extra="forbid"`. Adding fields:

```python
# In src/intelligence/schemas.py, inside class I4Context:
# ctx_SRConsensus outputs
sr_nearest_support:             float | None = None
sr_nearest_resistance:          float | None = None
sr_support_confluence_score:    float | None = None
sr_resistance_confluence_score: float | None = None
sr_support_dist_atr:            float | None = None
sr_resistance_dist_atr:         float | None = None
```

Must also add the plugin to `validate_schema_coverage()` I4 tier check list and to `TIER_I4`
and `I4_WAVE_B`.

### Registration Pattern (register_plugins.py)

Three places require updating when adding an I4 plugin:

1. `validate_schema_coverage()` — I4 tier check list (line ~180)
2. `TIER_I4` list (line ~479)
3. `I4_WAVE_B` list (line ~578)

Import the plugin at the top of the file alongside other context imports.

---

## Feature Field Availability (Critical for Step 2 and 3)

All 6 new zone_engine source fields per direction already exist as outputs of upstream plugins:

| Feature Key | Tier | Plugin | Schema Field |
|-------------|------|--------|--------------|
| `nearest_fib_level` | I3 | `struct_FibonacciZones` | `I3Structure.nearest_fib_level` |
| `fib_cluster_strength` | I3 | `struct_FibonacciZones` | `I3Structure.fib_cluster_strength` |
| `prior_session_high` | I3 | `struct_SessionLevels` | `I3Structure.prior_session_high` |
| `prior_session_low` | I3 | `struct_SessionLevels` | `I3Structure.prior_session_low` |
| `asian_session_high` | I3 | `struct_SessionLevels` | `I3Structure.asian_session_high` |
| `asian_session_low` | I3 | `struct_SessionLevels` | `I3Structure.asian_session_low` |
| `nearest_hvn_above` | I4 | `ctx_VolumeProfile` | `I4Context.nearest_hvn_above` |
| `nearest_hvn_below` | I4 | `ctx_VolumeProfile` | `I4Context.nearest_hvn_below` |
| `nearest_hvn_dist_atr` | I4 | `ctx_VolumeProfile` | `I4Context.nearest_hvn_dist_atr` |
| `avwap_upper_band` | I4 | `ctx_AnchoredVWAP` | `I4Context.avwap_upper_band` |
| `avwap_lower_band` | I4 | `ctx_AnchoredVWAP` | `I4Context.avwap_lower_band` |
| `kc_mid_20` | I1 | `KeltnerPlugin` | `I1Indicators` (extra="allow") |

`kc_mid_20` is produced by `KeltnerPlugin` as part of `I1Indicators` (which uses `extra="allow"`),
so it flows through to `frames["i1"]` without a schema declaration needed. No new plugins are
required for any of the 12 new zone_engine source keys.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Candidate deduplication | Custom dedup logic | `_dedup()` in zone_engine |
| Cluster detection | Custom proximity grouping | `_find_clusters()` in zone_engine |
| Best candidate selection | Custom scoring | `_pick_single_best()` in zone_engine |
| ATR reading | `features["atr_14"]` direct access | `get_atr(features)` from `atr_utils.py` |
| Feature float access | `features.get("x") or 0.0` | `_fval(features, "x")` from `plugin_utils.py` |
| HVN strength inversion | Custom formula | Extend `_resolve_strength()` with `dist_atr` handler |

---

## Common Pitfalls

### Pitfall 1: Forgetting `validate_schema_coverage()` Hard Crash

**What goes wrong:** Adding a new plugin that outputs a field not declared in `I4Context` causes
`RuntimeError` at `validate_schema_coverage()` call inside `register_all_plugins()`. The service
crashes at startup.
**How to avoid:** Add all 6 new fields to `I4Context` in `schemas.py` BEFORE adding the plugin to
the `validate_schema_coverage()` check list. The order within the file matters.

### Pitfall 2: `I4Context.extra="forbid"` — No New Undeclared Fields

**What goes wrong:** `ctx_SRConsensus.outputs` must exactly match what is declared in `I4Context`.
Extra keys in the returned dict that aren't in `I4Context` cause a Pydantic validation error at
publish time.
**How to avoid:** Keep `outputs` frozenset and `I4Context` declarations in sync.

### Pitfall 3: `compute_next` Must Delegate to `compute_full`

**What goes wrong:** `compute_next` is called for incremental bar processing. If not implemented,
the plugin never fires in live mode.
**How to avoid:** For non-incremental plugins, implement as `return self.compute_full(windows)`.

### Pitfall 4: Current Price Source

**What goes wrong:** `close_price` is NOT a field produced by the pipeline's tier sub-dicts.
Using `features.get("close_price")` returns `None` in an I4 context plugin.
**How to avoid:** Read current price from `frames.get("main")["close"].iloc[-1]` (the OHLCV df),
which is always available in `frames`.

### Pitfall 5: SR Synthetic Fallback Breaks Existing Test

**What goes wrong:** `test_sr_shared_peaks.py` asserts `nearest_support <= current_price` and
`nearest_resistance >= current_price`. After killing the synthetic fallback, when no real pivot
exists the plugin returns `{}` — tests checking for the output key presence will fail.
**How to avoid:** Update existing tests to assert that when no real pivot exists the key is absent
(or `None`), not that it equals a synthetic value. The tests currently check for key presence and
value relationship to price — both need adjustment for the no-pivot case.

### Pitfall 6: ATR Field Source in `struct_SupportResistance`

**What goes wrong:** `support_resistance.py.compute_full()` receives `frames["main"]` (the OHLCV
dataframe) but NOT `frames["i1"]` — I3 plugins run in Wave 1 alongside I2_WAVE_A, before I4.
However the executor DOES inject `frames["i1"]` for all plugins (set in `plugin_input` at
`executor.py:863-868`).
**How to verify:** Confirm that `frames.get("i1")` is non-None inside `support_resistance.compute_full()`.
The session_context plugin explicitly uses `frames.get("i1")` and runs in I4_WAVE_A — and I3
plugins run in Wave 1. The executor builds `plugin_input["i1"]` before any wave runs (lines 863-868
build all tier sub-dicts from the `intel_event` at the start, not after each wave). So `frames["i1"]`
IS available to I3 plugins — it contains the I1 outputs computed before the wave loop.
**Conclusion:** HIGH confidence that `frames.get("i1")` works in `support_resistance.compute_full()`.

### Pitfall 7: `_STRENGTH_FIELD` Key is `display_name`, Not `feature_key`

**What goes wrong:** `_STRENGTH_FIELD` maps the second tuple element (`display_name`) to a
strength feature key. It does NOT use the first tuple element (`feature_key`). Adding to
`_STRENGTH_FIELD` requires using the `display_name` (e.g., `"fib"`, `"hvn_below"`) as the
key, not `"nearest_fib_level"` or `"nearest_hvn_below"`.

### Pitfall 8: Zone Engine `collect_candidates()` Uses `lo < price < hi` (strict)

**What goes wrong:** The bound check is `lo < price < hi` — prices exactly equal to bound are
excluded. For `collect_sr_candidates()`, set `lo = price - max_dist` and `hi = price` for support
(not `hi = price + epsilon`). Since support candidates are below current price, the strict upper
bound excludes `price` itself which is correct.

### Pitfall 9: `nearest_hvn_dist_atr` Semantics for Strength

**What goes wrong:** The spec says HVN strength = `1/(1 + dist)`. But `nearest_hvn_dist_atr` is a
**distance in ATR units** — it is NOT the same field as `nearest_hvn_above`/`nearest_hvn_below`
(which are price levels). The `_STRENGTH_FIELD` entry for `"hvn_below"` must map to
`"nearest_hvn_dist_atr"` to get the distance for strength calculation. A separate handler is needed
in `_resolve_strength()` to handle the `"dist_atr"` key pattern (analogous to the existing
`"age_bars"` handler).

---

## Code Examples

### Step 1 — ATR-proportional clustering (support_resistance.py)

```python
# Source: src/intelligence/features/i3_structure/support_resistance.py (to modify)
# Current (wrong):
if abs(price - current_cluster[-1][0]) <= current_price * self.cluster_pct

# Replacement:
atr_14 = get_atr(frames.get("i1") or {})
cluster_radius = (atr_14 * self.cluster_atr_mult) if atr_14 else (current_price * 0.005)
if abs(price - current_cluster[-1][0]) <= cluster_radius
```

### Step 1 — TF-proportional lookback

```python
_LOOKBACK_BY_TF: dict[str, int] = {
    "1m": 60, "5m": 60, "15m": 80, "1h": 120, "4h": 120, "1d": 60,
}

def compute_full(self, frames):
    df = frames.get("main")
    tf = frames.get("timeframe") or frames.get("__timeframe__") or ""
    lookback = _LOOKBACK_BY_TF.get(tf, 120)
    if df is None or len(df) < self.min_lookback:
        return {}
    df = df.iloc[-lookback:]  # apply TF-appropriate window
    ...
```

### Step 1 — Kill synthetic fallback

```python
# Current (wrong):
else:
    nearest_s = {"level": current_price * 0.98, "strength": 0, "latest_idx": 0}

# Replacement:
else:
    nearest_s = None

# And in the return block:
if nearest_s is None:
    # No real support pivot — omit keys, downstream falls through to ATR fallback
    result = {
        "nearest_resistance": nearest_r["level"] if nearest_r else None,
        "resistance_strength": ...,
        # nearest_support omitted from return when no real pivot
    }
```

### Step 2 — `_resolve_strength()` extension for HVN dist_atr

```python
def _resolve_strength(features: dict, name: str, default: float) -> float:
    key = _STRENGTH_FIELD.get(name)
    if key is None:
        return default
    val = _fval(features, key)
    if val > EPSILON:
        if "age_bars" in key:
            return min(1.0, 1.0 / (1.0 + val / 50.0))
        if "dist_atr" in key:               # NEW: HVN distance handler
            return min(1.0, 1.0 / (1.0 + val))
        return min(1.0, val)
    return default
```

### Step 3 — `collect_sr_candidates()` (zone_engine.py)

```python
def collect_sr_candidates(
    features: dict[str, Any],
    direction: int,
    price: float,
    atr: float,
    max_dist: float,
) -> list[ZoneCandidate]:
    """Collect SR candidates for ctx_SRConsensus proximity gate.

    direction=-1: support (below price), lo=price-max_dist, hi=price
    direction=+1: resistance (above price), lo=price, hi=price+max_dist
    """
    if direction == 1:
        lo, hi = price, price + max_dist
        specs = _RESISTANCE_SPECS
    else:
        lo, hi = price - max_dist, price
        specs = _SUPPORT_SPECS

    tf = features.get("timeframe", "")
    raw: list[ZoneCandidate] = []
    for feat_key, name, default_str, tier, family in specs:
        p = _fval(features, feat_key)
        if p <= EPSILON or not (lo < p < hi):
            continue
        strength = _resolve_strength(features, name, default_str)
        raw.append(ZoneCandidate(price=p, name=name, strength=strength,
                                 source_tier=tier, source_family=family))

    # VP candidates (same logic as collect_candidates but with new bounds)
    poc = _select_vp(features, tf, "poc_price", "poc_price_rolling")
    c_sess, c_roll, c_name, hvn_key, hvn_name = _VP_DIRECTION[direction]
    companion = _select_vp(features, tf, c_sess, c_roll)
    hvn = _fval(features, hvn_key)
    for p, name in [(poc, "poc"), (companion, c_name), (hvn, hvn_name)]:
        if p > EPSILON and lo < p < hi:
            raw.append(ZoneCandidate(price=p, name=name,
                                     strength=0.8 if name == "poc" else 0.7,
                                     source_tier="i4", source_family=f"vp_{name}"))

    return sorted(_dedup(raw, atr), key=lambda c: c.price)
```

---

## Key Architectural Decisions

### `I4_WAVE_B` Current State

`I4_WAVE_B` currently contains exactly one plugin: `kalman_trend`. Adding `ctx_SRConsensus` makes
it a two-plugin wave that runs in parallel. No ordering constraint exists between Kalman and SR
consensus since they read independent features.

### `MAX_STOP_ATR_MULTIPLIER_BY_TF` Location

No `src/intelligence/trading/constants.py` exists. The spec explicitly says "move to
`constants.py` as a separate step." For Phase 116, import directly from `trade_framer.py`:

```python
from src.intelligence.trading.trade_framer import MAX_STOP_ATR_MULTIPLIER_BY_TF
```

This is a simple import — no circular dependency since `ctx_SRConsensus` lives in
`src/intelligence/context/` and `trade_framer.py` has no imports from the context layer.

### Schema Enforcement Flow

At `register_all_plugins()` exit, `validate_schema_coverage()` is called. It iterates the I4 plugin
list and checks every plugin's `outputs` frozenset against `I4Context.model_fields`. Any gap raises
`RuntimeError`. Therefore: schema fields must be added to `I4Context` first, plugin added to the
`validate_schema_coverage()` I4 check list second, then to `TIER_I4` and `I4_WAVE_B` third.

### Existing Test Coverage Impact

`tests/unit/intelligence/test_sr_shared_peaks.py` — 4 tests, all pass today. Tests that assert
`nearest_support <= current_price` and `nearest_resistance >= current_price` will break when the
synthetic fallback is removed because the test uses random data and may generate no real pivots.
The test must be updated to handle the `{}` return case.

`tests/unit/trading/test_zone_engine.py` — 9 tests, all pass today. Adding new specs to
`_SUPPORT_SPECS`/`_RESISTANCE_SPECS` will increase candidate counts; tests that assert
`len(candidates) > 0` or specific counts may need updating.

---

## Open Questions

1. **`timeframe` key inside I3 plugin `frames`**
   - What we know: executor injects `plugin_input["timeframe"] = tf` at root level (executor.py:853)
   - What's unclear: whether I3 plugins can reliably read `frames.get("timeframe")` or must use
     `frames.get("__timeframe__")`
   - Recommendation: Confirm by checking one existing I3 plugin that reads TF; `session_levels.py`
     likely uses it for Asian session detection.

2. **Volume column name in SR plugin dataframe**
   - What we know: the spec says "uses `volume` column from `df`"
   - What's unclear: whether `df["volume"]` exists in the I3 plugin's OHLCV dataframe or could be
     absent for some instruments
   - Recommendation: Guard with `if "volume" in df.columns` and fall back to `vol_ratio = 1.0`.

3. **Round number `_best_level()` implementation**
   - What we know: spec says "prefer highest-diversity cluster; fall back to `_pick_single_best()`"
   - What's unclear: `_pick_single_best()` signature requires an `entry` float for proximity scoring
   - Recommendation: Pass `current_price` as the `entry` arg to `_pick_single_best()` for the
     consensus use case.

---

## Sources

### Primary (HIGH confidence — code inspection)

- `src/intelligence/features/i3_structure/support_resistance.py` — current plugin implementation
- `src/intelligence/trading/zone_engine.py` — full zone engine, spec formats, all helper functions
- `src/intelligence/schemas.py` — I4Context model fields, extra="forbid" enforcement
- `src/intelligence/register_plugins.py` — TIER_I4, I4_WAVE_A, I4_WAVE_B, validate_schema_coverage
- `src/intelligence/trading/trade_framer.py` — MAX_STOP_ATR_MULTIPLIER_BY_TF location and values
- `src/intelligence/pipeline/executor.py` — wave ordering, plugin_input injection, tier dict building
- `src/intelligence/context/kalman_trend.py` — canonical I4 Wave-B plugin pattern
- `src/intelligence/context/volume_profile.py` — nearest_hvn_above/below/dist_atr fields confirmed
- `src/intelligence/context/anchored_vwap.py` — avwap_upper/lower_band fields confirmed
- `src/intelligence/features/i1_indicators/keltner.py` — kc_mid_20 confirmed in I1 (extra=allow)
- `tests/unit/trading/test_zone_engine.py` — existing zone engine test coverage
- `tests/unit/intelligence/test_sr_shared_peaks.py` — existing SR plugin tests to update

---

## Metadata

**Confidence breakdown:**
- Feature field availability: HIGH — all fields confirmed present in upstream plugins and schemas
- Zone engine tuple format: HIGH — confirmed from source code
- Schema enforcement system: HIGH — confirmed `extra="forbid"` + `validate_schema_coverage()` crash behavior
- Plugin registration flow: HIGH — confirmed 3-location update requirement
- Wave ordering: HIGH — confirmed executor.py wave definitions
- `timeframe` key access: MEDIUM — visible in zone_engine but not verified in I3 plugin context

**Research date:** 2026-06-05
**Valid until:** 2026-07-05 (codebase stable, no fast-moving dependencies)
