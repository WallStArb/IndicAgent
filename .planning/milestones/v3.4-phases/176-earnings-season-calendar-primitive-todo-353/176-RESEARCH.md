# Phase 176: Earnings-Season Calendar Primitive (todo 353) - Research

**Researched:** 2026-09-22
**Domain:** `feature_factory.py` calendar-group primitive addition + `ic_engine.py` regime-stratification extension (internal Python/TimescaleDB pipeline, no external services)
**Confidence:** HIGH for architecture/patterns (all claims code-grounded, live-verified against the actual repo); MEDIUM for the up_vol_body_diff evidence re-verification (attempted live, blocked by DB contention — see Assumptions Log)

## Summary

This phase has two connected workstreams (D-01): ship a new calendar-group `FeatureVector`
primitive, and wire it into `ic_engine.py`'s regime segmentation. Both have close, well-worn
precedent already living in this codebase — `opex_flag`/`quad_witching_flag`
(migration 290, Phase 151 Plan 05) are a near-exact structural twin of what this phase needs to
build: a tier-1 event flag, deterministic function of `bar_ts` alone, registered in
`concept_registry` with two tier-0 `parent_features` for partial-IC control. `regime_volatility`'s
existing per-symbol stratification pass in `ic_engine.py` (`_build_regime_passes`,
`_compute_one_regime_cell`) is a near-exact structural twin of the mask-based extension this
phase's regime-conditioning half needs — no new mechanism class required.

Two things in CONTEXT.md need correction before planning, both backed by code/doctrine found
during this research, not opinion:

1. **Naming:** `is_earnings_season` does not conform to `naming-system.md` §7a's calendar
   primitive vocabulary (fixed 4-form list, "no exceptions") or `glossary.md`'s `calendar
   primitive` doctrine (`docs/research/signal-temporal-atomic-primitives.md`). A binary that
   selects a specific window within a cycle is, by explicit doctrine, an **event flag**,
   permitted only at `tier='1_interaction'`, named `<event>_flag`. The correct name is
   **`earnings_season_flag`**, mirroring `opex_flag`/`quad_witching_flag` exactly. This is not
   a style nit — the same doctrine document explicitly banned `is_opex_day` at tier 0 for the
   identical reason and the codebase's own ROADMAP was corrected for it (2026-07-13). Recommend
   the plan adopt `earnings_season_flag` and correct CONTEXT.md's field name accordingly.

2. **Site count:** CONTEXT.md's "3-site-plus-migration" estimate for the primitive undercounts
   the real blast radius. Live grep of the `opex_flag`/`quad_witching_flag` precedent found the
   actual FeatureVector dataclass lives in `src/intelligence/schemas.py` (not
   `feature_factory.py`), and a canonical column-order module
   (`src/intelligence/features/feature_vector_persistence.py`) derives the SQL INSERT column
   list from the dataclass field order via named contiguous slices — a real, structural,
   change-detecting mechanism, not boilerplate to skip. The true site count for a 2-field
   calendar addition is **8-9 files** (see Architecture Patterns → Site Inventory below), not 3.
   Undercounting this is how "91/152 fields silently unpersisted for an entire corpus rebuild"
   happened before this pattern existed (see that module's own docstring) — treat the site
   inventory below as load-bearing, not decorative.

Live DB re-verification of D-04's primary effect was not re-attempted (already independently
re-verified in the CONTEXT.md discussion session, 1.90x/p=5.05e-05/67%, cite that number, not
the todo's original 4.3x/p=1.2e-17). Live re-verification of the **second finding**
(`up_vol_body_diff`'s IC roughly doubling in-season) was attempted this session and **blocked**
by a genuine, currently-running `decompress_chunk()` operation against a `feature_vectors`
chunk plus a wave of `autovacuum` workers queued behind it (observed directly in
`pg_stat_activity`, 19+ minutes in progress) — see Assumptions Log entry A1. This finding
remains unverified going into planning; treat it as directional evidence for prioritizing the
regime-conditioning workstream, not as a locked number to cite in the eventual
`concept_registry` row or promotion write-up.

**Primary recommendation:** Ship `earnings_season_flag` (tier-1 event flag) +
`days_since_quarter_end` (tier-1 continuous companion, NOT tier-0 — see Architecture Patterns)
in `feature_factory.py`/`schemas.py`/`feature_vector_persistence.py` following the
`opex_flag`/`quad_witching_flag` precedent file-for-file. For the `ic_engine.py` integration,
extend `_build_regime_passes()` with a new APR-gated `earnings_season` pass (reusing
`_compute_one_regime_cell`'s existing mask mechanism) on the per-symbol side, and post-hoc-mask
the already-materialized cell arrays inside `_compute_one_cross_sectional_cell`'s caller on the
cross-sectional side — do **not** build a new Phase-144-style `regime_group` (wrong shape: that
mechanism partitions the *universe* into disjoint peer groups; earnings season applies
uniformly to every equity symbol at once).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `earnings_season_flag` / `days_since_quarter_end` computation | Compute (`feature_factory.py`, Ring 1) | — | Pure, stateless, O(1) function of `bar_ts` — same tier as every existing calendar primitive; zero IO per `compute()`'s PURITY CONTRACT |
| Persistence of the 2 new columns | Persistence (`FeatureVectorWriter` / `feature_vector_persistence.py`) | — | DAG invariant 3: a compute daemon never writes its own output; `FeatureVectorWriter` is the sole writer, feeding off the canonical column-order module |
| APR window-boundary values (14/42 days) | Config (`ConfigService` via `FeatureFactoryConfig`) | — | D-03 mandate: no magic numbers; boundaries must be `ConfigService.get()`-sourced, pre-fetched into the frozen config object at `_prewarm_threshold_config()` time (compute() itself does zero IO) |
| Regime-conditioning stratification (reading the persisted flag) | Measurement (`ic_engine.py`) | — | D-03 mandate: `ic_engine.py` reads the already-persisted column, never recomputes calendar math itself — SoC between compute and measurement stages holds |
| `concept_registry` genesis seed (tier=1_interaction, group=calendar) | Governance (migration-time DDL) | — | Migration-time genesis-seeding exemption (unified-concept-registry.md) — a schema migration inserting the new concept's row directly, same as migrations 288-291/316 |

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 (scope):** Build BOTH workstreams (primitive + regime-conditioning integration) in
  this phase, not staged across two phases.
- **D-02 (field scope):** Ship both `is_earnings_season` (binary — **see naming correction
  above: `earnings_season_flag`**) and `days_since_quarter_end` (continuous companion). The
  continuous companion has NO proxy-test evidence of its own — treat it as unvalidated,
  independently gated, not exempted by the binary's evidence.
- **D-03 (design principles):** Renaissance-rigor lens binding for planning and execution:
  data integrity / no hidden bias (re-verify `up_vol_body_diff` before relying on it — attempted
  this session, blocked, see Assumptions Log A1); ruthless simplicity / component reuse (must
  reuse the existing calendar-group pattern and `ic_engine.py`'s existing stratification
  machinery, not invent a parallel mechanism); DAG topology / SoC (compute stays separate from
  persistence stays separate from measurement — `ic_engine.py` reads the persisted column, never
  computes calendar math itself); no magic numbers (14/42-day window boundaries MUST be
  APR-backed, `feature.earnings_season.*` namespace or similar, never hardcoded literals).
- **D-04 (corrected evidence base):** Primary effect corrected 2026-09-22: **1.90x ratio**
  (0.000397 in-season vs. 0.000209 off-season), **Welch p=5.05e-05**, **67% of symbols**
  (155/233) higher in-season — cite these numbers, not the todo's original 4.3x/p=1.2e-17/81%.
  The `up_vol_body_diff` second finding (+0.0197 vs. +0.0103 Spearman IC) was NOT
  independently re-verified in the discussion session and remains unverified after this
  research session too (DB contention, see A1) — do not cite as locked evidence.

### Claude's Discretion

- Exact implementation shape of the `ic_engine.py` regime-conditioning integration — **resolved
  by this research, see Architecture Patterns below: extend `_build_regime_passes()` with a
  new mask-based pass (per-symbol side) + post-materialization masking inside the
  cross-sectional cell caller (cross-sectional side). Not a new `regime_group`.**
- Whether `days_since_quarter_end` is raw days or normalized — **informed by this research: a
  live-computed Spearman correlation of 0.935 exists between raw calendar days-since-quarter-end
  and the already-live `quarter_position` field (measured this session, 11-year daily series,
  n=4018) — material but not exact collinearity (unlike the exact -1.0 redundancy that got
  `days_to_month_end` removed). Recommend keeping it a raw, unnormalized day count (fits fine at
  tier-1, which is not bound by the tier-0 [0,1]-fraction naming rule), registered with
  `parent_features` including `quarter_position` so the existing partial-IC control machinery
  (todo 037 methodology) tests it for genuine incremental IC before treating it as validated.**

### Deferred Ideas (OUT OF SCOPE)

None raised beyond the phase's own two workstreams — discussion stayed within scope.

## Standard Stack

No new external libraries. This phase is pure internal Python (numpy/psycopg already in use)
+ SQL migration. No `npm install` / `pip install` — **Package Legitimacy Audit section omitted**
per protocol (nothing to audit; no external packages introduced).

## Architecture Patterns

### System Architecture Diagram

```
bar_ts (already in every feature_factory.py compute call)
   |
   v
_earnings_season_flag(bar_ts, config)         _days_since_quarter_end(bar_ts)
   |  (config.earnings_season_start_days,          |  (pure calendar arithmetic,
   |   config.earnings_season_end_days,             |   no APR params needed)
   |   APR-backed, feature.earnings_season.*)       |
   +------------------------+------------------------+
                            |
                            v
              FeatureVector (schemas.py, +2 fields
              appended after volume_z_velocity)
                            |
                            v
        feature_vector_persistence.py (_ALL_COLUMN_NAMES +=
        new contiguous slice; INSERT SQL derived, not hand-typed)
                            |
                            v
        FeatureVectorWriter (sole writer) --> feature_vectors (TimescaleDB)
                            |
                            v
        ic_engine.py: SELECT bar_ts, regime_volatility, earnings_season_flag, {feature_cols}
        FROM feature_vectors ...   <-- reads the PERSISTED column, never recomputes
                            |
            +---------------+----------------------------+
            |                                             |
            v (per-symbol path)                           v (cross-sectional path)
   _build_regime_passes() appends a new                _compute_one_cross_sectional_cell's
   ("earnings_season_aligned", ["in_season",            caller masks the ALREADY-fetched
    "off_season"], "earnings_season") pass,              cell arrays in-memory by the aligned
   feeding the SAME existing                             earnings_season column (no 2nd DB
   _compute_one_regime_cell(mask=...) call               fetch), calling the SAME
   already used for regime_volatility                    _compute_one_cross_sectional_cell
            |                                             |
            +---------------------+-----------------------+
                                  v
                    feature_ic_scores rows, regime_scope='earnings_season'
                    (NEW CHECK-constraint value — migration required,
                     see Common Pitfalls)
                                  |
                                  v
                    Standard FDR/walk-forward gate (unchanged machinery)
```

### Site Inventory (correcting CONTEXT.md's "3-site-plus-migration" undercount)

Live-verified against the `opex_flag`/`quad_witching_flag` precedent (migration 290, Phase 151
Plan 05) — this is the exact shape (deterministic `bar_ts`-only calendar event flag) the new
fields must follow. Every site below currently touches `opex_flag`/`quad_witching_flag`; a new
field of the same shape touches all of them too:

| # | File | What changes |
|---|------|--------------|
| 1 | `src/intelligence/schemas.py` (`FeatureVector` dataclass, ~line 1204-1433) | Append 2 new fields immediately after `volume_z_velocity` (the current last field, confirmed live: `FeatureVector` has 298 fields today) |
| 2 | `src/intelligence/feature_factory.py` — pure function definitions (~line 3363-3384, next to `_opex_flag`/`_quad_witching_flag`) | New `_earnings_season_flag(bar_ts, config)` and `_days_since_quarter_end(bar_ts)` functions |
| 3 | `src/intelligence/feature_factory.py` — field-to-group dict (~line 236-237) | 2 new `"calendar"` entries |
| 4 | `src/intelligence/feature_factory.py` — `FeatureFactoryConfig` dataclass (~line 422+) | 2 new `int` fields for the APR-backed window boundaries (`earnings_season_start_days`, `earnings_season_end_days`) — `days_since_quarter_end` needs none |
| 5 | `src/intelligence/feature_factory.py` — `_build_feature_vector()` signature + body (~line 6244, ~line 6554) | New params + `_guard()`-wrapped construction |
| 6 | `src/intelligence/feature_factory.py` — `compute()` call site (~line 7249) | Pass computed values to `_build_feature_vector()` |
| 7 | `src/intelligence/feature_factory.py` — `compute_batch()` inline compute + `FeatureVector(...)` construction (~line 7768, ~line 8232) | Same pattern, 2 separate touch points within `compute_batch()` |
| 8 | `src/intelligence/feature_factory.py` — `_cold_start_vector()` (~line 8527) | `bar_ts is not None else <neutral>` pattern, matching `opex_flag`'s cold-start handling exactly |
| 9 | `src/intelligence/features/feature_vector_persistence.py` | New `_EARNINGS_SEASON_FIELD_NAMES` contiguous slice; append to `_ALL_COLUMN_NAMES` concatenation (~line 461) and to the params-building generator (~line 867); update module docstring (extends 298→300 columns) |
| 10 | `services/feature_vector_pipeline.py` — `_prewarm_threshold_config()` (production path, ~line 792 seed list + ~line 1051 construction) | Wire the 2 new APR keys |
| 11 | `services/backfill_feature_factory.py` (~line 506) | Mirror the same APR wiring for the batch/backfill init path |
| 12 | Migration `350_*.sql` | `ALTER TABLE feature_vectors ADD COLUMN`, APR key seed (`config_schema`/`config_state`/`config_history`), `concept_registry`/`concept_gate` genesis seed |
| 13 | `tests/unit/intelligence/test_feature_factory_p7.py` | New pure-function unit tests, mirroring `test_opex_flag_third_friday()` etc. (~line 473-490) |
| 14 | `tests/unit/services/test_feature_vector_writer_column_mapping.py` | **Must update the positional-index assertion** — currently asserts `quad_witching_flag` is the last element at param index 290 (`test_quad_witching_flag_at_index_290_is_last_element`); the new fields shift this index and need their own equivalent test |
| 15 | `tests/unit/services/test_feature_vector_writer.py`, `tests/unit/services/test_backfill_feature_factory.py` | Both construct full `FeatureVector(...)` fixtures with explicit `opex_flag=0.0, quad_witching_flag=0.0` kwargs — `FeatureVector` fields have no defaults, so these fixtures WILL fail to construct until the 2 new fields are added as kwargs too |

`services/feature_vector_writer.py` itself needs **no direct change** — confirmed via grep, it
delegates entirely to `feature_vector_persistence.py`'s generic `_record_to_insert_params()` /
`feature_vector_to_insert_params()`, which derives the SQL from the dataclass by name. This is
exactly the "derive-by-name, don't-hand-type" discipline that module's own docstring says exists
specifically because a hand-typed list let "91/152 fields silently unpersisted for an entire
corpus rebuild" happen once already — do not regress to hand-typing.

### Pattern 1: Tier-1 event flag registration (concept_registry)

**What:** New `FeatureVector` fields that select a specific window within a calendar cycle
(rather than spanning the whole cycle as a coordinate) register at `tier='1_interaction'`,
never `'0_atomic'`, with exactly 2 non-empty `parent_features` (the tier-0 atomics the
partial-IC control will condition against).

**When to use:** Any calendar-derived boolean or window-selecting continuous quantity — exactly
this phase's two new fields.

**Example (migration 290, live in this repo):**
```sql
-- Source: production/migrations/290_named_interaction_primitives.sql
INSERT INTO feature_registry
    (feature_name, group_name, tier, formula_short, normalization, linear_ready,
     requires_htf, status, added_phase, parent_features)
VALUES
('opex_flag',          'calendar', '1_interaction',
 'dow==Friday AND week_of_month==3 (monthly options expiration)',
 'bounded_unsigned', false, false, 'active', '151', ARRAY['dow_sin', 'week_of_month_sin']),
('quad_witching_flag', 'calendar', '1_interaction',
 'opex_flag AND month mod 3 == 0 (quarterly quad-witching)',
 'bounded_unsigned', false, false, 'active', '151', ARRAY['dow_sin', 'month_sin'])
ON CONFLICT (feature_name) DO NOTHING;
```
Note: `feature_registry` itself no longer exists (migration 311 DROPped it, Phase 170) —
migration 350 must seed `concept_registry`/`concept_gate` directly (see migration 316's
`concept_registry` INSERT for the current-generation pattern, reproduced below under Code
Examples). `parent_features` for the new fields: recommend `earnings_season_flag` takes
`ARRAY['quarter_position', 'quarter_cycle_sin']` (the natural tier-0 quarter-cycle controls,
same selection logic the doctrine doc prescribes for `opex_flag`/`quad_witching_flag`'s
parents — "the same-row columns partial_spearman_ic will control for"); `days_since_quarter_end`
takes `ARRAY['quarter_position', 'quarter_cycle_cos']` given the measured 0.935 correlation with
`quarter_position` (Open Questions/Pitfalls below).

### Pattern 2: APR-backed calendar boundary, threaded through `FeatureFactoryConfig`

**What:** `compute()`'s PURITY CONTRACT ("zero IO. No ConfigService.get(), no DB reads") means
window boundaries cannot be fetched inside the calendar function itself — they are pre-resolved
once into the frozen `FeatureFactoryConfig` object at `_prewarm_threshold_config()` time (2
call sites: production `services/feature_vector_pipeline.py`, batch
`services/backfill_feature_factory.py`), then threaded through as `config: FeatureFactoryConfig`.

**Example (existing precedent, `_in_ny_session`):**
```python
# Source: src/intelligence/feature_factory.py:1970
def _in_ny_session(bar_ts: datetime, config: FeatureFactoryConfig) -> float:
    """1.0 if bar_ts is within NY RTH, else 0.0."""
    total_minutes = bar_ts.hour * 60 + bar_ts.minute
    start_minutes = config.ny_session_start_utc_hour * 60 + config.ny_session_start_utc_minute
    end_minutes = config.ny_session_end_utc_hour * 60
    return 1.0 if start_minutes <= total_minutes < end_minutes else 0.0
```
The new `_earnings_season_flag(bar_ts, config)` should follow this exact shape (whole-config
param, not bare ints like `_ret_lag_fast(closes, window)`'s pattern — the whole-config shape is
what every other APR-backed *calendar* function already uses).

### Pattern 3: `ic_engine.py` regime-stratification extension — reuse, don't replicate

**What:** `_build_regime_passes()` (services/ic_engine.py:3101) already returns a
`list[tuple[label_array, distinct_labels, resolved_scope]]` that `_compute_symbol_tf`'s loop
(line ~3513) iterates generically, calling `_compute_one_regime_cell(regime_label, is_pooled,
mask, resolved_scope, X_aligned=..., ...)` once per label. This is a **pure, DB-free function**
with direct unit test coverage (`tests/unit/services/test_ic_engine.py`,
`tests/unit/test_ic_engine_clustering.py`) asserting on `regime_passes` length/scope without a
live DB connection — exactly the kind of surgical extension point D-03's reuse mandate wants.

**Recommended extension (per-symbol path):**
```python
# Pattern, not verbatim code -- see services/ic_engine.py:3101 for the real signature
if earnings_season_conditioned:  # new APR-gated run-level switch, mirrors cluster_regime_conditioned
    distinct_earnings_season = [r for r in set(earnings_season_aligned) if r is not None]
    regime_passes.append((earnings_season_aligned, distinct_earnings_season, "earnings_season"))
```
`earnings_season_aligned` is fetched the SAME way `regime_aligned` (regime_volatility) already
is — add `earnings_season_flag` to the existing `SELECT bar_ts, regime_volatility, {feature_cols}
FROM feature_vectors` (line ~3314), map its 0.0/1.0 values to `"in_season"`/`"off_season"`
string labels for the pass (matching the string-label convention every other regime axis uses).

**Recommended extension (cross-sectional path):** `_compute_one_cross_sectional_cell`
(services/ic_engine.py:3762) is explicitly documented as having **no internal mask step** —
"the caller's chunked fetch scopes to exactly this (tf, regime_label) cell." Do NOT add a
third DB-fetch dimension (group × regime_label × season_state) here — that would multiply the
number of expensive chunked cross-sectional fetches, the exact cost class that produced the
todo 371 OOM. Instead: after a cell's `X_raw`/`returns_mat`/`complete_mat`/`bar_ts` arrays are
already materialized (post-fetch, pre-bootstrap), compute an in-memory boolean mask from the
aligned `earnings_season_flag` values already present in that fetch, and call
`_compute_one_cross_sectional_cell` a **second time** with the row-sliced (not re-fetched)
arrays for each season state. This is strictly cheaper than the primary cell computation (each
season-split call processes a subset of rows already in memory) and reuses 100% of the existing
bootstrap/CI/FDR/walk-forward machinery untouched.

**Explicitly rejected: a new Phase-144-style `regime_group`.** `regime_group` (migration
251+, `alpha.regime.groups` APR config, `_build_symbol_regime_class`) exists to partition the
**universe** into mutually-exclusive peer sets (`breadth_vol` for equity, `curve_credit` for
rates), each with its own fitted cross-sectional regime *signal*. Earnings season is not a
peer-grouping concept — every equity symbol experiences the identical calendar boolean
simultaneously; it doesn't partition symbols into different groups. Building a `regime_group`
for this would be the wrong shape (and touches `_build_symbol_regime_class`'s
`AmbiguousRegimeGroupError`/mutual-exclusivity machinery for no reason), violating D-03's
ruthless-simplicity mandate.

### Anti-Patterns to Avoid

- **Don't cross-multiply `earnings_season` with `regime_volatility`** (3-way vol-regime × 2-way
  season = 6-cell combinatorial cross product) as a SINGLE cell definition. Run them as
  **separate, orthogonal stratification passes** (as `_build_regime_passes` already does for
  `symbol_hmm` alongside the primary cross-sectional pass) — each an independent mask over the
  SAME materialized matrix, not a joint mask. Crossing them multiplies cell count and shrinks
  per-cell N in exactly the direction that produced todo 371's OOM history at universe scale.
- **Don't recompute calendar math inside `ic_engine.py`.** D-03 is explicit and the DAG
  discipline backs it: read `earnings_season_flag` off the persisted `feature_vectors` row,
  exactly how `regime_volatility` is already read, never derive it from `bar_ts` a second time
  in the measurement layer.
- **Don't hand-type the SQL column list.** `feature_vector_persistence.py`'s entire design
  exists to prevent exactly this failure mode (documented in its own module docstring as the
  original bug class). Use the contiguous-slice pattern.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Symbol → regime-group peer-set routing | A parallel calendar-boolean-aware peer-grouping mechanism | Nothing — this phase has no peer-grouping need at all; earnings season is uniform across symbols | `_build_symbol_regime_class` solves a different problem (disjoint peer sets); reusing or extending it for a uniform calendar boolean is solving a problem that doesn't exist here |
| Spearman-rank redundancy detection | A bespoke correlation check outside the pipeline | The existing `parent_features` + partial-IC control (todo 037 methodology) already wired into every tier-1 feature's `concept_gate` evaluation | Same machinery already catches `ret_div_1m_5m`-class redundancy; `days_since_quarter_end`'s measured 0.935 correlation with `quarter_position` is exactly the case this control exists for |
| SQL column-order bookkeeping | A hand-typed INSERT column list | `feature_vector_persistence.py`'s contiguous-slice-from-dataclass pattern | The module's own docstring documents the exact incident (91/152 fields silently unpersisted) a hand-typed list caused before this pattern existed |

**Key insight:** every piece of this phase's mechanics — the tier-1 event-flag registration
shape, the APR-config-threading pattern, the regime-stratification pass mechanism, the
column-order derivation — already exists in this codebase in a form built for exactly this
shape of problem. The engineering work is disciplined reuse across ~14 files, not new design.

## Common Pitfalls

### Pitfall 1: `feature_ic_scores.regime_scope` CHECK constraint blocks a new scope value

**What goes wrong:** `feature_ic_scores.regime_scope` has a hard `CHECK (regime_scope IN
('cross_sectional', 'symbol_hmm', 'pooled'))` constraint (migration 187). Adding
`resolved_scope="earnings_season"` anywhere in the write path will hit a constraint violation
at INSERT time, not a graceful skip.
**Why it happens:** The enum was closed-world at migration 187 and never revisited.
**How to avoid:** Migration 350 (or a follow-up in the same phase) must `ALTER TABLE
feature_ic_scores DROP CONSTRAINT ... ADD CONSTRAINT ... CHECK (regime_scope IN
('cross_sectional', 'symbol_hmm', 'pooled', 'earnings_season'))`, mirroring migration 187's own
`DROP CONSTRAINT IF EXISTS` / `ADD CONSTRAINT` shape.
**Warning signs:** `_write_ic_results` (or equivalent) raising a Postgres CHECK-violation error
the first time an earnings-season cell tries to commit.

### Pitfall 2: Downstream consumers may assume exactly 3 `regime_scope` values

**What goes wrong:** `regime_scope` routing bugs are a LIVE, recently-bitten risk class in this
exact subsystem — commit `b8af2b749` (2026-09-17) fixed a corpus-wide `ic_engine.py`
regime-*group* routing bug (144/273 instruments matching 2+ groups) that blocked the engine
entirely until caught. A new `regime_scope` value silently mis-routed or double-counted by
`ensemble_trainer.py`'s eligibility filter (`WHERE symbol='POOLED' AND is_pooled=true AND
regime != '_pooled'`, STATE.md "Key Decisions") is the same failure class one layer over.
**Why it happens:** Enum-like string columns without an app-level exhaustiveness check are easy
to add a value to without checking every reader.
**How to avoid:** `grep -rn "regime_scope" services/ scripts/` before finalizing the migration;
confirm `ensemble_trainer.py`, `alpha_publisher.py`, and any dashboard/API route that filters
`feature_ic_scores` by scope either explicitly allow-lists `earnings_season` or is provably
scope-agnostic (reads all rows regardless of scope value).
**Warning signs:** Ensemble weighting picking up (or silently dropping) earnings-season cells
in a way that doesn't match the pre-registered design.

### Pitfall 3: `days_since_quarter_end` is measurably correlated with `quarter_position`

**What goes wrong:** Live-computed this session (Python, 2015-2025 daily series, n=4018):
Spearman rho between raw calendar days-since-last-quarter-end and the existing live
`quarter_position` field is **0.935** (Pearson r=0.934). This is NOT the exact -1.0 affine
redundancy that got `days_to_month_end` removed (that was a literal algebraic identity;
`quarter_position`'s 30-day-per-month approximation vs. true calendar-day counting keeps this
one short of exact), but it is high enough that a naive standalone IC test could look
"validated" while carrying near-zero information beyond what `quarter_position` already
provides.
**Why it happens:** Both fields fundamentally encode "how far into the current quarter are we,"
just with different units/approximation.
**How to avoid:** Register `days_since_quarter_end` with `parent_features` including
`quarter_position` (see Pattern 1) so the existing partial-IC control machinery tests
incremental information content, not raw IC alone, before any promotion decision leans on it.
**Warning signs:** `days_since_quarter_end` passing a standalone IC gate with a coefficient/IC
profile that looks like a rescaled `quarter_position`.

### Pitfall 4: `FeatureVector` construction sites will hard-fail until every site is updated together

**What goes wrong:** `FeatureVector` fields have no defaults (confirmed: existing fixtures
explicitly pass `opex_flag=0.0, quad_witching_flag=0.0` as required kwargs). Adding 2 new
fields to the dataclass without updating every construction site in the SAME commit breaks
`compute()`, `compute_batch()`, `_cold_start_vector()`, AND at minimum 2 test fixture files
(`test_feature_vector_writer.py`, `test_backfill_feature_factory.py`) simultaneously at import/
collection time, not at runtime.
**Why it happens:** Python dataclasses without defaults require every keyword at every
construction call.
**How to avoid:** Land the schema change and all 5-6 `feature_factory.py`
construction-site updates plus the 2 test-fixture updates in one atomic commit/task — do not
attempt to land the schema field alone as a separate task waved before the construction-site
updates.
**Warning signs:** `pytest tests/unit/ -x` failing at collection (not test execution) across
multiple unrelated-looking test files the moment the schema field lands.

### Pitfall 5: Corpus DB contention is real and currently active

**What goes wrong:** This research session observed a genuine, in-progress
`decompress_chunk()` operation against a `feature_vectors` chunk (19+ minutes, `WalSync` wait)
with a wave of `autovacuum` workers queued behind it on the same hypertable
(`_timescaledb_internal._hyper_85_*`), at the time this research was conducted (2026-09-22
14:5x UTC). A verification query against `feature_vectors` blocked on a relation lock for 5+
minutes before being cancelled.
**Why it happens:** Consistent with STATE.md's active corpus-pipeline work and the project's
own documented "check contention first" pattern (`feedback_multiple_concurrent_backfills.md`).
**How to avoid:** Before running this phase's eventual backfill/recompute step (or any more
verification queries against `feature_vectors`), check `pg_stat_activity` for active
`decompress_chunk`/`compress_chunk`/long-running corpus jobs first — do not launch a
recompute into contention with whatever operation produced this decompress activity.
**Warning signs:** Queries against `feature_vectors` hanging on `Lock`/`relation` wait events.

## Runtime State Inventory

Not applicable — this is a greenfield feature addition (new columns, new code), not a
rename/refactor/migration of existing state.

## Code Examples

### `concept_registry`/`concept_gate` genesis seed (current-generation pattern, post migration 311)

```sql
-- Source: production/migrations/316_velocity_primitives_extension.sql (adapted pattern)
INSERT INTO concept_registry
    (domain, name, description, status, enabled, group_name, is_control, added_phase, metadata)
VALUES
    ('feature', 'earnings_season_flag',
     '1.0 iff bar_ts falls feature.earnings_season.start_days-feature.earnings_season.end_days '
     'after the most recent calendar quarter end, else 0.0', 'active', true, 'calendar', false,
     '176',
     jsonb_build_object('tier', '1_interaction', 'formula_short',
         'days_since_quarter_end BETWEEN start_days AND end_days',
         'normalization', 'bounded_unsigned', 'linear_ready', false, 'requires_htf', false,
         'apr_namespace', 'feature.earnings_season.',
         'parent_features', jsonb_build_array('quarter_position', 'quarter_cycle_sin'))),
    ('feature', 'days_since_quarter_end',
     'Raw calendar days since the most recent quarter end (Mar 31/Jun 30/Sep 30/Dec 31)',
     'active', true, 'calendar', false, '176',
     jsonb_build_object('tier', '1_interaction', 'formula_short',
         'bar_ts.date() - last_quarter_end.date()',
         'normalization', 'unbounded_unsigned', 'linear_ready', true, 'requires_htf', false,
         'apr_namespace', 'feature.',
         'parent_features', jsonb_build_array('quarter_position', 'quarter_cycle_cos')))
ON CONFLICT (domain, name) DO NOTHING;

INSERT INTO concept_gate
    (concept_id, gate_metric_name, gate_eval_method, min_gate_n, fdr_required, fdr_alpha)
SELECT cr.concept_id, 'ic_sharpe_hac', 'bootstrap_ci', 100, true, 0.05
FROM concept_registry cr
WHERE cr.domain = 'feature'
  AND cr.name IN ('earnings_season_flag', 'days_since_quarter_end')
ON CONFLICT (concept_id) DO NOTHING;
```

### `regime_scope` CHECK constraint widening

```sql
-- Source pattern: production/migrations/187_feature_ic_scores_regime_scope.sql
ALTER TABLE feature_ic_scores DROP CONSTRAINT IF EXISTS feature_ic_scores_regime_scope_chk;
ALTER TABLE feature_ic_scores ADD CONSTRAINT feature_ic_scores_regime_scope_chk
    CHECK (regime_scope IN ('cross_sectional', 'symbol_hmm', 'pooled', 'earnings_season'));
```

### Live-verified redundancy check (reproducible; ran this session, no DB required)

```python
# Verified this session: spearman rho = 0.9349 (n=4018, daily, 2015-01-01..2025-12-31)
import datetime as dt
from scipy.stats import spearmanr

def quarter_position(d):
    month_in_q = (d.month - 1) % 3
    day_in_q = month_in_q * 30 + d.day
    return min(1.0, day_in_q / 91.25)

def days_since_quarter_end(d):
    quarter_ends = [dt.date(y, m, day) for y in (d.year - 1, d.year)
                    for m, day in [(3, 31), (6, 30), (9, 30), (12, 31)]]
    last_qe = max(qe for qe in quarter_ends if qe <= d)
    return (d - last_qe).days
```

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `up_vol_body_diff`'s Spearman IC roughly doubles in earnings season (+0.0197 vs +0.0103, per the todo) | Summary, D-04 | Live re-verification was attempted this session and blocked by an active `decompress_chunk()` operation on `feature_vectors` (19+ min, observed in `pg_stat_activity`) plus queued autovacuum workers — the verification query was cancelled after 5+ min stuck on a relation lock rather than compound the contention. **This number is still unverified** (same status as before this research session). If wrong or overstated, the regime-conditioning workstream's motivating evidence is weaker than believed, though D-01 already locks in building it regardless (user's explicit "build both, don't leave the stronger finding on the table" call) — re-run the query in Code Examples/the original todo's SQL once corpus DB contention clears, ideally as a Wave-0 planning task, before writing any promotion-facing document that cites this number. |
| A2 | Recommended `parent_features` selections (`['quarter_position', 'quarter_cycle_sin']` for the flag, `['quarter_position', 'quarter_cycle_cos']` for the companion) | Pattern 1, Code Examples | `[ASSUMED]` — chosen by analogy to `opex_flag`/`quad_witching_flag`'s parent selection (dow/week/month atomics closest to the event's structure), not independently measured for these two specific fields. The 0.935 correlation with `quarter_position` itself IS measured (A1 is about a different, unrelated number); the choice of `quarter_cycle_sin` vs. `quarter_cycle_cos` vs. some other second parent is a reasonable-but-unverified analogy. Low risk — `parent_features` only affects which columns the partial-IC control conditions on, not correctness of the core measurement. |
| A3 | Exact current line numbers cited throughout (e.g., `feature_factory.py:6244`, `ic_engine.py:3101`) | Architecture Patterns, Site Inventory | These are live-verified as of 2026-09-22 but will drift as other work lands on `main` before this phase executes. Treat as "grep for this function/pattern name," not as literal line-number targets, at implementation time. |

**A1 CORRECTION (2026-09-23, Plan 176-01 Task 3):** Live re-verified against the live corpus,
1d timeframe: in-season IC 0.019647 (n=300,546) vs off-season IC 0.010149 (n=629,965), ratio
1.94x -- closely reproducing the todo's originally reported second-finding numbers
(+0.0197/+0.0103). A1_VERDICT=CONFIRMED. The extended family-wide sweep required by D-01a
(the same 14-42-day window applied to the full 57-feature vol/volume family, BH-FDR corrected
exactly once) found 31/57 features broad and FDR-significant, including `up_vol_body_diff`
itself: SWEEP_VERDICT=CONFIRMED, gating plans 176-04/176-05/176-06 to PROCEED. Full measurement
(both 1d and supporting 1h numbers, the full 57-row table, and the breadth-test methodology):
`176-EVIDENCE-A1.md`.

## Open Questions

1. **(RESOLVED by 176-04)** **Should `earnings_season_conditioned` be a new run-level APR bool, or always-on once the
   column exists?**
   - What we know: `cluster_regime_conditioned` (Phase 151 Plan 02) is the precedent for a
     run-level APR switch gating an additional stratification pass, defaulted `true` at
     seed time (migration 286).
   - What's unclear: whether this phase wants the earnings-season pass to run unconditionally
     once the column is populated (simpler, matches D-01's "ship it, don't half-build it" tone)
     or gated behind a switch for a staged rollout (safer given the OOM history in this exact
     subsystem).
   - Recommendation: default the new APR switch to `true` (unconditional, matching D-01's
     intent) but keep it as a real APR key (not a hardcoded `if True`) so it can be flipped off
     operationally without a code deploy if the cross-sectional in-memory-masking addition
     turns out to add meaningful runtime cost at full universe scale.
   - **Resolution:** 176-04 implements exactly this — a real `alpha.ic.earnings_season_conditioned`
     APR key, seeded `true`, gating the new `_build_regime_passes()` entry without any hardcoded
     conditional.

2. **(RESOLVED by 176-06)** **Cross-sectional in-memory masking: exact insertion point inside `_compute_cross_sectional_tf`'s driver loop (`main()`, ~line 6683)?**
   - What we know: `_compute_one_cross_sectional_cell` has no internal mask step by design (its
     own docstring says so); the caller's chunked fetch already scopes to `(tf, regime_label)`.
   - What's unclear: the exact shape of the caller loop at line ~6683+ (`for regime_label in
     cs_regimes:`) wasn't fully traced in this research session (time-boxed) — specifically
     whether `bar_ts` is retained after materialization in a form easy to re-mask, or whether
     it's discarded once `X_raw`/`returns_mat` are built.
   - Recommendation: planning should read `_compute_cross_sectional_tf`'s full body
     (services/ic_engine.py:4466 onward, and the `main()` driver ~line 6260-7000) as a dedicated
     research/investigation task before writing the cross-sectional-side plan tasks — this
     research established the *shape* of the right answer (mask, don't re-fetch) but not the
     literal diff.
   - **Resolution:** 176-06 traced the exact insertion point during planning and specifies the
     literal diff in its Interfaces block — in-memory row-slicing against the already-materialized
     cell arrays, no second DB fetch.

## Environment Availability

Not applicable — no external tool/service dependencies beyond the already-running PostgreSQL/
TimescaleDB instance (confirmed reachable this session) and the existing Python environment
(`.venv/bin/python3`, confirmed working, includes `scipy`/`numpy`).

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (existing, `tests/unit/`) |
| Config file | existing project pytest config (no new config needed) |
| Quick run command | `.venv/bin/pytest tests/unit/intelligence/test_feature_factory_p7.py tests/unit/services/test_feature_vector_writer_column_mapping.py -x` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements → Test Map

No `.planning/REQUIREMENTS.md` exists in this project (confirmed — file absent); no
requirement IDs were supplied for this phase. Mapping instead to the two workstreams from
CONTEXT.md's Phase Boundary:

| Workstream | Behavior | Test Type | Automated Command | File Exists? |
|------------|----------|-----------|-------------------|-------------|
| Primitive compute | `_earnings_season_flag`/`_days_since_quarter_end` pure-function correctness at window boundaries (day 13/14/42/43, quarter boundaries) | unit | `pytest tests/unit/intelligence/test_feature_factory_p7.py -k earnings_season -x` | ❌ Wave 0 — new tests, mirror `test_opex_flag_third_friday` etc. |
| Persistence column mapping | New fields land at the correct positional SQL param index, no silent shift of existing fields | unit | `pytest tests/unit/services/test_feature_vector_writer_column_mapping.py -x` | ⚠️ Existing file, needs a new/updated test (Pitfall 4) |
| `FeatureVector` construction-site parity | `compute()`/`compute_batch()`/`_cold_start_vector()` all populate the 2 new fields with real (non-placeholder) values | unit/integration | `pytest tests/unit/intelligence/test_feature_factory_batch_parity.py -x` (existing parity-test file, extend) | ⚠️ Existing file, needs extension |
| Regime-pass construction (per-symbol) | `_build_regime_passes()` appends the new `earnings_season` pass correctly, no double-append | unit | `pytest tests/unit/services/test_ic_engine.py -k regime_passes -x` | ⚠️ Existing file, needs a new test mirroring the `symbol_hmm` pass-construction tests |
| `regime_scope` CHECK constraint | New value `'earnings_season'` accepted, old 3 values still enforced | integration | migration-apply test or a direct `psql` smoke check | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** the quick run command above
- **Per wave merge:** full suite green
- **Phase gate:** full suite green before `/gsd:verify-work`; additionally, the real
  `feature_ic_scores` FDR/walk-forward gate pass (not a unit test — a corpus measurement run)
  is the phase's actual completion criterion per CONTEXT.md's Phase Boundary ("this phase ends
  at a real `feature_ic_scores` FDR/walk-forward gate pass, same as any other new primitive")

### Wave 0 Gaps

- [ ] `tests/unit/intelligence/test_feature_factory_p7.py` — new `earnings_season_flag`/
      `days_since_quarter_end` pure-function tests (boundary days, cold-start `bar_ts=None`
      handling)
- [ ] `tests/unit/services/test_feature_vector_writer_column_mapping.py` — new positional-index
      test for the 2 new fields (Pitfall 4)
- [ ] `tests/unit/services/test_ic_engine.py` — new `_build_regime_passes()` test for the
      `earnings_season` pass (mirrors existing `symbol_hmm` pass tests)
- [ ] A smoke check that the widened `regime_scope` CHECK constraint accepts
      `'earnings_season'` and still rejects an arbitrary 5th value

## Security Domain

`security_enforcement` is absent from `.planning/config.json` (= enabled per protocol), but
this phase has no auth/session/network-facing/user-input surface — it is an internal
calendar-math feature addition to an existing batch pipeline, reading `bar_ts` (already-trusted
internal data) and writing to an existing internal table.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No new auth surface |
| V3 Session Management | No | No new session surface |
| V4 Access Control | No | No new access-control surface |
| V5 Input Validation | No (marginal) | `bar_ts` is already-validated internal pipeline data, not external input; the 14/42-day APR values are operator-configured (ConfigService), not user input |
| V6 Cryptography | No | No cryptographic material involved |

### Known Threat Patterns for this stack

None applicable — no new attack surface introduced (no new endpoint, no new external input
parsing, no new secrets).

## Sources

### Primary (HIGH confidence — live code/DB inspection this session)

- `src/intelligence/feature_factory.py` — verified all cited line numbers, `_opex_flag`/
  `_quad_witching_flag`/`_quarter_position`/`_in_ny_session` implementations, `FeatureFactoryConfig`,
  `_cold_start_vector`, `_build_feature_vector`, `compute()`/`compute_batch()` construction sites
- `src/intelligence/schemas.py` — `FeatureVector` dataclass location and current field count
  (298, confirmed via `dataclasses.fields()`)
- `src/intelligence/features/feature_vector_persistence.py` — full contiguous-slice pattern,
  module docstring history, `_ALL_COLUMN_NAMES` derivation
- `services/feature_vector_writer.py` — confirmed delegates to persistence module, no
  hardcoded field names
- `services/ic_engine.py` — `_build_regime_passes`, `_compute_one_regime_cell`,
  `_compute_one_cross_sectional_cell`, `_resolve_regime_scope`, regime_group/`_build_symbol_regime_class`
  architecture, `CellTooLargeError`/OOM history comments
- `production/migrations/290_named_interaction_primitives.sql`,
  `production/migrations/316_velocity_primitives_extension.sql`,
  `production/migrations/187_feature_ic_scores_regime_scope.sql` — exact migration patterns
- `docs/research/signal-temporal-atomic-primitives.md` — full calendar-primitive doctrine
  (tier-0 coordinates vs. tier-1 flags, the `is_opex_day` resolution precedent, the Q1-Q5
  quarterly-seasonality test-design section directly relevant to this phase's own methodology)
- `docs/foundation/glossary.md` `calendar primitive` entry
- `docs/foundation/naming-system.md` §7 and §7a
- `docs/foundation/unified-concept-registry.md` — genesis-seeding exemption
- `.planning/todos/pending/371-ic-engine-cross-sectional-cell-size-guard-post-materialization-ooms-at-universe-scale.md`
  — full OOM incident record informing the cross-sectional integration recommendation
- Live `pg_stat_activity` query (this session) — confirmed active `decompress_chunk()` +
  autovacuum contention on `feature_vectors`
- `tests/unit/services/test_feature_vector_writer_column_mapping.py`,
  `tests/unit/intelligence/test_feature_factory_p7.py`,
  `tests/unit/services/test_ic_engine.py`, `tests/unit/services/test_feature_vector_writer.py`,
  `tests/unit/services/test_backfill_feature_factory.py` — confirmed existing test shapes and
  fixture requirements
- Live Python computation this session (`scipy.stats.spearmanr`) — 0.935 correlation finding

### Secondary (MEDIUM confidence)

- `.planning/todos/pending/353-earnings-season-calendar-primitive-candidate.md` — origin todo's
  proxy-test numbers (superseded by D-04's live re-verification for the primary effect; the
  `up_vol_body_diff` number remains at this confidence tier per Assumption A1, not re-verified)
- STATE.md — commit `b8af2b749` regime-routing bug description (git log/show confirmed the
  commit exists and its message, not independently re-verified against the current code state)

### Tertiary (LOW confidence)

None — every claim in this document is either code-grounded (HIGH) or explicitly flagged in
the Assumptions Log (A1-A3).

## Metadata

**Confidence breakdown:**
- Standard stack: N/A — no external packages
- Architecture: HIGH — every pattern cited is live code in this repo, read and verified this
  session, not inferred from documentation alone
- Pitfalls: HIGH for pitfalls 1-4 (all code/constraint-verified); MEDIUM for pitfall 5
  (point-in-time observation, will have resolved by execution time)
- Evidence base (D-04 numbers): the primary effect is HIGH (independently re-verified in the
  CONTEXT.md discussion session per D-04's own text); the `up_vol_body_diff` second finding is
  LOW (unverified, blocked this session — see A1)

**Research date:** 2026-09-22
**Valid until:** ~14 days for the architecture/code findings (stable unless another phase lands
on `feature_factory.py`/`ic_engine.py`/`schemas.py` first — check `git log` on those 3 files
before executing this phase if more than 2 weeks have passed); the DB-contention observation
(Pitfall 5) is point-in-time only, re-check `pg_stat_activity` at execution time regardless of
elapsed time.
