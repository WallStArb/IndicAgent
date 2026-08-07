# Todo Priorities

**Scope of this index:** `pending/` only — small, single-session, run-it-now items. Phases
(ROADMAP.md, `/gsd-discuss-phase` workflow) are a separate execution track and do not appear
here; anything that's actually phase-scoped (a new feature family, a batched corpus-rerun item,
or hard-gated on a phase/dataset that doesn't exist yet) lives in `deferred/` with a status line
explaining what unblocks it.

**This file is the single source of truth for todo-level prioritization.** Do not automate
ranking itself (the P0-P3 tiers) — that's a judgment call reserved for the project owner. A
"Gate:" line written once at filing time rots — anything sitting in `deferred/` for more than
~2 weeks should have its gate re-checked against live state before being cited as still-blocked.

**Tiers:** P0 = fix soon, real gap/bug surfaced. P1 = high value, quick, fully unblocked. P2 =
real value, not urgent. P3 = hygiene/docs/process, opportunistic.

**Prioritization lens (this project's design north star, CLAUDE.md):** apply Musk's 5-step
mandate in order — question the requirement, delete, simplify, accelerate, automate — before
scoring or filing any todo; don't accelerate work steps 1-3 haven't justified, and don't automate
what isn't proven. A todo that's really a requirement to question or delete belongs in that
state, not P2 "someday."

Weight tier placement against Renaissance Technologies / Jim Simons principles (full doc:
`docs/foundation/principles.md`): instrument everything · shadow mode first · data quality over
model complexity · never drop data that could contain signal · earn promotion through proof
(p<0.05, sufficient N) · segment by regime · automate manual tasks · empirical over theoretical ·
resist overfitting. A todo that would earn its way to P0/P1 under these tests (a live-path
integrity gap, an unproven claim masquerading as settled) outranks one that's merely convenient.

**Phase-level status and in-flight run state:** see `.planning/STATE.md`'s "Current saga"
section (authoritative, live) and
`docs/research/intelligence-lifecycle-backlog-matrix.md`'s Operational Context -- never
duplicated here; a run-status snapshot pasted into this file goes stale within hours and this
file's job is prioritization, not a live dashboard. One open item with no phase home yet: todo
218 (`BIL` implausible per-symbol IC on thin cells, filed 2026-07-31, check `passes_fdr` once
the in-flight run completes).

**Regime-stratification cluster consolidated 2026-08-01** -- read
`docs/research/stratification-dimension-unification.md`'s "Reconciliation pass (2026-08-01)"
section before re-deriving candidate stratification dimensions from scratch; it already
cross-links todos 135/167/224/225/111 (Phase 145).

**Dual intelligence-path plan (stated 2026-08-01, `project_dual_intelligence_path_plan.md` in
memory):** v2.x I1-I7 will eventually run again as a second path alongside v3.0's AlphaEngine,
not retired permanently -- governs todo 223's archive-not-delete call and todo 056's
decommission-in-fact framing (re-read that plan before executing either).

**Corpus pass completed 2026-08-02 (step_timings.jsonl confirms steps 5-8 finished 21:19:49
UTC) -- sequencing chain gated on it re-checked 2026-08-03:** todo 210's live verification
against a repopulated `ensemble_alpha` is now CONFIRMED (1h/1d OOS rows present, see todo 173's
closure). Todo 065 (EM-CAL calibration) is now unblocked -- its gate was this pass completing.
Todo 167 (equity vs symbol-HMM falsifier) status is NOT yet re-confirmed -- unclear whether
`regime_writer` (step 2) itself reran with fresh dual-write data in this pass or whether the
relaunch-from-step-3 skipped it; check before assuming unblocked. **Separate finding, 2026-08-04,
NOT an answer to the step-2/167 question above (different table, different mechanism -- don't
conflate) -- [253](completed/253-forward-returns-frozen-at-oos-boundary-corpus-rebuild-skipped-step3.md):
`forward_returns` has zero rows at `bar_ts >= oos_start` at every tf, but this is NOT a skipped
step -- Phase 141.1's OOS holdout enforcement makes it structurally impossible for the normal
pipeline to ever write there, by design (two independent enforcement layers, confirmed via
`docs/plans/OOS-EVAL-PROTOCOL.md`). The real gap is that Phase 167's Gate 1/Gate 2 reads
`forward_returns` directly instead of computing OOS returns on the fly the way the protocol's own
sanctioned diagnostic scorer (`ops_oos_holdout_eval.py`) already does -- its 2026-07-27 PASS
verdict depended on an undocumented one-off population of the holdout region that a routine,
correct `TRUNCATE forward_returns` later erased. `ensemble_alpha`'s OOS rows (todo 210, above)
are unaffected -- different table, computed without needing realized forward returns.** Todo 253
itself closed 2026-08-04 (fix design done, folded into todo 243's execution). Once 065/167 are
actioned:
todo 214 (deferred ic_engine/ensemble_ic_engine compute-core refactor), and scoping
Phase 167/cross_sectional_relative_value's cost-hurdle-adjusted spread construction
(`docs/research/trade-construction-layer.md`) as a new phase via `/gsd-discuss-phase` --
proceeding on the latter is the user's call.

**Backlog-quality pass, 2026-08-03:** closed 7 pending todos on inspection -- 217/233 (both
fully shipped and live-confirmed, just never closed), 173 (the specific data gap it reported no
longer exists post the 2026-08-02 run), 189 (remaining scope had zero actionable payoff left),
111 (superseded/double-tracked by ROADMAP Phase 145), and 022+024 (Superset BI + dependent
dashboard, rejected as not Renaissance-quality -- pure convenience tooling with no proof-of-alpha
value for a single-operator system, see each file's closure note). All in `completed/`.

**Status sync pass, 2026-08-03 (later same day):** todos 239/240 code landed + committed
(`816032e2`, `dd19376a`) -- P1 rows updated to reflect that; both still gate on an actual
1h/1d/15m/5m re-run, not yet started. Todo 241 code landed + committed (`8b2cf690`, closing a
"not yet committed" note that was stale by the time this pass ran) -- moved to `completed/`,
dropped from the P1 table. Todo 218 confirmed closed (root-caused, deliberately not fixed) --
moved to `completed/`, dropped from the P2 table and from the tier-change-candidates footnote.
Todo 172 checked against its own file and found only PARTIALLY complete (item 2 fixed, item 1 --
the broader path-dependent-statistics sweep -- still open, unscoped) -- left in `pending/`,
existing row already stated this accurately.

**Structure cleanup pass, 2026-08-03:** this file had accumulated ~15 inline "CLOSED" narrative
blocks inside the P0-P3 tiers (204/230/219/221/210/179/146/124/188/231/234/222/236/233/232) --
duplicating what `completed/` already records, against this file's own stated scope ("Not in
this list: completed"). All stripped; verified each still exists in `completed/` first. Todo 099
was also mis-filed under the P0 header despite being tagged P2 in its own row text -- moved to
the P2 table where it belongs. No tier reassignments made beyond that placement fix and adding
todo 241 (filed same session) -- re-tiering existing items is a judgment call for you, not
something to do silently; flagged two candidates below the tables.

**Status-sync + hygiene pass, 2026-08-06:** todo 243's row updated to reflect the killed
`--apply` attempt (batching defect + undetected contention with todo 259, see the row itself).
Two filing collisions fixed: `259-single-name-equity-backfill-53-symbols-missing.md` was a
stale duplicate of the current `259-single-name-equity-backfill-135-symbols-missing.md` (same
todo number reused across refreshes instead of edited in place; verified the newer file is a
strict superset before deleting the older one) -- deleted. `271-instrument-tag-peer-group-
coverage-auditor.md` collided with the already-completed `271-feature-ic-scores-history-not-a-
hypertable.md` (flagged but not fixed in a prior session) -- renumbered to 272, content
unchanged. Neither collision reflects a real prioritization change, just filing hygiene.

**Parallel-track P2/P3 batch, 2026-08-07 (while todo 259's backfill and todo 243's `ic_engine
--refresh` ran in the background):** four todos actioned, deliberately code/design work with
no `feature_vectors`/`market_data_ohlcv`/regime-table contention against those two live jobs.
**156 CLOSED** -- step 3's remaining-services audit done; only `bar_auditor.py`/
`compression_auditor.py` were actually v3.0-relevant among the 8 `_run_audit`-shaped services
checked, both now span-wrapped. **242 CLOSED** -- `_CTF_HIGHER_TF` migrated to APR (migration
305, `FeatureFactoryConfig.ctf_higher_tf_map`), `feature_vector_pipeline.py`'s `_CTF_LOWER_TFS`
moved from module scope to instance state as the todo's own scope note anticipated. **262
CLOSED as moot** -- verified live before acting (per this file's own "verify then delete, don't
flag" discipline): migration 279 was never actually applied to this DB, zero rows in
`config_schema`/`config_state`/`config_history` for that key, nothing to clean up. **267
partially done** -- added a CI-clean drift-tripwire test
(`tests/unit/test_feature_edge_by_regime_filter_parity.py`) comparing `_apply_feature_transitions`'
SQL filter against `feature_edge_by_regime`'s WHERE clause; the two post-recompute operational
checks (`ANALYZE`/`EXPLAIN ANALYZE` re-verification) remain correctly gated on todo 243's
corpus recompute landing, left in `pending/`. Todo 009 Part B (promote `backfill_feature_factory.py`/
`regime_writer.py`/`forward_return_writer.py`/`ic_engine.py` to `BaseBatch`+systemd) was
explicitly scoped OUT of this batch -- it would edit `ic_engine.py` while its `--refresh` is
live; revisit once that run completes.

**Todo 243 CLOSED 2026-08-07 -- Phase 167's cross-sectional construction re-verified at
authoritative tier, both Validation Gates FAIL.** Moved to `completed/`, dropped from the P0
table. Full numbers in `.planning/STATE.md`'s Strategic Plan section and the todo file itself.
This is the resolution the whole CTF-leak investigation thread was building toward -- the fork
decided in advance now applies: back to discovery, not construction; Phase 168/156-159 stay
blocked. Side effects worth noting: (1) fixed a real, separate, project-wide blocker found along
the way -- `ic_engine.py` had been unable to run for anyone since 2026-08-02 (`fx` regime group
enabled but never populated), now fixed, closing half of todo 224; (2) todo 267's two
post-recompute operational checks, gated on "todo 243's corpus recompute landing," are now
unblocked -- not actioned here, todo 267 is a separate concurrent-session thread.

**Todo 224 CLOSED 2026-08-07 -- commodity regime group unified and enabled (migration 306).**
Moved to `completed/`, dropped from the P2 table. `commodity_energy`/`commodity_metals`/
`commodity_agri` merged into one `commodity` group (27 members, not the ~11 originally
estimated -- the universe expansion grew commodity-tagged membership materially between filing
and execution), `DBC`'s unrouted `commodity_broad` tag fixed, group enabled and confirmed
populated (564,439 `market_regimes` rows, all 4 tfs, no crash). The `AMLP`/`GDX`/`OIH`/`XLE`/
`XOP` equity-tag collision was resolved WITHOUT todo 225 -- `ic_engine.py`'s
`_build_symbol_regime_class` gained a new `exclude_symbols` field (small, explicit, tested
carve-out, not a silent precedence rule) instead of waiting on 225's gradient-conditional IC
mechanism, whose own pilot had already come back negative. Todo 225 demoted P2->P3 accordingly
(no longer blocking anything, purely an independent measurement idea now). Side effect: enabling
the group for the first time ever surfaced a real latent bug in `commodity_momentum_ts.py`
(never live-tested before -- shipped `enabled: false` since inception), fixed same session,
regression test added. Commit `d6623b31`.

---

## P0 — Fix soon (integrity/correctness gaps already surfaced)

| Todo | Gap |
|---|---|
| [270](pending/270-broadcast-feature-significance-overstates-effective-n.md) | New 2026-08-05, closing 3 stale P0 rows (252/203/253 were all already in `completed/`, PRIORITIES.md just never caught up). Split out of 203's own closure note: `vix_z`/`yield_slope_z`/`flight_quality` and every session/calendar feature are symbol-invariant (broadcast) at a given `bar_ts`, so a per-symbol significance test on the pooled cross-sectional sample overstates effective N by ~n_symbols. No significance claim on any broadcast feature can be trusted at face value under the current test -- real methodology design needed, not yet scoped when 203 flagged it. |

## P1 — High value, quick, fully unblocked

| Todo | Why now |
|---|---|
| [240](pending/240-nonlinear-interaction-combiner-baseline-is-single-feature-not-the-linear-ensemble.md) | From a rigor review of the Edge Source Thesis doc. nonlinear_interaction_combiner's pre-registered falsification bar says the tree must beat "the existing linear ensemble"; every run actually compared it to `ctf_momentum` alone. **Code landed + committed 2026-08-03** (`816032e2`): a fold-local linear-ensemble arm (`fit_linear_ensemble_weights`/`score_linear_ensemble`, reusing `ensemble_trainer.py`'s own weighting primitives) plus a paired-bootstrap PRIMARY VERDICT (tree vs linear), `ctf_momentum` kept as secondary. Independent review caught and fixed 2 blocking issues (features weren't z-scored before weighting; memory footprint too close to this module's prior OOM history) -- both fixed in the same commit. **Re-run at 1h/15m/5m gated on todo 243's corpus-recompute decision** (todo 245, all 3 tfs measured and CLOSED 2026-08-04 -- the training matrix confound is now quantified, not just flagged; the training matrix still includes lookahead-contaminated `ctf_momentum` until 243's corpus recompute happens) -- **1d re-run is safe and unblocked right now.** Gates todo 238. |
| [239](pending/239-nonlinear-interaction-combiner-embargo-passed-in-pooled-panel-rows-not-bars.md) | Same review. `_nonlinear_interaction_combiner_shared.py` passed `embargo_bars` into `build_walk_forward_folds(n_valid=len(X))` where `X` is the **pooled** ~80-rows-per-bar panel, so the intended 1-day embargo was 24/96/5 *rows* ≈ 0.3/1.2/0.06 bars at 1h/15m/1d, and fold boundaries split inside a single `bar_ts`. Bounded blast radius (~800 rows of ~2-8.5M, does NOT explain the 0.18-0.25 IC) but cited in the research doc as a rigor credential. **Code landed + committed 2026-08-03** (`816032e2`, same commit as 240): new `_pooled_panel_folds()` builds folds over the distinct `bar_ts` index and maps back to row slices; `build_walk_forward_folds` itself untouched. **Re-run gating: same as 240 -- 1d safe now, 1h/15m/5m wait on todo 243's corpus recompute.** |
| [238](pending/238-nonlinear-interaction-combiner-ranked-cross-sectional-relative-value-pre-registration.md) | New 2026-08-03, from a user-directed rigor review of Edge Source Thesis next steps. Both cross_sectional_relative_value (proven construction) and nonlinear_interaction_combiner (proven 3-5x-stronger signal) are independently validated at 15m; nobody has tested cross_sectional_relative_value ranked by nonlinear_interaction_combiner's tree score instead of `ctf_momentum` — highest-expected-value untested combination on the doc. Pre-registered falsification design (shuffled null, cost-hurdle, turnover, Gate-2-equivalent factor-attribution, breadth-preservation) written down before running, per this project's own pre-registration discipline. **Gated on cross_sectional_relative_value's own Gate 1/Gate 2 re-verification landing first** (todo 243 -- 253's own prerequisite fix already closed 2026-08-04) -- ranking by a tree score doesn't matter if the underlying construction's proof itself is unverified; testing this now would build on the same unresolved foundation. |
| [229](pending/229-regime-writer-hmm-retry-logic-structurally-unreachable.md) | New 2026-08-02, found reviewing todo 226's branch: hmmlearn 0.3.3's `monitor_.converged` is unconditionally `True` after any completed fit (proven both by source and empirical test), making `regime_writer.py`'s same-seed convergence retry (todo 108) dead code since it shipped. **Design decision settled and proven** (`monitor_.iter < monitor_.n_iter` is the exact fix) — implementation deliberately deferred, sequenced behind the next full corpus run's `iters_used` log data (todo 226's instrumentation) to measure blast radius before paying for the fix + mandatory re-run. P1 because "silent wrong answers are worse than loud crashes," not because it's urgent to implement immediately. |
| [248](pending/248-hmm-full-history-fit-regime-label-instability-gate4-pilot.md) | New 2026-08-03, retired out of `deferred/026`. Instability confirmed at 3 symbol/tfs (24.9-56.8% label agreement depending on tf). **Wired 2026-08-05**: `_compute_symbol_tf_walk_forward` (full production-parity path -- per-segment convergence retry, degenerate-segment gating, all `feature_vectors` columns, not just bare labels) added to `regime_writer.py`, dispatched via APR flag `alpha.hmm.walk_forward.enabled` (migration 292, **seeded `false`** -- landing the code changes zero existing regime label). Per-tf `refit_every_bars`/`initial_warmup_bars` seeded for all 4 tfs (1h/15m pilot-measured, 5m scaled-not-piloted, 1d unpiloted estimate -- see migration 292's per-key provenance). **Remaining work is now purely a deployment decision, not implementation**: flip the flag, run `regime_writer.py --refit`, then a downstream `ic_engine` recompute (same blast-radius class as an `HMM_RANDOM_STATE` change) -- still queued behind CTF/Phase 167 per the 2026-08-04 sequencing decision, unaffected by this session's wiring work. |
| [065](pending/065-emission-layer-calibration-proposals.md) | EM-CAL threshold calibration — both prerequisite gates (rebuild, EIC-04) cleared 2026-07-09. **Caution added 2026-07-30**: that clearance predates todo 146/208's grid rework (per-tf lookahead grid; 208's session-gate premise is now fixed, but the grid's actual values are still open, see 208's row below). **Unblocked 2026-08-03**: the corpus pass this was waiting on completed 2026-08-02 21:19 UTC (see preamble). Ready to calibrate against the corrected corpus now — real design/execution work, not mechanical. |
| [079](pending/079-anytime-valid-e-values-corpus-reruns.md) | Anytime-valid inference pilot (one tf) — new statistical primitive, deliberately staged small |
| [005](pending/005-ic-regime-transition-purge.md) | **Raised P2→P1, 2026-08-07.** Was sitting unblocked-but-idle since 2026-08-02 (its own gate cleared, attention went to the CTF investigation instead). Sharper than a P2 label suggests: `market_regimes` (what `ic_engine.py` actually stratifies on) does pure per-bar threshold bucketing with **zero transition guard of any kind** — not even the hysteresis the per-symbol HMM path already has. A live measurement-integrity gap underneath every regime-stratified IC test this project runs, not just an optimization. Also unblocks `docs/research/measurement-adaptive-combiner-weights.md`'s L5-1 (highest-conviction ensemble E-candidate). Recommend running as a third parallel diagnostic alongside `jump_diffusion_decomposition`/`cointegrated_pairs_residual` — disjoint, read-only, same resource shape. |
| [054](pending/054-shadow-alpha-events-monitoring.md) | Shadow alpha_events monitoring — prevents delayed detection of feature decay/threshold bugs |
| [169](pending/169-no-regime-coverage-completeness-check.md) | **Built and tested 2026-07-24, not yet deployed.** `services/regime_coverage_auditor.py` ships with unit tests (`tests/unit/services/test_regime_coverage_auditor.py`) and matching systemd unit files (`production/systemd/indicagent-regime-coverage-auditor.{service,timer}`, daily 06:00 UTC, same pattern as every other auditor). It already earned its keep once — immediately found 14 symbols, not the 7 known at filing time (closed as [168](../completed/168-seven-symbols-zero-per-symbol-hmm-regime-labels.md)). Remaining: actually enable the timer on the live host (`systemctl enable/start`) — a real persistent infra change, deliberately not done without explicit go-ahead. |
| [167](pending/167-equity-cross-sectional-vs-symbol-hmm-never-falsifier-tested.md) | **Plan changed 2026-07-29 — no longer a standalone equity-scoped relaunch,** folded into 176's queued sequence (market-data-gap catchup → 176's `--refresh` → one full-corpus `ic_engine` pass). **176's `--refresh` step confirmed run 2026-07-30**, but the sequence's final step (a full-corpus equity+rates `ic_engine` pass) status is unclear post-2026-08-02 (see preamble) — that pass is what would actually close this todo. |
| [118](pending/118-migrate-feature-domain-into-concept-registry.md) | Raised P2→P1 2026-08-04 — user confirmed `feature_registry` is an anachronism, migrate ASAP, don't leave two governance systems running in parallel. Stale gate note corrected: todo 117 (a different, already-completed actuator proof, closed 2026-07-19) was blocking this; it's done. The real remaining gate is `alpha_ensemble_ic` having real rows (0 as of today) so `ConceptRegistryService.record_comparison_outcome` can be rehearsed against live data for the first time (H-1/M-B, never yet exercised) — purely a corpus-rebuild dependency, not new design work. Execute the moment that data lands: rehearsal, then fold in L-5 (concept_gate missing shadow-recovery counters) and L-6 (FDR enforcement not service-enforced) as part of the same pass, then cut over and retire feature_registry. |
| [251](pending/251-feature-edge-summary-view.md) | **Views done 2026-08-05 (migration 297)**: `feature_edge_by_regime`/`feature_edge_by_symbol`, filters verified against `ic_engine.py`'s actual write paths and the live promotion/demotion hook query (not just this todo's own prose, which had an unreachable filter combination). Remaining: retire the orphaned `ops_primitive_discovery_report.py` skeleton it supersedes — deferred, Phase 170's concurrent session touched that exact file most recently (`fb638e86`); revisit once Phase 170 merges. |
| [261](pending/261-deploy-grain-corrected-cross-asset-mechanism-once-ingestion-resumes.md) | New 2026-08-05, closing Phase 151 Plan 09. Code+tests complete and merged: replaced todo 221/222's per-timeframe `CrossAssetState` live mechanism (a confirmed grain mismatch — computed from THIS TIMEFRAME's own intraday bars, not the canonical daily-broadcast definition every IC/gate measurement was built against) with a daily-grain mechanism sharing the batch path's own `build_cross_asset_series()`. Deployment (live daemon restart + Task 3's verification) deliberately NOT done in that plan's execution — ingestion is still paused (`max(bar_ts)` 8 days stale, restarting proves nothing right now) and this is a full mechanism replacement an unattended session shouldn't push live without operator sign-off. |

## P2 — Real value, not urgent

| Todo | What |
|---|---|
| [099](pending/099-bootstrap-ci-staged-validation-gate-not-cleared-5m-residual.md) | The bootstrap CI staged-validation gate's 6 SUSPECT cells trace to 5 diagnostic-only (`is_pooled=false`) breaches + 1 capital-relevant cell that independently clears its own bound — no longer blocks Plan 07. Underlying statistical question (why 5m autocorrelation/momentum features resist both Fisher-z and block-bootstrap) remains open as non-blocking follow-up. |
| [208](pending/208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md) | **Updated 2026-07-31 — characterization run is COMPLETE, not still pending.** Steps 1/2 DONE (`forward_return_writer.py`'s same-ET-session gate removed for 5m/15m/1h, `forward_returns` rebuilt clean). The run confirmed migration 269's grid values hold under corrected semantics — no re-migration needed. This todo's remaining scope is now the deeper method question it surfaced: does decay-walk-on-pooled-median-IC even make sense for `hold_max_bars` selection, given IC rises alongside CI width rather than decaying within any tested horizon. Real design pass needed (3 candidate approaches in the file), not mechanical. Not blocking anything, including the in-flight `ic_engine` run. |
| [213](pending/213-rolling-vp-suppressed-for-1d-never-independently-reviewed.md) | New 2026-07-30, found while closing 176: `poc_rolling_dist_atr`/`poc_session_rolling_divergence_atr` (D-18's rolling-track VP additions, tf-agnostic by construction) are suppressed for `tf='1d'` via the same code branch as session VP (which correctly doesn't apply to 1d) -- but the rolling case was never independently reviewed for tf-applicability across any of Phase 163's three design-review passes. Likely dropping real signal (a 1d bar's dislocation from a ~2-year value anchor is a coherent auction-market-theory concept per D-18's own argument), not a considered exclusion. Needs an incremental-IC check before promoting, same discipline as any other structural column. Renumbered from 209 -- collided with a same-day, independently-filed todo from the per-tf-active-scale-set final review. |
| [186](pending/186-ic-math-cross-sectional-block-bootstrap-gap.md) | New 2026-07-26, same review as 185: `ic_math.py` has a per-symbol circular block bootstrap but no cross-sectional (pooled-panel) variant, so nonlinear_interaction_combiner's within-bar_ts rigor check approximated it ad hoc. Lower urgency than 185 — the approximation is conservative and the script says so; do this once a real (non-exploratory) cross_sectional_relative_value/nonlinear_interaction_combiner candidate needs it. |
| [214](pending/214-ic-engine-ensemble-ic-engine-shared-compute-refactor.md) | New 2026-07-30, user question mid-session: `ic_engine.py` (5,239 lines) and `ensemble_ic_engine.py` (1,523 lines) independently duplicate the same per-scale compute pattern instead of sharing one implementation — exactly the duplication that let todo 210's bug (one engine masks on `complete_{scale}`, the other silently didn't) exist undetected. **One narrow slice landed 2026-07-30** (commit `955e6fbe`) — the `{scale: {tf: lookahead_bars}}` dict-construction duplicated across `ic_engine.py`/`ensemble_ic_engine.py`/`ops_ensemble_ablation.py` was consolidated into `lookahead_by_scale_from_apr()` (`services/_batch_utils.py`). The actual compute-core consolidation (fetch → mask → rank-IC → walk-forward folds) this todo describes is still open — real refactor, deliberately deferred until the current IC measurement chain (208/210/209/211's fixes, a fresh corpus rebuild) is stable again. |
| [177](pending/177-bar-history-maxlen-caps-windows-beyond-200.md) | **Step 1 (enumeration) done 2026-07-31** — 22 `FeatureFactoryConfig` fields confirmed >200 bars; 19 genuinely `BarHistory`-capped, 2 (`vix_zscore_window`/`yield_curve_zscore_window`) turned out to be a worse, unrelated dead-code-path bug, split out and fixed separately (todo 221, closed). Steps 2-3 (fix-shape decision + IC verification) still correctly deferred pending corpus rebuild. |
| [101](pending/101-migration-duplicate-number-sweep.md) | **Stale row corrected 2026-08-03**: the original 14-group finding was resolved in commit `18551320` (2026-07-18). Current remaining scope is narrower — one brand-new collision at `240` (two concurrent worktree sessions), caught by the guard test (`tests/unit/test_migration_number_uniqueness.py`) and allow-listed there pending a dedicated renumbering session. **Confirmed 2026-08-03: do not casually rename either 240 file** — both are already applied to the live DB; the guard test's own docstring explicitly scopes renumbering as its own higher-risk session, not a quick fix. |
| [108](pending/108-hmm-multi-seed-restart-best-likelihood.md) | `regime_writer.py`'s HMM fit uses a single seed with a same-seed convergence retry, not multi-seed-restart-and-keep-best-log-likelihood. Robustness gap, not a proven bug. **Update 2026-08-02:** todo 229 found the `n_restarts > 1` convergence-vs-likelihood tiebreak this todo relies on has been silently degraded to pure-likelihood ranking by the same `monitor_.converged` bug — 229's fix revives the intended tiebreak behavior as a side effect. Re-read 229 before scoping any further work here. |
| [038](pending/038-cross-sectional-collinearity-diagnostic.md) | Cross-sectional feature collinearity diagnostic vs IC |
| [039](pending/039-tag-stratified-ic-population-check.md) | Population-count check before tag-stratified cross-sectional IC |
| [081](pending/081-emission-meta-labeling-and-conviction-cross-ref.md) | Emission meta-labeling gate — check overlap with 065/EM-HYST before building |
| [089](pending/089-ensemble-ic-engine-recurring-cadence.md) | No recurring `ensemble_ic_engine` schedule exists — IC-decay trigger input can go stale |
| [009](pending/009-service-utils-ic-engine-cleanup.md) | Phase B infra cleanup batch — APR compliance sweep, `BaseBatch` promotion, naming vocab, shared-utility DRY fixes. Parts A and D closed 2026-07-31 (commit `bd3c5ced`, done in parallel with the in-flight `ic_engine` corpus run — pure code/infra, no corpus dependency). Part E closed 2026-07-23 via Phase 162-01. Parts B/C (promote 4 scripts to `BaseBatch`+systemd, naming-vocab doc update) remain open — real scoped work, not mechanical. |
| [191](pending/191-feature-scoring-beyond-ic.md) | Feature scoring beyond IC (near-term derived metrics) |
| [052](pending/052-adversarial-data-error-hunt.md) | Adversarial data-error hunt batch job |
| [042](pending/042-15m-chunk-size-retest.md) | Re-test 15m backfill chunk size (likely too conservative) — gate reconfirmed clear 2026-07-19, live probe not yet run (see file) |
| [125](pending/125-tag-calibrator-discovery-oos-gate-not-enforced.md) | TagCalibrator's `discovery_oos_days` OOS-confirmation gate computed but never enforced — new discoveries go live immediately. Zero current blast radius (no live consumer reads the affected tags yet, see 126). |
| [126](pending/126-instrument-tags-valid-to-no-consumer-contract.md) | No `instrument_tags` reader filters on `valid_to` — expiry has no observable effect yet, no contract established for future consumers. Resolve before/alongside 125. |
| [135](pending/135-cross-sectional-regime-grid-shape-never-validated.md) | Cross-sectional regime grid shape (9 equity cells, 6 rates cells) has never been validated as a model-selection question — unlike HMM's K=5, which went through a real BIC study. Distinct from todo 092 (cut-point values within the existing shape). |
| [078](pending/078-frame-outcome-labels-second-outcome-definition.md) | Register frame-outcome (barrier-hit sign) as a second outcome definition alongside forward-return IC, now that `alpha_frames` has real data. Gate cleared 2026-07-12 (todo 093 backfill ran); moved back to pending/ 2026-07-18. Diagnostic value, not a reason to touch 142B's frozen design. |
| [082](pending/082-simulation-validation-lenses-post-142b.md) | Additional read-only simulation/validation lenses over `alpha_frames` (standing permutation nulls, etc.) — same gate-cleared status as 078. No new judgment surface, mechanical. |
| [175](pending/175-structural-candidate-part2-smc-swing-fib-anchored-vwap.md) | Filed 2026-07-23 closing Phase 166: Part 2 of the structural stop/target candidate (SMC/swing/fib/anchored-VWAP, i.e. Phase 164/165's primitives) once those phases land — VP/SR (Part 1, Phase 163) is the only part Phase 166 actually scored. Gated on Phase 164 (not planned) and Phase 165 (researched, not planned). **Same deprioritization as todo 176 applies, per todo 179's now-closed findings** — read that file before resuming. |
| [155](pending/155-price-sanity-status-historical-backfill.md) | New 2026-07-20, filed closing [149](../completed/149-bar-ingestion-price-sanity-guard.md): live pilot measured ~4.1 years to clear the 215M-row historical backlog at `BarAuditor`'s default batch size/cadence. Raising the batch size risks the daemon's 60s systemd watchdog and conflates one-time historical debt with the ongoing live-stream audit. Needs a dedicated one-time backfill tool, decoupled from `BarAuditor`'s cycle, reusing 149's classification primitives and Task 1's TimescaleDB compressed-chunk lessons. Also: oldest-first ordering means the guard protects nothing live until this lands. **Batch its effects into the same next full corpus rebuild as todo 146's grid fix, not a standalone rebuild.** |
| [166](pending/166-1d-ensemble-eligibility-small-sample-treatment.md) | New 2026-07-21, split out of todo 164: `1d`'s median effective-N (1,222, min 143) is ~32x fewer than `15m`'s, CI width 3x wider — a genuine small-sample power problem (Type II error risk), not a miscalibrated threshold like `1h`'s. Needs a real small-sample statistical treatment (Bayesian shrinkage IC or a calibrated day-clustered bootstrap), scoped as its own plan. |
| [171](pending/171-rates-dual-write-symbol-hmm-reversion-check.md) | New 2026-07-22, a "don't forget" item recorded when closing Phase 144: `rates.dual_write_symbol_hmm=true` was deliberately temporary shadow-mode measurement; F1's non-trigger answered the question but only on a scoped 12-symbol run. Batch into the next full corpus rebuild (same cluster as todo 146/155) — confirm F1 holds at full scale before reverting the flag, don't revert on a partial sample, don't forget to ever revisit it either. |
| [172](pending/172-path-dependent-frame-statistics-order-sensitivity-sweep.md) | **Item 2 FIXED 2026-08-03** -- `frame_gate_passes`'s cluster-mean array is now sorted at both the inter-cluster and within-cluster level (the second level needed once testing exposed residual ULP-level float-summation noise from the first fix alone); regression test asserts exact reproducibility across different row-fetch orders. Item 1 (broader path-dependent-statistics sweep elsewhere in the codebase) remains open, unscoped. Did not affect Phase 148's actual gate verdicts (background: `_max_drawdown` over `alpha_frames` silently produced a non-reproducible number because same-`bar_ts` frames were treated as sequential in a cumulative-sum walk -- separately fixed for Gate 2 already). |
| [223](pending/223-src-intelligence-i1-i7-dead-code-153-files-30k-lines.md) | New 2026-08-01, found during a "clean up docs tests scripts dead code" survey pass: `src/intelligence/`'s I1-I7 orchestration/plugin tree (~153 files, ~30k lines) has no live production entry point (`services/intelligence_pipeline.py` is physically deleted) — reachable only via `shadow_validator.py`'s weekly job, which queries a table (`shadow_registry`) already confirmed dead. One clean orphaned duplicate (`features/i5_patterns/`, 17 files) already deleted same day. The rest needs an explicit delete-vs-archive decision plus a matching call on 18 Group-A dead-pipeline tests and 26+ Group-B SLA/I7-plugin tests (Group B depends on whether the paused IBKR ingestion chain resumes through the v2.x signal path or not). |
| [226](pending/226-regime-writer-n-iter-convergence-headroom-check.md) | New 2026-08-02. **Step 1 DONE 2026-08-02**: log `model.monitor_.iter` per (symbol, tf) cell (commit 5c86ffeb + fix 7a0d7de1). Next step: analyze distribution to decide if n_iter=200 cap is oversized. |
| [227](pending/227-ic-engine-adaptive-bootstrap-resample-early-stop.md) | New 2026-08-02. Contingent on a design decision: does `_blocked_bootstrap_ci` need bit-identical reproducibility (load-bearing like HMM) or is a documented tolerance acceptable? That choice gates whether adaptive/early-stopping resample is feasible or requires a full redesign. |
| [228](pending/228-corpus-pipeline-unmeasured-steps-io-vs-cpu-triage.md) | New 2026-08-02. `217` (step-timing instrumentation) is CLOSED (step_timings.jsonl confirmed live) but only captured steps 5-8 so far — steps 1-4 predate the instrumentation landing mid-run. Needs one more full pipeline run from step 1 to get timing data for all 8 steps. Then: classify steps 1/6/7/8 as I/O- vs CPU-bound before applying thread-tuning lessons from todos 215/216. |
| [235](pending/235-cross-sectional-relative-value-5m-construction-never-tested-15m-is-a-default-not-a-finding.md) | New 2026-08-03, user question mid-session. Phase 167's live tracker trades cross_sectional_relative_value at 15m only -- checked, that's an inherited default from the original falsification script, not a comparative finding. The one existing 5m cost-hurdle result (todo 030) tested standalone directional IC, not cross_sectional_relative_value's netted dollar-neutral spread, which the research doc itself says has different cost dynamics. Run cross_sectional_relative_value's actual methodology at 5m before assuming 15m is the right choice. |
| [256](pending/256-ctf-columns-no-explicit-ensemble-exclusion-pending-join-fix-recompute.md) | New 2026-08-05. `ctf_momentum`/`ctf_vwap_align`/`ctf_regime_align` (todo 243's leaked join, unfixed in the live corpus) have no explicit ensemble-eligibility exclusion — currently kept out of `alpha_ensemble_ic` by `ensemble_trainer.py`'s meta-FDR gate on their own (weak/sparse) merits, not by design. Verified live 2026-08-05: none of the 3 clear admission today. Fragile — any future `ic_engine` run could flip that by accident before the join-fix recompute lands. Not urgent (steps 6-8 still blocked on todo 230), but should close before/alongside the recompute plan. |

## P3 — Hygiene, docs, process (opportunistic)

| Todo | What |
|---|---|
| [056](pending/056-phase146-147-v2x-retirement-stale.md) | ROADMAP Phase 147/148 text rewritten 2026-07-19 (operator call resolved: archive not delete, decouple from proof gates). Remaining scope: the actual decommission-in-fact execution (git mv v2.x code to archive/, disable dead systemd units, rename-not-drop the frozen v2.x tables) — real multi-file operation, do with a clean git state. |
| [225](pending/225-multi-vector-systematic-regime-join-hybrid-sensitivity-symbols.md) | Downgraded P2→P3 2026-08-01 per its own pilot finding: read-only pilot on 5 hybrid symbols (`OIH`/`XLE`/`XOP`/`AMLP`/`GDX`) came back negative — the one BH-FDR survivor (`GDX momentum_z_fast`) failed cross-timeframe replication, flat null. Real information, not wasted effort; don't build the Fix steps until a better-motivated candidate surfaces or the universe scales. Full methodology in the todo file's "Pilot result" section. |
| [115](pending/115-days-to-month-end-exact-redundancy.md) | `days_to_month_end` is an exact affine complement of `month_position` (Pearson correlation -1) — perfectly collinear, remove one. |
| [244](pending/244-ctf-vwap-align-regime-align-never-computed-live.md) | New 2026-08-03, found via code review of todo 241's fix. `ctf_vwap_align`/`ctf_regime_align` (siblings of `ctf_momentum`, same batch `_build_ctf_series()`) are never computed live -- sit at the FeatureCache dataclass default (0.0) forever. Zero current blast radius: both were independently tested and rejected (todo 189) -- `ctf_vwap_align` dies on turnover cost, `ctf_regime_align` never clears its own CI. Not worth fixing speculatively for two already-dead features. |
| [258](pending/258-v3-cross-asset-kafka-route-dead-code.md) | New 2026-08-05, filed closing Phase 151 Plan 04 Task 4. `CacheManager.update_cross_asset()`/`topic_cross_asset` (fed by the dead `cross_asset_analyzer.py`, unit `inactive`) is dead v2.x-only code that shares a confusingly similar name with the LIVE, unrelated `FeatureCache.update_cross_asset()` -- same "two same-named methods, one dead" hazard shape as todo 158. The correctness half is already fixed independently (todo 221/222, landed 2026-07-31, before this todo was filed) -- what remains is a naming/dead-code hygiene question plus an open v2.x-revival question this todo can't answer unilaterally. **Superseded by Phase 151 Plan 09's grain-mismatch finding**: todo 221/222's fix was itself wrong-grain and has now been replaced (see todo 261) -- this todo's own "correctness half already fixed" framing is stale, though its actual scope (the dead Kafka route hygiene question) is unaffected. |
| [257](pending/257-feature-registry-worktree-branch-skew-blocks-ic-engine-runs.md) | New 2026-08-05, Phase 151 Plan 02. Concurrent GSD sessions share one physical DB — a worktree whose checked-out `FeatureVector` hasn't merged a sibling session's `feature_registry`/`concept_registry` schema changes fails `ic_engine.py`'s row-count parity gate. Not a code bug, an expected consequence of concurrent sessions; sequence corpus-wide `ic_engine.py` runs behind any in-flight concurrent phase's merge to `main`. |
| [273](pending/273-ctf-bisect-join-duplicated-between-feature-factory-and-recompute-script.md) | New 2026-08-06, found via `/simplify`'s altitude-angle review of todo 243's batching fix. `FeatureFactory.compute_batch`'s inline CTF bisect-join lookup is duplicated a second time in `ops_ctf_columns_recompute_15m.py` (the script's own comment admits it). Pure, low-risk extraction candidate, but touches `compute_batch`'s hot production path — deferred, not a drive-by fix. |
| [263](pending/263-feature-cache-update-cross-asset-dead-code-post-151-09.md) | New 2026-08-05, found in Phase 151's post-execution /simplify pass. `FeatureCache.update_cross_asset()`/`CrossAssetState` are now dead code in production (Plan 09 replaced their only live caller with `build_cross_asset_series()`), but carry ~9 dedicated tests documenting a real historical design decision (todo 222) — needs an explicit keep-or-delete call, not a unilateral cleanup-pass deletion. Zero effect on the batch/corpus recompute path either way. |
| [264](pending/264-equity-beta-z-rate-beta-z-never-wired-on-live-path.md) | New 2026-08-05, /simplify + code review WR-03. `equity_beta_z`/`rate_beta_z` allocated on `FeatureCache` but never computed live (batch/corpus path unaffected). **Partial fix landed 2026-08-05 (WR-03)**: live default changed from a fabricated `0.0` to `None`, honoring `FeatureVector`'s "None means not measured" contract — the actual live wiring (rolling per-symbol OLS beta) remains unbuilt. |
| [265](pending/265-guard-counted-observability-gap-on-live-path.md) | New 2026-08-05, code review WR-04. `_guard_counted()`'s "observable tripwire" for the 10 Theory-Motivated Interaction compounds only reports on the batch path (`_report_guard_counted_substitutions()` called solely from `compute_batch()`) — a live-path substitution silently accumulates in a counter nobody reads. Low likelihood (float64 product of two z-scores essentially can't overflow) and live ingestion is currently stopped, so no current blast radius. |
| [267](pending/267-feature-edge-by-regime-view-duplicates-lifecycle-hook-filter.md) | New 2026-08-05, `/simplify`'s altitude review of todo 251's edge-summary views. `feature_edge_by_regime`'s WHERE clause is a second, independently-maintained copy of `_apply_feature_transitions`' live promotion/demotion filter — no drift tracking if the hook's query changes. Also folds in 2 operational follow-ups from the efficiency review (re-run `ANALYZE`/`EXPLAIN ANALYZE` on both views once the corpus recompute lands with real data — verified against an empty table today). |
| [275](pending/275-v3-north-star-precedentengine-mechanics-predate-d4-rescope.md) | New 2026-08-06, found while doing the AnalogEngine→PrecedentEngine naming correction during a Phase 145 discuss-phase session. `docs/foundation/v3-north-star.md`'s PrecedentEngine mechanics (Score Object, independent-annotator framing, `signal_events` target) predate the D4 rescope that corrected exactly this framing elsewhere (glossary, `intel-precedent-engine.md`). Naming fixed inline + flagged; the mechanics reconciliation itself is real design work, not done here. No live consumer reads this doc's mechanics section today. |

---

(Todo 005's P2→P1 tier change, flagged here 2026-08-03 as "not applied, your call," was applied
2026-08-07 -- see the P1 table above. No longer a candidate.)

(Todo 026's P4a/P4b: not a tier-change candidate anymore, retired out to
[248](pending/248-hmm-full-history-fit-regime-label-instability-gate4-pilot.md) in the P1 table
above -- 026 itself stays in `deferred/` as the historical audit record.)

(Todo 218 resolved 2026-08-03 -- root-caused via direct peer comparison against SHY/IEF,
Hypothesis 1 confirmed, deliberately not fixed -- see `completed/218-...md`. No longer a
candidate; closed.)

**Not in this list:** anything in `deferred/` (phase-gated or corpus-rerun-batched) or
`completed/` (done). Check those folders directly for that work.
