# Phase 44: I7 DAG Refactor — Research

**Researched:** 2026-03-20
**Domain:** Python plugin architecture refactor — I7 trading layer
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Plugin utility extraction — class design**
- D-01: Extract shared I7 helpers as module-level utility functions in `plugin_utils.py` — NOT a `BaseI7Plugin` class or mixin.
- D-02: Rationale: `PatternPlugin` is already a Protocol (not a base class). `@dataclass` + Protocol is the clean DAG contract — class inheritance introduces hidden coupling and MRO complexity. Functions compose; hierarchies couple. A new plugin author should read one existing plugin, copy imports, never understand a class hierarchy.
- D-03: `plugin_utils.py` contains: `no_signal() → dict`, `extract_ohlcv(frames, min_bars) → tuple | None`, `default_compute_next()`, `signal_type_for_direction(direction) → str` (the `"_long"`/`"_short"` suffix helper).
- D-04: All 36 plugins import from `plugin_utils` explicitly. No magic inheritance.

**ATR utility**
- D-05: `atr_utils.py` is a thin null-guard wrapper around I1's `atr_14` feature — it is NOT a recomputer.
- D-06: Pattern: read `features.get("atr_14")`, validate > 0, return float. If missing or ≤ 0, return `None` and let the caller decide (typically `_no_signal()`).
- D-07: ATR is computed once in I1 (`atr_14`). Recomputing it in 17 plugins violates the data-quality-over-model-complexity principle.

**Stop/target placement — `position_utils` is dropped**
- D-08: `position_utils.py` is NOT created.
- D-09: `trade_framer.py` is the single source of truth for stop sizing — GARCH multipliers, FVG structural stops, stop_basis classification, chandelier logic all live there.
- D-10: The 14 plugins doing inline ATR stop placement are refactored to call `trade_framer.frame_trade()`. If `trade_framer`'s interface is too heavy for a plugin, expose a lighter helper function from within `trade_framer` — not a new module.
- D-11: `signal_type_for_direction()` (the string suffix helper) lives in `plugin_utils.py`.

**Confidence utilities**
- D-12: `confidence_utils.py` provides `compose_confidence()` with two named constants: `CONF_FLOOR = 0.10`, `CONF_CEIL = 0.95`.
- D-13: Constants are module-level (not function arguments) — simple, tunable in one place without touching 36 files.
- D-14: All 36 plugins route through `compose_confidence()`. Zero inline `min()`/`max()` clamping in plugin bodies.

**validate_signal() failure mode**
- D-15: Validation failure = log + drop + Prometheus counter. Never silent drop, never hard crash.
- D-16: Full signal dict + failure reason emitted to structured logger at ERROR level.
- D-17: Prometheus counter `signal_validation_failures_total{plugin=name}` — spikes are observable without crashing the pipeline.
- D-18: Dropped signals do not reach the aggregator. Invalid data must not enter the ledger.
- D-19: Rationale: a validation failure is signal about signal quality.

**cross_timeframe.py decomposition**
- D-20: `cross_timeframe.py` (460 lines) splits into 3 modules by computation stage:
  - `confluence_weights.py` — TF authority weights, recency decay, frame extraction helpers. Pure math, no market domain knowledge.
  - `confluence_alignment.py` — trend/structure/regime/pattern scoring functions.
  - `confluence_smc.py` — BOS, FVG, OB alignment scoring. SMC-specific domain logic.
- D-21: `CrossTimeframeConfluencePlugin` class stays intact — imports from the three modules and orchestrates.
- D-22: All existing I6 tests pass unchanged (the class interface doesn't change).

**composites/common.py promotion**
- D-23: `composites/common.py` promoted to `src/intelligence/utils/common.py` — tier-agnostic.
- D-24: I2 composites updated to import from new path. I7 plugins that benefit from these utilities adopt them.
- D-25: Zero imports from `composites/common.py` after migration.

**OFI/CVD type fix scope**
- D-26: Fix all 8 microstructure plugins, not just OFISpike + OFIContinuation.
- D-27: All 8 must return valid `stop_loss` (float), `targets` (non-empty list of floats), `regime_context` (str).

**make_signal() factory adoption**
- D-29: `make_signal()` becomes the only signal dict construction point in `signal_generator_service`.
- D-30: `validate_signal()` called on every signal before aggregation — not optional.
- D-31: Plugin output scope for Phase 44: plugins continue to assemble the full signal dict internally.

### Claude's Discretion

- Internal implementation of `compose_confidence()` formula
- Whether `atr_utils` exposes one function or two (extract vs validate)
- Exact Prometheus counter label names
- Module docstrings and type annotations on new utilities
- Order of plugin migration within each plan

### Deferred Ideas (OUT OF SCOPE)

- Typed intermediate plugin output (direction + raw_confidence only, no dict assembly in plugin) — Phase 45+
- Per-plugin confidence floor/ceiling overrides
- I6 → I7 confluence wiring (ctf_* scores in confidence calculation) — Phase 45
- Exhaustion wiring to all applicable plugins — Phase 45
- Prometheus alert rules for validation failure spikes — Phase 50
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DAG-01 | `atr_utils.py` exists; `plugin_utils.py` with `no_signal`, `extract_ohlcv`, `default_compute_next`, `signal_type_for_direction`; zero inline ATR fallback in 17 affected plugins; 14 inline-stop plugins route through `trade_framer.frame_trade()` | Confirmed: all 7 microstructure plugins output `stop_loss: None` / `targets: None`; `frame_trade(setup_type, direction, entry, features, atr)` interface is already the correct target; `atr_14` is the feature key to wrap |
| DAG-02 | All 36 I7 plugins use `plugin_utils` functions for `_no_signal()`, `compute_next()`, OHLCV extraction — grep confirms no duplicates | Confirmed: every plugin inspected has identical `_no_signal()` static method and `compute_next()` delegation pattern; OHLCV extraction is `frames.get("main")` + null guard + `to_numpy()` repeated verbatim |
| DAG-03 | `confidence_utils.compose_confidence()` enforces `[0.10, 0.95]` system contract; all 36 plugins use it; zero raw `min()`/`max()` clamping in plugin bodies | Confirmed: `trend_following.py` shows the current inconsistent pattern: raw `min(1.0, max(0.0, raw_conf))` then `min(0.95, max(0.10, confidence))`; two-step clamping needs consolidation into one utility call |
| DAG-04 | `validate_tier()` hard-crashes on missing `regime_type`; `cross_timeframe.py` split into 3 modules; `utils/common.py` exists; I2 imports updated; OFI/CVD type fixes; `make_signal()` factory wired in `signal_generator_service`; `validate_signal()` called pre-aggregation | Confirmed: `cross_timeframe.py` is 464 lines with 5 distinct computation groups; `utils/common.py` doesn't exist yet (only `utils.py`); all 8 microstructure plugins return `stop_loss: None`, `targets: None`, `regime_context: dict` |
</phase_requirements>

## Summary

Phase 44 is a pure structural refactor of the I7 trading layer. No signal behavior changes. The goal is to eliminate ~458 LOC of copy-pasted boilerplate across 36 plugins by creating 3 new utility modules (`plugin_utils.py`, `atr_utils.py`, `confidence_utils.py`), promoting `composites/common.py` to `utils/common.py`, decomposing `cross_timeframe.py` into 3 focused modules, fixing type contract violations in all 8 microstructure plugins, and enforcing `make_signal()` / `validate_signal()` at the aggregation boundary.

The critical architectural decision (D-01 through D-04) is **no inheritance**: utility functions only. This preserves the `@dataclass + PatternPlugin Protocol` contract that is the project's clean DAG pattern. Every change is mechanically verifiable — before and after grep confirms the cleanup.

**Primary recommendation:** Sequence the work in 4 plans: (1) `plugin_utils.py` + `atr_utils.py` + stop routing → `frame_trade()`; (2) `confidence_utils.py` + wire all 36 plugins; (3) `validate_tier()` enforcement + `cross_timeframe.py` decomposition; (4) `utils/common.py` promotion + microstructure type fixes + `make_signal()` factory wiring. Plans 1–3 are independent of Plan 4 (Plan 4 has the highest blast radius for existing imports).

## Standard Stack

### Core (all existing project dependencies — no new libraries needed)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python dataclasses | stdlib | Plugin `@dataclass` pattern | Already the project-wide plugin contract |
| prometheus_client | installed | Metrics counter for `signal_validation_failures_total` | `src/observability/metrics.py` already provides `counter()` helper |
| structlog | installed | Structured logging for validation failure ERROR events | Project-wide logging standard via `setup_service_logging()` |
| numpy | installed | `to_numpy()` in `extract_ohlcv`, ATR mean fallback (eliminated by atr_utils) | Already used in all plugins |

### No New Dependencies
Phase 44 introduces zero new packages. All new modules are pure Python using existing imports.

**Installation:** None required.

## Architecture Patterns

### Recommended Project Structure (after Phase 44)
```
src/intelligence/
├── trading/
│   ├── plugin_utils.py          # NEW: no_signal, extract_ohlcv, default_compute_next, signal_type_for_direction
│   ├── atr_utils.py             # NEW: get_atr(features) → float | None
│   ├── confidence_utils.py      # NEW: compose_confidence(), CONF_FLOOR, CONF_CEIL
│   ├── trade_framer.py          # EXISTING: frame_trade() — canonical stop/target
│   ├── signal_schema.py         # EXISTING: make_signal(), validate_signal()
│   ├── exhaustion_utils.py      # EXISTING: apply_exhaustion_boost, apply_exhaustion_guard
│   └── [36 plugin files]        # ALL: import from plugin_utils, atr_utils, confidence_utils
├── confluence/
│   ├── cross_timeframe.py       # EXISTING class, now thin orchestrator
│   ├── confluence_weights.py    # NEW: _TF_MINUTES, _get_recency_weight, _extract_trend_sign, _sign
│   ├── confluence_alignment.py  # NEW: _score_trend_alignment, _score_structure_alignment, _score_regime_agreement, _score_pattern_confirmation
│   └── confluence_smc.py        # NEW: _score_smc_bos_alignment, _score_fvg_alignment, _score_ob_alignment, _score_i2_events
├── utils/
│   └── common.py                # NEW (promoted from composites/common.py): is_num, crossover_detect, threshold_cross, track_bars_ago
├── composites/
│   ├── common.py                # RETIRED: zero imports after migration; delete or leave empty with deprecation notice
│   └── [11 composite files]    # ALL: updated to import is_num etc from src.intelligence.utils.common
└── utils.py                     # EXISTING: is_num (different version — math.isfinite guard), clamp, find_peaks, etc.
```

**Critical note on `is_num` collision:** `src/intelligence/utils.py` already exports `is_num` (with `math.isfinite` guard — returns False for NaN/Inf). `composites/common.py` also exports `is_num` (simpler — just `isinstance(x, int | float)`). The `utils/common.py` promotion should use the composites version verbatim (no behavior change for I2 composites that import it). The `utils.py` version is a separate, stricter utility used by `cross_timeframe.py`. These coexist without conflict — different import paths, different callers.

### Pattern 1: Plugin Utility Function (no_signal)

**What:** Replace all 36 identical `_no_signal()` static method definitions with one import.

**Current (repeated in every plugin):**
```python
@staticmethod
def _no_signal() -> dict[str, Any]:
    return {"signal_type": "none", "direction": 0, "confidence": 0.0}
```

**After:**
```python
# plugin_utils.py
def no_signal() -> dict[str, Any]:
    return {"signal_type": "none", "direction": 0, "confidence": 0.0}

# In plugin:
from .plugin_utils import no_signal
# ...
return no_signal()
```

### Pattern 2: OHLCV Extraction (extract_ohlcv)

**What:** Replace 36 identical `frames.get("main")` + null guard + `to_numpy()` blocks.

**Current (repeated verbatim):**
```python
df = frames.get("main")
features = frames.get("features") or {}
if df is None or len(df) < self.min_lookback:
    return self._no_signal()

close = df["close"].to_numpy(dtype=float)
high = df["high"].to_numpy(dtype=float)
low = df["low"].to_numpy(dtype=float)
```

**After:**
```python
# plugin_utils.py
def extract_ohlcv(frames: dict[str, Any], min_bars: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
    """Extract (open, high, low, close) arrays. Returns None if insufficient data."""
    df = frames.get("main")
    if df is None or len(df) < min_bars:
        return None
    return (
        df["open"].to_numpy(dtype=float),
        df["high"].to_numpy(dtype=float),
        df["low"].to_numpy(dtype=float),
        df["close"].to_numpy(dtype=float),
    )

# In plugin:
result = extract_ohlcv(frames, self.min_lookback)
if result is None:
    return no_signal()
open_, high, low, close = result
features = frames.get("features") or {}
```

### Pattern 3: ATR Utility (atr_utils)

**What:** Replace 17 plugins' `features.get("atr_14", 0.0)` + `np.mean(high - low)` fallback + zero guard with a single wrapper.

**Current (D-06 confirmed: the fallback recomputation was a workaround):**
```python
atr = features.get("atr_14", 0.0)
if atr <= 0:
    atr = float(np.mean(high[-14:] - low[-14:]))  # <-- recomputation violation
if atr <= 0:
    return self._no_signal()
```

**After:**
```python
# atr_utils.py
def get_atr(features: dict[str, Any]) -> float | None:
    """Return atr_14 from I1 features, or None if unavailable/invalid."""
    val = features.get("atr_14")
    if val is None:
        return None
    f = float(val)
    return f if f > 0 else None

# In plugin:
atr = get_atr(features)
if atr is None:
    return no_signal()
```

### Pattern 4: Confidence Composition (confidence_utils)

**What:** Replace the inconsistent two-step clamping pattern with one function.

**Current (from trend_following.py — inconsistent floor/ceiling across plugins):**
```python
confidence = round(min(1.0, max(0.0, raw_conf)), 4)  # first clamp to [0, 1]
# ... adjustments ...
confidence = round(min(0.95, max(0.10, confidence)), 4)  # then to [0.10, 0.95]
```

**After:**
```python
# confidence_utils.py
CONF_FLOOR: float = 0.10
CONF_CEIL: float = 0.95

def compose_confidence(raw: float) -> float:
    """Clamp raw confidence to the system contract [CONF_FLOOR, CONF_CEIL]."""
    return round(max(CONF_FLOOR, min(CONF_CEIL, raw)), 4)

# In plugin:
confidence = compose_confidence(raw_conf)
```

### Pattern 5: Stop Routing to trade_framer (for 14 inline-stop plugins)

**What:** The 14 plugins that build inline ATR stops/targets should call `frame_trade()`.

**Current (from trend_following.py — inline ATR stop):**
```python
if direction == 1:
    stop = entry - atr * self.atr_stop_multiplier
    targets = [round(entry + atr * m, 2) for m in self.atr_target_multipliers]
else:
    stop = entry + atr * self.atr_stop_multiplier
    targets = [round(entry - atr * m, 2) for m in self.atr_target_multipliers]
```

**After:**
```python
from .trade_framer import frame_trade
# ...
tf = frame_trade(signal_type, direction, entry, features, atr)
stop = tf.stop
targets = [t.price for t in tf.targets]
```

**Important:** `frame_trade(setup_type, direction, entry, features, atr)` is the correct signature. The `setup_type` string is already produced by `signal_type_for_direction()`. If `TradeFrame.viable` is False, plugin should call `no_signal()`.

### Pattern 6: signal_type_for_direction

**What:** Replace 15 plugins' `"trend_long" if direction == 1 else "trend_short"` (with varying prefixes) with a helper.

**After:**
```python
# plugin_utils.py
def signal_type_for_direction(prefix: str, direction: int) -> str:
    """Return '{prefix}_long' or '{prefix}_short'."""
    return f"{prefix}_long" if direction == 1 else f"{prefix}_short"
```

### Pattern 7: Microstructure Plugin Type Fix

**What:** All 8 microstructure plugins (`ofi_spike`, `ofi_divergence`, `ofi_continuation`, `cvd_spike`, `cvd_divergence`, `delta_exhaustion`, `dual_divergence`, `cross_asset_divergence`) return `stop_loss: None`, `targets: None`, `regime_context: dict`. All three must be fixed.

**Required output format:**
```python
# regime_context: str (not dict)
regime_context = f"hmm_{hmm_regime}" if hmm_regime is not None else "any"

# stop_loss + targets: ATR-based via frame_trade()
# OR if no structural context, simple ATR fallback
atr = get_atr(features)  # from atr_utils
if atr is None:
    return no_signal()
tf = frame_trade(signal_type, direction, entry, features, atr)
stop = tf.stop
targets = [t.price for t in tf.targets]
```

**Note on cross_asset_divergence:** Already calls `frame_trade()` and extracts `target_1`, `target_2`, `target_full`. However it returns `regime_context` as a dict. Fix is to stringify it.

### Pattern 8: cross_timeframe.py Decomposition

**What:** Split 464-line monolith into 3 modules by computation stage. The class remains intact and orchestrates.

**Split map (verified by reading the actual file):**

`confluence_weights.py` (lines ~1-58 + `_get_recency_weight`, `_extract_trend_sign`, `_sign`, `_proximity_decay`):
```python
# Pure numeric helpers — no market concepts
_TF_MINUTES: dict[str, int]
def _sign(x: float) -> int
def _proximity_decay(price, level_top, level_bottom, atr) -> float
def get_recency_weight(frames, tf) -> float
def extract_trend_sign(data) -> int
```

`confluence_alignment.py` (trend/structure/regime/pattern/I2 scoring — lines ~193-461):
```python
def score_trend_alignment(cur_trend, other_intel, weights) -> float
def score_structure_alignment(features, other_intel, weights) -> float
def score_regime_agreement(features, other_intel, weights) -> float
def score_pattern_confirmation(features, other_intel) -> float
def score_i2_events(features) -> float
# Also: _I2_BULLISH_EVENTS, _I2_BEARISH_EVENTS constants
```

`confluence_smc.py` (SMC/FVG/OB scoring — lines ~321-439):
```python
def score_smc_bos_alignment(features, other_intel, weights, extract_trend_sign_fn) -> float
def score_fvg_alignment(features, other_intel, current_tf, cur_trend, proximity_decay_fn) -> tuple[float, dict]
def score_ob_alignment(features, other_intel, current_tf, cur_trend, proximity_decay_fn) -> tuple[float, dict]
```

`cross_timeframe.py` (reduced to orchestrator — imports from all three, `CrossTimeframeConfluencePlugin.compute_full()` unchanged):
```python
from .confluence_weights import _TF_MINUTES, get_recency_weight, extract_trend_sign
from .confluence_alignment import score_trend_alignment, ...
from .confluence_smc import score_fvg_alignment, ...
# CrossTimeframeConfluencePlugin class with same interface as today
```

**Zero downstream change:** `market_analysis_service.py` imports `CrossTimeframeConfluencePlugin` — the class interface is unchanged.

### Anti-Patterns to Avoid

- **Inheritance for shared behavior:** Do not add `BaseI7Plugin` class. The Protocol + `@dataclass` pattern is the contract.
- **Recomputing ATR in plugins:** `atr_utils.get_atr()` must NOT call `np.mean(high - low)`. If ATR is missing from I1 features, return `None` and let plugin call `no_signal()`. The fallback recomputation was a workaround.
- **Parallel stop-sizing modules:** `position_utils.py` is NOT created. Route to `trade_framer.py` or add a thin helper inside `trade_framer.py`.
- **Two-step confidence clamping:** Consolidate to one `compose_confidence()` call. No raw `min()`/`max()` in plugin bodies.
- **Silent validation drops:** `validate_signal()` failures must log ERROR + increment counter + drop. Never swallow.
- **Hard crashes on validation failure:** `validate_signal()` failures must not raise. Log + drop + metric only.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Stop placement | Inline `entry ± atr * multiplier` | `trade_framer.frame_trade()` | GARCH multipliers, FVG priority stops, stop_basis classification all live in trade_framer; per-plugin stop logic can never match |
| Signal validation | Custom field checks per plugin | `signal_schema.validate_signal()` | Schema is already defined; duplicating checks creates drift |
| Signal construction | Manual dict assembly in service | `signal_schema.make_signal()` | Factory computes RR, handles rounding, enforces required fields |
| Prometheus counter registration | Bare `Counter(...)` call | `src/observability/metrics.py` `counter()` helper | The helper prevents duplicate registration errors on hot reload |
| Utility promotion | Copy-paste into utils/common.py | Move verbatim from composites/common.py | The composites version is the source of truth for I2 behavior; no changes to logic |

**Key insight:** The value of `trade_framer.py` is that it accumulates structural intelligence (GARCH vol regime, FVG stops, chandelier logic) that no per-plugin stop formula can replicate. Routing 14 plugins through `frame_trade()` is not just cleaner — it means those plugins instantly benefit from any future improvements to stop logic.

## Common Pitfalls

### Pitfall 1: is_num collision between utils.py and composites/common.py
**What goes wrong:** `src/intelligence/utils.py` exports `is_num` with a stricter definition (rejects NaN/Inf via `math.isfinite`). `composites/common.py` exports `is_num` with a simpler definition (`isinstance(x, int | float)` only). When `composites/common.py` is promoted to `utils/common.py`, the two `is_num` functions coexist at different import paths.
**Why it happens:** `cross_timeframe.py` imports `is_num` from `src.intelligence.utils` (the strict version). I2 composites import from `composites.common` (the simple version). The promotion doesn't change either.
**How to avoid:** When creating `utils/common.py`, copy the composites version verbatim. Do NOT merge or replace the `utils.py` version. The two serve different callers with different requirements. Document the distinction in module docstrings.
**Warning signs:** I2 composite tests failing with unexpected False results on numeric values that happen to be NaN.

### Pitfall 2: validate_signal() rejects all microstructure plugins until type fixes land
**What goes wrong:** If `make_signal()` factory adoption (plan 4) runs before the microstructure type fixes (also plan 4), all 8 microstructure plugins fail validation on every bar and are dropped.
**Why it happens:** `validate_signal()` checks `targets` is a non-empty list — but 7 of 8 plugins return `targets: None`. The `cross_asset_divergence` plugin is the only one that correctly calls `frame_trade()`.
**How to avoid:** Plan 4 must sequence microstructure type fixes BEFORE wiring `validate_signal()` enforcement in `signal_generator_service`. Within plan 4, fix plugins first, then add enforcement.
**Warning signs:** `signal_validation_failures_total{plugin=trad_OFISpike}` counter incrementing on every bar after plan 4.

### Pitfall 3: cross_timeframe.py method visibility after decomposition
**What goes wrong:** `_score_fvg_alignment` and `_score_ob_alignment` both call `_proximity_decay` (from `confluence_weights.py`) and `_extract_trend_sign` (also from `confluence_weights.py`). After decomposition, `confluence_smc.py` needs to import these from `confluence_weights.py` — or accept them as function arguments.
**Why it happens:** The monolith used `self._extract_trend_sign()` and module-level `_proximity_decay()`. The decomposed modules are plain functions, not classes — no `self`.
**How to avoid:** `confluence_smc.py` imports `_proximity_decay` and `_extract_trend_sign` directly from `confluence_weights.py`. All are module-level functions after decomposition. Keep import graph simple: `cross_timeframe.py` → all three modules; modules do NOT import from each other (except `confluence_smc.py` imports from `confluence_weights.py`).
**Warning signs:** `ImportError` or circular imports in the `confluence/` package.

### Pitfall 4: TradeFrame.viable=False drops viable signals
**What goes wrong:** `frame_trade()` returns `TradeFrame` with `viable=False` when T1 RR < 1.5. When the 14 inline-stop plugins are refactored to call `frame_trade()`, they must handle `viable=False` by calling `no_signal()`. If they don't check, they'll produce signals with bad RR.
**Why it happens:** The inline ATR stop approach never had an RR gate. `frame_trade()` does. The gate is intentional.
**How to avoid:** Always check `tf.viable` after `frame_trade()`. If False, call `no_signal()`.

### Pitfall 5: compute_next() is called in practice — the delegation pattern matters
**What goes wrong:** `default_compute_next(plugin, windows)` in `plugin_utils.py` needs access to the plugin instance to call `compute_full()`. The straightforward delegation `return plugin.compute_full(windows)` is correct. However, some plugins have state (`_state` field) that must persist between calls — this is already handled by `compute_full` writing state back.
**Why it happens:** `compute_next()` in all 36 plugins is currently `return self.compute_full(windows)` — identical one-liner. The only question is how to express this as a shared utility function when there's no inheritance.
**How to avoid:** The simplest approach: remove `compute_next()` entirely from plugins and have `plugin_utils.py` provide a standalone function that's called from the service layer instead of the method. Alternatively, keep the one-liner in each plugin since it's 1 line (not worth eliminating via complex indirection). Per the CONTEXT.md, `default_compute_next()` is in `plugin_utils.py` — the exact implementation is Claude's discretion. Recommend: keep `compute_next` as a 1-line method in each plugin importing `compute_full` — the duplication is 36 × 1 line, which is trivial and avoids any callable-indirection complexity.

### Pitfall 6: ROADMAP says 28 plugins, actual count is 36
**What goes wrong:** ROADMAP still references "28 plugins" in success criteria text. CONTEXT.md (line 11) explicitly documents this: "Actual count is 36 I7 plugins (28 original setups + 8 microstructure added in Phase 36)."
**Why it happens:** The ROADMAP was written before Phase 36 added 8 microstructure plugins. The success criteria grep tests should use 36 as the expected count.
**How to avoid:** All verification steps must target all 36 plugins in `TIER_I7` (not 28). The existing test `test_i7_registration.py::test_tier_i7_count` already asserts `len(TIER_I7) == 36`.

## Code Examples

Verified from actual codebase:

### frame_trade() signature (trade_framer.py line 779)
```python
def frame_trade(
    setup_type: str,  # e.g. "trend_long", "sweep_reclaim_long"
    direction: int,   # 1 or -1
    entry: float,     # current close price
    features: dict[str, Any],  # full features dict from _build_features_from_event()
    atr: float,       # ATR×14 from I1
) -> TradeFrame:
```
Returns `TradeFrame` with `.stop` (float), `.targets` (list[TradeTarget]), `.viable` (bool), `.stop_basis` (str|None).

### validate_signal() schema (signal_schema.py)
```python
REQUIRED_SIGNAL_FIELDS = frozenset({
    "type", "symbol", "timeframe", "timestamp", "signal_type",
    "setup_plugin", "direction", "entry_price", "stop_loss",
    "targets", "confidence", "risk_reward_ratio", "regime_context",
    "confluence_score", "supporting_factors", "invalidation_conditions", "ttl_bars",
})
# Rules: type=="signal.v1", confidence in [0.0, 1.0], direction in (1,-1,1.0,-1.0), targets is non-empty list
```

### make_signal() usage in signal_generator_service (current — manual dict, no factory)
The service currently assembles `LedgerEntry` directly from plugin output dicts without calling `make_signal()`. The `make_signal()` factory is only used in tests (`test_signal_schema.py`). Plan 4 wires `make_signal()` as the construction point in `_run_setup_plugins()` — plugin output passes through `make_signal()` before being appended to `signals`.

### Prometheus counter pattern (observability/metrics.py)
```python
# Use the project counter() helper to prevent duplicate registration:
from src.observability.metrics import counter
SIGNAL_VALIDATION_FAILURES = counter(
    "signal_validation_failures_total",
    "Signal validation failures before aggregation",
)
# With labels (if needed):
from prometheus_client import Counter
SIGNAL_VALIDATION_FAILURES = Counter(
    "signal_validation_failures_total",
    "Signal validation failures",
    ["plugin"],
)
```
**Note:** The project's `counter()` helper in `metrics.py` does NOT support labels. For a labeled counter (`{plugin=name}`), use `prometheus_client.Counter` directly — but check `_counters` dict first to avoid duplicate registration. Recommend: define a module-level constant in `signal_generator_service.py`.

### Current confidence clamping (two-step, inconsistent — trend_following.py lines 92, 114)
```python
confidence = round(min(1.0, max(0.0, raw_conf)), 4)    # first pass: [0, 1]
# ... penalty adjustments ...
confidence = round(min(0.95, max(0.10, confidence)), 4) # second pass: [0.10, 0.95]
```
Replace with single: `confidence = compose_confidence(raw_conf + adjustments)`

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Per-plugin `_no_signal()` static method | Module-level `no_signal()` import | Phase 44 | Zero behavior change; one definition |
| Inline ATR recomputation (`np.mean(high-low)`) | `atr_utils.get_atr()` returning None | Phase 44 | Removes false data path; I1 is the authoritative source |
| Inline ATR stops in 14 plugins | Route through `frame_trade()` | Phase 44 | These plugins gain GARCH-scaled stops automatically |
| Two-step confidence clamping with inconsistent floors | `compose_confidence()` with `[0.10, 0.95]` contract | Phase 44 | Consistent system-wide floor/ceiling; one tuning point |
| `validate_signal()` used in tests only | Enforced in `_run_setup_plugins()` pre-aggregation | Phase 44 | Invalid signals logged, counted, dropped before aggregation |
| `composites/common.py` (I2-only) | `utils/common.py` (tier-agnostic) | Phase 44 | I7 plugins can use crossover_detect, threshold_cross without re-implementing |
| 464-line cross_timeframe.py monolith | 3 focused modules + thin orchestrator | Phase 44 | Each module independently testable; pure-math separated from domain logic |

**Deprecated/outdated:**
- Inline `np.mean(high - low)` ATR fallback in plugins: eliminated — `atr_utils.get_atr()` returns None, plugin calls `no_signal()`
- `stop_loss: None` / `targets: None` / `regime_context: dict` in microstructure plugins: fixed to float/list/str for `validate_signal()` compatibility

## Open Questions

1. **compute_next() elimination scope**
   - What we know: All 36 plugins implement `compute_next` as `return self.compute_full(windows)` — 1-line delegation
   - What's unclear: Whether to expose `default_compute_next` in `plugin_utils.py` as a standalone function and call it from the service layer, or keep the 1-liner in each plugin
   - Recommendation: Keep the 1-liner in each plugin (it's a Protocol requirement and 1 line is not real duplication). The `default_compute_next` in `plugin_utils.py` can exist as a utility but plugins don't need to call it.

2. **trade_framer interface for microstructure plugins**
   - What we know: Microstructure plugins (OFI/CVD) fire on order flow anomalies, not structural levels. `frame_trade()` resolves structural stops — may produce `viable=False` for many microstructure signals since features won't have relevant structural context.
   - What's unclear: Whether `frame_trade()` ATR fallback stop (entry ± ATR×2.0) is appropriate for microstructure signals, or whether a lighter `"atr_fallback"` framing method is sufficient.
   - Recommendation: Call `frame_trade()` with the microstructure plugin's signal type. `frame_trade()` has `ATR_STOP_FALLBACK_MULTIPLIER = 2.0` as the fallback — this is reasonable for OFI/CVD signals. The planner should verify that `frame_trade()` doesn't return `viable=False` for these setup types in typical conditions.

3. **Prometheus counter for validation failures — label support**
   - What we know: The `counter()` helper in `metrics.py` does not support labels. Per-plugin attribution requires `{plugin=name}` label.
   - What's unclear: Whether to add label support to the helper or use raw `prometheus_client.Counter` with manual dedup guard.
   - Recommendation (Claude's discretion per D-17): Use raw `Counter` with a module-level singleton and `labels()` call. Register once at import time.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 6+ |
| Config file | `pytest.ini` (project root) |
| Quick run command | `.venv/bin/pytest tests/unit/intelligence/ -v -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DAG-01 | `atr_utils.get_atr()` returns float for valid feature, None for missing/zero | unit | `.venv/bin/pytest tests/unit/intelligence/test_atr_utils.py -x` | ❌ Wave 0 |
| DAG-01 | `plugin_utils.extract_ohlcv()` returns None on short df, tuple on valid | unit | `.venv/bin/pytest tests/unit/intelligence/test_plugin_utils.py -x` | ❌ Wave 0 |
| DAG-01 | `plugin_utils.no_signal()` returns correct dict | unit | `.venv/bin/pytest tests/unit/intelligence/test_plugin_utils.py -x` | ❌ Wave 0 |
| DAG-01 | 14 plugins no longer have inline ATR stops | grep/unit | `.venv/bin/pytest tests/unit/intelligence/test_plugin_utils.py::test_no_inline_atr_stops -x` | ❌ Wave 0 |
| DAG-02 | Zero plugins declare `_no_signal()` as instance/static method | grep/unit | `.venv/bin/pytest tests/unit/intelligence/test_plugin_utils.py::test_no_plugin_nosignal_methods -x` | ❌ Wave 0 |
| DAG-03 | `confidence_utils.compose_confidence()` clamps to [0.10, 0.95] | unit | `.venv/bin/pytest tests/unit/intelligence/test_confidence_utils.py -x` | ❌ Wave 0 |
| DAG-03 | Zero plugins use raw `min()`/`max()` for confidence clamping | grep/unit | `.venv/bin/pytest tests/unit/intelligence/test_confidence_utils.py::test_no_inline_clamping -x` | ❌ Wave 0 |
| DAG-04 | `validate_signal()` called pre-aggregation; failures emit ERROR log + counter | unit | `.venv/bin/pytest tests/unit/intelligence/test_signal_schema.py -x` | ✅ (extend) |
| DAG-04 | All 8 microstructure plugins produce valid `stop_loss` float, `targets` list, `regime_context` str | unit | `.venv/bin/pytest tests/unit/intelligence/trading/test_ofi_plugins.py tests/unit/intelligence/trading/test_cvd_plugins.py -x` | ✅ (extend) |
| DAG-04 | Existing I6 tests all pass after cross_timeframe.py decomposition | regression | `.venv/bin/pytest tests/unit/intelligence/test_cross_timeframe.py -x` | ✅ |
| DAG-04 | `utils/common.py` imports work; I2 composites import from new path | unit | `.venv/bin/pytest tests/unit/intelligence/test_utils.py -x` | ❌ Wave 0 |
| DAG-04 | `make_signal()` is the only construction point in signal_generator_service | grep | manual grep check | N/A |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/intelligence/ -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/intelligence/test_plugin_utils.py` — covers DAG-01, DAG-02 (no_signal, extract_ohlcv, signal_type_for_direction, no inline duplication)
- [ ] `tests/unit/intelligence/test_atr_utils.py` — covers DAG-01 (get_atr behavior)
- [ ] `tests/unit/intelligence/test_confidence_utils.py` — covers DAG-03 (compose_confidence clamping, system contract)
- [ ] `tests/unit/intelligence/test_utils.py` (extend or create) — covers DAG-04 (utils/common.py promotion, is_num from correct path)

Existing tests to extend:
- `tests/unit/intelligence/test_signal_schema.py` — add validate_signal failure path test
- `tests/unit/intelligence/trading/test_ofi_plugins.py` — add stop_loss/targets/regime_context type assertions
- `tests/unit/intelligence/trading/test_cvd_plugins.py` — same

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `src/intelligence/trading/trade_framer.py` — `frame_trade()` signature verified lines 779-805
- Direct code inspection: `src/intelligence/trading/signal_schema.py` — `make_signal()`, `validate_signal()`, `REQUIRED_SIGNAL_FIELDS` verified
- Direct code inspection: `src/intelligence/trading/exhaustion_utils.py` — utility function pattern confirmed as model
- Direct code inspection: `src/intelligence/confluence/cross_timeframe.py` — 464 lines, decomposition structure mapped
- Direct code inspection: `src/intelligence/composites/common.py` — 4 functions to promote
- Direct code inspection: `src/intelligence/utils.py` — `is_num` collision identified
- Direct code inspection: all 8 microstructure plugins — `stop_loss: None`, `targets: None`, `regime_context: dict` confirmed
- Direct code inspection: `src/intelligence/register_plugins.py` — TIER_I7 = 36 plugins confirmed
- Direct code inspection: `tests/unit/intelligence/test_i7_registration.py` — test_tier_i7_count asserts 36
- Direct code inspection: `services/signal_generator_service.py` — `make_signal()` NOT currently called in production path (only referenced in TTL comment); manual `LedgerEntry` assembly confirmed

### Secondary (MEDIUM confidence)
- `.planning/phases/44-i7-dag-refactor/44-CONTEXT.md` — all locked decisions and rationale
- `.planning/REQUIREMENTS.md` — DAG-01 through DAG-04 success criteria
- `.planning/ROADMAP.md` — Phase 44 success criteria (note: ROADMAP says "28 plugins"; actual count 36 per CONTEXT.md)

### Tertiary (LOW confidence)
- None — all findings verified against actual code.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; all existing tools
- Architecture patterns: HIGH — verified against actual code in each source file
- Pitfalls: HIGH — `is_num` collision confirmed by reading both files; validate_signal type issues confirmed by grep across all 8 microstructure plugins
- Decomposition plan: HIGH — cross_timeframe.py fully read and method group boundaries mapped

**Research date:** 2026-03-20
**Valid until:** 2026-04-20 (stable architecture — the I7 plugin set and trade_framer interface are unlikely to change before Phase 44 execution)
