---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: Phase 144 (Cross-Sectional Regime Model) COMPLETE (6/6) -- D-05 verdict landed 2026-07-22 (F1 not triggered, F2 triggered for 15m/5m); Phase 148 (Alpha Scoring System) fully PLANNED (5/5 plans, 3 waves), cross-AI reviewed and replanned with fixes, plan-checker verified PASS WITH CONCERNS, execution-ready but not yet run; Phase 143.1 also COMPLETE (8/8) -- 143.1-08 VERDICT HOLD; todos 164/165 closed; todos 160/147 CLOSED 2026-07-22 (corrupt-print discovery mechanism was broken, fixed, 47 bars across 16 symbols corrected, low_bull CV reached parity)
stopped_at: Phase 148 finalized (renamed, cross-AI reviewed, replanned, verified) and execution-ready; todos 160/147 fully closed (discovery-mechanism fix + 47-bar correction + CV parity confirmed); next action is /gsd-execute-phase 148
last_updated: 2026-07-22T18:15:00.000Z
progress:
  total_phases: 12
  completed_phases: 8
  total_plans: 45
  completed_plans: 39
  percent: 67
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Alpha must be demonstrated empirically before any ensemble weight is assigned.

**Current focus (updated 2026-07-22, superseding the stale text below that this replaces):**
Phase 143.1 is COMPLETE (8/8 plans) — 143.1-08's shadow-mode validation concluded HOLD,
`alpha.ensemble.sign_symmetric` stays `false`, confirmed twice (once pooled, once via todo
165's regime-stratified re-evaluation). Todo 094 (the sign-symmetric redesign this validation
gated) is closed with that verdict. Todos 164/165 (regime-stratified promotion gate + 1h
ensemble eligibility) are also closed, merged to main.

**Two concurrent sessions converged today (2026-07-22) — reconciling both here, not picking
one.** Track A (regime-model refinement, this note's own thread): symbol_hmm restoration →
Phase 144 D-05 → Phase 145 is now fully resolved, see below. Track B (proof-of-alpha,
concurrent session): Phase 148 was fully planned (5 plans, 3 waves) and a real Phase 147
dependency correction landed — **Phase 148 is unblocked today, independent of Phase 147**,
and per that session's own investigation is arguably the higher-priority track: it's the two
independent OOS gates (signal proof + execution proof) this whole measurement pipeline exists
to produce, not incremental refinement of an already-working stratification mechanism.

**Track A, resolved:** the symbol_hmm restoration fix (worktree
`worktree-restore-symbol-hmm-ic-measurement`) landed all 5 tasks: `dual_write_symbol_hmm`
threaded through `ic_engine.py` (`083b3db6`), migration 247 seeding it `true` for `rates`
(`8695673e`), live-verified (`TLT` now has 6,045 fresh `symbol_hmm` rows), and D-05's gate
re-run produced a real verdict (previously years of `(no rows)`/INCONCLUSIVE): **F1 not
triggered** (TLT's per-symbol HMM stays deficient, demotion holds, matching the original
2026-07-02 finding) and **F2 triggered for 15m/5m** (rates cross-sectional is ALSO deficient
at high frequency — pre-registered build trigger for a factor-augmented HMM challenger,
pending confirmation `volatility_pct` hasn't already passed its own substitution gate for
rates). Full detail in ROADMAP.md's Phase 144 section, now ✅ COMPLETE. **Phase 145
(StratificationDimension Formalization) is now unblocked** (was gated on this exact verdict)
but not yet started. Three follow-ups filed, not silently dropped: todo 167 (equity's
analogous falsifier question, never tested), todo 168 (7 corpus symbols —
`LQD`/`PFF`/`RSP`/`USMV`/`UUP`/`VWO`/`XRT` — have zero per-symbol HMM regime coverage at all,
a real pre-existing `regime_writer.py` gap unrelated to this fix), todo 169 (the missing
systemic monitor that would have caught 168's gap years earlier). **Recorded but not
executed:** don't flip `rates.dual_write_symbol_hmm` back to `false` until the next full
corpus rebuild reproduces F1's non-trigger result — this was a scoped 12-symbol verification
run, not full-corpus confirmation.

**Track B, per the concurrent session:** `/gsd-discuss-phase 147` surfaced that Phase 147 (I7
CORPUS-07 Evaluation — auditing whether the 35 archived, zero-live-consumer I7 plugins hold
signal not already in the v3.0 Feature Factory) is due diligence on a dead system, not v3
measurement work, and does NOT gate Phase 148 — the "Depends on: Phase 147" line in
ROADMAP.md was itself stale (SCORE-01/02/03 read only pure v3.0 tables; the one place 147
ever connected was SCORE-04, already downgraded to documentation-only 2026-07-19). Fixed in
ROADMAP.md, the backlog matrix, and here. Phase 148's prerequisites (EIC-04 PASS, ≥60 days
closed `alpha_frames`) are already met by a wide margin (15.6M `closed_max_hold` rows, ~4,883
distinct trading days) — fully planned (5 plans, 3 waves), not yet executed.

Milestone v3.1 is not yet complete.

**Next actions — reconciled todo+phase priority view (2026-07-22, supersedes the numbered list
this replaces; that list's item (1) FRAME-04-recheck nuance is now resolved — Phase 148's own
CONTEXT.md D-08 established SCORE-03 IS FRAME-04, not a second gate needing a separate re-run):**

*Tier 1 — next up:* **Phase 148 execution** (`/gsd-execute-phase 148`) — the real proof-of-alpha
milestone: fully planned, cross-AI reviewed (Antigravity + Codex), review findings incorporated
(fixed a confirmed-real crash in `evaluate_frame_gate`'s group-key call shape, added pre-run
integrity snapshots + `--dry-run` escape hatches to both irreversible gates), independently
plan-checker-verified PASS WITH CONCERNS (no blockers). Todos 160/147 **CLOSED 2026-07-22** —
corrupt-print candidate-discovery mechanism was itself broken (gated behind `forward_returns`
suspect flags, blind to `high`/`low`-only corruption); fixed to scan all ~320 registered pairs
directly; found and corrected 47 bars across 16 symbols total (40 across 14 symbols in the main
batch, 7 more across FXY/IWM once a threshold-sensitivity gap surfaced). `low_bull`'s CV reached
parity with clean regimes (5m: 582.9→3.49, 15m: 469.4→2.80); the one remaining elevated cell
(`5m/high_bear`, CV≈116) confirmed to be the already-adjudicated 2010 Flash Crash, not a gap.
See `completed/160-vwo-dia-kre-corrupt-prints-uncorrected.md` and
`completed/147-vol-normalized-target-low-bull-divergence.md` for full disposition.

*Tier 2 — ready now, independent of 148:* Phase 163 execution (`/gsd-execute-phase 163`,
planned) · Phase 162 execution (`/gsd-execute-phase 162`, planned + reviewed, gated only on
`ps aux | grep ic_engine` clear) · todo 088 (`hold_max_bars` type safety, small, unblocked) ·
todos 168/169 (7 symbols with zero HMM regime coverage + no monitor that would've caught it) ·
todo 170 (`volatility_pct` substitution probe for rates, cheap, do before any HMM-challenger
build).

*Tier 3 — needs a planning pass first:* Phase 145 (StratificationDimension Formalization,
unblocked by Phase 144's D-05 verdict, not yet discussed/planned) · Phase 165 (Swing/Fib/Trend
Structure Primitives, context+research done, needs `/gsd-plan-phase 165`) · todo 111 (same
unblock as Phase 145).

*Tier 4 — real value, not urgent:* Phase 147 (I7 CORPUS-07 — due diligence on an already-dead
system, cheap, gates nothing) plus the full P2/P3 tier in `.planning/todos/PRIORITIES.md`.

*Tier 5 — explicitly gated, do not start planning yet:* Phases 149-159 (PrecedentEngine,
Feature Primitives Expansion, Alt Data, Portfolio State, Position Sizing, Live Execution, Cost
Calibration) — registered in ROADMAP.md, zero planning artifacts, v4.0-adjacent scope. Per
"prove edge before production infra," none of these should get planning time until Phase 148
delivers a real verdict.

**Execution plan:** `docs/plans/2026-06-30-alphaengine-v1-execution-plan.md`

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
| 142A | Ensemble IC Measurement | COMPLETE (2/2 plans) — EIC-04 current verdict PASS 54/1425=3.79%, see [Corpus pipeline state](project_corpus_pipeline_state.md) for the live number |
| 142B.1 | Ensemble Weighting Methodology | COMPLETE (5/5 plans) — E1 (shrunk-IC) is champion; E2 (mean-variance) rejected |
| 142.5 | Renaissance Primitives | COMPLETE (8/8 plans) — 89 primitives live in Feature Factory, 150 total `FeatureVector` fields |
| 142B | Frame Simulation + Counterfactual Tracking | COMPLETE (2/2 plans) — `alpha_frames` hypertable + `AlphaFrameWriter` + `CounterfactualTracker` live |
| 143 | Feature Lifecycle Routing (merged with 149B) | COMPLETE (3/3 plans) — `feature_registry` evidence-based promotion/demotion + `integrity_monitor` table live |
| 143.1 | Measurement and Eligibility Integrity | COMPLETE (8/8 plans, 2026-07-21) — 143.1-08 shadow-mode validation VERDICT: HOLD (`alpha.ensemble.sign_symmetric` stays false); see Session's "2026-07-21" closeout subsection below |
| 144 | Cross-Sectional Regime Model (`regime_group`) | COMPLETE (6/6 plans, 2026-07-22) — D-05 verdict: F1 not triggered (TLT HMM stays deficient, demotion holds), F2 triggered for 15m/5m (rates cross-sectional also deficient there); see Current focus |
| 146 | Empirical Instrument Tag Calibrator | COMPLETE (5/5 plans, 2026-07-17) — `TagCalibrator` live-verified: 11/12 measurable tags carry real `source='empirical'` rows |
| 160 | Concept Registry MVP | COMPLETE (4/4 plans) — 4-table schema + `ConceptRegistryService`/`ConceptRegistryAPI`/`ConceptRegistryDashboard` live |
| 161 | Controlled Vocabulary System | COMPLETE (4/4 plans, 2026-07-18) — schema + `VocabularyService` + `vocabulary_drift` audit + `/api/vocabulary/{namespace}` route, live-verified (VERIFICATION.md: passed, 23/24 truths, 1 accepted YAGNI override) |

Current row counts and every downstream measurement number live in
[Corpus pipeline state](project_corpus_pipeline_state.md) — that file is the single source of
truth; don't duplicate counts here.

**Dual regime system (both live):**

- `feature_vectors.regime` — 5 per-symbol HMM labels (trending_down/transition_down/ranging/transition_up/trending_up), written by `regime_writer.py` (K=5, causal forward-filter)
- `market_regimes` — cross-sectional labels keyed by `regime_group` (a named peer group with a pluggable regime signal: `breadth_vol` for equity, `curve_credit` for rates; commodity/fx modules ship disabled), written by `cross_sectional_regime_model.py` (Phase 144, replaced `equity_regime_model.py`); `ic_engine` stratifies on these

## Key Decisions (load-bearing — don't re-derive)

- **HMM_RANDOM_STATE = 42** — changing invalidates all feature_ic_scores, requires full re-run
- **Pooled IC (is_pooled=true)** — cross-sectional POOLED strata ARE the ensemble training eligibility source. `ensemble_trainer.py` reads `WHERE symbol='POOLED' AND is_pooled=true AND regime != '_pooled'` (lines 317, 430-431, 469, 540)
- **IC Sharpe gate** — sharpe_window_size=2000 RAW bars; gate is n_raw_bars >= 20,000; stride divides inside _compute_ic_rolling_metrics
- **regime_label_source DEFAULT** — 'forward_filter' (not 'filtered') in both forward_returns and feature_ic_scores
- **APR key** — alpha.ic.subsample_min_stride is a floor: actual_stride = max(min_stride, lookahead_bars)
- **Gradient naming** — return_fast/mid/slow/extended; momentum_z_fast/mid/slow; volatility_rank_z
- **ON CONFLICT for partial indexes** — use column list + WHERE clause, not ON CONSTRAINT (TimescaleDB)
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

- Phase 162 added (2026-07-18): ic_engine Corpus Pipeline Throughput — bundles todos 134/133/122/139/140/129/009E. **PLANNED 2026-07-22** (4 plans, 4 sequential waves — `162-01` structural extraction/memory-bounding, `162-02` per-tf bootstrap threads, `162-03` fingerprint table + watermarks + `.pkl` deletion, `162-04` equivalence harness). Research + pattern-map + plan-checker all passed (0 blockers); skipped `/gsd-discuss-phase` since two prior Fable design passes already served as its equivalent — see ROADMAP.md's Phase 162 section and `162-RESEARCH.md`/`162-PATTERNS.md`/`162-VALIDATION.md`. `143.1-07`'s resource-contention gate cleared before this session (143.1 is complete); no other blocker. Not yet executed — `/gsd-execute-phase 162` is the next step, gated only on `ps aux | grep ic_engine` being clear.
- Phase 163 added (2026-07-20): VP/SR Structural Primitives — closes todo 153 (poc_dist_atr/va_position/sr_support_dist/sr_resist_dist permanently stuck at constant defaults since v3 rebuild). Sibling atomic-expansion item to Phase 151, not folded into it. No dependency on the in-flight todo-147 CV recheck or 094 shadow-mode validation running elsewhere. Scope widened same day: port ctx_VolumeProfile (I4, 18 fields) instead of the thinner i3_structure/market_profile.py originally identified — self-contained, no known bugs, same computation cost. **PLANNED but NOT YET EXECUTED as of session end 2026-07-20** — see "Session" below for exact resume point; do not run `/gsd-execute-phase 163` until the pending rolling-track review (Fable dispatch, in flight at session end) resolves.
- Phase 164 added (2026-07-20): SMC Institutional Footprint Primitives — atomic distance/strength/duration/count primitives ported from the archived v2.x smc_context plugins (order blocks, FVG, liquidity sweeps/pools, supply/demand zones, AMD cycle, breaker/mitigation blocks, BOS/CHoCH). All self-contained on already-live shared utils, no cross-plugin dependency chain. Sequenced after Phase 163 for shared conventions, not a hard code dependency. Registered in ROADMAP.md with a raw-price-vs-ATR-companion warning (see Phase 163's D-16/D-17 lesson) but NOT planned — no CONTEXT.md/RESEARCH.md/PLAN.md yet.

## Session

**Last session:** 2026-07-22T12:11:02.801Z
**Stopped At:** Phase 148 context gathered

**Resume File / exact next action:** Run `/gsd-execute-phase 163`. Nothing else needs checking first — verified directly (not just trusting the planner agent's self-report): `git log` shows `f394bbdd` as the last commit touching the phase dir, and both `163-01-PLAN.md`/`163-02-PLAN.md` grep-confirm "12 new" column phrasing and both `poc_rolling_dist_atr`/`poc_session_rolling_divergence_atr` present. After execution: close todo 153 (move `pending/153-vp-sr-features-null-in-batch-corpus.md` → `completed/`), noting the decision made (implement, not delete) and pointing at whatever incremental-IC result eventually comes out of the next `ic_engine` corpus run per D-07's promotion bar (not measured as part of this phase — that's out of scope by design).

**This session's full arc (for context if resuming cold):** Started from todo 153 (VP/SR features permanently null) → Fable research → discovered a better port source (`ctx_VolumeProfile`) than originally proposed → caught and fixed a raw-price-as-ML-feature bug in that scoping (D-16) → planned Phase 163 via direct `gsd-planner` dispatch (bypassing the full `/gsd-plan-phase` skill since CONTEXT.md/RESEARCH.md were already hand-written) → got an independent Fable review of the whole corrected scope, which caught 2 more issues (D-17: dropped `in_lvn`, undocumented `va_width_atr` collinearity) → both fixed in the already-written plans → user caught a further gap (rolling-track signal computed but unused) → third Fable review dispatched, in flight at session end. Also: filed todo 158 (unrelated live-path bug found incidentally: `above_wk_vwap` frozen at 0.0 in live pipeline, batch path is correct) and closed out the todo-147 CV recheck's A/B rerun analysis (encouraging but not fully closed — see PRIORITIES.md's todo-147 entry, the direct `true_range_pct` CV re-check is still outstanding). Phase 164 (SMC Institutional Footprint Primitives) registered but not planned — deliberately deferred to a future session/prioritization call.

**Note (2026-07-20, concurrent todo-track session):** the paragraph above's "filed todo 158" /
"closed out... (encouraging but not fully closed)" is a stale snapshot from mid-flight — see the
dedicated subsection below for what actually happened on that track. Left this paragraph
unedited rather than risk a racy overwrite of the phase-track's own resume notes above.

### Todo-track resume point (concurrent session, same day — 158/159/147/124/160)

**Stopped at:** Todo 158 fully fixed, merged to `main` (commit `803d8893`). Investigating todo
147's outstanding CV re-check surfaced a real, deeper data-integrity bug (todo 124/160) that is
now the next concrete action, not yet started.

**What happened, in order:**

1. **Todo 158** (`above_wk_vwap` frozen at 0.0 on the live path) — root-caused via
   `systematic-debugging`, fixed with one line in `_process_bar_compute` (`cache.advance_bar(...)`
   after `FeatureFactory.compute()`), TDD regression test added, `/simplify` clean, Codex peer
   review (AGY was out of quota). Merged to `main`.

2. **Todo 159** filed from that Codex review: `FeatureCache` isn't warmed from the bar history
   `_seed_bar_history_from_db()` already loads at startup, so `above_wk_vwap`/`hmm_duration`
   still start cold after every restart. Not started.

3. **Todo 147's outstanding CV re-check** (the `true_range_pct` per-(tf,regime) CV pull its
   "Fix / next step" section asked for, never run before this session) — ran it: `low_bull`
   still ~150-300x every clean regime's CV, NOT at parity despite 151/154's correction pass.

4. Traced why: `VWO`/`DIA` were never flagged at all (candidate-discovery gap). `KRE` WAS
   correctly flagged `price_sanity_status='confirmed_corrupt'` with `forward_returns`
   recomputed sane — but `feature_vectors.true_range_pct` for that same bar is still corrupt,
   because `backfill_feature_factory.py` reads raw `market_data_ohlcv` directly instead of the
   `price_sanity_status`-filtering `market_data_ohlcv_tradeable` view. The flag never reaches
   feature computation.

5. This reclassified **todo 124** (previously P3, "style/DRY only" — that assessment predates
   `price_sanity_status`, written 2026-07-16) to **P1**, now the real fix owner. Filed
   **todo 160** as the evidence trail/reproduction. Both PRIORITIES.md and two memory files
   were corrected after an initial (wrong) framing that assumed all 3 rows were simply
   uncorrected — first commit `0b57fa22`, correction commit `2a1d3a78`.

**Exact next action:** Todo 124's real fix — migrate `services/backfill_feature_factory.py`
from raw `market_data_ohlcv` reads to `market_data_ohlcv_tradeable`. Do this file first (proven
correctness impact), not the other 13 files in 124's Tier-2 list (still style/DRY-only as far as
evidence shows). After that lands: redo the DELETE + recompute for `KRE` (and newly-flagged
`VWO`/`DIA` — flag them first via `ops_known_corrupt_print_cleanup.py --symbols VWO DIA
--apply`), then re-run todo 147's CV check a third time, then close 147 if parity holds.

**Also worth a quick look before the 124 fix, low-cost sanity check:** `regime_writer.py` and
`forward_return_writer.py` share the identical `volume > 0`-only exposure pattern as
`backfill_feature_factory.py` (same allow-list entry, same stale 2026-07-16 audit) but haven't
been checked for a live reproduction — todo 124's text now flags this, not yet investigated.

**Priority docs status (checked this session, per user request):** `.planning/todos/PRIORITIES.md`
verified in sync with `pending/` (only 2 unreferenced numbers, 012/032, both intentional
merge-pointer stubs to todo 009, not real gaps). `docs/research/intelligence-lifecycle-backlog-matrix.md`
("the priority matrix") is genuinely stale — last rewritten 2026-07-08, predates Phase 144 going
code-complete, Phase 143.1's near-completion, and Phases 162/163/164/165 all being registered.
It already correctly defers todo-level ranking to PRIORITIES.md (no drift there), but its own
"Phases" table and "Operational context" note need a refresh — not done this session, flagged
here rather than silently left stale. ROADMAP.md spot-checked consistent with STATE.md (Phase
144 header deliberately still says PLANNED per its own documented reason, not a bug).

### Session closeout (2026-07-21) — 143.1-08 resolved, merged to main; Phase 143.1 is COMPLETE

**Todo 124's real fix landed** (the "exact next action" the prior subsection stopped at):
`backfill_feature_factory.py`, `regime_writer.py`, `forward_return_writer.py` all migrated
`market_data_ohlcv` → `market_data_ohlcv_tradeable` (the sibling-file sanity check that
subsection flagged as "worth a quick look" — done, same fix, same commit). `/simplify`-clean,
full unit suite green. Data recompute (KRE/VWO/DIA, todo 147's third CV re-check) still not
done — deliberately held to avoid DB contention with the concurrent 143.1-08 backfill below;
still the next action for that track.

**Todo 159 fixed and closed**: `FeatureCache` now warms `above_wk_vwap` from seeded bar
history at `_get_cache()`'s first call per (symbol, tf) — `hmm_duration` deliberately left cold
(would fabricate a duration, not recover a real one). 3 regression tests, moved to
`completed/`.

**Phase 165 (Swing/Fib/Trend Structure Primitives) fully scoped**: Fable-researched
`165-CONTEXT.md`/`165-RESEARCH.md` committed — 41 new columns across 5 files
(`swing_detector`/`swing_momentum`/`trend_structure`/`fibonacci_zones`/`session_levels`), 2
silent-wrong-answer bugs found and scoped for fixing during port, 3 tangential ideas proposed
and council-rigor-tested (2 accepted as free columns off existing computation, 1 — Fibonacci
extensions — explicitly deferred as premature scaling of an unproven hypothesis family). Not
planned yet (`/gsd-plan-phase 165` is the next step whenever picked back up). Phase 163 also
got a real post-review correction (D-19: 5 free S/R fields — `resistance_strength`/
`support_strength`/`resistance_age_bars`/`support_age_bars`/`sr_level_count` — found via Codex
cross-AI review, folded into the plan before execution; migration 243 is now 17 new columns,
not 12). **Phase 163 is still execution-ready (`/gsd-execute-phase 163`), not yet run.**

**143.1-08 (shadow-mode champion/challenger validation) is DONE — VERDICT: HOLD.**
`alpha.ensemble.sign_symmetric` stays `false`; criteria 2/3/4 (mean-P&L CI, Sharpe, max
drawdown) all fail decisively for the sign-symmetric challenger, not a close call. Emission
mechanism confirmed working as designed regardless (challenger: 69.83% short vs champion's
0.335%). **Phase 143.1 (Measurement and Eligibility Integrity) is now COMPLETE (8/8 plans)** —
the "Phases" table above still says "IN PROGRESS (7/8 plans)"; next session should flip this to
COMPLETE and re-check whether Phase 144's D-05 acceptance gate re-run (the next actual
milestone step) is now unblocked.

**Along the way:** the `counterfactual_tracker --backfill` this validation depended on had
zero progress across 3 attempts (~18h wall-clock) before a real root cause was found and fixed
— `ProcessPoolExecutor.map()`'s head-of-line-blocking ordering compounded by 358x per-row
TimescaleDB chunk-routing overhead (1,034 chunks). Fixed, verified (78min corrected run, 23.15M
rows), closed as **todo 161**. Sanity-checking the resulting numbers before trusting them (not
just accepting extreme Sharpe/drawdown values at face value) surfaced a real, separate,
cross-cutting data-quality gap: ATR-based stop distances have no minimum-price-fraction floor,
producing R-multiples down to **-926R** on thin-volatility FX/commodity ETFs at 5m — filed as
**todo 162 (P1)**, confirmed via a trimmed-outlier check that it doesn't change the HOLD
verdict itself, just inflates the tail statistics' magnitude. Honest limit: could not verify
whether this contaminated any *past* gate evaluation (E6/FRAME-04) since the underlying
`alpha_frames` rows from before this session have since been superseded — flagged as a
plausible risk, not a confirmed retroactive finding.

**Merge:** the worktree branch (`worktree-agent-acc3e6a78746c2514`) carrying all of the above
was merged to `main` via a regular merge commit (`c9622932` — not fast-forward, histories had
diverged; verified zero real conflicts via `git merge-tree` before merging, confirmed empirically
correct when the merge itself applied cleanly), full unit suite green post-merge, pushed to
`origin/main`. Worktree removed, branch deleted, `git worktree prune` run — zero worktrees
remain.

**Todo 162 resolved same day, after this closeout was first written** (fix landed
`5db6c298`): went with the skip-and-count direction (widened `degenerate_atr_skip_count`
guard via `alpha.frame.min_stop_price_fraction`, migration 243, seed 0.001
`[initial_estimate]`), not a widened-stop-distance floor — a floor would have silently
fabricated `target_price` too, since it's derived from `stop_distance`. Filed a deferred
follow-up (todo 163, gated on Phase 163 actually shipping real `sr_support_dist`/
`sr_resist_dist`) for the separate question of whether frame geometry should become
S/R-aware once that data exists — cross-referenced from Phase 163's own CONTEXT.md.

**Next actions, in order:** (1) Todo 147's third CV re-check (KRE/VWO/DIA recompute, now that
124's fix is live and DB contention has cleared). (2) Phase 144's D-05
acceptance gate re-run, now that 143.1 is complete. (3) Phase 163 execution
(`/gsd-execute-phase 163`) — ready, independent of the above. (4) Phase 165 planning
(`/gsd-plan-phase 165`) — ready, independent of the above.

### Session closeout (2026-07-21, later same day) — todos 164/165 implementation plan executed and merged

This session picked up mid-flight work that neither this file nor `main`'s working tree
accurately reflected: a full implementation plan
(`docs/superpowers/plans/2026-07-21-regime-stratified-promotion-and-per-timeframe-eligibility.md`,
found investigating 143.1-08's HOLD verdict) had already been executed 9 commits deep in an
active worktree (`worktree-todo-164-165-ensemble-eligibility`), while `main`'s working tree
held stray, redundant, uncommitted duplicates of the worktree's earliest commit (confirmed
byte-identical/formatting-only diffs before discarding them).

**Todo 165 (regime-stratified OOS promotion gate) — shipped.** `evaluate_frame_gate`
(`services/counterfactual_tracker.py`) generalized with a grouping-key + day-cluster
coverage-floor parameter; wired into `scripts/analysis/phase143_1_08_shadow_validation.py`'s
C2/C7 criteria; new pre-registered `alpha.validation.regime_gate_min_clusters` APR key
(migration 244, seed 20, explicitly not tunable post-hoc). Re-run against real 143.1-08 data:
**verdict unchanged, still HOLD** — every cell with adequate coverage failed criterion 2
decisively for both champion and challenger; 6 of 8 champion cells and 6 of 14 challenger
cells had insufficient day-cluster coverage and were excluded from the gate rather than
counted pass/fail (a partial, honest regime-by-regime verdict, not a complete one). Full
output in `143.1-08-SHADOW-VALIDATION.md` section 7.

**Todo 164 (`1h` portion) — shipped, with a real emergent finding along the way.** Per-tf
APR resolution added for `min_passing_features`/`max_feature_weight`/`meta_fdr_min_cells`
(`_resolve_per_tf`/`_assert_feasible_thresholds`, `services/ensemble_trainer.py`) plus a
startup feasibility assertion. Migration 245 (seeding `1h`'s `min_passing_features=3`/
`max_feature_weight=0.34`) alone proved **insufficient** on live re-run — `1h` still wrote
zero strata on every regime. Root-caused one gate upstream to `meta_fdr_min_cells`; fixed
with an emergent migration 246 (`meta_fdr_min_cells.1h=2`, live-queried against
`feature_ic_scores` before seeding, not guessed). Live-verified via a full completed
`ensemble_trainer.py --sign-symmetric` run: `1h` now writes 5 of 7 regimes (`high_bear`,
`low_bull`, `mid_bear`, `mid_bull`, `mid_neutral`), previously 0 of 7. `low_neutral` and
`high_neutral` remain unfixed (documented, not silently dropped) — `low_neutral` is one
meta-eligible feature short of the floor, `high_neutral` has zero IC rows entirely, a
deeper population gap. `5m`/`15m`/`1d` confirmed byte-identical to pre-existing baseline
(no per-tf key set for them). `1d`'s genuinely different small-sample power problem split
out to new **todo 166** (P2, pending) rather than papered over with the same fix.

**Both todos closed** (moved to `completed/`, `PRIORITIES.md` updated). **Cleanup:** ~50M
total leftover debug rows removed from `ensemble_alpha`/`ensemble_weights` across two
throwaway `weight_version`s (`debug_1h_investigation`, `debug_164_1h_verify2`) that a prior
session's live-verification runs had left behind — one was still actively writing when this
session started and had to be waited out rather than killed (would have orphaned the
in-flight batch write). Full unit suite green (`.venv/bin/pytest tests/unit/ -q`, both in
the worktree and again on `main` post-merge). Merged via fast-forward (`main` was already an
ancestor of the worktree branch — no divergence, unlike the 143.1-08 merge earlier this
session), pushed to `origin/main` (`24ca4da1`). Worktree removed, branch deleted,
`git worktree prune` run — zero worktrees remain.

**Next actions, in order:** (1) Todo 147's third CV re-check — unchanged from above, still
the longest-outstanding item. (2) Phase 144's D-05 acceptance gate re-run. (3) Phase 163
execution (`/gsd-execute-phase 163`) — ready. (4) Phase 165 planning (`/gsd-plan-phase 165`)
— ready. (5) Todo 166 (1d small-sample statistical treatment, P2) — newly filed, needs real
design work, not urgent. (6) Consider whether Phase 144's D-05 gate and Phase 148's OOS
proof gates should adopt the same regime-stratified evaluation pattern todo 165 just proved
out — flagged as a likely-shared mechanism in todo 165's original filing, not yet checked.

### Session closeout (2026-07-22) — symbol_hmm restoration complete + Phase 148 planning merged

Two concurrent sessions converged on `main` today; this subsection reconciles both rather
than letting one silently overwrite the other's STATE.md edit (real merge conflict on this
file's header/current-focus block, resolved by hand — see the merge commit for the full
before/after).

**Track A (this session, worktree `worktree-restore-symbol-hmm-ic-measurement`): symbol_hmm
restoration, all 5 tasks complete.** `dual_write_symbol_hmm` threaded through `ic_engine.py`
end-to-end (`083b3db6`), migration 247 seeding it `true` for `rates` only (`8695673e`),
live-verified via a scoped 12-symbol re-run (`TLT` got 6,045 fresh `symbol_hmm` rows,
existing `cross_sectional` rows and equity symbols confirmed untouched). Phase 144's D-05
gate re-run then produced a real verdict for the first time (previously years of `(no
rows)`/INCONCLUSIVE): **F1 not triggered** (TLT's per-symbol HMM stays deficient, demotion
holds) and **F2 triggered for 15m/5m** (rates cross-sectional also deficient at high
frequency — pre-registered build trigger for a factor-augmented HMM challenger, pending a
`volatility_pct` substitution-gate check). **Phase 144 closes COMPLETE.** Phase 145
(gated on this exact verdict) is now unblocked, not yet started. Three follow-ups filed:
todo 167 (equity's analogous falsifier question never tested), todo 168 (7 corpus symbols
with zero per-symbol HMM regime coverage at all — `LQD`/`PFF`/`RSP`/`USMV`/`UUP`/`VWO`/`XRT`,
a real pre-existing `regime_writer.py` gap), todo 169 (the missing systemic monitor that
would have caught 168's gap years earlier). Recorded a trigger, not executed: don't flip
`rates.dual_write_symbol_hmm` back to `false` until a full corpus rebuild reproduces F1's
non-trigger result on more than this scoped 12-symbol sample.

Also on this same worktree: Phase 162 (ic_engine Corpus Pipeline Throughput) was fully
planned (research, pattern map, validation strategy, 4 plans across 4 waves), cross-AI
reviewed (Codex found one real HIGH-severity gap — a stale `existing_keys` snapshot that
could silently skip a just-invalidated cell — fixed by removing the parameter entirely, not
just passing an empty set), and independently re-verified by `gsd-plan-checker` (0 blockers,
all 20 live `existing_keys` occurrences traced and accounted for). Not yet executed.

**Track B (concurrent session): Phase 148 fully planned, Phase 147 dependency corrected.**
`/gsd-discuss-phase 147` found Phase 147 (I7 CORPUS-07 due-diligence on a dead system) does
NOT gate Phase 148 — the ROADMAP "Depends on: Phase 147" line was stale (SCORE-01/02/03 read
only pure v3.0 tables; the one real connection, SCORE-04, was already downgraded to
documentation-only 2026-07-19). Phase 148 (the two independent OOS proof gates — signal proof
+ execution proof — this whole measurement pipeline exists to produce) is unblocked today,
prerequisites already met by a wide margin, fully planned (5 plans, 3 waves), not yet
executed.

**Merge:** real (non-fast-forward) merge, `main` had diverged (`d7c74da9` vs this worktree's
tip) with no file overlap except this file and ROADMAP.md's Phase 144/145 sections, both
resolved by hand reconciling both tracks' content rather than discarding either side. Full
unit suite green post-merge. Pushed to `origin/main`.

**Next actions, in order — Phase 148 execution first per track B's own reasoning (the actual
proof-of-alpha path), everything else independent of it:** (1) Phase 148 execution
(`/gsd-execute-phase 148`) — re-run FRAME-04 against the post-143.1 corpus first (stale
16/17-cells-fail result predates 143.1's fix). (2) Todo 147's third CV re-check (KRE/VWO/DIA)
— longest-outstanding independent item. (3) Todo 088 (`hold_max_bars` type safety) — small,
unblocked. (4) Phase 163 execution — planned, ready. (5) Phase 162 execution — planned,
reviewed, ready; gated only on `ps aux | grep ic_engine` clear. (6) Phase 165 planning —
ready. (7) Phase 145 planning — newly unblocked by Phase 144's verdict, read it first. (8)
Phase 147 whenever convenient — cheap, not gating anything.

### Session closeout (2026-07-22, later same day) — Phase 148 finalized, todo 160's real scope found and fixed

Picked up from the prior subsection's Phase 148 memory-file handoff. Cleaned up Phase 148's
remaining doc debt first: finished the migration-numbering correction notes in
`148-RESEARCH.md`/`148-PATTERNS.md` (148-01-PLAN.md itself was already correct at migration
248), added the missing Gate 2 reproduction-tolerance assertion to `148-05-PLAN.md` Task 2
(now asserts freshly-computed `c2_ci_lower`/`c3_sharpe`/`c4_max_dd` match the known 143.1-08
baseline within 1e-6, not just "a row exists"). Renamed the phase itself (title + directory,
`148-alpha-scoring-system-v2-x-decommission-planned` → `148-alpha-scoring-system-planned`) to
drop the "v2.x Decommission" framing — the phase's own CONTEXT.md already states decommission
is explicitly out of scope (todo 056 owns it), the title never matched what the phase does.

**Cross-AI review (Antigravity + Codex) ran clean.** Both converged independently on the same
3 concerns from different angles: (1) `evaluate_frame_gate` group-key reuse — 148-02's 4-tuple
call and 148-04's `(direction, regime)` call both risked breaking against the helper's real
signature; (2) irreversible one-shot gates lacked a pre-run integrity snapshot and atomic
write; (3) validation was lighter than the irreversible stakes warrant, no dry-run escape
hatch for dev-time testing. Replanned all 5 plans to fix these. The group-key fix turned out
load-bearing: read `evaluate_frame_gate`'s live source directly and confirmed it hard-crashes
(`ValueError: too many values to unpack`) on anything but a 2-tuple — the original 148-02 plan
would have failed on first execution, not just "risked" a mismap as the reviewers guessed.
Fixed to call per-cohort with a 2-tuple, matching an existing production precedent
(`phase143_1_08_shadow_validation.py`). Independently verified by `gsd-plan-checker`: **PASS
WITH CONCERNS, no blockers** — confirmed the group-key fix against live source itself before
trusting it, confirmed the dry-run/atomicity revisions didn't complicate the core Gate-1-before-
Gate-2 sequencing, confirmed migration numbering and the tolerance assertion both survived the
replan intact. One hygiene-only finding (leaked tool-wrapper tags at the end of all 5 plan
files) fixed before committing. **Phase 148 is now execution-ready** — planned, reviewed,
replanned with fixes, independently verified.

**Sanity-checked whether Phase 148 was actually the right next step before executing it** (user
asked directly) — found a real answer, not just deference to the stored priority order: todo
160 (P0, corrupt-print correction) was still open, and its root cause traces into the exact
tables Gate 2 reads (`alpha_frames`' underlying feature computation via ATR-based stop
distances). Gate 2 is irreversible (D-04, run once ever) — spending that one shot on a
population with a known, cheap-to-fix contamination was the wrong trade. Investigated further:
the automated flagging tool (`ops_known_corrupt_print_cleanup.py`) couldn't even find the two
known-bad rows (VWO/DIA) — its candidate discovery was gated behind `forward_returns` suspect
flags, structurally blind to corruption confined to `high`/`low` with a sane `open`/`close`
(confirmed live: only 18-20 of 320 registered (symbol,tf) pairs were ever discoverable that
way). **Fixed the discovery mechanism itself** (scan all registered pairs directly via
`backfill_status`, not a derived-return proxy) rather than hand-patching the 2 known rows —
the systemic fix, not the symptom. Live full-corpus dry-run under the fix found **40
CONFIRMED_CORRUPT bars across 14 symbols** (DBC/DIA/EDV/EFA/EWG/FXI/GLD/IWM/RSP/SPY/UUP/VWO/
VYM/XRT), 20x the previously-known count — every one the identical clean
`isolated_spike_neighbors_agree` signature (tightly-agreeing neighbors, single-field
order-of-magnitude outlier). SPY's $1441.65 spike on a ~$142 bar was the most consequential
single find given SPY's weight across the corpus. Applied after human review (both the
dry-run report and an explicit user confirmation given the blast radius grew from 2 symbols to
14). 28 rows correctly stayed classified MARKET_EVENT (the known 2010-05-06 Flash Crash
cluster, cross-symbol corroborated) and excluded from correction.

**Recompute hit a real infrastructure lesson along the way.** `backfill_feature_factory.py
--compute-only` at its default worker count (12) OOM-killed twice in a row at nearly identical
elapsed time (~5-6 min) regardless of whether an external timeout was involved — confirmed via
`journalctl -k` (not guessed): python worker processes at 2.3-2.9GB RSS each, 12 concurrent
workers computing full-history features for large symbols (390K+ bars) exceeded available
memory. Fixed by dropping to `--workers 4` (the script's existing, previously-undocumented-in-
practice `--workers` flag / `infra.feature_factory.workers` APR key) — completed cleanly.
**New gotcha for `docs/reference/gotchas.md` if not already there:** this script's default
worker count is unsafe for a full 14-symbol multi-timeframe recompute on this machine's
available RAM; use `--workers 4` for any recompute touching more than a handful of symbols at
once.

**Reconciled todo-level and phase-level prioritization into one view** (user requested this
explicitly) — the two tracks (`.planning/todos/PRIORITIES.md` P0-P3 tiers and ROADMAP.md's
phase queue) had never been merged into a single ranked view before. Five tiers, written into
this file's "Next actions" section above: Tier 1 (todo 160/147 close-out, then Phase 148
execution) → Tier 2 (Phase 163/162 execution, todos 088/168/169/170, all ready and independent
of 148) → Tier 3 (Phase 145/165, need planning first) → Tier 4 (Phase 147 + the full P2/P3 todo
backlog, real value but not urgent) → Tier 5 (Phases 149-159, explicitly gated behind Phase
148's verdict per "prove edge before production infra" — v4.0-adjacent scope with zero
planning artifacts, should not get planning time yet).

**Next actions, in order:** see this file's "Next actions" section under Project Reference
(the reconciled Tier 1-5 view) — do not re-derive a separate list here.
