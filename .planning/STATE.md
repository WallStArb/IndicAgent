---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: AlphaEngine Validation + Alpha Scoring
status: ready_to_plan
last_updated: 2026-07-10T12:17:09.819Z
progress:
  total_phases: 9
  completed_phases: 5
  total_plans: 24
  completed_plans: 22
  percent: 56
stopped_at: Phase 142B complete (2/2) — ready to discuss Phase 143
---

# Project State

## Project Reference

See: .planning/PROJECT.md

**Core value:** Alpha must be demonstrated empirically before any ensemble weight is assigned.
**Current focus (updated 2026-07-10):** Phase 142.5 (Renaissance Primitives) COMPLETE (8/8 plans, 2026-07-07; 89 primitives/150 total `FeatureVector` columns). The 6th corpus rebuild (2026-07-09) completed clean end-to-end — full history of the 5 prior failed attempts and the 2 blockers hit mid-run in ROADMAP.md's Phase 142A EIC-04 Verdict Log and [Corpus pipeline state](project_corpus_pipeline_state.md).

**2026-07-09/10 (this session): a Renaissance-council-style rigor audit of the corpus's own measurement machinery found and fixed a real eligibility-gate bug, then closed the loop on live data.** `ensemble_trainer.py`'s 3 eligibility queries and `ensemble_ic_engine.py`'s EIC-02 `hold_max_bars` gate required cross-sectional significance (`ic_ci_lower>0, passes_fdr=true, reliable=true`) but never `passes_walkforward=true`/`walk_forward_stable=true` — 36% of "qualifying" `feature_ic_scores` rows had never been confirmed out-of-sample, and EIC-02 had drifted out of sync with EIC-04's own (correctly gated) query. Fixed, commit `3c1b2649` (shared `_ELIGIBILITY_WHERE`/`_QUALIFYING_FLAGS` constants so the criterion can't drift a third time). Separately traced and ruled out `regime_writer.py`'s per-symbol HMM look-ahead leak as the cause — real in code, confirmed not live (`equity_model_enabled=true` routes measurement through the cross-sectional model instead; see todo 026). Regenerated the full downstream chain under the corrected gate: `ensemble_trainer` → `alpha_publisher` (`ensemble_weights` 251→193, `ensemble_alpha` 33.2M→32.9M, `alpha_events` 12.26M→11.81M) → `EnsembleICEngine` re-measured; reverted 6 `hold_max_bars` cells across 2 rounds that were stale from intermediate not-fully-fixed states (final: 11/36 genuinely walk-forward-confirmed, 25/36 correctly on `[initial_estimate]`). **EIC-04 PASS, 54/1425 = 3.79% qualifying** (supersedes 2026-07-09's 35/1585=2.21% — first verdict computed against a fully mutually-consistent corpus). Full detail: ROADMAP.md Phase 142A EIC-04 Verdict Log, 2026-07-09/10 entry.

**Phase 142B (frame simulation) is now COMPLETE (2026-07-10, 2/2 plans executed and verified).** `alpha_frames` hypertable (migrations 214+215) + `AlphaFrameWriter` + `CounterfactualTracker` built; code review found 2 blockers (unguarded zero-ATR division that would abort and discard an entire scan; `target_r_multiple` not snapshotted, risking the same historical-drift class of bug already fixed for `cost_r`) plus 5 minor findings — all 7 fixed and independently verified in code (commit `fa4208ef`). `docs/plans/SHADOW-REVIEW.md` (frozen Phase 147 promotion criteria) committed, gaining two edge-case clauses during the fix pass. `alpha_frames` has 0 rows — running the writer/tracker against the historical corpus and evaluating the FRAME-04 gate is Phase 147/ops-run territory, out of this phase's scope. Full detail: [Phase 142B code review and fixes](project_phase142b_code_review_fixes.md).

Separately: Phase 142B.1 machinery is complete (verified 2026-07-04) but the E1/E2 A/B judgment (`ops_ensemble_weight_compare.py`) still hasn't been run — it flags a winner's-curse caveat on every WIN verdict (commit `ac9e7f25`, todo 069) since OQ7's peer-group-for-shrinkage question is still genuinely unresolved. Phase 144 (Cross-Sectional Regime Model) is unblocked for `/gsd-discuss-phase` — its HMM weak-separation fallback decision was made 2026-07-08 (see `docs/research/fable-2026-07-07-phase144-conditioning-decision.md`), though its own evidence needs re-measuring against the current corpus. A large backlog of Renaissance-refinement proposals (todos 068-085) was filed 2026-07-08 from a full layer-by-layer Fable review — none urgent. Test-debt cleanup landed 2026-07-09: 22 pre-existing `tests/unit/` failures reduced to 1 (already-tracked todo-086 false positive).

**Next actions, in order:** (1) Phase 143 (Feature Lifecycle Routing, merged with 149B) is the next unstarted phase in ROADMAP.md order — `/gsd-discuss-phase 143` to start; (2) separately, run the E1/E2 A/B judgment (`ops_ensemble_weight_compare.py`) whenever convenient — not blocking anything; (3) todo 026 flags two candidate (non-bug) explanations for the corpus's remaining regime-conditional IC tail worth a look eventually: FDR-tail concentration (expected, not actionable) and P3's still-uncalibrated `equity_regime_model.py` cut points (`vix_low_pct`/`vix_high_pct`/`breadth_bear`/`breadth_bull`, still guessed defaults, never empirically fit) — the latter is a real, bounded, currently-open todo worth prioritizing.
**Execution plan:** `docs/plans/2026-06-30-alphaengine-v1-execution-plan.md`

## v3.1 Current Status

**Phase 141 — Corpus Quality Gate + IC Validation:** ✅ COMPLETE 2026-06-29

- P0: validity fixes (V1 look-ahead bias, V3 JSONB codec) + corpus rerun
- P1: IC validation — gate FAIL: 5m=0 qualifying features, 1h=23 qualifying features
- P2: HMM JIT 40x speedup shipped

**Phase A — IC Engine Methodology Fixes + Gate Redesign:** ✅ COMPLETE 2026-06-30

- A1: 5m IC failure root cause — gate design bug, not signal absence (721 cells with ic_ci_lower > 0)
- A2: IC engine methodology fixes (WF fold construction, corpus-level BH-FDR, scale-specific embargo, direct-linkage clustering)
- A3: APR compile-time binding for ic_engine + ensemble_trainer
- A4: CANCELLED — Renaissance principle: never delete signal candidates; shadow/demote/promote handles this
- A5: Renaissance IC gate redesign — ic_ci_lower > 0 AND passes_fdr = true replaces binary passes_walkforward gate

**Phase B — corpus re-run on corrected ic_engine:** ✅ COMPLETE 2026-07-01 (3rd rebuild, 15:52 UTC). feature_vectors 10,080,038 (100% regime-populated), forward_returns 10,080,038 (all executable_open_to_open), feature_ic_scores 254,126, market_regimes 928,791. Qualifying features (POOLED, ci_gate AND fdr): 5m=37, 15m=28, 1h=15, 1d=28 — up from 0/0 pre-Phase-A. Caveat: counts carry gate-redesign selection pressure (see `docs/plans/methodology-change-ledger.md` E2); not cited as edge evidence until 142A OOS.

- B1: `scripts/ops/corpus/ops_corpus_pipeline_run.sh` — regime_writer → forward_return_writer → ic_engine → ensemble_trainer → alpha_publisher — done
- B2: Empirical calibration (cost hurdle, threshold validation, gap contamination check) — done, todo 030 closed 2026-07-02
- B3: IC validation analysis — done, counts above

**Phase 141.1 — Measurement and Decision Integrity Foundation:** ✅ COMPLETE 2026-07-02 (4/4 plans) — OOS holdout enforcement, weight-epoch/silent-retrain fix, `regime_scope` schema disambiguation (256,566 rows backfilled), cost-hurdle APR calibration (todo 030 Steps 0-3).

**Regime-label validation (corrected 2026-07-01):** HMM regime model (`regime_writer.py`) fits on the full corpus before its causal decode — possible look-ahead bias in regime-stratified IC. Tracked in `.planning/todos/pending/026-hmm-regime-audit-optimization.md` (P4a section) — not an unconditional blocker; 026's own decision gate requires empirical proof of harm (baseline-separation query on `feature_ic_scores`) before any fix is warranted.

**Phase 142A — Ensemble IC Measurement:** ✅ COMPLETE 2026-07-02 (2/2 plans) — `alpha_ensemble_ic` schema + `EnsembleICEngine` + `hold_max_bars` decay-curve calibration + EIC-04 gate + EIC-05 diagnosis script. Code review found 2 BLOCKER + 3 WARNING findings, all fixed except WR-02 (pooled cross-sectional measurement gap, captured as todo 046 — not a blocker, EIC-04/EIC-05 both function per-symbol). Verified: 10/10 must-haves. **Machinery complete ≠ gate passage: EIC-04 verdict is FAIL as of 2026-07-03** (0/50 qualifying cells at 0.60 threshold; EIC-05 diagnosis = data starvation, concentrated in the single populated `5m`/`high_bear` cell). **Phase 142B does not begin until a re-run shows PASS or an operator override is recorded with reasoning** (see ROADMAP.md Phase 142A section verdict log).

**Phase 142B.1 — Ensemble Weighting Methodology:** ✅ COMPLETE 2026-07-04 (5/5 plans, verified). Built E1 (shrunk-IC inputs via `ops_ic_shrinkage.py`) and E2 (mean-variance `Σ⁻¹·IC` combination) weighting variants plus `ops_ensemble_weight_compare.py` (D-10 win-decision gate: `challenger.ic_ci_lower > champion.ic_ci_upper AND challenger.walk_forward_stable`, per-stratum, D-14 regime-caveat tagged). CR-01/CR-02 blocker findings (weight_version scoping gaps) fixed same session (`d8b98cfb`). **Deliberately does not run the actual A/B judgment or promote a winner** — verification confirms this is expected end-of-phase state, not a gap; E2 (`mean_variance`) has not been promoted to live `weight_method`. Follow-on noted in ROADMAP but not yet a todo: seed `concept-governance-registries.md`'s four-table Concept Registry MVP from the E1-E4 `weight_version` rows.

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
| 140.5 | Corpus Foundations + Feature Governance | COMPLETE (5/5 plans, 2026-06-26; 27/29 verification truths) |
| 141 | Corpus Quality Gate + IC Validation | COMPLETE (3/3 plans, 2026-06-29) — gate FAIL: 5m=0 features (pre-Phase-A baseline, see below) |
| 141.1 | Measurement and Decision Integrity Foundation | COMPLETE (4/4 plans, 2026-07-02) |
| 142A | Ensemble IC Measurement | COMPLETE (2/2 plans, 2026-07-02) — infra shipped, code review blockers fixed; **EIC-04 gate verdict FAIL as of 2026-07-03** (data starvation, re-run pending) |
| 142B.1 | Ensemble Weighting Methodology | COMPLETE (5/5 plans, verified 2026-07-04) — E1/E2 machinery + A/B judge script built; actual A/B run + promotion not yet performed |
| 142.5 | Renaissance Primitives | COMPLETE (8/8 plans, 2026-07-07) — 91 new primitives implemented in Feature Factory (61 baseline + 91 = 152 total fields); migration 206 applied live to `indicagent` DB (152 feature_vectors columns, 152 feature_registry rows, 54 APR keys), verified idempotent; corpus backfill to populate these fields in existing rows deferred to next corpus run. Replanned 2026-07-06 from cross-AI review (142.5-REVIEWS.md): added Plan 05.5 to implement the 8 price-volume interaction primitives Plan 06 was already creating schema/APR for; fixed cold-start crash, feature_registry seeding, and registry row-count sync gaps |
| 142B | Frame Simulation + Counterfactual Tracking | COMPLETE (2/2 plans, verified 2026-07-10) — `alpha_frames` schema + `AlphaFrameWriter` + `CounterfactualTracker`; 2 code-review blockers + 5 minor findings fixed (commit `fa4208ef`); `alpha_frames` has 0 rows, corpus run deferred to Phase 147/ops |

**4th corpus rebuild IN PROGRESS as of 2026-07-08** (started 2026-07-07 17:00) — will supersede
the Phase B row counts above once complete (`feature_vectors` already at 36.7M rows mid-rebuild,
up from 10.08M, from the ETF expansion + Phase 142.5 primitives landing for the first time).
Live status and step-by-step detail: `docs/research/2026-07-08-intelligence-lifecycle-backlog-matrix.md`
("Operational context") — don't duplicate row counts here, that doc and
`logs/corpus_pipeline/full_run_20260707_170028.log` are the source of truth until this rebuild
finishes and this section gets its own update.

**SUPERSEDED — pre-Phase-A/pre-3rd-rebuild baseline, do not cite as current:** the row counts and IC gate
results below are from the 2026-06-29 corpus run, before Phase A's ic_engine methodology fixes and before
the 2026-07-01 3rd rebuild. Current counts are in the Phase B entry above.

- feature_vectors: 54,260,576 rows (58 symbols × 4 TFs) — forward_returns: 1:1 match
- feature_ic_scores: 402,651 rows; 5m/15m: 0 qualifying features (FAIL — root cause was a gate design bug, not signal absence, per Phase A finding); 1h: 23 qualifying; 1d: insufficient coverage
- alpha_events: 12,472,068 rows; OOS boundary: `alpha.validation.oos_start = 2025-12-24T05:15:00Z`

**Dual regime system (both live):**

- `feature_vectors.regime` — 5 per-symbol HMM labels (trending_down/transition_down/ranging/transition_up/trending_up), written by `regime_writer.py` (K=5, causal forward-filter)
- `market_regimes` — 9 cross-sectional labels ({low/mid/high}_{bull/neutral/bear}), written by `equity_regime_model.py`; ic_engine stratifies on these

## Key Decisions (load-bearing — don't re-derive)

- **HMM_RANDOM_STATE = 42** — changing invalidates all feature_ic_scores, requires full re-run
- **Pooled IC (is_pooled=true)** — cross-sectional POOLED strata ARE the ensemble training eligibility source. `ensemble_trainer.py` reads `WHERE symbol='POOLED' AND is_pooled=true AND regime != '_pooled'` (lines 317, 430-431, 469, 540) — the prior "diagnostic only, filter WHERE is_pooled=false" claim here was inverted (semantics changed when cross-sectional POOLED strata became the eligibility source in Phase A/141.1; corrected 2026-07-08)
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

## Accumulated Context

### Roadmap Evolution

- Phase 142B.1 inserted after Phase 142B: Ensemble Weighting Methodology — from 2026-07-01 v3 architecture review (.planning/research/2026-07-01-v3-architecture-review.md). Not urgent: depends on Phase 142A complete, does not change current-focus sequencing.
- Phase 141.1 inserted between Phase 141 and Phase 142A (2026-07-02) — measurement/decision integrity fixes needed before 142A's OOS ensemble IC measurement would be trustworthy. See `.planning/research/2026-07-02-v3-bottomup-audit.md`.
- 2026-07-02 evening: user confirmed Phase 142A complete and Phase 142B (frame simulation) targeted for completion tonight. **Correction (2026-07-04): that Phase 142B completion never happened** — 142B.1 was planned and executed instead (out of the order this note implied), and 142B remains 0/2 plans, still blocked on EIC-04. This STATE.md file itself sat stale for 2 days (last real update 2026-07-03) claiming 142B "IN PROGRESS" and 142B.1 as "current focus" for planning — both wrong; corrected above.
- 2026-07-04: Phase 142B.1 verified complete (5/5 plans). Real next steps: run the E1 (`v1_shrunk`)/E2 (`v2_mv`) weight_version variants through `EnsembleICEngine`, judge them with `ops_ensemble_weight_compare.py`, then re-run EIC-04 to check for gate passage before Phase 142B can start. Separately, in another session (2026-07-04), the user is running a Fable review reconciling `docs/research/concept-governance-registries.md` against its consumer docs (intel-10/13/14/15) and the ROADMAP — not yet landed as of this update.
- 2026-07-04: Deep-dive on EIC-04's FAIL verdict found the "data starvation, expect it to resolve with accumulation" framing (ROADMAP.md Phase 142A verdict log, 2026-07-03) was only partly right — see the 2026-07-04 correction entry in that same log for the full breakdown. Summary: 15m is at its old depth ceiling (fixed by the in-progress 20yr backfill, not by waiting); 1h/1d were simply never trained despite already-qualifying features (an unexercised pipeline path — `ensemble_trainer.py` manifest shows only one run ever, 2026-07-01, 5m/15m only); the one well-powered cell we do have (`POOLED`/5m/`high_bear`) is a genuine null, not underpowered; and the gate script itself unweighted-averages `POOLED` with 49 per-symbol cells. Full remediation plan (backfill to 20yr for all 80 active equity instruments, including 22 never-before-processed symbols, then full corpus re-run, then re-run EIC-04/EIC-05, then the still-unexecuted 142B.1 E1/E2 judgment run) is at `/home/bg/.claude/plans/should-we-back-fill-nested-peacock.md` — in progress as of this update, and now the critical path for unblocking Phase 142B.
- 2026-07-02: `.planning/research/2026-07-02-v3-topdown-architecture.md` proposes a `StratificationDimension` contract to unify the two live regime systems (per-symbol HMM `regime_writer.py`, cross-sectional `equity_regime_model.py`) as part of a new milestone "v3.15 Conditioning & Identity Foundation," sequenced between v3.1 and v3.2 (AnalogEngine). Explicitly does NOT block or change Phase 142B.1's E1→E2→E3→E4 order — E1/E2 only consume existing regime labels as an opaque stratification key. No code changes intended before that milestone is actually planned.
- Phase 142.5 inserted after Phase 142B.1: Renaissance Primitives - Add ~83 foundational primitives to Feature Factory. Planned 2026-07-06 with 7 plans (00-06). Corpus backfill and IC evaluation deferred to next corpus run (before 142B execution). Verification found 8 price-volume interaction primitives that Plan 06 creates schema for but no plan implements — left as-is per user decision. **Correction (2026-07-06, same day): "left as-is per user decision" was wrong — no CONTEXT.md/discuss-phase happened for this phase, so there was no user decision; this was an unresolved plan-checker BLOCKER. Two independent cross-AI reviews (142.5-REVIEWS.md) and a re-run plan-checker confirmed the gap and it was fixed via a targeted replan: new Plan 05.5 implements all 8 interaction primitives end-to-end. Also fixed in the same replan: a cold-start crash in Plans 01-04 (`_cold_start_vector()` never updated for their new fields), `feature_registry` never seeded with the new rows, `_REGISTRY_ROW_COUNT` stuck at 126, migration misnumbered 177 (now 206, avoiding collision with Phase 143's already-planned 202-205), and undocumented scope gaps (Open-to-Close Split, month_sin/cos — now implemented; Cross-TF Divergences — explicitly deferred, todo 066). Final reconciled count: 91 new primitives, 152 total fields (61 baseline + 91), across 8 plans (00-06 + 05.5). Plan-checker re-verified: 0 blockers.**
