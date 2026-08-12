# Phase 148: Alpha Scoring System - Context

**Gathered:** 2026-07-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the scoring system and run the two independent OOS proof gates that answer whether
the v3.0 AlphaEngine has real, provable alpha: **Gate 1 (signal proof)** — does `alpha_score`
predict forward returns out-of-sample? — and **Gate 2 (execution proof)** — does the frame
simulation capture that signal as real P&L out-of-sample? No live execution; that is v4.0.
This is the actual "does the system work" milestone the whole measurement pipeline
(Feature Factory → IC engine → ensemble → alpha_frames/CounterfactualTracker) exists to
produce a verdict for.

**Not in scope:** Phase 147 (I7 CORPUS-07 evaluation) — confirmed during this discussion to
have zero real dependency link to this phase (see Decisions below). Live execution / v4.0.
v2.x physical decommission (archiving `src/intelligence/` I1-I7, disabling the failed
systemd unit) — tracked separately in todo 056, decoupled from this phase's proof gates per
the 2026-07-19 operator call.

</domain>

<decisions>
## Implementation Decisions

### Phase 147 dependency (corrected during this discussion)

- **D-01 [informational]:** ROADMAP.md's "Depends on: Phase 147 complete" line on this phase was stale and
  has been corrected (commit `4ef1b71a`). SCORE-01/02/03 read only `alpha_frames`/
  `alpha_ensemble_ic`/`alpha_strategy_scores` — pure v3.0 tables, zero I7 lineage. This phase
  is unblocked today, independent of Phase 147.

### Gate 1 (signal proof) — priority and build approach

- **D-02:** Gate 1 must be built and run **before** Gate 2's formal evaluation, not after or
  in parallel. Rationale: Gate 1's OOS data (`alpha_ensemble_ic`) is genuinely untested —
  live-verified 2026-07-22 that the table has exactly one run (2026-07-19, in-sample only;
  `EnsembleICEngine` currently only ever filters `bar_ts < oos_start`, never scores the OOS
  side). It is the foundational question ("is there real signal at all") and answering it
  first, cleanly, before Gate 2's already-complicated picture gets folded in, keeps the two
  questions from being conflated into one gut feeling.
- **D-03:** The OOS Gate 1 scorer is a **standalone one-shot script**, not a new mode bolted
  onto the production `EnsembleICEngine` service. Reuse `EnsembleICEngine`'s pure IC helper
  functions (BH-FDR, bootstrap CI, Fisher-z, walk-forward stability) — same reuse pattern
  the existing interim diagnostic scorer (`scripts/ops/corpus/ops_oos_holdout_eval.py`)
  already uses, but promoted from "diagnostic only, never a gate" to "authoritative, one-shot".
  Reason for standalone over extending the service: `alpha_ensemble_ic`'s schema (checked
  2026-07-22) has **no column distinguishing in-sample vs. OOS-scored rows** — writing OOS
  results into that shared table would create two indistinguishable row populations, a real
  silent-ambiguity risk for any future consumer. The scorer's verdict + evidence JSON is
  written to `gate_evaluations` (per SCORE-02's existing spec), not to `alpha_ensemble_ic`.
- **D-04:** Per `OOS-EVAL-PROTOCOL.md`'s frozen cadence rule, this scorer runs **at most once**
  for this milestone gate. Do not re-run "to check if it passes now" after any tweak.

### Gate 2 (execution proof) — OOS data provenance and reporting

- **D-05:** Gate 2's OOS window (`alpha_frames`/`counterfactual_pnl_r`, `bar_ts >= oos_start`)
  has already been examined twice this week (143.1-08's champion/challenger validation, and
  todo 165's regime-stratified re-evaluation of the same data) — for the E1-vs-E2 ensemble
  weighting decision, not for this promotion gate directly. Neither look changed the champion
  (E2 lost; E1's weights are unchanged). **Decision: disclose, don't re-derive theatrically,
  and don't shift the OOS window to dodge it** — shifting the window specifically because the
  visible result is unfavorable would itself be the post-hoc renegotiation
  `SHADOW-REVIEW.md` explicitly bans, just applied to the window boundary instead of a
  numeric threshold.
- **D-06:** SCORE-03 formally **adopts the champion's already-computed 143.1-08 numbers**
  for the pooled Gate 2 evaluation rather than re-running an equivalent computation from
  scratch and pretending it's a fresh look. Cite the provenance (143.1-08-SHADOW-VALIDATION.md
  section 6) and the no-tuning-occurred argument explicitly in the promotion decision record.
  **Known going in: on this data, the champion's pooled numbers already fail 3 of 5
  SHADOW-REVIEW criteria** (`c2_ci_lower=-0.121` fails >0; `c3_sharpe=0.385` fails >0.5;
  `c4_max_dd=9.6` fails <0.25 ratio) — this is disclosed up front, not discovered as a
  surprise during planning/execution.
- **D-07:** **The pooled verdict must never stand alone as "the" Gate 2 verdict.** It must be
  paired with a regime-stratified breakdown of the same champion data, reusing the exact
  machinery todo 165 already built and reviewed for this purpose:
  `evaluate_frame_gate(rows, ..., group_key=lambda row: (row["direction"], row["regime"]),
  min_clusters=...)` in `services/counterfactual_tracker.py`. Rationale: todo 165 proved,
  this week, on this exact data, that a pooled single-fixed-window verdict is structurally
  blind to regime-conditional edge (shorts profited in the COVID crash, were breakeven
  through the 2022 bear market, lost money specifically in the one rally window tested).
  Reporting Gate 2 as a flat pooled FAIL without the regime-stratified companion breakdown
  would repeat a known, just-diagnosed blindness one phase later. The promotion decision
  record must show both numbers and explain what the regime breakdown reveals about *why*
  the pooled number failed, not just that it failed.
- **D-08:** `FRAME-04` (Phase 142B's own frame-quality gate, referenced elsewhere as needing
  a "re-run against the post-143.1 corpus") and `SCORE-03` are **the same gate**, not two
  sequential steps. `SHADOW-REVIEW.md` (the frozen 5-criteria doc SCORE-03 cites) is titled
  "Phase 147 Live Promotion Criteria" — a numbering fossil predating the roadmap's
  renumbering. Do not plan a separate "re-run FRAME-04 first" task; it collapses into
  SCORE-03's own work.

### Claude's Discretion

- Exact structure of the promotion decision record document (location, format) — planner's
  call, following this project's existing doc conventions (likely `docs/plans/` or the phase
  directory itself; see `feedback_spec_location` convention — canonical decision docs go in
  `docs/plans/`, not scattered).
- Whether Gate 1's standalone script lives under `scripts/ops/corpus/` (matching the existing
  interim scorer's location) or `scripts/analysis/` (matching `phase143_1_08_shadow_validation.py`'s
  location) — either is consistent with existing conventions; planner should pick based on
  which sibling script it more directly extends/reuses.
- `gate_evaluations` table schema details (columns beyond what SCORE-02/03 already specify:
  timestamp, gate_id, result, evidence JSON) — standard APR/migration conventions apply, no
  new user decision needed.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Schema and design (load-bearing)
- `docs/plans/archive/2026-06-25-v30-alpha-lifecycle-schema.md` — `alpha_ensemble_ic`/`alpha_frames`/
  `alpha_strategy_scores` table schemas, APR keys (`alpha.scoring.*`), phase sequencing. Note:
  this doc's internal "Phase 142A/142B/144" phase-number references are stale relative to the
  current roadmap (the AlphaScorer work it describes as "Phase 144" is now Phase 148) — trust
  the schema/logic content, not the phase numbers in this doc.
- `docs/plans/OOS-EVAL-PROTOCOL.md` — frozen OOS holdout discipline: `alpha.validation.oos_start`
  boundary, "run at most once per milestone gate" cadence rule, no-post-hoc-renegotiation rule.
  Directly governs D-02/D-03/D-04/D-05 above.
- `docs/plans/SHADOW-REVIEW.md` — frozen 5 pass/fail criteria (min sample, mean P&L CI 95%,
  Sharpe >0.5, max drawdown <25%, no IC-Sharpe cliff) that SCORE-03/Gate 2 evaluates against.
  Title says "Phase 147" — numbering fossil, see D-08.

### Prior measurement this phase directly builds on
- `.planning/phases/143.1-measurement-and-eligibility-integrity-fisher-z-ci-bootstrap-/143.1-08-SHADOW-VALIDATION.md`
  — source of the champion's already-computed Gate-2-equivalent numbers (D-06). Section 6
  (pooled) and Section 7 (regime-stratified, todo 165) both directly relevant.
- `services/counterfactual_tracker.py` — `evaluate_frame_gate`/`frame_gate_passes`, the
  generalized (grouping-key + coverage-floor) day-clustered bootstrap machinery from todo 165,
  to be reused for Gate 2's regime-stratified companion breakdown (D-07).
- `scripts/ops/corpus/ops_oos_holdout_eval.py` — existing interim diagnostic IC scorer;
  reuse pattern for Gate 1's standalone script (D-03).
- `services/ensemble_ic_engine.py` — pure IC helper functions to reuse for Gate 1's scorer;
  confirms current in-sample-only filtering behavior (`bar_ts < oos_start`).

### ROADMAP.md sections
- `.planning/ROADMAP.md` Phase 148 section — SCORE-01 through SCORE-04 requirements, two-gate
  promotion model, corrected "Depends on" line (2026-07-22, commit `4ef1b71a`).
- `.planning/ROADMAP.md` Phase 142A/142B sections — where `alpha_ensemble_ic`/`alpha_frames`
  were built; this phase is the consumer, not the builder, of those tables.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `services/ensemble_ic_engine.py` — pure IC computation helpers (BH-FDR, bootstrap CI,
  Fisher-z, walk-forward stability check) — reuse for Gate 1's standalone scorer, do not
  reimplement.
- `services/counterfactual_tracker.py::evaluate_frame_gate` — already generalized (todo 165,
  2026-07-21) with `group_key`/`min_clusters` params specifically for regime-stratified
  reuse. Directly applicable to Gate 2's D-07 requirement with zero new code needed beyond
  the call site.
- `scripts/ops/corpus/ops_oos_holdout_eval.py` — existing read-only OOS diagnostic scorer;
  structural template for Gate 1's authoritative version.
- `scripts/analysis/phase143_1_08_shadow_validation.py` — existing script pattern for
  loading APR config, running `evaluate_frame_gate`, printing a verdict report; structural
  template for Gate 2's SCORE-03 script.

### Established Patterns
- APR-backed thresholds via `config_schema`/`config_state`/`config_history` migration triple
  — `alpha.scoring.*` keys already exist (`min_strategy_n=30`, `bootstrap_max_n=5000`,
  `bootstrap_batch=1000`, `bootstrap_random_state=42`) and should be reused, not redefined.
- Day-clustered bootstrap CI (`frame_gate_passes`) is this project's established method for
  OOS mean-P&L significance testing — do not reintroduce a naive per-frame CI.
- Pre-registered, non-post-hoc-tunable APR keys (e.g. `alpha.validation.regime_gate_min_clusters`,
  seeded todo 165) — same discipline applies to any new threshold this phase introduces.

### Integration Points
- Neither table this phase needs (`alpha_strategy_scores`, `gate_evaluations`) currently
  exists in the DB — confirmed via `\d` 2026-07-22. Both need a real migration.
- `alpha_ensemble_ic` and `alpha_frames` already exist and are populated — this phase reads
  them, does not need to (re)create or backfill them.

</code_context>

<specifics>
## Specific Ideas

No UI/presentation specifics discussed — this is a batch scoring + gate-evaluation phase with
no dashboard component in its current scope. The "council of senior Renaissance engineers /
Jim Simons" lens the user applied throughout this discussion should carry forward into
planning and execution: ruthless simplicity, no schema built for hypothetical future reads,
full disclosure over false purity when reporting gate results, diagnose independently rather
than conflating signal and execution failures.

</specifics>

<deferred>
## Deferred Ideas

- Phase 147 (I7 CORPUS-07 evaluation) — confirmed during this discussion to be pure due
  diligence on an operationally dead system (I7 pipeline service failed since 2026-07-17,
  `ExecStart` target deleted from disk, zero plugins ever promoted/evaluated live), not a
  gate on this phase. Whenever convenient, not urgent.
- v2.x physical decommission (archive `src/intelligence/` I1-I7 tree, disable failed systemd
  unit, archive frozen v2.x tables) — todo 056, explicitly decoupled from this phase's proof
  gates per the 2026-07-19 operator call. Not this phase's scope.
- If Gate 2's pooled+regime-stratified verdict comes back HOLD (plausible given D-06's known
  starting numbers): diagnosing *why* and whether a frame/execution recalibration (not a
  signal problem) can fix it is real follow-on work, but is out of scope for this phase —
  this phase's job is to produce the verdict and the diagnostic evidence, not to fix a
  failing frame.

### Reviewed Todos (not folded)
None scored above the generic 0.6 keyword-match ceiling in `todo.match-phase` for this phase
— no todo had specific enough overlap with Gate 1/Gate 2 scope to fold in.

</deferred>

---

*Phase: 148-Alpha Scoring System*
*Context gathered: 2026-07-22*
