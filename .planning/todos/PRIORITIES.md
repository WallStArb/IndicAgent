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

288's own row moved to `completed/` 2026-08-28 — closed on live verification: `feature_vectors` back to 85/85 chunks compressed (compression policy present and scheduled, auto-restored after the Phase 172 relabel), and the systemic half (future batch-UPDATE relabels vs. compressed chunks) addressed by todo 306's `compressed_hypertable_write_session` bracket + CI guard. Both option-branches of its "decide and execute" mooted.

Todo 270's row moved out of this table 2026-08-21 -- promoted to **Phase 173 (Broadcast Feature
Significance Correction)** in ROADMAP.md, per this file's own stated scope ("Phases... are a
separate execution track and do not appear here"). Context captured
(`.planning/milestones/v3.1-phases/173-.../173-CONTEXT.md`): all 23 broadcast features move together, a new
lightweight cell reuses `_subsample_and_rank` per-`(regime_group, tf, regime_label)` against an
equal-weighted aggregate return, same `feature_ic_scores` table/FDR family. Ready for
`/gsd-plan-phase 173`. Todo 270's own file kept in `pending/` as the historical scope record --
not re-closed here, just no longer a P0 backlog item to loop on. **Closed 2026-08-28: Phase 173
shipped complete** (2026-08-25/26; planned via `/gsd-plan-phase`, two independent review rounds,
live-smoke-tested against production, post-implementation codex+agy re-review clean, `/simplify`
done). 270's file now in `completed/` with the full closure note. Its citation caveat (no
broadcast-feature significance claim is Phase-173-corrected until the in-flight `--from-step 4`
recompute lands) is tracked in `.planning/STATE.md`, not as an open todo.

**354 CLOSED 2026-08-26, row removed.** Implemented substantially as proposed (day-decimation
via a new `_compute_one_symbol_broadcast_cell`, mirroring the already-shipped cross-sectional
`_compute_one_broadcast_cell`), plus three real design corrections found during implementation
and independent review, all fixed and re-verified against live production data before closing:
(1) 1h's `slow`/`extended` scales need a multi-day `day_stride` (day-decimation alone
insufficient -- new APR keys, migration 325); (2) `embargo_bars`/`bootstrap_block_size` must be
converted to day-array units, not reused raw from the per-bar sibling's convention (would have
over-embargoed/under-sized bootstrap blocks by ~`day_stride`x, silently starving folds and
understating standard errors); (3) `1d` correctly excluded entirely (no duplication to fix
there, and the fix's own sentinel would be actively wrong for `1d`'s own multi-day scales).
**Scope narrowed from the original proposal**, the session's most consequential finding: live DB
check caught that concept_registry's full `broadcast=true` set (~38 features) includes ~35
genuinely intraday-varying features (`hour_of_day_cos` confirmed 78 distinct values/day) that
are NOT day-constant -- using the full set would have silently dropped real signal or crashed
the new invariance guard. Fixed with a narrow, explicit, empirically-verified 3-name allowlist
(`_TEMPORAL_BROADCAST_FEATURE_NAMES`); widening it needs its own empirical classifier, filed as
[360](pending/360-broadcast-day-constant-empirical-classifier.md). 18 new unit tests + live
end-to-end smoke tests against real AAPL/5m and SPY/1h/1d data at every stage. Full evidence in
`completed/354-...md`.

**005 CLOSED 2026-08-27, row removed.** Fixed at the source: `cross_sectional_regime_model.py`'s
`_assign_labels` now applies a causal min-hold-bars hysteresis smoother (ports
`regime_writer.py`'s existing `_smooth_states` pattern to string labels) to each tier
dimension before combining into `regime_label`. New APR key
`alpha.regime.cross_sectional.min_hold_bars=3` (migration 326). Verified via a real write
through the production entry point + before/after label-churn measurement against the live
DB, not just synthetic tests: bar-to-bar churn dropped from 5.6%/18.3%/64%/84%
(equity/rates/fx/commodity) to a uniform 5.4%-7.4% band post-fix. **Materially more severe
finding than the original filing suspected:** commodity/fx were flipping regime label on the
majority of consecutive bars pre-fix -- near-random, not "occasional" noise. 17 new unit
tests, full `tests/unit/` suite green. Fixed *before* launching the pending post-Phase-173
corpus recompute (same blast-radius class as an `HMM_RANDOM_STATE` change) to avoid a second
multi-day recompute cycle. Full evidence in `completed/005-...md`.

| Todo | Gap |
|---|---|
**335 CLOSED 2026-08-31, row removed.** Steps 3-4's recompute (`--from-step 4`) landed
2026-08-31 12:16 UTC. Verified live: `market_regimes` commodity group now shows all 4 tiers
(`up_secondary`/`down_primary` -- the two states the bug made unreachable -- both populated),
fx group shows both risk states (`risk_off` now populated for both dollar-strength tiers),
confirmed propagated through to `feature_ic_scores`. See todo file's closure section.

**306 CLOSED 2026-08-31, row removed.** Corpus-recovery side resolved earlier this session
(regime population, `forward_returns` OOS-capping, co-dependents 285/287/335 all verified).
Live IBKR ingestion also now resolved -- the 2026-08-13 "stuck in 2FA loop" diagnosis was
wrong; real cause was `libgtk-3-0` missing from the `ib-gateway` image, fixed live and
verified connected. Durability follow-up filed as todo 363 (fix survives `docker restart`
but not a container recreation). See todo file's closure section.

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
**287 CLOSED 2026-08-31, row removed.** `ensemble_trainer` re-ran under the fix commit
(`9469b0a50`) 2026-08-30 -- verified live: zero leaked columns appear as `feature_name` in
`ensemble_weights`, zero NULL-imputation gap possible now the columns are excluded outright.
See todo file's closure section.

**285 CLOSED 2026-08-31, row removed.** All 5 verification steps run against the completed
post-Phase-173 recompute: no retired trend labels anywhere in `feature_ic_scores`, every
per-symbol volatility label is a registered CVR code, VINTAGE DISJOINT still PASS at full
scale, per-cell coverage checked (45/262 evidence-file cells produced no IC rows -- 44
explained by the documented bar-floor limitation, 1 new finding filed as todo 362). See todo
file's closure section.
| [240](pending/240-nonlinear-interaction-combiner-baseline-is-single-feature-not-the-linear-ensemble.md) | From a rigor review of the Edge Source Thesis doc. nonlinear_interaction_combiner's pre-registered falsification bar says the tree must beat "the existing linear ensemble"; every run actually compared it to `ctf_momentum` alone. **Code landed + committed 2026-08-03** (`816032e2`): a fold-local linear-ensemble arm (`fit_linear_ensemble_weights`/`score_linear_ensemble`, reusing `ensemble_trainer.py`'s own weighting primitives) plus a paired-bootstrap PRIMARY VERDICT (tree vs linear), `ctf_momentum` kept as secondary. Independent review caught and fixed 2 blocking issues (features weren't z-scored before weighting; memory footprint too close to this module's prior OOM history) -- both fixed in the same commit. **Re-run at 1h/15m/5m gated on todo 243's corpus-recompute decision** (todo 245, all 3 tfs measured and CLOSED 2026-08-04 -- the training matrix confound is now quantified, not just flagged; the training matrix still includes lookahead-contaminated `ctf_momentum` until 243's corpus recompute happens) -- **1d re-run is safe and unblocked right now.** Gates todo 238. |
| [239](pending/239-nonlinear-interaction-combiner-embargo-passed-in-pooled-panel-rows-not-bars.md) | Same review. `_nonlinear_interaction_combiner_shared.py` passed `embargo_bars` into `build_walk_forward_folds(n_valid=len(X))` where `X` is the **pooled** ~80-rows-per-bar panel, so the intended 1-day embargo was 24/96/5 *rows* ≈ 0.3/1.2/0.06 bars at 1h/15m/1d, and fold boundaries split inside a single `bar_ts`. Bounded blast radius (~800 rows of ~2-8.5M, does NOT explain the 0.18-0.25 IC) but cited in the research doc as a rigor credential. **Code landed + committed 2026-08-03** (`816032e2`, same commit as 240): new `_pooled_panel_folds()` builds folds over the distinct `bar_ts` index and maps back to row slices; `build_walk_forward_folds` itself untouched. **Re-run gating: same as 240 -- 1d safe now, 1h/15m/5m wait on todo 243's corpus recompute.** |
| [238](pending/238-nonlinear-interaction-combiner-ranked-cross-sectional-relative-value-pre-registration.md) | New 2026-08-03, from a user-directed rigor review of Edge Source Thesis next steps. Both cross_sectional_relative_value (proven construction) and nonlinear_interaction_combiner (proven 3-5x-stronger signal) are independently validated at 15m; nobody has tested cross_sectional_relative_value ranked by nonlinear_interaction_combiner's tree score instead of `ctf_momentum` — highest-expected-value untested combination on the doc. Pre-registered falsification design (shuffled null, cost-hurdle, turnover, Gate-2-equivalent factor-attribution, breadth-preservation) written down before running, per this project's own pre-registration discipline. **Gated on cross_sectional_relative_value's own Gate 1/Gate 2 re-verification landing first** (todo 243 -- 253's own prerequisite fix already closed 2026-08-04) -- ranking by a tree score doesn't matter if the underlying construction's proof itself is unverified; testing this now would build on the same unresolved foundation. |
| [248](pending/248-hmm-full-history-fit-regime-label-instability-gate4-pilot.md) | New 2026-08-03, retired out of `deferred/026`. Instability confirmed at 3 symbol/tfs (24.9-56.8% label agreement depending on tf). **Wired 2026-08-05**: `_compute_symbol_tf_walk_forward` (full production-parity path -- per-segment convergence retry, degenerate-segment gating, all `feature_vectors` columns, not just bare labels) added to `regime_writer.py`, dispatched via APR flag `alpha.hmm.walk_forward.enabled` (migration 292, **seeded `false`** -- landing the code changes zero existing regime label). Per-tf `refit_every_bars`/`initial_warmup_bars` seeded for all 4 tfs (1h/15m pilot-measured, 5m scaled-not-piloted, 1d unpiloted estimate -- see migration 292's per-key provenance). **Remaining work is now purely a deployment decision, not implementation**: flip the flag, run `regime_writer.py --refit`, then a downstream `ic_engine` recompute (same blast-radius class as an `HMM_RANDOM_STATE` change) -- still queued behind CTF/Phase 167 per the 2026-08-04 sequencing decision, unaffected by this session's wiring work. |
| [065](pending/065-emission-layer-calibration-proposals.md) | EM-CAL threshold calibration — both prerequisite gates (rebuild, EIC-04) cleared 2026-07-09. **Caution added 2026-07-30**: that clearance predates todo 146/208's grid rework (per-tf lookahead grid; 208's session-gate premise is now fixed, but the grid's actual values are still open, see 208's row below). **Unblocked 2026-08-03**: the corpus pass this was waiting on completed 2026-08-02 21:19 UTC (see preamble). Ready to calibrate against the corrected corpus now — real design/execution work, not mechanical. |
| [079](pending/079-anytime-valid-e-values-corpus-reruns.md) | Anytime-valid inference pilot (one tf) — new statistical primitive, deliberately staged small |
| [054](pending/054-shadow-alpha-events-monitoring.md) | Shadow alpha_events monitoring — prevents delayed detection of feature decay/threshold bugs |
| [167](pending/167-equity-cross-sectional-vs-symbol-hmm-never-falsifier-tested.md) | **Plan changed 2026-07-29 — no longer a standalone equity-scoped relaunch,** folded into 176's queued sequence (market-data-gap catchup → 176's `--refresh` → one full-corpus `ic_engine` pass). **176's `--refresh` step confirmed run 2026-07-30**, but the sequence's final step (a full-corpus equity+rates `ic_engine` pass) status is unclear post-2026-08-02 (see preamble) — that pass is what would actually close this todo. |
| [261](pending/261-deploy-grain-corrected-cross-asset-mechanism-once-ingestion-resumes.md) | New 2026-08-05, closing Phase 151 Plan 09. Code+tests complete and merged: replaced todo 221/222's per-timeframe `CrossAssetState` live mechanism (a confirmed grain mismatch — computed from THIS TIMEFRAME's own intraday bars, not the canonical daily-broadcast definition every IC/gate measurement was built against) with a daily-grain mechanism sharing the batch path's own `build_cross_asset_series()`. Deployment (live daemon restart + Task 3's verification) deliberately NOT done in that plan's execution — ingestion is still paused (`max(bar_ts)` 8 days stale, restarting proves nothing right now) and this is a full mechanism replacement an unattended session shouldn't push live without operator sign-off. |
| [369](pending/369-bar-replay-systemd-execstart-references-renamed-module.md) | New 2026-09-04, side finding from a `docs/reference/` refresh pass. `indicagent-bar-replay.service`'s `ExecStart` calls a module (`services.bar_replay_provider_agent`) that doesn't exist — real file is `services/bar_replay_provider.py`, a stale `_agent` rename this project's earlier suffix-retirement sweep missed. Currently latent (`disabled`/`inactive`), one-line fix, fully unblocked. |
| [370](pending/370-weekly-db-maintenance-job-failing-recompress-signal-ledger-job-silent-noop.md) | New 2026-09-04, side finding from the same pass. Two live scheduled TimescaleDB jobs are broken against the v3.0 schema: `weekly_db_maintenance` (job 1020) has failed all 1243 runs — first statement targets a materialized view that no longer exists; `recompress_signal_ledger` (job 1021) reports Success every run (96/96) but silently no-ops — `signal_ledger` is a view now, not a hypertable, so its chunk-selection query never matches. Neither threatens live data today; needs a retire-vs-rewrite decision, not a mechanical fix. |

## P2 — Real value, not urgent

**366 (live ingestion consumer chain never restarted after the todo 306/363 gateway fix)**
-- new 2026-09-01, found starting `statistical_factor_residual` Stage 3; `market_data_ohlcv`
1m frozen at 2026-08-12 for most of the universe, real gap, corrects the "RESOLVED" framing
in `project_ibkr_live_ingestion_stalled_2fa` memory. **Filed P2, not P0** -- user direction
2026-09-01: decades of history already available, no proven edge yet to protect, so
live-ingestion freshness doesn't gate research value. A backfill to bring OHLCV current is
optional/later; fixing the consumer-restart durably (and todo 363's Dockerfile fix) can wait
until it actually matters. See [366](pending/366-live-ingestion-consumer-services-never-restarted-after-gateway-fix.md).

**2026-08-26 drift catch:** [353](pending/353-earnings-season-calendar-primitive-candidate.md)
(earnings-season calendar primitive, real proxy evidence, p=1.2e-17), 356 (cross-sectional
fetch chunk query pathologically slow on the largest cell, found during Phase 173's smoke test
-- CLOSED 2026-08-26, see below), [357](pending/357-phase173-triple-duplicated-per-scale-cell-block.md) (3-way duplicated
per-scale block in `ic_engine.py`), [358](pending/358-phase173-broadcast-cell-bar-ts-array-efficiency.md)
(`bar_ts_arr` as `dtype=object` + a redundant pass, same OOM-history function) were all filed
but missing from this file — added now. [359](pending/359-phase173-altitude-design-notes.md)
(3 architecture notes, already reviewed/accepted, no action needed) filed P3, see below.

**356 CLOSED 2026-08-26, row removed.** Root-caused via `EXPLAIN (ANALYZE, BUFFERS)` against
the real query shape (298 columns, not the stale "152 features" comment elsewhere in the file):
`bar_ts = ANY(<5000 values>)` against the compressed hypertable expands chunk exclusion into a
literal per-batch `OR`-chain of `_ts_meta_min`/`_ts_meta_max` checks, `O(batches x
len(ts_chunk))`. Fix: redundant `BETWEEN ts_min AND ts_max` bound ahead of the existing `ANY()`,
using `ts_chunk[0]`/`ts_chunk[-1]` (already correct since `ts_chunk` is a contiguous slice of an
`ORDER BY ts` result). Measured, isolated, single-variable on real data: 10.2s->0.3s (~32x) and
1.5s->0.5s (~2.9x) on two different real chunks; correctness verified via matching row-count +
order-sensitive checksum on real data (238,121 rows, identical both ways), not assumed. Verified
the fix generalizes across the whole cell (all 108 real chunks span 19-250 days, none spans
years) before trusting it. Independent Codex review found no blocking issues; one valid point
(source-inspection test alone doesn't prove the ts_min/ts_max invariant) addressed by adding a
second test proving the slicing invariant directly against synthetic sequences. Full `tests/unit/`
green, ruff/black clean. Full evidence in `completed/356-...md`. **Not independently re-verified:**
whether this alone resolves the reported 95+-minute-and-not-finished full-cell behavior, or
whether other large 5m cells hit the same pathology -- watch during the next full corpus run
rather than assuming fully closed.

**2026-08-21 backlog audit:** [281](pending/281-systematic-dominance-and-volume-price-confirmation-as-feature-primitives.md)
re-tiered P3→P2 -- misfiled under P3 with no documented reason (unlike 280/225, which both carry
an explicit re-tier rationale), against its own P2 frontmatter. Content is real, scoped
feature-primitive work with a concrete next step (add columns, then a Phase-144-D-05-shaped
separation test), not hygiene.

| Todo | What |
|---|---|
| [281](pending/281-systematic-dominance-and-volume-price-confirmation-as-feature-primitives.md) | New 2026-08-08, out of Phase 171's candidate-regime-axes test. Two real, null-arm-validated signals (idiosyncratic-vs-market co-movement, volume-price confirmation) should ship as plain `feature_vectors` columns, not HMM regime labels — identifiability for both is too narrow/fragile to trust as a discrete regime. |
| [340](pending/340-ihf-5m-feature-compute-zero-row-positive-input-error.md) | New 2026-08-21, split out of todos 259/296's closure. `IHF`/`5m` has zero `feature_vectors` rows -- `"expected a positive input, got 0.0"` compute error, likely a `log()`/division call in `FeatureFactory.compute_batch` hitting a genuine zero (volume or price) on a specific bar for this thinly-traded sector ETF. Single symbol/tf, bounded blast radius, not investigated further yet. |
| [355](pending/355-context-features-writer-orphaned-after-phase-173.md) | New 2026-08-25, filed alongside 354 during Phase 173 Plan 02. `infrastructure_context_features_writer.py` still writes daily `flight_quality`/`yield_slope_z`/`vix_z` rows into `context_features`, but `ic_engine.py` (the table's only documented consumer) lost its last query against it in this same plan -- an unowned writer with no downstream reader. Nothing lost (`feature_vectors` carries equivalent per-bar values); decision needed is retire-writer-and-drop-table vs repoint-at-a-real-consumer, deliberately not made by Phase 173. |
| [360](pending/360-broadcast-day-constant-empirical-classifier.md) | New 2026-08-26, filed closing todo 354. `_TEMPORAL_BROADCAST_FEATURE_NAMES` (todo 354's day-decimation gate) is a small, hand-written, empirically-verified 3-name allowlist (`vix_z`/`yield_slope_z`/`flight_quality`), deliberately narrower than concept_registry's full `broadcast=true` set (~38 features) -- live DB verification caught that most of the other 35 (calendar/session encodings, `amd_phase`, cross-asset ratios) are NOT day-constant and would break the fix if included unfiltered. Real follow-up: an empirical within-day-variance classifier mirroring `ops_broadcast_feature_audit.py`'s existing cross-symbol-variance detector, replacing the hardcoded allowlist. Not urgent -- current scope is correct, just narrower than it eventually could be. |
| [353](pending/353-earnings-season-calendar-primitive-candidate.md) | New 2026-08-23. No `is_earnings_season` primitive exists in `feature_factory.py`. Cheap SQL-only proxy test (calendar-derived flag, no new feature built) against `forward_returns.return_fast` at 1d shows a real, broad effect: pooled mean return 4.3x higher in-season (p=1.2e-17, n=923,353), 81% of symbols (186/230) individually higher in-season, confirmed equity-specific. Validated candidate, not yet built as a real feature -- window definition corrected mid-session to days 14-42 post-quarter-end (not 0-42, which the proxy test used). |
| [357](pending/357-phase173-triple-duplicated-per-scale-cell-block.md) | New 2026-08-26, `/simplify`'s reuse+simplification review of Phase 173's diff (2 independent agents). `_compute_one_broadcast_cell` (`services/ic_engine.py` ~3273-3658) is a third near-identical copy of the ~140-line per-scale block (`_subsample_and_rank` → IC/CI/walk-forward → rolling metrics → row emission) already duplicated twice by `_compute_one_cross_sectional_cell`/`_compute_one_regime_cell`. Pre-existing duplication pattern, not a new problem -- extraction deferred because it would touch two already-shipped production functions on the significance-gate hot path, one with documented 2026-07-08 OOM history. |
| [358](pending/358-phase173-broadcast-cell-bar-ts-array-efficiency.md) | New 2026-08-26, `/simplify`'s efficiency review of Phase 173's diff. Same OOM-history function family: `bar_ts_arr` is built as `dtype=object` (Python `datetime` per element) instead of `datetime64[ns]`, costing ~500-600MB extra at the largest real cell (~9.4M rows) and forcing the core boundary-scan comparison into per-element Python instead of a vectorized kernel; plus a third redundant pass over `batch` solely to extract `bar_ts` that could be folded into an existing loop. Not fixed inline -- needs verifying the `datetime64[ns]` cast is safe against actual upstream row values first. |

**329 CLOSED 2026-08-21, row removed.** Migration 322 adds the `timeframe`/
`intraday_plus_hourly` CVR group; `vocabulary_access.group_codes()` (new) repoints both
`signal_auditor.py`/`feature_validation_analyzer.py` at it, replacing `assert_known_subset()`.
Full `tests/unit/` green (6 new tests), ruff/black clean. Full evidence + one documented
behavior-shape trade-off (silent fallback replaces hard-crash on a broken group) in
`completed/329-...md`.

**346 CLOSED 2026-08-21, row removed -- hypothesis was WRONG, gate not broken.**
The exact CI command (`mypy src/ --ignore-missing-imports | mypy-baseline filter`)
against the real, already-committed baseline shows `new: 0`. The original "72 new"
finding came from checking a single file instead of the whole tree -- mypy's own
`note:` context differs by invocation scope, not baseline staleness. Full
corrected finding in `completed/346-...md`.

**328 CLOSED 2026-08-21, row removed.** Executed all 4 confirmed-dead deletions
(re-verified live first), plus found and handled 2 scope gaps the original filing
missed (a dangling `__init__.py` re-export that would've broken the package import, a
second test file directly reading the deleted module's source). Deleting the dead file
cascaded into 12 new vulture findings in sibling files -- real evidence the broader
`src/intelligence/pipeline/` package has more dead code than this todo scoped to find,
whitelisted with a note pointing at todo 223 (the actual audit for that question)
rather than re-litigated here. Full `tests/unit/` green, vulture exit 0. Full evidence
in `completed/328-...md`.

**315 CLOSED 2026-08-21, row removed.** Trigger identified:
`setup_service_logging()`'s `RotatingFileHandler(maxBytes=10MB)` is a size-based rotation
completely independent of the daily `logrotate.timer` -- the ~7-15min cadence was just
`regime_writer.py`'s own log volume hitting that threshold, confirmed directly, not
inferred. Fix (not a workaround): `setup_service_logging()` now installs a `sys.excepthook`
routing uncaught exceptions through the same rotation-safe handler, closing the one real
gap (Python's default crash-traceback path bypasses `RotatingFileHandler` entirely). Lives
in shared Ring 0 code, so it automatically covers `ic_engine.py`/`regime_writer.py`/
`forward_return_writer.py` (all confirmed callers) with no per-service audit needed. Zero
risk to the live corpus run (source change, doesn't affect an already-loaded process). 6
new tests where zero existed before. Full evidence in `completed/315-...md`.

**313 CLOSED 2026-08-21, row removed.** Cross-referenced migration 312's full 303-column
list against every `feature_vectors` writer outside the 4 known `bulk_update_by_key` call
sites -- CLEAN, no follow-up fix needed. Every other writer found is structurally immune
to the col_types-drift bug class (direct-INSERT with no temp table, or NULL-only UPDATE),
not just currently correct. Full evidence in `completed/313-...md`.

**294 CLOSED 2026-08-21, row removed.** Fixed 8 genuine present-tense `feature_registry`
claims across 4 docs (verified against live migrations 283/284/311 and live code before
editing, not assumed), including one substantive fix beyond a table-name swap
(`intel-symbol-state-query-layer.md`'s "fixed DB check-constraint" premise no longer
holds -- `concept_registry.group_name` is unconstrained text). Deliberately left
`measurement-governance-monitor.md`'s ~15 occurrences and one dated numeric-snapshot
section alone, with reasons recorded inline, not silently skipped. Full detail in
`completed/294-...md`.

**342 CLOSED 2026-08-21, row removed.** Generalized `1d` slot generation to `futures_24_5`
(CME/CBOT/COMEX/NYMEX -- CFE deliberately excluded, raises rather than silently returning
empty)/`fx_24_5`/`crypto_24_7`, resolving the "no live data to test against" question the
filing flagged by testing the calendar/weekday-rule logic directly instead of storage
reproduction. New shared `_daily_slots()` helper, new `MarketCalendar.supports_exchange()`.
12 new tests, full `tests/unit/` green. Full detail in `completed/342-...md`.
| [341](pending/341-bil-etha-ibit-zero-regime-labels.md) | New 2026-08-21, found by `regime_coverage_auditor.py`'s first live production run (todo 169). `BIL`/`ETHA`/`IBIT` have 100% NULL `feature_vectors.regime` -- same failure shape as todo 168 (7 different symbols, closed). Plausibly related to `BIL`'s separate compute-underflow finding (todo 340's sibling note) via BIL's near-zero-volatility character; `ETHA`/`IBIT` may just be short-history crypto-trust ETFs below the HMM warmup requirement. Not investigated further yet. |
| [334](pending/334-has-gap-before-entry-never-set-dead-column.md) | New 2026-08-16, added to PRIORITIES.md 2026-08-21 (was missing entirely -- this session's drift audit). `forward_returns.has_gap_before_entry` had been dead since the table existed (permanently `false`, never written by `forward_return_writer.py`), making `ops_cost_hurdle_calibration.py`'s gap-contamination check structurally incapable of ever firing. **Write-path fix already landed and verified same session** (29/29 tests, synthetic positive-control cases confirmed correct) -- future rows get the real computed value. Remaining scope is narrower than the original finding: a retroactive backfill of the 103M existing rows, deliberately deferred (compressed hypertable, same blast-radius class as the 2026-08-13 disk-full incident) until planned with the performance-investigation SOP. |
| [343](pending/343-regime-writer-backfill-feature-factory-write-isolation-shared-helper.md) | New 2026-08-21, `/simplify`'s reuse-angle review of the full session's diff. `backfill_feature_factory.py`'s new per-cell write-isolation loop (todo 318) duplicates a shape `regime_writer.py` already established, with no shared helper in `_batch_utils.py` capturing it. Not extracted this session -- touches an unrelated, live, well-tested batch writer outside the reviewed diff. |
| [344](pending/344-bar-normalizer-slots-nyse-should-reuse-marketcalendar.md) | New 2026-08-21, `/simplify`'s simplification-angle review of todo 300's fix. `_slots_nyse` (intraday) still maintains its own separate NYSE calendar (`_NYSE_CAL`/raw `mcal.schedule()`), unlike the new `_slots_nyse_daily` which correctly reuses `MarketCalendar`. Also found: `MarketCalendar`'s pre-built range only covers 2005-2035 -- confirmed NOT a live issue (earliest `1d` row is 2006-03-22). Needs a new `MarketCalendar` accessor (open/close times) before `_slots_nyse` can migrate -- real API-surface expansion, not a drive-by fix. |
| [345](pending/345-backfill-feature-factory-decompress-prep-serialized-before-compute.md) | New 2026-08-21, `/simplify`'s efficiency-angle review of todo 318's fix. `_write_session`'s decompress/GUC-prep phase (documented as expensive) is fully serialized in front of worker compute instead of overlapping with it; `pool.map()`'s submission-order iteration also head-of-line-blocks fast writes behind slow earlier symbols. Fix requires restructuring `pool.map()` to explicit `submit()`+`as_completed()`, which would break every existing test's `mock_pool.map.return_value` mocking -- deferred as a scoped follow-up rather than a risky mid-`/simplify` rewrite. |
| [337](pending/337-concept-gate-counter-advance-no-cas-lock-and-per-run-write-volume.md) | **Re-tiered P1→P2, 2026-08-20**: finding 3 (optimistic lock) fixed same day, only finding 4 remains -- `advance_active_counters_sync` now writes+logs once per active concept every corpus run (~200 sequential single-row commits) instead of just `shadow_only` concepts. Real overhead in the direction of CLAUDE.md's batched-write guidance, but small in absolute terms against a multi-hour+ corpus run; its own filing text already said "not urgent." Fix, if pursued: collect `(feature_name, passed)` pairs across the loop, one batched UPDATE after. |
| [331](pending/331-vocabulary-drift-auditor-windowed-query-blind-spot.md) | New 2026-08-16, from todo 327's final whole-branch review - the root-cause explanation for why migration 233's missing `4h` code sat undetected for 3 years. `VocabularyDriftAuditor`'s source queries are all window-bounded (`infra.vocabulary_drift.window_days`, default 30); a code that's rare/sparse enough to fall outside any given window is structurally invisible to the auditor, indistinguishable from "no data at all." Applies to every namespace it checks, not just `timeframe`. Needs design, not obvious - see todo for options weighed. |
| [317](pending/317-backfill-status-migrate-to-anti-join-checkpoint-pattern.md) | New 2026-08-14, split out of todo 316's `/simplify` altitude review. `backfill_status.status='complete'` is the only side-table checkpoint of its kind left in `services/*.py` — every other batch writer (`alpha_frame_writer.py`'s documented "Pattern 4", `regime_writer.py`, and `ic_engine.py` which deleted a decoupled `.pkl` checkpoint outright for this same root cause) queries the target table directly instead. Todo 316's fix reconciles the desync after the fact; this is the deeper fix — eliminate the second source of truth. Not urgent: 316 already makes the current design self-detecting/self-healing. |
| [309](pending/309-vulture-baseline-cleanup-backlog.md) | New 2026-08-14, filed wiring vulture (dead-code detection) into CI for the first time — it had sat in `requirements.txt` unwired since before this session. CI now blocks any *new* dead code; the 1136 pre-existing findings were frozen into `tools/vulture_whitelist.py` rather than triaged by hand (real dead code is mixed in with known dataclass/Pydantic false positives). One freebie found + fixed inline: an `if False else` unreachable branch in `src/intelligence/ai/context.py`. |
| [339](pending/339-backfill-feature-factory-worker-rows-unbounded-memory-across-ipc.md) | New 2026-08-21, split out of todo 318 Bug 2's fix (`/simplify` + `/code-review` both converged on it). Making workers compute-only (CLAUDE.md invariant) means each now returns every computed row for a symbol across all 4 timeframes in one shot instead of streaming `insert_batch_size` chunks as it goes -- bounded to ~191K rows/symbol worst case (full-depth `--refresh`), same `update_rows`-over-IPC shape `regime_writer.py` already uses, just proportionally heavier per row. Not a correctness bug, deferred rather than expanding the fix's diff further; fix shape (APR-capped `n_workers` for refresh runs, or a deeper chunk-granularity IPC redesign) not yet decided. |
| [308](pending/308-compressed-hypertable-registry-should-be-live-cached-not-hardcoded.md) | New 2026-08-14, split out of todo 306/307's compressed-hypertable-write-session fix. `_KNOWN_COMPRESSED_HYPERTABLES` (`services/_batch_utils.py`) is a hardcoded set `bulk_update_by_key`'s hot-path guard checks -- the "missing entry" drift direction is silent and unprotected (guard just never fires), unlike the harmless "stale entry" direction. Deliberately deferred (bounded: only 2 tables affected today, both correctly protected) rather than bolted onto an already-large diff -- recommended fix mirrors ConfigService/VocabularyService's cache-at-init pattern. |
| [255](pending/255-counterfactual-tracker-evaluate-gate-no-d04-governance.md) | New 2026-08-04, added to PRIORITIES.md 2026-08-11 (was missing entirely, self-tagged P2 in its own frontmatter). Split out of todo 253 while wiring D-04 governance into `cross_sectional_spread_tracker.py` -- same gap, different phase, deliberately not fixed in that pass to avoid expanding its blast radius. |
| [274](pending/274-live-tradeable-vs-corpus-universe-flag.md) | New 2026-08-06, added to PRIORITIES.md 2026-08-11 (was missing entirely). `instruments` has no column distinguishing "eligible for live IBKR streaming" (80-subscription cap) from "part of the backfill/corpus measurement universe" (231 active) -- `get_active_contracts()` collapses both into one `is_active` boolean. Real design question, unblocked, no urgency while ingestion stays paused. |
| [272](pending/272-instrument-tag-peer-group-coverage-auditor.md) | New 2026-08-05 (renumbered from 271), added to PRIORITIES.md 2026-08-11 (was missing entirely, and this project's memory has been citing it under the stale "todo 271" number -- fixed). No automated audit for thin/missing `instrument_tags` peer-group cardinality -- every gap found so far (this todo, plus todos 280/283's specific instances) was found by a human asking "what about X?", not a query. Distinct from 280/283 (which are the specific data gaps already found) -- this is the general tooling to catch the next one automatically. |
| [286](pending/286-build-obs-matrix-nested-rolling-warmup-artifact-in-vol-of-vol.md) | New 2026-08-09, added to PRIORITIES.md 2026-08-11 (was missing entirely). Phase 172 cross-AI review (Antigravity, LOW severity, the one finding neither reviewer duplicated) -- `_build_obs_matrix`'s `valid_start` warmup calculation is correct for 4 of 5 observation columns but not for `vol_of_vol` (a rolling-std-of-a-rolling-std, needs `2x` the window, not `1x`). Minor HMM observation-matrix artifact, not a stratification-label-level bug. |
| [301](pending/301-bulk-insert-shared-primitive-vs-local-batching.md) | New 2026-08-11, filed by a `/simplify` pass on this session's `store_bars()` batching fix. Two independent review agents (reuse + altitude angles) converged on the same point: the fix diverges from `forward_return_writer.py`'s chunked-`executemany()` convention and an existing `ic_engine.py` comment arguing against manual VALUES batching -- comment fixed to note the divergence is deliberate (backed by a live 2x benchmark, not theory) rather than reconciled. Real follow-up: promote to a shared COPY-based `bulk_insert` primitive in `_batch_utils.py` (matching `bulk_update_by_key`'s precedent) and point all `market_data_ohlcv` writers at it, including the untouched sibling in `backfill_feature_factory.py:896`. |
| [292](pending/292-hmm-vol-churn-corpus-values-predate-wr01-fix.md) | New 2026-08-09, filed closing Phase 172's code-review gate. WR-01's churn-fabrication-across-segment-gap fix (commit `fdc14050`) landed after plan 172-05's corpus relabel already wrote 9.4M `hmm_vol_churn` rows with the pre-fix buggy logic -- confirmed legacy `hmm_churn` (27.9M rows) unaffected (`alpha.hmm.walk_forward.enabled=false`, that path never ran in production), but every `hmm_vol_churn` row needs a decide-or-recompute call. `regime_volatility` itself (the label `ic_engine.py` actually stratifies on) is completely unaffected. |
| [291](pending/291-regime-volatility-structural-duplication-followups.md) | New 2026-08-09, Phase 172's own `/simplify` gate (reuse/simplification/altitude angles, flagged independently by 2-3 reviewers each). Three functions in `regime_writer.py` (`_compute_symbol_tf_volatility_walk_forward`, `_fetch_obs_matrix_volatility`, `_write_regime_volatility_results`) duplicate their trend-path counterparts instead of sharing them via the `vocab` parameterization the inner layers already use. Deliberately deferred out of the phase's own cleanup pass -- touches HMM-fitting/DB-write hot paths, deserves dedicated test coverage rather than a drive-by refactor right after the corpus relabel landed. |
| [290](pending/290-regime-volatility-memory-and-query-efficiency-followups.md) | New 2026-08-09, Phase 172's own `/simplify` gate (efficiency angle). Real, measured costs: `_build_obs_matrix_volatility`'s rolling-std at window=250 can allocate up to ~9.5GB concurrent transient memory across a 12-worker pool (real OOM risk on a future full corpus `--refit`); per-cell `count(*)` verification queries cost ~10min aggregate per corpus run; `vocabulary_drift.py` scans `feature_vectors` twice per audit run instead of once. `ic_engine.py`'s startup-gate `count(*)`→`EXISTS` (measured 75x) already fixed inline during the phase's own cleanup pass; this todo is the remaining items. |
| [289](pending/289-regime-volatility-1d-sparse-coverage-refit-schedule-mismatch.md) | New 2026-08-09, found closing Phase 172 plan 172-05's corpus relabel. `regime_volatility`'s 1d-timeframe coverage is genuinely sparse (45% of cells skipped vs 8-11% at 5m/15m/1h) -- root-caused to `alpha.hmm.walk_forward.refit_every_bars.1d = 252` never being re-validated against the phase's new 250-bar `vol_window`/`vol_of_vol_window`. Shared key with the legacy `regime` family, needs its own investigation/gate. |
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
| [175](pending/175-structural-candidate-part2-smc-swing-fib-anchored-vwap.md) | Filed 2026-07-23 closing Phase 166: Part 2 of the structural stop/target candidate (SMC/swing/fib/anchored-VWAP, i.e. Phase 164/165's primitives) once those phases land — VP/SR (Part 1, Phase 163) is the only part Phase 166 actually scored. **Corrected 2026-08-21** -- the "gated on Phase 164/165 (not planned)" framing was stale; both are COMPLETE (2026-07-28, confirmed both in STATE.md's Phase Summary table and this todo's own frontmatter) -- 2 of 3 prerequisites cleared, only anchored-VWAP scoping remains unstarted. Not a reason to resume, though: this exists to serve Phase 148/166's per-symbol directional construction's stop/target logic, and todo 179 (CLOSED 2026-07-31) found that construction itself carries zero real edge at any regime/direction slice -- refining its execution layer is moot until some construction proves edge, per STATE.md's Tier 4 note and the project's own "prove edge before production infra" principle. The previous "same deprioritization as todo 176" citation was a mistake (176 is an unrelated VP/S-R backfill item, no deprioritization content) -- corrected to cite 179 directly. |
| [155](pending/155-price-sanity-status-historical-backfill.md) | New 2026-07-20, filed closing [149](../completed/149-bar-ingestion-price-sanity-guard.md): live pilot measured ~4.1 years to clear the 215M-row historical backlog at `BarAuditor`'s default batch size/cadence. Raising the batch size risks the daemon's 60s systemd watchdog and conflates one-time historical debt with the ongoing live-stream audit. Needs a dedicated one-time backfill tool, decoupled from `BarAuditor`'s cycle, reusing 149's classification primitives and Task 1's TimescaleDB compressed-chunk lessons. Also: oldest-first ordering means the guard protects nothing live until this lands. **Batch its effects into the same next full corpus rebuild as todo 146's grid fix, not a standalone rebuild.** |
| [166](pending/166-1d-ensemble-eligibility-small-sample-treatment.md) | New 2026-07-21, split out of todo 164: `1d`'s median effective-N (1,222, min 143) is ~32x fewer than `15m`'s, CI width 3x wider — a genuine small-sample power problem (Type II error risk), not a miscalibrated threshold like `1h`'s. Needs a real small-sample statistical treatment (Bayesian shrinkage IC or a calibrated day-clustered bootstrap), scoped as its own plan. |
| [171](pending/171-rates-dual-write-symbol-hmm-reversion-check.md) | New 2026-07-22, a "don't forget" item recorded when closing Phase 144: `rates.dual_write_symbol_hmm=true` was deliberately temporary shadow-mode measurement; F1's non-trigger answered the question but only on a scoped 12-symbol run. Batch into the next full corpus rebuild (same cluster as todo 146/155) — confirm F1 holds at full scale before reverting the flag, don't revert on a partial sample, don't forget to ever revisit it either. |
| [172](pending/172-path-dependent-frame-statistics-order-sensitivity-sweep.md) | **Item 2 FIXED 2026-08-03** -- `frame_gate_passes`'s cluster-mean array is now sorted at both the inter-cluster and within-cluster level (the second level needed once testing exposed residual ULP-level float-summation noise from the first fix alone); regression test asserts exact reproducibility across different row-fetch orders. Item 1 (broader path-dependent-statistics sweep elsewhere in the codebase) remains open, unscoped. Did not affect Phase 148's actual gate verdicts (background: `_max_drawdown` over `alpha_frames` silently produced a non-reproducible number because same-`bar_ts` frames were treated as sequential in a cumulative-sum walk -- separately fixed for Gate 2 already). |
| [223](pending/223-src-intelligence-i1-i7-dead-code-153-files-30k-lines.md) | New 2026-08-01, found during a "clean up docs tests scripts dead code" survey pass: `src/intelligence/`'s I1-I7 orchestration/plugin tree (~153 files, ~30k lines) has no live production entry point (`services/intelligence_pipeline.py` is physically deleted) — reachable only via `shadow_validator.py`'s weekly job, which queries a table (`shadow_registry`) already confirmed dead. One clean orphaned duplicate (`features/i5_patterns/`, 17 files) already deleted same day. The rest needs an explicit delete-vs-archive decision plus a matching call on 18 Group-A dead-pipeline tests and 26+ Group-B SLA/I7-plugin tests (Group B depends on whether the paused IBKR ingestion chain resumes through the v2.x signal path or not). |
| [226](pending/226-regime-writer-n-iter-convergence-headroom-check.md) | New 2026-08-02. **Step 1 DONE 2026-08-02**: log `model.monitor_.iter` per (symbol, tf) cell (commit 5c86ffeb + fix 7a0d7de1). Next step: analyze distribution to decide if n_iter=200 cap is oversized. |
**227 CLOSED 2026-08-31, row removed.** Design decision resolved 2026-08-05 (tolerance
acceptable, not bit-identical), implementation landed and flag flipped 2026-08-12, full-scale
confirmation done 2026-08-31: post-flip full `ic_engine` runs trending faster run-over-run
(289,674s -> 237,730s) with zero downstream gate anomalies. See todo file's closure section.
| [228](pending/228-corpus-pipeline-unmeasured-steps-io-vs-cpu-triage.md) | New 2026-08-02. `217` (step-timing instrumentation) is CLOSED (step_timings.jsonl confirmed live) but only captured steps 5-8 so far — steps 1-4 predate the instrumentation landing mid-run. Needs one more full pipeline run from step 1 to get timing data for all 8 steps. Then: classify steps 1/6/7/8 as I/O- vs CPU-bound before applying thread-tuning lessons from todos 215/216. |
| [235](pending/235-cross-sectional-relative-value-5m-construction-never-tested-15m-is-a-default-not-a-finding.md) | New 2026-08-03, user question mid-session. Phase 167's live tracker trades cross_sectional_relative_value at 15m only -- checked, that's an inherited default from the original falsification script, not a comparative finding. The one existing 5m cost-hurdle result (todo 030) tested standalone directional IC, not cross_sectional_relative_value's netted dollar-neutral spread, which the research doc itself says has different cost dynamics. Run cross_sectional_relative_value's actual methodology at 5m before assuming 15m is the right choice. |
| [256](pending/256-ctf-columns-no-explicit-ensemble-exclusion-pending-join-fix-recompute.md) | New 2026-08-05. `ctf_momentum`/`ctf_vwap_align`/`ctf_regime_align` (todo 243's leaked join, unfixed in the live corpus) have no explicit ensemble-eligibility exclusion — currently kept out of `alpha_ensemble_ic` by `ensemble_trainer.py`'s meta-FDR gate on their own (weak/sparse) merits, not by design. **Re-verified live 2026-08-07 against the post-join-fix, post-todo-230-resolution corpus (0.0/0.1/0.2% pass rates across 3,640 cells each) — still doesn't clear admission, risk confirmed still dormant, not resolved.** Fragile — any future `ic_engine` run could flip that by accident. `todo 230` resolved 2026-08-02 (steps 6-8 run regularly now), that's no longer a reason for low urgency — should close before/alongside any future recompute regardless. |

## P3 — Hygiene, docs, process (opportunistic)

**2026-08-26:** [359](pending/359-phase173-altitude-design-notes.md) added — 3 Phase 173
architecture notes (cluster_id offset partition, fingerprint watermark special-case, hardcoded
validation list), all already reviewed/accepted by codex+agy during Phase 173's own mandatory
review, recorded for future consideration only.

**336 CLOSED 2026-08-21, row removed.** Ran the specified cross-chunk aggregation + code
cross-check against all 5 flagged indexes (live DB, read-only, safe alongside the running
corpus job). Mixed verdict, not a blanket call: ~973MB (`feature_ic_scores_history_cell_idx`
+ `_archived_at_idx`, `idx_market_data_ohlcv_base`) confirmed dead -- real drop candidates,
not yet executed (DDL deferred until the current corpus run finishes). The biggest one
(`idx_market_data_ohlcv_price_sanity_unaudited`, 501MB) turned out NOT to be simply dead --
its column order can't serve its own real consumer's query shape, a genuine design bug, not
neglect. Filed as [347](pending/347-price-sanity-index-column-order-mismatch-bar-auditor-query.md),
which also cross-references todo 155's ~4.1-year backlog-clear estimate as a possible
downstream consequence. `ensemble_alpha_symbol_tf_idx` left genuinely ambiguous (real
consumer exists, table is 30M rows not small, but 0 scans unexplained). Full evidence in
`completed/336-...md`.
| [347](pending/347-price-sanity-index-column-order-mismatch-bar-auditor-query.md) | New 2026-08-21, found investigating todo 336. `idx_market_data_ohlcv_price_sanity_unaudited`'s `(symbol, timeframe, timestamp)` column order can't serve `bar_auditor.py`'s actual query shape (`ORDER BY timestamp` with no symbol/tf filter) -- likely explains both the 0-scan finding directly and possibly part of todo 155's ~4.1-year price-sanity backlog-clear estimate (the read side of that pipeline was never checked, only the write side). Fix shape identified (drop symbol/tf, add `volume > 0` to the partial predicate) but deliberately not built -- same compressed-hypertable class as the 2026-08-13 disk-full incident, needs its own reviewed pass per `performance-investigation-sop.md`, not a drive-by DDL change. |
| [348](pending/348-equity-regime-model-still-carries-unfixed-on2-causal-rank.md) | New 2026-08-21, `/simplify`'s reuse-angle review of `causal_rank.py`'s O(n^2)->O(n log n) rewrite. `services/equity_regime_model.py:237-257`'s `_compute_vix_pct_rank` still carries its own hand-copied, unfixed O(n^2) causal-rank loop -- the exact algorithm the shared helper just fixed, never migrated onto it. Deliberately not touched: the file is DEPRECATED (Phase 144) and marked "no functional changes" since its migration, an emergency single-group rollback path, not the live path (`cross_sectional_regime_model.py` is). Needs its own TDD pass, not a drive-by. |
| [349](pending/349-stage2-hurst-rolling-apply-still-unvectorized.md) | New 2026-08-22, `/simplify`'s altitude-angle review of the autocorr vectorization fix in `per_symbol_regime_candidates_stage2_orthogonality.py`. `_single_window_hurst`'s `rolling.apply()` is now the dominant remaining cost in `_compute_candidates` (same 200x null-arm hot loop the autocorr fix targeted) -- no direct pandas-vectorized equivalent exists for the R/S statistic (unlike autocorr's exact Pearson-correlation identity), needs custom `sliding_window_view` engineering plus its own TDD pass. Not urgent: research script, doesn't block any measurement, just slower than necessary. |
| [350](pending/350-stage3-build-panel-recomputes-all-5-candidates-per-name.md) | New 2026-08-22, `/simplify`'s efficiency-angle review of the same fix. `per_symbol_regime_candidates_stage3_falsification.py`'s `_build_panel()` calls `_compute_candidates` (all 5 candidates) once per `candidate_name` iteration but uses only 1 -- up to 200x5x(4/5 wasted) computation across the null-arm loop. Fix requires restructuring the loop nesting so `_compute_candidates` runs once per symbol per permutation, not per candidate_name; needs a real design decision on whether the null arm shares one permutation across all 5 candidates per replicate (changes statistical meaning, not just speed) -- not a mechanical optimization. |
**351 CLOSED 2026-08-31, row removed.** This "not yet confirmed live-impacting" risk turned out
to be exactly what caused the 2026-08-23 AND 2026-08-30 `alpha_publisher` production failures
(same statement-timeout signature both times, self-deadlock via `XactLockTableWait` -- see
`docs/reference/gotchas.md`'s new asyncpg entry). Fixed: `_flush_chunk` now takes `conn`
directly instead of acquiring a second pooled connection. Verified live: rerun against the
70.5M-row corpus completed cleanly in 78.5min, no hang, fresh data confirmed in `alpha_events`.
| [352](pending/352-chunk-accumulate-flush-pattern-duplicated-4x-extract-to-batch-utils.md) | New 2026-08-23, `/simplify`'s reuse-angle review of the same fix. The accumulate-then-flush-at-chunk_size shape is now independently duplicated 4x across `services/` (`alpha_publisher.py`, `alpha_frame_writer.py`, `counterfactual_tracker.py`, plus one more) with no shared `_batch_utils.py` helper -- confirmed not a reuse bug in any one diff (each follows the existing convention), but worth extracting once, touching all call sites in one dedicated pass rather than piecemeal. |
| [359](pending/359-phase173-altitude-design-notes.md) | New 2026-08-26, `/simplify`'s altitude review of Phase 173's diff. Three design-depth notes, all already reviewed and accepted by both codex and agy during Phase 173's own mandatory Wave-3 review -- not bugs, not urgent, recorded for future consideration only: (1) `_BROADCAST_CLUSTER_ID_OFFSET = 10000` is a numeric-range partition bolted onto the BH-FDR grouping key rather than a real `cell_kind` field; (2) `_fingerprint_computational_key` special-cases the literal `"broadcast_hash"` string instead of classifying watermark sub-keys generically at the point produced; (3) `_D02_ENUMERATED_BROADCAST_FEATURES` (32-name validation floor) lives in an ops script, not a test, so it will drift silently with no CI signal. |
| [361](pending/361-rename-ensemble-layer-to-alpha-combiner.md) | New 2026-08-30, user naming-taste call. Rename `ensemble_trainer`/`EnsembleICEngine`/`ensemble_weights`/`alpha_ensemble_ic`/`alpha.ensemble.*` to an `alpha_combiner` family -- "ensemble" is an ML borrowing, "alpha combination" fits this project's Renaissance/Simons framing better. Real rename (code + DB migration + CLAUDE.md + docs), not urgent. **Update 2026-08-31: the "land before ensemble_trainer's next run" window has closed** -- that run (step 7 of the post-Phase-173 recompute) completed 2026-08-30 under the old name, before this todo was actioned. No longer time-sensitive to a specific run; do whenever, migration will just rename in place over live data as originally scoped. |
| [362](pending/362-bil-5m-zero-regime-volatility-labels.md) | New 2026-08-31, found during todo 285's closure verification. `BIL/5m` has zero `regime_volatility` (calm/elevated/turbulent) labels in `feature_ic_scores` despite 165,500 rows in `feature_vectors` -- not explained by the usual bar-floor limitation (unlike the other 44 cells in the same diff, all `1d` or short-history). Hypothesis: BIL's near-flat T-Bill price series may be structurally unsuited to volatility-HMM fitting. Not yet root-caused. Low priority, single-symbol/single-tf scope. |
| [363](pending/363-ib-gateway-libgtk3-fix-not-durable-across-recreation.md) | New 2026-08-31, found fixing todo 306's live-ingestion gap. `libgtk-3-0` was missing entirely from `ghcr.io/gnzsnz/ib-gateway:stable`'s image -- the real root cause of the 16-day ingestion outage, fixed live via `apt-get install` inside the running container. Survives `docker restart` but NOT a container recreation (`--force-recreate`, image re-pull since `:stable` is a rolling tag) -- needs a small wrapper Dockerfile baking the package in, or this exact bug returns silently. |
| [365](pending/365-bootstrap-ic-duplication-jump-diffusion-cointegrated-pairs.md) | New 2026-09-01, reuse/architecture check before writing `statistical_factor_residual`'s Stage 3. `ic_math.py::_circular_block_bootstrap_ic` has 2 independent hand-rolled duplicates (`cointegrated_pairs_residual_pilot.py`, `jump_diffusion_decomposition_spy_pilot.py`, both DEAD candidates) for the bootstrapped-partial-IC case it doesn't natively support. Verified Stage 3 itself does NOT repeat this (reuses the shared primitive as-is per its pre-registered design) -- not blocking, purely future-proofing hygiene if a 3rd real need for bootstrapped partial-IC shows up. |

**303/304 CLOSED 2026-09-01, rows removed.** Ran Stage 3 (falsification + null-arm) for both
todos' candidates together (shared script, pooled BH-FDR family, 20 threshold-clearing tests
across 5 candidates x 2 xbar columns x 2 timeframes). All DEAD: neither `hurst_rank` nor
`autocorr_rank` (303) nor `volatility_pct`/`skew_tail`/`volume_pct` (304) sharpens IC beyond
`regime_volatility` at 5m or 15m. One cell (`hurst_rank vs momentum_z_fast @ 5m`) cleared the
raw null-arm bar (null_p=0.03) but failed BH-FDR correction (bh_p=0.475) -- the
multiple-comparisons false positive the design exists to catch. Along the way, found and
fixed two real bugs in the shared Stage 2/3 scripts: an unvectorized Hurst rolling-window
computation (22x slower than necessary, caused a 4h48m run producing zero output) and a
single DB connection held idle across the whole compute stretch past Postgres's 1h
idle_session_timeout (crashed mid-run). Both fixed, commit `1084a1d11`. Full numbers:
`docs/research/measurement-per-symbol-trend-regime.md` and
`docs/research/measurement-per-symbol-percentile-rank-candidates.md`'s "Result — Stage 3"
sections.

**364 CLOSED 2026-09-01, row removed.** Re-ran N1-a-capped @ 1h fresh at both colsample_bytree
values (0.10, 0.05) -- both reproduced their original 2026-08-25 numbers bit-identically
(`point_diff`/`ci_lower`/`ci_upper`/`p`/fold-1 breach magnitude/row counts all matched exactly),
traced to todo 366's live-ingestion gap meaning the 1h equity corpus genuinely hasn't grown
since before N1's original run. Verdict per the todo's own pre-registered framing: the
colsample-sensitivity instability persists, confirming it's real and structural, not a
data-staleness artifact. Full numbers:
`docs/research/measurement-nonlinear-interaction-combiner.md`'s "N1-a-capped @ 1h fresh
re-run, 2026-09-01" section.

**244 CLOSED 2026-08-21 -- re-verified, decision confirmed unchanged, row removed.**
`ctf_vwap_align`/`ctf_regime_align` still have zero live consumers (`ensemble_trainer.py`/
`concept_registry_service.py` confirmed clean via direct grep) -- the 2026-08-03
"not worth fixing speculatively" call stands. Full evidence in `completed/244-...md`.

**322 CLOSED 2026-08-21 -- doc fix landed in both places Invariant 1 is stated, row removed.**
CLAUDE.md's UCR paragraph and `docs/foundation/unified-concept-registry.md`'s own Invariant 1
(the "full spec" CLAUDE.md itself points to) both now carve out migration-time genesis seeding
from the status-flip rule. The "5 migrations" claim re-verified directly (288/289/290/291/316,
each grepped and read) before citing it, not trusted from the filing text. No code/behavior
change. Full detail in `completed/322-...md`.

| Todo | What |
|---|---|
| [338](pending/338-integration-db-rebuild-fixture-per-table-seed-pattern-repeating.md) | New 2026-08-20, from todo 293's `/simplify` altitude pass. `tests/integration/conftest.py`'s per-table data-seed pattern (schema-only baseline drops a pre-cutoff reference table's DML, blocking the whole rebuild fixture until seeded) has now repeated twice (`instruments`, then `tag_vocabulary`). Not fixed generically yet -- two occurrences is defensible one-off under YAGNI -- but nothing watches for a third. Tripwire only: if a third table hits this, generalize instead of filing a fourth narrow todo. |
| [298](pending/298-backfill-connection-drop-silent-failure-and-completeness-audit.md) | New 2026-08-11, follow-up from todo 296. **Downgraded P0→P3 same session**: original filing claimed the backfill's connection-drop path was a silent failure — wrong, re-reading the code confirmed it already prints exact symbol/tf errors, exits nonzero, and emits `job_completed_total{status="partial"}`. Root-cause half (checkpoint I/O contention) already fixed live this session (`max_wal_size` 1GB→4GB via `ALTER SYSTEM`+reload). What's left is tooling polish: `backfill_retry_loop.sh` doesn't generalize to arbitrary `--client-id`/`--symbols` (hardcoded for the original 80-symbol universe), and no automated end-of-run completeness summary beyond the exit code (the `n_tf=5` SQL exists, just isn't wired in). |
| [056](pending/056-phase146-147-v2x-retirement-stale.md) | ROADMAP Phase 147/148 text rewritten 2026-07-19 (operator call resolved: archive not delete, decouple from proof gates). Remaining scope: the actual decommission-in-fact execution (git mv v2.x code to archive/, disable dead systemd units, rename-not-drop the frozen v2.x tables) — real multi-file operation, do with a clean git state. |
| [225](pending/225-multi-vector-systematic-regime-join-hybrid-sensitivity-symbols.md) | Downgraded P2→P3 2026-08-01 per its own pilot finding: read-only pilot on 5 hybrid symbols (`OIH`/`XLE`/`XOP`/`AMLP`/`GDX`) came back negative — the one BH-FDR survivor (`GDX momentum_z_fast`) failed cross-timeframe replication, flat null. Real information, not wasted effort; don't build the Fix steps until a better-motivated candidate surfaces or the universe scales. Full methodology in the todo file's "Pilot result" section. |
| [115](pending/115-days-to-month-end-exact-redundancy.md) | `days_to_month_end` is an exact affine complement of `month_position` (Pearson correlation -1) — perfectly collinear, remove one. |
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
| [324](pending/324-gradient-vocabulary-naming-check-unenforced.md) | New 2026-08-15, found via user Q&A tracing fast/mid/slow naming against APR/ITR/CVR/UCR. naming-system.md §7's gradient-scale-vocabulary table (widely used across Feature Factory primitives) has zero CI/pre-commit enforcement - only Check 3 (Ring 0 boundary) of the doc's own 5 proposed checks is actually wired into `ci.yml`. **Revised twice 2026-08-15**: settled on a CVR `gradient_scale` namespace under the new D-07 admission criterion (todo 326's grep found concrete self-drift among Python-only CVR consumers, justifying the criterion) rather than a standalone module. Needs `VocabularyDriftAuditor`'s `has_live_source` distinction designed first. **330 (its sequencing blocker) CLOSED 2026-08-20** (row corrected 2026-08-21 -- was still linking `pending/330-...`, a broken path since 330 moved to `completed/`) -- `src/core/timeframe_vocabulary.py` → `src/core/vocabulary_access.py`, `codes(namespace, default)` primitive live. The sync-context read module this todo would have duplicated already exists; unblocked, no longer waiting on 330. |

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

**Extended backlog pass, 2026-08-21/22 (same overall session as the P0-clearing pass above):**
9 more todos closed with real evidence (276, 244, 329, 322, 342, 294, 313, 336, 315, 328, 346 --
each has its own closure note inline above at the tier it was in), pending count 105→96. Two
non-todo findings surfaced and fixed along the way, not filed as todos since they were
same-session catches: (1) `main` was genuinely broken for several minutes
(`ModuleNotFoundError` on `import src.intelligence.pipeline`) when an earlier autonomous
iteration's dead-code deletion (todo 328) got cut off by context compression before its
dependent `__init__.py` fix landed -- caught and fixed same session (`8046f1e32`). (2) Todo 346
itself, self-filed mid-session suspecting a broken mypy-baseline gate, was re-investigated and
found wrong -- the gate is clean, closed with the correction on record. **Drift audit re-run**:
`ls pending/` vs. every `[N](pending/...)` link -- only 080/270 unlinked, both already
documented as deliberate exclusions (redirect stub, phase-promotion note respectively), no new
gaps. All 17 commits from this window pushed to `origin/main` (`466676e61`), clean fast-forward.
