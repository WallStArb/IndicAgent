# Phase 173: Broadcast Feature Significance Correction - Context

**Gathered:** 2026-08-21
**Status:** Ready for planning

<domain>
## Phase Boundary

`ic_engine.py`'s pooled cross-sectional significance test (`_compute_one_cross_sectional_cell`)
treats every `(bar_ts, symbol)` row as an independent observation. For ~23 broadcast
(symbol-invariant) features — `vix_z`/`yield_slope_z`/`flight_quality` (`CONTEXT_FEATURES`), 15
calendar/session fields, 5 cross-asset fields — this is false: every symbol in the pool carries
the identical value at a given `bar_ts`, so the test overstates effective N by roughly
`n_symbols` and understates p-values on a production `passes_fdr` gate.

This phase delivers: (1) exclusion of all 23 broadcast features from the per-symbol pooled
cross-sectional cell, (2) a new, separate, lightweight broadcast significance cell that reuses
the existing `_subsample_and_rank` kernel against a correctly-constructed market-aggregate
forward-return outcome, computed per `(regime_group, tf, regime_label)` cell exactly like today's
per-symbol cells, and (3) retirement of `_compute_symbol_tf`'s bespoke `CONTEXT_FEATURES`
per-symbol daily-cadence path (which has its own, different bug: 231 redundant per-symbol
significance tests of the literal same time series, entering BH-FDR independently).

Out of scope: any change to the per-symbol cross-sectional cell's own statistical machinery
(`_subsample_and_rank`, walk-forward folds, bootstrap CI) beyond removing the 23 broadcast
columns from its input matrix. Not a re-litigation of regime-group/regime-label definitions.

</domain>

<decisions>
## Implementation Decisions

### Cell scope (broadcast feature population)
- **D-01:** All 23 confirmed-broadcast features move to the new mechanism in this phase — the 3
  `CONTEXT_FEATURES` (`vix_z`/`yield_slope_z`/`flight_quality`) AND the 20 calendar/session/
  cross-asset fields. `_compute_symbol_tf`'s existing bespoke per-symbol daily-cadence block for
  `CONTEXT_FEATURES` is deleted in this phase, not left running alongside the new mechanism —
  one unified broadcast significance path, no lingering second bug in production.
- **D-02:** The confirmed broadcast population (authoritative, from todo 270's scope check) is:
  `dow_sin/cos`, `month_position`, `quarter_position`, `days_to_month_end`,
  `quarter_cycle_sin/cos`, `tdom_sin/cos`, `minute_of_hour_sin/cos`, `hour_of_day_sin/cos`,
  `week_of_month_sin/cos`, `day_of_month_sin/cos`, `week_of_year_sin/cos`, `in_ny_session`,
  `in_london_kz`, `in_overlap`, `power_hour`, `opening_range`, `vix_z`, `yield_slope_z`,
  `flight_quality`, `tip_tlt_ret_z`, `hyg_lqd_ret_z`, `sb_corr_fast`, `sb_corr_slow`, `sb_corr_z`.
  Do not re-derive this list from scratch during research/planning — verify it's still current
  (no Phase 151+ addition missed) with a row-by-row cross-check against `concept_registry`, but
  treat it as the starting authoritative set.

### Aggregate-return construction
- **D-03:** The broadcast significance cell reuses the SAME `(regime_group, tf, regime_label)`
  cell boundary `_compute_cross_sectional_tf`/`_compute_one_cross_sectional_cell` already compute
  today — it does NOT introduce a new global, regime-independent aggregate. This is a deliberate
  choice, not a shortcut: it preserves regime-conditionality (every other measurement in this
  system is regime-stratified; an unconditional broadcast test would be the one inconsistent
  exception) and lets real asset-class heterogeneity show up (e.g., `vix_z` may predict bonds'
  aggregate return differently than equities') rather than collapsing it into one number.
- **D-04:** The outcome variable is an **equal-weighted mean** of `returns_mat` across the
  regime_group's own peer symbols (already fetched for that cell — the same array the per-symbol
  path already has), one value per distinct `bar_ts`. NOT cap-weighted — no market-cap/weighting
  data exists anywhere in this codebase for the ETF/futures/FX universe, and building that
  infrastructure now to satisfy an untested hypothesis about weighting mattering would violate
  "empirical over theoretical." Revisit only if a later measurement shows equal-weighting
  materially misrepresents the aggregate.
- **D-05:** The broadcast cell's feature-value matrix is one row per distinct `bar_ts` (values
  read from any single representative symbol in the cell's `symbol_list`, since they are
  identical across the group by construction) — never touching the OOM-prone per-symbol chunked
  accumulator (`Float32ChunkAccumulator`) for its own construction. `bar_ts` DOES need to be
  threaded through `_compute_cross_sectional_tf`'s chunked fetch (currently dropped per todo
  270's finding #5) since both the broadcast row-collapse and the aggregate-return groupby need
  it — this is real, unavoidable surface area, confirmed already bar_ts-contiguous per todo 270's
  own note (chunks are built from `ts_chunk`, so the groupby-collapse is mechanically clean).
- **D-06:** A cell with too few distinct `bar_ts` values after regime-stratification to clear
  `min_reliable_n` is skipped (same gate every other cell already uses) — this is CORRECT
  behavior for a thin regime/tf slice, not a bug to work around. Expect more skips here than the
  per-symbol path sees, since collapsing to one-row-per-`bar_ts` divides N by roughly
  `n_symbols_in_group`.

### Downstream integration
- **D-07:** Broadcast significance rows land in the SAME `feature_ic_scores` table and the SAME
  BH-FDR family (grouped by `cf_cluster_id`, same as every other feature) — no new table, no new
  parallel measurement system. This deliberately avoids repeating the `feature_registry`/
  `concept_registry` parallel-system mistake (retired Phase 170, migration 311).
- **D-08:** Broadcast-ness is NOT a new column on `feature_ic_scores` itself. It's resolved by
  joining `concept_registry.metadata` (JSONB, `domain='feature'`) at read time — the single
  already-designated source of truth for this classification per the 2026-08-11 decision
  (`concept_annotation` was explicitly rejected as a home; migration 225's own comment: "no gate
  decision may read annotation content"). No migration needed for this — the column already
  exists.
- **D-09:** Broadcast cell rows use the identical shape/sentinel convention today's cross-
  sectional cells already use (`symbol=_CROSS_SECTIONAL_SYMBOL` / `'POOLED'`, `is_pooled=True`,
  `regime=regime_label`) — this is a natural fit, not a special case, since D-03 means broadcast
  rows are computed at exactly the same `(regime_group, tf, regime_label)` granularity as the
  existing POOLED cross-sectional rows they sit alongside.

### Detector for broadcast classification (writing concept_registry.metadata)
- **D-10:** A lightweight variance-based detector (cross-sectional variance ≈ 0 per feature,
  per todo 270's own "far simpler than TagCalibrator's OLS/HAC machinery" framing) writes the
  `concept_registry.metadata` broadcast flag for `domain='feature'` rows. New APR key:
  `alpha.ic.broadcast_variance_threshold`. This is Claude's discretion on exact mechanics
  (oneshot script vs. wired into an existing pass) — not re-litigated here.

### Claude's Discretion
- Exact mechanics of the broadcast-variance detector (oneshot vs. wired into an existing batch
  pass; where it lives in the file tree).
- Whether `_compute_one_broadcast_cell` is a fully separate function or a thin wrapper that calls
  `_compute_one_cross_sectional_cell` with a pre-collapsed input (implementation detail — the
  KERNEL reuse via `_subsample_and_rank` is locked, D-05's "never touch the chunked accumulator"
  constraint is locked, the exact function boundary is not).
- Test coverage shape and unit test organization.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Problem scope and history
- `.planning/todos/pending/270-broadcast-feature-significance-overstates-effective-n.md` — full
  scope history, the confirmed 23-feature broadcast population enumeration and how each was
  verified, the 2026-08-11 original decision, and the 2026-08-21 architecture reconsideration
  this phase's CONTEXT.md is built from. Read in full — this CONTEXT.md summarizes it but does
  not repeat every verification detail.
- `.planning/todos/completed/203-canary-rng-seed-not-per-symbol-cross-sectional-pseudo-replication.md`
  — the original canary-seed fix that surfaced this gap.

### Governance precedent this phase's decisions rely on
- `docs/foundation/unified-concept-registry.md` — `concept_registry.metadata` semantics,
  `domain='feature'` row lifecycle, why `concept_annotation` is not a valid home for gate-relevant
  classification (D-08's basis).
- Migration 311 / Phase 170 retirement of `feature_registry` into `concept_registry` — the
  precedent for "don't build a second parallel system" that governs D-01/D-07's "one unified
  mechanism" calls.

### Code this phase touches
- `services/ic_engine.py`:
  - `CONTEXT_FEATURES` (line ~228) — frozenset to be superseded/removed
  - `_compute_symbol_tf`'s `CONTEXT_FEATURES` per-symbol daily-cadence block (~lines 2790-2870
    per todo 270's citation) — deleted in this phase (D-01)
  - `_compute_cross_sectional_tf` (~line 3409) — needs `bar_ts` threaded through its chunked
    fetch (D-05); needs the 23 broadcast columns excluded from what it hands to
    `_compute_one_cross_sectional_cell`
  - `_compute_one_cross_sectional_cell` (~line 3164) — no structural change to its own matrix
    handling; just stops receiving broadcast columns
  - `_subsample_and_rank` (~line 1933) — the shared kernel, confirmed fully row/column-agnostic
    during this discussion; reused as-is, no changes needed
  - `Float32ChunkAccumulator` (`services/_batch_utils.py`) — the OOM-history accumulator this
    phase's design deliberately does NOT extend/thread broadcast construction through

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_subsample_and_rank` (`services/ic_engine.py:1933`): rank → IC → circular block bootstrap CI
  → walk-forward fold pipeline, confirmed generic over `[n_sub, n_features]` + a matching
  `returns_scale` vector — has zero knowledge of what a "row" represents. This is the exact
  kernel the new broadcast cell reuses; no modification needed to this function.
- `concept_registry.metadata` (JSONB column, already exists, `domain='feature'`) — the intended
  home for the broadcast classification flag (D-08); no migration required.
- `_CROSS_SECTIONAL_SYMBOL` / `'POOLED'` sentinel + `is_pooled` convention — already the exact
  row-shape contract the new broadcast rows will reuse (D-09).

### Established Patterns
- Every existing IC measurement in this codebase is regime-stratified — no precedent anywhere
  for an unconditional/global significance test. D-03's per-cell design follows this pattern
  rather than introducing a new global-aggregate pattern.
- `symbol_list` (regime_group's own peer symbols) is already resolved per-cell by the caller from
  `symbol_regime_class` before `_compute_cross_sectional_tf` is invoked — the aggregate-return
  construction (D-04) reuses this exact peer group, no new symbol-selection logic.

### Integration Points
- `_compute_cross_sectional_tf`'s chunked fetch is the one place `bar_ts` needs to start being
  retained (currently fetched then dropped — todo 270 finding #5). This is the single piece of
  genuinely new plumbing this phase requires; confirmed already bar_ts-contiguous per chunk, so
  the groupby-collapse itself is mechanically clean once threaded through.
- `feature_ic_scores`'s existing BH-FDR grouping by `cf_cluster_id` needs no change (D-07) — the
  23 broadcast features simply start producing correctly-computed rows into the same population.

</code_context>

<specifics>
## Specific Ideas

No UI/visual specifics — this is a backend measurement-correctness fix with no operator-facing
surface beyond `feature_ic_scores`/`concept_registry` rows already read by existing dashboards
and `ensemble_trainer`'s eligibility gate (both continue to work unmodified per D-07/D-09).

The user explicitly directed this phase's design to be reasoned through under "Renaissance
Technologies / Jim Simons council of senior engineers" rigor rather than accepting a
first-pass answer at face value — D-03/D-04/D-07/D-08 above are the product of that
stress-testing (each records the rejected alternative and why), not just a preference pick.

</specifics>

<deferred>
## Deferred Ideas

### Reviewed Todos (not folded)
The todo-matcher tool returned ~104 near-universal keyword matches for this phase (clearly noise
— every match scored via generic "2026"/common-term overlap, no real semantic relevance). Skipped
mechanical review of all 104. Manually reviewed the handful whose titles suggested real overlap;
none folded — each is its own independent concern, not this phase's scope:
- `038-cross-sectional-collinearity-diagnostic.md` — PCA/eigenvector variance-concentration
  diagnostic, unrelated statistical question.
- `039-tag-stratified-ic-population-check.md` — population-count check for a different
  (tag-stratified) cross-sectional IC path.
- `135-cross-sectional-regime-grid-shape-never-validated.md` — validates the regime GRID SHAPE
  (cut-points/cell count), not the significance test's independence assumption.
- `186-ic-math-cross-sectional-block-bootstrap-gap.md` — a different combiner script
  (`nonlinear_interaction_combiner`)'s ad hoc bootstrap approximation, not `ic_engine.py`.
- `214-ic-engine-ensemble-ic-engine-shared-compute-refactor.md` — a much larger, separately-scoped
  duplication-elimination refactor between `ic_engine.py`/`ensemble_ic_engine.py`.
- `227-ic-engine-adaptive-bootstrap-resample-early-stop.md` — orthogonal early-stop optimization
  for the bootstrap resample loop, applies equally to both old and new cells, not a blocker either
  way.

[No other deferred ideas — discussion stayed within phase scope.]

</deferred>

---

*Phase: 173-Broadcast Feature Significance Correction*
*Context gathered: 2026-08-21*
