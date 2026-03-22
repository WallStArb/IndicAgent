# Phase 44: I7 DAG Refactor — Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Pure structural refactor of the I7 trading layer. Extract shared utilities, enforce the DAG pipeline contract, standardize signal construction via `make_signal()` factory, decompose `cross_timeframe.py` into focused modules. Zero signal behavior change — all existing tests pass unchanged.

**Note:** ROADMAP references "28 plugins" in several places. Actual count is **36 I7 plugins** (28 original setups + 8 microstructure added in Phase 36). All refactoring targets apply to all 36.

</domain>

<decisions>
## Implementation Decisions

### Plugin utility extraction — class design

- **D-01:** Extract shared I7 helpers as **module-level utility functions** in `plugin_utils.py` — NOT a `BaseI7Plugin` class or mixin.
- **D-02:** Rationale: `PatternPlugin` is already a Protocol (not a base class). `@dataclass` + Protocol is the clean DAG contract — class inheritance introduces hidden coupling and MRO complexity. Functions compose; hierarchies couple. A new plugin author should read one existing plugin, copy imports, never understand a class hierarchy.
- **D-03:** `plugin_utils.py` contains: `no_signal() → dict`, `extract_ohlcv(frames, min_bars) → tuple | None`, `default_compute_next()`, `signal_type_for_direction(direction) → str` (the `"_long"`/`"_short"` suffix helper).
- **D-04:** All 36 plugins import from `plugin_utils` explicitly. No magic inheritance.

### ATR utility

- **D-05:** `atr_utils.py` is a **thin null-guard wrapper** around I1's `atr_14` feature — it is NOT a recomputer.
- **D-06:** Pattern: read `features.get("atr_14")`, validate > 0, return float. If missing or ≤ 0, return `None` and let the caller decide (typically `_no_signal()`). The ATR fallback computation (`np.mean(high - low)`) was compensating for I1 data not reaching plugins cleanly — graceful degradation, not a desired code path.
- **D-07:** ATR is computed once in I1 (`atr_14`). Recomputing it in 17 plugins violates the data-quality-over-model-complexity principle.

### Stop/target placement — `position_utils` is dropped

- **D-08:** **`position_utils.py` is NOT created.** This module was planned before the audit confirmed `trade_framer.py` already owns this responsibility.
- **D-09:** `trade_framer.py` is the single source of truth for stop sizing — GARCH multipliers, FVG structural stops, stop_basis classification, chandelier logic all live there. Creating a parallel `build_stops_targets()` function would split responsibility across two modules, requiring updates in two places whenever stop logic evolves.
- **D-10:** The 14 plugins doing inline ATR stop placement are refactored to call `trade_framer.frame_trade()`. If `trade_framer`'s interface is too heavy for a plugin, expose a lighter helper function from within `trade_framer` — not a new module.
- **D-11:** `signal_type_for_direction()` (the string suffix helper) lives in `plugin_utils.py` alongside other tiny pure helpers.

### Confidence utilities

- **D-12:** `confidence_utils.py` provides `compose_confidence()` with two named constants: `CONF_FLOOR = 0.10`, `CONF_CEIL = 0.95`.
- **D-13:** Constants are module-level (not function arguments) — simple, tunable in one place without touching 36 files. Per-plugin overrides are not needed and would undermine the system contract.
- **D-14:** All 36 plugins route through `compose_confidence()`. Zero inline `min()`/`max()` clamping in plugin bodies.

### validate_signal() failure mode

- **D-15:** Validation failure = **log + drop + Prometheus counter**. Never silent drop, never hard crash.
- **D-16:** Full signal dict + failure reason emitted to structured logger at ERROR level.
- **D-17:** Prometheus counter `signal_validation_failures_total{plugin=name}` — spikes are observable without crashing the pipeline.
- **D-18:** Dropped signals do not reach the aggregator. Invalid data must not enter the ledger.
- **D-19:** Rationale: a validation failure is signal about signal quality. Dropping it silently destroys that information. Hard crash kills the pipeline for all symbols. Log + drop + metric is the Renaissance-grade answer: instrument everything, degrade gracefully.

### cross_timeframe.py decomposition

- **D-20:** `cross_timeframe.py` (460 lines) splits into **3 modules by computation stage**, not by concept label:
  - `confluence_weights.py` — TF authority weights, recency decay, frame extraction helpers. Pure math, no market domain knowledge. Independently testable with numeric inputs alone.
  - `confluence_alignment.py` — trend/structure/regime/pattern scoring functions. Reads market features, returns scalar scores.
  - `confluence_smc.py` — BOS, FVG, OB alignment scoring. SMC-specific domain logic isolated here.
- **D-21:** `CrossTimeframeConfluencePlugin` class stays intact — it imports from the three modules and orchestrates. The class is the DAG stage; the modules are the computation libraries.
- **D-22:** All existing I6 tests pass unchanged (the class interface doesn't change).

### composites/common.py promotion

- **D-23:** `composites/common.py` promoted to `src/intelligence/utils/common.py` — tier-agnostic. Contains: `is_num`, `crossover_detect`, `threshold_cross`, `track_bars_ago`.
- **D-24:** I2 composites updated to import from new path. I7 plugins that can benefit from these utilities adopt them.
- **D-25:** Zero imports from `composites/common.py` after migration (import path fully replaced).

### OFI/CVD type fix scope

- **D-26:** Fix **all 8 microstructure plugins**, not just OFISpike + OFIContinuation.
- **D-27:** Rationale: consistency is non-negotiable in a quantitative system. If `validate_signal()` enforces a schema contract and 6 of 8 microstructure plugins produce invalid output, the validation pass is a lie. The ROADMAP mentioned 2 plugins because it was written before the full audit.
- **D-28:** All 8 must return valid `stop_loss` (float), `targets` (non-empty list of floats), `regime_context` (str) before Phase 44 ships.

### make_signal() factory adoption

- **D-29:** `make_signal()` becomes the **only** signal dict construction point in `signal_generator_service`. Manual dict assembly is replaced.
- **D-30:** `validate_signal()` called on every signal before aggregation — not optional, not configurable.
- **D-31:** Plugin output scope for Phase 44: plugins continue to assemble the full signal dict internally (passed to `make_signal()` for construction). Typed intermediate results (direction + raw_confidence only) are Phase 45+ territory — the delta is too large for a single refactor phase.

### Claude's Discretion

- Internal implementation of `compose_confidence()` formula
- Whether `atr_utils` exposes one function or two (extract vs validate)
- Exact Prometheus counter label names
- Module docstrings and type annotations on new utilities
- Order of plugin migration within each plan

</decisions>

<specifics>
## Specific Ideas

- "What would Jim Simons demand?" framing applied throughout — one module per responsibility, no parallel stop-sizing modules, instrument validation failures, keep the DAG explicit.
- `trade_framer.py` is the canonical stop module. If its interface needs lightening for some call sites, add a helper function inside `trade_framer` — not a new file.
- The `PatternPlugin` Protocol + `@dataclass` pattern is correct. Don't pollute it with inheritance.
- A new developer adding a plugin should read one existing plugin and copy imports. No class hierarchy to understand.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing utilities to extend or route through
- `src/intelligence/trading/trade_framer.py` — canonical stop/target module; 14 inline-stop plugins must route here; do NOT create parallel stop logic
- `src/intelligence/trading/signal_schema.py` — `make_signal()` and `validate_signal()` signatures; adoption target for all signal construction
- `src/intelligence/trading/exhaustion_utils.py` — `apply_exhaustion_boost`, `apply_exhaustion_guard`; understand interface before writing plugin_utils
- `src/intelligence/trading/position_sizer.py` — exists; understand boundary with trade_framer before touching either

### Modules to create
- `src/intelligence/trading/plugin_utils.py` — `no_signal`, `extract_ohlcv`, `default_compute_next`, `signal_type_for_direction`
- `src/intelligence/trading/atr_utils.py` — null-guard wrapper around `atr_14`; no recomputation
- `src/intelligence/trading/confidence_utils.py` — `compose_confidence`, `CONF_FLOOR`, `CONF_CEIL`

### Modules to decompose
- `src/intelligence/confluence/cross_timeframe.py` — 460-line monolith; split into `confluence_weights.py`, `confluence_alignment.py`, `confluence_smc.py` in same directory; class stays

### Modules to promote
- `src/intelligence/composites/common.py` → `src/intelligence/utils/common.py`; update all I2 composite imports

### Plugin registry
- `src/intelligence/register_plugins.py` §TIER_I7 — 36 plugins (not 28); `validate_tier()` enforcement target

### Phase spec
- `.planning/ROADMAP.md` §Phase 44 — requirements DAG-01 through DAG-04 and success criteria
- `.planning/ROADMAP.md` §Phase 45 — depends on confidence_utils + BaseI7Plugin pattern being in place; read to understand what Phase 44 must leave ready

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `trade_framer.py`: Already owns stop/target logic for all I7 setups. GARCH_MULTIPLIERS, FVG priority stop, stop_basis classification. Extend its interface if call sites need a lighter entry point — do not replicate.
- `signal_schema.make_signal()`: 24-parameter factory, currently used only by aggregator. Phase 44 wires it as the single construction point in `signal_generator_service`.
- `signal_schema.validate_signal()`: Schema validation exists. Phase 44 enforces it on every signal pre-aggregation.
- `exhaustion_utils.py`: 2 functions used by 4 plugins. Interface is stable — use as model for `confidence_utils` design.
- `position_sizer.py`: `calculate_position_size()` + `PositionSize` dataclass. Pure utility. Understand its boundary with `trade_framer` before touching either.

### Established Patterns
- `@dataclass` + `PatternPlugin` Protocol: Do not break this with class inheritance. Every new utility is a function, not a method.
- `_no_signal()` as nested function returning `{}`: Replace with `plugin_utils.no_signal()` import — same semantics, one definition.
- `frames.get("main")` + null guard + `to_numpy()`: Replace with `plugin_utils.extract_ohlcv(frames, self.min_lookback)` — consistent across all 36 plugins.
- `features.get("atr_14", 0.0)` + fallback compute: Replace with `atr_utils.get_atr(features)` returning `float | None`.

### Integration Points
- `signal_generator_service.py`: Calls all 36 plugins, assembles signal dicts, feeds aggregator. `make_signal()` adoption happens here — plugin outputs pass through factory before aggregation.
- `register_plugins.py` §TIER_I7: `validate_tier()` must hard-crash if any I7 plugin missing `regime_type`. Tighten enforcement here.
- I6 `CrossTimeframeConfluencePlugin`: Interface unchanged by decomposition. Market analysis service imports the class, not the internal modules — zero downstream change.
- I2 composites (`src/intelligence/composites/`): All must update import path after `common.py` promotion.

</code_context>

<deferred>
## Deferred Ideas

- **Typed intermediate plugin output** (direction + raw_confidence only, no dict assembly in plugin) — Phase 45+ territory; delta too large for a pure structural refactor phase
- **Per-plugin confidence floor/ceiling overrides** — not needed now; if calibration data ever supports it, `compose_confidence()` can accept optional overrides without touching 36 plugins
- **I6 → I7 confluence wiring** (ctf_* scores in confidence calculation) — Phase 45; Phase 44 must land `confidence_utils` first so Phase 45 has a stable composition point
- **Exhaustion wiring to all applicable plugins** — Phase 45
- **Prometheus alert rules for validation failure spikes** — Phase 50 observability

</deferred>

---

*Phase: 44-i7-dag-refactor*
*Context gathered: 2026-03-20*
