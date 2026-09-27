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

<!-- R4..R6 sections appended below as each reviewer completes; consensus summary written after all six. -->



