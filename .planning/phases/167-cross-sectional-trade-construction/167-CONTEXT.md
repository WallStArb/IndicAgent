# Phase 167: Cross-Sectional Trade Construction (cross_sectional_relative_value) - Context

**Gathered:** 2026-07-26 (--auto mode — no interactive discussion; deep context already
established this session via cross_sectional_relative_value's falsification script and results)
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the cross-sectional long-short construction `docs/research/trade-construction-layer.md`
designs (v1: rank the equity universe by a feature at each bar, long the top decile / short
the bottom decile, dollar-neutral) plus its shadow measurement — turning Edge Source Thesis's
cross_sectional_relative_value from a validated one-off falsification script
(`scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py`) into a real,
cost-aware, monitored construction that can eventually feed Phase 156-159's execution/sizing
chain. This phase does NOT touch live capital, does NOT build portfolio state/sizing/execution
infrastructure (those stay gated behind this phase's outcome, per STATE.md), and does NOT
attempt Kelly sizing, risk modeling, or borrow-cost modeling — `trade-construction-layer.md`'s
own "What This Explicitly Defers" section rules those out for v1.

Read this phase entirely through a Renaissance-style rigor lens: the construction earns
production consideration through validated shadow measurement (net-of-cost spread Sharpe > 0
at 95% bootstrap CI, beating the shuffled-ranking null — `trade-construction-layer.md`'s own
Validation Gates section), not by being built and assumed correct. Prefer the simplest
mechanism that clears the bar; this is a v1 spec, not an optimizer.

</domain>

<decisions>
## Implementation Decisions

**All decisions below were auto-resolved (--auto mode) using the "replicate exactly what cross_sectional_relative_value
proved, expand incrementally" principle** — every gray area had a "match the proven result"
option and a "generalize/expand now" option; the former was chosen every time, consistent with
this project's established discipline (`docs/foundation/principles.md`: earn complexity through
proof; multiple prior phases — 143.1's sign-symmetric HOLD, Phase 166's scalar-vs-structural
comparison — followed the identical pattern of not adding scope the evidence doesn't yet
support).

### Ranking input: raw qualifying feature, not ensemble_alpha
- **D-01:** Rank the cross-sectional universe directly on `ctf_momentum` (the specific feature
  cross_sectional_relative_value measured and validated), NOT on the existing linear `ensemble_alpha`/IC-weighted combiner
  output. This is a hard architectural distinction, not a style preference: `ensemble_alpha` is
  the per-symbol absolute-direction construction that Phase 148's Gate 2 already failed and
  todo 179 found has zero regime-conditional edge anywhere. Building Phase 167 on top of that
  same combiner's output would test an unvalidated, already-suspect input — the entire point of
  cross_sectional_relative_value was that ranking a raw feature directly, bypassing the linear combiner, is what cleared
  the bar. Confirmed via direct code/data check this session: cross_sectional_relative_value's script ranks
  `feature_vectors.ctf_momentum` directly, never touches `alpha_events`/`ensemble_alpha`.

### Feature scope for v1: single feature, not a composite
- **D-02:** Ship v1 wired specifically to `ctf_momentum` — the exact feature and construction
  cross_sectional_relative_value validated (decile spread, dollar-neutral, both lookahead scales, cost-hurdle-adjusted).
  Do NOT generalize to a multi-feature composite ranking score in this phase. A composite score
  re-opens exactly the "how do multiple features combine" question D-01 just resolved in
  the OTHER direction (raw feature > combiner) and would dilute a proven single-feature signal
  with untested ones. Expanding to additional qualifying features is legitimate future work,
  scoped as its own follow-on once this construction is live and shadow-validated.

### Rebalance cadence: replicate cross_sectional_relative_value's exact per-bar rebalance for v1 validation
- **D-03:** The first shadow-validation pass must rebalance every bar, exactly matching how cross_sectional_relative_value
  was measured (mean one-way leg turnover ~19.5%/bar, median ~6.25%, net spread confirmed
  positive up to a 10bp round-trip cost floor at that turnover). `trade-construction-layer.md`'s
  stated "trade only ranking changes that clear a cost floor" optimization is a legitimate
  future refinement, but implementing it in the SAME pass as building the construction changes
  two variables at once (does the construction work at all? does the turnover-reduction
  optimization also work?) — don't conflate them. Build the exact-replica version first, prove
  it holds up in real shadow measurement, then evaluate the reduced-turnover variant as a
  fast-follow with its own before/after comparison.

### Universe/timeframe scope: 15m, full equity 80-symbol universe, matching the proof exactly
- **D-04:** v1 targets `tf=15m` only, over the full active equity universe (the same 80-symbol
  set, `i.is_active=true AND i.contract_details->>'asset_class'='equity'`, cross_sectional_relative_value's script used).
  No other timeframe or asset class in this phase. cross_sectional_relative_value's temporal-stability check (run this
  session, 21/21 years 2006-2026 positive, all three major stress eras positive) is 15m-specific
  evidence; extending to 5m/1h/1d or to `rates` is unvalidated and belongs in a future phase
  once 15m's live shadow construction proves out.

### Cost-hurdle treatment: already applied, carries forward as a locked finding
- **D-05:** The construction must be built cost-aware from the start, not as an afterthought.
  This session already ran the todo-030-convention cost-hurdle sweep directly against cross_sectional_relative_value's
  actual measured turnover (not a flat per-trade cost) — net spread survives at every tested
  round-trip cost floor from 1bp through 10bp (todo 030's own blended range for this liquidity
  mix). This result is now built into
  `scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py`'s `_cost_hurdle_check`
  function — planner/researcher should treat this as a settled input, not a question to
  re-litigate, though the production construction service should still compute cost
  net-of-turnover the same way (don't hardcode a single "it survives" conclusion without the
  live computation).

### Folded Todos
- **185 — `ic_math.py` causal per-entity demeaning primitive** (filed this session): not
  directly required by cross_sectional_relative_value's construction (cross_sectional_relative_value ranks, it doesn't pool absolute per-symbol
  predictions the way nonlinear_interaction_combiner's non-linear combiner does), but the shadow-measurement/monitoring
  service this phase builds will likely need the SAME class of guard if it ever computes
  pooled-panel statistics (e.g., aggregate portfolio-level diagnostics across symbols). Fold in
  as a prerequisite check for the researcher to confirm is/isn't needed, not as a hard
  dependency.
- **186 — `ic_math.py` cross-sectional block-bootstrap gap** (filed this session): directly
  relevant. This phase's shadow-validation measurement (`trade-construction-layer.md`'s
  Validation Gate 1: "net-of-cost spread Sharpe > 0 at 95% bootstrap CI") needs exactly this
  primitive — a properly calibrated cross-sectional block bootstrap, not the approximated
  version nonlinear_interaction_combiner's rigor pass used ad hoc. Planner should scope calibrating and landing this
  primitive as part of Phase 167's plan, reusing the approximation in
  `t5_nonlinear_combiner_lightgbm_check.py` as a starting point, not a final answer.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design and validation (locked, do not re-derive)
- `docs/research/trade-construction-layer.md` — the full v1 construction design (rank → decile
  buckets → equal-weight vol-scaled legs → dollar-neutral netting → cost-floor-gated
  rebalance → portfolio-level measurement), Validation Gates section (the exact bar this
  phase's shadow measurement must clear), and the AegisAgent/TradeAgent reuse assessment
  (what does/doesn't transfer from old vision docs — not relevant to v1 scope but useful
  context for why certain things are explicitly deferred)
- `docs/research/data-edge-source-thesis.md` — cross_sectional_relative_value section (today's validated result, both
  lookahead scales, shuffled-null clearance), T2 section (why the per-symbol/linear-combiner
  construction was rejected — the reason D-01 above rules out `ensemble_alpha` as the ranking
  input), nonlinear_interaction_combiner section (the sibling non-linear-combiner candidate — informative, not this
  phase's scope)

### The proof this phase turns into production
- `scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py` — the exact
  construction, cost-hurdle treatment, and temporal-stability methodology this phase's
  production service must replicate faithfully (same decile fraction, same feature, same tf,
  same universe filter, same cost-floor convention)

### Statistical primitives this phase's measurement work depends on
- `src/intelligence/statistics/ic_math.py` — `circular_block_bootstrap_ic_serial` (per-symbol,
  existing) and `build_walk_forward_folds` (existing, reusable as-is); needs the cross-sectional
  block-bootstrap variant (todo 186) before this phase's Validation Gate 1 can be measured with
  full statistical rigor
- `services/counterfactual_tracker.py` — `frame_gate_passes`/`evaluate_frame_gate` (the
  day-clustered BCa/CLT bootstrap machinery cross_sectional_relative_value's script already reuses verbatim — same pattern
  the production service should use for its own gate checks)

### Cost-hurdle convention
- `.planning/todos/pending/030-cost-hurdle-apr-calibration.md` — Step 0's blended round-trip
  cost-floor convention (~1bp liquid core, ~2-4bp sector ETFs, ~6-10bp illiquid international);
  this phase's cost treatment (D-05 above) applies that same convention to actual measured
  turnover rather than todo 030's own median-IC-implied-E[R] approximation

### Base class / architecture pattern
- `src/core/agent/base_batch.py` — `BaseBatch`, the standing Ring 0 pattern every batch/
  measurement service since Phase 138 extends (confirmed via `services/tag_calibrator.py`,
  `services/counterfactual_tracker.py`); this phase's construction+measurement service should
  follow the same pattern unless research finds a specific reason not to

### Phase sequencing
- `.planning/ROADMAP.md` Phase 167 entry — full phase text, dependency on Phase 142A (already
  cleared 2026-07-22), sequencing ahead of Phase 156-159 (execution/sizing chain) and
  independent of Phase 151/164/165 (feature-expansion track)
- `.planning/STATE.md` Current Focus section — the fork this phase resolves (T2 dead per todo
  179, cross_sectional_relative_value the chosen path forward) and the standing caveat that T2's death is still provisional
  pending todo 183's corpus recompute (does not affect cross_sectional_relative_value's own result, which has no regime
  dependency)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `services/counterfactual_tracker.py`'s `frame_gate_passes`/`evaluate_frame_gate` — day-
  clustered BCa/CLT bootstrap gate evaluation, already proven correct and already used by cross_sectional_relative_value's
  falsification script; the production service's own gate checks should call this directly, not
  reimplement
- `src/intelligence/statistics/ic_math.py`'s `circular_block_bootstrap_ic_serial` and
  `build_walk_forward_folds` — existing, reusable verbatim for any per-symbol-scoped statistics
  this phase's monitoring needs
- `src/core/agent/base_batch.py`'s `BaseBatch` — pool lifecycle, D-06 oneshot contract,
  `content_key()`; the established base class for this shape of service

### Established Patterns
- Every batch/measurement service since Phase 138 (`ic_engine.py`, `ensemble_trainer.py`,
  `tag_calibrator.py`, `counterfactual_tracker.py`) extends `BaseBatch` and follows the DAG
  invariant that persistence goes through a dedicated writer, never inline compute — this
  phase's construction service should match that shape
- Shadow-mode-first validation before any production/live consideration — Phase 142B's
  `alpha_frames`/`CounterfactualTracker` pattern (counterfactual measurement before real
  capital) is the direct precedent `trade-construction-layer.md` cites for this phase's own
  validation approach

### Integration Points
- Reads `feature_vectors` (for `ctf_momentum` and the ranking universe) and `forward_returns`
  (for measured spread returns) directly — same tables every other measurement service in this
  pipeline reads, no new upstream dependency
- Does NOT read or depend on `alpha_events`/`ensemble_alpha` (see D-01) — this is a parallel
  measurement path to the existing linear-ensemble pipeline, not a consumer of its output

</code_context>

<specifics>
## Specific Ideas

No user-provided specifics beyond what's already locked in `trade-construction-layer.md` and
this session's cross_sectional_relative_value validation work — this phase exists specifically because that prior research
and this session's falsification-test result already answered "does this construction work,"
leaving "how do we build and monitor it in production shape" as the only open question for
planning.

</specifics>

<deferred>
## Deferred Ideas

- **Multi-feature composite ranking** (D-02) — belongs in a future phase once the single-feature
  `ctf_momentum` construction is live and shadow-validated.
- **Cost-floor-gated rebalance-on-ranking-change** (D-03) — `trade-construction-layer.md`'s own
  stated optimization; deferred to a fast-follow once the exact-replica per-bar version proves
  out in shadow measurement.
- **Additional timeframes/asset classes** (D-04) — 5m/1h/1d and `rates`/`commodity`/`fx` groups
  are all out of scope; revisit once 15m/equity is live and validated.
- **Kelly-fraction sizing, risk modeling, borrow-cost modeling** — explicitly deferred by
  `trade-construction-layer.md`'s own "What This Explicitly Defers" section; not re-litigated
  here.

### Reviewed Todos (not folded)
The todo-matcher's keyword scoring returned every single pending todo at an identical 0.6 score
(clearly not discriminating — spot-checked 038 and 135, neither is materially about trade
construction), so the standard --auto "fold everything >=0.4" rule was overridden here rather
than followed blindly. Only 185/186 (see Folded Todos above) were judged genuinely relevant
after manual review; the remaining ~55 pending todos were reviewed by title/score and found
unrelated to this phase's scope (regime-model calibration, HMM internals, API route hygiene,
migration cleanup, etc.) — none warrant listing individually here.

</deferred>

---

*Phase: 167-cross-sectional-trade-construction*
*Context gathered: 2026-07-26*
