---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: blocked
stopped_at: Phase 171 context gathered
last_updated: "2026-08-08T06:16:08.935Z"
progress:
  total_phases: 12
  completed_phases: 9
  total_plans: 45
  completed_plans: 44
  percent: 75
---

# Project State

## Strategic Plan (fork RESOLVED 2026-08-07 -- read this before anything else in this file)

**RESOLVED: Phase 167's cross-sectional construction does NOT survive re-measurement under the
corrected join. Both Validation Gates FAIL, authoritative-tier, real production path.** The
2026-08-05 execution plan (`docs/plans/2026-08-05-ctf-join-fix-scoped-recompute-and-gate1-reverify.md`)
ran to completion 2026-08-06/07: (1) surgical `feature_vectors` UPDATE for the 80-equity/15m scope
verified correct (0 rows would change on re-check); (2) `ic_engine.py --refresh` (needed for todo
256's ensemble-eligibility check, NOT a Gate 1/2 dependency -- `cross_sectional_spread_tracker.py`
reads `feature_vectors`/`forward_returns` directly, confirmed via grep, zero references to
`feature_ic_scores`); (3) `construction_spreads` TRUNCATEd and rebuilt via `--backfill` from the
corrected values (its `ON CONFLICT DO NOTHING` write meant a bare re-run without truncating first
would have silently measured stale leaked-join data -- caught before it happened); (4) Gate 1/Gate
2 re-run through the real production path, `null_shuffles` raised 40->1000 for the run-once look,
new gate_id suffix `ctf_join_v2` (governance reasoning: bug found independent of the gate's prior
result, fix shipped before that result was recorded, the prior PASS measured known-corrupted
data -- all 3 conditions from `OOS-EVAL-PROTOCOL.md`'s Cadence section satisfied).

**Real numbers, OOS window, 3,803 bars / 147 day-clusters:**

- **Gate 1** (`gate1_ctf_momentum_decile_ls_ctf_join_v2`, `gate1_passes=False`): fast scale
  `ci_lower=-0.000141` (doesn't clear zero), `null_p=0.649`; slow scale `ci_lower=-0.000486`,
  `null_p=0.986` (observed spread beaten by 98.6% of random-ranking draws). Both scales fail both
  criteria.

- **Gate 2** (`gate2_ctf_momentum_decile_ls_ctf_join_v2`, `gate2_passes_overall=False`): after
  removing the static-tilt benchmark, no residual survives at 95% CI at either scale
  (`residual_ci_lower` -0.0000706 fast / -0.000354 slow).

This confirms both prior diagnostic-tier measurements (SPY single-symbol pilot, the earlier
diagnostic-tier cross-sectional reverify) at full authoritative tier -- not a new finding, a
confirmation with real governance weight. `nonlinear_interaction_combiner`'s original
"substantial" edge claim and Phase 167's "COMPLETE, both Validation Gates PASSED" verdict are both
retracted; the small residual `nonlinear_interaction_combiner` still shows is a separate,
already-tracked thread (see `docs/research/measurement-nonlinear-interaction-combiner.md`), not
resurrected by this result.

**Fork resolution (branch was decided in advance specifically so this didn't need
re-litigating):** **FAIL branch -- back to discovery, not construction.** Priority becomes the
five untested Signal-Extraction candidates (`cointegrated_pairs_residual`,
`statistical_factor_residual`, `cross_asset_lead_lag`, `adaptive_combiner_weights`,
`jump_diffusion_decomposition`) and `nonlinear_interaction_combiner`'s N1 residual-form test (the
recommended next design once the tree's structural mismatch to this corpus -- no per-feature
exposure cap -- is accounted for). Phase 168 (cost-hurdle spread refinement, direct Phase 167
follow-on) and Phase 156-159 (execution/sizing/kill-switch) stay blocked -- not "unverified"
anymore, actually FAILED; do not start either without a new, independently-proven construction
first. Converges on the same already-stated project principle either way: prove edge before
production infra, never the reverse.

**Still open, lower priority, not blocking the fork's resolution:** todo 256's ensemble-eligibility
re-check against fresh `feature_ic_scores` once `ic_engine.py --refresh` (launched 2026-08-06,
still running as of this writing -- genuinely expensive: 2000-resample circular block bootstrap CI
per cell, correctness-motivated re-ranking-every-iteration per `ic_engine.py`'s own docstring, not
a performance bug) finishes. `docs/research/data-edge-source-thesis.md` and todo 247 need their
stale "substantial at 1h/15m" claims corrected to this real FAIL result.

**Corpus-hygiene backlog (todo 250 hypertable, todo 252 fingerprint-deletion-no-archive) is real
but lower-urgency and can be picked up opportunistically without blocking the main line.**

**Expectation to hold, not a consolation-prize framing:** every "large" edge found in this corpus
so far has collapsed 44-91% once a leak was corrected, with a small real residual surviving each
time. If that pattern holds, real edge here is probably small (single-digit-bps scale), not a
headline number -- consistent with Renaissance's own actual history. The win condition for this
milestone is a confirmed small edge with a clean gate record, not a big trade.

**HMM issue status (asked 2026-08-04): fix built and TDD-tested, NOT deployed.**
`_walk_forward_hmm_labels`/`_seed_prior_from_label`/`_hmm_seed_stability_check` exist in
`regime_writer.py` (todo 248) with 6 passing unit tests, but zero call sites reference
`_walk_forward_hmm_labels` from the live path -- `_compute_symbol_tf` still does the full-history
fit. Confirmed by direct grep 2026-08-04, not assumed. Phase 171 (wire it in) exists in ROADMAP.md
as a stub with 0 plans, explicitly sequenced behind this Strategic Plan's step 3 to avoid two
overlapping corpus-recompute-scale efforts running at once.

**Phase 170 (feature_registry -> Concept Registry migration) is running in a separate, concurrent
session as of 2026-08-04 -- do not touch `feature_registry`/`concept_registry` files, migrations,
or ROADMAP.md's Phase 170 section from this thread of work.** Independent subsystem, no expected
file overlap with the Strategic Plan above.

---

## Project Reference

See: .planning/PROJECT.md

**Core value:** Alpha must be demonstrated empirically before any ensemble weight is assigned.

**Guiding lens (Renaissance / Musk, per CLAUDE.md's north star):** every claim in this section
must be empirically demonstrated, not assumed -- cross_sectional_relative_value below earned its place by clearing a
shuffled-ranking-null guard, not by a plausible story. Before building anything, apply Musk's
5-step mandate: question whether the requirement is real, delete before adding, simplify,
accelerate, automate -- in that order. **Corrected 2026-08-03 -- this sentence used to lump
Phase 164/165 in with Phase 151 as "deprioritized, expensive, unproven"; that's stale. Phase
164/165 were deprioritized behind Phase 167 on 2026-07-26, then the user explicitly overrode
that call the next day (Tier 0) and both executed to COMPLETE by 2026-07-28, columns already
backfilled and live in the corpus (see Phase Summary table).** Phase 151 alone remains planned
but not executed, still deliberately behind Phase 167: don't accelerate feature-expansion work
that hasn't been shown to be the actual bottleneck.

**Current focus (updated 2026-08-08):** Milestone v3.1's defining verdict stands: Phase 148 found
Gate 1 (signal proof) PASS but Gate 2 (execution proof) FAIL -- do not promote the per-symbol
directional construction to live capital. **New thread, 2026-08-08: user wants to refine this
per-symbol construction using Phase 163-165's features (Phase 164 in particular measured as the
best-performing feature vintage in the corpus, 72.2% FDR clear rate).** A rigor review before
any gate work found 3 gating items, all filed as P1 todos: [276](../todos/pending/276-phase163-165-lookahead-causal-safety-audit.md)
(Phase 163-165 have never been audited for the same lookahead-leak bug class that hit
`ctf_momentum` and `regime_writer`'s HMM fit, twice already), [277](../todos/pending/277-alpha-score-concentration-cofiring-degeneracy-diagnosis.md)
(Gate 2's ~22-concurrent/99.5%-same-direction co-firing pattern suggests `alpha_score` may be a
disguised single-factor bet, not real per-symbol breadth -- diagnose before refining features
that feed the same combination), [278](../todos/pending/278-oos-protocol-gate-relook-decision-phase163-165-features.md)
(checked against `docs/plans/OOS-EVAL-PROTOCOL.md`'s own 3-condition re-look exception -- fails
2 of 3 as scoped; a bare Gate 1/Gate 2 re-run would be an ungoverned second look at an
already-3x-used OOS holdout). **Do not jump straight to a gate re-run** -- 276/277 are
read-only/diagnostic-tier and can run in parallel now; 278 needs an explicit decision recorded
before any authoritative gate consumes another look. Phase 167 (Cross-Sectional Trade Construction,
`cross_sectional_relative_value`) was recorded 2026-07-27 as COMPLETE, both live Validation Gates
PASSED, but that verdict did not survive re-measurement under the corrected `ctf_momentum` join --
**re-verified at authoritative tier 2026-08-07, both gates now FAIL** (see the Strategic Plan
section at the top of this file for real numbers). Do not cite Phase 167 as a proven result and do
not start Phase 168 -- this is now a settled FAIL, not a pending re-verification.

Which tf Phase 167 should trade at is now moot given the FAIL verdict above -- `_TF="15m"` was
inherited from the original falsification script, never comparatively tested against 5m, and
there's no live construction left to trade at any tf (todo 235 accordingly deprioritized).
`regime_conditional_persistence` is CONFIRMED DEAD (270 cells tested, zero pass on live corrected
labels). `nonlinear_interaction_combiner` has a small real residual surviving the CTF-leak
correction at all three affected tfs, not the "substantial" edge originally published -- collapse
90.6%/79.1%/43.8% at 1h/15m/5m respectively, with the surviving residual growing as tf gets finer
even as collapse % shrinks (leak magnitude is roughly bounded by HTF bar duration; total
predictive power grows at finer granularity). Full numbers:
[CTF leak status](project_ctf_momentum_leak_and_nonlinear_combiner_status.md) in memory. Five new
Signal-Extraction candidates (`cointegrated_pairs_residual`, `statistical_factor_residual`,
`cross_asset_lead_lag`, `adaptive_combiner_weights`, `jump_diffusion_decomposition`) remain
untested -- now the actual priority per the resolved fork above. Full detail on all theses:
`docs/research/data-edge-source-thesis.md` (still needs its stale "substantial at 1h/15m" CTF
claim corrected to the real FAIL result -- todo 247, unblocked, not yet executed). Phase
144/143.1/162/163/164/165/167 are all COMPLETE -- see Phase Summary table below.

**CTF join-fix investigation (todos 241/243/245/253/256) -- RESOLVED 2026-08-07, authoritative
tier, both gates FAIL.** Full narrative in
[project_ctf_momentum_leak_and_nonlinear_combiner_status.md](project_ctf_momentum_leak_and_nonlinear_combiner_status.md)
and each todo file, not restated here; real numbers are in the Strategic Plan section at the top
of this file. Todo 256's ensemble-eligibility re-check against fresh `feature_ic_scores` is the
only piece still open (gated on `ic_engine.py --refresh` finishing, in progress -- not a Gate 1/2
dependency). `docs/research/measurement-nonlinear-interaction-combiner.md` has a structural
critique of the tree estimator (no per-feature exposure cap) plus two pre-registered follow-on
test designs (N1/N2), not yet run -- N1 (residual-form) is the recommended next move.

**New, separate thread the same night: `regime_writer.py`'s per-symbol HMM has a real
parameter-level lookahead bug, confirmed, fixed, tested, and measured to NOT help (todos 026/248)
-- do not wire the fix into production.** `_compute_symbol_tf` fits its `GaussianHMM`'s
parameters once on the ENTIRE (symbol, tf) history before causally decoding -- the decode is
clean, the model doing the deciding was not. Tracked since 2026-06-28 as todo 026's P4a, gated on
a "validate the practical impact first" test that was never run until tonight. **Confirmed real
and large at 3 symbol/tfs**: production (full-fit) vs an expanding-window-refit labeling agree
only 24.9% of the time at SPY/1h (chance baseline 21.7%), 31.0% at TLT/1h (chance 20.6%), 56.8%
at SPY/15m (chance 22.1%) -- tracks bar-density-per-refit-window, not a uniform "regime labels
are unreliable" finding. **The real fix was implemented and TDD-tested**:
`_walk_forward_hmm_labels()`/`_seed_prior_from_label()`/`_hmm_seed_stability_check()` landed in
`regime_writer.py` (belief continuity across refit boundaries via the ending regime *label*,
mapped through each new model's own `_build_label_map` -- not raw state-index carryover, not a
reset to a fresh stationary prior), 6 new tests, full `tests/unit/` suite green, ruff/black clean.
**Deliberately NOT wired into `_compute_symbol_tf` or the live `--refit` path** -- per the
project's own "prove it before shipping it" discipline. **The actual Gate 4 measurement then ran
and FAILED**: SPY/1h ordinal-regime-score IC (the 5 labels have a natural order, mapped to
{-2..2}), walk-forward vs production, paired bootstrap diff=-0.0130, CI [-0.0276,0.0013] crosses
zero; walk-forward's own IC is significantly *negative* (-0.0171), wrong sign. **The instability
finding stands (real, causal-violation-grounded); the "fixing it improves predictions" claim does
not, on this test.** Real caveat, not yet resolved: this pilot tests regime as a standalone
predictor, stricter than todo 026's original ask (per-feature regime-*stratified* IC, which is
how `feature_ic_scores`/`ensemble_trainer` actually use `feature_vectors.regime` -- a
conditioning variable, not a direct predictor) -- the corpus-wide, per-feature version has never
been run; whether it's worth running given tonight's negative first read is an open call. **Decision
corrected 2026-08-04: user directive is to wire the fix into production regardless of the Gate 4
ordinal-IC result -- this is a confirmed causal-law violation in an existing core mechanism, not a
new/unproven signal subject to "prove before promoting."** Blast radius matches an
`HMM_RANDOM_STATE` change (full regime + downstream `ic_engine` recompute); **sequencing decided
2026-08-04: queued behind the CTF-leak/Phase 167 re-verification work**, scope as its own phase via
`/gsd-discuss-phase` once that clears. Full
detail: `.planning/todos/pending/248-hmm-full-history-fit-regime-label-instability-gate4-pilot.md`,
`docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md`.

Also this session: todo 172's item 2 (frame_gate_passes cluster-mean non-determinism) FIXED;
item 1 (broader path-dependent-statistics sweep) remains open, unscoped. Todo 218 (BIL thin-cell
IC instability) root-caused via direct peer comparison (SHY/IEF) and closed -- deliberately not
fixed, folded as corroborating evidence into todo 099 whenever that gets real design attention.
Todo 157 (base-class compliance mechanical check) fully closed. Full detail, all cross-refs:
`.planning/todos/PRIORITIES.md`'s 2026-08-03 status-sync entry.

**2026-07-30 thread (compressed 2026-08-03 -- reconciliation/merge detail dropped, git log has
it):** the per-tf-active-scale-set fix (migration 271) and todo 208's same-ET-session gate fix
(`complete_{scale}` now means "the forward bar exists" at every tf; migration 272;
`forward_returns` rebuilt clean) both landed, triggering the corpus pipeline relaunch whose
outcome is recorded authoritatively in Tier -1 below -- not restated here. `_SCALES`-hardcoding
cleanup: todos 209/210/211/212 CLOSED; todo 214 (the duplicated-compute-logic root cause) still
open, deliberately deferred until this chain is stable through a full cycle. Todo 146's per-tf
lookahead grid (migration 269): session-boundedness premise resolved, actual VALUES still open
pending `ops_lookahead_horizon_response.py` characterization + real measurement -- design doc:
`docs/research/2026-07-30-forward-return-horizon-grid-refactor.md`. Todo 203 (canary RNG
pseudo-replication) fixed; todo 204 status is in Tier -1 below (don't restate here).

**Next actions, priority order:**

*Tier 0.5 -- outranks Tier 1: execute the scoped recompute plan.* `ctf_momentum` batch-join
lookahead bias (todos 243/245/256) -- full current status in the Strategic Plan section above,
not restated here. The recompute/re-verification plan is written and ready
(`docs/plans/2026-08-05-ctf-join-fix-scoped-recompute-and-gate1-reverify.md`); only the
user go-ahead to execute it remains.

*Tier 1 -- decision point, REDIRECTED 2026-07-27 by explicit user instruction:* Phase 156-159
(execution/sizing) is NOT the priority even though its precondition is cleared. User wants the
features/regimes/IC/ensemble signal-generation stack validated first ("real proven signals")
before any execution-layer investment. Do not resume Phase 156-159 scoping without the user
re-raising it.

*Tier 2 -- serves the redirected priority:* todo 234 CLOSED 2026-08-03 -- nonlinear_interaction_combiner's 15m result
substantial at the tf that's actually tradeable, **but see Tier 0.5/Strategic Plan: that read needs
re-confirming once the corpus recompute lands (1d re-run is safe now, 1h/15m/5m wait).** todo
235 (cross_sectional_relative_value-at-5m, never comparatively tested against 15m for this
construction); the open `alpha_ensemble_ic`/`alpha_events` question (is the linear-only combiner
adequate -- confirmed `ensemble_trainer.py`'s `resolve_stratum_weights` is linear combination
only; `alpha_events` confirmed sparse/emission-gated, not a dense ranking input; not yet
investigated further). Phase 151 is the next-tier option if these don't pan out.

*Tier 2b -- concretely staged, waiting on Tier -1's pipeline to exit:* todo 167 (equity
cross-sectional-vs-symbol-HMM stratification falsifier, never tested unlike rates'). Migration
262 applied (`dual_write_symbol_hmm=true` for equity), falsifier gate script written and
verified (`scripts/analysis/equity_regime_separation_gate.py`, generalized from Phase 144's D-05
gate). **The in-flight `ic_engine` run (Tier -1) is a full, unscoped pass -- check whether it
already covers the 49 equity symbols this todo needs before assuming a second scoped run is
still required once it completes.**

*Tier 3 -- ready now, independent of the pipeline:* todo 009 Parts B/C (Parts A/D closed
2026-07-31 -- promote 4 scripts to `BaseBatch`+systemd, naming-vocab doc update, still open).
Todos 172/173 (non-blocking Phase 148 findings) also live here, lower urgency.

*Tier 4 -- deprioritized, do not resume without re-reading why:* Phase 151 (Feature Primitives
Expansion, planned and ready but not the next priority -- see Guiding lens above), Phase 145
(StratificationDimension Formalization, unblocked but not planned), todo 175 (structural
candidate Part 2 -- exists only to serve an overridden plan, see todo 179).

*Tier 0 -- CLOSED 2026-07-29:* the combined `backfill_feature_factory.py --compute-only
--refresh` pass landed Phase 164/165's 77 new columns and Phase 163's deferred VP/SR historical
backfill (todo 176). Its regime-wipe side effect (todo 205) and the resulting repair pipeline
are ALSO fully closed as of 2026-07-30 -- not the pipeline currently running (see Tier -1).

*Tier -1 -- CORRECTED 2026-08-08 (was stale "HALTED"): this tier actually CLEARED same-day,
2026-08-02.* the corpus pipeline relaunched 2026-07-30 from step 3 (`forward_return_writer`)
reached `ic_engine` (step 5/8) run_complete at **2026-08-02 19:19:25 UTC** -- 81/81 symbols,
2,924,007 `feature_ic_scores` rows, zero error-level log lines, FDR backfill already complete
(`passes_fdr` non-NULL on every row), elapsed ~70.2h. Clean on its own terms. The wrapper
script's next gate, `ops_canary_integrity_assert.py`, FATAL-halted before steps 6-8
(`ic_shrinkage`/`ensemble_trainer`/`alpha_publisher`) ran. Two findings from that gate, both
filed and both CLOSED: **todo 204** (positive control `canary_acausal_placebo` now clears
correctly, 231/239 cells -- confirms the gate itself works and the prior failure was a
stale-vintage artifact) and **todo 230** (3 negative-control canaries falsely cleared the gate,
8/717 cell-tests ≈1.1%) -- **resolved properly the same day, not overridden.** Root-caused to
two things: (1) the gate applied a Binomial tail-bound tolerance to per-symbol clears but was
hard-zero-tolerance on POOLED clears specifically (confirmed deliberate per
`methodology-change-ledger.md` E7, not an accidental gap); (2) traced the 8 cells anyway and
found genuine regime-conditional signal concentrating BH-FDR's budgeted false-discovery rate
into those exact cells (expected behavior of a correctly-functioning corpus-wide FDR
procedure, not a corpus artifact) -- `breadth_vol.py`'s regime construction re-verified fully
causal. Fix: extended the Binomial tolerance to POOLED with a stricter `pooled_tail_alpha`,
documented as a dated E7 addendum. **Confirmed via `logs/corpus_pipeline/step_timings.jsonl`:
steps 6-8 ran to completion same day** -- `ic_shrinkage` done 20:42:44 UTC (E1 gate PASSED),
`ensemble_trainer` done 20:54:43 UTC (190 `ensemble_weights` rows/25 strata), `alpha_publisher`
done 21:19:49 UTC (~30M `ensemble_alpha` rows, 8,855,505 `alpha_events` emitted). Corpus-write
work has been safe to start again since 2026-08-04 (confirmed independently in
[[project_corpus_pipeline_state]] memory) -- **this Tier -1 entry sat stale for 6 days citing a
halt that had already cleared; if STATE.md's own "supersedes every tier below" framing is ever
trusted again, re-verify against `step_timings.jsonl` directly first, don't take the prose at
face value.**

**Parallel to this run, 2026-08-02 (pure code/docs, no corpus dependency):** todo 216 (BLAS
thread oversubscription across all 5 `ProcessPoolExecutor` batch services) CLOSED, migration
281 -- not yet confirmed at production scale, self-confirms on the next full pipeline run since
it landed after this run's `regime_writer` step. Reviewing that fix surfaced todo 229 (a
separate, deeper bug: hmmlearn's `monitor_.converged` is unconditionally `True` post-fit,
making `regime_writer.py`'s same-seed convergence retry structurally unreachable since it
shipped) -- design proven, implementation deferred pending this run's own convergence-iteration
log data. Todo 005 (regime-label transition IC contamination) got a measurement-first design
doc after an Opus review + rewrite corrected its own motivating statistic (measured on the
wrong population initially). See `docs/research/intelligence-lifecycle-backlog-matrix.md`'s
Operational Context section for full detail on both threads, not duplicated here.

A same-day partial-data check (safe, read-only, ran alongside the live pipeline) had found
`ctf_momentum` at 15m holding up on the first 21 symbols computed under that corpus (872 cells,
91.4% positive sign, 63% passing the bootstrap CI gate, mean IC 0.0527) and read it as early
reinforcement of Phase 167. **Re-read now that todo 243's fix landed: that reinforcement does not
survive.** Those values came from the pre-fix leaky join; the SPY single-symbol pilot under the
fixed join at 15m found point_ic collapses to +0.0047 (CI [-0.0007,0.0100], not significant) --
consistent with the leak, not genuine signal, being what that partial check saw.

*Tier 5 -- gate status changed 2026-07-27, re-opened 2026-08-04, RESOLVED 2026-08-07:* Phase
156-159 (Portfolio State/Sizing/Execution/Cost) was gated on Phase 167 producing a proven signal --
recorded as cleared when Phase 167's both Validation Gates PASSED. **That clearance is now
formally revoked, not just suspended** -- the corrected-join re-verification (see Strategic Plan
above) shows both gates FAIL at authoritative tier. Phase 156-159 stays gated; it needs an
independently-proven construction, not a re-earned Phase 167. Phase 149/150/155 (PrecedentEngine, Alt Data) -- v4.0-adjacent, no case made yet.
Phase 147 (I7 due diligence) -- cheap, gates nothing.

Full P2/P3 todo backlog: `.planning/todos/PRIORITIES.md`. Idea-level scoring:
`docs/research/intelligence-lifecycle-backlog-matrix.md`.

**Execution plan:** `docs/plans/archive/2026-06-30-alphaengine-v1-execution-plan.md`

## v3.0 Phase Summary (SHIPPED 2026-06-25)

| Phase | Name | Status |
|-------|------|--------|
| 137 | Feature Factory | COMPLETE (7/7 plans, 2026-06-21) |
| 138 | IC Engine + Forward Returns | COMPLETE (9/9 plans, 2026-06-23) |
| 139 | Ensemble + Alpha Emission | COMPLETE (3/3 plans, 2026-06-24; 14/14 verification truths) |
| 140 | IC Engine Correctness | COMPLETE (4/4 plans, 2026-06-25) |

## v3.1 Phase Summary (IN PROGRESS)

| Phase | Name | Status |
|-------|------|--------|
| 140.5 | Corpus Foundations + Feature Governance | COMPLETE (5/5 plans) |
| 141 | Corpus Quality Gate + IC Validation | COMPLETE (3/3 plans) |
| 141.1 | Measurement and Decision Integrity Foundation | COMPLETE (4/4 plans) |
| 142A | Ensemble IC Measurement | COMPLETE (2/2 plans) -- EIC-04 current verdict PASS 54/1425=3.79%, see [Corpus pipeline state](project_corpus_pipeline_state.md) for the live number |
| 142B.1 | Ensemble Weighting Methodology | COMPLETE (5/5 plans) -- E1 (shrunk-IC) is champion; E2 (mean-variance) rejected |
| 142.5 | Renaissance Primitives | COMPLETE (8/8 plans) -- 89 primitives live in Feature Factory, 150 total `FeatureVector` fields |
| 142B | Frame Simulation + Counterfactual Tracking | COMPLETE (2/2 plans) -- `alpha_frames` hypertable + `AlphaFrameWriter` + `CounterfactualTracker` live |
| 143 | Feature Lifecycle Routing (merged with 149B) | COMPLETE (3/3 plans) -- `feature_registry` evidence-based promotion/demotion + `integrity_monitor` table live |
| 143.1 | Measurement and Eligibility Integrity | COMPLETE (8/8 plans, 2026-07-21) -- 143.1-08 shadow-mode validation VERDICT: HOLD (`alpha.ensemble.sign_symmetric` stays false) |
| 144 | Cross-Sectional Regime Model (`regime_group`) | COMPLETE (6/6 plans, 2026-07-22) -- D-05 verdict: F1 not triggered (TLT HMM stays deficient, demotion holds), F2 triggered for 15m/5m (rates cross-sectional also deficient there) |
| 146 | Empirical Instrument Tag Calibrator | COMPLETE (5/5 plans, 2026-07-17) -- `TagCalibrator` live-verified: 11/12 measurable tags carry real `source='empirical'` rows |
| 160 | Concept Registry MVP | COMPLETE (4/4 plans) -- 4-table schema + `ConceptRegistryService`/`ConceptRegistryAPI`/`ConceptRegistryDashboard` live |
| 161 | Controlled Vocabulary System | COMPLETE (4/4 plans, 2026-07-18) -- schema + `VocabularyService` + `vocabulary_drift` audit + `/api/vocabulary/{namespace}` route, live-verified (VERIFICATION.md: passed, 23/24 truths, 1 accepted YAGNI override) |
| 148 | Alpha Scoring System (OOS Proof Gates) | COMPLETE (5/5 plans, 2026-07-22) -- the actual proof-of-alpha milestone: Gate 1 PASS, Gate 2 FAIL, VERDICT do not promote to live capital; see ROADMAP.md's Phase 148 section and `docs/plans/2026-07-22-phase148-promotion-decision.md` for full evidence |
| 162 | ic_engine Corpus Pipeline Throughput | COMPLETE (4/4 plans, 2026-07-23) -- whole-cell fingerprint mechanism, equivalence-proven |
| 166 | Frame/Execution Recalibration | COMPLETE (6/6 plans, 4 waves, 2026-07-23) -- baseline and scalar candidates FAIL gate166 decisively; structural candidate halted pending Phase 163. Part 2 (todos 175/176) deprioritized by todo 179's finding. |
| 163 | VP/SR Structural Primitives | COMPLETE (3/3 plans, 2026-07-24, verification 15/15 must-haves) -- closes todo 153. Historical backfill still open (todo 176, deprioritized) |
| 167 | Cross-Sectional Trade Construction (cross_sectional_relative_value) | COMPLETE (6/6 plans, 2026-07-27) -- **original verdict RETRACTED, re-verified 2026-08-07: both Validation Gates FAIL** (`gate1_ctf_momentum_decile_ls_ctf_join_v2`, `gate2_ctf_momentum_decile_ls_ctf_join_v2`) after correcting the sole ranking feature `ctf_momentum`'s lookahead-leaked join (todo 243). No live construction. See Strategic Plan section. |
| 164 | SMC Institutional Footprint Primitives | COMPLETE (4/4 plans, 2026-07-28) -- all 36 SMC FeatureVector fields now real computed values in both FeatureFactory.compute() and compute_batch(). Plan 01 (data contract): 36 new feature_vectors columns + registry rows + FeatureVector fields (172->208 total), 39 feature.smc.* APR keys, FeatureCache.update_overnight_range() AMD mutator built. Plan 02 (order blocks + stateless breaker/mitigation): 7 fields via _compute_order_blocks(); 2 bugs caught and fixed during TDD. Plan 03 (FVG + liquidity sweeps + liquidity pools): 12 fields via _compute_fvg()/_compute_liquidity_sweeps()/_compute_liquidity_pools() (single-tf descoped, PWH/PWL/PDH/PDL dropped); an FVG selection bug found and fixed. Plan 04 (supply/demand zones + BOS/CHoCH + AMD cycle): final 18 fields via _compute_supply_demand_zones()/_compute_bos_choch()/_derive_amd_cycle(); update_overnight_range() wired into compute_batch(), the live per-bar handler, and the warm-up replay block, closing the AMD state-lifecycle cold-start gap. Historical backfill for all 36 columns deliberately deferred to the consolidated 163/164/165 recompute pass (todo 176). |
| 165 | Swing/Fib/Trend/Session Structure Primitives | COMPLETE (5/5 plans, 2026-07-28) -- migration 267 adds 41 new feature_vectors columns + registry rows (group_name='session') for swing detection (7), trend structure (6), swing momentum (8), fibonacci zones (4), session levels (16); zero raw price levels or raw bar indices (D-02/D-04); all 41 fields float \| None, no fake-numeric defaults (D-01). 17 feature.swing.*/feature.trend_structure.*/feature.swing_momentum.*/feature.fib.*/feature.session_levels.* APR keys wired into both live and batch FeatureFactoryConfig sites. `_compute_swing_structure()`/`_compute_trend_structure()` (13 cols, shared `find_peaks`/`find_troughs` pass, D-06), `_compute_swing_momentum()`/`_compute_fib_zones()` (12 cols, deletes the archived cross-plugin fallback outright per D-05), `update_session_levels()` FeatureCache mutator (22 new internal state fields, D-07/D-08/D-09) + `_derive_session_levels()` (final 16 cols) all wired into both `compute()`/`compute_batch()`. Phase-closing gate (`test_phase165_all_41_fields_non_constant_batch`) confirms all 41 columns produce real values; `feature_registry` DB check confirms 41 rows with `added_phase='165'`. Every plan's mutation-verification pass (commit `a748d13d` discipline) surfaced and fixed a real bug in the plan's own tests or comments (a `math.isclose` `rel_tol` masking, a structurally-blind accumulator-collision test, a vacuous live/batch parity check, and a post-merge causal-safety-lint false positive) -- the discipline earned its keep every time it ran. Historical `feature_vectors` backfill for all 41 columns deliberately deferred to the consolidated 163/164/165 recompute pass (todo 176 / STATE.md Tier 0). |

Current row counts and every downstream measurement number live in
[Corpus pipeline state](project_corpus_pipeline_state.md) -- that file is the single source of
truth; don't duplicate counts here.

**Dual regime system (both live):**

- `feature_vectors.regime` -- 5 per-symbol HMM labels (trending_down/transition_down/ranging/transition_up/trending_up), written by `regime_writer.py` (K=5, causal forward-filter)
- `market_regimes` -- cross-sectional labels keyed by `regime_group` (a named peer group with a pluggable regime signal: `breadth_vol` for equity, `curve_credit` for rates; commodity/fx modules ship disabled), written by `cross_sectional_regime_model.py` (Phase 144, replaced `equity_regime_model.py`); `ic_engine` stratifies on these

## Key Decisions (load-bearing -- don't re-derive)

- **HMM_RANDOM_STATE = 42** -- changing invalidates all feature_ic_scores, requires full re-run
- **Pooled IC (is_pooled=true)** -- cross-sectional POOLED strata ARE the ensemble training eligibility source. `ensemble_trainer.py` reads `WHERE symbol='POOLED' AND is_pooled=true AND regime != '_pooled'` (lines 317, 430-431, 469, 540)
- **IC Sharpe gate** -- sharpe_window_size=2000 RAW bars; gate is n_raw_bars >= 20,000; stride divides inside _compute_ic_rolling_metrics
- **regime_label_source DEFAULT** -- 'forward_filter' (not 'filtered') in both forward_returns and feature_ic_scores
- **APR key** -- alpha.ic.subsample_min_stride is a floor: actual_stride = max(min_stride, lookahead_bars)
- **Gradient naming** -- return_fast/mid/slow/extended; momentum_z_fast/mid/slow; volatility_rank_z
- **ON CONFLICT for partial indexes** -- use column list + WHERE clause, not ON CONSTRAINT (TimescaleDB)
- **Corpus re-run required** after Phase A ic_engine methodology fixes (028 P0/P2/P3/P4 change IC scores corpus-wide)

## Corpus Pipeline Gotcha

`--compute-only` silently skips all symbols if backfill_status is empty. After any truncation, seed first:

```sql
INSERT INTO backfill_status (symbol, tf, fetch_complete, status)
SELECT DISTINCT symbol, timeframe, true, 'pending'
FROM market_data_ohlcv WHERE timeframe IN ('5m', '15m', '1h', '1d')
ON CONFLICT (symbol, tf) DO UPDATE SET fetch_complete = true;
```

## Roadmap Evolution

- Phase 171 (HMM Walk-Forward Regime Labeling, Parameter-Lookahead Fix): added 2026-08-04, out of
  todo 248. Wires the already-implemented + TDD-tested `_walk_forward_hmm_labels()` into
  `regime_writer.py`'s live path, replacing the full-history HMM parameter fit. Ships regardless
  of the Gate 4 ordinal-IC pilot's negative result -- confirmed causal-law violation in an
  existing core mechanism, not a new/unproven signal gated on "prove before promoting." Not yet
  planned (0 plans) -- remaining requirements (tf-calibrated refit windows for 15m/5m/1d, live
  wiring, full regime + downstream `ic_engine` recompute) are in the phase entry and todo 248.
  **Sequenced after the CTF-leak/Phase 167 re-verification work by explicit user decision**, to
  avoid two overlapping corpus-recompute-scale efforts.

- Phase 169 (Symbol State Query Layer): added 2026-07-31. Scoped through extensive same-session
  design work (rejected a predictive composite score, an independent Opus review that corrected
  several factual errors along the way, a descriptive-vs-predictive correction, and a locked
  `-1`/`+1` gradient encoding -- one number for magnitude strata like volatility, a
  direction+conviction pair for directional strata like structure). Not yet planned -- design doc
  only: `docs/research/intel-symbol-state-query-layer.md`. Independent of Phase 168 (reads
  `feature_vectors`/`market_regimes`, not `construction_spreads`).

- Phase 168 (Cost-Hurdle-Adjusted Spread Construction, cross_sectional_relative_value Follow-On): added 2026-07-31 as a
  parallel track while the in-flight `ic_engine` recompute runs (zero compute contention --
  pure scoping/discussion work). Follow-on to Phase 167's cross-sectional long-short
  construction; applies todo 030's cost-hurdle sweep as a construction-layer change (which
  symbols/legs survive transaction costs), no new features. Plans are execution-ready (5 plans,
  4 waves, Codex+Agy reviewed) but **DO NOT EXECUTE -- Phase 167's Gate 1/Gate 2 both FAILED at
  authoritative tier 2026-08-07** (see Strategic Plan section); this phase has no live
  construction left to refine. Blocked indefinitely pending an independently-proven construction,
  not a re-verification. See `docs/research/trade-construction-layer.md`.

- Phase 151 (Feature Primitives Expansion + Interaction Layer): planned 2026-07-24, cross-AI reviewed and revised same day (Codex found 3 HIGH-severity findings, all fixed as real plan changes). **UPDATE 2026-08-05: waves 1-5 (plans 01-06, 09; 7 of 9) executed, /simplify'd, code-reviewed (1 critical + 5 warning findings, all but 2 deferred-as-todo fixed), and pushed to origin/main.** `FeatureVector` grew 249->292 fields. Waves 6-7 (151-07 corpus recompute, 151-08 interaction IC sweep) intentionally paused -- not deprioritized behind Phase 167 anymore, but sequenced to run once against the new 111-symbol universe (todo 259's in-flight backfill) instead of twice. See STATE.md frontmatter `stopped_at` for full current status.

(Entries for Phases 162/163/164/165/166/167 removed 2026-08-03 -- all COMPLETE, already fully
described in the Phase Summary table above; this section is for phases with no table row yet.)

## Session

**Last GSD-phase-level session:** 2026-07-31T12:00:00.000Z. **Stopped at:** Phase 171 context gathered
5 plans in 4 waves, plan-checker passed, reviewed by Codex + Agy/Antigravity, 9 findings
incorporated. Ready to execute: `/gsd:execute-phase 168`. (Phase 165's own execution detail --
wave-by-wave commits, mutation-verification catches -- is fully resolved and git-log-recoverable;
trimmed here 2026-08-03. See the Phase Summary table above for what it shipped.)
