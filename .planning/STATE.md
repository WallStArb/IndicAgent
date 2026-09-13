---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: milestone_complete
last_updated: "2026-09-11T00:00:00.000Z"
---

# Project State

## Strategic Plan (read this first)

**Cross-TF signal correlation screen, 2026-09-13 — real decorrelation found for
momentum, but a wrong-feature-choice detour along the way.** Continuing the TF-stack
scoping thread: Fable's recommended cheapest first test (before any fusion
infrastructure gets built) was to check whether coarse-TF and fine-TF reads of the
same signal decorrelate (worth a real pre-registration) or just re-express the same
information at a different sampling rate (Phase 148's own already-measured 100% sign
co-firing across 15m/1h/1d for `alpha_score` — the reference "dead" pattern).
**First run used `ctf_momentum` and returned a suspicious EXACT 1.0000 correlation
between 15m and 5m — investigated rather than reported, and it revealed a real
architectural fact:** `ctf_momentum` ("Cross-TimeFrame momentum") is not TF-native at
all — per `ctf_higher_tf_map` in `feature_factory.py` (`{"5m":"1h","15m":"1h","1h":"1d","1d":"1d"}`),
it's a higher-timeframe value read down into lower-tf rows via a bisect lookup (5m and
15m both read the literal same 1h value). **This means the codebase already has a
working cross-TF broadcast mechanism at the feature-computation level** — corrects an
earlier same-session claim (made to the user and to Fable) that zero cross-TF fusion
exists anywhere in the architecture; that was only true at the `alpha_score`/
`ensemble_trainer` level, not the feature level. Swapped in `momentum_z_fast`
(verified TF-native, no ctf/htf dependency) and re-ran clean:
**`momentum_z_fast` 1d-vs-15m correlation is -0.004, 1d-vs-5m is -0.031, sign agreement
48-49% — essentially coin-flip, real decorrelation, NOT the Phase-148 re-expression
pattern.** `range_pct_fast` (unaffected, always TF-native) shows moderate correlation
(0.66-0.86) with sensible decay by TF distance. **Caveat, stated plainly, not
smoothed over: decorrelation is necessary but not sufficient for fusion to add
tradeable value — it only means the two reads aren't redundant, not that either one
(or their combination) is predictive.** This clears Fable's stated first bar (worth a
real pre-registration on the DIVERGENCE framing specifically, not a generic
"combine timeframes" construction) — it does not clear the bar itself. Not yet
pre-registered or built; per Fable's own guardrail, this competes for priority against
universe expansion rather than preceding it by default — a resourcing call for the
user, not decided here. `scripts/analysis/cross_tf_signal_correlation_screen.py`
(script's own docstring documents the ctf_momentum detour and correction in full).

**Data-integrity incident, 2026-09-13: 10x spread-cost bug in the kill criterion's
foundational verdict, found by direct user challenge, verdict UNCHANGED after
correction.** User directly disputed this session's cost assumptions ("execution costs
are near free... assume minimal costs") rather than accepting the hurdle framing at
face value. Decomposing the cost model in response surfaced a real bug:
`range_pct_fast_xs_ls_h5_falsification.py` — the script behind Pre-registration 1, one
of the two formal pre-registered results the 2026-09-12 kill criterion rests on — had
`_LIVE_SPREAD_ANCHOR = 0.0014` (14bp) instead of `0.00014` (1.4bp), a 10x transcription
error. The exact same bug `personal_edge_paper_screen.py` had already caught and fixed
in itself on 2026-09-02; the fix never propagated to this sibling script. Sat
undetected 11 days — through an AGY adversarial design review, the 2026-09-11
graveyard reconsideration (which cited this verdict as "confirmed settled" without
re-deriving it), and two same-day reuses of this exact file's `_build_phase` earlier
the same session it was finally caught. Fixed in source; the entire original
falsification was re-run end to end at the corrected value. **Verdict unchanged: still
DEAD** — all 9 cost combos still fail CI>0, stability still fails on the same
qualitative shape — but every point estimate moved meaningfully more favorable
(cheapest-corner mean: ≈−1bp → +1.85bp; subperiods: −9.7/−12.1/+8.7bp →
−3.9/−6.4/+14.2bp). `concept_registry` migration 335;
`docs/research/methodology-change-ledger.md` E12 (full incident record);
`docs/research/construction-verdict-ledger.md`'s `range_pct_fast_xs_ls_h5` row. Checked
all 5 scripts sharing this constant — only the one was affected, now consistent
everywhere. **This does not reopen the fired kill criterion** — the correction made the
evidence for DEAD slightly weaker in magnitude but not different in conclusion — but it
is a real reminder that every number in this program's record should be treated as
provisional until independently re-derived, not just cited from a prior session's
summary, no matter how many reviews it already passed.

**TF-stack economics for universe-expansion scoping, checked 2026-09-13 — holding
period, not TF granularity, is the real constraint.** User question ("do we need to
reduce TFs? is 5m/1m really useful?") prompted extending workstream 0b's personal cost
hurdle to the intraday tiers for the first time (it had been hardcoded `tf='1d'` since
2026-09-02 — nobody had ever tested whether 5m/15m/1h signal survives THEIR OWN
turnover costs, only whether they clear raw FDR significance, which all four tiers do
comparably: 5m 2.05%, 15m 1.87%, 1d 1.75%, 1h 1.22%). Fable consulted first, recommended
exactly this check before deciding anything either way.
`scripts/analysis/personal_cost_hurdle_by_tf.py` (reuses 0b's live-validated 1.4bp
spread anchor; generalizes turnover measurement and annualization from calendar days to
tf-native bars; compares against the real measured avg IC at each tf's own
`lookahead_bars` already used in `feature_ic_scores`, not assumed values). **Every tf
shows the identical shape**: short holds fail catastrophically (5m @ 1 bar: IC_min
25-63x the measured IC; 15m @ 1 bar: 5-13x; 1h @ 1 bar: mixed), and the hurdle collapses
as horizon lengthens (5m @ 39 bars ≈ half day: clears with 1.2-3x margin; 15m @ 10 bars
≈ 2.5hr: clears everywhere; 1h @ 20-60 bars ≈ 3-10 days: clears with 18-100x margin) —
the exact same shape 0a/0c already found at 1d, just replicated at finer granularity.
**Conclusion: TF granularity itself is not the uneconomical thing; ultra-short holding
periods are, at any granularity.** 5m as a data/feature tier is not dead weight — a
half-day-hold 5m-tier construction clears its own economics with real margin. Cutting
5m outright (the naive reading of the cost-pressure argument) would be wrong; a sharper,
cheaper move for universe-expansion scoping is to stop MEASURING (not computing) the
short-horizon cells that structurally can never clear personal-scale costs at any tf
(H=1 bar everywhere, H=6/12 at 5m) — real compute savings without losing anything of
economic value. Not yet acted on; a scoping input for the universe-expansion phase, not
itself a phase or a construction verdict.

**Council review of the fired gate, 2026-09-13 — verdict stands, all three follow-up
threads closed.** A 4-seat adversarial review of the 2026-09-12 firing raised
objections, then actually resolved every checkable one rather than leaving them open:
(1) confirmed the 0c hurdle is NOT a tautology — minimum |IC| across the full 554-cell
FDR-passing population is 0.023, ~5-7x the hurdle floor, closed for good; (2) ran the
"near-free" TSMOM per-symbol screen this program's own proposal doc flagged but never
executed — **decisive negative**, mean IC negative across pooled/single-name/ETF
splits, 0 symbols qualify BY-FDR at any split — closes the "did we try a structurally
different construction type" gap; (3) `range_pct_fast`'s single-name-only beta-
contamination lead (β=0.91/R²=0.44 vs. pooled β=1.14/R²=0.75) was taken all the way to
a proper AGY-reviewed pre-registration (Pre-registration 3) — **DEAD on the stability
criterion**: subperiod 2 (2013-2019) net -1.14bp at anchor cost, verified directly
against the locked formula (AGY's own specific numbers were wrong but its qualitative
call — criterion fails — was right). Verdict `range_pct_fast_xs_ls_h5_single_name_only`,
migration 334, todo 375 completed. **Three distinct construction paradigms (pooled
cross-sectional, single-name-only cross-sectional, per-symbol time-series) have now all
failed on this corpus** — the "universe expansion is primary" resourcing call stands on
materially firmer ground than at the 2026-09-12 firing. Survivorship bias (100% of the
231-symbol universe is `is_active=true`, zero delisted-name representation, verified
live) stays genuinely unresolved — no new data gathered, no owner assigned beyond "flag
before citing any IC number as a hard ceiling."

**Personal-scale decision gate: KILL CRITERION FORMALLY FIRED 2026-09-12 (rule 3).**
Full evidentiary record and verdict text: `docs/plans/2026-09-02-personal-scale-edge-
determination-plan.md`'s "3 — Decision gate" Results section (appended 2026-09-12).
Summary: 14 constructions now run to a definitive verdict since this program's
pre-registration discipline began, zero PASS — both of the program's own formal shots
(decision rule 2's one-shot `range_pct_fast_xs_ls_h5`: DEAD, market-beta tilt; todo
278's mandated `alpha_score_residual_single_security_15m` diagnostic: FAIL, real but
0/231-concentrated) failed under full falsification machinery (shuffled null,
bootstrap CI, BH-FDR, stability), and the 2026-09-11 graveyard reconsideration closed
3 of its 4 remaining items decisively (the 4th has no candidate). Failures trace to
construction/economic reality (beta tilts, dilute common-factor effects, negative
gross P&L, regime-taxonomy-averaging artifacts), never to the cost hurdle, which 0b
showed has an order-of-magnitude of headroom throughout. **Verdict: "this corpus, at
breadth ~8 (0a's MP-K=7 IC-profile effective rank) and this TF stack (5m→1d), cannot
carry the endgame." Universe expansion becomes primary, via its own scoping phase —
not yet scoped.** A process-integrity gap surfaced while verifying the record before
firing — `bars_since_high_fast_xs_ls_h5`'s DEAD verdict (the gate's closing
candidate) rested partly on an uncommitted, unreproducible ad hoc analysis, unlike
this program's other four construction verdicts; backfilled into `concept_registry`
(migration 333) with the gap recorded honestly, remediation filed as todo 374 —
doesn't reopen the gate, which stands on the fully rigorous record alone. Explicitly
NOT closed by this verdict: N1 (structurally inconclusive, separate thread), todo 281
(feature recommendation, not a construction), H-A/H-B (separate track, own
pre-registration, unrun as of this gate — see its own status note below).

**Graveyard reconsideration plan (2026-09-11):** a Fable pass re-examined the 6
DEAD/settled graveyard constructions for genuinely untried refinements.
`range_pct_fast`/Phase 148 confirmed settled (natural refinement was already the test
performed, or the apparent significance was a selection artifact). Four items queued as
cheap (1-4 day), fast-kill-gated refinements: (1) bucketed `alpha_score_residual` retest —
**RESOLVED same day, FAST-KILL**: 8 sector buckets, 0/8 qualify, every raw bucket null_p
>= 0.15; both per-symbol and bucketed forms of condition (d) now exhausted, construction
closed. (2) regime-gated `bars_since_high_fast`/`bars_since_low_fast` — **RESOLVED same
day, CLOSED**: the cited "0.11 avg IC, 46-symbol support" premise
(`scripts/analysis/personal_edge_paper_screen.py`) decomposes into 5 FDR-passing
`feature_ic_scores` cells drawn from 4 structurally different `market_regimes.regime_group`
taxonomies (equity/commodity/rates/fx) averaged together as if comparable. The standout cell
(commodity `down_primary_backwardation`, IC=0.299) occurred on only 52 days across 16 years —
a handful of macro-shock episodes, not independent bets; stripping it out, the only
broad/robust cells (equity `mid_neutral`/`high_bear`, IC~0.04) sit barely above the
already-failed unconditional pooled IC. No regime-gate construction survives this
decomposition. (3) same-sector single-equity pairs screen for `cointegrated_pairs_residual`
— **RESOLVED same day, CLOSED**: `scripts/analysis/cointegrated_pairs_residual_same_sector_screen.py`
tested 471 economically-motivated same-sector single-name pairs (ITR `single_name_equity`
tag × sector, 20 sectors) via Engle-Granger + BY-FDR correction + OOS split-sample
reconfirmation, reusing the original 6-pair pilot's exact methodology. **0/471 qualify** —
0 even survive corrected Stage 1 alone. Far stronger than the original 0/6; per the
pre-registered fast-kill rule, cointegration is genuinely rare in this corpus/era regardless
of granularity — construction type closed for good. (4) `cross_sectional_relative_value`
construction-type reuse was gated on (2) or (3) producing a clean substitute feature — both
failed to produce one, so (4) has no current candidate and stays queued with no clear path
forward (not itself run). **All three executed items of the graveyard-reconsideration queue
(1/2/3) are now closed, all FAST-KILL/DEAD; only (4), which depends on a substitute neither
(2) nor (3) supplied, remains open with no obvious next step.** Full detail and effort
estimates: `docs/research/2026-09-11-strategic-plans-features-ensemble-construction.md`;
verdicts tracked live in `docs/research/construction-verdict-ledger.md`.

**Todo 372 (`Panel.sync_shift_null_p` panel-synchronicity bug), two findings, status
mixed:** finding 1 (per-symbol `k % m` shift silently desyncing the panel-wide null) is
FIXED in code (`scripts/analysis/alpha_score_residual_single_security_15m.py`, design:
Fable; TDD-verified via `tests/unit/test_alpha_score_residual_panel_sync_shift.py`, 3
passing tests) but has NOT had independent adversarial review — AGY and Codex were both
rate-limited the session the fix landed. Finding 2 (`volume_z` has no diurnal/
session-boundary detrending, affecting both H-A and H-B) is untouched. Todo stays open
pending both. Full detail: `.planning/todos/pending/372-panel-sync-shift-null-not-actually-panel-synchronous-plus-volume-z-diurnal-bias.md`.

**Universe/infrastructure note, 2026-09-11:** confirmed live that the 22 registered but
inactive futures/FX instruments (ES, NQ, CL, GC, VX, the Treasury/grain complex, 4 FX
pairs) have ZERO rows in `market_data_ohlcv` and `feature_vectors` — never backfilled,
despite existing as instrument metadata. Relevant to any multi-asset-class construction
(e.g. TSMOM, proposed in the strategic-plans doc above) and to any future "expand the
universe" discussion — the actual total instrument count is 253 (231 active equity-
structured ETFs + 22 inactive, data-empty futures/FX), not the ~350 previously assumed.
Server headroom for expansion: 24 cores, 29GB RAM + 150GB swap, 569GB disk free of 914GB —
disk is not the constraint, but compute time already is at the current scale (full
`ic_engine` recompute has run 66-77+ hours historically, needed emergency swap expansion
once this week).

**Update 2026-09-10, supersedes the 2026-09-09 note below on the recompute's status only
(nothing else changes):** the Workstream-1 `ic_engine` recompute this note describes
**COMPLETED cleanly, all 8 pipeline steps, 2026-09-10 04:30 UTC** (relaunched 2026-09-09
13:15 UTC after the migration 332 fix, ~15h elapsed). Step 6 (`ic_shrinkage`) hard gate
PASSED (34,877 cells, shrunk error 0.0458 < raw error 0.0486; `alpha.ensemble.ic_input`
flipped to `ic_shrunk`). Step 8 (`alpha_publisher`) emitted 68,323,631 rows, 0 rejected —
first clean run of this step since the todo-351 self-deadlock fix, no repeat. **The
decision gate (rule-3 kill criterion, [[project-personal-scale-edge-program]]) is now
unblocked and is the sole remaining step of the active program** — it has not been run
yet. Full detail: `project_corpus_pipeline_state` memory. Orphaned monitoring process from
the OOM-recovery work (PID 29213, a `pgrep -f`-based resource sampler that self-matched its
own command line and never saw its exit condition) found still running 3 days later and
killed 2026-09-10; harmless (just a stray `free`/`ps` loop) but a real bug pattern, see
`feedback_corpus_orchestrator_and_orphan_trap` memory.

**Update 2026-09-09, supersedes nothing below (additive status only):** the ACTIVE PROGRAM's
decision-gate-blocking `ic_engine` recompute hit two separate failures since 2026-09-03 and is
now running again — full detail in `project_corpus_pipeline_state` memory, not duplicated here.
Summary: OOM on `equity/5m/high_bear` (2026-09-07, fixed with swap headroom, todo 371), then a
clean `alpha.ic.max_cell_rows` failure on `equity/5m/mid_neutral` (2026-09-08, fixed via
migration 332 — the ceiling was stale relative to migration 331's equity-universe growth,
recalibrated from real evidence: this same run had already proven the box handles a 64M-row
cell). Relaunched 2026-09-09; all equity `5m` cells now clear, ~88 smaller-universe cells
(rates/commodity/fx) plus steps 6-8 remain before the decision gate can fire. Todos 369/370
(unrelated small fixes) closed same window; todo 372 (a real gap in shared null-test machinery,
`Panel.sync_shift_null_p` not actually calendar-synchronous across symbols with varying
active-date counts) filed, not yet fixed — found via a separate, unrelated pre-registration
(`docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md`, H-A/H-B,
explicitly NOT part of this program — see `project_extreme_volume_divergence_prereg_2026_09_09`
memory for that track's own status). New: `docs/research/construction-verdict-ledger.md`
consolidates every construction/hypothesis this project has run to a definitive verdict —
check there before recommending a new candidate or re-deriving the project's track record from
scattered memory.

**Resolved 2026-08-07: Phase 167's cross-sectional construction (`cross_sectional_relative_value`)
does NOT survive re-measurement under the corrected `ctf_momentum` join. Both Validation Gates
FAIL at authoritative tier, real production path, OOS window (3,803 bars / 147 day-clusters).**
Gate 1: `ci_lower` doesn't clear zero at either scale, `null_p` 0.65-0.99 (observed spread beaten
by up to 98.6% of random-ranking draws). Gate 2: no residual survives at 95% CI after removing
the static-tilt benchmark. This retracts Phase 167's original "COMPLETE, both gates PASSED"
verdict and `nonlinear_interaction_combiner`'s original "substantial edge" claim — the small
residual `nonlinear_interaction_combiner` still shows is a separate, already-tracked thread
(`docs/research/measurement-nonlinear-interaction-combiner.md`), not resurrected by this result.
Full numbers: `logs/construction_verdicts/gate1_latest.json` / `gate2_latest.json`.

**Fork resolution (decided in advance, not re-litigated): back to discovery, not construction.**
Phase 168 (cost-hurdle spread refinement) and Phase 156-159 (execution/sizing) stay blocked —
not "unverified," actually FAILED; do not start either without an independently-proven
construction first. Priority is the untested Signal-Extraction candidates below.
**Expectation to hold, not a consolation-prize framing:** every "large" edge found in this corpus
has collapsed 44-91% once a leak was corrected, with a small real residual surviving each time —
consistent with Renaissance's own actual history. The win condition is a confirmed small edge
with a clean gate record, not a big trade.

**Discovery track: 5/5 candidates run to a definitive verdict now DEAD, closed 2026-09-01.**
4 cheap Signal-Extraction candidates (`jump_diffusion_decomposition`, `cointegrated_pairs_
residual`, 2 Trade Construction theses) came back DEAD earlier —
`project_discovery_track_pilot_results_2026_08_07` memory. **`statistical_factor_residual`**
(the harder, K-selection-gated candidate picked next) also now DEAD: Stage 3 (IC
falsification vs. `ctf_momentum`, 3 measurement axes, run 2026-09-01) found residualizing
away the top-K statistical factors did not improve IC on any axis — if anything pulled it
toward zero. Full detail: `docs/research/measurement-statistical-factor-residual.md`. Per
that memory's own standing instruction, this is the point to surface the pattern before
starting a 6th candidate, not mechanically continue down the list. Two more per-symbol
regime candidates (todo 303 trend, todo 304 percentile-rank) also CLOSED DEAD 2026-09-01:
Stage 3 (falsification + null-arm, 20-test pooled BH-FDR family across both todos' 5
candidates × 2 xbar columns × 2 timeframes) found none of `hurst_rank`/`autocorr_rank`/
`volatility_pct`/`skew_tail`/`volume_pct` sharpens IC beyond `regime_volatility` at 5m or
15m — one cell cleared the raw null-arm bar but failed BH-FDR correction, exactly the
multiple-comparisons false positive the design exists to catch. Full detail:
`docs/research/measurement-per-symbol-trend-regime.md` and
`docs/research/measurement-per-symbol-percentile-rank-candidates.md`. **This closes all
three items from this session's discovery-track sequencing** — every candidate queued
coming into this session is now resolved (DEAD or, for N1, confirmed-structural-inconclusive).

**ACTIVE PROGRAM (2026-09-02): personal-scale edge determination —
`docs/plans/2026-09-02-personal-scale-edge-determination-plan.md`.** User-approved after
council review; replaces candidate-hunting as the research priority. Shape: (0a) feature-
library dimensionality, (0b) pre-registered personal hurdle function with horizon as a
first-class axis, (0c/todo 367) paper placement of already-measured signal mass, (1)
coverage fix (todos 280+283), (2) todo 278's ready diagnostic, (3) a pre-registered
decision gate with an explicit kill criterion ("corpus at breadth ~8 cannot carry the
endgame" → universe expansion becomes primary). Driving observation: measured signal mass
at 1d roughly doubles from 1d to 5-10d horizons (62→162 FDR cells) and lives in the
range/vol family, while turnover there is 5-10x lower — the hurdle is easiest exactly
where mass peaks. Gate structure unchanged (null-arm/BH-FDR/pre-registration); the
ruler's constants are recalibrated personal-scale, pre-registered before use.

**Todo 364 (N1 fresh re-run) CLOSED 2026-09-01.** Re-ran N1-a-capped @ 1h at both
colsample_bytree values (0.10, 0.05) — both reproduced their original 2026-08-25 numbers
bit-identically (point_diff/ci/p/fold-breach/row-counts all matched exactly), traced to
todo 366's live-ingestion gap (corpus hasn't grown since before N1's original run). Verdict:
the colsample-sensitivity instability is confirmed structural, not a staleness artifact —
still not resolved which value (if either) is "correct," and won't be until the corpus
actually grows or a differently-designed fix is built. Full detail:
`docs/research/measurement-nonlinear-interaction-combiner.md`'s "N1-a-capped @ 1h fresh
re-run" section.

**Live ingestion gap found closing this thread, filed as todo 366 (P2), explicitly NOT
urgent per user direction 2026-09-01:** the corpus has decades of history and no proven edge
yet to protect, so live-ingestion freshness doesn't gate research value — corrects the
"RESOLVED 2026-08-31" framing in `project_ibkr_live_ingestion_stalled_2fa` memory (the
gateway libgtk3 fix was real, but the 5 consumer services that write bars were never
restarted; most of the universe has had zero new bars since 2026-08-12). A backfill to
bring OHLCV current is optional/later, not blocking. Todo 366 itself was routed around, not
fixed, for Stage 3: `_fetch_universe`'s "zero tolerance for any gap date" rule was tripping
on the resulting gap dates, fixed by excluding those specific dates (not interpolating) —
see the research doc's Stage 3 section for the corrected universe/K.

**HMM per-symbol lookahead bug (todo 248): fix built + TDD-tested, NOT deployed.**
`regime_writer.py`'s `_compute_symbol_tf` fits `GaussianHMM` parameters once on the entire
(symbol, tf) history before causally decoding — a real causal-law violation, confirmed large at
3 symbol/tfs (24.9-56.8% label agreement vs. an expanding-window-refit baseline, vs. 20-22%
chance). The walk-forward fix (`_walk_forward_hmm_labels`/`_seed_prior_from_label`/
`_hmm_seed_stability_check`) is built and tested but not wired into the live path. **User
directive: deploy regardless of Gate 4's own negative ordinal-IC result** — this is a confirmed
causal-law violation in an existing mechanism, not a new/unproven signal subject to "prove before
promoting." Blast radius matches an `HMM_RANDOM_STATE` change (full regime + downstream `ic_engine`
recompute); was queued behind the CTF-leak work, which has since cleared — re-evaluate scoping
this as its own phase via `/gsd-discuss-phase`. Full detail: `.planning/todos/pending/
248-hmm-full-history-fit-regime-label-instability-gate4-pilot.md`,
`docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md`.

**Corpus pipeline: the post-Phase-173 recompute (all 8 steps) COMPLETE as of 2026-08-31 —
see [Corpus pipeline state](project_corpus_pipeline_state.md) for full detail, not
duplicated here.** All three discovery-track threads above were blocked on this recompute
finishing; re-verify each one's specific prerequisite directly before assuming unblocked
rather than inferring it from the pipeline's completion alone.

**Priority ordering for the rest of the backlog: `.planning/todos/PRIORITIES.md` is the sole
authoritative source, not duplicated here.** A tiered-priority snapshot pasted into this file
went stale every single time it was tried (confirmed repeatedly through 2026-08-08) — don't
recreate that pattern. Idea-level scoring: `docs/research/intelligence-lifecycle-backlog-matrix.md`.

**Current focus: Phase 173 (broadcast-feature-significance-correction) SHIPPED COMPLETE
(2026-08-26), full corpus recompute COMPLETE (2026-08-31 12:16 UTC).** 4 plans/3 waves
executed, merged, live-smoke-tested, independently re-reviewed (codex+agy, no blocking
findings), `/simplify` pass done. The full corpus recompute Phase 173's own fingerprint
change required (`ops_corpus_pipeline_run.sh --from-step 4`, launched 2026-08-27) ran all 8
steps end to end — `alpha_events` now carries Phase-173-corrected numbers for all 38
broadcast features, including `hyg_lqd_ret_z`/`tip_tlt_ret_z`. A real self-deadlock bug in
`alpha_publisher.py` (todo 351) was found and fixed along the way. Full detail:
`project_phase173_broadcast_significance_complete` and `project_corpus_pipeline_state`
memories. Exit-cluster todos 227/285/287/335/351/306 all individually verified and closed
2026-08-31; 292 was NOT touched by this recompute (started at step 4, not `regime_writer`)
and remains open.
Separately that session: the `ic_engine --cross-sectional-only` run completed 2026-08-25
(144,232 rows, covers the corrected commodity/fx labels from todo 335); N1
(`nonlinear_interaction_combiner`'s residual-form test) ran and came back genuinely
inconclusive (result flips sign of significance between adjacent parameter choices at 1h) —
don't cite as pass or fail either way, see
`project_n1_nonlinear_combiner_and_feature_phase_audit_2026_08_25` memory.

**Checked 2026-09-01: neither the Phase 173 recompute nor todo 335's fix reopens any
previously DEAD/inconclusive discovery-track verdict.** Verified in code, not assumed: the 4
DEAD discovery pilots and T2 (`regime_conditional_persistence`) have zero dependency on any
broadcast column or `regime_group`; Phase 167's construction trains on `ctf_momentum` alone
(already re-verified post-fix); N1 trains on ~248 columns including the broadcast set but
never touches `ic_engine.py`'s significance test (the only thing Phase 173 changed) and is
equity-only (todo-335-irrelevant). N1's own "inconclusive" verdict is still worth a fresh
re-run given ~3 weeks of real corpus churn since it ran — filed as todo 364, not a blanket
re-run-everything pass. Phase 151's Waves 6-7 (interaction IC sweep, paused behind this same
corpus pipeline) are also now unblocked — see ROADMAP.md's Phase 151 entry.

**Phase 148's Gate 1 (signal proof) PASS but Gate 2 (execution proof) FAIL** — do not promote the per-symbol directional
construction to live capital. A refinement plan using Phase 163-165's features has its 3 gating
items resolved: [276](../todos/completed/276-phase163-165-lookahead-causal-safety-audit.md)
lookahead/causal-safety audit CLEAN; [277](../todos/completed/277-alpha-score-concentration-cofiring-degeneracy-diagnosis.md)
`alpha_score` is substantially a disguised common cross-sectional factor, not real per-symbol
breadth (100% same-direction at 15m/1h/1d), though the demeaned residual carries real small
signal where the raw score has ~zero; [278](../todos/completed/278-oos-protocol-gate-relook-decision-phase163-165-features.md)
a residual-stripping construction is materially different from Phase 148's original verdict and
earns its own new `gate_id`, conditional on first clearing a diagnostic-tier test (day-clustered
bootstrap/shuffled-null/BH-FDR at 15m) — that test is the next real action if this plan proceeds,
not yet filed as its own todo.

`regime_conditional_persistence` is CONFIRMED DEAD (270 cells tested, zero pass on corrected
labels). `nonlinear_interaction_combiner` has a small real residual surviving the CTF-leak
correction at all three affected tfs (collapse 90.6%/79.1%/43.8% at 1h/15m/5m, residual growing
finer as tf gets finer) — full numbers in the CTF memory cited above. This line previously
(stale, corrected 2026-09-01) listed `cointegrated_pairs_residual`/`jump_diffusion_
decomposition`/`statistical_factor_residual` as "remaining untested" — all 3 are now DEAD (see
discovery-track paragraph above). The two genuinely still-untested Signal-Extraction
candidates are `cross_asset_lead_lag` (waits on `stale_reference_price_adjustment` running
first) and `adaptive_combiner_weights` (gated on a data-availability trigger) — full theses:
`docs/research/data-edge-source-thesis.md`. Phase 144/143.1/162/163/164/165/167 are all
COMPLETE — see Phase Summary table below.

**Execution plan:** `docs/plans/archive/2026-06-30-alphaengine-v1-execution-plan.md`

## v3.0 Phase Summary (SHIPPED 2026-06-25)

| Phase | Name | Status |
|-------|------|--------|
| 137 | Feature Factory | COMPLETE (7/7 plans, 2026-06-21) |
| 138 | IC Engine + Forward Returns | COMPLETE (9/9 plans, 2026-06-23) |
| 139 | Ensemble + Alpha Emission | COMPLETE (3/3 plans, 2026-06-24; 14/14 verification truths) |
| 140 | IC Engine Correctness | COMPLETE (4/4 plans, 2026-06-25) |

## v3.1 Phase Summary (SHIPPED 2026-09-02)

| Phase | Name | Status |
|-------|------|--------|
| 140.5 | Corpus Foundations + Feature Governance | COMPLETE (5/5 plans) |
| 141 | Corpus Quality Gate + IC Validation | COMPLETE (3/3 plans) |
| 141.1 | Measurement and Decision Integrity Foundation | COMPLETE (4/4 plans) |
| 142A | Ensemble IC Measurement | COMPLETE (2/2 plans) -- EIC-04 current verdict PASS 54/1425=3.79%, see [Corpus pipeline state](project_corpus_pipeline_state.md) for the live number |
| 142B.1 | Ensemble Weighting Methodology | COMPLETE (5/5 plans) -- E1 (shrunk-IC) is champion; E2 (mean-variance) rejected |
| 142.5 | Renaissance Primitives | COMPLETE (8/8 plans) -- 89 primitives live in Feature Factory, 150 total `FeatureVector` fields |
| 142B | Frame Simulation + Counterfactual Tracking | COMPLETE (2/2 plans) -- `alpha_frames` hypertable + `AlphaFrameWriter` + `CounterfactualTracker` live |
| 143 | Feature Lifecycle Routing (merged with 149B) | COMPLETE (3/3 plans) -- `feature_registry` evidence-based promotion/demotion + `integrity_monitor` table live (retired into `concept_registry` by Phase 170) |
| 143.1 | Measurement and Eligibility Integrity | COMPLETE (8/8 plans, 2026-07-21) -- 143.1-08 shadow-mode validation VERDICT: HOLD (`alpha.ensemble.sign_symmetric` stays false) |
| 144 | Cross-Sectional Regime Model (`regime_group`) | COMPLETE (6/6 plans, 2026-07-22) -- D-05 verdict: F1 not triggered (TLT HMM stays deficient, demotion holds), F2 triggered for 15m/5m (rates cross-sectional also deficient there) |
| 146 | Empirical Instrument Tag Calibrator | COMPLETE (5/5 plans, 2026-07-17) -- `TagCalibrator` live-verified: 11/12 measurable tags carry real `source='empirical'` rows |
| 160 | Concept Registry MVP | COMPLETE (4/4 plans) -- 4-table schema + `ConceptRegistryService`/`ConceptRegistryAPI`/`ConceptRegistryDashboard` live |
| 161 | Controlled Vocabulary System | COMPLETE (4/4 plans, 2026-07-18) -- schema + `VocabularyService` + `vocabulary_drift` audit + `/api/vocabulary/{namespace}` route, live-verified |
| 148 | Alpha Scoring System (OOS Proof Gates) | COMPLETE (5/5 plans, 2026-07-22) -- the proof-of-alpha milestone: Gate 1 PASS, Gate 2 FAIL, VERDICT do not promote to live capital; `docs/plans/archive/2026-07-22-phase148-promotion-decision.md` |
| 162 | ic_engine Corpus Pipeline Throughput | COMPLETE (4/4 plans, 2026-07-23) -- whole-cell fingerprint mechanism, equivalence-proven |
| 166 | Frame/Execution Recalibration | COMPLETE (6/6 plans, 4 waves, 2026-07-23) -- baseline and scalar candidates FAIL gate166 decisively; structural candidate halted pending Phase 163 |
| 163 | VP/SR Structural Primitives | COMPLETE (3/3 plans, 2026-07-24, verification 15/15 must-haves) -- closes todo 153 |
| 167 | Cross-Sectional Trade Construction (cross_sectional_relative_value) | COMPLETE (6/6 plans, 2026-07-27) -- **original verdict RETRACTED, re-verified 2026-08-07: both Validation Gates FAIL** (todo 243's lookahead-leaked join). No live construction. See Strategic Plan section. |
| 168 | Cost-Hurdle-Adjusted Spread Construction (Phase 167 follow-on) | BLOCKED, not executed -- plans execution-ready but no live construction left to refine. `docs/research/trade-construction-layer.md` |
| 169 | Symbol State Query Layer | NOT PLANNED -- design doc only (`docs/research/intel-symbol-state-query-layer.md`), needs a fresh live-verification pass before planning (its "What Exists" section is a dated 2026-07-31 snapshot, now stale on row counts). |
| 170 | Concept Registry Feature-Domain Migration (`feature_registry` retirement) | COMPLETE 2026-08-10 (migration 311) -- `feature_registry`/`feature_transition_log` DROPped, `concept_registry` sole feature-lifecycle system. |
| 171 | HMM Walk-Forward Regime Labeling, Parameter-Lookahead Fix | COMPLETE 2026-08-08 -- walk-forward fitting procedure wired; root-cause investigation found production's `regime` label is a volatility partition mislabeled as trend (non-identifiability). Composite-label rollout WITHDRAWN. `171-FINAL-VERDICT.md`. |
| 172 | HMM Regime -- Volatility-Only Redesign | COMPLETE 2026-08-09 (v3.1's final phase) -- `regime_volatility` column live (migration 307), K=3, calm/elevated/turbulent vocab, replaces the trend-mislabeled `regime` column for stratification. |
| 164 | SMC Institutional Footprint Primitives | COMPLETE (4/4 plans, 2026-07-28) -- all 36 SMC `FeatureVector` fields real in both `compute()`/`compute_batch()`. |
| 165 | Swing/Fib/Trend/Session Structure Primitives | COMPLETE (5/5 plans, 2026-07-28) -- 41 new columns (swing/trend/momentum/fib/session), all float\|None, zero raw price levels. |

Current row counts and every downstream measurement number live in
[Corpus pipeline state](project_corpus_pipeline_state.md) -- that file is the single source of
truth; don't duplicate counts here.

**Dual regime system (both live):**

- `feature_vectors.regime` -- 5 per-symbol HMM labels (trending_down/transition_down/ranging/transition_up/trending_up), written by `regime_writer.py` (K=5, causal forward-filter). **Confirmed a volatility partition mislabeled as trend, not a genuine trend signal (Phase 171 verdict) — `regime_volatility` is the corrected replacement for stratification.**
- `market_regimes` -- cross-sectional labels keyed by `regime_group` (a named peer group with a pluggable regime signal: `breadth_vol` for equity, `curve_credit` for rates; commodity/fx modules ship enabled since migration 306). `cross_sectional_regime_model.py` (Phase 144) is the writer; `ic_engine` stratifies on these.

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

Phase-by-phase planning narrative (wave breakdowns, cross-AI review findings, plan-count
history) has been compressed out of this section — each phase's authoritative verdict lives in
the Phase Summary table above, and the full planning/execution record for any COMPLETE phase is
in its own `.planning/milestones/v3.1-phases/<N>-*/` directory (archived at milestone close 2026-09-02; future phases create fresh dirs under `.planning/phases/`) and `docs/foundation/`/`docs/research/` docs, not
duplicated here. Currently open/not-yet-planned phases, compressed to current status only:

- **Phase 169** (Symbol State Query Layer): design doc only, `docs/research/intel-symbol-state-query-layer.md`. Not planned. Needs its own live-verification refresh before planning (flagged stale 2026-08-21 -- its "What Exists" section's row/symbol counts predate the universe expansion to 231 symbols).
- **Phase 168** (Cost-Hurdle-Adjusted Spread Construction): plans execution-ready but blocked indefinitely -- Phase 167 has no live construction left to refine (see Strategic Plan section). `docs/research/trade-construction-layer.md`.
- **Phase 151** (Feature Primitives Expansion + Interaction Layer): waves 1-5 (7/9 plans) executed 2026-08-05, `FeatureVector` 249→292 fields. Waves 6-7 (corpus recompute + interaction IC sweep) intentionally paused, sequenced behind the corpus pipeline finishing rather than run twice.
- **Phase 145** (StratificationDimension Formalization): unblocked but not planned, not currently prioritized.

## Session

**This section has a recurring pattern of going stale the moment GSD-phase-level work pauses**
(confirmed 3 times: 2026-07-31, 2026-08-09, 2026-08-14) -- narrative left here gets superseded by
the Strategic Plan section and rots undetected. **Check the Strategic Plan section at the top of
this file first, always** -- it is the one kept live. GSD-phase-level work has been idle since
Phase 172 (2026-08-09); activity since then has been discovery-track research and ops/incident
work, which doesn't flow through the phase-execution loop this section exists to track. Resolved
incident narrative belongs in memory (e.g. `project_disk_full_incident_2026_08_13`) or git log,
not here.
