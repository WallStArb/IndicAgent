# AlphaEmitter - Stage 4 Emission Mechanisms

**Status:** Idea - not planned
**Author:** Fable 5 (dispatched via Claude Code Agent tool)
**Date:** 2026-07-07
**Priority:** medium (one high-value item inside: threshold calibration, an already-admitted gap)
**Milestone:** unscheduled; every empirical item below is gated on `alpha_events` having real rows again (corpus rebuild + EIC-04 re-run)
**Tags:** emission, alpha-events, threshold, stage-4, calibration, cross-sectional, hysteresis

**Companion to:** `docs/intelligence/intelligence-layer-architecture.md` (Stage 4 is the only
stage whose summary table says "not currently questioned" - this doc is the questioning),
`docs/intelligence/intelligence-alphaengine-methodology.md` § Emission Threshold, and
`docs/research/trade-construction-layer.md` (the layer immediately downstream; the interface
between them is settled here, the sizing mechanics are not).

---

## The Core Idea

Stage 4 (Emission) is the one pipeline stage with no design doc proposing alternatives. Stages
1-3 each have their mechanism named, questioned, and (for Stage 3) already multi-mechanism with
an A/B judgment harness. Stage 4 has a single mechanism nobody has re-derived from first
principles since Phase 139 shipped it.

Having now re-derived it against live code and data, the honest headline is: **threshold
crossing is structurally fine.** The gate composition is sound, direction-aware, and
APR-backed. The real Stage 4 gaps are narrower and cheaper than a mechanism replacement:

1. The threshold values are admitted guesses - the methodology doc itself says "researcher
   estimates, not empirically derived" and the calibration sweep it promises was never built.
2. The CI gate does less than the architecture doc claims - it is a second stratum-constant
   threshold, not per-bar statistical confidence (§ Finding F1).
3. Emission has zero visibility into weight staleness - an event fired from 90-day-old weights
   is indistinguishable from one fired the day after training.
4. The architecture doc's one-line summary of Stage 4 is wrong in three particulars (§ Doc
   drift).

This doc proposes an `emission gate stack` as the swappable unit (the Stage 3 `weight_method`
pattern adapted to a stage whose mechanisms compose rather than substitute), four concrete
candidates with falsification criteria, and three things explicitly not worth building.

---

## What Stage 4 Actually Is Today (verified against code and DB, 2026-07-07)

**Code:** `services/alpha_publisher.py` (`AlphaPublisher`, `BaseBatch` oneshot,
`compute_version 1.0.0`). Reads `ensemble_alpha` for one `weight_version`, applies four gates,
writes `alpha_events` (composite PK `(event_id, bar_ts)`,
`event_id = content_key(symbol, tf, bar_ts_ns, ensemble_version, weight_version)`), publishes
to Kafka `alpha.events`. Shadow mode: no execution, no sizing.

**The gate stack, in evaluation order** (gates 1-3 run in SQL, gate 4 in Python):

| # | Gate | Granularity | APR key(s) | Live value |
|---|---|---|---|---|
| 1 | `effective_n >= gate` | stratum (tf, regime) | `alpha.ensemble.effective_n_gate` | 3.0 |
| 2 | `ABS(alpha_score) > threshold` | **per TF only** | `alpha.quant.threshold.{tf}` | 5m=1.5, 15m=1.2, 1h=1.0, 1d=0.8 |
| 3 | direction-aware CI + cost: long `alpha_ci_lower > hurdle`, short `alpha_ci_upper < -hurdle` | per bar (but see F1) | `alpha.quant.cost_hurdle.{tf}` | all 0.0 |
| 4 | `top_features` non-empty for the (tf, regime) stratum | stratum | - | - |

**Doc drift** (three corrections to `intelligence-layer-architecture.md`'s Stage 4 line and
`intelligence-alphaengine.md`, worth fixing at next touch):

- The architecture doc says `threshold[symbol][tf][regime]`. The real threshold is per TF
  only - no symbol or regime granularity exists in code or APR.
- The architecture doc says the gate is `ci_lower > 0`. The real gate is direction-aware with
  a cost hurdle (short events gate on `ci_upper < -hurdle`), plus the effective_n and
  top_features gates it doesn't mention.
- `intelligence-alphaengine.md` names the APR key `alpha.threshold.<regime>` and an
  `alpha_events.feature_contributions` JSONB; the real key family is
  `alpha.quant.threshold.{tf}` and the real column is `top_features`.

**Empirical state:** `alpha_events` has **0 rows** (truncated in the 3rd corpus rebuild;
emission hasn't re-run since, pending XLC/SHY backfill and the EIC-04 re-run). Every
event-rate, flapping, and threshold-sensitivity question in this doc is therefore currently
unanswerable from data. That constrains this doc's shape: measurements are pre-registered here,
not asserted, in the same spirit as todo 026's pre-committed decision gates.

---

## Two Structural Findings

### F1 - The CI gate is a stratum-constant second threshold, not per-bar confidence

`ensemble_trainer.py` computes the CI analytically:
`margin = 1.96 * sqrt(sum(w_f^2 * sigma_f^2))` where `sigma_f` comes from each feature's IC CI
width. Every term is a property of the **(tf, regime) stratum**, not of the bar. So
`alpha_ci_lower = alpha_score - margin` with `margin` constant across all bars in the stratum,
and gate 3 (long) reduces exactly to `alpha_score > cost_hurdle + margin[tf][regime]`.

Consequence: per bar, today's entire emission decision is a **single effective threshold**,
`max(threshold_tf, margin[tf][regime] + hurdle_tf)`, applied to `alpha_score` - gates 1 and 4
only admit or exclude whole strata. The architecture doc's phrase "statistically confident
enough to act on" overstates this: no bar is ever more or less confident than its stratum
neighbors. Two honest responses exist and EM-CAL below picks one:

- **Simplify (Musk step 3):** acknowledge the effective threshold and calibrate it directly.
  The CI gate's real function is to make the threshold regime-sensitive through `margin`;
  calibration can do that explicitly and legibly.
- **Make CI per-bar informative:** widen the margin for bars with degraded feature coverage
  (NULL features force rank imputation upstream). Real but unproven value; not proposed here -
  it earns consideration only if EM-CAL's sweep shows the stratum-constant margin is binding
  in a way that costs measurable return.

### F2 - `ensemble_alpha` is the conviction surface; `alpha_events` is a frozen filter of it

Every scored bar, above threshold or not, is persisted in `ensemble_alpha` with score and CI.
Nothing below threshold is lost - the "never drop data that could contain signal" principle is
already satisfied one table upstream. `alpha_events` is a materialized, frozen-at-emission-time
view whose reason to exist as a table (rather than a query) is the Canonical Simulator's
frozen-claim contract: FRAME-01 freezes geometry off the emitted event, and an event's gates,
threshold, and weight epoch must be immutable facts about what the system believed at emission
time, not re-derivable opinions.

This settles the "continuous vs. discrete emission" question cleanly - see § Rejected R1.

---

## The Contract, and the Swappable Unit

**Contract (unchanged):** per-bar composite score + CI in → discrete, timestamped, direction-
stamped, fully-auditable tradeable event out. Consumers: Canonical Simulator (frozen claims),
Phase 142B frames, future Trade Construction Layer (as trigger stream, not as conviction
source - see § Interfaces).

**Swappable unit:** Stage 3's `weight_method` is an exclusive choice - exactly one weighting
mechanism produces the score. Stage 4 is different in kind: gates **compose** (AND-chain), so
the swappable unit is the **gate stack**, not a single enum. Proposed as an APR behavioral
list (APR mandate category 2):

```
alpha.emission.gates = ["effective_n", "abs_threshold", "ci_cost_directional", "top_features_nonempty"]
```

seeded to exactly the incumbent stack (provenance `[conventional]`, byte-for-byte behavior
preserved), loaded via `json.loads(cfg.get_sync(key, default_json))` in `AlphaPublisher`. Each
candidate below is one named gate (or one calibration job) that enters this list only after
clearing its falsification test - the same "mechanism swappable, contract fixed" shape as
Stage 3, adapted to composition. An A/B judgment between two stacks is a re-run of
`alpha_publisher` with a different list against the same `ensemble_alpha` epoch, scored on OOS
executable forward returns - no new harness needed beyond the EM-CAL sweep script.

---

## Proposals

Ordered by recommended build priority. Each states mechanism, schema/code delta, APR keys,
and the result that would kill it.

### EM-CAL - Empirical threshold calibration (build first; this is the admitted gap)

**Mechanism:** sweep the effective emission threshold over the persisted conviction surface.
For each (tf, regime) stratum: join `ensemble_alpha` × `forward_returns`
(`return_type = 'executable_open_to_open'` only, OOS window only, per OOS-EVAL-PROTOCOL),
compute net-of-cost mean executable forward return per event and event count N as a function
of threshold, using todo-030-calibrated cost floors. Select the threshold maximizing net
return per event subject to `N >= alpha.emission.min_events_per_stratum` (new APR key,
`[initial_estimate]`; a stratum below the floor keeps its per-TF parent threshold rather than
getting its own overfit one). Write results back to APR through the normal lifecycle
(`seed → ml_learned`, `config_history` reason = sweep run ID).

**Regime granularity is the sweep's question to answer, not this doc's:** per-(tf, regime)
thresholds are admitted only where the sweep shows the optimal threshold differs across
regimes by more than the CI of the estimate; otherwise the per-TF threshold stands. This is
also the principled resolution of the doc-drift item - the architecture doc's
`threshold[symbol][tf][regime]` becomes true only for the granularity that earns it.

**Schema/code:** none on `alpha_events`. New ops script
`scripts/ops/alpha/ops_emission_threshold_sweep.py` (mirroring the
`ops_ensemble_weight_compare.py` precedent - an ops-script judgment harness, promoted to a
`BaseBatch` oneshot only if run cadence ever proves it). APR: existing
`alpha.quant.threshold.{tf}` values become `ml_learned`; new `alpha.quant.threshold.{tf}.{regime}`
rows only for strata that pass the granularity test; new `alpha.emission.min_events_per_stratum`.

**Falsified if:** the sweep surface is flat - net-of-cost return per event insensitive
(within bootstrap CI) to threshold across the plausible range in every stratum. That result
would say threshold *value* doesn't matter given the CI/cost gates, the seeds stay, and the
sweep script is retired to a one-time-audit artifact. Also falsified per-stratum if the swept
optimum does not beat the seed OOS.

### EM-STAMP - Weight-age stamping (decay awareness, additive, near-zero cost)

**Problem:** emission fires on whatever `weight_version` is current with no record of how
stale that epoch's training window is relative to `bar_ts`. In corpus batch mode this is
benign (one epoch, `weight_version` inside `event_id` already gives epoch identity). In live
operation it is a silent-bias channel: the designed-but-unbuilt Alpha Decay Protocol re-solves
weights on decay, but between re-solves - or during a LIFECYCLE-04 regime-shift hold, which
deliberately freezes weights - events keep firing on aging weights with nothing on the event
saying so.

**Mechanism, two steps with separate burdens:**
1. **Stamp (build with the next migration that touches `alpha_events`):** nullable column
   `alpha_events.weight_computed_at timestamptz` copied from `ensemble_weights.computed_at`
   for the emitting stratum (already in the publisher's preloaded weights cache; one field
   added to the SELECT). Age is derived at query time (derived values are APR-exempt). This
   makes "does per-event forward return decay with weight age" a measurable question forever
   after, at the cost of one column.
2. **Gate (do not build yet):** `alpha.emission.max_weight_age_days` refusing or flagging
   emission past an age ceiling - only if step 1's measurement shows a real decay curve.

**Falsified if:** with sufficient live-mode N, regression of per-event OOS executable forward
return on weight age shows no negative slope at p<0.05 (controlling for tf and regime). Then
the gate idea dies and the stamp remains as cheap provenance.

### EM-RANK - Cross-sectional rank gate (real case, deliberately gated on T3)

**The question:** today every (symbol, tf) emits against an absolute bar in isolation. A
Renaissance-shaped alternative asks "is this symbol's score extreme *relative to the universe
right now*" - and the Trade Construction Layer's own analysis argues the 80-ETF universe is a
relative-value universe (effective breadth ~8-15), where ranking is what monetizes.

**Mechanism:** a composable gate, not a replacement: at each (bar_ts, tf), rank `alpha_score`
across all symbols scored at that bar (within validated `regime_scope`); the gate passes only
events in the top/bottom `alpha.emission.rank_gate_quantile`, and only when at least
`alpha.emission.rank_gate_min_universe` symbols were scored at that bar_ts (a rank over 6
stragglers is noise). Stamp `alpha_events.cross_rank_pct` (nullable) so rank context is a
frozen fact on the event either way - the stamp is worth building even if the gate never is.

**What it needs from Stage 3:** nothing new mechanically - `ensemble_alpha` already scores
every symbol per bar. What it needs *epistemically* is the Cross-Sectional Rank IC addendum
(`measurement-ic-engine.md`) clearing first: if cross-sectional rank IC is not measurably
better than pooled time-series IC on this universe (edge thesis T3), a rank gate at emission
is decoration.

**Boundary honesty:** ranking is also step 2 of the Trade Construction Layer's design. The
division that keeps the DAG clean: EM-RANK decides *whether a discrete event exists* (Stage 4's
contract); construction decides *how a portfolio is built from conviction* (and reads the full
`ensemble_alpha` surface for that, per § Interfaces). If the construction layer ships its
cross-sectional long-short v1, EM-RANK becomes largely redundant for that track and should be
re-justified for the per-symbol directional track alone before surviving. Sequencing verdict:
**do not build before the T3 falsification measurement runs**; the stamp (`cross_rank_pct`)
may ride any earlier migration.

**Falsified if:** on the OOS window, the rank-gated event set's net-of-cost long-short spread
does not beat the absolute-threshold event set's at matched event count - or if the T3
addendum itself fails (cross-sectional rank IC ≤ pooled), which kills it upstream without a
build.

### EM-HYST - Hysteresis / debounce (pre-register the measurement; probably don't build)

**The worry:** a score oscillating around the threshold emits a flapping event train, and if
downstream ever treats consecutive events as separate trades, flapping is pure turnover cost.

**Empirical status: hypothetical.** `alpha_events` is empty; there is no event train to
measure. Whether flapping is real depends on the autocorrelation of `alpha_score` near the
threshold, which nobody has looked at. Building enter/exit dual thresholds against an
unmeasured problem is the exact anti-pattern the 5-Step mandate exists to stop.

**Pre-registered measurement (commit to this now, run on the first post-rebuild emission):**
- *Flap rate:* fraction of events whose same-(symbol, tf) predecessor is within K bars with
  the same direction (re-fire), and fraction with opposite direction within K bars
  (direction flap), K = the stratum's `hold_max_bars` from Phase 142A.
- *Decision bar, pre-committed:* if direction-flap fraction < 5% and re-fire fraction < 20%
  in every tf, hysteresis is dead - close the question and record the numbers here. Above
  those bars, scope the mechanism: `alpha.emission.exit_threshold_frac` (exit level as a
  fraction of the enter threshold) and/or `alpha.emission.min_gap_bars`, as composable gates.
- Note: Phase 142B's frames already impose hold semantics *after* emission; measure flapping
  against frame behavior, not in isolation, before concluding it costs anything.

**Falsified if (built):** the debounced event set does not beat the raw set on net-of-cost
OOS return after counting the turnover the debounce saved - i.e., the events hysteresis
suppresses were not actually the money-losing ones.

---

## Explicitly Rejected (restraint is the deliverable here)

**R1 - Continuous/graded emission as a new mechanism.** The intuition ("emit a strength
score, not a boolean, so sizing has more to work with") is already ~90% satisfied: every
emitted event carries `alpha_score`, both CI bounds, `effective_n`, and `top_features` - the
event is boolean only in *existence*, not in content. And the below-threshold information a
continuous stream would add is already persisted in `ensemble_alpha` (Finding F2). Building a
continuous emission channel would duplicate Stage 3's output table under a new name. What the
downstream sizing layer actually needs is calibration of the conviction surface into return
units (`feature-scoring-beyond-ic` 0c), which is Stage 2/3 work, not emission work.

**R2 - Cross-TF confirmation gate.** Requiring (say) 1h agreement before a 5m event fires is
researcher-defined confluence - precisely the I6 epistemology v3.0 was built to delete ("the
researcher produces features, the data discovers confluence, the IC engine arbitrates"). If
cross-TF agreement carries information, the system must *discover* that: the correct home is a
Stage 0 feature (e.g., coarser-TF alpha or momentum context as a feature column, which the
cross-TF machinery already partially provides) whose IC is then measured and weighted like
everything else. One cheap diagnostic query is worth pre-registering, not a gate: stratify
emitted events' OOS forward returns by same-symbol coarser-TF `ensemble_alpha` sign agreement;
if separation appears, that is evidence for a *feature*, and still not for a hard-coded veto.

**R3 - Per-symbol thresholds.** The architecture doc's `threshold[symbol][tf][regime]`
notation imagines granularity that would be ~80 × 4 × 6 tunable cells - an overfitting surface
with no plausible N to calibrate most cells, violating the same N-budget logic that gates
stratification dimensions. Symbol-level heterogeneity that matters (vol scale) is already
normalized away by within-symbol rank normalization upstream. Reject unless a specific,
measured cross-symbol miscalibration is ever demonstrated at the (tf, regime) level first.

---

## Interfaces (fixed by this doc, so downstream designs can rely on them)

- **Canonical Simulator:** consumes `alpha_events` as frozen claims. Every proposal above is
  additive-nullable on the schema and preserves `event_id` semantics (any gate-stack change
  that alters *which* events exist rides a new `weight_version`/`ensemble_version`, so
  replayed epochs never silently mix gate regimes). Gate-stack composition is stamped per
  event implicitly via `emission_threshold`, `cost_hurdle`, and (new) `cross_rank_pct` /
  `weight_computed_at` - the frozen claim stays self-describing.
- **Trade Construction Layer:** two distinct feeds, and conflating them is the error to avoid.
  The *trigger stream* for the per-symbol directional track is `alpha_events`. The *conviction
  surface* for cross-sectional construction is `ensemble_alpha` (all symbols, all bars,
  calibrated by 0c when that ships) - construction must NOT be built to reconstruct universe
  rankings from `alpha_events`, which censors everything below threshold by design.
- **Stage 3:** no new requirements. EM-RANK consumes what `ensemble_trainer` already writes.

---

## Sequencing

1. **Nothing before `alpha_events` has real rows** - i.e., after XLC/SHY backfill completes,
   EIC-04 re-runs, and the emission pipeline produces a post-rebuild event set.
2. **EM-CAL first** (highest value, already-admitted gap, needs only the sweep script and the
   existing todo-030 cost floors). The E1/E2 weight A/B judgment shares its OOS window; run
   EM-CAL after a weight winner is promoted so thresholds calibrate against the surviving
   `weight_method`, not a superseded one.
3. **EM-STAMP columns** (`weight_computed_at`, optionally `cross_rank_pct`) ride whatever
   migration next touches `alpha_events` - stamps before gates, always.
4. **EM-HYST measurement** runs as a query against the first post-rebuild event set; its
   pre-committed decision bar then closes or scopes the mechanism.
5. **EM-RANK** waits for the T3 / Cross-Sectional Rank IC addendum verdict and re-justifies
   itself against whatever the Trade Construction Layer has become by then.
6. The `alpha.emission.gates` APR list can be introduced with EM-CAL's PR (seeded to the
   incumbent stack, behavior-preserving) so later gates are config, not code forks.

This respects the roadmap's priority frame: Core Alpha Pipeline OOS proof is gate #1 and none
of this blocks or accelerates it; EM-CAL is the only item that plausibly *helps* it (a
calibrated threshold makes the shadow event set more representative of what would trade).

---

## What This Doc Does NOT Resolve

- **Cost-hurdle values.** `alpha.quant.cost_hurdle.{tf}` live at 0.0; whether todo 030's
  calibration outputs were meant to land there or remain query-side floors is a bookkeeping
  question for the EM-CAL PR, not settled here.
- **Whether the analytic (stratum-constant) CI should become per-bar** (Finding F1's second
  branch). Deferred until EM-CAL's sweep shows whether the constant margin is costing anything.
- **Live-mode emission cadence.** Today's publisher is a corpus-mode oneshot; the hot-path
  `BaseAlphaEmitter` daemon (Phase C in `intelligence-alphaengine.md`) doesn't exist yet. All
  proposals here are cadence-agnostic (they gate on stratum/bar facts, not on batch identity),
  but the daemon design should re-read this doc when Phase C is scoped.
- **The doc-drift fixes** to `intelligence-layer-architecture.md` and
  `intelligence-alphaengine.md` (§ What Stage 4 Actually Is Today) - flagged for the next
  touch of those files, not silently patched by this one.

---

## References

- `services/alpha_publisher.py` - the incumbent mechanism (gate SQL at lines 216-247, CI/cost
  gate semantics in the module docstring)
- `services/ensemble_trainer.py` - analytic CI construction (`margin`, ~line 772), the basis
  of Finding F1
- `docs/intelligence/intelligence-layer-architecture.md` - Stage 4 contract; the "not
  currently questioned" row this doc answers
- `docs/intelligence/intelligence-alphaengine-methodology.md` § Emission Threshold - the
  "researcher estimates, not empirically derived" admission EM-CAL closes
- `docs/research/platform-canonical-simulator.md` - frozen-claim contract constraining every
  schema change here
- `docs/research/trade-construction-layer.md` - downstream consumer; § Interfaces fixes the
  trigger-stream vs. conviction-surface split
- `docs/research/measurement-ic-engine.md` - Cross-Sectional Rank IC addendum (EM-RANK's
  upstream gate, thesis T3)
- `docs/plans/OOS-EVAL-PROTOCOL.md` - every falsification test above runs under it
- `.planning/todos/pending/030-cost-hurdle-apr-calibration.md` - cost floors feeding EM-CAL's
  net-of-cost objective
- `docs/foundation/adaptive-parameter-registry.md` - APR conventions for the proposed keys
  (`alpha.emission.*` behavioral list is mandate category 2)
