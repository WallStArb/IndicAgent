# Phase 144 Conditioning Decision - Fallback for Weak-Separation Asset Classes (2026-07-07)

**Author:** Fable 5 (dispatched via Claude Code Agent tool)

**What this is:** the operator decision the ROADMAP v3.15 build trigger requires before
intel-12's substitution test runs - a SHADOW-REVIEW-style pre-commitment of the fallback
mechanism for asset classes where the per-symbol HMM shows weak or inverted IC separation
(topdown Open Q4; `docs/research/stratification-dimension-unification.md` Open Question 1). TLT is the
evidence case. Decided against the pre-142.5 corpus, deliberately before the in-flight corpus
rerun produces new numbers that could bias the choice.

---

## 1. Executive Summary

1. **Decision: option (b), adopted as the pre-committed default.** Any `regime_group` whose
   per-symbol HMM labels land in the deficient band of the widened Step 1 protocol (gap < 0.01,
   per-symbol queries only, one representative per enabled group) has its HMM demoted to shadow
   for that group: labels still written to `feature_vectors.regime`, still measured every
   ic_engine epoch, but no longer used as a conditioning axis for that group's IC stratification,
   ensemble eligibility, or (critically) AnalogEngine retrieval filters. The group stratifies on
   its own cross-sectional `regime_group` label instead, plus `volatility_pct` if and when that
   candidate passes its own substitution gate. Demotion is reversible through the same
   substitution test as any candidate.
2. **Option (c), the factor-augmented HMM variant, is pre-registered as the challenger for
   rates specifically** - not the default. Its build trigger is defined in §4 (F2), not left to
   be invented after the data arrives.
3. **Option (a), per-asset-class HMM observation vectors, is rejected as a default** and only
   re-enters if the widened Step 1 shows a systematic (multi-group) failure pattern (§4, F4).
4. **Phase 144 is unblocked for `/gsd-discuss-phase`.** This doc is the missing operator
   decision. Verified today: migration 189 unapplied (`market_regimes` still has `asset_class`),
   plan doc complete, todo 041 gates only commodity/fx group *enablement* (those groups ship
   disabled) and does not block the phase. Three planning inputs to carry in are listed in §6.
5. **All 2026-07-02 Step 1/Step 2 magnitudes are stale and must be re-measured** on the fresh
   corpus before any demotion executes (§5: synthetic-bar filter fix `26efb75b`, 91 new 142.5
   primitives, full-depth backfill). The *mechanism* is locked now; the *per-class verdicts*
   come from the post-rerun widened Step 1. That separation is the whole point of pre-committing.

---

## 2. Why the decision has to be made now

The corpus pipeline is mid-rerun as of this writing (verified live: `ops_corpus_pipeline_run.sh`
running since 17:00, `ic_engine.py --training-window-end 2025-12-24` active). When it completes,
`feature_ic_scores` will carry fresh regime-IC separation numbers computed over the expanded
142.5 feature set and the synthetic-bar-filtered cross-sectional labels. This is the last moment
the fallback choice can be made without those numbers in view. SHADOW-REVIEW discipline exists
precisely so the result cannot pick its own remediation; the same rule that governed 142B's
promotion criteria applies here.

## 3. The decision and the reasoning chain

**Adopt (b): demote to shadow per weak `regime_group`, stratify on cross-sectional +
`volatility_pct`.**

**3.1 The evidence shape rules out "fix the HMM" as a default.** TLT's Step 1 result is not
weak-but-correctly-signed separation (which would fit the parameter-look-ahead story that
rolling refit, todo 026 P4a, targets). It is *inverted*: trending_up IC 0.0064 vs trending_down
0.0097, gap -0.003. Todo 026's own root-cause note concludes bond regime dynamics
(mean-reversion around curve shape) may simply not fit a generic 5-state trend HMM built for
equity-style trending - a model-class mismatch, not a fit-window artifact. Both (a) and (c)
presuppose a specific root cause ((a): wrong observation features; (c): missing exogenous
factors) that no experiment has yet isolated. (b) presupposes nothing: it stops conditioning on
a label that failed the separation test and lets the challengers compete through the standard
gate.

**3.2 Deletion before construction.** The 5-step mandate says delete before you build. (a) and
(c) are builds layered on an undiagnosed failure; (b) is the delete. It is also the only option
executable at Phase 144 time with zero new modeling code - the demotion is a governance state
change plus an ic_engine routing consequence, both of which v3.15 is building anyway.

**3.3 Demotion is nearly free in the live path - verified, not assumed.** `ensemble_trainer.py`
trains exclusively on cross-sectional POOLED strata (`WHERE symbol = 'POOLED' AND is_pooled =
true AND regime != '_pooled'` - lines 317, 430-432, 469, 540). Per-symbol HMM labels feed
per-symbol diagnostic IC strata only. Shadowing them for rates changes no live weight today. The
consumer this decision actually protects is AnalogEngine's future retrieval hard-filter (Phase
148), where a failed stratum would be baked into stored embeddings. Cheap now, expensive to be
wrong about later: exactly the case for the conservative option.

**3.4 Renaissance data retention holds.** Shadow means written and measured, not dropped. The
labels keep accumulating alongside `hmm_churn` (Phase 143's new continuous instability score),
so the re-promotion case can be made from data that never stopped being collected.

**3.5 N-discipline, per the crypto precedent.** The 2026-07-07 crypto-into-fx decision is the
template: N=1 instrument does not justify a dedicated regime signal module. The weak-separation
evidence today is one symbol (TLT) standing for one class (rates). Building a dedicated
per-asset-class HMM mechanism, or a factor-augmented variant, on one confirmed-weak symbol is
the same over-mechanization the crypto call rejected. Demote-to-shadow costs nothing; a
dedicated mechanism costs a build plus permanent audit surface on a model family whose one
production instance still has open audit items (P1b, P2a, P4a).

**3.6 (b) generalizes into the rule v3.15 exists to build.** Under the per-`regime_group`
promotion model in `stratification-dimension-unification.md` §Governance, a dimension live for `equity`
and shadow for `rates` is a normal state. Choosing (b) as the fallback means the fallback *is*
the governance rule's output, not a special case bolted alongside it. Choosing (a) or (c) as
the default would pre-empt the substitution-test machinery before it exists.

**3.7 What Phase 144's `rates` group changes - and what it doesn't.** It makes TLT's clean
comparison *possible* for the first time (per-symbol HMM vs a same-asset-class cross-sectional
label instead of the contaminated equity comparison), and it gives (b) its replacement
substrate: without a valid rates label, demotion would leave rates with no conditioning at all.
It is also (c)'s structural prerequisite (`_resolve_group_symbols` peer resolution). But it does
not adjudicate between the options - the curve_credit label is a new hypothesis with its own
burden of proof (§4, F2), not a presumed winner. Phase 144 shipping strengthens (b)'s
viability; it does not change which option is right.

## 4. Pre-committed falsifiers and exit conditions

The decision is only as good as its exit conditions. These are locked with the decision:

- **F1 - the demotion premise fails.** If the post-rerun widened Step 1 (fresh corpus, 142.5
  features, per-symbol queries, todo 026's bands: gap < 0.01 deficient, 0.01-0.05 ambiguous)
  shows the rates representative with gap >= 0.01 and correct sign, rates is not a
  weak-separation class and no demotion happens. The 2026-07-02 numbers do not execute the
  demotion by themselves; they justified pre-committing the mechanism, nothing more.
- **F2 - (b) leaves a class unconditioned; (c)'s build trigger.** If, after Phase 144 ships,
  the `rates` cross-sectional label *itself* fails TLT's per-symbol separation test (gap < 0.01
  on the pre-registered comparison), and `volatility_pct` has not passed its substitution gate
  for rates, then (b) has left rates with no valid conditioning axis. That state - not
  operator preference - is the build trigger for (c), the factor-augmented variant, as the
  pre-registered challenger.
- **F3 - re-promotion path.** If (c) (or any candidate, including a future per-class HMM
  refit) passes the substitution test for rates (>= 10% IC Sharpe improvement in at least one
  joint cell, N > 20,000 bars in that cell), it becomes the rates conditioning axis through the
  normal promotion machinery. Nothing in this decision privileges the shadow status.
- **F4 - the failure turns out systematic, not per-class.** If the widened Step 1 puts the
  representatives of half or more of the enabled regime_groups in the deficient band, the
  per-class demotion frame is wrong - that pattern is evidence for a shared observation-vector
  mismatch, and (a) reopens as the leading hypothesis. Per-class shadow demotion is the right
  shape for isolated failures, the wrong shape for a global one.
- **F5 - the model-class-mismatch diagnosis is wrong.** If P4a's rolling-refit pilot ever
  clears its own 4-condition gate and shows TLT's sign un-inverting under a causal fit window,
  the mean-reversion-mismatch story was wrong and the look-ahead story was right; re-run the
  rates Step 1 before acting further on this decision.

## 5. What changed since 2026-07-03 and its bearing

Checked via git log and live process state; none of it changes which option wins, and two items
strengthen the case for locking the mechanism now:

- **`26efb75b` (2026-07-05): zero-volume synthetic bars filtered from cross-sectional regime
  queries.** The Step 2 "cross-sectional separates 1.4x wider than HMM for SPY" magnitude was
  computed on pre-fix labels and is stale; direction likely stands, number does not. Re-measure
  on the fresh corpus; do not quote 1.4x again.
- **Phase 142.5 (shipped 2026-07-07): 91 new Renaissance primitives; corpus rerun in-flight.**
  All regime-IC separation numbers will be superseded when the rerun completes - the pre-commit
  window is closing, which is why this doc exists today. Sequencing consequence: Phase 144's
  batched ic_engine re-run (roadmap D5) must queue behind the in-flight rerun, never run
  concurrently with it (single-writer discipline on derived tables).
- **Depth backfill closed (2026-07-07): all 80 symbols at full real depth.** The widened Step 1
  protocol (one representative per enabled regime_group) is data-feasible for the first time.
- **`c67dbc07` (2026-07-07): crypto lumped into fx; idiosyncratic/systematic vocabulary.**
  Supplies the N-discipline template used in §3.5.
- **Phase 143 LIFECYCLE-00 (2026-07-06): occupation-fraction gate + `hmm_churn`.** Hardens the
  incumbent's internals and gives shadow-mode HMM labels an extra continuous score to keep
  measuring; does not touch the TLT separation evidence.

## 6. Is Phase 144 unblocked?

**Yes - `/gsd-discuss-phase` can start now.** The build trigger's required operator decision is
this document. Verified: migration 189 unapplied (`\d market_regimes` still shows
`asset_class`), the implementation plan (`docs/plans/2026-07-01-cross-sectional-regime-model.md`)
is complete and current, and todo 041 gates commodity/fx group *enablement* only - those groups
ship `enabled: false`, so 041 batches into the same v3.15 re-run without blocking the phase.

Three inputs Phase 144 planning must carry:

1. **Pre-register the rates comparison and the widened Step 1 protocol into todo 026 now**,
   per `stratification-dimension-unification.md` Open Questions 2 and 4: TLT vs the `rates` group label,
   same per-symbol query shape as SPY's Step 2(c); one most-liquid representative per enabled
   regime_group; todo 026's existing bands; per-class verdict table, never a global verdict.
   Committing the queries and thresholds before Phase 144 makes them runnable costs nothing.
2. **Sequencing: the batched ic_engine re-run waits for the in-flight 142.5 corpus rerun to
   complete.** Planning and code execution (migration, signal modules, dispatcher, routing) can
   proceed in parallel with the rerun; only the re-measurement step queues.
3. **The concept_registry row-grain question** (one row per (dimension, regime_group), per the
   2026-07-04 cluster review F2 provisional) is presupposed directionally by this decision -
   shadow-for-rates/live-for-equity needs per-scope status somewhere. Decide it for real at
   v3.15 planning as already flagged; this doc does not settle it.

## 7. Corrections to existing docs

- **ROADMAP.md v3.15 build-trigger paragraph:** the pending operator decision is resolved;
  short dated note appended pointing here (this session).
- **todo 026:** decision note appended pointing here, plus the caveat that the 2026-07-02
  Step 1/Step 2 magnitudes are stale (synthetic-bar fix + 142.5 feature set + depth backfill)
  and the widened Step 1 must re-run on the fresh corpus before any demotion executes.
- **`docs/research/stratification-dimension-unification.md` Open Question 1:** its recommendation is hereby
  ratified as written (it recommended (b) with (c) as queued challenger). No edit made in this
  session; fold a "ratified 2026-07-07" pointer in during the v3.15 planning pass that already
  owns that doc.
