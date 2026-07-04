> **ARCHIVED 2026-07-03.** Superseded by `docs/ideas/intel-10-confluence-detection-persistence-layer.md`
> v3.0, rewritten per `.planning/research/2026-07-03-intel10-11-fable-review.md`. Kept for
> historical reference only — do not build against this version. The statistical content (gate
> stack, shrinkage, effective-N, decay design) survived into v3 unchanged; what changed is the
> architecture around it (v2's bespoke gate machinery, lifecycle tables, live daemon, and
> calibration estimate are deleted in favor of the shared Measurement Engine / Concept Registry /
> emission layer / feature-scoring §0b-0c that now own them generically). v2's claim that ANALOG-08's
> Score Object is a convergence target is also stale — `intel-13-analog-engine.md` deleted the Score
> Object outright.

# Confluence Detection & Persistence Layer — Terminal Output of the v3.0 Intelligence Pipeline

**Version:** 2.0
**Status:** draft — v1 design discussed 2026-07-01; v2 refined same day (Renaissance council pass)
**Priority:** high (names the actual terminal deliverable of the v3.0 pipeline)
**Milestone:** future — sequenced after Phase 147 (Interaction Primitives) and Phase 145-146 (AnalogEngine)
**Last Updated:** 2026-07-01
**Tags:** confluence, ic, calibration, analog-engine, shrinkage, shadow-mode, renaissance, persistence

**Supersedes in scope (not content):** `docs/ideas/intel-04-confluence-patterns.md` (I6, v2.x
plugin-based confluence — hand-tuned alignment scoring, not IC-validated). This doc is the v3.0
successor concept: a confluence is an empirically-validated statistical object with a lifecycle,
not a hand-authored rule.

**Strategic framing:** this doc is the **DiscreteTrack** of a two-track architecture — see
`docs/ideas/intel-11-dual-system-discrete-vs-portfolio.md` for the companion **PortfolioTrack**
(continuous forecasting + portfolio construction, firm-style) and the decision on how the two
relate and sequence.

---

## The Goal, Stated Precisely

Identify combinations of primitive features that have jointly predicted future price action with
statistical robustness the individual primitives lack; **save each validated combination as a
named, governed object**; and when the same combination recurs on a live bar, **persist a discrete,
auditable occurrence record** carrying the calibrated expected outcome and full provenance.

Execution and position sizing are out of scope. The system's terminal artifact is the saved,
provenanced occurrence — a falsifiable claim: *"pattern C_i, validated on N historical
occurrences with calibrated E[R] of X bps at horizon H, is present on this bar."*

## First Principles (the council's constraints, applied in order)

**1. Make the requirement less dumb.** The requirement is not "detect patterns." It is "make
falsifiable, auditable predictions whose accuracy is continuously measured." A pattern that fires
but whose outcomes aren't tracked against its claimed distribution is decoration. Outcome tracking
is therefore part of the core object, not a monitoring afterthought.

**2. Delete.** A confluence must beat the thing we already have. The additive `alpha_score`
ensemble is the null model. A candidate confluence earns existence only by demonstrating
**incremental predictive power over the linear combination of its own constituents** — partial IC
conditioned on the additive baseline, not standalone IC. Standalone significance is trivially
achievable by any correlated bundle of already-good features; that discovers nothing. This is the
single most important gate in the doc.

**3. Simplify.** The discrete event is *derived from* the continuous estimate — one mechanism, two
views. No separate detector logic, no independently-tuned firing threshold that can drift away
from the estimator it's supposed to summarize.

**4. Accelerate only after 1-3.** Live detection is cheap once discovery is done (features already
compute live per bar). Do not build live infrastructure before one confluence has survived
validation. There is nothing to detect yet.

**5. Automate the lifecycle.** Promotion, demotion, and retirement of confluences must run without
human judgment calls — the same evidence bars everywhere (`n >= 100`, bootstrap CI, p < 0.05),
enforced by machinery, not review meetings.

---

## The Statistical Object

**Governance note (2026-07-01):** this object's lifecycle is a Concept Registry domain — see
`docs/ideas/concept-governance-registries.md`, which generalizes exactly this pattern
(evidence-gated lifecycle + knowledge annotations) across research domains, and whose own build
trigger names "domain #2 with real candidates" as the go signal. If this doc reaches build stage
first, implement the lifecycle in the registry's four-table MVP shape
(concept_registry/concept_gate/concept_transition_log/concept_annotation), not as bespoke
confluence tables. The `decaying` state below maps onto the registry's status enum as a
transition pattern (active → shadow_only re-entry), not a new status — see the mapping note in
that doc's MVP section.

A **confluence** `C_i` is a tuple:

```
C_i = (constituents, condition, horizon, regime_scope,
       calibrated_outcome_distribution, validation_record, lifecycle_state)
```

- `constituents` — the primitive features (or the AnalogEngine embedding neighborhood) involved
- `condition` — the joint state that constitutes "present" (interaction term above/below calibrated
  bounds, or analog similarity above threshold with sufficient analog count and OOD-clear)
- `horizon` — the forward-return lookahead the prediction is calibrated against (from the IC decay
  curve, not chosen by hand)
- `regime_scope` — the stratification cells where validation held; a confluence validated in
  `high_bear` makes no claim in `low_bull`
- `calibrated_outcome_distribution` — the shrunk conditional distribution of forward returns given
  the condition (see Estimation below)
- `validation_record` — every gate it passed, with numbers, immutable
- `lifecycle_state` — `candidate → shadow → active → decaying → retired` (reuses Phase 149B
  governance one level up)

## Estimation: Calibrated, Shrunk, Never Raw

**The score is a conditional expectation with units** — `E[forward_return | C_i present]` (and the
distribution around it), not an IC-weighted sum in z-score units. It must be checkable for
calibration: predicted quantiles vs. realized outcomes (reliability curve, Brier score for the
directional claim).

**Shrinkage is mandatory, not optional.** Every confluence's raw historical mean return is an
overestimate — it was *selected* for looking good (the discovery process is a max over many
candidates; the winner's in-sample performance is biased upward by construction). The persisted
estimate is the raw conditional mean **shrunk toward the unconditional/baseline mean**, with
shrinkage weight set by effective sample size and cross-validated out-of-fold performance
(James-Stein / empirical-Bayes flavored — exact estimator is an open question below, but the
direction is not: raw selected means are never persisted as the claim). This is the quantitative
version of "expect the live edge to be smaller than the backtest edge," built into the estimate
itself rather than left as a caveat.

**Effective N, not raw N.** Occurrences of a confluence cluster in time (regimes persist; a
condition true at bar T is usually true at T+1). Validation counts must use autocorrelation-
corrected effective sample size — same HAC/subsampling discipline `ic_engine` already applies —
or a 500-occurrence confluence that is really 30 independent episodes will sail through gates it
should fail.

## The Gate Stack (all mandatory, in order)

1. **Marginal lift over the additive null.** Partial IC / incremental out-of-fold R² of the
   confluence conditioned on the linear combination of its own constituents. No lift → the
   confluence is a repackaging of known marginals → rejected. (Delete step.)
2. **Multiplicity control at the search level.** BH-FDR across *all candidate confluences tested
   in the discovery batch*, not per-candidate p-values. The combinatorial search space is the
   multiple-testing surface; Phase 147's ≤50-curated-interactions cap and the corpus-level FDR
   machinery from Phase A are the existing controls this inherits.
3. **Walk-forward stability.** Same fold construction as feature IC; max/min fold ratio bound. An
   effect that lived in one regime-era and died is regime-scoped or rejected, not averaged.
4. **Calibration.** On held-out folds, the predicted outcome distribution must match realized
   outcomes (reliability curve within tolerance; Brier score beats the unconditional-base-rate
   forecast). IC says the ranking is right; calibration says the *number we persist* is honest.
5. **Cost hurdle.** Shrunk E[R] must clear the transaction-cost floor (todo 030) with margin, at
   the executable-returns definition (Invariant 1 — `executable_open_to_open`, never theoretical).
   A real pattern that can't pay its costs is saved as research, never fired as an event.
6. **OOS confirmation.** The standing 6-month OOS boundary (`alpha.validation.oos_start`) applies:
   discovery and gates 1-5 run strictly pre-boundary; a confluence touches `active` only after its
   OOS window confirms the shrunk estimate within its own claimed distribution.

A confluence passing 1-5 enters **shadow**: it fires and persists occurrences live, outcomes are
tracked, nothing downstream consumes it. Promotion to `active` is earned by shadow-mode proof —
the same `n >= 100 AND bootstrap_ci_lower > 0` bar as everything else in this codebase, applied to
its live shadow occurrences. **The system never trusts its own backtest as final evidence.**

## Live Detection & the Persisted Event

Once ≥1 confluence reaches `shadow`:

- A live daemon (the first live consumer in the v3.0 stack — none of `regime_writer`/`ic_engine`/
  `ensemble_trainer`/`alpha_publisher` currently runs live) holds the registry of shadow+active
  confluences and evaluates each against the completed bar's feature vector. Per-bar cost is a
  handful of comparisons and, for analog-type confluences, one ANN lookup against a pre-built
  index — cheap by design; all expensive work happened offline.
- **On match, persist an occurrence row:** confluence ID + version, symbol/tf/bar_ts, the
  constituent values at fire time, the shrunk calibrated E[R] and distribution *as claimed at fire
  time* (frozen — so later re-estimation can't retroactively flatter old fires), regime context,
  and lifecycle state at fire time.
- **Every occurrence row is opened, not closed.** At horizon H the realized executable return is
  back-filled (the `llm_writer` outcome-backfill pattern, reused). The occurrence table is
  therefore simultaneously the audit trail and the calibration/decay dataset.

**Continuous score alongside discrete events:** the same registry evaluation yields, per bar, the
combined calibrated expectation across whatever confluences are present (see open question 3).
This is the graded view; the persisted events are its auditable extremes. One estimator, two views
— nothing to keep in sync.

## Decay Is the Steady State, Not an Exception

Renaissance's core operational insight is that signals die — competition, regime change,
publication. Design for it:

- Rolling calibration check per confluence on its own live occurrences: when realized outcomes
  drift outside the claimed distribution (CUSUM or rolling Brier degradation past an APR-keyed
  bound), auto-demote `active → decaying` (weight-consumers stop reading it), then `→ retired` if
  it fails re-qualification. Symmetric: a `decaying` confluence whose live outcomes recover
  re-promotes by the same evidence bar. No cooldown clocks, no human sign-off — evidence in, state
  out (Phase 149B semantics, one level up).
- Retired confluences and their full occurrence history are **never deleted** — they are training
  data about how edges die, and candidate re-entrants if their regime returns.

## Silent Failure Modes (design against, up front)

- **Selection bias in the persisted estimate** — addressed by mandatory shrinkage (above); the
  single most likely way this system quietly lies to us.
- **Temporal clustering inflating N** — addressed by effective-N (above).
- **Analog index leakage** — AnalogEngine retrieval must be point-in-time: a live query may only
  retrieve analogs whose *outcomes were realized* before the query bar. An index rebuilt naively
  over full history leaks future outcome information into "historical analog" statistics.
- **Regime-scope creep** — a confluence firing outside its validated `regime_scope` must be
  recorded as `out_of_scope` occurrences (tracked, never counted toward its claims, useful as free
  OOS evidence for scope expansion).
- **Threshold drift** — the firing condition's bounds live in APR with provenance, recalibrated
  only through the gate stack, never hand-nudged because "it stopped firing."

## Dependencies

- **Phase 147** — supplies explicit interaction-term candidates (constituents + condition)
- **Phase 145-146** — supplies analog-neighborhood candidates; ANALOG-08's Score Object
  (E[R] distribution, direction, OOD flag, analog count) is a direct precursor of this doc's
  calibrated-estimate concept and should converge with it, not duplicate it
- **Todo 030** — cost-hurdle floor for gate 5
- **Phase 149B** — lifecycle/demotion machinery, reused at confluence grain
- **Prerequisite build item:** the live-scoring daemon (none exists in v3.0); scope it inside this
  phase when scoped, not as an assumption

## Open Questions

1. Shrinkage estimator specifics — empirical-Bayes toward the regime-cell baseline vs. out-of-fold
   mean; how the shrinkage weight maps to effective N. Needs a small study on Phase 147's first
   surviving interactions, not a whiteboard decision.
2. Occurrence schema — new table vs. `alpha_events` extension. Leaning new table
   (`confluence_events`): different grain (sparse discrete fires vs. per-bar scores), different
   lifecycle joins, and `alpha_events` is already 12M+ rows of a different concept.
3. Combining simultaneous confluences on one bar into the continuous view — independent-evidence
   product/pooling vs. max-conviction vs. learned combiner; must not silently re-introduce the
   additive assumption gate 1 exists to escape. Default until studied: report the set, combine
   conservatively (min or shrunk pool), never sum.
4. Calibration sample floor — how many *effective* occurrences before a reliability-curve claim is
   trustworthy; parallel to `alpha.ic.min_obs_per_regime`, needs its own APR key with
   `[initial_estimate]` provenance.

## References

- `docs/plans/2026-07-01-regime-stratification-alternatives.md` — stratification dimensions; CI-width
  selection logic this design's calibration layer extends
- `docs/ideas/multi-engine-regime-architecture.md` — Partial IC validation protocol (gate 1's direct
  ancestor)
- `docs/ideas/intel-04-confluence-patterns.md` — pre-v3.0 confluence concept (I6, plugin-based)
- Todo `030-cost-hurdle-apr-calibration.md`
- ROADMAP.md Phase 145, 146, 147, 149B; Phase 142B SHADOW-REVIEW.md pre-commitment pattern (criteria
  defined before data is seen — the same discipline applies to every gate in this doc)
