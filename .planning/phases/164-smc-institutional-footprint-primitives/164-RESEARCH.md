# Phase 164: SMC Institutional Footprint Primitives - Research

**Researched:** 2026-07-25
**Domain:** Feature engineering port (archived v2.x plugin logic -> v3 FeatureFactory primitives), TimescaleDB schema migration, APR parameter registration
**Confidence:** HIGH (all claims verified by direct source read against `src/intelligence/archive/smc_context/*.py`, `src/intelligence/feature_factory.py`, `src/intelligence/feature_cache.py`, `src/intelligence/features/feature_vector_persistence.py`, and `production/migrations/`)

## Summary

This phase ports 8 of the ~10 archived v2.x SMC plugins (order blocks, fair value gaps,
liquidity sweeps, liquidity pools, supply/demand zones, AMD cycle, breaker/mitigation blocks,
BOS/CHoCH) into v3 `FeatureVector` primitives, following the exact wiring pattern Phase 163
established: a single pure `compute()`/`compute_batch()` function in `feature_factory.py`,
optional `FeatureCache` mutators for session-scoped state, an append-only field-name slice in
`feature_vector_persistence.py`, and `FEATURE_VECTOR_DOMAIN`-tagged entries for IC/collinearity
screening.

**Three findings materially change this phase's scope relative to ROADMAP.md's framing, and
must be resolved during planning, not discovered during implementation:**

1. **ROADMAP's "no cross-plugin dependency chain" claim is false for 3 of the 8 in-scope
   plugins.** `breaker_blocks.py` and `mitigation_blocks.py` have a **hard** dependency on
   `order_blocks.py`'s output fields (`ob_type`/`ob_top`/`ob_bottom`/`ob_mitigated`);
   `supply_demand_zones.py` has a **soft** (optional, default-if-missing) dependency on
   `fair_value_gap.py`'s `fvg_midpoint` and `liquidity_pools.py`'s `price_in_premium`. This is
   solvable within one function (compute order-blocks first, thread its dict forward, matching
   the archived `frames.get("smc")` fusion pattern) but must be an explicit sequencing decision
   in the plan, not an assumption of independence.
2. **`liquidity_pools.py`'s PWH/PWL/PDH/PDL levels require daily-timeframe (`1d`) bar access**
   that the live v3 `FeatureFactory.compute(bars, symbol, tf, cache, config)` signature does not
   provide (single-timeframe `bars` list only — cross-timeframe data only reaches `compute()`
   today via the separate CTF cache-population mechanism, not a general per-plugin facility).
   This is the single biggest scope question for planning: either descope PWH/PWL/PDH/PDL (keep
   only equal-highs/equal-lows + session-high/low, both derivable from the primary timeframe) or
   build new daily-bar cache plumbing. Recommend descoping — see Architecture Patterns.
3. **`breaker_blocks.py`/`mitigation_blocks.py` carry cross-bar-call state** (`self._state`)
   that outlives their own tiny `InputSpec.lookback` (2-10 bars) — the archived plugins rely on
   the live pipeline's persistent in-memory `_state` dict to remember order blocks formed dozens
   of bars earlier. A literal stateless port over a 10-bar window would silently lose that
   memory. Recommend reimplementing both as pure functions of `order_blocks.py`'s own ~100-bar
   detection window (deriving breaker/mitigation directly from the full candidate list in the
   same pass) rather than adding a new `FeatureCache` mutator — see Architecture Patterns.

Beyond these three, the raw-price-vs-ATR-companion audit ROADMAP flagged is real and detailed
field-by-field below; two of the eight files (`liquidity_pools.py`, `supply_demand_zones.py`)
already compute ATR-normalized companions correctly in the archived source and need **only**
have their raw fields dropped, not new normalization derived — this is materially less work
than ROADMAP's blanket warning implies for those two files specifically.

**Primary recommendation:** Sequence this phase's single compute pass as: `order_blocks` ->
`breaker_blocks`/`mitigation_blocks` (consume OB output) -> `fair_value_gap` ->
`liquidity_sweeps` -> `liquidity_pools` (descoped to single-tf sources only) ->
`supply_demand_zones` (consumes FVG + LiquidityPools output) -> `bos_choch` -> `amd_cycle`
(needs a new session-scoped `FeatureCache` mutator, UTC-20:00 boundary). Persist only
ATR-distance/percentage/bounded/count/ordinal fields per the field-by-field audit below; never
persist a `_top`/`_bottom`/`_level`/`_midpoint` field.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| SMC primitive computation (order blocks, FVG, sweeps, pools, zones, AMD, breaker/mitigation, BOS/CHoCH) | Compute Pipeline (`FeatureFactory.compute()`/`compute_batch()`, Ring 1 `src/intelligence/`) | — | Pure function per CLAUDE.md's DAG invariant #3 (compute daemon never persists its own output); matches Phase 163's exact pattern |
| Session-scoped state (AMD overnight range) | Compute Pipeline (`FeatureCache` mutator) | — | Mirrors `update_session_vp()`/`update_wk_vwap()` — session-boundary-reset accumulation, not a DB round-trip |
| Persistence (new `feature_vectors` columns) | Database/Storage (`FeatureVectorWriter` live path, `backfill_feature_factory.py` batch path) | — | DAG invariant #3: a dedicated `BaseWriter`/`BaseBatch` subclass writes, never the compute daemon inline |
| Persistence contract / column-name completeness | Compute Pipeline (`feature_vector_persistence.py`, Ring 1) | Database/Storage | Single source of truth consumed by both live (asyncpg) and batch (psycopg2) writers — Phase 163's `_STRUCTURAL_VP_SR_FIELD_NAMES` append-only pattern |
| Parameter tuning (impulse thresholds, ATR multipliers, lookback windows) | Compute Pipeline (APR / `ConfigService`) | — | CLAUDE.md APR mandate — no hardcoded numeric thresholds in `src/`/`services/` |
| Downstream IC/promotion evaluation | Out of this phase's scope (existing `ic_engine`/corpus pipeline) | — | Phase 163's D-07 precedent: this phase stops at "correct, real, non-constant values persisted," not "promoted to ensemble weights" |

## Project Constraints (from CLAUDE.md)

- **DAG invariant #3:** compute daemon never persists its own output — `FeatureFactory.compute()`/`compute_batch()` stay pure; a `BaseWriter`/`BaseBatch` subclass (already-live `FeatureVectorWriter`/`backfill_feature_factory.py`) does the writing. No new daemon needed — reuse the existing writers exactly as Phase 163 did.
- **APR mandate (migrate-as-you-go):** every new numeric threshold (impulse-move %, base-body ratio, ATR multipliers, reclaim-bar counts, lookback windows, AMD session-boundary hours) goes under a new `feature.*` APR namespace via `config_schema`/`config_state` migration + `ConfigService.get()` — no hardcoded constants in the ported code. Description must note provenance (`[conventional]` for values copied verbatim from the archived plugin's hardcoded defaults, since they're unvalidated ICT-community conventions, not `[rca_analysis]`).
- **Ring rule:** stays in Ring 1 (`src/intelligence/`) — no domain vocab leaks into Ring 0 (`src/core/`).
- **All timestamps UTC:** AMD Cycle's session-boundary logic (20:00/00:00/10:00/21:00 UTC) already matches this — `datetime.now(UTC)` only, confirmed via `utc_datetime_from_df` (already live, not archived).
- **Naming system:** new columns/APR keys must follow `snake_case` derivation; distance fields end in `_dist_atr`, bounded fields stay unsuffixed or `_pct`/`_flag`, counts stay unsuffixed integers-as-float.
- **Migrate-as-you-go:** any hardcoded threshold discovered in the archived source during port (e.g. `impulse_bars: int = 3`, `impulse_atr_mult: float = 1.5`) must become an APR key in the same migration, not deferred.
- **Test sweep on rename:** if any archived field is renamed during the raw-price cleanup (e.g. `ob_distance_pct` -> `ob_dist_atr`), grep `tests/` for the old name — none currently exist referencing these plugins (verified, see Wave 0 Gaps), so this specific risk is low for this phase but the rule still applies to any future renames.

## Standard Stack

No new external packages. This phase is a pure-Python port using libraries already imported by
`feature_factory.py` today: `numpy`, `pandas` (both already project dependencies, no version
change). `src/intelligence/utils.py` (`find_peaks`, `find_troughs`, `clamp`) and
`src/intelligence/utils/gradient_utils.py` (`linear_ramp`, `freshness_decay`) are already live,
non-archived modules — direct reuse, no porting needed for these utilities themselves.

**Package Legitimacy Audit:** Not applicable — this phase installs zero external packages.
`slopcheck`/registry verification steps are skipped per the protocol's scope (Node/Python/Rust
package installs only).

## Architecture Patterns

### System Architecture Diagram

```
market_data_ohlcv_tradeable (single tf: 1m/5m/15m/1h/1d)
        |
        v
FeatureFactory.compute(bars, symbol, tf, cache, config)   [live, per-bar]
FeatureFactory.compute_batch(...)                          [backfill, vectorized]
        |
        |-- atr_val (already computed, existing code)
        |
        |-- [1] order_blocks: scan ~100-bar window for impulse+opposing-candle OB
        |         -> ob_type, ob_strength, ob_mitigated, ob_dist_atr (derived)
        |         -> (also retains full active_obs list in-pass, not just latest,
        |             to support directional nearest-bull/nearest-bear per ROADMAP)
        |
        |-- [2] breaker_blocks / mitigation_blocks: derive from [1]'s active_obs list
        |         directly (NOT from cross-call self._state) -- stateless recompute
        |         -> breaker_block_active, breaker_block_type, breaker_dist_atr
        |         -> ob_mitigation_status (ordinal), ob_mitigation_pct
        |
        |-- [3] fair_value_gap: scan 3-candle imbalances over window
        |         -> fvg_type, fvg_size_atr (derived), fvg_dist_atr (derived, new),
        |            fvg_open_count
        |
        |-- [4] liquidity_sweeps: find_peaks/find_troughs (already-live utils) + wick-beyond
        |         -> sweep_detected, sweep_type, sweep_strength, reclaim_velocity,
        |            bars_since_last_sweep (derived, new)
        |
        |-- [5] liquidity_pools: DESCOPED to single-tf sources only (equal highs/lows,
        |         session high/low) -- PWH/PWL/PDH/PDL dropped, needs 1d bars unavailable
        |         to compute()'s single-tf signature
        |         -> bsl_dist_atr, ssl_dist_atr (already ATR-normalized in source),
        |            bsl_touches, ssl_touches, pool_count
        |
        |-- [6] supply_demand_zones: consumes [3].fvg_midpoint + [5].price_in_premium
        |         (soft dependency, defaults if the composing plugin's flag ordering
        |         changes) -- Rally-Base-Drop / Drop-Base-Rally detection
        |         -> demand_dist_atr, supply_dist_atr (already ATR-normalized in source),
        |            demand_freshness/strength, supply_freshness/strength,
        |            active_demand_zones, active_supply_zones, zone_friction_score
        |
        |-- [7] bos_choch: find_peaks/find_troughs + get_atr(features) (ATR already
        |         available, not a genuine SMC-to-SMC dependency)
        |         -> bos_strength, choch_strength (already ATR-normalized in source),
        |            bos_direction, choch_direction, smc_trend_direction,
        |            bars_since_last_shift (derived, new)
        |
        |-- [8] amd_cycle: NEW FeatureCache mutator (session-scoped, UTC 20:00 reset,
        |         analogous to update_session_vp()'s NY-session-scoped pattern but with
        |         a different boundary hour)
        |         -> amd_phase (ordinal-encoded), amd_manipulation_detected,
        |            amd_distribution_direction, manip_strength (needs clamp -- currently
        |            unbounded in archived source)
        |
        v
FeatureVector (new fields appended via _SMC_FIELD_NAMES slice)
        |
        v
feature_vector_persistence.py (single INSERT-column source of truth, both paths import it)
        |
        +--> FeatureVectorWriter (live, asyncpg)        --> feature_vectors (TimescaleDB)
        +--> backfill_feature_factory.py (batch, psycopg2) --> feature_vectors (TimescaleDB)
```

### Computation-order dependency (corrects ROADMAP's "no cross-plugin dependency chain" claim)

| Plugin | Depends on (within this phase) | Dependency strength |
|--------|-------------------------------|---------------------|
| `order_blocks.py` | none | — |
| `breaker_blocks.py` | `order_blocks.py` output (`ob_type`/`ob_top`/`ob_bottom`/`ob_mitigated`) | **Hard** — archived code returns empty/state-fallback without it |
| `mitigation_blocks.py` | `order_blocks.py` output (`ob_top`/`ob_bottom`/`ob_mitigated`) | **Hard** — archived code returns `None` without it |
| `fair_value_gap.py` | none | — |
| `liquidity_sweeps.py` | none (uses `find_swing_highs`/`find_swing_lows` directly) | — |
| `liquidity_pools.py` | none (after PWH/PWL/PDH/PDL descope) | — |
| `supply_demand_zones.py` | `fair_value_gap.py`'s `fvg_midpoint`, `liquidity_pools.py`'s `price_in_premium` | **Soft** — archived code defaults to `0.0`/no-op if missing, but this changes the actual computed `zone_strength`/`zone_friction_score` values, so the plan must still fix an order |
| `bos_choch.py` | ATR (already computed pre-SMC-block in existing `compute()`) | Not a real SMC dependency — same as every other file's `atr_val` use |
| `amd_cycle.py` | none (self-contained, new session mutator) | — |

**Recommended single-pass order:** `order_blocks` -> `breaker_blocks` + `mitigation_blocks` ->
`fair_value_gap` -> `liquidity_sweeps` -> `liquidity_pools` -> `supply_demand_zones` ->
`bos_choch` -> `amd_cycle`. This is a plain Python dict threaded through one function body — no
new inter-service coupling, no violation of DAG invariant #5 (no agent calls another agent
directly; this is intra-function, not inter-service).

### Pattern: stateless full-window recompute (reuse Phase 163's D-01/D-13 precedent)

**What:** Every SMC plugin declares `supports_incremental: bool = False`, meaning
`compute_next()` already just calls `compute_full()` again in the archived code — the same
non-incremental design Phase 163 chose deliberately for `ctx_VolumeProfile` (D-13) specifically
to sidestep unbounded-accumulator bugs. Reuse this for all 8 plugins: no new incremental
`compute_next` branch is needed anywhere in this phase.

**Correction needed for `breaker_blocks.py`/`mitigation_blocks.py` specifically:** despite
declaring `supports_incremental: bool = False`, these two files still mutate `self._state`
across calls in the *archived* live pipeline (a violation of true statelessness, papered over
by the fact that the old I1-I7 pipeline kept one long-lived plugin instance per symbol/tf). Do
**not** carry this `self._state` pattern into v3 — v3's `compute()`/`compute_batch()` are
explicitly documented as "PURE FUNCTION: no IO... Deterministic: identical inputs -> identical
output" (`feature_factory.py:3792-3797`), and per-instance mutable state on a plugin dataclass
does not fit that contract at all (batch/backfill calls `compute_batch()` over historical
windows with no notion of a persistent instance). Reimplement both as pure derivations from
`order_blocks`' own already-scanned ~100-bar `active_obs` list within the same compute pass —
no `FeatureCache` mutator needed for these two.

**When a `FeatureCache` mutator IS needed:** only for `amd_cycle.py`'s overnight-range
tracking, which is genuinely unrecoverable from a short window (the overnight high/low from
20:00-00:00 UTC must still be remembered during the 10:00-21:00 UTC distribution phase, many
hours and hundreds of 1m bars later). Add a new mutator, e.g. `update_overnight_range(bar_ts,
high, low, config)`, following `update_wk_vwap()`'s exact reset-on-boundary-change shape but
keyed on UTC-hour rollover into the accumulation window (20:00 UTC) instead of ISO week. New
`FeatureCache` fields: `_overnight_high`, `_overnight_low`, `_overnight_day` (analogous to
`_wk_tp_vol_sum`/`_wk_vol_sum`/`_wk_year_week`), plus persisted `amd_phase`/
`amd_manipulation_detected`/`amd_distribution_direction`/`manip_strength` fields matching
`poc_dist_atr` etc.'s "session-level (reset at session open by caller)" comment block.

### Pattern: cross-timeframe data gap (liquidity_pools.py PWH/PWL/PDH/PDL)

**What:** `liquidity_pools.py`'s named-level hierarchy (PWH/PWL = prior-week high/low, PDH/PDL
= prior-day high/low) reads a second `InputSpec(timeframe="1d", lookback=5)` frame
(`frames.get("1d")`) that the archived tiered-plugin pipeline supplied via multi-timeframe frame
injection. **Confirmed directly against the live `compute()` signature** (`feature_factory.py:
3785-3791`): `compute(bars, symbol, tf, cache, config)` takes a single timeframe's `bars` list
only. Cross-timeframe values that do reach `compute()` today (the `ctf_*` fields, `vix_z`/
`flight_quality`/`yield_slope_z`) arrive via a separate, purpose-built cache-population
mechanism (HTF bar arrival / cross-asset ETF bar arrival), not a generic multi-tf frame facility
any plugin can request.

**Recommendation:** descope PWH/PWL/PDH/PDL from this phase. Keep only the two liquidity-pool
components computable from the primary timeframe alone: equal-highs/equal-lows (swing-based,
`find_peaks`/`find_troughs`) and session-high/session-low (rolling max/min over the current
session's own bars, same session-boundary concept already used by `update_session_vp`). This
keeps `liquidity_pools.py`'s port genuinely self-contained, matching Phase 163's D-04 "stay
self-contained" discipline, and avoids building new daily-bar cache plumbing whose IC value is
unproven. Flag PWH/PWL/PDH/PDL as a deferred idea, not a silent drop — a `_touches_for()`-style
significance downgrade is not equivalent, so state explicitly that named weekly/daily levels
are out of scope pending a real cross-timeframe injection design (a bigger, separately-scoped
architectural question, likely shared with any future phase needing HTF level context beyond
the existing CTF fields).

### Recommended project structure

No new files — this port lands inside the same three files Phase 163 touched:
```
src/intelligence/
├── feature_cache.py              # + update_overnight_range() mutator, + AMD state fields
├── feature_factory.py            # + SMC compute block (8 sub-computations, ordered per above)
│                                  #   + FEATURE_VECTOR_DOMAIN entries tagged "smart_money"
├── features/
│   └── feature_vector_persistence.py  # + _SMC_FIELD_NAMES slice (append-only, matches
│                                       #   _STRUCTURAL_VP_SR_FIELD_NAMES precedent exactly)
└── schemas.py                    # + new FeatureVector fields (session-level block)
```

### Anti-patterns to avoid

- **Persisting any `_top`/`_bottom`/`_level`/`_midpoint`/`_high`/`_low` field.** Non-stationary
  raw price, breaks cross-sectional IC — the exact D-16 mistake Phase 163 corrected after the
  fact. See the field-by-field audit below for every occurrence in this phase's 8 files.
- **Carrying `self._state` dict mutation into `compute()`/`compute_batch()`.** Both are
  documented pure functions; per-instance state doesn't survive `compute_batch()`'s vectorized
  history replay and isn't reproducible on re-run. Use a `FeatureCache` mutator only where state
  is genuinely unrecoverable from a bounded window (AMD only, per above).
- **Persisting a string-valued field directly.** `amd_phase` (accumulation/manipulation/
  distribution/unknown) and `ob_mitigation_status` (fresh/partial/void) are Python `str` in the
  archived source — `FeatureVector` fields are `float | None` throughout the existing schema
  (verified: every existing field in `schemas.py`'s structural block is `float`). Both need
  ordinal encoding before they can become `FeatureVector` columns.
  `amd_phase`: 0.0=unknown, 1.0=accumulation, 2.0=manipulation, 3.0=distribution (Claude's
  discretion on exact mapping, document in the column COMMENT per migration 255's convention).
  `ob_mitigation_status`: this one is fully redundant with the already-numeric
  `ob_mitigation_pct` (0.0=fresh, (0,1)=partial, 1.0=void is recoverable from the percentage
  alone) — recommend dropping `ob_mitigation_status` entirely rather than ordinal-encoding a
  second copy of the same information.
- **Leaving `manip_strength` unbounded.** Unlike `sweep_strength` (already wrapped in
  `linear_ramp(depth, 0, 2.0)`, bounded [0,1]), `amd_cycle.py`'s `manip_strength = (high -
  on_high) / on_range` has no upper clamp — a manipulation wick that overshoots the overnight
  range by more than 100% produces a value >1.0. Apply the same `linear_ramp`/`clamp` treatment
  before persisting.

## Field-by-Field Raw-Price Audit (the single most important table in this document)

| Source file | Raw field(s) — NEVER persist | Existing normalized companion (already correct) | New derivation needed | Redundant field to drop |
|---|---|---|---|---|
| `order_blocks.py` | `ob_top`, `ob_bottom` | none (`ob_distance_pct` exists but is a **percentage**, not ATR) | `ob_dist_atr` = `ob_distance_pct`-equivalent computed as `abs(close - ob_mid) / atr`; also extend to track separate nearest-bull/nearest-bear (archived code returns only the single latest OB across both types) | — |
| `fair_value_gap.py` | `fvg_top`, `fvg_bottom`, `fvg_midpoint` | none (`fvg_size_pct` exists but is a **percentage**) | `fvg_size_atr` = `(top-bottom)/atr`; `fvg_dist_atr` = `(close - fvg_midpoint)/atr` (no distance field exists at all today, only size) | — |
| `liquidity_sweeps.py` | `sweep_level` | `sweep_strength`, `reclaim_velocity` already bounded [0,1] via `linear_ramp` | `bars_since_last_sweep` (not in current outputs; derive from tracked `bar_idx`); optionally `sweep_depth_atr` for unit consistency (currently `sweep_depth_pct`, a percentage — lower priority than the others) | — |
| `liquidity_pools.py` | `bsl_level`, `ssl_level` | **`bsl_dist_atr`/`ssl_dist_atr` ALREADY exist and are correctly ATR-normalized** — drop raw only, no new derivation needed | — (after PWH/PWL/PDH/PDL descope, see Architecture Patterns) | `bsl_type`/`ssl_type` are byte-identical to `bsl_significance`/`ssl_significance` in current source (`"bsl_type": sig, "bsl_significance": sig` — same value assigned twice) — drop the `_type` copy |
| `supply_demand_zones.py` | `nearest_demand_high/low`, `nearest_supply_high/low` | **`demand_dist_atr`/`supply_dist_atr` ALREADY exist and correctly ATR-normalized** — drop raw only | — | — |
| `breaker_blocks.py` | `breaker_block_top`, `breaker_block_bottom` | **`breaker_dist_atr` ALREADY exists and correctly ATR-normalized** — drop raw only | — | — |
| `mitigation_blocks.py` | none raw-price | `ob_mitigation_pct` already [0,1] | — | `ob_mitigation_status` (string) fully redundant with `ob_mitigation_pct` — drop, don't ordinal-encode a duplicate |
| `bos_choch.py` | `bos_level` | `bos_strength`/`choch_strength` already ATR-normalized (break-distance/ATR) — these may already fully substitute for a distance field; confirm with planner whether a separate `bos_dist_atr` is needed beyond `bos_strength` | `bars_since_last_shift` (not in current outputs; derive from tracked break-bar index) | `bos_confidence` is byte-identical to `bos_strength` in current source (`"bos_confidence": bos_strength`) — drop |
| `amd_cycle.py` | none raw-price (but `amd_phase` is a raw **string**, not numeric) | `manip_strength` exists but is **unbounded** — needs clamp before it counts as "already correct" | `amd_phase` ordinal encoding (0/1/2/3); clamp `manip_strength` to [0,1] | — |

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Swing-point / pivot detection | A new peak/trough finder | `find_peaks`/`find_troughs` (`src/intelligence/utils.py`) via `swing_utils.py`'s existing re-export shim | Already live, already used by `liquidity_sweeps.py`, `liquidity_pools.py`, `bos_choch.py`, and Phase 163's own S/R clustering — one implementation, not a second copy |
| Bounded strength/decay scoring | Custom min/max clamping per plugin | `linear_ramp`, `clamp`, `freshness_decay` (`src/intelligence/utils.py` + `utils/gradient_utils.py`) | Already used correctly by `liquidity_sweeps.py` (`sweep_strength`) and `supply_demand_zones.py` (`demand_freshness`) — reuse the same functions for the new `manip_strength` clamp and any other new bounding needed |
| ATR access | Recomputing ATR inline in a new SMC block | `atr_val` — already computed once in `compute()`/`compute_batch()` before Phase 163's structural block, and `get_atr(features)` where the archived plugin threads a features dict (bos_choch.py, breaker_blocks.py, mitigation_blocks.py) | Same value, same computation, avoid drift between two ATR calculations in one pass |
| Session-boundary-reset accumulation | A bespoke reset-detection helper for AMD's overnight window | Copy `update_wk_vwap()`'s reset-on-boundary-change shape (compare `(prior_boundary_key)` vs `(current_boundary_key)`, reset accumulators on change) | Exact same pattern, different boundary calculation (UTC hour rollover vs ISO week) — no new abstraction needed |
| Persistence column wiring | A new INSERT-building helper | `feature_vector_persistence.py`'s existing append-only `_XXX_FIELD_NAMES` slice + derive-by-name convention (`_STRUCTURAL_VP_SR_FIELD_NAMES` is the direct precedent) | The completeness-guard test (`tests/unit/test_feature_vector_persistence_completeness.py`) structurally enforces every `FeatureVector` field appears in the INSERT — hand-rolling a parallel column list reintroduces the exact bug class the 2026-07-08 incident (91/152 columns silently discarded) created |

**Key insight:** every genuinely reusable primitive this phase needs (peak/trough detection,
bounded scoring, ATR access, session-boundary accumulation, persistence wiring) already exists
live in the codebase, most of it built specifically for Phase 163's identical port. This phase's
real work is the field-by-field raw-price cleanup and the cross-plugin sequencing above, not new
infrastructure.

## Common Pitfalls

### Pitfall 1: Trusting ROADMAP.md's "self-contained, no cross-plugin dependency" framing
**What goes wrong:** Planning tasks as 8 fully independent, parallelizable ports when 3 of the 8
files have real (2 hard, 1 soft) dependencies on each other's output within the same compute
pass.
**Why it happens:** ROADMAP.md's claim was based on file-level self-containment (no imports of
one plugin module from another) rather than runtime data-flow dependency (reading another
plugin's *output dict* at call time via `frames.get("smc")` fusion) — a distinction the archived
v2.x tiered pipeline handled via ordering (`I1 -> I3 -> I4 -> SMC -> I6`) but a naive "port each
file independently" plan would miss.
**How to avoid:** Follow the single-pass ordering table above; write breaker_blocks/
mitigation_blocks/supply_demand_zones' tests with fixture OB/FVG/pool data injected explicitly,
not assumed absent.
**Warning signs:** A test for `breaker_blocks` port that never constructs a preceding
mitigated order block will always exercise the "no breaker" branch and pass vacuously.

### Pitfall 2: Persisting the archived plugin's exact output dict verbatim
**What goes wrong:** A literal 1:1 port (rename `compute_full` -> inline block, keep every
output key) reintroduces every raw-price field the audit table above lists — the identical
mistake Phase 163's original VP scoping made (D-16 correction after the fact).
**Why it happens:** The archived plugins were designed to feed v2.x I7 trading plugins that
did their own ATR-normalization at consumption time; v3's `FeatureFactory` has no such
downstream consumer and feeds `ic_engine`/ensemble training directly on whatever is persisted.
**How to avoid:** Use the field-by-field audit table as the literal task checklist — for each
plugin, list only the surviving fields before writing the migration.
**Warning signs:** A migration or `FeatureVector` field named `*_top`, `*_bottom`, `*_level`,
`*_midpoint`, `*_high`, `*_low` (excluding already-established exceptions like `dist_from_high`/
`dist_from_low`, which are themselves distances, not raw levels).

### Pitfall 3: Assuming `manip_strength`/`sweep_depth_pct`/other magnitude fields are already bounded
**What goes wrong:** Persisting `amd_cycle.py`'s `manip_strength` as-is produces values >1.0
whenever a manipulation wick overshoots the overnight range by more than 100% — silently
breaking any downstream assumption that "strength" fields sit in [0,1] the way `sweep_strength`/
`demand_freshness`/`ob_strength` do.
**Why it happens:** Only some of the 8 files apply `linear_ramp`/`min(1.0, ...)` clamping
consistently; `amd_cycle.py` computes a raw ratio with no clamp at all.
**How to avoid:** Audit every "strength"/"score" field for an explicit upper bound before
porting, not just the ones ROADMAP.md's candidate list names.
**Warning signs:** A `feature_registry` row for a "strength" field with no `normalization=
'bounded_unsigned'`/`'bounded'` tag, or IC screening later surfacing an implausible outlier
influence from one column.

### Pitfall 4: Treating `amd_phase`/`ob_mitigation_status` as droppable-in-place string fields
**What goes wrong:** These are Python `str` return values in the archived source
(`"accumulation"`, `"fresh"`, etc.) — a naive port that just changes the type annotation to
`float` without an explicit ordinal mapping will crash at the first `FeatureVector(...)`
construction or, worse, silently coerce via a bug (e.g. `hash(str) % N`) that isn't
reproducible/documented.
**Why it happens:** The archived plugins predate v3's all-`float` `FeatureVector` schema
discipline entirely — they were written for a dict-based intelligence-event bus that tolerated
mixed types.
**How to avoid:** Write the ordinal mapping explicitly in a migration COMMENT (matching
migration 255's per-column documentation convention) before implementation starts.

## Code Examples

### Verified pattern: session-boundary-reset accumulator (`FeatureCache.update_wk_vwap`, direct template for AMD's new mutator)

```python
# Source: src/intelligence/feature_cache.py:165-188 (live, verified 2026-07-25)
def update_wk_vwap(
    self,
    bar_ts: datetime,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> None:
    """Update weekly VWAP state and set above_wk_vwap from current bar.

    Resets accumulators at ISO week boundary. Called by the pipeline or backfill
    once per bar, after FeatureFactory.compute().
    """
    iso = bar_ts.isocalendar()
    year_week = (iso.year, iso.week)
    if year_week != self._wk_year_week:
        self._wk_tp_vol_sum = 0.0
        self._wk_vol_sum = 0.0
        self._wk_year_week = year_week
    typical = (high + low + close) / 3.0
    self._wk_tp_vol_sum += typical * volume
    self._wk_vol_sum += volume
    wk_vwap = self._wk_tp_vol_sum / self._wk_vol_sum if self._wk_vol_sum > 1e-10 else close
    self.above_wk_vwap = float(close > wk_vwap)
```
AMD's new mutator follows this exact shape: replace `year_week = iso.isocalendar()` with a UTC-
hour-rollover boundary key (e.g. `(bar_ts.date(), bar_ts.hour >= 20)` transitioning to a new
accumulation window), replace the VWAP running sums with `min`/`max` accumulation of high/low.

### Verified pattern: append-only persistence field-name slice (`feature_vector_persistence.py`, direct template for this phase's new fields)

```python
# Source: src/intelligence/features/feature_vector_persistence.py (live, verified 2026-07-25)
# _STRUCTURAL_VP_SR_FIELD_NAMES is Phase 163's precedent -- Phase 164 adds an
# analogous _SMC_FIELD_NAMES slice, appended after it, same derive-by-name discipline:
_STRUCTURAL_VP_SR_FIELD_NAMES: tuple[str, ...] = _ALL_FEATURE_VECTOR_FIELD_NAMES[
    # slice bounds computed from dataclasses.fields(FeatureVector) order, not hand-typed
]
# INSERT SQL and the row-serializer params tuple both derive from this slice by name --
# tests/unit/test_feature_vector_persistence_completeness.py enforces every
# dataclasses.fields(FeatureVector) entry appears here, structurally.
```

### Verified pattern: stateless full-window recompute, no incremental branch (`ctx_VolumeProfile`, Phase 163's D-13 precedent — reuse for all 8 SMC plugins)

```python
# Source: src/intelligence/archive/smc_context/order_blocks.py:157-158 (live, verified 2026-07-25)
def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
    return self.compute_full(windows)
```
Every one of the 8 in-scope files already has this exact `compute_next -> compute_full`
delegation. Port target: fold the body of `compute_full` directly into the appropriate section
of `feature_factory.py`'s `compute()`/`compute_batch()` — no new incremental code path.

## State of the Art

| Old Approach (v2.x archived) | Current Approach (v3) | When Changed | Impact |
|--------------------------------|------------------------|---------------|--------|
| Tiered plugin registry (`I1->I3->I4->I5->SMC->I6->I7`), each plugin a `dataclass` with `compute_full`/`compute_next`, registered via `register_plugins.py` | Single pure `FeatureFactory.compute()`/`compute_batch()` function, `FEATURE_VECTOR_DOMAIN`-tagged fields, `FeatureCache` for mutable state | v3.0 rebuild (2026-06), reconfirmed by Phase 163 (2026-07-24) | This phase's plugin protocol (`plugin-reference`/`add-plugin` skill docs) describes the **archived, dead** system — do not follow those skills' Gate 4/5 (`register_plugins.py`, `wire-pipeline`) for this phase; follow Phase 163's actual file-touch pattern instead (see below) |
| Cross-plugin fusion via `frames.get("smc")`/`frames.get("i4")` dict merging, resolved by pipeline ordering | Cross-primitive fusion via plain Python variables threaded through one function body in explicit call order | Same as above | Simpler, no dict-merge indirection, but the *dependency itself* (order_blocks -> breaker/mitigation) still needs to be respected in code order |
| Raw price levels (`poc_price`, `ob_top`, `bsl_level`, etc.) persisted as event-bus payload for I7 consumption | Only ATR-distance/percentage/bounded/count/ordinal fields persisted to `feature_vectors` — raw levels are intermediate-only | Phase 163 D-16 (2026-07-20) | This phase's central discipline; see Field-by-Field Raw-Price Audit |

**Deprecated/outdated:**
- `.claude/skills/add-plugin/SKILL.md` and `.claude/skills/plugin-reference/SKILL.md` — both
  describe the archived I1-I7 tiered plugin registry (`register_plugins.py`,
  `src/intelligence/smart_money/`, `TIER_*` constants, `registry.register_pattern()`). Per
  `src/intelligence/CLAUDE.md`'s own archived-system banner and this project's "check archived
  before investigating" convention, **do not use these skills' Gate 4 (Register) or Gate 5
  (Wire Pipeline) steps for this phase.** Follow Phase 163's actual precedent instead: edit
  `feature_cache.py` + `feature_factory.py` + `feature_vector_persistence.py` + `schemas.py`
  directly, no plugin registry involved. (Gates 1-3's general design/plan/TDD discipline still
  applies as generic project process, just not the plugin-specific mechanics in Gates 4-6.)

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Recommended descope of PWH/PWL/PDH/PDL (vs. building new cross-timeframe cache plumbing) is the right call for this phase | Architecture Patterns | If wrong, this phase's `liquidity_pools` port is materially incomplete relative to ROADMAP's implied full port; a future phase would need to revisit with real HTF-cache design work |
| A2 | `amd_phase` ordinal encoding (0=unknown/1=accumulation/2=manipulation/3=distribution) is an arbitrary but reasonable mapping | Anti-patterns to avoid | Low — any consistent, documented mapping works equally for downstream IC screening; only matters if a specific ordinal relationship (e.g. phase progression) is assumed by a future consumer |
| A3 | `bos_strength`/`choch_strength` already substitute for a `bos_dist_atr` field, so no new distance derivation is strictly required for BOS/CHoCH | Field-by-Field Raw-Price Audit | Low-medium — if the planner/user wants a literal "distance to bos_level" concept distinct from "break magnitude," a new field would need deriving as `(close - bos_level) / atr` before persisting `bos_level` itself is dropped |
| A4 | `feature.smc.<concept>.*` (nested per-concept APR namespace) is the right convention, vs. Phase 163's flatter `feature.session_vp.*`/`feature.sr.*` (one namespace per sub-feature-family, matching that phase's 2-concept scope) | APR namespace section below | Low — either convention works technically (no schema constraint on key depth); a mismatch just means a slightly less consistent `config_state` key list, not a functional bug |
| A5 | New `FEATURE_VECTOR_DOMAIN` tag should be `"smart_money"` (matching the archived plugins' own `capability_tags` value) rather than reusing `"structural"` or inventing another term | Architecture Patterns / Standard Stack | Low — purely a screening/grouping label for collinearity sweeps and IC dashboards, easy to rename later |

**All five assumptions above are Claude's Discretion recommendations pending user/planner
confirmation, not verified facts about what the user wants** — none of them come from an
existing CONTEXT.md (this phase has none yet) or a locked ROADMAP.md decision.

## Open Questions

1. **Should `bars_since_last_sweep`/`bars_since_last_shift` be raw bar counts or ATR-time-normalized?**
   - What we know: Phase 163's D-19 precedent (`resistance_age_bars`/`support_age_bars`) treats
     bar counts as directly comparable across symbols with no normalization, following the
     existing `swing_high_age_bars`/`trend_duration_bars`/`macd_cross_bars_ago` convention.
   - What's unclear: whether that convention should extend uniformly to this phase's new
     "bars since X" fields or whether any of them warrant a different treatment.
   - Recommendation: follow the D-19 precedent (raw bar count, `normalization='none'`
     equivalent) for consistency — no evidence this phase's fields are meaningfully different.

2. **Does `smc_trend_direction` (BOS/CHoCH's 2-swing-point trend call) overlap materially with
   the existing per-symbol HMM regime direction?**
   - What we know: both are "trend direction" signals, but computed by entirely different
     methods (2-point swing-high/swing-low comparison vs. a fitted HMM over log-return +
     realized-vol). Not provably redundant without measurement.
   - What's unclear: correlation strength, whether it clears Phase 163's D-07-style
     incremental-IC bar.
   - Recommendation: include in whatever collinearity/incremental-IC sweep this phase's
     promotion-bar work runs (ROADMAP already calls for one shared sweep across the whole
     "distance to level" family — extend it to include this "trend direction" family pairing
     too, don't treat it as a separate concern).

3. **Migration number: is 259 still free at plan/execution time?**
   - What we know: 258 is the current max (`258_curve_credit_causal_rank_calibration.sql`,
     confirmed 2026-07-25 by directory listing).
   - What's unclear: whether a concurrent session claims 259 before this phase executes (the
     project has hit this exact collision twice before — migration 243's plan-text vs.
     migration 255's actual-assigned number, and migration 216's analogous note).
   - Recommendation: re-verify `ls production/migrations/ | sort -V | tail -3` immediately
     before writing the migration file, not just at planning time — same discipline migration
     255's own header comment documents.

## Environment Availability

Skipped — this phase makes no new external tool/service/runtime dependencies. All required
libraries (`numpy`, `pandas`) and utilities (`find_peaks`/`find_troughs`/`clamp`/`linear_ramp`/
`freshness_decay`/`utc_datetime_from_df`/`get_atr`) are already live, non-archived, importable
from the current codebase — verified directly by reading `src/intelligence/utils.py`,
`src/intelligence/utils/gradient_utils.py`, and `src/intelligence/trading/atr_utils.py`.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (already project-standard) |
| Config file | none dedicated — project-wide `pytest.ini`/`pyproject.toml` config already governs `tests/unit/` |
| Quick run command | `.venv/bin/pytest tests/unit/intelligence/test_smc_<concept>.py -x -q` (per new test file, matching Phase 163's `test_support_resistance_primitives.py`/`test_volume_profile_primitives.py` naming precedent) |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements -> Test Map

No formal `REQUIREMENTS.md` IDs exist for this project (verified: `.planning/REQUIREMENTS.md`
does not exist; only a milestone-scoped `.planning/milestones/v2.10-REQUIREMENTS.md` exists,
unrelated to this phase). Following Phase 163's own precedent ("Requirements: closes todo 153,
no formal REQUIREMENTS.md IDs; governed by decisions..."), this phase should be governed by
CONTEXT.md decisions once `/gsd-discuss-phase 164` or equivalent runs, not formal REQ-IDs.
Provisional behavior-to-test map based on this research's own findings:

| Behavior | Test Type | Automated Command | File Exists? |
|----------|-----------|-------------------|-------------|
| Order-blocks detection produces `ob_dist_atr` (not raw `ob_top`/`ob_bottom`) on synthetic impulse+OB fixture | unit | `pytest tests/unit/intelligence/test_smc_order_blocks.py -x -q` | ❌ Wave 0 |
| Breaker/mitigation blocks correctly derive from order-blocks output within the same compute pass (no cross-call state) | unit | `pytest tests/unit/intelligence/test_smc_order_blocks.py -x -q` (same file, sequencing dependency) | ❌ Wave 0 |
| FVG detection produces `fvg_size_atr`/`fvg_dist_atr` (not raw `fvg_top`/`fvg_bottom`/`fvg_midpoint`) | unit | `pytest tests/unit/intelligence/test_smc_fvg.py -x -q` | ❌ Wave 0 |
| Liquidity sweeps produce bounded `sweep_strength`/`reclaim_velocity` + `bars_since_last_sweep` | unit | `pytest tests/unit/intelligence/test_smc_liquidity.py -x -q` | ❌ Wave 0 |
| Liquidity pools produce `bsl_dist_atr`/`ssl_dist_atr` from single-tf sources only (PWH/PWL/PDH/PDL descoped) | unit | `pytest tests/unit/intelligence/test_smc_liquidity.py -x -q` (same file) | ❌ Wave 0 |
| Supply/demand zones correctly consume FVG + LiquidityPools output in sequence | unit | `pytest tests/unit/intelligence/test_smc_zones.py -x -q` | ❌ Wave 0 |
| BOS/CHoCH produces `bars_since_last_shift`, drops `bos_level`/`bos_confidence` | unit | `pytest tests/unit/intelligence/test_smc_structure.py -x -q` | ❌ Wave 0 |
| AMD cycle's overnight-range state survives across bars via new `FeatureCache` mutator, resets at UTC 20:00 boundary, `amd_phase` ordinal-encoded, `manip_strength` clamped [0,1] | unit | `pytest tests/unit/intelligence/test_smc_amd_cycle.py -x -q` | ❌ Wave 0 |
| Live vs. batch parity for all new fields (matching `test_feature_factory_batch_parity.py`'s existing convention) | unit | `pytest tests/unit/intelligence/test_feature_factory_batch_parity.py -x -q` (extend existing file) | ✅ (extend) |
| `feature_vector_persistence.py` completeness guard covers new fields | unit | `pytest tests/unit/test_feature_vector_persistence_completeness.py -x -q` | ✅ (structural, auto-covers) |

### Sampling Rate
- **Per task commit:** the relevant `test_smc_*.py -x -q` file for that task
- **Per wave merge:** `.venv/bin/pytest tests/unit/intelligence/ -q`
- **Phase gate:** `.venv/bin/pytest tests/unit/ -q` full suite green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/intelligence/test_smc_order_blocks.py` — covers order blocks + breaker +
      mitigation (sequenced together)
- [ ] `tests/unit/intelligence/test_smc_fvg.py` — covers fair value gaps
- [ ] `tests/unit/intelligence/test_smc_liquidity.py` — covers liquidity sweeps + pools
- [ ] `tests/unit/intelligence/test_smc_zones.py` — covers supply/demand zones
- [ ] `tests/unit/intelligence/test_smc_structure.py` — covers BOS/CHoCH
- [ ] `tests/unit/intelligence/test_smc_amd_cycle.py` — covers AMD cycle + new `FeatureCache`
      mutator
- Confirmed via direct grep (`grep -rl "smc_context\|OrderBlocksPlugin\|..." tests/`): **zero
  existing tests reference any of these 8 archived plugin classes** — full Wave 0, no partial
  coverage to build on.

## Security Domain

`security_enforcement` is absent from `.planning/config.json` (treated as enabled per protocol
default), but this phase has essentially no attack surface to evaluate: it is internal batch/
live feature computation over already-ingested, already-trusted OHLCV market data, with no user
input, no authentication/session surface, no network-facing endpoint, and no new external
package. Determination below, not a skipped section.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | No auth surface — internal compute pipeline |
| V3 Session Management | No | No session surface |
| V4 Access Control | No | No new access-controlled resource |
| V5 Input Validation | Marginal | `FeatureFactory.compute()`'s existing "yields 0.0 for continuous features" cold-start convention already guards against insufficient/malformed bar history; new SMC fields must follow the same guard (return neutral defaults, never raise, never emit NaN/Inf into `feature_vectors` — matches every existing field's contract) |
| V6 Cryptography | No | No cryptographic operation involved |

### Known Threat Patterns for this stack
Not applicable — no injection surface, no serialization of untrusted input, no new
authentication/authorization boundary. The one real correctness-adjacent risk (silent
NaN/Inf/unbounded-value propagation into a training feature) is already covered under V5 above
and under Common Pitfall 3 (unbounded `manip_strength`).

## Sources

### Primary (HIGH confidence — direct source read, 2026-07-25)
- `src/intelligence/archive/smc_context/order_blocks.py` — full read, `OrderBlocksPlugin`
- `src/intelligence/archive/smc_context/fair_value_gap.py` — full read, `FairValueGapPlugin`
- `src/intelligence/archive/smc_context/liquidity_sweeps.py` — full read, `LiquiditySweepsPlugin`
- `src/intelligence/archive/smc_context/liquidity_pools.py` — full read, `LiquidityPoolsPlugin`
- `src/intelligence/archive/smc_context/supply_demand_zones.py` — full read, `SupplyDemandZonesPlugin`
- `src/intelligence/archive/smc_context/breaker_blocks.py` — full read, `BreakerBlocksPlugin`
- `src/intelligence/archive/smc_context/mitigation_blocks.py` — full read, `MitigationBlocksPlugin`
- `src/intelligence/archive/smc_context/amd_cycle.py` — full read, `AMDCyclePlugin`
- `src/intelligence/archive/smc_context/bos_choch.py` — full read, `BOSCHoCHPlugin`
- `src/intelligence/archive/smc_context/premium_discount.py` — full read (confirms exclusion rationale + cross-references `LiquidityPools`)
- `src/intelligence/archive/smc_context/swing_utils.py` — full read (confirms thin re-export of live `find_peaks`/`find_troughs`)
- `src/intelligence/archive/smc_context/ict_killzones.py` — full read (confirms already-ported claim, notes different UTC windows than live `in_london_kz`/`in_overlap`/`power_hour`)
- `src/intelligence/utils.py` — confirmed live `find_peaks`/`find_troughs`/`clamp`/`utc_datetime_from_df`
- `src/intelligence/utils/gradient_utils.py` — confirmed live `linear_ramp`/`freshness_decay`
- `src/intelligence/feature_factory.py` — `compute()` signature (lines 3785-3811), `FEATURE_VECTOR_DOMAIN` dict (lines 64-175), `_in_london_kz`/`_in_overlap`/`_power_hour` (lines 1616-1654)
- `src/intelligence/feature_cache.py` — `FeatureCache` dataclass, `update_wk_vwap()` (lines 165-188), `update_session_vp()` header comment (Phase 163 precedent)
- `src/intelligence/features/feature_vector_persistence.py` — full header + `_STRUCTURAL_VP_SR_FIELD_NAMES` pattern
- `production/migrations/255_vp_structural_primitives.sql` — full read, migration structure, APR key seeding pattern, `feature_registry` insert convention
- `production/migrations/` directory listing — confirmed 258 is current max, 259 is next-free as of 2026-07-25
- `.planning/phases/163-vp-sr-structural-primitives/163-CONTEXT.md` — full read, D-01 through D-19
- `.planning/ROADMAP.md` — Phase 163 (lines 2176-2210) and Phase 164 (lines 2212-2291) sections, full read
- `.claude/skills/add-plugin/SKILL.md`, `.claude/skills/plugin-reference/SKILL.md` — full read, confirmed describes the archived I1-I7 system, not applicable to this phase's actual wiring pattern
- `src/intelligence/CLAUDE.md` — archived-system banner
- `/home/bg/dev/indicagent/CLAUDE.md` — project constraints (APR mandate, DAG invariants, naming system)
- `.planning/config.json` — `nyquist_validation: true`, no `security_enforcement` key

### Secondary (MEDIUM confidence)
- none — all findings verified against primary source in this session

### Tertiary (LOW confidence)
- none

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages, confirmed by direct import inspection
- Architecture: HIGH — cross-plugin dependencies and the cross-timeframe gap confirmed by direct
  source read against both the archived plugins and the live `compute()` signature, not inferred
- Raw-price audit: HIGH — every field in the audit table read directly from archived source
- Pitfalls: HIGH — each pitfall traces to a specific, cited line in the archived source
- APR namespace / domain-tag recommendations (A4/A5): MEDIUM — reasonable per existing
  convention but genuinely Claude's Discretion, not verified user preference

**Research date:** 2026-07-25
**Valid until:** 30 days (stable internal codebase, not a fast-moving external dependency) —
re-verify the migration-number assumption (Open Question 3) immediately before execution
regardless of research age, per the project's documented history of migration-number collisions.
