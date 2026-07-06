# IntegrityMonitor — Drift, Decay, and Ensemble Health, Reconciled

**Version:** 1.0
**Status:** draft — rearchitected from a 10-doc cluster with real internal conflicts and dropped
substance, for independent iteration
**Priority:** high (Phase 151/143 (merged lifecycle phase)/152; live-safety gate as system nears real capital)
**Milestone:** proposed v4.1 IC Governance + Drift Monitoring (Phases 151, 143 (merged lifecycle phase), 152 — renumbered 2026-07-04, originally 149A/149B/150) — per
topdown doc D12, should be unhooked from "v4.1" framing and scheduled opportunistically once
its table dependencies exist, not held for a milestone boundary
**Last Updated:** 2026-07-02
**Tags:** drift, decay, promotion, demotion, shadow, ensemble-health, cusum, concept-registry
**Informed by:** Fable 5 - consolidation audit corrections (D3 framing, feature_registry transition semantics, live alpha_events schema), Phase 143 reconciliation, recommendation in § Open Questions, and design revisions marked *(Fable's revision)* inline (2026-07-02)
**Status note (2026-07-04, cluster review F9):** ROADMAP Phase 143 was rewritten 2026-07-03
*adopting this doc's own recommendations* — the merge is executed (cooldown rejected, D3 applied,
`pre_shadow_weight` in LIFECYCLE-01). Passages below that frame the two planned lifecycle builds
as an unreconciled conflict, or describe roadmap Phase 143 as still specifying a bespoke
`AlphaDecayMonitor`/`is_decaying` writer, are historical record of the state *before* that
rewrite, not a live conflict — do not "fix" it a second time.

---

## Why This Doc Exists

This cluster is not a case of scattered-with-no-hub like regime or AnalogEngine were — a
consolidation already happened (`docs/plans/archive/2026-06-27-health-guardian-design.md`, "IntegrityMonitor,"
explicitly replaces three earlier service-design docs into one service with three monitor
modules). The problem is different and, in a specific way, worse: **the consolidation itself
lost real content**, and its schema proposal has since been overruled by a decision (the
topdown review's D3) that nobody has yet applied back into the doc cluster. Reading all ten
source docs in full surfaced three concrete problems worth naming before any design decision:

1. **The consolidated ensemble-health design is less complete than its own predecessor.**
   `alpha-ensemble-lifecycle.md` (older) specs three independent conviction sub-tests —
   stability, calibration, distribution health. `health-guardian-design.md` (the doc that
   claims to replace it) keeps only stability. The other two aren't rejected with reasoning;
   they're just gone. They still exist, fully specced with APR keys, in the implementation-plan
   doc underneath (`2026-06-27-ensemble-lifecycle-implementation.md`) — the three-doc lineage
   disagrees with itself and nobody reconciled it.
2. **A genuinely useful technique got dropped in the same silent way.** v2.x had a working
   CUSUM (cumulative sum) change-detector on per-signal `pnl_r`. `2026-06-26-drift-detection-architecture.md`
   specs its v3.0 adaptation — CUSUM on ensemble IC instead, an early-warning mechanism that
   detects a *developing* degradation before it crosses a static threshold, which is
   structurally more sensitive than the threshold-only E1 gate that survived into
   `health-guardian-design.md`. It is absent from the "unified" design with no note that it was
   considered and cut.
3. **The proposed schema is already overruled — the ruling just hasn't been applied here.**
   `health-guardian-design.md`'s `ICLifecycleMonitor` proposes adding
   `is_shadowed`/`shadow_corpus_runs`/`pre_shadow_weight`/etc. directly onto `feature_ic_scores`
   and running its own promotion/demotion state machine there. Two things supersede that:
   `feature_registry.md` already ships this state machine in production (`candidate → active →
   shadow_only → deprecated`, `trigger_reason` enum, APR-backed demotion periods, 61 real rows,
   and `ensemble_trainer` already filtering on `feature_status_at_eval = 'active'`); and the
   topdown review's decision D3 adjudicated this exact design by name: *"drop
   `is_decaying`/`decay_detected_at`/`recovery_eligible_at` from `feature_ic_scores` design...
   move all lifecycle state to the registry... this also resolves the 149B rename (is_decaying
   → is_shadowed) by deletion."* So this is not a conflict nobody noticed; D3 is the fix, not
   yet propagated to this cluster. D3 enumerates the three legacy columns, but its principle
   (lifecycle state out of measurement tables) covers all five proposed shadow columns equally.
   It also covers the *other* planned build of the same state machine: roadmap **Phase 143**
   (LIFECYCLE-01..06) specs an `AlphaDecayMonitor` daemon writing `is_decaying` into
   `feature_ic_scores`, with a fourth, different recovery policy; D3 names that write too.
   Two planned lifecycle builds (Phase 143 and the then-separate 149B), one live registry, one
   ruling: the remaining work is applying the ruling and collapsing the duplication, not adding a
   table-local branch. (Historical: this merge is now executed — see status note at top.)

None of this is a reason to distrust the underlying ideas — the regime-conditioned KS windows,
the signed Wasserstein distance, the three-gate ensemble health check, evidence-based shadow
recovery over calendar cooldowns — all of that is genuinely good, Renaissance-grade thinking.
It needs reassembling correctly, not rebuilding.

---

## What's Solid and Survives Whole: Distribution Drift Detection

`DistributionDriftMonitor` (from `health-guardian-design.md`) is the one piece of this cluster
with no internal conflict and no dropped substance. Two real improvements over the original
(pre-consolidation) drift design, both worth keeping exactly as specced:

**Regime-conditioned reference windows.** A naive 29-day reference window fires false KS alerts
on every regime transition — RSI and ADX distributions naturally differ between trending and
ranging regimes, and that's correct behavior, not corruption. The fix determines majority HMM
regime in the current window from posteriors already in `feature_vectors`, then filters both
reference and current windows to the same regime before comparing. No new joins, no new tables.
*(This dimension-conditioning logic is itself a candidate `StratificationDimension` consumer
once `docs/ideas/intel-12-stratification-dimension.md` ships — the majority-regime query here
duplicates logic that a unified conditioning layer would centralize. Not a blocker; worth noting
for whoever builds this after intel-12 lands.)*

**Signed Wasserstein distance, not just the KS statistic.** KS tells you a distribution moved;
it doesn't tell you which direction. `scipy.stats.wasserstein_distance` is the same computational
cost (O(n log n)) and gives signed magnitude — positive means the current window shifted right
of reference, negative means left. Recorded alongside KS so that after 3-6 months of accumulated
history, direction-specific penalty learning becomes possible (a feature drifting toward a
*stronger* signal is a different event than one drifting toward noise, even though both fire a
KS alert today).

**One query for all features per window** — KS (continuous) and chi-squared (categorical)
features read from the same `feature_vectors` rows in one query per (symbol, tf) per window;
Python splits post-query. Halves DB load versus querying per-feature.

**Adaptive, magnitude-scaled penalty**, not a fixed step: `penalty = max(floor, 1.0 -
abs(wasserstein_signed) * scale)`, separate floors and scales for warning vs critical severity.
Recovery clears the penalty after `recovery_clean_tests_required` (default 2) consecutive clean
checks, piggybacked on the existing 4h check cycle — no second timer.

**Open, worth resolving before build:** whether the CUSUM-on-ensemble-IC technique below
(currently scoped to `EnsembleHealthMonitor`'s E1 gate) should *also* apply here as a
feature-distribution early-warning, or whether feature distributions are noisy enough at that
grain that a sequential change-detector would false-positive more than it helps. Untested
either way — flag, don't decide.

---

## What Needs Rearchitecting: Feature Lifecycle (Promotion/Demotion)

**The core correction: this is not a new subsystem to build. It is a routing decision.**
`feature_registry.md` already implements the exact state machine every source doc in this
cluster independently re-derives (`candidate → active → shadow_only → deprecated`, with
`trigger_reason ∈ {ic_promotion, ic_demotion, parent_cascade, operator_override}`), already in
production with 61 rows. [Concept Registry](platform-unified-concept-registry.md) is the
already-decided generalization of that same state machine across domains (`feature`,
`ensemble_strategy`, `regime_model`, ...). The consumer half already works end to end:
`ic_engine` stamps `feature_status_at_eval` from registry state on every IC score row, and
`ensemble_trainer` filters `WHERE feature_status_at_eval = 'active'` behind a crash-loud
startup alignment gate. The only missing piece in production is the **transition writer** -
something that evaluates each corpus run's results against the gate and flips registry status.
That, not a third bespoke set of columns on `feature_ic_scores`, is the whole remaining scope.

**One lifecycle build, not two** *(Fable's revision)*: roadmap Phase 143 (LIFECYCLE-01..06,
AlphaDecayMonitor) and the then-separate Phase 149B (ICLifecycleMonitor) were two planned
implementations of this same transition writer, drafted a day apart, never reconciled at the
time. Collapse them into one build — since executed: 149B was merged into Phase 143 2026-07-03
(see status note at top).
Phase 143 contributes three things this doc cluster lacks and should keep: LIFECYCLE-00
(regime-label validation, a prerequisite for anything regime-stratified), the LIFECYCLE-04
**regime-shift guard** (if ≥ `alpha.decay.regime_shift_fraction`, default 0.60, of active
feature-regime cells fail in the same run, classify as market regime shift and hold existing
weights rather than mass-zeroing - human review before any weight change), and IC staleness
alerting. health-guardian contributes evidence-based recovery and `pre_shadow_weight`. The
merged build routes all state through `feature_registry` per D3.

**Recovery policy: four designs, one verdict.**

| Design | Source | Recovery rule | Verdict |
|---|---|---|---|
| Pure cooldown | `feature-vector-lifecycle.md` (06-25) | 30-day cooldown, then one passing IC run promotes | Rejected: calendar gate blocks genuinely fast recovery for no statistical reason; single-run promotion flaps on noise |
| Cooldown + confirmation | `feature-ic-decay-implementation.md` (06-26) | 30-day cooldown, *then* 2 consecutive passing runs | Rejected: keeps the calendar gate that its own confirmation step makes redundant |
| Pure evidence | `health-guardian-design.md` (06-27) | No cooldown; 2 consecutive passing corpus runs promote | **Adopted**, with the floor below |
| Cooldown + evidence mass | Phase 143 LIFECYCLE-01 (roadmap) | Cooldown AND ≥ 2000 new independent observations | Rejected as stated (cooldown again), but its observation floor is the one idea the winner lacks |

*"A benched feature with a cooldown clock is a benched feature guessing. A benched feature in
shadow mode is a benched feature proving."* The confirmation requirement, not the cooldown, is
what prevents flapping on noisy IC measurements.

*(Fable's revision)* **Adopt pure evidence plus Phase 143's new-evidence floor:** promotion
requires 2 consecutive passing corpus runs AND ≥ `alpha.ic.decay_recovery_min_observations`
(default 2000) independent observations accumulated since demotion. Consecutive corpus runs
are not independent evidence - rebuilds run days apart on mostly-overlapping windows, so two
passes can double-count the same fluke. The run count guards against measurement noise; the
observation floor guards against evidence reuse. Neither alone does both jobs, and the floor
is evidence-denominated, not calendar-denominated, so it keeps the "no cooldown clock"
principle intact.

**Kept from the source designs, once routed:**

1. **`pre_shadow_weight` restoration on promotion.** The IC Sharpe value at the moment of
   demotion becomes the starting ensemble weight on the first post-promotion run - the feature
   earned that number once, confirmed recovery says it's back, no reason to make it re-earn
   weight from zero. Normal IC-based weighting takes over on subsequent runs. New column on
   whichever system owns the state machine (feature_registry today, Concept Registry later).
2. **Deprecation stays operator-confirmed, never automatic.** After
   `shadow_max_corpus_runs` (default 12) consecutive failing shadow runs, a feature becomes a
   *deprecation candidate* - an event, not an action. An operator confirms the actual
   deprecation. This prevents permanently excluding a feature that might recover in a regime it
   simply hasn't seen during its shadow window. Note this is a *change* to `feature_registry`'s
   current semantics, not a reuse: today the registry automates `active → deprecated` via
   `ic_demotion` after `alpha.feature_registry.demotion_periods` (default 3) failing evals.

**Registry amendments required** *(Fable's revision - this is the actual Phase 143 scope (merged
from the then-separate 149B) once routed, so the "routing decision" framing doesn't understate
it)*:

1. Redirect automated `ic_demotion` to target `shadow_only` instead of `deprecated`;
   `deprecated` becomes operator-only, closing the auto-deprecation path the registry
   currently allows.
2. Add the evidence-based `shadow_only → active` promotion transition - none exists today;
   `shadow_only` is currently an operator-entered dead end.
3. Add `pre_shadow_weight` and the shadow run counters (consecutive fails, consecutive passes,
   observations since demotion) as registry columns - they are lifecycle state, so they live
   with the status. All transitions land in `feature_transition_log` as today; add a nullable
   free-text `note` column there for the operator's deprecation reason.

**Who writes the transition - ICLifecycleMonitor dissolves** *(Fable's revision)*: no separate
monitor module, no corpus-complete Kafka subscription, no daily scan daemon. Lifecycle state
can only change when new IC measurements land, so the natural writer is a post-run step in
`ic_engine` calling `FeatureRegistryService`, the narrowly-scoped service method that
concept-governance's invariant 1 requires for status flips anyway. Phase 143's daily
AlphaDecayMonitor scan would re-read unchanged data six days out of seven (LIFECYCLE-05 itself
documents the 0-7 day staleness); the end-of-run hook gives identical detection latency with
no daemon and no event-vs-data-visibility race. The regime-shift guard runs in the same hook;
it needs exactly the per-run view the hook already has (fraction of cells newly failing). What
remains inside `integrity-monitor` under the `ic_lifecycle` monitor_type is observability
only: the hook writes a gate-evaluation fact row (which gates passed/failed, metric vs
threshold) so drift, lifecycle, and ensemble health stay queryable from one table, while the
authoritative transition record is `feature_transition_log`. IC staleness alerting, the one
job that needs a process running when ic_engine *doesn't*, piggybacks as a one-query check on
DistributionDriftMonitor's existing 4h cycle, not a module.

**What NOT to build:** any of the `is_shadowed`/`shadow_corpus_runs`/`shadow_confirmation_count`
columns as specced directly on `feature_ic_scores` - that table is a measurement fact store;
per D3, lifecycle decisions live in the registry that already owns them. *(Fable's revision)*
Also not the `feature_deprecations` table: registry `status = 'deprecated'` plus a
`feature_transition_log` row (`trigger_reason = 'operator_override'`, reason in the new `note`
column) already records exactly what that table would; a second operator-deprecation store is
the same state written twice.

---

## What Needs Restoring: Ensemble Health, in Full

`EnsembleHealthMonitor`'s three-gate structure (E1 ensemble IC, E2 conviction reliability, E3
feature coverage — AND logic, any failure halts or degrades emission) is the right shape and
should be kept. But the version in `health-guardian-design.md` is a lossy simplification of its
own predecessor docs. Restoring the dropped pieces:

### E1 — Ensemble IC Gate, with CUSUM restored as a staged early warning

The threshold check survives (`ic_sharpe_hac < floor` → halt or reduce). What's missing: v2.x
ran a CUSUM change-detector on per-signal `pnl_r` that worked and is a natural fit for
`alpha_ensemble_ic` in v3.0 — sequential cumulative-sum detection is structurally more sensitive
than a static floor because it accumulates small, consistent drift into an alert *before* any
single measurement crosses the threshold:

```
μ₀, σ₀ = mean/std of first 20 IC measurements per (symbol, tf, regime, lookahead), σ₀ clamped
x_n = (ic_mean[n] - μ₀) / σ₀
S+_n = max(0, S+_{n-1} + (x_n - k))     # detects improvement    k = 0.5σ allowance
S-_n = max(0, S-_{n-1} + (-x_n - k))    # detects degradation
Alert when S- > h (4.0σ warning, 8.0σ critical)
```

This is a real, previously-working mechanism that got dropped without a stated reason during
consolidation. *(Fable's revision)* Verdict rather than another open flag: **build it with
Phase 152, alert-only until it earns halt authority** - see Open Question 1 for the full
reasoning. Two explicit decisions from the source doc carry forward with it: **no automatic
re-baselining** after an alert (human investigation before reset; auto-reset masks recurring
degradation), and per-key arming at `alpha.drift.cusum_min_outcomes` (default 20) baseline
measurements; below that the detector is silently inert for that key, which is correct
behavior, not a gap.

### E2 — Conviction Reliability, all three sub-tests, not one

`health-guardian-design.md` kept only E2A (conviction stddev stability). E2B and E2C are fully
specced with concrete queries and APR keys in
`2026-06-27-ensemble-lifecycle-implementation.md` and answer genuinely different questions than
stability does:

- **E2A — Stability:** `STDDEV(conviction)` over trailing window. Answers: is the ensemble's
  output *consistent*? (kept, along with health-guardian's one genuine improvement here:
  the stddev is computed within the majority regime of the check window, since trending
  regimes legitimately produce higher variance and pooling inflates the baseline)
- **E2B — Calibration:** bucket `alpha_events` by conviction decile, check win rate is
  monotonically increasing across deciles. Answers: does higher conviction actually mean higher
  win rate, or is the conviction number decorative? A stable-but-uncalibrated ensemble passes
  E2A while being actively misleading about which trades to size up.
- **E2C — Distribution health:** convictions aren't collapsed to extremes (`low_conviction_pct
  < 0.6`, `high_conviction_pct > 0.1`, mean in a reasonable band). Answers: is the ensemble
  actually discriminating, or outputting the same number regardless of input? A collapsed
  distribution can be perfectly stable (E2A passes) and even accidentally calibrated (E2B
  passes on too little variance to fail) while carrying no real information.

Each answers a question the other two structurally cannot. Dropping E2B/E2C isn't a
simplification, it's a coverage gap — an ensemble can pass the surviving E2A alone while being
broken in exactly the ways E2B and E2C exist to catch.

*(Fable's revision)* **One correction before any E2 gate is built:** the queries in both
source docs were written against an assumed schema. Live `alpha_events` (Phase 142A) has no
`conviction` column (the emitted quantity is `alpha_score`, signed and unbounded) and no
`outcome_r`; realized outcomes will land in `alpha_frames` (Phase 142B). So E2A/E2C re-base on
`alpha_score`, and E2C's absolute bands (`< 0.2`, `> 0.8`, mean in 0.3-0.7) assume a bounded
[0,1] conviction; they must be re-derived from `alpha_score`'s empirical distribution (e.g.
percentile-based collapse checks) before they gate anything. E2B reads closed `alpha_frames`
rows and is buildable only once enough closed frames exist per (symbol, tf); it is the
last-arriving gate within Phase 152, not a blocker for the others. The three questions the
gates ask are unchanged; the columns they ask them of are not.

### E3 — Feature Coverage, unchanged

`COUNT(*) FILTER (WHERE active) < floor` per (symbol, tf, regime, lookahead). No conflict across
any source doc here; the only correction is what "active" means, and that filter already
exists in production form: `feature_status_at_eval = 'active'` on `feature_ic_scores`, stamped
by ic_engine from registry state at eval time. E3 counts those rows; no bespoke `is_shadowed`
column, no new join.

### Cascade reasoning and the retrain spec — restore both

`alpha-ensemble-lifecycle.md` worked through four concrete scenarios (single feature decay →
ensemble absorbs it silently; multi-feature cascade → still fine if coverage holds; systemic
collapse → all three gates fail together, halt and diagnose; ensemble IC decay *without* feature
decay → the one case that proves feature health and ensemble health are genuinely independent
questions, not two views of the same fact). Scenario 3's "diagnose before acting" step already
has an automated arm specced in roadmap Phase 143: the LIFECYCLE-04 regime-shift guard (hold
weights on mass simultaneous decay, human review before changes) belongs in the merged
lifecycle build above; the ensemble-health gates independently halt emission if ensemble IC
collapses, so held-weights-plus-halted-emission is the correct combined posture while a human
diagnoses. `health-guardian-design.md` has none of this
reasoning and treats `force_retrain` as `(future)` — unspecced. The predecessor doc already
specced what retraining actually does (refetch IC scores → recompute weights → re-run
walk-forward → re-run FDR → write new `alpha_ensemble_ic` baseline) and when it fires
(scheduled every 30 days, IC-driven on floor breach, or emergency within 24h if IC drops below
0.3). This is concrete, already-designed, and should not be re-derived — it should be copied
into whatever implementation plan actually gets built.

**One structural rule worth keeping from the predecessor:** no automatic `failed → active`
transition. After a retrain, state returns to `candidate` — gates must pass again before
resuming emission. A system that lets itself silently resume after fixing itself is one bad
retrain away from emitting on an ensemble nobody re-validated.

---

## Schema (reconciled)

**`integrity_monitor` hypertable** — kept as specced in `health-guardian-design.md`: one table,
discriminated by `monitor_type` (`distribution_drift` / `ic_lifecycle` / `ensemble_health`),
shared recovery-state and halt-state columns. This part of the consolidation was correct — one
service, one table, one recovery state machine, one action registry is the right shape.
*(Fable's revision)* One amendment: drop the lifecycle-transition columns
(`prior_state`/`new_state`/`trigger_reason`) from the schema. With lifecycle state routed
through the registry, `feature_transition_log` is the authoritative transition record;
`integrity_monitor`'s `ic_lifecycle` rows carry per-run gate-evaluation facts (metric vs
threshold, pass/fail), not a second copy of the state change. Everything recorded once.

**Not built as specced:** the `feature_ic_scores` schema additions (`is_shadowed`,
`shadow_corpus_runs`, `shadow_confirmation_count`, `shadow_recovery_confirmed_at`,
`pre_shadow_weight`) and the `is_decaying → is_shadowed` rename. Per D3, `feature_ic_scores`
stays a measurement fact store; the three legacy lifecycle columns
(`is_decaying`/`decay_detected_at`/`recovery_eligible_at`, still present and unread in the
live schema) get dropped, not renamed. Lifecycle columns belong on whichever registry owns
feature identity — `feature_registry` today, migrating to `concept_registry` per D9's build
trigger.

**`feature_deprecations`** — not built (see "What NOT to build" above): registry status plus
transition-log `note` column replaces it.

---

## Sequencing

Per topdown decision D12: Phase 151 (distribution drift, originally 149A) and Phase 143
(feature lifecycle routing, merged from the then-separate 149B) depend
only on tables that already exist (`feature_vectors`, `feature_ic_scores`, `feature_registry`)
and should not wait for a "v4.1" milestone boundary — they're startable independently today.
Phase 152 (ensemble health, originally 150) is the one genuinely gated dependency, requiring
`alpha_ensemble_ic` from Phase 142A, which is now complete — so it is unblocked as of this doc's
writing.

**Status (2026-07-04):** D9's Concept Registry build trigger has since fired (Phase 142B.1
complete) — see [Concept Registry](platform-unified-concept-registry.md)'s build-trigger section and todo
058. The registry is not yet built, so "if D9's build trigger has fired by then" below should be
read as "the registry may already be mid-build by the time this phase lands" (OQ3 below still
applies as the build-time routing check).

Recommended build order, correcting the original three-phase split:
1. **Phase 151 (originally 149A) — DistributionDriftMonitor**, as specced, no changes needed beyond what's above.
2. **Phase 143 (feature lifecycle routing, merged from the then-separate 149B)** *(Fable's revision)*:
   one build, not two. ic_engine's post-run hook detects promotion/demotion trigger conditions
   and writes transitions through `feature_registry` (or `concept_registry` if D9's build
   trigger has fired by then): the registry amendments listed above, plus Phase 143's
   LIFECYCLE-00 regime-label validation, regime-shift guard, and staleness alerting. No new
   columns on `feature_ic_scores`, no AlphaDecayMonitor daemon, no ICLifecycleMonitor module.
3. **Phase 152 (originally 150) — EnsembleHealthMonitor**, with E2B/E2C restored (re-based on the live schema:
   `alpha_score`, `alpha_frames`; see E2 section) and CUSUM built alert-only per Open
   Question 1. Within the phase, E2B lands last; it needs closed `alpha_frames` rows that
   only start accumulating once Phase 142B ships.

---

## Open Questions

1. **CUSUM for ensemble IC — build now or explicitly defer?** *(Fable's revision - resolved
   with a recommendation rather than left open, since the grounds exist.)* **Build it with
   Phase 152, alert-only, staged authority.** Reasoning: (a) the mechanism is proven, it ran
   in v2.x on per-signal pnl_r; (b) it is nearly free at build time, the accumulator runs over
   the same `alpha_ensemble_ic` rows E1 already fetches, so it is a small pure function, not a
   new data path; (c) the real gate is data, not code: each key needs
   `alpha.drift.cusum_min_outcomes = 20` baseline measurements, and `alpha_ensemble_ic` accrues
   one per corpus run per (symbol, tf, regime, lookahead), so most keys will arm months after
   Phase 152 ships regardless of when the code is written. Deferring the build gains nothing;
   building it now means it self-arms per key as history accumulates. Authority is staged and
   falsifiable: alerts only (no halt) until its first real alerts have been human-reviewed for
   precision; grant halt authority per the same operator-confirmed path every other gate uses.
   Keep the v2.x parameters (k = 0.5σ, h = 4.0σ, h_critical = 8.0σ) as APR seeds and the
   no-automatic-re-baselining rule.
2. **Does regime-conditioning in `DistributionDriftMonitor` get rebuilt once intel-12 ships, or
   is the current inline majority-regime query fine to keep as a special case?** Leaning toward
   "migrate once intel-12's contract exists, not worth blocking Phase 151 (originally 149A) on it
   now" — but that's a sequencing call, not a technical one.
3. **Timing of the feature_registry → concept_registry migration relative to Phase 143 (merged
   from the then-separate 149B).** **Status (2026-07-04):** D9's build trigger has fired
   (Phase 142B.1 complete) but Concept Registry itself is not yet built (todo 058, pending). If
   Phase 143 ships before the registry is actually built, it should route through
   `feature_registry` as-is and migrate later for free (per D9's reasoning: the migration window
   is cheap now precisely because so little depends on the current shape yet). If the registry
   has already been built by the time Phase 143 ships, skip `feature_registry` entirely and route
   there directly. Not a design question, just an ordering one to check at build time — the
   trigger having fired doesn't resolve it, since firing and building are different events.

---

## References

- `docs/plans/archive/2026-06-27-health-guardian-design.md` — the existing consolidation; correct on
  service architecture, incomplete on ensemble health, its feature-lifecycle schema overruled
  by D3. Kept for its DistributionDriftMonitor spec and the shared `integrity_monitor` schema.
- `docs/ideas/archive/data-integrity-monitor-design.md`, `docs/ideas/archive/system-health-monitor-design.md`,
  `docs/ideas/archive/predictive-decay-detector-design.md` — already correctly marked SUPERSEDED,
  pointing at health-guardian-design.md. `predictive-decay-detector-design.md`'s core insight
  ("name the service after the problem, not the metric" — decay detection generic across
  IC/Sharpe/R²/calibration) was the right instinct and is exactly what Concept Registry later
  became; no separate service needed to realize it now.
- `docs/plans/archive/2026-06-26-drift-detection-architecture.md` — source of the CUSUM-on-ensemble-IC
  technique, dropped from the consolidation without documented reasoning.
- `docs/plans/archive/2026-06-26-feature-distribution-drift-detection.md` — KS/chi-squared detail,
  fully absorbed into health-guardian's DistributionDriftMonitor already.
- `docs/plans/archive/2026-06-26-feature-ic-decay-implementation.md` — the cooldown+confirmation hybrid
  recovery design, superseded by the adopted recovery policy above; its `is_pooled`
  handling and prior-row LAG-comparison implementation notes for ic_engine remain useful detail.
- `docs/plans/archive/2026-06-27-ensemble-lifecycle-implementation.md` — source of the E2B/E2C
  restoration above; the actual implementation-ready spec for gates health-guardian-design.md
  dropped.
- `docs/ideas/archive/feature-vector-lifecycle.md` — original cooldown-based recovery design (superseded
  by evidence-based recovery above); correctly identified the promotion/demotion gap, incorrectly
  solved the recovery-timing question.
- `docs/ideas/archive/alpha-ensemble-lifecycle.md` — source of the cascade-scenario reasoning and the
  concrete retrain-process spec, both dropped from health-guardian-design.md without restatement.
- `docs/ideas/feature-registry.md` — the already-production state machine feature lifecycle
  should route through, not duplicate.
- [Concept Registry](platform-unified-concept-registry.md) — the eventual generalization target (D9); its
  invariant 1 (only a deterministic, narrowly-scoped code path flips status) shapes the
  transition-writer position above.
- `.planning/research/2026-07-02-v3-topdown-architecture.md` — D3 (lifecycle state out of
  measurement tables), D9 (Concept Registry MVP), D12 (149A/149B/150, renumbered 2026-07-04 to 151/143 (merged)/152, unhooked from v4.1 framing)
- `.planning/ROADMAP.md` Phase 143 (Feature Vector Lifecycle + Alpha Decay Infrastructure),
  the phase the then-separate 149B was merged into (executed 2026-07-03); source of the
  regime-shift guard, the new-evidence recovery floor, LIFECYCLE-00, and IC staleness alerting
- `docs/ideas/intel-12-stratification-dimension.md` — regime-conditioning overlap noted above
  in the DistributionDriftMonitor section
