# Phase 144: Cross-Sectional Regime Model (`regime_group`) - Context

**Gathered:** 2026-07-12
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace `market_regimes.asset_class` with `regime_group` — a named peer group with a pluggable
cross-sectional regime signal (`breadth_vol` for equity, `curve_credit` for rates; `commodity_*`
and `fx` signal modules built but shipped disabled). Fixes a confirmed live bug: non-equity
corpus symbols (`fi_*` bonds, GLD/SLV/VNQ, IBIT) currently get a contaminated equity regime
label because no real symbol→group routing exists yet. This phase builds that routing, plus the
generic dispatcher and rates signal module, and unblocks a clean TLT-vs-rates separation
comparison for the first time.

**This phase's deliverable is the mechanism only** — migration + signal modules + dispatcher +
`ic_engine.py` routing (plan doc Tasks 0-9). It does not include HMM-internals hardening
(already shipped elsewhere, see Decisions) or query-time tag-stratified IC filtering (explicitly
sequenced after, see Deferred).

</domain>

<decisions>
## Implementation Decisions

### Scope: mechanism only, nothing to bundle
- **D-01:** Phase 144 ships exactly `docs/plans/2026-07-01-cross-sectional-regime-model.md`'s
  Tasks 0-9: migration 189-equivalent (renumber to next free migration — corpus is at 228 as of
  2026-07-12, plan doc's literal "189" is stale), `src/intelligence/regime_signals/` (breadth_vol
  + curve_credit; commodity/fx modules ship present but `enabled: false`),
  `services/cross_sectional_regime_model.py` dispatcher, `services/ic_engine.py` routing
  (`_build_symbol_regime_class`, `AmbiguousRegimeGroupError`, per-group `mr_dicts_by_group`).
- **D-02 [informational]:** Todo 026 P2b (degenerate-model occupation-fraction gate) and P2c
  (`hmm_churn` column) were investigated as candidates to bundle in (ROADMAP's v3.15 intro
  batches them with this phase) — **verified already shipped 2026-07-06 via Phase 143 Plan 01
  (LIFECYCLE-00)**: `feature_vectors.hmm_churn` column live (migration 201),
  `feature.hmm.min_state_occupation` and `feature.hmm.churn_window` APR keys live (migration
  200), `_compute_hmm_churn()` in `regime_writer.py:347`. Nothing to bundle — no plan task
  should reference this as work to do. Corrected the stale "NOT DONE" status in
  `.planning/todos/deferred/026-hmm-regime-audit-optimization.md` and the stale ROADMAP.md
  v3.15 batching paragraph during this discussion (both said P2b/P2c were still open).
- **D-03 [informational]:** Todo 026's remaining item (P3, empirical vix/breadth threshold
  calibration) is already split into standalone
  `.planning/todos/pending/092-equity-regime-model-threshold-calibration.md` — stays separate,
  not folded into this phase's plan. No plan task should reference this as work to do.
- **D-04 [informational]:** Todo 041 (tag exposure-vs-sensitivity taxonomy audit) gates
  commodity/fx group *enablement* only (those groups ship `enabled: false` regardless) — does
  not block or need to be folded into this phase's plan. No plan task should reference this as
  work to do (Plan 03's objective note citing it as context is fine; it is not a task deliverable).

### Acceptance gate: this phase includes the empirical re-measurement
- **D-05:** Phase 144 is not "done" at code-complete. Its own verification includes running the
  widened Step 1 protocol from `docs/research/fable-2026-07-07-phase144-conditioning-decision.md`
  §6 Input 1: per-symbol TLT vs. the new `rates` cross-sectional group (not the old contaminated
  equity comparison), one representative per enabled `regime_group`, todo 026's existing bands
  (gap < 0.01 deficient, 0.01-0.05 ambiguous). This is the pre-committed falsifier check (F1/F2
  in that doc) that decides whether per-symbol HMM stays demoted-to-shadow for `rates` (already
  the default live behavior via routing) or the factor-augmented HMM challenger (option c) gets
  triggered. Rationale: "earn promotion through proof" — a regime label nobody re-measured isn't
  proven, it's deployed.
- **D-06:** This re-measurement step is necessarily sequenced after the corpus re-run (see D-07)
  — it cannot run against stale data. Plan-phase should scope it as this phase's final
  verification task, not as a separate follow-up todo.

### Sequencing relative to the in-flight 143.1-07 corpus rebuild
- **D-07:** Code, migration, dispatcher, and `ic_engine.py` routing work can be planned and
  executed now — none of it touches the in-flight `143.1-07` corpus rebuild (confirmed still
  running as of 2026-07-12, per `feature_ic_scores` corpus-wide BH-FDR write not yet landed).
  Defer running `cross_sectional_regime_model.py` full-run and the batched `ic_engine` re-run
  (and therefore D-05's Step 1 gate) until 143.1-07 completes and is verified clean — single-
  writer discipline on derived tables, per the Fable decision doc's own sequencing note.
- **D-08:** No code changes needed to check 143.1-07's status at execute-phase time — check
  `feature_ic_scores` row freshness / the corpus pipeline state memory before running the
  measurement step.

### Claude's Discretion
- Exact migration number (whatever is next free — plan doc's literal "189" is stale).
- Whether to keep `equity_regime_model.py` as a deprecated rollback fallback (plan doc's Task 1
  says yes, no functional changes) — follow the plan doc unless a reason emerges not to.
- Commodity/fx signal modules (`commodity_momentum_ts.py`, `fx_dollar_carry.py`) ship as part of
  this phase per the plan doc's File Map even though their groups stay `enabled: false` — build
  them now (cheap, already spec'd with tests) rather than defer, since todo 041 only gates
  *enablement*, not module existence.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Implementation plan (primary source — read first)
- `docs/plans/2026-07-01-cross-sectional-regime-model.md` — the full task-by-task implementation
  plan (migration SQL, signal module code, dispatcher code, ic_engine.py diffs, tests) that this
  phase executes. Treat as authoritative for HOW; this CONTEXT.md only adds scope/gate/sequencing
  decisions on top of it. Note: literal migration number "189" and any line numbers referencing
  `ic_engine.py` are stale (file has moved since 2026-07-01) — verify against live file before
  applying line-anchored edits.

### Operator decision this phase depends on
- `docs/research/fable-2026-07-07-phase144-conditioning-decision.md` — the pre-committed
  fallback mechanism (demote weak-separation HMM to shadow per `regime_group`) and its
  falsifiers (F1-F5). §6 lists the three planning inputs this phase must carry — Input 1 is D-05
  above; Input 3 (concept_registry row-grain question) is explicitly deferred, see Deferred
  section below.

### Roadmap and milestone context
- `.planning/ROADMAP.md` — "v3.15 Conditioning & Identity Foundation" section (Phases 144, 145)
  and the "### Phase 144" subsection for the already-made routing decisions (unrouted-symbol
  policy, crypto-into-fx, commodity/fx enablement blocker).
- `docs/research/stratification-dimension-unification.md` — broader `StratificationDimension` governance
  vision this phase is a concrete instance of; §Governance line on per-`regime_group` promotion
  state; line 452 confirms P2b/P2c shipped (used to verify D-02).

### Related, explicitly out of scope for this phase
- `.planning/todos/deferred/026-hmm-regime-audit-optimization.md` — HMM audit findings; status
  table corrected this session (P2b/P2c → DONE).
- `.planning/todos/pending/092-equity-regime-model-threshold-calibration.md` — todo 026 P3,
  separate.
- `.planning/todos/deferred/041-tag-vocabulary-category-audit.md` — gates commodity/fx
  enablement only.
- `.planning/todos/pending/039-tag-stratified-ic-population-check.md` — explicitly blocked ON
  this phase shipping first (query-time tag filter within a `regime_group`); do not build ahead
  of it being needed.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `services/_batch_utils.py::load_config_service_sync` — APR config loading, already used by the
  plan doc's dispatcher.
- `src/observability/metrics.py::JOB_COMPLETED_TOTAL` + `flush_and_shutdown_metrics` — D-06
  oneshot contract, already wired into the plan doc's `main()`.
- `services/equity_regime_model.py` — logic source for `breadth_vol.py`'s extraction (plan doc
  Task 2); stays live as deprecated rollback fallback, no functional changes.

### Established Patterns
- APR namespace convention: `alpha.regime.groups` (JSON array of group configs) +
  `alpha.{group_name}_regime.*` (per-group signal thresholds) — matches existing `alpha.*`
  conventions.
- `AmbiguousRegimeGroupError` fail-loud pattern for config authoring errors (tag_filter overlap)
  — consistent with project mandate "silent wrong answers are worse than loud crashes."

### Integration Points
- `services/ic_engine.py` — 6 touch points enumerated in plan doc Task 5 (constants block,
  `_assert_prerequisites`, `_load_apr`, `mr_dict` loading, worker args, `_compute_cross_sectional_tf`,
  cross-sectional pass loop). Verify exact line numbers against current file — plan doc's are
  from 2026-07-01 and `ic_engine.py` has changed significantly since (Phase 143's lifecycle hook,
  143.1's Fisher-z/e-value/sign-symmetry work all touch this file).
- Live schema confirmed 2026-07-12: `market_regimes.asset_class` still exists (migration not yet
  applied) — plan doc's Task 1 is still valid to execute as-is.
- `instrument_tags` live tag data confirmed 2026-07-12: OIH/XLE carry both `eq_*` and
  `commodity_energy_crude` tags (won't collide today since commodity_energy ships disabled, but
  confirms todo 041's concern is real for whenever it's enabled); VNQ has no tag matching any
  group's filter (stays unrouted — expected, real-estate hybrid-sensitivity is explicitly the
  plan doc's deferred "second job," not this phase's).

</code_context>

<specifics>
## Specific Ideas

No specific UI/UX asks — this is a backend batch-pipeline phase. User's steering input during
discussion was a general instruction to apply Renaissance/Simons-style rigor (reusable
microservices, strong institutional foundation, minimize redundant work) rather than a specific
implementation preference — applied directly to the scope question (D-02: verify before bundling,
found nothing to bundle) rather than captured as a standalone decision.

</specifics>

<deferred>
## Deferred Ideas

- **concept_registry row-grain question** (Fable decision doc §6 Input 3) — whether `regime_model`
  domain status should live as one row per (dimension, regime_group) vs. global status + per-
  stratum deployment as a fact elsewhere. Explicitly noted in
  `docs/research/fable-2026-07-04-concept-registry-cluster-review.md` F2 as something that "can
  wait for v3.15 planning." Not resolved here — `concept_registry` itself does not exist yet
  (confirmed via `\dt`, no such table live as of 2026-07-12); it's scoped to a future
  `concept_registry` MVP seeding todo (todo 058 covers `ensemble_strategy` as domain #1;
  `regime_model` would be a later domain). Revisit when that MVP work is actually scheduled, not
  as part of this phase's code.

### Reviewed Todos (not folded)
- **Todo 026 P2b/P2c** — reviewed, found already shipped elsewhere (Phase 143), not applicable
  to fold in. See D-02.
- **Todo 026 P3 / Todo 092** — reviewed, correctly sequenced as a separate standalone todo, not
  folded in. See D-03.
- **Todo 041** — reviewed, gates commodity/fx *enablement* only, does not block or need folding
  into this phase. See D-04.
- **Todo 039** (tag-stratified IC population check) — reviewed, explicitly designed as a
  follow-on that requires `regime_group` to exist first; correctly deferred to after this phase,
  not before or during it.
- **Todo 038** (cross-sectional collinearity diagnostic) — reviewed, tangentially related
  (cross-sectional correlation structure) but scoped to HMM input diagnostics, not regime
  routing; not folded in.

</deferred>

---

*Phase: 144-Cross-Sectional Regime Model (`regime_group`)*
*Context gathered: 2026-07-12*
