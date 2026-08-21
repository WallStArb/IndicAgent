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

**Phase-level status and in-flight run state:** see `.planning/STATE.md`'s "Strategic Plan"
section (authoritative, live) and
`docs/research/intelligence-lifecycle-backlog-matrix.md`'s Operational Context -- never
duplicated here; a run-status snapshot pasted into this file goes stale within hours and this
file's job is prioritization, not a live dashboard. (Todo 218, the item this paragraph used to
flag as open, was root-caused and closed 2026-08-03 -- see the Status sync entry below and
`completed/218-...md`. This line sat stale for 18 days citing a closed todo as open; caught
2026-08-21.)

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

**Todo 229 CLOSED 2026-08-08 -- record correction, fix has been live since 2026-08-05.**
Moved to `completed/`, dropped from the P1 table. The fix (`monitor_.iter < monitor_.n_iter`
replacing hmmlearn 0.3.3's always-True `monitor_.converged`) shipped in commit `ba8a74ef`
2026-08-05, live in both `_compute_symbol_tf` and `_walk_forward_hmm_full` -- confirmed by
direct grep against `services/regime_writer.py` before closing. This file's row had gone
stale describing the fix as still-unimplemented; it was not, it already shipped, and the
pending file was simply never moved. The blast-radius verification
the fix's own commit deferred to "the next scheduled corpus rebuild" is Phase 171's own
full-corpus refit (plan 171-06), whose per-segment `iters_used` records (plan 171-01) supply
that evidence. See `completed/229-regime-writer-hmm-retry-logic-structurally-unreachable.md`
for the full closing note.

---

## P0 — Fix soon (integrity/correctness gaps already surfaced)

**2026-08-21 cleanup pass:** 318/314/323 all confirmed CLOSED (files verified in `completed/`,
none lingering in `pending/`) and their inline narrative stripped per this file's own
"Not in this list: completed" scope -- same discipline as the 2026-08-03 structure-cleanup
pass, which this table had drifted back away from. Two-table split (a leftover from an earlier
uncoordinated append) also merged back into one. 316/305/270 pointer notes below the table
predate this pass and stay as-is (already narrative-free).

**2026-08-21 link-integrity audit (second, later pass, same day):** scripted a full diff of
every `pending/*.md` filename against every `[NNN](pending/...)` reference across all four
tables. Found and fixed 4 real drift items, no others: **328** was in `pending/` with zero
mention anywhere in this file -- added to the P3 table below. **324**'s row still linked
`pending/330-...` after 330 closed 2026-08-20 (moved to `completed/`, a dead path) -- corrected
to state 330's closure and that 324 is unblocked. **281** sat in the P3 table with a P2
frontmatter and no re-tier rationale (unlike 280/225, which both document one) -- moved to P2.
**257**'s row and file both still described a `feature_registry` gate that Phase 170 `DROP`ped
2026-08-10 -- struck, kept only the still-live `concept_registry` half. Everything else in
`pending/` cross-checked clean: every file appears in exactly one table (or is a documented
deliberate exclusion, like 080's redirect-stub or 270's phase-promotion note), and every
`[NNN](pending/...)` link across all tables resolves to a real file.

316's own row moved to `completed/` — data remediation finished 2026-08-15, all 231 active instruments confirmed present in `feature_vectors`.

305's own row moved to `completed/` — CI check (`tests/unit/test_compressed_hypertable_migration_vacuum_check.py`) landed 2026-08-15, table-scoped per todo 305's own spec, verified against 5 constructed adversarial cases plus the real migration history.

Todo 270's row moved out of this table 2026-08-21 -- promoted to **Phase 173 (Broadcast Feature
Significance Correction)** in ROADMAP.md, per this file's own stated scope ("Phases... are a
separate execution track and do not appear here"). Context captured
(`.planning/phases/173-.../173-CONTEXT.md`): all 23 broadcast features move together, a new
lightweight cell reuses `_subsample_and_rank` per-`(regime_group, tf, regime_label)` against an
equal-weighted aggregate return, same `feature_ic_scores` table/FDR family. Ready for
`/gsd-plan-phase 173`. Todo 270's own file kept in `pending/` as the historical scope record --
not re-closed here, just no longer a P0 backlog item to loop on.

| Todo | Gap |
|---|---|
| [335](pending/335-regime-signal-bucket-tier-order-inversion-commodity-fx.md) | **Missing from this file entirely until 2026-08-21** despite self-tagging `priority: P0` in its own frontmatter since filing (2026-08-19) -- caught by this session's drift audit. Code fix landed 2026-08-20 (commit `db98ac0a3`): two of four `regime_signals` modules (`commodity_momentum_ts`, `fx_dollar_carry`) violated `_bucket()`'s required-ascending-sort contract, producing backwards commodity/fx tier labels live in `market_regimes`. **The in-flight `ic_engine` run (see 306 below) was launched with `--from-step 5`, which skips step 4 -- it is consuming the pre-fix mislabeled commodity/fx rows and will not self-correct.** A detached watcher was queued 2026-08-20 to auto-launch the `--from-step 4` recompute once that run finishes; **found dead 2026-08-21** (process gone, log 0 bytes, never ran) and relaunched more robustly same day (`scripts/ops/corpus/watch_todo335_recompute.sh`, PID 3892989, polls process liveness + `alpha_ensemble_ic` freshness instead of a log-tail banner). See the todo file's own 2026-08-21 update for full detail. |
| [306](pending/306-corpus-pipeline-recovery-after-disk-full-incident.md) | **Re-verified live 2026-08-20, substantially resolved, not still-blocking**: `feature_vectors.regime` is 31,204,768/106,268,964 populated and `.regime_volatility` is 31,004,453/106,268,964 populated (not 0 as originally filed 2026-08-13), and `indicagent-feature-vector-pipeline`/`-writer` are both `active (running)` (not `failed`) -- resolved through the 2026-08-15+ corpus pipeline relaunches, not through this todo's own 5-step plan directly. **Do not close once the in-flight run finishes** -- per 335 above, that run's commodity/fx cross-sectional cells are known-mislabeled and a second pass (`--from-step 4`, watcher-gated) is required before this can be called done. Live IBKR ingestion status also still not re-checked. |

## P1 — High value, quick, fully unblocked

**2026-08-21 cleanup pass:** stripped 11 confirmed-CLOSED rows (330/326/327/312/307/259+296/
293/277/278/169/251 -- all verified present in `completed/`, none in `pending/`), same
discipline as the P0 table above. The stale 337-duplicate note (below) predates this pass.

**276 CLOSED 2026-08-21 -- audited, CLEAN, row removed from this table.** Phase 163-165's
batch feature computations were checked against the same lookahead-leak shape that hit
`ctf_momentum` and `regime_writer`'s HMM fit; every call site pre-slices to a strictly causal
window and swing/pivot detection has a real, math-enforced confirmation lag, not just
convention. Full evidence in `completed/276-...md`. This was the last of the three gating
items for the single-security alpha refinement plan (with 277/278, already closed) -- all
three now clear.

337's row removed from this table 2026-08-21 -- stale duplicate left behind when it was
re-tiered P1→P2 on 2026-08-20 (the P1 row never got deleted, only the P2 row was added). Current
status lives in the P2 table only.

| Todo | Why now |
|---|---|
| [287](pending/287-legacy-regime-probability-columns-leak-into-ensemble-training-matrix.md) | **Fix landed 2026-08-12, committed 2026-08-13** (`9469b0a50` -- row corrected 2026-08-21, commit confirmed via `git log`, was stale-flagged "uncommitted"): `_META_COLS` now uses `*REGIME_WRITER_OWNED_COLUMN_NAMES` (shared constant, matches the sibling `regime_volatility` family's pattern) instead of a hand-typed 4-of-8 subset -- closes the leak (`hmm_prob_trending_up`/`hmm_prob_ranging`/`hmm_prob_trending_down`/`hmm_churn` were silently 0.0-imputed for unlabeled rows) permanently, can't drift apart again. New regression test added, full `tests/unit/` suite green. **Still open: impact assessment (size the correction, re-run `ensemble_trainer`)** -- don't close until done. **Update 2026-08-13: the corpus pipeline this was banking on FAILED at step 2 (disk-full incident) and never reached step 7** -- `ensemble_trainer` still needs its own explicit re-run, nothing picked this up automatically. |
| [285](pending/285-phase172-full-scope-ic-engine-verification-after-volatility-cutover.md) | **Unblocked 2026-08-11** (was missing from PRIORITIES.md, blocked-on-Phase-172 framing stale). Phase 172's volatility-only HMM cutover is confirmed EXECUTED+COMPLETE (2026-08-09) but only ever validated by its own 4-symbol/1d smoke test -- this is the full-scope corpus verification that smoke test explicitly does not perform. Matches "earn promotion through proof" -- a completed phase's cutover correctness isn't actually confirmed at scale yet. |
| [240](pending/240-nonlinear-interaction-combiner-baseline-is-single-feature-not-the-linear-ensemble.md) | From a rigor review of the Edge Source Thesis doc. nonlinear_interaction_combiner's pre-registered falsification bar says the tree must beat "the existing linear ensemble"; every run actually compared it to `ctf_momentum` alone. **Code landed + committed 2026-08-03** (`816032e2`): a fold-local linear-ensemble arm (`fit_linear_ensemble_weights`/`score_linear_ensemble`, reusing `ensemble_trainer.py`'s own weighting primitives) plus a paired-bootstrap PRIMARY VERDICT (tree vs linear), `ctf_momentum` kept as secondary. Independent review caught and fixed 2 blocking issues (features weren't z-scored before weighting; memory footprint too close to this module's prior OOM history) -- both fixed in the same commit. **Re-run at 1h/15m/5m gated on todo 243's corpus-recompute decision** (todo 245, all 3 tfs measured and CLOSED 2026-08-04 -- the training matrix confound is now quantified, not just flagged; the training matrix still includes lookahead-contaminated `ctf_momentum` until 243's corpus recompute happens) -- **1d re-run is safe and unblocked right now.** Gates todo 238. |
| [239](pending/239-nonlinear-interaction-combiner-embargo-passed-in-pooled-panel-rows-not-bars.md) | Same review. `_nonlinear_interaction_combiner_shared.py` passed `embargo_bars` into `build_walk_forward_folds(n_valid=len(X))` where `X` is the **pooled** ~80-rows-per-bar panel, so the intended 1-day embargo was 24/96/5 *rows* ≈ 0.3/1.2/0.06 bars at 1h/15m/1d, and fold boundaries split inside a single `bar_ts`. Bounded blast radius (~800 rows of ~2-8.5M, does NOT explain the 0.18-0.25 IC) but cited in the research doc as a rigor credential. **Code landed + committed 2026-08-03** (`816032e2`, same commit as 240): new `_pooled_panel_folds()` builds folds over the distinct `bar_ts` index and maps back to row slices; `build_walk_forward_folds` itself untouched. **Re-run gating: same as 240 -- 1d safe now, 1h/15m/5m wait on todo 243's corpus recompute.** |
| [238](pending/238-nonlinear-interaction-combiner-ranked-cross-sectional-relative-value-pre-registration.md) | New 2026-08-03, from a user-directed rigor review of Edge Source Thesis next steps. Both cross_sectional_relative_value (proven construction) and nonlinear_interaction_combiner (proven 3-5x-stronger signal) are independently validated at 15m; nobody has tested cross_sectional_relative_value ranked by nonlinear_interaction_combiner's tree score instead of `ctf_momentum` — highest-expected-value untested combination on the doc. Pre-registered falsification design (shuffled null, cost-hurdle, turnover, Gate-2-equivalent factor-attribution, breadth-preservation) written down before running, per this project's own pre-registration discipline. **Gated on cross_sectional_relative_value's own Gate 1/Gate 2 re-verification landing first** (todo 243 -- 253's own prerequisite fix already closed 2026-08-04) -- ranking by a tree score doesn't matter if the underlying construction's proof itself is unverified; testing this now would build on the same unresolved foundation. |
| [248](pending/248-hmm-full-history-fit-regime-label-instability-gate4-pilot.md) | New 2026-08-03, retired out of `deferred/026`. Instability confirmed at 3 symbol/tfs (24.9-56.8% label agreement depending on tf). **Wired 2026-08-05**: `_compute_symbol_tf_walk_forward` (full production-parity path -- per-segment convergence retry, degenerate-segment gating, all `feature_vectors` columns, not just bare labels) added to `regime_writer.py`, dispatched via APR flag `alpha.hmm.walk_forward.enabled` (migration 292, **seeded `false`** -- landing the code changes zero existing regime label). Per-tf `refit_every_bars`/`initial_warmup_bars` seeded for all 4 tfs (1h/15m pilot-measured, 5m scaled-not-piloted, 1d unpiloted estimate -- see migration 292's per-key provenance). **Remaining work is now purely a deployment decision, not implementation**: flip the flag, run `regime_writer.py --refit`, then a downstream `ic_engine` recompute (same blast-radius class as an `HMM_RANDOM_STATE` change) -- still queued behind CTF/Phase 167 per the 2026-08-04 sequencing decision, unaffected by this session's wiring work. |
| [065](pending/065-emission-layer-calibration-proposals.md) | EM-CAL threshold calibration — both prerequisite gates (rebuild, EIC-04) cleared 2026-07-09. **Caution added 2026-07-30**: that clearance predates todo 146/208's grid rework (per-tf lookahead grid; 208's session-gate premise is now fixed, but the grid's actual values are still open, see 208's row below). **Unblocked 2026-08-03**: the corpus pass this was waiting on completed 2026-08-02 21:19 UTC (see preamble). Ready to calibrate against the corrected corpus now — real design/execution work, not mechanical. |
| [079](pending/079-anytime-valid-e-values-corpus-reruns.md) | Anytime-valid inference pilot (one tf) — new statistical primitive, deliberately staged small |
| [005](pending/005-ic-regime-transition-purge.md) | **Raised P2→P1, 2026-08-07.** Was sitting unblocked-but-idle since 2026-08-02 (its own gate cleared, attention went to the CTF investigation instead). Sharper than a P2 label suggests: `market_regimes` (what `ic_engine.py` actually stratifies on) does pure per-bar threshold bucketing with **zero transition guard of any kind** — not even the hysteresis the per-symbol HMM path already has. A live measurement-integrity gap underneath every regime-stratified IC test this project runs, not just an optimization. Also unblocks `docs/research/measurement-adaptive-combiner-weights.md`'s L5-1 (highest-conviction ensemble E-candidate). Recommend running as a third parallel diagnostic alongside `jump_diffusion_decomposition`/`cointegrated_pairs_residual` — disjoint, read-only, same resource shape. |
| [054](pending/054-shadow-alpha-events-monitoring.md) | Shadow alpha_events monitoring — prevents delayed detection of feature decay/threshold bugs |
| [167](pending/167-equity-cross-sectional-vs-symbol-hmm-never-falsifier-tested.md) | **Plan changed 2026-07-29 — no longer a standalone equity-scoped relaunch,** folded into 176's queued sequence (market-data-gap catchup → 176's `--refresh` → one full-corpus `ic_engine` pass). **176's `--refresh` step confirmed run 2026-07-30**, but the sequence's final step (a full-corpus equity+rates `ic_engine` pass) status is unclear post-2026-08-02 (see preamble) — that pass is what would actually close this todo. |
| [261](pending/261-deploy-grain-corrected-cross-asset-mechanism-once-ingestion-resumes.md) | New 2026-08-05, closing Phase 151 Plan 09. Code+tests complete and merged: replaced todo 221/222's per-timeframe `CrossAssetState` live mechanism (a confirmed grain mismatch — computed from THIS TIMEFRAME's own intraday bars, not the canonical daily-broadcast definition every IC/gate measurement was built against) with a daily-grain mechanism sharing the batch path's own `build_cross_asset_series()`. Deployment (live daemon restart + Task 3's verification) deliberately NOT done in that plan's execution — ingestion is still paused (`max(bar_ts)` 8 days stale, restarting proves nothing right now) and this is a full mechanism replacement an unattended session shouldn't push live without operator sign-off. |
| [283](pending/283-new-universe-symbols-thin-tags-and-unrouted-from-regime-groups.md) | New 2026-08-08, found writing `docs/foundation/instrument-data-model.md`. 115/151 (76%) of the symbols added in the 2026-08-05/06 universe expansion carry no `exposure`-prefix tag and are silently excluded from all regime-stratified IC — same failure mode as todo 280 (5/17 unrouted) but ~20x the scale and specific to the recent expansion. Merge scope with 280 before fixing either. |
| [280](pending/280-single-name-equity-symbols-unrouted-from-regime-groups.md) | New 2026-08-08, found during Phase 171's HMM regime investigation. `single_name_equity`-tagged symbols (AAPL/MSFT/GOOGL/AMZN/JPM tested here, likely many more in the 231-instrument universe) match no enabled `alpha.regime.groups` tag_filter, so every single-name equity is silently excluded from regime-stratified `feature_ic_scores`. **Re-tiered P3→P1, 2026-08-08**: was misfiled under P3 despite the file's own P2 frontmatter; todo 283 found the same gap at ~20x this sample's scale, confirming this is a live measurement-integrity issue, not hygiene. Merge scope with 283. |

## P2 — Real value, not urgent

**2026-08-21 backlog audit:** [281](pending/281-systematic-dominance-and-volume-price-confirmation-as-feature-primitives.md)
re-tiered P3→P2 -- misfiled under P3 with no documented reason (unlike 280/225, which both carry
an explicit re-tier rationale), against its own P2 frontmatter. Content is real, scoped
feature-primitive work with a concrete next step (add columns, then a Phase-144-D-05-shaped
separation test), not hygiene.

| Todo | What |
|---|---|
| [281](pending/281-systematic-dominance-and-volume-price-confirmation-as-feature-primitives.md) | New 2026-08-08, out of Phase 171's candidate-regime-axes test. Two real, null-arm-validated signals (idiosyncratic-vs-market co-movement, volume-price confirmation) should ship as plain `feature_vectors` columns, not HMM regime labels — identifiability for both is too narrow/fragile to trust as a discrete regime. |
| [340](pending/340-ihf-5m-feature-compute-zero-row-positive-input-error.md) | New 2026-08-21, split out of todos 259/296's closure. `IHF`/`5m` has zero `feature_vectors` rows -- `"expected a positive input, got 0.0"` compute error, likely a `log()`/division call in `FeatureFactory.compute_batch` hitting a genuine zero (volume or price) on a specific bar for this thinly-traded sector ETF. Single symbol/tf, bounded blast radius, not investigated further yet. |
| [341](pending/341-bil-etha-ibit-zero-regime-labels.md) | New 2026-08-21, found by `regime_coverage_auditor.py`'s first live production run (todo 169). `BIL`/`ETHA`/`IBIT` have 100% NULL `feature_vectors.regime` -- same failure shape as todo 168 (7 different symbols, closed). Plausibly related to `BIL`'s separate compute-underflow finding (todo 340's sibling note) via BIL's near-zero-volatility character; `ETHA`/`IBIT` may just be short-history crypto-trust ETFs below the HMM warmup requirement. Not investigated further yet. |
| [334](pending/334-has-gap-before-entry-never-set-dead-column.md) | New 2026-08-16, added to PRIORITIES.md 2026-08-21 (was missing entirely -- this session's drift audit). `forward_returns.has_gap_before_entry` had been dead since the table existed (permanently `false`, never written by `forward_return_writer.py`), making `ops_cost_hurdle_calibration.py`'s gap-contamination check structurally incapable of ever firing. **Write-path fix already landed and verified same session** (29/29 tests, synthetic positive-control cases confirmed correct) -- future rows get the real computed value. Remaining scope is narrower than the original finding: a retroactive backfill of the 103M existing rows, deliberately deferred (compressed hypertable, same blast-radius class as the 2026-08-13 disk-full incident) until planned with the performance-investigation SOP. |
| [342](pending/342-daily-slot-generation-not-generalized-beyond-nyse.md) | New 2026-08-21, `/simplify`'s altitude-angle review of todo 300's fix. `1d` gap-detection was only fixed for `session_id='nyse'` -- futures/fx/crypto `1d` bars still fall through to the buggy interval-stepped path. Currently dormant (zero futures/fx `1d` rows exist live), but nothing prevents it triggering the moment a `1d` backfill ever runs against those asset classes. Deliberately not generalized alongside 300 -- no live data to test the fix against for those session types. |
| [343](pending/343-regime-writer-backfill-feature-factory-write-isolation-shared-helper.md) | New 2026-08-21, `/simplify`'s reuse-angle review of the full session's diff. `backfill_feature_factory.py`'s new per-cell write-isolation loop (todo 318) duplicates a shape `regime_writer.py` already established, with no shared helper in `_batch_utils.py` capturing it. Not extracted this session -- touches an unrelated, live, well-tested batch writer outside the reviewed diff. |
| [344](pending/344-bar-normalizer-slots-nyse-should-reuse-marketcalendar.md) | New 2026-08-21, `/simplify`'s simplification-angle review of todo 300's fix. `_slots_nyse` (intraday) still maintains its own separate NYSE calendar (`_NYSE_CAL`/raw `mcal.schedule()`), unlike the new `_slots_nyse_daily` which correctly reuses `MarketCalendar`. Also found: `MarketCalendar`'s pre-built range only covers 2005-2035 -- confirmed NOT a live issue (earliest `1d` row is 2006-03-22). Needs a new `MarketCalendar` accessor (open/close times) before `_slots_nyse` can migrate -- real API-surface expansion, not a drive-by fix. |
| [345](pending/345-backfill-feature-factory-decompress-prep-serialized-before-compute.md) | New 2026-08-21, `/simplify`'s efficiency-angle review of todo 318's fix. `_write_session`'s decompress/GUC-prep phase (documented as expensive) is fully serialized in front of worker compute instead of overlapping with it; `pool.map()`'s submission-order iteration also head-of-line-blocks fast writes behind slow earlier symbols. Fix requires restructuring `pool.map()` to explicit `submit()`+`as_completed()`, which would break every existing test's `mock_pool.map.return_value` mocking -- deferred as a scoped follow-up rather than a risky mid-`/simplify` rewrite. |
| [337](pending/337-concept-gate-counter-advance-no-cas-lock-and-per-run-write-volume.md) | **Re-tiered P1→P2, 2026-08-20**: finding 3 (optimistic lock) fixed same day, only finding 4 remains -- `advance_active_counters_sync` now writes+logs once per active concept every corpus run (~200 sequential single-row commits) instead of just `shadow_only` concepts. Real overhead in the direction of CLAUDE.md's batched-write guidance, but small in absolute terms against a multi-hour+ corpus run; its own filing text already said "not urgent." Fix, if pursued: collect `(feature_name, passed)` pairs across the loop, one batched UPDATE after. |
| [329](pending/329-timeframe-subset-vocabulary-group.md) | New 2026-08-16, from todo 327's final whole-branch review. `signal_auditor.py`'s `_COVERAGE_TFS` and `feature_validation_analyzer.py`'s `_TIMEFRAMES` hold byte-identical literal timeframe subsets - literally D-07's own admission condition, and CVR already has `vocabulary_group` for exactly this. Todo 327 gave both a drift-guard assertion instead (correct, since forcing them onto the full set would silently change production behavior), but the assertion doesn't catch the two literals drifting apart from each other. Zero behavior change to fix - registry-visibility only. |
| [331](pending/331-vocabulary-drift-auditor-windowed-query-blind-spot.md) | New 2026-08-16, from todo 327's final whole-branch review - the root-cause explanation for why migration 233's missing `4h` code sat undetected for 3 years. `VocabularyDriftAuditor`'s source queries are all window-bounded (`infra.vocabulary_drift.window_days`, default 30); a code that's rare/sparse enough to fall outside any given window is structurally invisible to the auditor, indistinguishable from "no data at all." Applies to every namespace it checks, not just `timeframe`. Needs design, not obvious - see todo for options weighed. |
| [315](pending/315-regime-writer-log-rotates-too-fast-fd-stuck-on-deleted-inode.md) | New 2026-08-14, found live babysitting the 5th `regime_writer` relaunch — two Monitor stall alarms were false positives, root-caused to `logs/regime_writer.log*` rotating every ~7-15min (trigger unidentified, not the daily `logrotate.timer`), stranding the process's stdout/stderr fd on an unlinked inode (data loss risk on the next rotation, incl. any future crash traceback) while its actual internal file handle keeps tracking the live path. Not blocking the current run. |
| [317](pending/317-backfill-status-migrate-to-anti-join-checkpoint-pattern.md) | New 2026-08-14, split out of todo 316's `/simplify` altitude review. `backfill_status.status='complete'` is the only side-table checkpoint of its kind left in `services/*.py` — every other batch writer (`alpha_frame_writer.py`'s documented "Pattern 4", `regime_writer.py`, and `ic_engine.py` which deleted a decoupled `.pkl` checkpoint outright for this same root cause) queries the target table directly instead. Todo 316's fix reconciles the desync after the fact; this is the deeper fix — eliminate the second source of truth. Not urgent: 316 already makes the current design self-detecting/self-healing. |
| [313](pending/313-audit-remaining-bulk-update-by-key-col-types-drift.md) | New 2026-08-14, split out of todo 312's fix. The systemic `bulk_update_by_key` clamp protects any caller whose `col_types` is correct; this is the remaining work to find callers (outside `bulk_update_by_key`, or with still-undetected `col_types` drift) whose metadata might still be stale against migration 312's 303-column type-narrowing sweep. |
| [309](pending/309-vulture-baseline-cleanup-backlog.md) | New 2026-08-14, filed wiring vulture (dead-code detection) into CI for the first time — it had sat in `requirements.txt` unwired since before this session. CI now blocks any *new* dead code; the 1136 pre-existing findings were frozen into `tools/vulture_whitelist.py` rather than triaged by hand (real dead code is mixed in with known dataclass/Pydantic false positives). One freebie found + fixed inline: an `if False else` unreachable branch in `src/intelligence/ai/context.py`. |
| [339](pending/339-backfill-feature-factory-worker-rows-unbounded-memory-across-ipc.md) | New 2026-08-21, split out of todo 318 Bug 2's fix (`/simplify` + `/code-review` both converged on it). Making workers compute-only (CLAUDE.md invariant) means each now returns every computed row for a symbol across all 4 timeframes in one shot instead of streaming `insert_batch_size` chunks as it goes -- bounded to ~191K rows/symbol worst case (full-depth `--refresh`), same `update_rows`-over-IPC shape `regime_writer.py` already uses, just proportionally heavier per row. Not a correctness bug, deferred rather than expanding the fix's diff further; fix shape (APR-capped `n_workers` for refresh runs, or a deeper chunk-granularity IPC redesign) not yet decided. |
| [308](pending/308-compressed-hypertable-registry-should-be-live-cached-not-hardcoded.md) | New 2026-08-14, split out of todo 306/307's compressed-hypertable-write-session fix. `_KNOWN_COMPRESSED_HYPERTABLES` (`services/_batch_utils.py`) is a hardcoded set `bulk_update_by_key`'s hot-path guard checks -- the "missing entry" drift direction is silent and unprotected (guard just never fires), unlike the harmless "stale entry" direction. Deliberately deferred (bounded: only 2 tables affected today, both correctly protected) rather than bolted onto an already-large diff -- recommended fix mirrors ConfigService/VocabularyService's cache-at-init pattern. |
| [303](pending/303-per-symbol-trend-regime-null-arm-tested-candidate.md) | New 2026-08-12. No validated per-symbol trend axis exists -- the old `regime` (K=5) claimed to be trend but Phase 171/172's null-arm control found it was actually a volatility partition; `regime_volatility` (the correct replacement) is live but measures volatility, not trend. **Stage 1 PASSED 2026-08-12** (`per_symbol_trend_candidates_stage1_pilot.py`). **Stage 2 + Stage 3 code both built 2026-08-14, shared with 304** (`per_symbol_regime_candidates_stage2_orthogonality.py`, `per_symbol_regime_candidates_stage3_falsification.py`, 16 unit tests green) -- corrected the pre-registered N>20,000-bars gate (unreachable at 1d/5-symbol scale) to run at 5m/15m instead; no `ic_engine` dependency after all. Both gated on `regime_writer`'s `regime_volatility` pass finishing (in progress). Disjoint from `statistical_factor_residual`, can run in parallel, but don't open as a third unfinished thread. |
| [304](pending/304-per-symbol-percentile-rank-candidates-volume-skew-volatility.md) | New 2026-08-12, companion to 303 (different mechanism family -- percentile-rank-of-zscore, not Hurst/trend). Three candidates: `volume_pct`, `skew_tail`, `volatility_pct` -- the last one doubles as a simplification test (does a plain rank beat the `regime_volatility` HMM's added complexity for the same measure). **Stage 1 PASSED 2026-08-12** (`per_symbol_regime_candidates_stage1_pilot.py`). **Stage 2 + Stage 3 code both built 2026-08-14, shared with 303** -- see 303's row for the shared scripts and the N-gate/timeframe correction (5m/15m, not 1d). Gated on `regime_writer`'s `regime_volatility` pass finishing (in progress). |
| [255](pending/255-counterfactual-tracker-evaluate-gate-no-d04-governance.md) | New 2026-08-04, added to PRIORITIES.md 2026-08-11 (was missing entirely, self-tagged P2 in its own frontmatter). Split out of todo 253 while wiring D-04 governance into `cross_sectional_spread_tracker.py` -- same gap, different phase, deliberately not fixed in that pass to avoid expanding its blast radius. |
| [274](pending/274-live-tradeable-vs-corpus-universe-flag.md) | New 2026-08-06, added to PRIORITIES.md 2026-08-11 (was missing entirely). `instruments` has no column distinguishing "eligible for live IBKR streaming" (80-subscription cap) from "part of the backfill/corpus measurement universe" (231 active) -- `get_active_contracts()` collapses both into one `is_active` boolean. Real design question, unblocked, no urgency while ingestion stays paused. |
| [272](pending/272-instrument-tag-peer-group-coverage-auditor.md) | New 2026-08-05 (renumbered from 271), added to PRIORITIES.md 2026-08-11 (was missing entirely, and this project's memory has been citing it under the stale "todo 271" number -- fixed). No automated audit for thin/missing `instrument_tags` peer-group cardinality -- every gap found so far (this todo, plus todos 280/283's specific instances) was found by a human asking "what about X?", not a query. Distinct from 280/283 (which are the specific data gaps already found) -- this is the general tooling to catch the next one automatically. |
| [286](pending/286-build-obs-matrix-nested-rolling-warmup-artifact-in-vol-of-vol.md) | New 2026-08-09, added to PRIORITIES.md 2026-08-11 (was missing entirely). Phase 172 cross-AI review (Antigravity, LOW severity, the one finding neither reviewer duplicated) -- `_build_obs_matrix`'s `valid_start` warmup calculation is correct for 4 of 5 observation columns but not for `vol_of_vol` (a rolling-std-of-a-rolling-std, needs `2x` the window, not `1x`). Minor HMM observation-matrix artifact, not a stratification-label-level bug. |
| [301](pending/301-bulk-insert-shared-primitive-vs-local-batching.md) | New 2026-08-11, filed by a `/simplify` pass on this session's `store_bars()` batching fix. Two independent review agents (reuse + altitude angles) converged on the same point: the fix diverges from `forward_return_writer.py`'s chunked-`executemany()` convention and an existing `ic_engine.py` comment arguing against manual VALUES batching -- comment fixed to note the divergence is deliberate (backed by a live 2x benchmark, not theory) rather than reconciled. Real follow-up: promote to a shared COPY-based `bulk_insert` primitive in `_batch_utils.py` (matching `bulk_update_by_key`'s precedent) and point all `market_data_ohlcv` writers at it, including the untouched sibling in `backfill_feature_factory.py:896`. |
| [294](pending/294-doc-tail-feature-registry-present-tense-sweep.md) | New 2026-08-10, filed closing Phase 170 (todo 118). `feature_registry` was DROPped (migration 311) but 44 doc files still mention it -- most correctly, as historical record. Targeted audit for the present-tense-claim subset (4 candidates flagged, not verified), not a blind sweep. |
| [292](pending/292-hmm-vol-churn-corpus-values-predate-wr01-fix.md) | New 2026-08-09, filed closing Phase 172's code-review gate. WR-01's churn-fabrication-across-segment-gap fix (commit `fdc14050`) landed after plan 172-05's corpus relabel already wrote 9.4M `hmm_vol_churn` rows with the pre-fix buggy logic -- confirmed legacy `hmm_churn` (27.9M rows) unaffected (`alpha.hmm.walk_forward.enabled=false`, that path never ran in production), but every `hmm_vol_churn` row needs a decide-or-recompute call. `regime_volatility` itself (the label `ic_engine.py` actually stratifies on) is completely unaffected. |
| [291](pending/291-regime-volatility-structural-duplication-followups.md) | New 2026-08-09, Phase 172's own `/simplify` gate (reuse/simplification/altitude angles, flagged independently by 2-3 reviewers each). Three functions in `regime_writer.py` (`_compute_symbol_tf_volatility_walk_forward`, `_fetch_obs_matrix_volatility`, `_write_regime_volatility_results`) duplicate their trend-path counterparts instead of sharing them via the `vocab` parameterization the inner layers already use. Deliberately deferred out of the phase's own cleanup pass -- touches HMM-fitting/DB-write hot paths, deserves dedicated test coverage rather than a drive-by refactor right after the corpus relabel landed. |
| [290](pending/290-regime-volatility-memory-and-query-efficiency-followups.md) | New 2026-08-09, Phase 172's own `/simplify` gate (efficiency angle). Real, measured costs: `_build_obs_matrix_volatility`'s rolling-std at window=250 can allocate up to ~9.5GB concurrent transient memory across a 12-worker pool (real OOM risk on a future full corpus `--refit`); per-cell `count(*)` verification queries cost ~10min aggregate per corpus run; `vocabulary_drift.py` scans `feature_vectors` twice per audit run instead of once. `ic_engine.py`'s startup-gate `count(*)`→`EXISTS` (measured 75x) already fixed inline during the phase's own cleanup pass; this todo is the remaining items. |
| [289](pending/289-regime-volatility-1d-sparse-coverage-refit-schedule-mismatch.md) | New 2026-08-09, found closing Phase 172 plan 172-05's corpus relabel. `regime_volatility`'s 1d-timeframe coverage is genuinely sparse (45% of cells skipped vs 8-11% at 5m/15m/1h) -- root-caused to `alpha.hmm.walk_forward.refit_every_bars.1d = 252` never being re-validated against the phase's new 250-bar `vol_window`/`vol_of_vol_window`. Shared key with the legacy `regime` family, needs its own investigation/gate. |
| [288](pending/288-feature-vectors-left-decompressed-after-phase172-relabel.md) | New 2026-08-09, found closing Phase 172 plan 172-05. `feature_vectors` left fully decompressed (0/83 chunks, was 80/83) after the relabel hit a genuine TimescaleDB compressed-chunk write-cost blocker -- third incident of the todos-149/161 failure shape. Storage/ops tradeoff, not a correctness gap; decide whether to recompress or redesign the compression policy so future batch-UPDATE regime relabels don't hit the same wall. |
| [279](pending/279-fxa-ipo-sdog-incomplete-15m-backfill-old-universe.md) | New 2026-08-08, found sanity-checking the alpha_score single-security diagnostic. FXA (52.5%)/IPO (77.9%)/SDOG (82.8%) have lower 15m bar counts than universe peers -- **downgraded P1->P2 same day**: a full 21-symbol batch check found a smooth liquidity-correlated gradient (currency/niche ETFs low, large heavily-traded ETFs 99.5-100%), more consistent with genuine thin trading than an incomplete backfill. Does NOT undermine the single-security diagnostic's SDOG finding after all. Real remaining item: `backfill_status` has its own bookkeeping bug (`rows_written` exceeds `theoretical_max`), independent of the liquidity question. |
| [282](pending/282-instrument-metadata-not-backfilled-for-universe-expansion.md) | New 2026-08-08, found writing `docs/foundation/instrument-data-model.md`. `instrument_metadata` has 0% coverage for the 151 symbols added in the 2026-08-05/06 universe expansion — table hasn't been written to since a single 2026-06-20 bulk seed. No live consumer found reading this table, so purely descriptive/hygiene, not urgent. |
| [302](pending/302-ibkr-pre-listing-void-query-cancelled-not-fast-skipped.md) | New 2026-08-12, found during client-49's full-universe catch-up backfill. IBKR's `Error 162: query cancelled` (pre-listing void, e.g. GEV's 18-year gap) isn't recognized by the fast no-data skip (`_no_data_req_ids` only matches "HMDS query returned no data"), so it falls through to the full 3-attempt retry storm (~195s+ wasted) per chunk instead. Performance/efficiency bug, not correctness -- pipeline still completes right. |
| [099](pending/099-bootstrap-ci-staged-validation-gate-not-cleared-5m-residual.md) | The bootstrap CI staged-validation gate's 6 SUSPECT cells trace to 5 diagnostic-only (`is_pooled=false`) breaches + 1 capital-relevant cell that independently clears its own bound — no longer blocks Plan 07. Underlying statistical question (why 5m autocorrelation/momentum features resist both Fisher-z and block-bootstrap) remains open as non-blocking follow-up. |
| [208](pending/208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md) | **Updated 2026-07-31 — characterization run is COMPLETE, not still pending.** Steps 1/2 DONE (`forward_return_writer.py`'s same-ET-session gate removed for 5m/15m/1h, `forward_returns` rebuilt clean). The run confirmed migration 269's grid values hold under corrected semantics — no re-migration needed. This todo's remaining scope is now the deeper method question it surfaced: does decay-walk-on-pooled-median-IC even make sense for `hold_max_bars` selection, given IC rises alongside CI width rather than decaying within any tested horizon. Real design pass needed (3 candidate approaches in the file), not mechanical. Not blocking anything, including the in-flight `ic_engine` run. |
| [213](pending/213-rolling-vp-suppressed-for-1d-never-independently-reviewed.md) | New 2026-07-30, found while closing 176: `poc_rolling_dist_atr`/`poc_session_rolling_divergence_atr` (D-18's rolling-track VP additions, tf-agnostic by construction) are suppressed for `tf='1d'` via the same code branch as session VP (which correctly doesn't apply to 1d) -- but the rolling case was never independently reviewed for tf-applicability across any of Phase 163's three design-review passes. Likely dropping real signal (a 1d bar's dislocation from a ~2-year value anchor is a coherent auction-market-theory concept per D-18's own argument), not a considered exclusion. Needs an incremental-IC check before promoting, same discipline as any other structural column. Renumbered from 209 -- collided with a same-day, independently-filed todo from the per-tf-active-scale-set final review. |
| [186](pending/186-ic-math-cross-sectional-block-bootstrap-gap.md) | New 2026-07-26, same review as 185: `ic_math.py` has a per-symbol circular block bootstrap but no cross-sectional (pooled-panel) variant, so nonlinear_interaction_combiner's within-bar_ts rigor check approximated it ad hoc. Lower urgency than 185 — the approximation is conservative and the script says so; do this once a real (non-exploratory) cross_sectional_relative_value/nonlinear_interaction_combiner candidate needs it. |
| [214](pending/214-ic-engine-ensemble-ic-engine-shared-compute-refactor.md) | New 2026-07-30, user question mid-session: `ic_engine.py` (5,239 lines) and `ensemble_ic_engine.py` (1,523 lines) independently duplicate the same per-scale compute pattern instead of sharing one implementation — exactly the duplication that let todo 210's bug (one engine masks on `complete_{scale}`, the other silently didn't) exist undetected. **One narrow slice landed 2026-07-30** (commit `955e6fbe`) — the `{scale: {tf: lookahead_bars}}` dict-construction duplicated across `ic_engine.py`/`ensemble_ic_engine.py`/`ops_ensemble_ablation.py` was consolidated into `lookahead_by_scale_from_apr()` (`services/_batch_utils.py`). The actual compute-core consolidation (fetch → mask → rank-IC → walk-forward folds) this todo describes is still open — real refactor, deliberately deferred until the current IC measurement chain (208/210/209/211's fixes, a fresh corpus rebuild) is stable again. |
| [177](pending/177-bar-history-maxlen-caps-windows-beyond-200.md) | **Step 1 (enumeration) done 2026-07-31** — 22 `FeatureFactoryConfig` fields confirmed >200 bars; 19 genuinely `BarHistory`-capped, 2 (`vix_zscore_window`/`yield_curve_zscore_window`) turned out to be a worse, unrelated dead-code-path bug, split out and fixed separately (todo 221, closed). Steps 2-3 (fix-shape decision + IC verification) still correctly deferred pending corpus rebuild. |
| [101](pending/101-migration-duplicate-number-sweep.md) | **Stale row corrected 2026-08-03**: the original 14-group finding was resolved in commit `18551320` (2026-07-18). Current remaining scope is narrower — one brand-new collision at `240` (two concurrent worktree sessions), caught by the guard test (`tests/unit/test_migration_number_uniqueness.py`) and allow-listed there pending a dedicated renumbering session. **Confirmed 2026-08-03: do not casually rename either 240 file** — both are already applied to the live DB; the guard test's own docstring explicitly scopes renumbering as its own higher-risk session, not a quick fix. |
| [108](pending/108-hmm-multi-seed-restart-best-likelihood.md) | `regime_writer.py`'s HMM fit uses a single seed with a same-seed convergence retry, not multi-seed-restart-and-keep-best-log-likelihood. Robustness gap, not a proven bug. **Update 2026-08-02:** todo 229 found the `n_restarts > 1` convergence-vs-likelihood tiebreak this todo relies on has been silently degraded to pure-likelihood ranking by the same `monitor_.converged` bug — 229's fix revives the intended tiebreak behavior as a side effect. **229 CLOSED 2026-08-08** (fix live since commit `ba8a74ef`, 2026-08-05) — re-read `completed/229-regime-writer-hmm-retry-logic-structurally-unreachable.md` before scoping any further work here. |
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
| [256](pending/256-ctf-columns-no-explicit-ensemble-exclusion-pending-join-fix-recompute.md) | New 2026-08-05. `ctf_momentum`/`ctf_vwap_align`/`ctf_regime_align` (todo 243's leaked join, unfixed in the live corpus) have no explicit ensemble-eligibility exclusion — currently kept out of `alpha_ensemble_ic` by `ensemble_trainer.py`'s meta-FDR gate on their own (weak/sparse) merits, not by design. **Re-verified live 2026-08-07 against the post-join-fix, post-todo-230-resolution corpus (0.0/0.1/0.2% pass rates across 3,640 cells each) — still doesn't clear admission, risk confirmed still dormant, not resolved.** Fragile — any future `ic_engine` run could flip that by accident. `todo 230` resolved 2026-08-02 (steps 6-8 run regularly now), that's no longer a reason for low urgency — should close before/alongside any future recompute regardless. |

## P3 — Hygiene, docs, process (opportunistic)

| Todo | What |
|---|---|
| [338](pending/338-integration-db-rebuild-fixture-per-table-seed-pattern-repeating.md) | New 2026-08-20, from todo 293's `/simplify` altitude pass. `tests/integration/conftest.py`'s per-table data-seed pattern (schema-only baseline drops a pre-cutoff reference table's DML, blocking the whole rebuild fixture until seeded) has now repeated twice (`instruments`, then `tag_vocabulary`). Not fixed generically yet -- two occurrences is defensible one-off under YAGNI -- but nothing watches for a third. Tripwire only: if a third table hits this, generalize instead of filing a fourth narrow todo. |
| [298](pending/298-backfill-connection-drop-silent-failure-and-completeness-audit.md) | New 2026-08-11, follow-up from todo 296. **Downgraded P0→P3 same session**: original filing claimed the backfill's connection-drop path was a silent failure — wrong, re-reading the code confirmed it already prints exact symbol/tf errors, exits nonzero, and emits `job_completed_total{status="partial"}`. Root-cause half (checkpoint I/O contention) already fixed live this session (`max_wal_size` 1GB→4GB via `ALTER SYSTEM`+reload). What's left is tooling polish: `backfill_retry_loop.sh` doesn't generalize to arbitrary `--client-id`/`--symbols` (hardcoded for the original 80-symbol universe), and no automated end-of-run completeness summary beyond the exit code (the `n_tf=5` SQL exists, just isn't wired in). |
| [056](pending/056-phase146-147-v2x-retirement-stale.md) | ROADMAP Phase 147/148 text rewritten 2026-07-19 (operator call resolved: archive not delete, decouple from proof gates). Remaining scope: the actual decommission-in-fact execution (git mv v2.x code to archive/, disable dead systemd units, rename-not-drop the frozen v2.x tables) — real multi-file operation, do with a clean git state. |
| [225](pending/225-multi-vector-systematic-regime-join-hybrid-sensitivity-symbols.md) | Downgraded P2→P3 2026-08-01 per its own pilot finding: read-only pilot on 5 hybrid symbols (`OIH`/`XLE`/`XOP`/`AMLP`/`GDX`) came back negative — the one BH-FDR survivor (`GDX momentum_z_fast`) failed cross-timeframe replication, flat null. Real information, not wasted effort; don't build the Fix steps until a better-motivated candidate surfaces or the universe scales. Full methodology in the todo file's "Pilot result" section. |
| [115](pending/115-days-to-month-end-exact-redundancy.md) | `days_to_month_end` is an exact affine complement of `month_position` (Pearson correlation -1) — perfectly collinear, remove one. |
| [244](pending/244-ctf-vwap-align-regime-align-never-computed-live.md) | New 2026-08-03, found via code review of todo 241's fix. `ctf_vwap_align`/`ctf_regime_align` (siblings of `ctf_momentum`, same batch `_build_ctf_series()`) are never computed live -- sit at the FeatureCache dataclass default (0.0) forever. Zero current blast radius: both were independently tested and rejected (todo 189) -- `ctf_vwap_align` dies on turnover cost, `ctf_regime_align` never clears its own CI. Not worth fixing speculatively for two already-dead features. |
| [258](pending/258-v3-cross-asset-kafka-route-dead-code.md) | New 2026-08-05, filed closing Phase 151 Plan 04 Task 4. `CacheManager.update_cross_asset()`/`topic_cross_asset` (fed by the dead `cross_asset_analyzer.py`, unit `inactive`) is dead v2.x-only code that shares a confusingly similar name with the LIVE, unrelated `FeatureCache.update_cross_asset()` -- same "two same-named methods, one dead" hazard shape as todo 158. The correctness half is already fixed independently (todo 221/222, landed 2026-07-31, before this todo was filed) -- what remains is a naming/dead-code hygiene question plus an open v2.x-revival question this todo can't answer unilaterally. **Superseded by Phase 151 Plan 09's grain-mismatch finding**: todo 221/222's fix was itself wrong-grain and has now been replaced (see todo 261) -- this todo's own "correctness half already fixed" framing is stale, though its actual scope (the dead Kafka route hygiene question) is unaffected. |
| [257](pending/257-feature-registry-worktree-branch-skew-blocks-ic-engine-runs.md) | New 2026-08-05, Phase 151 Plan 02. **Corrected 2026-08-21** -- originally named two gates; the `feature_registry` half no longer exists (Phase 170 `DROP`ped that table 2026-08-10). Surviving gate: concurrent GSD sessions share one physical DB — a worktree whose checked-out `FeatureVector` hasn't merged a sibling session's `concept_registry` schema changes fails `ic_engine.py`'s row-count parity gate. Not a code bug, an expected consequence of concurrent sessions; sequence corpus-wide `ic_engine.py` runs behind any in-flight schema-changing session's merge to `main`. |
| [273](pending/273-ctf-bisect-join-duplicated-between-feature-factory-and-recompute-script.md) | New 2026-08-06, found via `/simplify`'s altitude-angle review of todo 243's batching fix. `FeatureFactory.compute_batch`'s inline CTF bisect-join lookup is duplicated a second time in `ops_ctf_columns_recompute_15m.py` (the script's own comment admits it). Pure, low-risk extraction candidate, but touches `compute_batch`'s hot production path — deferred, not a drive-by fix. |
| [263](pending/263-feature-cache-update-cross-asset-dead-code-post-151-09.md) | New 2026-08-05, found in Phase 151's post-execution /simplify pass. `FeatureCache.update_cross_asset()`/`CrossAssetState` are now dead code in production (Plan 09 replaced their only live caller with `build_cross_asset_series()`), but carry ~9 dedicated tests documenting a real historical design decision (todo 222) — needs an explicit keep-or-delete call, not a unilateral cleanup-pass deletion. Zero effect on the batch/corpus recompute path either way. |
| [264](pending/264-equity-beta-z-rate-beta-z-never-wired-on-live-path.md) | New 2026-08-05, /simplify + code review WR-03. `equity_beta_z`/`rate_beta_z` allocated on `FeatureCache` but never computed live (batch/corpus path unaffected). **Partial fix landed 2026-08-05 (WR-03)**: live default changed from a fabricated `0.0` to `None`, honoring `FeatureVector`'s "None means not measured" contract — the actual live wiring (rolling per-symbol OLS beta) remains unbuilt. |
| [265](pending/265-guard-counted-observability-gap-on-live-path.md) | New 2026-08-05, code review WR-04. `_guard_counted()`'s "observable tripwire" for the 10 Theory-Motivated Interaction compounds only reports on the batch path (`_report_guard_counted_substitutions()` called solely from `compute_batch()`) — a live-path substitution silently accumulates in a counter nobody reads. Low likelihood (float64 product of two z-scores essentially can't overflow) and live ingestion is currently stopped, so no current blast radius. |
| [267](pending/267-feature-edge-by-regime-view-duplicates-lifecycle-hook-filter.md) | New 2026-08-05, `/simplify`'s altitude review of todo 251's edge-summary views. `feature_edge_by_regime`'s WHERE clause is a second, independently-maintained copy of `_apply_feature_transitions`' live promotion/demotion filter — no drift tracking if the hook's query changes. Also folds in 2 operational follow-ups from the efficiency review (re-run `ANALYZE`/`EXPLAIN ANALYZE` on both views once the corpus recompute lands with real data — verified against an empty table today). |
| [275](pending/275-v3-north-star-precedentengine-mechanics-predate-d4-rescope.md) | New 2026-08-06, found while doing the AnalogEngine→PrecedentEngine naming correction during a Phase 145 discuss-phase session. `docs/foundation/v3-north-star.md`'s PrecedentEngine mechanics (Score Object, independent-annotator framing, `signal_events` target) predate the D4 rescope that corrected exactly this framing elsewhere (glossary, `intel-precedent-engine.md`). Naming fixed inline + flagged; the mechanics reconciliation itself is real design work, not done here. No live consumer reads this doc's mechanics section today. |
| [284](pending/284-gsd-review-agy-stdin-invocation-broken.md) | New 2026-08-09, found running `/gsd-review 172 --agy`. `~/.claude/get-shit-done/workflows/review.md`'s documented `agy -p -` (stdin) invocation for Antigravity silently produces an empty/garbage review against the installed `agy` CLI — `-p -` doesn't read stdin, and the failure looks like a real chat response so the skill's existing empty-output check doesn't catch it. GSD tooling, not IndicAgent code. |
| [299](pending/299-reset-pipeline-data-ts-single-letter-helper.md) | New 2026-08-11, found by two `/simplify` altitude-agent passes on todo 297's fix (repo-wide greps to confirm 297's scope was correctly bounded). Two same-shape `_ts()` violations outside `src/api/`, not caught by naming-system.md's original authoring pass: `infrastructure_reset_pipeline_data.py:286` and `tests/unit/intelligence/test_smc_amd_cycle.py:168`. Same fix shape as 297. |
| [321](pending/321-feature-factory-config-test-fixture-consolidation.md) | New 2026-08-15, found by `/simplify`'s altitude review of todo 320 (Velocity Primitives Extension). No shared `FeatureFactoryConfig` test builder exists — 15+ files hand-type the full ~95-kwarg literal independently, so every new config field (this is at least the 6th time) requires the same mechanical edit replayed across all of them. Fails loudly (missing-kwarg `TypeError`) if forgotten, not silently — not urgent, but worth doing before the next field-adding phase. |
| [322](pending/322-ucr-invariant1-wording-genesis-seed-carveout.md) | New 2026-08-15, found by `/review` (code-review) during todo 320's cleanup. CLAUDE.md's UCR Invariant 1 ("only `ConceptRegistryService` flips `status`") doesn't acknowledge the established, repeated (5 migrations: 288/289/290/291/316) practice of genesis-seeding new atomic primitives as `status='active'` directly via raw migration SQL. Doc-wording fix only, no code/behavior change — the practice is already consistent, the invariant's stated wording just lags it. |
| [324](pending/324-gradient-vocabulary-naming-check-unenforced.md) | New 2026-08-15, found via user Q&A tracing fast/mid/slow naming against APR/ITR/CVR/UCR. naming-system.md §7's gradient-scale-vocabulary table (widely used across Feature Factory primitives) has zero CI/pre-commit enforcement - only Check 3 (Ring 0 boundary) of the doc's own 5 proposed checks is actually wired into `ci.yml`. **Revised twice 2026-08-15**: settled on a CVR `gradient_scale` namespace under the new D-07 admission criterion (todo 326's grep found concrete self-drift among Python-only CVR consumers, justifying the criterion) rather than a standalone module. Needs `VocabularyDriftAuditor`'s `has_live_source` distinction designed first. **330 (its sequencing blocker) CLOSED 2026-08-20** (row corrected 2026-08-21 -- was still linking `pending/330-...`, a broken path since 330 moved to `completed/`) -- `src/core/timeframe_vocabulary.py` → `src/core/vocabulary_access.py`, `codes(namespace, default)` primitive live. The sync-context read module this todo would have duplicated already exists; unblocked, no longer waiting on 330. |
| [336](pending/336-unused-index-cross-chunk-verification.md) | New 2026-08-20, found via a `/supabase:supabase-postgres-best-practices` read-only DB audit run alongside the in-flight `ic_engine` corpus pipeline run. Several indexes (`idx_market_data_ohlcv_price_sanity_unaudited` ~500MB, `feature_ic_scores_history_cell_idx` 808MB, others) showed `idx_scan=0` on their largest sampled chunk -- but that's per-chunk TimescaleDB stats, not aggregated per logical index, so it's not conclusive evidence of dead weight. Needs cross-chunk aggregation + code grep before any drop is considered. DB health otherwise clean (connections, seq-scan ratios, bloat, compression all fine) -- this is opportunistic cleanup, not a live problem. |
| [328](pending/328-timeframe-dead-code-found-during-327-investigation.md) | **Missing from this file entirely until 2026-08-21** (this session's drift audit). New 2026-08-15, split out of todo 327's timeframe-CVR consolidation work -- 4 of the 9 originally-listed `timeframe`-tuple call sites turned out to be dead code, not live scatter needing consolidation: a whole orphaned v2.x file (`feature_pipeline_executor.py`, misidentified as live due to a name collision with the genuinely-live `feature_vector_pipeline.py`), two zero-importer module constants (`bar_history.py::_STANDARD_TFS`, `service_utils.py::CROSS_ASSET_VALID_TFS`), and a shadowed-by-package bare file (`src/intelligence/utils.py`, unreachable since Python's `PathFinder` resolves the same-named `utils/` package first). Standard dead-code removal, zero runtime impact, batch with a future `/simplify` pass rather than a dedicated session. |

---

(Todo 005's P2→P1 tier change, flagged here 2026-08-03 as "not applied, your call," was applied
2026-08-07 -- see the P1 table above. No longer a candidate.)

(Todo 026's P4a/P4b: not a tier-change candidate anymore, retired out to
[248](pending/248-hmm-full-history-fit-regime-label-instability-gate4-pilot.md) in the P1 table
above -- 026 itself stays in `deferred/` as the historical audit record.)

(Todo 218 resolved 2026-08-03 -- root-caused via direct peer comparison against SHY/IEF,
Hypothesis 1 confirmed, deliberately not fixed -- see `completed/218-...md`. No longer a
candidate; closed.)

(Todo 297 resolved 2026-08-11 -- signals.py's single-letter coercion helpers renamed, see
`completed/297-...md`. No longer a candidate; closed. Surfaced
[299](pending/299-reset-pipeline-data-ts-single-letter-helper.md), a same-shape violation
outside the original scope.)

(Todo 319 resolved 2026-08-15, same session it was filed -- Loki's Grafana datasource uid
renamed from auto-generated hex to `loki` via delete+reprovision, matching `uid: prometheus`/
`uid: tempo`. See `completed/319-...md`. No longer a candidate; closed.)

(Todo 080 stays out of the tier tables on purpose -- it's a deliberate redirect stub, not live
work: content moved 2026-08-07 to `docs/research/measurement-adaptive-combiner-weights.md`,
the file kept in `pending/` only as a pointer. Confirmed 2026-08-11 during a drift audit that
it's correctly excluded, not accidentally missing.)

**Not in this list:** anything in `deferred/` (phase-gated or corpus-rerun-batched) or
`completed/` (done). Check those folders directly for that work.

**Drift audit, 2026-08-11:** diffed `ls pending/` against every `[N](pending/...)` link in this
file -- 9 todos had no entry (080, 255, 259, 272, 274, 285, 286, 287, 296). 080 confirmed a
deliberate redirect stub (see above, no entry needed). The other 8 are now tiered above. Two had
stale content beyond just the missing entry, both corrected in the todo files themselves: 259
("holding until client-id 41" was ~2 client-ID generations out of date; actual state is 115/135
done, client-48 running the rest) and 285 ("blocked on Phase 172 completing" -- Phase 172 has
been complete since 2026-08-09, this todo just never got the unblock applied). No stale
PRIORITIES.md entries pointing at deleted/moved files were found in the reverse direction.

**Drift audit, 2026-08-13:** re-ran the same diff. Only one new gap: [302](pending/302-ibkr-pre-listing-void-query-cancelled-not-fast-skipped.md)
had no entry (now added to P2 above). Also corrected 287's row -- it assumed the in-flight
2026-08-12 corpus pipeline would reach step 7 and pick up its fix automatically; that run FAILED
at step 2 (768GB disk-full incident, see `project_disk_full_incident_2026_08_13` memory) and
never got there. No other stale entries found.

**Cleanup + drift audit, 2026-08-21:** re-ran the same `ls pending/` vs. `[N](pending/...)` link
diff (105 pending todos, one gap: 334, now added to P2) plus a reverse pass checking every
strikethrough-CLOSED row against `completed/` (all 23 verified present there, none lingering in
`pending/`) -- stripped all of them from the P0/P1/P2 tables, restoring this file's own stated
"Not in this list: completed" scope after it drifted back toward inline-CLOSED-narrative the
same way the 2026-08-03 structure-cleanup pass had already fixed once. Also caught and fixed:
a stale preamble line still citing todo 218 as open 18 days after it closed, and 335's much
more consequential gap -- filed 2026-08-19 self-tagged `priority: P0` but never added to this
file at all, discovered while auditing why the file and `.planning/STATE.md` disagreed about
what's actually blocking the in-flight corpus run. Investigating 335 surfaced a live
operational failure, not just a doc gap: the automated watcher queued 2026-08-20 to chain the
corrected recompute onto the current run's completion was found dead (process gone, log never
written) and has been relaunched more robustly -- see 335's row in the P0 table and the todo
file itself. **Net effect on P0: 318/314/323 all closed and stripped this pass (real backlog
progress, matching this file's "reprioritize as P0 clears" instruction), but 335 replaces them
as the sharpest open item -- it's actively corrupting the regime labels a multi-day-running
corpus job is producing right now, not a latent gap.** No other stale entries found; P1/P2/P3
tier placements otherwise left as previously judged (re-tiering is deliberately not
auto-applied by this pass, per this file's own "judgment call for you" rule).
