---
phase: 186
reviewers: [claude-opus-r1, claude-opus-r2, grok-4.7-high-owner-run, claude-opus-r3, claude-opus-r4, claude-opus-r5, claude-opus-r6]
reviewed_at: 2026-09-27T15:11:55Z
plans_reviewed: [186-01-PLAN.md, 186-02-PLAN.md, 186-03-PLAN.md, 186-04-PLAN.md, 186-05-PLAN.md, 186-06-PLAN.md, 186-07-PLAN.md, 186-08-PLAN.md, 186-09-PLAN.md, 186-10-PLAN.md, 186-11-PLAN.md, 186-12-PLAN.md, 186-13-PLAN.md, 186-14-PLAN.md, 186-15-PLAN.md, 186-16-PLAN.md, 186-17-PLAN.md, 186-18-PLAN.md, 186-19-PLAN.md, 186-20-PLAN.md, 186-21-PLAN.md, 186-22-PLAN.md, 186-23-PLAN.md, 186-24-PLAN.md, 186-25-PLAN.md, 186-26-PLAN.md, 186-27-PLAN.md, 186-28-PLAN.md, 186-29-PLAN.md]
external_reviewers: `agy` quota-blocked until ~2026-10-01, `codex` until ~2026-10-15 (probed 2026-09-25, not re-probed per memory); substitutes: an owner-run Grok 4.7 (high) review over all 29 plans (section below, source file 186-REVIEW-GROK.md) plus six fresh-context Claude Opus agents, one plan group each, shared prompt
---

# Cross-AI Plan Review — Phase 186

External CLIs (Antigravity, Codex) were quota-blocked on 2026-09-27; per the standing fallback,
each plan group was reviewed instead by a fresh-context Claude Opus agent with repo access and a
shared adversarial prompt (`R1`..`R6`). All 29 plans were covered; group assignments:

- R1: 186-01, 186-02, 186-16, 186-29 (summary cards; scripts/analysis deletion)
- Grok (owner-run): all 29 plans, goal-backward contract-level read (section after R2)
- R2: 186-03, 186-04, 186-05, 186-06, 186-07, 186-17 (determinism tool, helper promotion, db hygiene, bulk-load primitive, todo 445, Postgres tuning)
- R3: 186-08, 186-12, 186-13, 186-15, 186-18 (kernel registry, feature_factory splits, regime kernel + bundle)
- R4: 186-09, 186-10, 186-14, 186-20, 186-28 (lifecycle shrink, fresh IC jobs/writer, parity + purge, fresh IC on rebuild)
- R5: 186-11, 186-19, 186-21, 186-22, 186-23 (ctx-writer retirement, old-chain code deletion, ops/APR keys, table drops, ic_engine/forward_returns deletion)
- R6: 186-24, 186-25, 186-26, 186-27 (new feature_vectors schema, rebuild writer, gated rebuild run, close-out)

## R1 Review — Claude Opus (fresh context)

**Plans:** 186-01, 186-02, 186-16, 186-29

### Summary

This is a well-evidenced plan set. Nearly every factual assertion I checked against the repo held: the 7-row `gate_evaluations`/`gate_look_log.jsonl` table in 186-01 matches the database exactly; all 18 ledger section 4 rows, the 5 reopened rows (10, 13, 14, 17, 18), every cited doc, migration, todo, milestone report and manifest exists; the three freeze/run commits resolve; the writers table matches actual `INSERT INTO` sites; the 186-16 importer list and test-deletion set match a fresh grep exactly; the sleeve `config.py` import-closure claim (only `__future__` + `dataclasses`) is true; and the 13-name DROP_TABLES list maps completely onto what 186-11, 186-22, 186-23 and 186-27 actually drop. The concerns below are coupling ambiguities and small factual nits, none of which break an invariant or lose data.

### Strengths

- 186-16's importer inventory is exactly right. I reproduced `grep -rnE "(from|import) +scripts\.analysis"` repo-wide; every outside importer is accounted for (5 research tests kept, `test_date_panel.py` and `test_compute_ready_predicate_apr.py` to 186-04, `universe_expansion_promote_compute_eligible.py:34` to 186-04, the rest deleted), and no importer of a surviving module is missed.
- 186-01's `gate_evaluations` table (gate_id/result/run_ts, 7 rows, the unnamed 2026-07-23 look) verified live read-only: identical. The `gate_look_log:2026-07-23T00:26:31.223260Z` ref matches the jsonl `run_ts` byte-for-byte.
- 186-02's 18-row interfaces table verified against `docs/research/construction-verdict-ledger.md` section 4 (18 rows, verdict wordings map onto the 6-value enum including `REJECTED_AS_AXIS` for row 8 and `INCONCLUSIVE` for row 9) and section 2 (exactly rows 10, 13, 14, 17, 18 reopened). Freeze commits `0c33a2596`/`da0548a96`/`f461bdc54` all resolve.
- DROP_TABLES (13) fully reconciles with downstream reality: ctx_events/ctx_snapshots (186-11), 9 chain tables (186-22), forward_returns (186-23), feature_vectors (186-27). No drop plan drops a table outside the list.
- Deletion discipline is strong: pre-delete sha recorded, D-08 greps with recorded output, no archive copies, migrations committed with apply, boundary allow-list verified to contain zero `scripts/analysis/` entries (so nothing to remove there, correctly not listed in files_modified).
- 186-16's measured "95 Python files, ~26.8k lines" is accurate (95 .py + excluded_features.json, 26,843 lines).
- Gate structure is honest: both deletion plans gate on real conditions (process check via ps, card lint with git checks active, STATE.md lane row quoted verbatim in the summary) and stop safely rather than proceeding degraded.

### Concerns

- **MEDIUM — 186-16 gate 3 hardcodes 186-04's discretionary module names.** Task 1 gate 3 requires `scripts/research/date_panel.py`, `cost_hurdle.py`, `feature_matrix.py` to exist, but the outline (186-PLAN-OUTLINE.md:91-96) says 186-04's module names are "Claude's discretion". If 186-04 picks different names, 186-16 false-blocks on a healthy tree. Failure mode: safe stop, but a blocked wave-3 plan needs a re-gate edit. Evidence: 186-16-PLAN Task 1 gate 3 vs outline lines 91-96.
- **MEDIUM — 186-01's git-history checks skip in CI, and the D-06 coverage gate is only as strong as the drop plans' local runs.** The `test` job uses default checkout (`.github/workflows/ci.yml:175`, no fetch-depth; the `fetch-depth: 0` at :94 belongs to `plugin-guards` only), so 186-01's claim is correct, but T-186-01-06's "drop plans run the lint locally" is stated in 186-01, not enforced by 186-22's own text I can see (outline line 273 does say "card lint green" as 186-22's gate). Acceptable, but 186-23 (drops forward_returns) does not name the card lint as a gate anywhere; coverage happens to hold because the card already exists. LOW-to-MEDIUM; worth one line in 186-23's gate.
- **LOW — 186-16's glossary-baseline count is wrong.** Task 2 says "delete the keys for files that no longer exist (the three `scripts/analysis/...` keys today)", but `tools/glossary_baseline.json` has five keys naming files 186-16 deletes: lines 88, 91, 94 (scripts/analysis) plus lines 151, 154 (`tests/unit/sleeve_walk_forward/test_run.py`, `test_synthetic.py`). The general instruction covers all five if followed literally, and stale keys don't fail `check_glossary`, so impact is cosmetic; 186-29's later "any key containing sleeve_walk_forward" sweep would catch the stragglers anyway.
- **LOW — 186-16 Task 2 acceptance `git diff --name-status <pre-delete sha> | grep -v "^D"`** is only correct if evaluated at the deletion commit; after Task 3's edits (migration, docs, README, todo) the same command lists extra non-D files. Ambiguity an executor could misread as a failure or, worse, satisfy early.
- **LOW — line-number drift in cited anchors.** CLAUDE.md `fetch_training_matrix` reference is at line 157, not 159 (186-16 interfaces; plan says re-grep, so harmless). Same class: 186-02 cites ledger "sections 2 and 4 (lines 47-122)" which is approximately right.
- **LOW — 186-02 rule 3's table-extraction heuristic** (`grep -oiE "(from|join)\s+[a-z_]+"` over the script at recipe_commit) will match CTE names and prose words; the `to_regclass`/migration confirmation step mitigates, but expect noisy `tables` lists. Not a correctness risk given the confirmation step.

### Suggestions

- In 186-16 gate 3, replace the three file-existence checks with the name-agnostic condition that actually matters: the two repoint greps print 0 (already present) plus `grep -rnE "(from|import) +scripts\.analysis" scripts/infrastructure tests/unit/scripts` being empty except sanctioned paths. Keep the filenames as an informational note, not a gate.
- In 186-16 Task 2, scope the non-D diff check to the deletion commit (`git diff --name-status HEAD~1 HEAD` at that commit, or `<pre-delete sha>..HEAD` evaluated before Task 3 starts), and say which.
- 186-16 Task 2: correct "the three scripts/analysis/... keys today" to five, or just say "every key naming a path this plan deletes, including the two tests/unit/sleeve_walk_forward keys".
- Consider adding one sentence to 186-23's gate (other reviewer's plan, flag to the phase owner) that the card lint must be green, matching 186-22, since it drops `forward_returns`.
- 186-01: the strict-loader copy from `src/intelligence/research/spec.py:317-338` is a good instinct; add a fixture asserting a YAML `yes`/`on` also parses as a string (YAML 1.1 booleans beyond no/yes pairs), since the resolver copy is subtle.

### Risk assessment

**LOW-to-MEDIUM overall.** No plan asserts anything false that would cause data loss, a broken invariant, or an unsafe execution; every load-bearing repo claim I tested (importers, tables, rows, verdicts, commits, allow-lists) checked out. The residual risk is execution friction: the 186-16 gate's hardcoded sibling-plan filenames could false-block, and the two card plans (01, 02) are heavy transcription work where a mis-copied number is the main hazard; their mitigation (every number pinned to a source with SQL and run date in prose, lint-enforced refs) is the right shape for that.

### Cross-plan checks

- **Names vs outline:** wave numbers match the outline for all four plans (01 w1, 02 w2, 16 w3, 29 w4); depends_on edges match outline rows exactly. Binding names used (`scripts/research/determinism/repro_frozen.py`, `HarnessConfig` import line, `tests/unit/research_tools/test_determinism_modules.py`, card id grammar) are consistent across 01/02/16/29 and the outline.
- **Gate circularity:** none. 01 → 02 → 16 → 29 is a clean chain; 16 gates on 01+02 card lint plus 03's recorded bit-identity plus 04's repoint; 29 gates on 16's survivor set plus lane release. 16's note on 186-13 (`_compute_symbol_tf` importers) is order-independent as claimed: the 11 `hmm_*` importer pilots are deleted by 16, verified they exist and are not in the keep set.
- **Deletion/keep handoff 16 → 29:** survivor set (4 paths) matches what a fresh `git ls-files` implies post-16; `test_config.py`'s rewritten assertion `shift_memory == 504+252+2` matches the actual `HarnessConfig.shift_memory = 758`; the "sleeve config removed" skip in 186-03's byte-equality test is anticipated in 29's scope limits.
- **Card pointers vs deletions:** every `scripts/analysis/` path cited by a 01/02 card will be gone from HEAD after 16/29; the lint's dual check (`recipe_commit:<path>` OR `HEAD:<path>`) plus 16's post-deletion lint rerun and the README "Deleted recipe code" paragraph close this correctly.
- **Boundary allow-list:** `tests/unit/test_market_data_ohlcv_boundary.py` has no `scripts/analysis/` entries, so no same-commit allow-list removal is needed; 186-16's files_modified correctly omits it.
- **186-01 key_links names "downstream drop plans 186-11, 186-22, 186-27"** but not 186-23 (forward_returns drop) — coverage still holds since the card exists; cosmetic.

---

## R2 Review — Claude Opus (fresh context)

**Plans:** 186-03, 186-04, 186-05, 186-06, 186-07, 186-17

### Summary

This is an unusually well-evidenced plan set. Every repo and database claim I checked held: the frozen pickles and their embedded old class path (03), all four promoted helpers and their importers (04), the duplicate index and the exact 11-table no-PK inventory (05), the todo 301/343/352 bodies and the `_batch_utils` interfaces (06), todo 445's body and the `oos_start` enforcement chain (07), and the container drift facts (17). Gates are mostly real, refusal semantics are defined, and the plans respect D-01/D-02/R-11/R-13. The findings that remain are gate-quality and coordination issues: one vacuous acceptance grep (07), a migration-number race between parallel wave-1 plans (05/06), a restart gate that may be unsatisfiable for weeks given the live 449 backfill (17), and a gap between 06's append-only contract and the outline's `bulk_load(replace_where=)` binding name.

### Strengths

- **03:** Both S3 pickles verified to embed `scripts.analysis.sleeve_walk_forward.evaluate` (`strings` on `s3_4dead18ade3bde16.pkl`, `s3_d3c9294661215c6d.pkl`); both S2 pickles carry no first-party class path, exactly as the plan claims. All cited line numbers in the sleeve modules match (`snapshot.py:24-29,249-299`, `run.py:156-169,191-206`, `repro_frozen.py` argv-at-import). Sleeve/research non-editing is enforced by `cmp` and `git diff --stat` gates, plus a baseline run of the original tool so a research regression cannot be masked as a promotion pass.
- **04:** Importers verified at the claimed lines (`universe_expansion_promote_compute_eligible.py:34`, `test_compute_ready_predicate_apr.py:15`, `test_date_panel.py:5`); the onboarding SOP genuinely names only the promote script (verified, so "no edit needed" is correct, not an omission); promoted fetch reads `market_data_ohlcv_tradeable` only; `forward_returns` ban is enforced by AST/grep gates.
- **05:** Live catalog matches the plan's 11-table inventory exactly (my `pg_index` query returned the identical set). Duplicate index exists: 387 MB, 31.9M scans; PK same key, 0 scans, 400 MB, verified plain table. The plan correctly captures the surprising scan asymmetry and gates the drop on a rolled-back-transaction EXPLAIN proof. Settings drift confirmed live: `work_mem` 8192 kB source `command line` vs compose 64 MB. Refusal to touch settings is airtight: read-only script, acceptance checks container `StartedAt` unchanged.
- **06:** D-01 gate is real and correctly scoped; I verified `_batch_utils` is in ic_engine's import closure (`services/ic_engine.py:95`) and that the live 449 backfill pipeline does *not* import it, so the gate's pattern correctly omits it. Idempotency design is sound: PK on `batch_key`, data COPY and completed record in one transaction, immutable-identity guard trigger modeled on the real migration 366, advisory lock against concurrent same-key loads.
- **07:** In-sample bound is enforced by construction at three layers: `build_panel` refuses `end_exclusive > oos_start` (verified `snapshot.py:241`), SQL filters `bar_ts < oos_start`, and the result JSON asserts it. `oos_start` is read from `config_state` (verified value `2025-12-24T05:15:00Z`), never hardcoded. 5m alignment is the bar *ending* at the 15m close with a runtime `bar_close_ts` check; the decision rule is committed before the run; the counted look lands in the git-tracked `gate_look_log.jsonl`. Cost constants match `personal_cost_hurdle_by_tf.py:40-51`.
- **17:** Every container fact verified live: `.Config.Cmd` has `work_mem=8MB`, Created 2026-06-22, ShmSize 512 MiB, compose says 64 MB. The restart gate is a real multi-signal check (`ps aux` patterns, non-idle sessions + idle-in-transaction, timers within 30 min, recent backfill write) with defined refusal semantics: stop, record, retry later, never kill, never wait-loop. `--no-deps --no-build` plus before/after `version()`/`extversion` blocks the silent image upgrade; the config-hash-label check structurally prevents R-12 drift from recurring.

### Concerns

- **MEDIUM (07, Task 3):** The STATE.md acceptance `grep -n "needs the 5m timeframe decision first" .planning/STATE.md returns nothing` is vacuous: the clause wraps across lines 68-69 (`...needs the 5m` / `timeframe decision first (todo 445...`), so the literal string never matches, before or after the edit. The only automated check that the stale clause was actually replaced is the second grep for `445`, which stays present either way. Failure mode: the stale "rebuild needs the 5m decision first" fact survives, contradicting the closed todo. Fix: grep for `timeframe decision first` or assert a decided-fact string exists.
- **MEDIUM (05 Task "numbering" vs 06 Task 1, cross-plan):** Both plans name the same next migration number (05: "As of planning the highest is 379"; 06: "380 if nothing landed since 379") while running concurrently in wave 1, and 186-09 also adds a migration. The mitigations (check `ls production/migrations` in both the worktree and main immediately before numbering, `test_migration_number_uniqueness.py`) are real but racy across the check-then-apply gap. Failure mode: duplicate numbers, CI failure, rework; worst case two agents apply interleaved files. Suggest a stated rule: re-check after writing the file and immediately before `psql -f`, and on collision take the next number and rename before applying.
- **MEDIUM (17, Task 2):** The gate may be unsatisfiable for weeks. The todo 449 backfill is live right now (verified: `infrastructure_run_historical_pipeline.py --client-id 46`, 1h/15m lane, running 2026-09-27) and runs through ~mid-Oct; the gate refuses on it. The plan's retry-later semantics are safe but unbounded, and the pinch is real: after 449 finishes, the rebuild (186-26) launches, and 186-17 would then refuse on the rebuild. The natural windows are (a) a gap between 449 lanes, or (b) immediately after 449 completes and before the rebuild's precondition check passes. The plan coordinates with neither. Failure mode: tuning lands after the multiday rebuild it exists to speed up, or the executor burns retries. Suggest Task 2 name the intended window explicitly and record coordination with the 449 session in the summary.
- **MEDIUM (06 vs outline, cross-plan):** The outline's binding names include `bulk_load(replace_where=)`, `kernel_code_key()` and `bar_content_digests()` "in `services/_batch_utils.py`", but 186-06 defines `bulk_load` with no `replace_where` and an explicit append-only, loud-PK-conflict contract. An executor of 186-06 reading the outline could implement `replace_where` now, contradicting the must-have truths; or 186-14's later extension could be judged a contract violation. 186-06 should state in one line that `replace_where` and the two digest/key helpers are later plans' (186-14) extensions of the same module, so the sole-writer allow-list and contract are read as extensible.
- **LOW (17, Task 2):** `SELECT max(fetched_at) FROM backfill_status` names a nonexistent column; live schema has `started_at`/`completed_at`/`rows_written` only. The hedge ("or the column the 186-05/185 summaries name") is vague since 186-05 names none. The primary `ps aux` gate covers the real check; the named query will just error.
- **LOW (04, Task 3):** Plan says "CLAUDE.md line 159"; the wide-frame rule is at line 157. Trivial, but an instruction pinned to a wrong line number invites an off-target edit; the grep criteria in the acceptance cover it.
- **LOW (04/07, cross-plan):** 186-07 copies the pre-registered cost constants from `scripts/analysis/personal_cost_hurdle_by_tf.py` while 186-04 promotes the same constants into `scripts/research/cost_hurdle.py` in the same wave. Two committed copies of the pre-registered numbers will coexist on main, and only one will get the 186-16-surviving home. Suggest 07 import from `scripts.research.cost_hurdle` if 186-04 has merged by its Task 1, or a one-line repoint in 07's Task 3.
- **LOW (05, Task 2):** The per-table D-08 grep scopes docs to `docs/operations` + `docs/foundation`, so `docs/plans/archive/2026-06-26-drift-detection-architecture.md`'s `drift_monitor` mentions never enter the record. Harmless (archived), but the D-08 claim is "repo-wide"; note the exclusion in the summary.
- **LOW (06):** Identity includes `apr_hash`, so an APR value change mid-rebuild makes a resumed unit hit a loud target-PK conflict instead of a skip. Deliberate and disclosed, but 186-25's resume story should state that APR keys are frozen for the build duration.

### Suggestions

- 07: replace the vacuous grep with `grep -c "445" .planning/STATE.md` plus an assertion that a `Rebuild timeframes:` pointer exists in STATE.md, mirroring the todo's parseable-line device.
- 05/06/09: add one sentence to each migration task: "if another wave-1 plan consumed the number between check and apply, take the next free number and rename before applying" (the uniqueness test then stays a backstop, not the only guard).
- 17: add to Task 2's gate a note naming the expected deferral (449 through ~mid-Oct) and the intended restart window, so the executor does not interpret repeated refusals as plan failure.
- 06: one line in the context/contract block: "`replace_where` and `kernel_code_key()`/`bar_content_digests()` are 186-14 extensions; do not build them here."
- 03: none needed; the plan is executable as written.

### Risk assessment

**LOW-MEDIUM.** No HIGH findings: nothing here would cause data loss, a silent wrong answer, or a broken invariant if executed as written. The DB-touching plans (05, 06) have genuine pre-apply gates, dry-runs, same-commit-apply rules, and rollback paths; 17's restart is the riskiest single action in the set and its gate is real, with the caveat that scheduling (not safety) is the open problem. All concerns are resolvable with one-line plan edits.

### Cross-plan checks

- Binding names verified against the outline: `scripts/research/determinism/` (03), `scripts/research/date_panel.py`/`cost_hurdle.py`/`feature_matrix.py` and `scripts/infrastructure/instrument_compute_eligibility_audit.py` (04), `provenance_batch`, `bulk_load()`, `BulkLoadSpec`, `completed_provenance_batch()`, synchronous psycopg with `asyncio.to_thread` for async callers (06) all match. `bulk_load(replace_where=)`, `kernel_code_key()`, `bar_content_digests()` do not appear in 06 (see MEDIUM above; they belong to 186-14, which I did not review).
- Wave ordering holds: 186-17 depends on 186-05 and consumes exactly the names 05's Task 3 defines (`parse_compose_command_settings`, `compare_settings`, `--out` JSON); 186-16's gate reads 186-03's recorded bit-identical result, which 03's Task 3 summary explicitly records.
- 05's post-run no-PK acceptance (exactly `ctx_events, feature_ic_scores_history, market_data_ohlcv`) is consistent with 186-11 (wave 2) and 186-22 (wave 6) landing later.
- Concurrent-edit friction: 186-06 and 186-07 both edit PRIORITIES.md (including the same build-lane row text) in wave 1; the link-integrity test is the backstop, but the second merger should expect a conflict there.

## Owner-run external review — Grok 4.7 (high)

**Plans:** all 29 (contract level; load-bearing plans 06, 10, 14, 20, 23, 25, 26, 27, 28, 29 task-audited). Source: `186-REVIEW-GROK.md` (verbatim below).

> This session had already seen the R1 section and most of R2 in `186-REVIEWS.md` before this review. R3-R6 were not read. Findings below were re-checked against the plan files.

### Summary

The 29 plans will deliver the phase goal if executed as their task text is written: summary cards before drops, the old chain deleted after consumer greps, a fresh IC engine beside the old one with parity before any purge, and a gated append-only `feature_vectors` rebuild that refuses to start until 185's derived grid, the todo 445 decision, the drops, and bar coverage are actually present. Locked decisions D-01 through D-38 and resolutions R-01 through R-13 each appear in at least one plan's `requirements`. Deferred work (phase 187 UCR / `book_memory()`, phase 188 forward runner, nightly temporal-integrity jobs, todo 443) is not pulled in. The dependency graph is acyclic and every wave number is one past the latest dependency wave. No finding here invalidates a plan. The residual risk is an executor following a must-have sentence instead of the SQL next to it, and schedule coupling that can hold the rebuild behind work it does not computationally need.

### Strengths

- D-02 is operational, not a slogan. Plans that touch code assert `git diff --stat` empty on `src/intelligence/research/`. The one sanctioned edit is `186-29`, and it stops unless STATE.md shows the research lane released or the five tests have already dropped the sleeve import.
- Strangler order is real. `186-10` is pure and does not enter `ic_engine`'s import closure. `186-14` writes through the new engine and leaves `services/ic_engine.py` byte-unchanged. `186-20` commits the parity report before any delete. `186-23` refuses to delete `forward_return_writer` until that report is on main and phase 185 D-14 has moved the bar flags.
- D-19 is closed by the end of the phase, not by a silent keep. `186-20` deletes only `NOT is_pooled` rows. `186-28` requires the whole-table count of `training_window_end >= oos_start` to be 0 after the legacy-scope delete, and the delete script refuses when fresh rows are absent.
- `186-14` does not assume `replace_where` already exists. `186-06` never mentions it (append-only). `186-14` adds the keyword, requires the existing bulk-load tests to pass unchanged when it is omitted, and uses it for atomic unit replacement.
- Rebuild gates match D-32 / R-09 / R-13. `186-26` launches nothing until `186-25`'s checker passes, reads coverage instead of starting an IBKR job, and will not run while a rebuild it does not own is live. Drops (`186-22`, `186-23`) are dependencies, so the ~61 GB lands before the multiday write.
- `186-27` states the drift sample and the 5% unexplained-diff stop before any measurement, and it refuses to swap a run that is still resumable.

### Concerns

- **MEDIUM — `186-20` must-have overstates the purge predicate.** The must-have says the D-19 purge is rows whose target window ends at or after `oos_start`. The task SQL is `DELETE ... WHERE NOT is_pooled AND training_window_end >= oos_start`, and the same plan records that every stored row, pooled included, has `training_window_end` equal to `oos_start` (10,616,092 rows). An executor who "corrects" the SQL to match the must-have parenthetical deletes the 1,301,353 pooled rows that `186-23` still expects to find and that `186-28` is supposed to replace. The action text, the dry-run, and threat T-186-20-02 already forbid that. The must-have sentence is the hazard.
- **MEDIUM — migration numbers 380+ are claimed by phase 185 and by several wave-1 plans here.** `186-05`, `186-06`, and `186-09` all describe the next migration as 380 if nothing has landed since 379. Phase 185's plans already name 380 through 392. Each 186 plan says to re-check `ls production/migrations` at write time, which is the right rule, and it is still a check-then-apply race across parallel worktrees and the 185 session. Failure mode is a duplicate number and a CI break, not a bad drop.
- **MEDIUM — `186-26` wall-clock is easy to mis-scale.** `186-25` pins path-dependent kernels to a fetch from series start for every calendar-year unit. A pilot of an early year therefore understates a 2024 unit, and multiplying "seconds per unit-year" by the unit count double-counts history that every unit recomputes. The plan re-measures at runtime and is resumable, so this does not threaten correctness. It does threaten the "expected wall-clock" the operator will use to decide whether to launch.
- **MEDIUM — the rebuild waits on `186-23`, which waits on phase 185 D-14.** D-32's precondition is the derived 15m/1h grid, todo 445, coverage, and disk after the drops. D-14 (bar flags off `forward_return_writer`) is a precondition of the deletion, and `186-26` depends on that deletion. That is coherent for the 14 GB `forward_returns` drop (R-09) and it is also a schedule coupling: a stalled 185 D-14 holds the rebuild even after D2b has landed. The stop is safe. It should be explicit in `186-26`'s blocked message so it is not treated as a checker bug.
- **LOW — `186-06` versus the outline's `bulk_load(replace_where=)`.** The outline lists `replace_where` as part of the bulk-load binding name. `186-06` implements append-only COPY and says PK conflicts are loud. `186-14` is where the keyword is added. An executor of `186-06` who treats the outline as the contract could build the option early and fight `186-14`'s tests. The plan text of `186-14` is the one to follow.
- **LOW — `186-20` calls the non-pooled delete "the D-19 purge" while D-19's pooled half waits for `186-28`.** The split is disclosed in the task (todo 439 stays open; pooled rows are replaced later). The phase still delivers D-19, at plan 28, not at plan 20.

### Suggestions

- In `186-20`, change the must-have to the predicate that is actually executed: non-pooled rows with `training_window_end >= oos_start`, pooled rows untouched, whole-table D-19 closed in `186-28`.
- In `186-05`, `186-06`, and `186-09`, one sentence: phase 185 may already have consumed 380-392; take the next free number after the file exists and again immediately before `psql -f`.
- In `186-26` Task 1, name the blocked reasons separately (449 coverage, 185 D2b marker, 185 D-14 via `186-23`, disk guard) and pick the pilot unit-year explicitly (one early year and one late year) before extrapolating.
- In `186-06`'s context block, one line: `replace_where` is `186-14`'s extension; do not add it here.

### Risk assessment

**LOW-to-MEDIUM. No HIGH.** Nothing in the plans, executed as the task text is written, drops a kept table, edits the research package while the lane owns it, or starts the rebuild on a partial bar history. The irreversible steps (IC shrink, `forward_returns` drop, `feature_vectors` swap) each have a prior committed artifact and a refuse-and-stop gate. The MEDIUM items are misread predicates and scheduling, and each has a one-line fix.

### Cross-plan checks

- **Coverage.** Every D-01..D-38 and R-01..R-13 is in some plan's `requirements`. Deferred ideas from CONTEXT are absent from those fields.
- **Waves.** `depends_on` edges match the outline. Wave assignment is `max(dependency wave) + 1` for all 29. Plan numbers are not wave order (`186-17` is wave 2, `186-12` is wave 2, `186-29` is wave 4); the outline says IDs are stable and not execution order.
- **Card before drop.** `186-01` / `186-02` precede `186-11`, `186-16`, `186-22`, `186-23`, and `186-27`. `DROP_TABLES` in `186-01` names the D-14 tables plus `ctx_events`, `ctx_snapshots`, `construction_spreads`, `alpha_strategy_scores`, `forward_returns`, and `feature_vectors`.
- **Parity before purge before delete.** `186-20` Task 2 commits the report; Task 3 refuses without it. `186-23` refuses without that report and without 185 D-14. `186-28` refuses to delete legacy scopes until fresh rows and completed provenance exist.
- **`replace_where` handoff.** Absent from `186-06`. Specified, tested, and consumed in `186-14`. `186-25` and `186-28` call the landed signature.
- **Research lane.** No plan other than `186-29` edits `src/intelligence/research/` or the five HarnessConfig tests. `186-29` is wave 4, depends only on `186-16`, and is not on the rebuild's dependency path, so a held lane does not block the rebuild.
- **185 boundary.** `186-26` reads 185's D2b marker and does not start IBKR jobs (R-13). `186-23` reads 185 D-14 and does not implement it.

### Council pass (data integrity, one clock, one statistic)

Applied after the consistency pass, against `docs/foundation/principles.md`: one direction of flow, one meaning per column, failures loud, complexity deleted before it is optimized. The consistency pass found no HIGH. This pass does. The plans are executable. Two designs will write a silent wrong answer if left as specified.

#### What already matches the standard

Raw bars stay. Derived tables are cache and are dropped only after a card. The research package is not edited while another lane owns it. The rebuild compresses per chunk and does not decompress `feature_vectors` in place (the failure mode of todo 426). The causality probe in `186-08` fails a kernel that normalizes over its full input, and once `186-12` registers kernels that test is no longer an empty parameter set. Those are the right instincts. Do not reopen the drops.

#### Defect 1 — one column, two clocks

`186-14` states the choice in prose: fresh rows store `training_window_end` as the latest target exit, always before `oos_start`; legacy rows store the same column as the window bound, and every one of the 10,616,092 live rows sits exactly on `oos_start`. Both populations share `feature_ic_scores` from `186-14` until `186-28`, which is after the rebuild and the name swap.

`training_window_end` is the hypertable time column. A reader who filters `training_window_end < oos_start` sees only the fresh scope. A reader who filters `>= oos_start` sees only the legacy scope, whose targets touch the forward span. `feature_lifecycle` and any ad hoc IC query that does not also filter `regime_scope` mixes or drops a population with no error. The integration test in `186-14` even seeds a legacy row and asserts it survives a fresh write. That is coexistence by design.

The phase already has the pattern that removes this: `feature_vectors_v2`, write, prove, swap, drop. Fresh IC rows belong in a new table with one clock. The legacy table stays untouched until `186-28` deletes it. `replace_where` against a mixed table, and a write session that decompresses the legacy population in order to append a different population, both go away. `186-20`'s must-have hazard (purge predicate wider than its SQL) is the same defect showing up as an instruction bug.

#### Defect 2 — parity certifies a function the writer does not run

`186-20` replays stored cell masks through the IC function, once with table targets and once with kernel targets. That is the right test of the rank statistic. It is not a test of `services/ic_measure.py`.

The writer, in `186-14`, builds S0 panels with `end_exclusive = oos_start`, stacks symbol chunks, aligns features, and chooses stride from APR. The parity harness feeds the stored observation set. R-06 is explicit that no stored cell has an exact kernel counterpart, so nothing in the plan requires those two assemblies to match. The `186-14` integration test checks that a hand-built predictive column gets a positive IC on 8 symbols. A sign check is not parity.

`186-23` then deletes the old engine and `forward_returns`. `186-27` drops the old feature table. `186-28` is the first time the production assembly writes the numbers anyone will read. If chunk stacking or `align_features` shifts a target by one bar, the result is a clean table of the wrong statistic, and the artifact that could have caught it has already been dropped. Raw bars can rebuild features. They cannot tell you the new IC matches the old one.

The missing gate is small: one frozen cell, production path only (`build_target_panels` -> `align_features` -> the same IC function the harness uses), compared to the harness output on that cell, committed before `186-23`. Same function, two callers, one expected number. If they differ, stop.

#### Defect 3 — provenance records two recipes for one row

D-24 says a rerun of the same key is a no-op. `186-14` case 3 expects a changed bar to replace the data rows and leave **two** `completed` provenance rows for the unit. Both keys claim the current rows. A later resume that recomputes the old digest finds the old key completed and skips, leaving the new rows in place under the old recipe. Lineage is the invariant that makes a result auditable. A log of attempts is not the identity of the stored batch. On replace, the previous key has to stop meaning "these rows." Mark it superseded in the same transaction as the delete-and-COPY, or the record is a lie.

#### Complexity to delete, not tune

`186-25` fetches from series start for every calendar-year unit because the kernel set contains path-dependent kernels. Declared memory was built in `186-08` so a unit can fetch its warmup and nothing else. One expanding kernel, if any exists, should be named and either given an explicit expanding memory or removed. Three hundred columns should not recompute twenty years because one of them might need to. The `186-26` pilot will measure that cost and then treat it as a property of the machine. It is a property of the decision.

`replace_where` on the append-only primitive exists to edit a mixed table in place. Defect 1 removes the need. An append-only `COPY` whose conflict is loud is the whole primitive.

The sync `asyncio.run` around `build_target_panels` is not the defect. This is a batch job whose contract is a deterministic `COPY`. Making it async would add a second runtime for the same numbers.

#### What Simons would require before execution

1. Fresh IC writes a new table. One meaning of `training_window_end`. Legacy rows are not neighbors of fresh rows.
2. One committed cell where the writer path and the parity harness agree, before any drop.
3. A replaced batch has one completed provenance row.
4. Rebuild warmup is `max(declared memory)` over the registry actually used, measured, not "from the first bar."

None of these add a stage. They delete a coexistence protocol, a second statistic, and a full-history refetch. The rest of the phase can run as written.

---

## R3 Review — Claude Opus (fresh context)

**Plans:** 186-08, 186-12, 186-13, 186-15, 186-18 (kernel-registry track)

### Summary

This is an unusually well-evidenced plan set. I verified dozens of factual claims against the repo and database and almost all were exactly right: every line-number claim I checked (feature_factory 8733 lines, `FeatureFactoryConfig` :424, `compute_batch` :7347, `_momentum_z_series_full` :2154, `_canary_acausal_placebo` :1959 reading `closes[i+1]/[i+2]`, regime_writer 2640 lines with the full-history `_compute_symbol_tf` at :1568 and dispatch at :2173, `_ColumnFamily` :110, `_cross_asset_record_for_date` :401/:1550, cross_asset_series `bisect_right` :161) matched. The config_history claim (walk_forward.enabled=true, 2026-08-12, "todo 248", user-approved) is verbatim in the DB, and the 186-18 "live APR today" block matches `config_state` exactly. The todo 420 weekend-orphan count (1,223,265) matches a live read-only count exactly. The 186-12 same-day macro lookahead is real at feature_factory.py:7734/7758 with cross_asset_series.py:161, and todo 450 describes precisely what task 3 fixes, at the right place. The byte-identical parity design is genuinely hermetic (inputs AND outputs frozen in npz; the parity test never reads the DB), would catch 1-ulp float32 drift (canonicalized little-endian digests + `array_equal(equal_nan=True)`), and every plan requires a recorded mutation check proving the test bites. Failure paths (behavior change = own commit; golden regeneration = further separate commit with a changed-column whitelist and stop-on-unexpected-diff) are consistently defined. Live-run check: no ic_engine/backfill_feature_factory/regime_writer process is running; the todo 449 IBKR lane IS live, and no plan starts an IBKR job or writes the DB.

### Strengths

- Parity fixtures pin both inputs and outputs, so later plans recompute offline; capture runs twice and refuses nondeterminism (186-08 task 3b).
- Commit taxonomy is rigorous: code-only moves leave fixtures untouched (asserted via `git show --stat` and `git log` acceptance criteria); behavior fixes are separate with RED tests recorded before the fix.
- 186-13 verifies todo 248 from three independent sources before touching planning docs, and STATE.md edits follow the "plain replacement, no CORRECTED block" rule. This matters: todo 292's blast-radius section still claims `walk_forward.enabled = false` (written 2026-08-09, nine days stale), so the verify-first task is load-bearing, not ceremony.
- 186-18 task 3 step 4 encodes the outline's binding ordering note exactly (cleanup runs only if J=0 or 186-20-SUMMARY.md exists on main; otherwise defers with todo 420 left pending), and never recomputes regime into the current `feature_vectors`; the todo 426 guard is explicitly untouched and the writer is never run against the DB.
- DAG invariants hold: the pipeline's D-28 change is a startup validation + shared lookup rule only, no self-persistence; sweep workers are compute-only with bars fetched in main; worker-args become a NamedTuple (todo 291 item 4).
- 186-15's CTF availability tests are written before the move against the unchanged code, with a real-data perturbation variant, and an explicit no-fix/fix branch; the documented CTF-vs-macro availability asymmetry is correctly left alone.
- None handling (`_guard`'s None vs non-finite distinction) is traced per column rather than hand-waved.

### Concerns

- **MEDIUM — Todo 450 is never referenced in 186-12's body, and todo 451 never in 186-13's**, yet the outline binds both ("450 ... fixed in 186-12 task 3"; "451 ... 186-13 task 2") and each todo names the plan in its Fix section. Neither plan closes, moves, or appends to the todo; 186-12's caveat trace says "file a todo" with no pointer to the existing one, inviting a duplicate P0. Evidence: `grep 450 .planning/phases/.../186-12-PLAN.md` (no hit); todo files exist in `pending/`. Failure mode: fixed P0/P1 todos sit open in `pending/` after the fixes land, and the todo-file linkage the phase relies on goes stale.
- **MEDIUM — Deferred `market_regimes` cleanup ownership is inconsistent.** Todo 420's "Deferred rerun owner (2026-09-27)" says the rerun is "owned by the 186-28 executor, run after the feature_vectors swap"; 186-18's deferral message says "rerun ... after 186-20 merges". Nothing in the outline's 186-20 or 186-28 scope paragraphs mentions running `cross_sectional_regime_model --accept-orphan-delete`. Failure mode: the orphan delete (1.22M rows) falls between two plans that each believe the other owns it. The todo stays pending so it is not lost, but the executor instructions contradict.
- **MEDIUM — Dead-import window for `scripts/analysis/` pilots.** 18 files there reference regime_writer and at least two import from it (`hmm_walk_forward_seed_stability_pilot.py:49`, `hmm_n_restarts_walk_forward_comparison_pilot.py:67`) functions 186-13 (wave 3) deletes, while 186-16 (also wave 3, deps only on 01-04) deletes the directory. The outline's stated ordering intent is "scripts/analysis is deleted before the old-chain services so its scripts never sit on dead imports"; 186-13 breaks that intent within its own wave. Mitigated (nothing live imports them; 186-13 records them as superseded), but wave-3 execution order is unspecified.
- **MEDIUM — Gate breadth vs the live todo 449 IBKR lane.** All five gates check `ps aux` for ic_engine/backfill/regime_writer/rebuild and STATE.md's lane table; none checks or even records the IBKR backfill lane except 186-08's passive "record whether IBKR writers were active during capture". Risk is bounded — every DB access in these plans is read-only against `market_data_ohlcv_tradeable` and no plan opens an IBKR client — but 186-18 task 2's sweep (up to ~931 symbols x 4 tf x 3 schedules x 2 families, estimated up to 3 h) runs unbounded CPU/IO against the same host and TimescaleDB while the backfill lane writes and wave-4 plans (186-15, 186-19, 186-20) execute concurrently. No plan states cross-plan CPU contention as a consideration for that sweep.
- **LOW — Stale wave text:** 186-13's context says "186-15 (wave 3)"; 186-15's objective says "the outline row puts this plan in wave 3"; the outline table says wave 4 (matching both frontmatters). Depends_on makes real order unambiguous, but an executor reading prose could parallelize 13 and 15, which both edit feature_factory/backfill/tests.
- **LOW — 186-08 task 3's "1m coverage is 2026-03-23 to 2026-06-23" is stale:** live max is 2026-09-26 (`SELECT max(timestamp) ... timeframe='1m'`). The chosen windows (ending before 2026-06-20) remain inside coverage, so no execution impact.
- **LOW — 186-08 does not state explicitly that `real_inputs.npz` must also store the cross-asset helper series (SHY/TIP/HYG/LQD 1d)** the real-case reference rebuilds `cross_asset_by_date` from; "stored ... 1d bars" is ambiguous between DB and npz. If it means DB, the parity test is not hermetic and later plans' parity silently depends on live table state.
- **LOW — 186-13 has no branch for todo 451's "if the RED tests do not fail, close as not a bug" case;** task 2 assumes the RED tests fail (the source reading strongly suggests they will, and 451 itself marks it "not yet proven").

### Suggestions

- Add one line each to 186-12 task 3 and 186-13 task 2: after the fix commit, append a dated note to todos 450/451 (and PRIORITIES.md if disposition changes), rather than leaving their lifecycle to nobody.
- Reconcile the 420 rerun owner: either 186-18's deferral message should name the 186-28 executor and the post-swap timing (matching the todo), or 186-28's plan should be amended; today they disagree.
- State in 186-08 task 3a that `real_inputs.npz` includes the six cross-asset 1d helper series per case so the test never touches the DB.
- Add to 186-18 task 2 step 4: record that the todo 449 IBKR lane is live during the sweep and cap `--workers` with a stated headroom, so the sweep cannot starve the nightly lanes.
- Fix the two stale wave mentions (186-13 context, 186-15 objective) to "wave 4".

### Risk assessment

LOW-to-MEDIUM. The plans' factual grounding is the best I have measured in this phase: every checkable claim I tested was true, the parity/probe/golden machinery is real and provably bites, and the dangerous operations (regime UPDATE path, corpus recompute, market_regimes cleanup) are correctly gated or deferred. Residual risk is confined to todo-lifecycle bookkeeping (450/451), the 420 rerun ownership gap, and wave-3/4 execution-order prose — all rework-class, none data-loss or silent-wrong-answer class.

### Cross-plan checks

- Binding names match the outline everywhere I checked: `registry.py`, auto-discovered `KERNELS`, `path_dependent`/`memory_atol`/`acausal_control`/`compute_kernels()` (186-08/12/13/15 progressively, each extending with defaulted fields so prior tests stay green), `UNOWNED_COLUMNS` placed in `registry.py` by 186-15 task 3 as the outline states, `ExternalInput` `symbol` (control.py) and `tf` (regime.py) declared once with the duplicate-name refusal.
- Fixture handoff is coherent: 186-12 regenerates `kernel_parity/` (commit C) and 186-15 consumes "as regenerated by 186-12"; 186-13's acceptance asserts `kernel_parity/` untouched; `regime_kernel/` has its own directory and regeneration chain with 186-18 preserving 186-13's records in a list.
- Wave/dependency graph is consistent with the outline (08→12→13→{15,18}); 186-15's stated dependency reason for 186-13 (the `tf` external, shared files) is real.
- 186-18's interfaces block restates 186-13's planned names and explicitly instructs "where they differ from this plan, follow the merged code" — the right posture given `_build_obs_matrix`'s signature claim I did not independently confirm post-move.
- The 286→186-26 handoff is honest: stored-column defects (obs warmup artifact, stale churn, intraday macro lookahead, label-mask lookahead) are recorded as known defects on the old-table card / todos rather than recomputed in place, matching the todo triage and the rebuild design.

## R4 Review — Claude Opus (fresh context, desk-standard lens)

**Plans:** 186-09, 186-10, 186-14, 186-20, 186-28 (measurement track)

### Summary

These five plans form a coherent measurement track: the lifecycle shrink (09), the pure measure package (10), the ic_measure writer with the scope-key migration (14), the parity-then-purge plan (20), and the fresh-IC replacement run (28). I verified the load-bearing repo and database claims live: feature_lifecycle.py really contains the IC gates, the `ensemble_weights` join and the `alpha.ensemble.*`/`alpha.decay.*` reads plan 09 removes; the three lifecycle metrics exist at `src/observability/metrics.py:1262-1274` with no other emitter; migration 311 and the D-31 targets (verify script, `schemas.py:1535` comment, ROADMAP line 67, design line 730) all exist; `ic_math.py` has every function plan 10 imports; `snapshot.build_panel` refuses past `oos_start` (`snapshot.py:241`) and reads only the tradeable view; the feature_ic_scores schema, PK, three partial unique indexes, CHECK, policy job and every row count (10,616,092 total; 9,314,739 non-pooled split 5,540,805/2,188,440/1,585,494; 1,301,353 pooled split 971,073/210,600/119,680; all `training_window_end = 2025-12-24 05:15+00`; stored pooled cross_sectional lookaheads exactly {5m 6,12,39; 15m 2,5,10; 1h 1,2,20,60; 1d 1,2,10}) match the plans' cited facts; `regime_label -> regime_group` uniqueness holds live; `scale_stride = max(subsample_min_stride, lookahead)` with stride-slice-before-mask is confirmed at `services/ic_engine.py:2404-2430`; todos 391 (completed), 412 and 439 read as the plans claim; and plan 14's evidence-based deviation on `_AGENT_ID_TO_UNIT`/`alert.lag.*` is sound (BaseBatch is a separate abc from BaseDaemon; ic-engine/feature-lifecycle carry no lag entry). The set is strong. Three findings stand out: plan 14 has an undeclared, ungated cross-phase dependency on phase 185's bar-digest view, which does not exist today; plan 28 does not own the market_regimes orphan rerun that todo 420 explicitly assigns to "the 186-28 executor"; and nothing compares the fresh numbers against the legacy rows they replace even though the two populations coexist while 186-28 task 2 runs.

### Strengths

- Plan 10's D-19-by-construction design is correct and verified: `forward_returns` (panel.py:93-134) NaNs the last 1+h rows, refuses cross-session intraday targets via `session`, and `build_target_panels` double-guards at oos_start.
- Plans 10 and 20 pin the exact stride/mask order against `_compute_one_cross_sectional_cell` and the live code confirms the pinned order (stride slice precedes the complete/finite mask, ic_engine 2404-2430), so the parity failure mode is loud, not silent.
- Plan 14's key-change migration is the careful version: scratch-hypertable rehearsal, row count plus `hashtext` checksum before/after, headroom check, recompress, bare VACUUM, policy rescheduled, ON CONFLICT consequence stated; todo 391's silent-collision failure mode is correctly closed by scope in the PK.
- Plan 20's ordering is right and enforced: parity report committed before any delete (R-06), D-19 purge before the old-grid delete, both `NOT is_pooled`-scoped, dry-first, batched, counted separately, SOP + VACUUM.
- Plan 09 defines the coverage statistic once outside the research package with an APR floor, removes the last `ensemble_weights` reader before 186-22's drop (R-03 honored), and keeps a dry-run-only posture on the live DB.
- 186-28's delete is properly gated on 186-27's drift report, fresh-coverage-completeness, and all-provenance-completed, and it explicitly records that per-symbol pooled and earnings_season rows get no fresh counterpart.

### Concerns

- **HIGH — 186-14 depends on phase 185-11's `bar_content_digest` table / `bar_content_digest_current` view (migration 383) without declaring it:** `depends_on: [186-06, 186-10, 186-11]`, no precondition task. Verified live: `to_regclass('bar_content_digest'), to_regclass('bar_content_digest_current')` both empty; `ls production/migrations | grep ^38` empty; the view exists only in 185-11's plan text. Failure mode: task 2 (`services/_batch_utils.py` behavior bullet at 186-14 line 346) is unimplementable as written; an executor improvising would read `market_data_ohlcv` raw, tripping the boundary allow-list. Add a gate: refuse until `to_regclass('bar_content_digest_current')` is non-null, pointing at 185-11.
- **HIGH — the todo 420 market_regimes orphan rerun has no owner.** Todo 420's "Deferred rerun owner (2026-09-27, plan-phase)" note says "owned by the 186-28 executor", and 186-18 task 3 stops with a deferral message when J>0; but 186-28 (grep of its text for orphan/regime_model/420: no task) never schedules `cross_sectional_regime_model --accept-orphan-delete`, and the outline (line 328) instead says "186-18 task 3 cleans market_regimes orphans only after 186-20's parity summary is on main" — three documents, three attributions, zero plans owning it. Failure mode: the rerun silently never happens; stale weekday-orphan labels that join feature rows persist into the rebuild's regime kernel inputs (R-10) and are baked into the fresh feature_vectors and then into the fresh IC rows 186-28 writes. Also note the todo's stated timing ("after the feature_vectors swap") may itself be too late, since the rebuild consumes regime inputs before the swap. Fix: add an explicit 186-28 task (or an explicit 186-18 follow-up task) that runs the rerun, records per-group/tf counts, and closes or re-routes todo 420.
- **MEDIUM — no comparison of replaced numbers before the old ones are gone.** Plan 20 proves the IC statistic machinery on stored cells; it does not and cannot prove the fresh proposer's unstratified cells, whose observation set (all valid rows) is a different population; 186-20's report "conclusion the proposer's unstratified pooled cell is justified per R-06" is asserted, not demonstrated. At 186-28 task 2 both populations coexist in the table, so a free, independent check is available and not taken: record fresh unstratified IC vs legacy cross_sectional IC for matched (feature, tf, horizon) as a disclosure (differences expected from the population change; the value is detecting gross errors, e.g. sign flips or scale errors from a misaligned label join). After task 3 runs, the artifact that could have disproven the fresh numbers is deleted.
- **MEDIUM — 186-14 line 375 asserts "185-11's migration 383 stores it ... and names this phase as its consumer" as a live fact, with no re-check.** Same root as the first HIGH; list it in the gate task explicitly.
- **MEDIUM — 186-14 Task 1's pg_stat_activity gate filters `query ILIKE '%feature_ic_scores%'` only;** it does not cover readers of `feature_vectors`/`forward_returns` (the parity/replay reads in 186-20 do filter feature_vectors — 186-28 does). The 9.3M-row delete contends with any long feature_vectors reader only through locks on feature_ic_scores, so this is minor; noting for completeness.
- **LOW — 186-10 Task 2 leaves `align_features` in "ic.py or proposer.py (executor's choice, documented)" while 186-14's context and 186-20's interfaces both cite `measure.ic.align_features`.** A wrong choice lands a one-line import fix later; pin it to ic.py.
- **LOW — 186-09 adds a new file under `src/intelligence/statistics/`; CLAUDE.md's repro_frozen rule reads "after any edit under src/intelligence/research/ or src/intelligence/statistics/".** The new module is not in ic_engine's import closure so the frozen verdicts cannot move, but the plan should say so (or just run `scripts/analysis/sleeve_walk_forward/repro_frozen.py` once, it is cheap) instead of leaving the rule's scope argued implicitly. Note 186-09 executes in wave 1, before 186-16 deletes the sleeve directory, so the script is still present.
- **LOW — 186-09's acceptance grep also counts docs hits only as a list; make the expected old-chain hit list (ensemble_trainer.py, ops_ic_shrinkage.py, orchestrator) an explicit allowed-hits list** to keep the executor from "fixing" them early.
- **LOW — 186-28 context states "feature_vectors is the rebuilt 310-column table" as fact;** the rebuilt column count is 186-24's to decide and could differ. Harmless (nothing keys on the number), but state it as the actually measured count at task 1.

### Suggestions

- 186-14: add to Task 1's gate: `select to_regclass('bar_content_digest_current') is null` -> stop with "blocked: 185-11 not landed". Optionally seed a fallback: if 185-11 slips, define the digest directly over the tradeable view with an explicit, planned boundary-test allow-list entry instead of improvising.
- 186-28: add a task-2 evidence field comparing fresh vs legacy pooled IC at matched keys, and add the todo 420 rerun task (or state in the plan why 186-18 task 3 owns it and make 186-18's deferral path re-enter its own step 4 after 186-20 merges).
- 186-28 task 2: also record `max(training_window_end)` per (scope, tf) against `alpha.ic_measure.horizons`' horizon (exit bar = last bar + 1 + h), a cheap shape check that the stored `training_window_end` really is the exit bar.
- 186-20: in the parity report, also record the peer-symbol set source (market_regimes + alpha.regime.groups config, confirmed live, 10 alpha.regime.* keys present) and note that `alpha.regime.groups` must survive 186-21's APR deletion, so 186-21 does not delete it by LIKE.
- 186-20: the D-19 purge expected total (9,314,739) makes the second delete a guaranteed no-op by construction (all rows share one training_window_end); keep both counted deletes but the summary can state that up front rather than treating a 0 as an anomaly to investigate.
- 186-09: list the allowed old-chain hits explicitly in the D-08 summary format, and add one sentence to the plan stating why repro_frozen is not required (new module outside ic_engine's import closure).

### Risk assessment

MEDIUM. The track's statistics and deletion paths are unusually well pinned (stride/mask order, counted deletes, provenance identity, gates on completed provenance). The residual risk concentrates in coordination, not computation: an ungated cross-phase dependency (185-11) and an ownerless deferred rerun (todo 420) — both are "silently never happens" failure modes rather than loud ones, which is the class of failure this phase is otherwise designed to prevent.

### Cross-plan checks

- Binding names all resolve: `bulk_load(replace_where=)`, `BulkLoadSpec`, `completed_provenance_batch`, `kernel_code_key`, `bar_content_digests`, `provenance_batch`, `src/intelligence/measure/`, `services/ic_measure.py`, oneshot `indicagent-ic-measure` match the outline's binding-names block (outline lines 323-331). Plan 14's `_AGENT_ID_TO_UNIT`/`alert.lag.*` deviation is explicitly sanctioned by the plan ("outline wording adjusted on evidence") and I confirmed the evidence: BaseBatch is a separate abc (`base_batch.py:38`), no ic-engine/feature-lifecycle lag entries exist.
- Wave ordering holds: 09/10 (wave 1) -> 14 (wave 3, deps 06/10/11) -> 20 (wave 4, dep 14) -> 28 (wave 10, dep 27). 186-18's cleanup-before-parity ordering concern is handled: it defers when J>0 until 186-20's summary is on main — but see the ownerless-rerun HIGH.
- Gate circularity: none. 186-20's purge is gated on parity; 186-23's deletion is gated on 186-20's report; 186-28's delete is gated on fresh coverage plus completed provenance.
- 186-20's parity inputs all verified derivable: label-to-group uniqueness holds live (0 multi-group labels), `forward_returns` columns (`return_fast/mid/slow/extended`, `complete_*`, `has_gap_before_entry`, `return_type`) exist, the `alpha.ic.lookahead.<tf>.<scale>` keys exist today and are unique per tf for the stored lookaheads, and `alpha.regime.groups` (peer routing) exists and is not in 186-21's deletion list.
- 186-10's `align_features` placement ambiguity is the only binding-name-adjacent drift I found; pin it to `measure.ic.align_features` as 186-14 and 186-20 already assume.

## R5 Review — Claude Opus (fresh context, desk-standard lens)

**Plans:** 186-11, 186-19, 186-21, 186-22, 186-23 (old-chain retirement track)

### Summary

This is an unusually well-evidenced plan set. I verified the load-bearing claims live and almost all were exact: ctx tables 0 rows with jobs 1040/1049 and `alert.lag.ctx-writer`=500; `service_auditor.py` old-chain hits exactly at lines 112-116/210-214 with no `_AGENT_ID_TO_UNIT` entries; `ensemble/__init__.py` eager imports and `weighting.py:24-26` submodule imports (R-04); `metrics.py`/`stream_keys.py`/`base_batch.py`/`_batch_utils.py` all confirmed inside `services.ic_engine`'s import closure by importing it; orchestrator banner `Step %d/8` with steps 6-8 and the WEIGHT_EPOCH block; monitor's `/6` mismatch; verifier Check 6 and recovery branches; `REQUIRED_STEPS = ["ic_engine", "ensemble_trainer", "alpha_publisher"]`; APR keeps at `tag_calibrator.py:1254`, `ic_engine.py:839-841`, `feature_factory.py:749`; exactly 20 `alpha.ic.lookahead.*` keys; `feature_ic_scores` = 10,616,092 rows; the four 186-23 ops scripts do read `forward_returns` (via `JOIN`, which the plan's "real SQL hit" rule covers). The one clear factual error is in 186-22's TimescaleDB job-id claims, plus a vacuous gate, a session-specific path baked into 186-19's verify, and two post-drop surfaces no plan owns.

### Strengths

- Guarded drop migrations (in-transaction reader guards, no `IF EXISTS`/`CASCADE`), applied-then-committed-in-the-same-commit, per-key APR deletes never LIKE, keeps re-counted post-apply — the desk standard is met nearly everywhere.
- D-01 gates checked against the live environment: none of the five plans' `ps aux` patterns match the running todo 449 lane (`infrastructure_run_historical_pipeline.py --client-id 46` verified live), the `pg_stat_activity` guards use table-name ILIKE patterns that lane never emits, and no plan starts IBKR work. No false stops, no contention.
- R-04 is handled with real proof obligations (sys.modules check, byte-unchanged diff on `weights.py`/`covariance.py`, post-merge three-line bit-identity run, revert-before-push on failure).
- 186-23 honestly documents the strangler window where old ic_engine becomes non-runnable between 186-22 and 186-23, and gates the whole deletion on the committed 186-20 parity report including the writer-path cell and 185 D-14.
- Hand-off chain 19→21→22→23 is explicit and I found no name mismatches against the outline's binding names.

### Concerns

- **HIGH — 186-22 (must_haves truth, interfaces, Task 3 verify): the compression job-id claim is factually wrong.** The plan asserts jobs "1067-1072" cover the six old-chain hypertables and names "alpha_ensemble_ic (1071)". Live: `SELECT job_id, proc_name, hypertable_name FROM timescaledb_information.jobs` shows **1071 = policy_compression on `feature_ic_scores`** (a D-15-protected table 186-28 drops later), and **`alpha_ensemble_ic` has no compression job at all** (0 chunks). Old-chain jobs are 1067, 1068, 1069, 1070, 1072 (+retention 1073). An executor running the Task 3 verification as parenthesized ("job_id IN (1067-1072, 1073) is 0") gets a spurious failure on job 1071, and the wrong resolution — concluding `feature_ic_scores`' job should have been removed — points at the one survivor table this track must not touch. Task 1's run-time re-record mitigates but does not excuse the must-have.
- **MEDIUM — 186-23 (Task 1 APR classification vs must_haves): `alpha.ic.lookahead.*` has a surviving runtime reader the plan never dispositions.** `src/observability/corpus_manifest_verifier.py:86,126` builds and reads `alpha.ic.lookahead.{tf}.{scale}` from `config_state` at runtime (verified). The plan's own KEEP rule ("a runtime reader in a surviving module") therefore classifies all 20 keys KEEP, contradicting the must-have that all 20 retire. Retirement is numerically safe today (the verifier's hardcoded mirror equals the APR values, verified bytewise) but the change permanently converts a documented "falls back when keys are absent" path into the only path — a silent fallback in a Ring 0 module, exactly the pattern this phase is deleting. The D-08 prefix grep will surface the file; the plan gives the executor no disposition for it.
- **MEDIUM — 186-22 (Task 1 verify): a gate that cannot fail.** The automated verify runs bare `psql -U postgres -h localhost ...` with no `PGPASSWORD`; on this host that fails with `fe_sendauth` (no `~/.pgpass`, verified), producing empty output, so `test -z "$(...)"` passes vacuously even with a live reader session. Every other psql in the set sets `PGPASSWORD`; this one is the reader-safety gate.
- **MEDIUM — 186-19 (Task 3 verify): session-specific scratchpath hardcoded.** The automated verify ends `grep -c "bit-identical" /tmp/claude-1000/-home-bg-dev-indicagent/2fd043db-74e6-4e8a-9d9c-c278f1f8b1bf/scratchpad/repro_186_19.log`. That UUID is one session's scratchpad; any other executor fails the critical post-merge bit-identity proof as written, or is tempted to satisfy the literal path.
- **MEDIUM — 186-22/186-23 (cross-plan gap): `infrastructure_truncate_derived_tables.sh:74` (`TRUNCATE forward_returns;`) has no owner after 186-23.** 186-22 edits the script but deliberately leaves the `forward_returns` line (correct at its wave); 186-23's `files_modified` does not include the script, so after the drop the documented recovery/reset script dies mid-run on a missing table. Loud, but it violates the phase's own "nothing live points at dropped tables" end state and D-22's "every script reading the table".
- **MEDIUM — 186-22 (Task 3 step 1): the migration guard omits the row-count-stability and compression-job-running guards that 186-PATTERNS.md (lines 212-214) prescribes for 186 drop migrations and that 186-11 includes.** All writers are deleted and gated, so the probability is low, but the cheap guard is what converts "rows appeared since the card was written" from a silent destruction into a loud refusal.
- **LOW — 186-23 (Task 1 gate 4): hardcodes `feature_ic_scores` count `10,616,092` as the dependency check.** Verified exact today; brittle to any legitimate intervening purge. Equality against the just-recorded count would carry the same protection without the stale-literal risk.
- **LOW — 186-23 (interfaces): `ops_lookahead_horizon_response.py` is pre-listed as a forward_returns table reader but shows no live SQL** (only docstring mentions plus `from services.ic_engine import ...` at line 120). It dies either way via the importer rule; the mislabel just muddies the D-08 record.
- **LOW — 186-19 (Task 3): invokes "ALPHA FIRST" when waiting out a research run.** The owner replaced alpha-first with build-first; the behavior (wait, never stop the run) is right, the label is stale.

### Suggestions

- 186-22: correct the job-id text to "recorded at run time; measured 2026-09-27: 1067/1068/1069/1070/1072 + retention 1073; `alpha_ensemble_ic` currently has none; job 1071 is `feature_ic_scores`' and must survive the migration"; add the row-count guards from the pattern doc.
- 186-22: add `PGPASSWORD=postgres` to the Task 1 verify.
- 186-19: replace the hardcoded scratchpath with "the executor's scratchpad dir; record the resolved path in the summary".
- 186-23: add an explicit disposition for `corpus_manifest_verifier.py`'s lookahead read (reword its fallback comment to state the keys were retired and the mirror is now the source); add the truncate script's `forward_returns` line to its own deletion scope; state that `lookahead_by_scale_from_apr`/`lookaheads_for_tf` in `_batch_utils` go dead here while `LOOKAHEAD_FALLBACKS_BY_TF` stays (`ops_oos_holdout_eval.py:381` uses it); add "feature_lifecycle has zero `lookahead` hits" to gate 4 (it holds only because 186-09 removes the import at `feature_lifecycle.py:64,112` — verified present today).
- 186-22: make the Task 3 verify's `git log --grep` match the migration filename only, not any commit mentioning "186-22".

### Risk assessment

**MEDIUM.** No unmitigated data-loss path: every drop is guarded, loud, and gated on cards plus dependency proofs, and the D-01 discipline is real (verified against the live backfill lane). But one drop plan's must-haves carry a false DB-state claim that points a spurious failure at a protected table, one safety gate is vacuous as written, the flagship deletion plan (186-23) has an unresolved reader contradiction on the keys it retires, and two post-drop surfaces are currently unowned. All are fixable in a doc pass; none should ride into execution as written.

### Cross-plan checks

- Wave/dependency gates verified coherent: 186-19 gates on 186-11's `service_auditor` cleanup and 186-14's `indicagent-ic-measure` registration (both currently absent/present as expected pre-execution); 186-21 gates on 186-19's deleted services; 186-22 gates on 186-21's keeps-count-4; 186-23 gates on 186-22's NULL `to_regclass` probes and the amended 186-20 writer-path parity cell. No circularity.
- Hand-offs match: `cluster_regime_conditioned` (KEEP in 186-21 → retire in 186-23), `REQUIRED_STEPS = ["ic_engine"]` (set 186-21 → held 186-22 → repointed 186-23), `feature_ic_scores` untouched until 186-28 (probed non-NULL in both 186-22 and 186-23). todo 420's orphan rerun is correctly absent from my plans (186-26 Task 1 owns it, per the outline resume note).
- Binding names consistent: `feature_ic_scores_v2`, `services/ic_measure.py`, `indicagent-ic-measure`, `scripts/research/determinism/repro_frozen.py` all used exactly as the outline fixes them.
- Verified the only real importers 186-19 leaves for 186-21 are `ops_ensemble_ablation.py:85` and `ops_oos_gate1_signal_eval.py:63`; `ops_ic_shrinkage.py:75` imports the surviving `ensemble.shrinkage`, not a deleted module, so 186-19's "only two importers" acceptance holds.
- 186-19's `resolve_per_tf` "caller: ensemble_trainer only" is false on today's main (`sleeve_walk_forward/refit.py:37`) but becomes true once 186-16 deletes refit.py and its tests (verified in 186-16-PLAN's delete list); acceptable given the plan's re-grep-at-run-time caveat.

## R6 Review — Claude Opus (fresh context, desk-standard lens)

**Plans:** 186-24, 186-25, 186-26, 186-27 (rebuild track)

### Summary

The rebuild track is unusually well-evidenced: the dropped-column proofs, live facts, and line-number claims in all four plans check out against the live DB and repo (I re-ran them; see Cross-plan checks). The unit/provenance resume design, the stated-before-measuring drift sample, and the completion gate are the right shape. One genuine design flaw sits at the center of 186-25/186-26: per-unit `compress_before` on 1-year hypertable chunks that many units share will trip `bulk_load`'s compressed-chunk refusal on the second unit of every (tf, year) group, killing the multiday run almost immediately. That must be resolved before 186-25 is executed. The remaining findings are execution-ambiguity and honesty-of-gating issues, not silent-wrong-answer risks in the rebuild math itself.

### Strengths

- Counted evidence before DDL: 186-24 proves each dropped column never-computed (I verified: all six non-null counts are 0 on 108,646,010 rows) and `regime_label_source` is the single constant `filtered` (verified). Mismatch paths stop the plan instead of dropping a contradicted column.
- 186-27 states the drift sample (symbols, 2024 window, float32 semantics, 5% attribution bar) before measuring, and commits the report before the drop; unexplained diff classes stop the swap. This is the correct answer to "last chance to explain before the old bytes are gone."
- Resume semantics are pinned by test: provenance-keyed units, atomic data+provenance commit in `bulk_load`, kill-and-resume proven once in 186-26 with skip counts equal to pre-kill completions.
- The freeze discipline chain (186-26 records sha/log in STATE.md; 186-27's gate proves completion, which is what lifts the freeze) is coherent and both plans say which side of the freeze their edits are on.
- The warmup rule is honest about the expanding-memory case: series_start fetch is allowed only for a named kernel, and 186-26 Task 2 adapts the pilot to one early + one late year if it fires.

### Concerns

- **HIGH — per-unit `compress_before` collides with shared 1-year chunks.** Units are (symbol chunk ~25 names, tf, calendar year); a hypertable chunk is one year across *all* symbols and tfs. 186-25 Task 2 step 4 passes `compress_before=range_end` per completed unit, and 186-24/186-25 both state `bulk_load` "refuses on ... an already-compressed chunk in range" (186-06-PLAN.md:30, :317: "any chunk with `is_compressed` overlapping the range refuses"). The first unit completing in a (tf, year) compresses the shared chunk; every subsequent unit (the other ~37 symbol chunks at 931/25, plus resume and kill-and-resume traffic) gets `BulkLoadRefused`. Failure mode: the multiday run fails at the second unit of the first year group; worse, a partial kill-and-resume could leave a chunk compressed with most of its units unloaded, and the resume then cannot write into it at all without a decompress path the plans explicitly do not have. Fix: compress per *chunk* when its last unit completes (main process consults provenance for unit-completeness of the (tf, year) group), or drop `compress_before` from the writer and compress in a chunk-completion pass. 186-26's launch shape and T-186-25-05 inherit this and need the same amendment.
- **MEDIUM — spool files deleted before the main process reads them.** 186-25 Task 2 step 3 puts spools "under a `tempfile.TemporaryDirectory` created per worker invocation" and then *returns* the spool paths across IPC. A literal implementation deletes the directory when the worker returns; main then has paths to nothing, or the executor is left to invent a different lifetime. Specify: spool dir per group owned by the main process (workers write into a main-supplied path), cleaned after the group's units load.
- **MEDIUM — warmup bound assumes declared memory is denominated in the unit's tf bars.** `unit_fetch_start` converts `effective_memory_bars` via `TF_SECONDS[tf]`. The post-186-15 externals are cross-tf (`ctf_series_by_close` from HTF closes), daily-asof macro, and rolling betas on daily bars. If any kernel declares memory in *source*-tf bars (1d) while consumed at 15m/1h, the fetch under-warms and the first bars of every unit get values computed from truncated history — unmasked, silently, into the permanent rebuilt table. 186-25's summary-only "named or removed" check does not catch a *mis-denominated* declared memory. Add a 186-15/186-25 test asserting each cross-tf/macro kernel's declared memory is expressed in the consuming tf's bars, and have `unit_fetch_start` take the registry's own conversion.
- **MEDIUM — todo 449 dependency is enforced but not stated as a schedule reality.** The rebuild's coverage gate (all 931 names at decided tfs) cannot pass for 15m/1h on the ~698 names until 449 finishes (~mid-Oct). 186-26 quotes the D-32 owner rule but never says "this plan stops and must be re-run after 449 completes"; an executor could read a coverage-gate stop as a phase failure rather than the designed wait. State it, and note that bars arriving after launch (late 449 stragglers) leave completed units stale — the feature path has no content-digest re-detection (that exists only in the 186-14 IC writer).
- **LOW — 186-24's `numeric_columns` union contradicts the schema.** 186-24 claims `feature_columns() ∪ UNOWNED_COLUMNS` equals the 311 numeric columns while also placing `regime_rolling` in UNOWNED_COLUMNS; `regime_rolling` is `text` (verified live). The union is therefore 312 entries and Task 1's `len == 311` assert trips — loud, and the plan prescribes reconciliation, but the interfaces state two incompatible facts an executor must arbitrate.
- **LOW — hard-coded 310 vs conditional keep paths.** If the `bar_close_ts` derivation proof mismatches, the plan keeps the column and the count becomes 311, but Task 1/3 asserts pin `expected_column_count == 310`. The "keep it" branch cannot pass the plan's own verification.
- **LOW — 186-27 Task 2 verify contradicts its own repoint scope.** `grep -c "feature_vectors_v2" services/backfill_feature_factory.py | grep -qx 0` will fail on the 186-25 module docstring ("single rebuild writer for feature_vectors_v2") unless Task 2 also edits that docstring, which it only specifies for `feature_vector_persistence.py`. Restrict the grep to non-comment lines or add the docstring edit.
- **LOW — 186-26 pilot uniformity claim breaks for 1d.** 1d runs as one full-history range per chunk (no calendar-year units), so "per-unit cost is uniform across calendar years" and the pilot's "first completed calendar-year unit at each decided tf" do not apply to 1d; the wall-clock arithmetic should measure the actual 1d unit.
- **LOW — "the 426 reserve the module names"** (186-26 Task 2 step 4) is a dangling reference to a constant that only exists after 186-25 lands; name the parameter exactly.

### Suggestions

- Fix the compression sequencing in 186-25 Task 2 (behavior block and step 4), 186-24's interfaces note to 186-27 ("all rebuilt chunks are already compressed"), T-186-25-05, and 186-26's launch shape in one pass: chunk compression keyed on group completion, not unit completion.
- Add an explicit 186-26 gate/honesty block: "expected to stop at the coverage gate until todo 449 completes; re-run the plan afterwards."
- In 186-25, make `check_no_live_run`'s STATE.md lane-table read specific (ic_engine corpus run or rebuild), since the 449 lane is legitimately live — current wording is specific enough, keep it that way during amendment.
- Consider recording in the 186-26 evidence JSON the per-(tf, year) chunk completion checklist the writer uses for compression, so 186-27 can verify "all chunks compressed" without re-deriving.

### Risk assessment

**MEDIUM-HIGH as written, LOW after the compression-sequencing fix.** Everything else I probed held up under live verification, and the failure modes the plans worry about (premature launch, silent drift, premature close-out) are gated loudly. But the HIGH is on the critical path of the most expensive run in the phase and would surface only after the gates pass, mid-run.

### Cross-plan checks (verified live or against outline)

- Verified live: `feature_vectors` 322 columns / 108,646,010 rows; all six never-computed columns 0 non-null; `regime_label_source` single value `filtered`; 86 chunks; `policy_compression` `compress_after = 6 mons`; `regime_rolling text`, `days_to_month_end real`; latest migration 379 (186-24's "380 expected" correct); `backfill_feature_factory.py` 1,815 lines and every cited line number (1035, 1326, 1451, 1603, 797, 813, 234-256) matches; free disk 494 GB vs the stated 499 GB (moving target, re-measured at run time, acceptable).
- Verified live: `bulk_load`/`BulkLoadSpec`/`rebuild_preconditions.py`/`ic_measure.py`/`registry.py` do not exist yet — consistent with waves 1-4 unexecuted; 186-24/25 precondition checks ("SUMMARY exists on main") correctly refuse until then.
- Names match the outline's binding set everywhere: `provenance_batch`, `bulk_load()`, `completed_provenance_batch`, `bar_content_digests`, `feature_ic_scores_v2`, `services/ic_measure.py`, `src/intelligence/features/registry.py`, `UNOWNED_COLUMNS`.
- (d) from my tasking: 186-28 is correctly gated on 186-27 (`depends_on: [186-27]`; stops unless `186-27-SUMMARY.md` + passing drift verdict exist), and 186-27 Task 3 writes the explicit handoff. Sequencing is sound: the fresh IC run cannot start before the swap.
- 186-27 Task 1 step 1b's `infra.bar_derivation.intraday_recovery_unlocked` / `rebuild_state_table` names and JSON shape exactly match 185-20-PLAN.md:55/:72 (which I read; neither key exists in `config_state` yet, as expected pre-185-20). The 185-20 refusal counts non-completed rows across both target names, matching 186-27's post-swap mapping.
- Todo 420 ownership in 186-26 Task 1 step 5 is correctly conditioned (186-18 deferral with J > 0) and correctly ordered after 186-20's parity lands on main via the 186-26 → 186-23 → 186-20 dependency chain.
- 186-25 `check_drops_landed`'s 12-table list matches the 186-22/186-23/186-11 drop scopes; 186-26 Task 1's "nine 186-22 tables" plus `forward_returns` is the same set. No gate circularity found: the disk-guard inputs come from the pilot, which comes after the checker, and the checker defers the disk check to the caller as 186-26 assumes.
- One arithmetic reconciliation for the record: 310 new columns = 3 keys + 2 regime text + (311 old numerics − 6 dropped numerics; `regime_rolling` is text and is one of the 11 non-numeric). The plans' "322 minus 12" phrasing lands on the same number, but the executor should use the recomputed formula as the plans instruct.

---

## Consensus summary

Six independent reviewers (five fresh-context Claude Opus agents partitioned across all 29 plans, plus the owner-run Grok 4.7 consistency and council passes), each blind to the others' findings, plus integration commits applying the accepted findings to the plans as they landed. Every HIGH and the council's four required changes has a fix either already committed or specified below. Reviewer-by-reviewer raw text above is authoritative; this section records convergence and disposition.

### Independent convergences (multiple reviewers, no coordination)

1. **One column, two clocks in `feature_ic_scores`** — Grok council defect 1 (design rejection) and R4's verification that all 10,616,092 legacy rows sit exactly on oos_start while fresh rows would sit before it. *Fixed:* `feature_ic_scores_v2` created by 186-14 with one clock; legacy table untouched until 186-28's whole-table drop; the coexistence protocol, the D-19 purge, and `replace_where`-into-a-mixed-table are all deleted (commit 54188a155).
2. **The production writer path was never proven** — council defect 2 (parity certified a function the writer does not run) and R4's MEDIUM (no comparison of replaced numbers before the old ones are gone). *Fixed:* 186-20 Task 3's writer-path parity cell (production assembly vs harness on one frozen cell, committed before 186-23 can delete anything), plus 186-28 Task 2's fresh-vs-legacy matched-key disclosure before the legacy drop (54188a155, 9a7a6ea59).
3. **Migration-number race** — R2 MEDIUM and Grok consistency MEDIUM (phase 185 names 380-392; 186-05/06/09 all said "380 next"). *Fixed:* next-free-number + re-check-before-apply + rename-on-collision sentences in all three plans (0cffde0ae).
4. **Todo 420 market_regimes orphan rerun had no owner** — R3 MEDIUM and R4 HIGH (three documents, three attributions). *Fixed:* 186-26 Task 1 step 5 owns the conditional rerun (after 186-20's parity, before the rebuild consumes regime inputs — earlier than the todo's "after the swap", which R4 showed was too late); todo, 186-18 deferral message, and outline aligned (54188a155).
5. **Undeclared phase-185 dependencies** — R4 HIGH (185-11's `bar_content_digest_current` gate in 186-14) and R6's verification that 186-27's 185-20 handoff names check out. *Fixed where broken:* the 185-11 existence gate; 186-27's 185-20 coupling was already sound.
6. **Factual errors in live-state claims** — R5 HIGH (186-22's compression job ids; job 1071 is `feature_ic_scores`'s) and R6 LOW (186-24's 311-vs-312 union arithmetic). The first is fixed (abb4a2de8); the second is in the R6 fix pass below.

### Desk-standard verdicts

- The Grok council's standard (one definition per number, one data-flow direction, no silent two-population mix) was adopted as the review lens for R4-R6 after the council pass. R4-R6, reviewing post-amendment text, found no further two-population or silent-fallback designs; R5's one silent-fallback residue (the corpus verifier's lookahead mirror) and R6's one silent-under-warm path (mis-denominated cross-tf memory) are dispositioned below.
- All six reviewers rated the plans' evidence quality unusually high: every load-bearing live claim re-verified by at least one reviewer held (row counts, schemas, line numbers, job ids apart from the two named errors, APR keys, greps).
- Post-amendment residual risk after the R6 fix pass: **LOW-MEDIUM**, concentrated in schedule coupling (todo 449 through ~mid-Oct gating the rebuild's coverage gate; 185 D-14 gating 186-23) rather than computation.

### Disposition of remaining findings (R6, applied after this summary)

- **R6 HIGH (per-unit `compress_before` vs shared 1-year chunks):** must-fix before 186-25 executes; chunk-completion-keyed compression in 186-25/26 + threat + 186-24's interfaces note.
- **R6 MEDIUMs:** spool-dir lifetime owned by main; declared-memory denomination test for cross-tf/macro kernels (186-15/186-25); 186-26 states the expected stop-and-rerun at the coverage gate until todo 449 completes.
- **R6 LOWs:** 186-24 union arithmetic and the 310-vs-keep-branch verify; 186-27's grep scope; 186-26's 1d pilot arithmetic and the dangling "426" reference.
- **R5 items already applied:** abb4a2de8 (see R5 section).
- **R1-R4 items already applied:** 0cffde0ae, 54188a155, 9a7a6ea59 (see respective sections).

### Not accepted (with reasons)

- R1's MEDIUM on 186-16 gate 3 hardcoding 186-04's module names: moot — 186-04 pins the exact names and the outline marks them binding.
- R4's pg_stat_activity breadth MEDIUM in 186-14: the cross-table contention path is lock-mediated and covered by the migration window; noted in the plan, no edit.
- Council's "sync `asyncio.run` around panel builds" was explicitly not a defect; no change.

The phase is ready to execute after the R6 fix pass lands.






