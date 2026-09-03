# Phase 171: HMM Walk-Forward Regime Labeling (Parameter-Lookahead Fix) - Context

**Gathered:** 2026-08-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the already-built `_walk_forward_hmm_labels()` (`services/regime_writer.py`, implemented +
TDD-tested via todo 248) into the live labeling path, replacing `_compute_symbol_tf`'s
full-history HMM parameter fit — the one producer in the codebase that doesn't enforce "a fact
computed at bar t may only use data ≤ t." This ships regardless of the Gate 4 ordinal-IC pilot's
negative result (decision corrected 2026-08-04) — it is a confirmed causal-law violation in an
existing core mechanism, not a new/unproven signal subject to this project's "prove before
promoting" discipline.

**Sequencing:** rides in the same corpus-recompute pass as Phase 151 waves 6-7 (feature primitives
corpus recompute + interaction IC sweep), once todo 259's client-43 universe-expansion backfill
completes. Both require the same full regime + `ic_engine` recompute — bundling avoids paying for
two full `ic_engine` passes over the 231-symbol universe.

</domain>

<decisions>
## Implementation Decisions

### Governing principle for this phase (locked, applies to every implementation choice below)
- **D-00:** Design and execute this phase the way a council of senior engineers/quants at
  Renaissance Technologies would — the standard already stated in this project's own
  `CLAUDE.md` Design mindset section, explicitly reinforced by the user for this phase given its
  blast radius (full regime + `ic_engine` recompute). Concretely: ruthlessly eliminate
  unnecessary complexity — no special-case bandaids layered on `regime_writer.py`'s shared
  infrastructure where a structural fix is warranted; data integrity is paramount — guard
  against hidden bias or silent edge-case failures at every step (this is exactly what surfaced
  todo 229's structurally-unreachable retry logic); prioritize clean data flow and SoC —
  compute ≠ persistence ≠ transport; DAG topology stays acyclic, one direction; empirical
  verification over verification-by-inspection — every claim in this phase (cap headroom,
  multi-seed benefit, 1d calibration) gets measured, not assumed; component reuse over
  duplication — `_walk_forward_hmm_labels`/`_seed_prior_from_label`/`_hmm_seed_stability_check`
  already exist and are tested, this phase wires them in, it does not rebuild them.

### Rollout staging: staged pilot, then full corpus refit
- **D-01:** Flip `alpha.hmm.walk_forward.enabled` for a staged pilot (5-10 symbols spanning a mix
  of bar-density/liquidity profiles, not a convenience sample) with an explicit go/no-go gate,
  BEFORE committing the full 231-symbol × 4-tf universe. Matches this project's own repeated
  precedent (Phase 168 D-02's parallel-construction-never-mutate-baseline pattern; Phase 166
  D-03's "evaluate empirically, don't adopt by inspection"). The pilot is also where
  `_hmm_seed_stability_check` (built + unit-tested in todo 248, never yet exercised against real
  corpus data) gets its first live run — it must not stay invoked-nowhere per the phase's own
  requirement 5. Rejected alternative: flip-and-refit-everything in one shot — simpler, but
  skips the one cheap check that catches a degenerate symbol/tf combination before the full
  231-symbol blast radius is sunk.
- **Go/no-go gate criteria for the pilot: Claude's discretion at planning time** — should draw on
  the same measurement machinery already proven in todo 248's Gate 4 pilot
  (`_nonlinear_interaction_combiner_shared.py`'s bootstrap CI helpers) and the seed-stability
  check's own pass/fail semantics, not a new ad hoc metric.

### 1d timeframe calibration: derive via density-scaling, disclosed as an estimate
- **D-02:** `refit_every_bars`/`initial_warmup_bars` for `tf=1d` are derived using the same
  "~1 trading year refit, ~2 year warmup" heuristic already used for 5m/15m, scaled by 1d's own
  bar density (~252 bars/year, per the phase's own requirement 1 note) rather than pilot-measured
  directly. Explicitly disclosed in the resulting migration/APR key description as
  `[initial_estimate]`, not `[rca_analysis]` — matches this project's "disclose limitations,
  don't gate on them" precedent (Phase 166 D-05) rather than blocking the whole rollout on a
  dedicated 1d pilot (which would need ~20yr of history per symbol to say anything meaningful).
  Rejected: running a dedicated 1d pilot first (more rigorous, matches how 1h/15m actually got
  their real numbers, but adds a full measurement pass before this phase can close — 1d already
  has known-weak statistical power in this corpus per todo 166's ~32x-fewer-effective-N finding,
  so the marginal rigor gain is smaller than for 1h/15m). Also rejected: excluding 1d from this
  rollout entirely — every other tf already has a walk-forward path, leaving 1d on the biased
  full-history fit indefinitely is itself a data-integrity gap under D-00's governing principle.

### Multi-seed HMM restart (todo 108): tested now, as a parallel comparison arm
- **D-03:** Test `alpha.hmm.n_restarts > 1` empirically in this same corpus-recompute pass,
  NOT deferred to a separate pass — real compute budget is already committed to a full refit.
  **Attribution safeguard (resolves the two-variables-move-at-once risk):** run `n_restarts=1`
  and `n_restarts>1` as two separate parallel comparison arms during the pilot (D-01), not a
  blind switch of the default — directly reusing this project's own Phase 168 D-02
  parallel-construction-never-mutate-baseline pattern. The pilot's go/no-go gate must be able to
  independently attribute any observed behavior change to walk-forward labeling vs.
  multi-seed-restart, not conflate them. If the full-corpus rollout proceeds, `alpha.hmm.n_restarts`
  is set based on what the pilot's parallel-arm comparison actually shows, not assumed.

### Folded Todos
- **Todo 229** (HMM retry logic structurally unreachable) — **ALREADY FIXED**, not open
  implementation work. `monitor_.converged`'s always-True bug (hmmlearn 0.3.3) was corrected to
  `monitor_.iter < monitor_.n_iter` in commit `ba8a74ef` (2026-08-05), live in both
  `_compute_symbol_tf` (the current live path) and the walk-forward path this phase wires in.
  The pending todo file was never moved to `completed/` and `PRIORITIES.md` still describes it
  as "deliberately deferred" — both stale. **This phase's execution must**: (a) move
  `229-regime-writer-hmm-retry-logic-structurally-unreachable.md` to `completed/` with a closing
  note citing `ba8a74ef`, (b) correct `PRIORITIES.md`'s stale entry, (c) treat this rerun as the
  blast-radius verification the fix's own commit message explicitly deferred to "the next
  scheduled corpus rebuild" — confirm via the `iters_used` data (D-04 below) that the
  now-functional retry path behaves as expected at full scale, not just the 15-cell sample.
- **Todo 226** (n_iter=200 cap headroom) — instrumentation already wired (`model.monitor_.iter`
  logged per (symbol, tf) cell, commits `5c86ffeb`/`7a0d7de1`). This full-corpus rerun IS the
  "real full-corpus measurement (all symbols × all tfs)" the todo's own text says is required
  before any cap change. **D-04:** Collect the data as a side effect of this phase's refit;
  do NOT change `alpha.hmm.n_iter` in this phase — that's an explicitly separate follow-on
  decision once the full-scale distribution is in hand, per the todo's own "don't change n_iter
  blind" rule. This phase reads the data, a later todo acts on it.
- **Todo 108** (multi-seed HMM restart) — folded per D-03 above.
- **Todo 167** (equity cross-sectional-vs-symbol-HMM falsifier) — different regime system
  (cross-sectional `market_regimes`, not this phase's per-symbol HMM) but consumes the same
  downstream `ic_engine` pass this phase's Requirement 4 triggers. **Verification task, not new
  implementation:** once this phase's `ic_engine` recompute lands, check whether it already
  covers the 49 equity symbols todo 167 needs (its own falsifier gate script,
  `scripts/analysis/equity_regime_separation_gate.py`, already exists and is verified) before
  assuming a second scoped run is required.

### Claude's Discretion
- Exact pilot symbol selection (which 5-10 symbols span bar-density/liquidity profiles) —
  planner/executor should draw candidates from across the tf-calibration density buckets
  (1h/15m/5m/1d) rather than picking arbitrarily.
- Exact go/no-go gate statistical thresholds for the pilot (D-01) — reuse existing bootstrap CI
  machinery, calibrate specific thresholds at planning time.
- Whether the `iters_used`/cap-headroom data (D-04) gets its own summary report or is folded
  into this phase's own completion notes — a documentation-shape choice, not a design decision.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and requirements
- `.planning/ROADMAP.md` §"Phase 171: HMM Walk-Forward Regime Labeling (Parameter-Lookahead Fix)"
  — the 5 locked requirements this phase must satisfy
- `.planning/STATE.md` — Strategic Plan section (fork resolution, 2026-08-07) establishes why
  this phase's only remaining blocker (CTF/Phase 167 sequencing) has cleared

### The mechanism being wired in (already implemented, this phase activates it)
- `services/regime_writer.py` — `_walk_forward_hmm_labels()`, `_seed_prior_from_label()`,
  `_hmm_seed_stability_check()`, `_compute_symbol_tf_walk_forward()`, `_walk_forward_hmm_full()`,
  `_compute_symbol_tf()` (the live path being replaced), the `monitor_.iter < monitor_.n_iter`
  convergence-check fix (todo 229, commit `ba8a74ef`)
- `tests/unit/services/test_regime_writer.py` — existing coverage for all of the above

### Folded todos (full detail, not duplicated above)
- `.planning/todos/pending/229-regime-writer-hmm-retry-logic-structurally-unreachable.md`
- `.planning/todos/pending/226-regime-writer-n-iter-convergence-headroom-check.md`
- `.planning/todos/pending/108-hmm-multi-seed-restart-best-likelihood.md`
- `.planning/todos/pending/167-equity-cross-sectional-vs-symbol-hmm-never-falsifier-tested.md`
- `.planning/todos/pending/248-hmm-full-history-fit-regime-label-instability-gate4-pilot.md` —
  the original todo this phase implements

### Precedent patterns this phase's decisions reuse
- `.planning/milestones/v3.1-phases/168-cost-hurdle-adjusted-spread-construction-follow-on/168-CONTEXT.md` D-02
  — parallel-construction-never-mutate-baseline pattern (informs D-01, D-03)
- `.planning/milestones/v3.1-phases/166-frame-execution-recalibration/166-CONTEXT.md` D-03/D-05 — empirical
  comparison over a priori choice; disclose coverage limitations rather than gate on them
  (informs D-01, D-02)
- `.planning/milestones/v3.1-phases/167-cross-sectional-trade-construction/167-CONTEXT.md` D-03 — don't conflate
  two unproven changes in the same pass (the tension D-03 above explicitly resolves)

### APR / infrastructure conventions
- `docs/foundation/adaptive-parameter-registry.md` — APR pattern this phase's flag
  (`alpha.hmm.walk_forward.enabled`, migration 292) and new `alpha.hmm.n_restarts`/tf-calibration
  keys must follow
- `CLAUDE.md` — Design mindset section (the standard D-00 explicitly invokes)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_walk_forward_hmm_labels()` / `_seed_prior_from_label()` / `_hmm_seed_stability_check()` /
  `_compute_symbol_tf_walk_forward()` / `_walk_forward_hmm_full()` — all already implemented and
  unit-tested in `services/regime_writer.py`. This phase's job is wiring/dispatch/rollout, not
  building new HMM mechanics.
- The `alpha.hmm.walk_forward.enabled` APR dispatch flag already exists in `_run_symbol_worker`/
  `main()` (migration 292, seeded `false`) — the on/off switch this phase's rollout flips.

### Established Patterns
- Corrected HMM convergence check (`model.monitor_.iter < model.monitor_.n_iter` instead of
  hmmlearn 0.3.3's always-True `monitor_.converged`) is already the standard in this file as of
  commit `ba8a74ef` — any new code touching HMM fit/retry logic in this phase must use this
  pattern, never the old `monitor_.converged` check.
- APR-flagged rollout (flag seeded `false`, flip deliberately, never a silent swap) is this
  project's established pattern for blast-radius-class changes (matches `HMM_RANDOM_STATE`
  precedent per `CLAUDE.md`).

### Integration Points
- Downstream `ic_engine`/`feature_ic_scores` — regime is the stratification key; any change to
  `feature_vectors.regime` requires a full re-run of `ic_engine` (this phase's Requirement 4).
- `services/ic_engine.py`'s per-feature regime-stratified IC path (not the standalone ordinal-IC
  test Gate 4 used) is how `feature_vectors.regime` actually gets consumed in production —
  planner should be aware Gate 4's negative result was on a stricter, different test than what's
  live downstream.

</code_context>

<specifics>
## Specific Ideas

No specific UI/behavior references beyond what's captured in Decisions above — this is a
backend/batch-compute phase with no user-facing surface.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope. All 4 candidate todos surfaced by
`todo.match-phase` with genuine domain overlap (229/226/108/167) were folded in; the remaining
60 matches were keyword-noise (generic "2026"/"todo"/"phase" overlaps against nearly the entire
pending backlog) and correctly excluded without individual review.

</deferred>

---

*Phase: 171-hmm-walk-forward-regime-labeling-parameter-lookahead-fix*
*Context gathered: 2026-08-07*
