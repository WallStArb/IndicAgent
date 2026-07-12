# Confluence — a Governed Predictor Family

**Version:** 3.0
**Status:** draft — v1 design discussed 2026-07-01; v2 refined same day (Renaissance council pass);
v3 rewritten 2026-07-03 against the post-142A predictor architecture (see Provenance)
**Priority:** high (a proven confluence is a real predictor family for the ensemble, not a
side system)
**Milestone:** future — sequenced after Phase 150 (Interaction Primitives) and `intel-13`'s
analog predictors (formerly Phase 148-149), and gated on the calibration prerequisite below
**Last Updated:** 2026-07-12 (full Fable re-verification against Phase 143's executed lifecycle
mechanics, todo 098 item 2 - see 2026-07-12 note below)
**2026-07-11 note:** fixed two broken filename references in the Bibliography (`intel-13`/`intel-15`
prefixes were dropped in a since-run rename sweep) and flagged gate 6's `bootstrap_ci_lower > 0`
form as inheriting Phase 143.1's sign-asymmetric gate finding. Spot-checked against live schema:
`concept_*` tables still unbuilt (doc's claim holds) and `feature_registry`'s `shadow_only`/
`deprecated` enum values confirmed real. A full re-verification against Phase 143's executed
lifecycle mechanics (per todo 098) is still owed — this pass was budget-constrained, not that.
**2026-07-12 note (todo 098 item 2 - the full re-verification the 2026-07-11 note left owed, now
done):** verified against `src/intelligence/feature_registry_service.py`
(`record_transition_sync`, `advance_shadow_counters_sync`, `is_promotion_eligible`),
`services/ic_engine.py`'s `_run_lifecycle_hook`, and migrations 216/218/224. Four corrections
applied in place: (1) the shadow→active promotion bar - the previously cited
`n >= 100 AND bootstrap_ci_lower > 0` bar is the archived v2.x `shadow_registry` bar (dead since
2026-07-02); the live mechanic is Phase 143's counter-based recovery
(`alpha.decay.recovery_min_passes` = 2 consecutive passing runs AND
`alpha.decay.recovery_min_observations` = 2000 independent observations, counters reset to zero
on every re-demotion). (2) Gate 6's sign-asymmetry caveat updated: the sign-symmetric predicate
has since shipped inside the lifecycle hook behind the `alpha.ensemble.sign_symmetric` APR flag
(migration 224, currently `false`), so the corrected form of the bar is now known, not pending.
(3) Automated retire retracted - Phase 143 makes `deprecated` operator-only
(`record_transition_sync` raises ValueError on any automated transition targeting it); the Decay
section now also inherits the materiality gate and regime-shift guard the executed hook actually
applies. (4) Governance table-name typo fixed (`concept_domains` → `concept_gate`) plus a pointer
to `concept_gate_stack` as the home of the ordered gate 1-6 stack. Confirmed accurate as written:
`active → shadow_only` demotion via `record_transition_sync` with an optimistic
`WHERE status = from_status` lock; evidence-only transitions with no cooldown clocks;
`decaying`/`retired` as narrative labels only (real states are
`candidate`/`active`/`shadow_only`/`deprecated`, migration 172); no `pre_shadow_weight` column
(promotion is the status flip alone, ensemble_trainer recomputes weights from scratch, migration
216). Phase 143's `feature_transition_log` (sole authoritative record) + `integrity_monitor`
(observability-only gate facts, migration 218) split is the shipped realization of this doc's
immutable `validation_record` at feature grain; at confluence grain the analog is
`concept_transition_log` + `integrity_monitor`.
**Tags:** confluence, ic, calibration, analog-engine, shrinkage, shadow-mode, renaissance,
concept-registry, predictor

**Source:** `.planning/research/2026-07-03-intel10-11-fable-review.md` (F1-F6, R1) — Author: Fable 5
**Informed by:** Fable 5 — corrected the doc's own "terminal deliverable" framing, retired the
stale ANALOG-08 Score Object convergence target, named feature-scoring §0b/0c as hard
prerequisites of gate 1, and confirmed the Concept Registry deferral was already right.
Supersedes v2.0 (2026-07-01), archived at `docs/research/archive/intel-10-v2-confluence-persistence.md`.

**Supersedes in scope (not content):** `docs/research/intel-04-confluence-patterns.md` (I6, v2.x
plugin-based confluence — hand-tuned alignment scoring, not IC-validated). This doc is the v3.0
successor concept: a confluence is an empirically-validated statistical object with a lifecycle,
not a hand-authored rule.

---

## The Core Idea, Stated Once

A **confluence** is an empirically validated joint condition over primitive features (or an
AnalogEngine embedding neighborhood) that jointly predicts forward returns with statistical
robustness the individual constituents lack. Under the architecture that settled out of the
2026-07-02 review (`intel-15`'s Measurement Engine, `intel-13`'s analog predictors), a confluence
is not a new terminal layer — **it is a predictor**: a per-bar value measured by the same
kernel, weighted by the same ensemble, emitted through the same emission layer, validated by the
same frame simulator as every other predictor in the system. Its per-bar value is a shrunk,
calibrated conditional-return distribution (`intel-13`'s return-distribution primitive), **NULL
where the condition is absent** — the same definedness rule `intel-13` already specified for
analog predictors: sparsity is handled by the existing min-obs gates, conditionality is stated,
never hidden.

This v3 rewrite does not change the statistical content of v2 — the gate stack, shrinkage,
effective-N, and decay design below are unchanged and survived Fable review intact. What changes
is the architecture around them: four systems v2 proposed building bespoke are deleted in favor
of the generic layer that now owns them.

## What Gets Deleted as Separate Systems

| v2 proposed (bespoke, confluence-grain) | Where it actually lives now |
|---|---|
| Its own gate machinery (FDR, walk-forward, OOS confirmation) | Measurement Engine kernel (`intel-15`) — one estimator, shared with every predictor including Phase 150's interaction terms |
| Its own lifecycle (`candidate → shadow → active → decaying → retired`) | Concept Registry's four-table MVP (`concept_registry`/`concept_gate`/`concept_transition_log`/`concept_annotation`) — this deferral was already correct in v2 and is unchanged here |
| A dedicated live daemon + `confluence_events` occurrence table | The emission layer (`alpha_publisher`/`alpha_events`) + Phase 142B's `alpha_frames` — frozen claim at emission, outcome backfilled, pre-committed review criteria. One simulator concept, not a second one |
| A bespoke calibrated E[R] estimate | `2026-06-29-feature-scoring-beyond-ic.md` §0b (shrunk weights) / §0c (calibrated return-unit output) — now a **named prerequisite** of gate 1 (see below), not a parallel calibration mechanism |

The live-scoring daemon is real infrastructure the v3 stack currently lacks entirely (nothing
runs live yet), but it is not confluence-specific — scope it once, at the emission layer, the
first time *anything* is worth firing live. Confluence does not own it.

## What Is Genuinely New Here, and Where It Lands

1. **Gate 1 — marginal lift over the additive null.** Partial IC / incremental out-of-fold R² of
   the confluence conditioned on the linear combination of its own constituents. This is the
   single most important idea in this doc and exists nowhere else in the built system. It belongs
   in the measurement kernel as a gate mode, shared with Phase 150's interaction candidates — one
   implementation, two consumers.
2. **Mandatory winner's-curse shrinkage** on the persisted estimate — the same mechanism
   [Concept Registry](platform-unified-concept-registry.md)'s `baseline_metric` shrinkage note already uses (feature-
   scoring §0b's estimator). Keep unified, not reimplemented.
3. **Effective-N via temporal-clustering correction** on occurrence counts — the same HAC/
   subsampling discipline `ic_engine` already applies, applied to a new count. Occurrences of a
   confluence cluster in time (a condition true at bar T is usually true at T+1); a 500-occurrence
   confluence that is really 30 independent episodes must not sail through gates it should fail.
4. **Per-concept calibration monitoring** (rolling reliability/Brier drift, CUSUM) driving
   Concept Registry transitions, plus `out_of_scope` occurrence tracking as free OOS evidence for
   scope expansion — both evaluation-engine behaviors writing registry state, not properties of a
   bespoke event system.
5. **Conservative combination default** when multiple confluences fire on one bar (report the
   set, combine via min or shrunk pool, never sum) — pending the study in Open Question 3.

## The Hard Prerequisite Gate 1 Depends On

**Gate 1's null model must be the calibrated, shrunk additive baseline — not the current raw
`alpha_score`.** If gate 1 tests incremental lift against today's IC-weighted linear sum of
z-scores (no units, weights from raw selected ICs), the gate is soft: a candidate confluence can
clear it merely by recovering information a properly shrunk/calibrated linear combiner would have
captured anyway. That would silently persist "validated confluences" whose entire edge is an
artifact of a weak baseline — exactly the kind of silent wrong answer this codebase's principles
exist to prevent, at the single gate this doc calls most important.

**`feature-scoring-beyond-ic.md` §0b (shrunk weights) and §0c (calibrated return-unit output) are
therefore hard prerequisites of gate 1**, not merely a shared upgrade path. Once they land, the
null model is the calibrated linear combination of the confluence's constituents in return units
— "incremental lift" then means what it claims to mean, and the cost-hurdle gate (gate 5) compares
like units to like.

## The Gate Stack (all mandatory, in order)

1. **Marginal lift over the calibrated additive null** (see prerequisite above). No lift → the
   confluence is a repackaging of known marginals → rejected.
2. **Multiplicity control at the search level.** BH-FDR across *all candidate confluences tested
   in the discovery batch*, not per-candidate p-values. Phase 150's ≤50-curated-interactions cap
   and the corpus-level FDR machinery from Phase A are the existing controls this inherits.
3. **Walk-forward stability.** Same fold construction as feature IC; max/min fold ratio bound. An
   effect that lived in one regime-era and died is regime-scoped or rejected, not averaged.
4. **Calibration.** On held-out folds, the predicted outcome distribution must match realized
   outcomes (reliability curve within tolerance; Brier score beats the unconditional-base-rate
   forecast). IC says the ranking is right; calibration says the *number we persist* is honest.
5. **Cost hurdle.** Shrunk E[R] must clear the transaction-cost floor (todo 030) with margin, at
   the executable-returns definition (Invariant 1 — `executable_open_to_open`, never theoretical).
6. **OOS confirmation.** The standing 6-month OOS boundary (`alpha.validation.oos_start`) applies:
   discovery and gates 1-5 run strictly pre-boundary; a confluence touches `active` only after its
   OOS window confirms the shrunk estimate within its own claimed distribution.

   **Caveat added 2026-07-11, updated 2026-07-12:** Phase 143.1 found that `ic_ci_lower > 0`/
   `fold_ic > 0`-style gates are sign-asymmetric — they silently exclude every contrarian
   (short-favoring) candidate before weighting, which is why `alpha_events` is currently 99.99%
   long-only. The corrected form has since shipped in `ic_engine`'s lifecycle hook (143.1
   Component E, todo 094): under the `alpha.ensemble.sign_symmetric` APR flag (migration 224,
   currently `false`, flips after 143.1's A/B), a cell fails only when the CI on its OWN claimed
   side includes zero (`ic_ci_lower <= 0` for `ic_sign = 1`, `ic_ci_upper >= 0` for
   `ic_sign = -1`). This gate's bar should be written that way from day one: "bootstrap CI on the
   claimed direction's side excludes zero," not `bootstrap_ci_lower > 0` unconditionally. A
   confluence whose `condition` already encodes a directional bias may keep an asymmetric bar,
   but that is then a stated per-confluence choice, never an inherited default.

A confluence passing 1-5 enters **shadow**: it fires and persists occurrences live, outcomes are
tracked, nothing downstream consumes it. Promotion to `active` is earned by shadow-mode proof.
**Corrected 2026-07-12:** this doc previously cited `n >= 100 AND bootstrap_ci_lower > 0` as
"the same bar as everything else in this codebase" - that bar belongs to the archived v2.x
`shadow_registry` (confirmed dead 2026-07-02) and is not the live mechanic. The live lifecycle's
promotion bar is Phase 143's counter-based recovery (`is_promotion_eligible` in
`src/intelligence/feature_registry_service.py`): `consecutive_shadow_passes >=
alpha.decay.recovery_min_passes` (2) AND `observations_since_demotion >=
alpha.decay.recovery_min_observations` (2000), evidence-only, no calendar clock, both counters
reset to zero on every re-demotion so a second decay cycle re-earns the full bar. A
confluence-grain promotion bar should take that shape - consecutive passing evaluations plus an
independent-observation floor counted at confluence effective-N - with the two floors as
`concept_gate` fields, and any CI bound stated sign-symmetrically per the gate 6 caveat above.
**The system never trusts its own backtest as final evidence.**

## The Statistical Object

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
- `calibrated_outcome_distribution` — **`intel-13`'s return-distribution primitive** (full empirical
  distribution per horizon — percentiles, moments, shape label), shrunk per the mechanism above.
  This replaces v2's convergence target of ANALOG-08's Score Object, which `intel-13` deleted
  outright along with `score_cache` — do not build toward that object; it no longer exists in the
  design.
- `validation_record` — every gate it passed, with numbers, immutable
- `lifecycle_state` — a Concept Registry row (see Governance below), gate stack = gates 1-6

A confluence concept row is a `concept_registry` row whose gate stack is gates 1-6; there is no
separate "confluence governance." That also resolves the calibration-sample-floor question below
as a `concept_gate` field, not a new mechanism.

## Governance: Concept Registry, Unchanged

**This deferral was already correct in v2 and Fable review confirmed it stays exactly as
written.** Implement the lifecycle in [Concept Registry](platform-unified-concept-registry.md)'s four-table MVP shape
(`concept_registry`/`concept_gate`/`concept_transition_log`/`concept_annotation`), not as bespoke
confluence tables. The registry doc's 2026-07-06 domain-vetting pass added `concept_gate_stack`
(a fifth table, built only when a domain with an ordered gate sequence is actually seeded) as the
home for this doc's gates 1-6; scalar floors like the calibration sample floor stay
`concept_gate` fields. `decaying` maps onto the registry's status enum as a transition pattern
(`active → shadow_only` re-entry), not a new status — see that doc's mapping note. `retired` maps
onto `deprecated`. Per the topdown review (D9), the registry's MVP is built as a follow-on seeded
from Phase 142B.1's `ensemble_strategy` outputs (topdown Open Q6's backfill path — 142B.1 itself
shipped no registry code; tracked at todo 058), not built during 142B.1 itself; `confluence`
is a later domain, added once real candidates exist (Phase 150 / analog predictors survive their
gates).

## Decay Is the Steady State, Not an Exception

**Note (2026-07-04, cluster review F4):** `decaying` and `retired` below are domain shorthand, not
registry enum values — per Governance above, `decaying` = `active → shadow_only` re-entry and
`retired` = `deprecated`. Kept as narrative labels here because they read naturally for what the
confluence is *doing* (still firing, not yet acted on / permanently excluded); an implementer
should write the actual transitions in enum terms.

Renaissance's core operational insight is that signals die — competition, regime change,
publication. Design for it:

- Rolling calibration check per confluence on its own live occurrences: when realized outcomes
  drift outside the claimed distribution (CUSUM or rolling Brier degradation past an APR-keyed
  bound), auto-demote `active → decaying` (weight-consumers stop reading it). Symmetric: a
  `decaying` confluence whose live outcomes recover re-promotes by the same evidence bar. No
  cooldown clocks, no human sign-off — evidence in, state out (Phase 143's executed semantics,
  one level up). **Corrected/extended 2026-07-12** against `ic_engine`'s executed
  `_run_lifecycle_hook`, three rules this section previously missed or got wrong:
  - **No automated retire.** Phase 143 makes `deprecated` operator-only:
    `record_transition_sync` raises ValueError on any automated transition targeting it. This
    section's earlier "then `→ retired` if it fails re-qualification" is retracted - a confluence
    that fails re-qualification parks in `shadow_only` indefinitely (its history intact, per the
    never-delete rule below); `retired` (= `deprecated`) is an operator decision, never automatic.
  - **Materiality gate on demotion.** In the executed hook a failing cell only counts toward
    demotion when it is capital-relevant: `standing_weight * |nearest CI bound| >
    alpha.decay.materiality_threshold` (0.005). Confluence-grain decay inherits the same gate so
    a near-zero-weight confluence's noise never churns lifecycle state.
  - **Regime-shift guard.** If >= `alpha.decay.regime_shift_fraction` (0.60) of active cells fail
    the same run simultaneously, the executed hook holds ALL transitions for that run rather than
    misread a market dislocation as mass feature decay. Per-confluence CUSUM/Brier monitoring
    needs the same population-level circuit breaker; without it, one dislocation demotes the
    whole confluence family at once.
- Retired confluences and their full occurrence history are **never deleted** — they are training
  data about how edges die, and candidate re-entrants if their regime returns.

## Silent Failure Modes (design against, up front)

- **Selection bias in the persisted estimate** — addressed by mandatory shrinkage (above); the
  single most likely way this system quietly lies to us.
- **Temporal clustering inflating N** — addressed by effective-N (above).
- **Analog index leakage** — AnalogEngine retrieval must be point-in-time: a live query may only
  retrieve analogs whose *outcomes were realized* before the query bar. Independently re-derived
  in `intel-13`'s substrate law; a confluence built on analog neighborhoods inherits this
  discipline, does not restate it.
- **Regime-scope creep** — a confluence firing outside its validated `regime_scope` must be
  recorded as `out_of_scope` occurrences (tracked, never counted toward its claims, useful as free
  OOS evidence for scope expansion).
- **Threshold drift** — the firing condition's bounds live in APR with provenance, recalibrated
  only through the gate stack, never hand-nudged because "it stopped firing."
- **A weak baseline masquerading as confluence lift** — addressed by the hard prerequisite above;
  the single most likely way *this specific gate* would silently lie.

## Dependencies

- **Phase 150** — supplies explicit interaction-term candidates (constituents + condition)
- **`intel-13` analog predictors** (formerly Phase 148-149) — supplies analog-neighborhood
  candidates via the return-distribution primitive, not the deleted Score Object
- **`feature-scoring-beyond-ic.md` §0b/0c** — hard prerequisite of gate 1 (see above), not just a
  shared upgrade path
- **Todo 030** — cost-hurdle floor for gate 5
- **Phase 143 (merged lifecycle phase, formerly 149B)** — lifecycle/demotion machinery, reused at
  confluence grain via Concept Registry. Shipped 2026-07-10 (`record_transition_sync`,
  `ic_engine` post-run lifecycle hook, `integrity_monitor`); this dependency is now met
- **The emission-layer live daemon** — scope once, system-wide, the first time anything is worth
  firing live; not a confluence-specific build item

## Open Questions

1. Shrinkage estimator specifics — empirical-Bayes toward the regime-cell baseline vs. out-of-fold
   mean; how the shrinkage weight maps to effective N. Needs a small study on Phase 150's first
   surviving interactions, not a whiteboard decision.
2. Combining simultaneous confluences on one bar into the continuous view — independent-evidence
   product/pooling vs. max-conviction vs. learned combiner; must not silently re-introduce the
   additive assumption gate 1 exists to escape. Default until studied: report the set, combine
   conservatively (min or shrunk pool), never sum.

## References

- `docs/plans/2026-07-01-regime-stratification-alternatives.md` — stratification dimensions; CI-width
  selection logic this design's calibration layer extends
- `docs/research/multi-engine-regime-architecture.md` — Partial IC validation protocol (gate 1's direct
  ancestor)
- `docs/research/intel-04-confluence-patterns.md` — pre-v3.0 confluence concept (I6, plugin-based)
- `docs/research/intel-case-substrate.md` (formerly `intel-13-analog-engine.md`, renamed with the
  AnalogEngine→CaseSubstrate rename, `1d41f1da`) — return-distribution primitive, definedness
  rules, analog point-in-time discipline (all inherited verbatim, not restated)
- `docs/research/measurement-ic-engine.md` (formerly `intel-15-measurement-engine.md`) — the shared
  kernel gate 1 lives in
- `docs/research/platform-unified-concept-registry.md` — lifecycle MVP, `baseline_metric` shrinkage,
  `decaying`-as-transition mapping
- `docs/plans/2026-06-29-feature-scoring-beyond-ic.md` §0b/0c — hard prerequisite of gate 1
- Todo `030-cost-hurdle-apr-calibration.md`
- `.planning/research/2026-07-03-intel10-11-fable-review.md` — this rewrite's source review
- ROADMAP.md Phase 150, Phase 143 (merged lifecycle phase, formerly 149B); Phase 142B SHADOW-REVIEW.md pre-commitment pattern (criteria
  defined before data is seen — the same discipline applies to every gate in this doc)
