# Grok review — Phase 186 (owner-run external)

**Reviewer:** Grok (Cursor session on `\\192.168.68.60\dev\indicagent`)
**Reviewed:** 2026-09-27
**Plans:** all 29 (`186-01` through `186-29`)
**Method:** goal-backward read of `186-CONTEXT.md` (D-01..D-38, R-01..R-13, deferred list), `186-PLAN-OUTLINE.md`, every plan's wave / `depends_on` / `requirements`, and the task text of the load-bearing plans (`06`, `10`, `14`, `20`, `23`, `25`, `26`, `27`, `28`, `29`). Other plans were checked at contract level (must-haves, files, gates), not line-audited against the live repo.

This session had already seen the R1 section and most of R2 in `186-REVIEWS.md` before this review. R3–R6 were not read. Findings below were re-checked against the plan files.

## Summary

The 29 plans will deliver the phase goal if executed as their task text is written: summary cards before drops, the old chain deleted after consumer greps, a fresh IC engine beside the old one with parity before any purge, and a gated append-only `feature_vectors` rebuild that refuses to start until 185's derived grid, the todo 445 decision, the drops, and bar coverage are actually present. Locked decisions D-01 through D-38 and resolutions R-01 through R-13 each appear in at least one plan's `requirements`. Deferred work (phase 187 UCR / `book_memory()`, phase 188 forward runner, nightly temporal-integrity jobs, todo 443) is not pulled in. The dependency graph is acyclic and every wave number is one past the latest dependency wave. No finding here invalidates a plan. The residual risk is an executor following a must-have sentence instead of the SQL next to it, and schedule coupling that can hold the rebuild behind work it does not computationally need.

## Strengths

- D-02 is operational, not a slogan. Plans that touch code assert `git diff --stat` empty on `src/intelligence/research/`. The one sanctioned edit is `186-29`, and it stops unless STATE.md shows the research lane released or the five tests have already dropped the sleeve import.
- Strangler order is real. `186-10` is pure and does not enter `ic_engine`'s import closure. `186-14` writes through the new engine and leaves `services/ic_engine.py` byte-unchanged. `186-20` commits the parity report before any delete. `186-23` refuses to delete `forward_return_writer` until that report is on main and phase 185 D-14 has moved the bar flags.
- D-19 is closed by the end of the phase, not by a silent keep. `186-20` deletes only `NOT is_pooled` rows. `186-28` requires the whole-table count of `training_window_end >= oos_start` to be 0 after the legacy-scope delete, and the delete script refuses when fresh rows are absent.
- `186-14` does not assume `replace_where` already exists. `186-06` never mentions it (append-only). `186-14` adds the keyword, requires the existing bulk-load tests to pass unchanged when it is omitted, and uses it for atomic unit replacement.
- Rebuild gates match D-32 / R-09 / R-13. `186-26` launches nothing until `186-25`'s checker passes, reads coverage instead of starting an IBKR job, and will not run while a rebuild it does not own is live. Drops (`186-22`, `186-23`) are dependencies, so the ~61 GB lands before the multiday write.
- `186-27` states the drift sample and the 5% unexplained-diff stop before any measurement, and it refuses to swap a run that is still resumable.

## Concerns

- **MEDIUM — `186-20` must-have overstates the purge predicate.** The must-have says the D-19 purge is rows whose target window ends at or after `oos_start`. The task SQL is `DELETE ... WHERE NOT is_pooled AND training_window_end >= oos_start`, and the same plan records that every stored row, pooled included, has `training_window_end` equal to `oos_start` (10,616,092 rows). An executor who "corrects" the SQL to match the must-have parenthetical deletes the 1,301,353 pooled rows that `186-23` still expects to find and that `186-28` is supposed to replace. The action text, the dry-run, and threat T-186-20-02 already forbid that. The must-have sentence is the hazard.
- **MEDIUM — migration numbers 380+ are claimed by phase 185 and by several wave-1 plans here.** `186-05`, `186-06`, and `186-09` all describe the next migration as 380 if nothing has landed since 379. Phase 185's plans already name 380 through 392. Each 186 plan says to re-check `ls production/migrations` at write time, which is the right rule, and it is still a check-then-apply race across parallel worktrees and the 185 session. Failure mode is a duplicate number and a CI break, not a bad drop.
- **MEDIUM — `186-26` wall-clock is easy to mis-scale.** `186-25` pins path-dependent kernels to a fetch from series start for every calendar-year unit. A pilot of an early year therefore understates a 2024 unit, and multiplying "seconds per unit-year" by the unit count double-counts history that every unit recomputes. The plan re-measures at runtime and is resumable, so this does not threaten correctness. It does threaten the "expected wall-clock" the operator will use to decide whether to launch.
- **MEDIUM — the rebuild waits on `186-23`, which waits on phase 185 D-14.** D-32's precondition is the derived 15m/1h grid, todo 445, coverage, and disk after the drops. D-14 (bar flags off `forward_return_writer`) is a precondition of the deletion, and `186-26` depends on that deletion. That is coherent for the 14 GB `forward_returns` drop (R-09) and it is also a schedule coupling: a stalled 185 D-14 holds the rebuild even after D2b has landed. The stop is safe. It should be explicit in `186-26`'s blocked message so it is not treated as a checker bug.
- **LOW — `186-06` versus the outline's `bulk_load(replace_where=)`.** The outline lists `replace_where` as part of the bulk-load binding name. `186-06` implements append-only COPY and says PK conflicts are loud. `186-14` is where the keyword is added. An executor of `186-06` who treats the outline as the contract could build the option early and fight `186-14`'s tests. The plan text of `186-14` is the one to follow.
- **LOW — `186-20` calls the non-pooled delete "the D-19 purge" while D-19's pooled half waits for `186-28`.** The split is disclosed in the task (todo 439 stays open; pooled rows are replaced later). The phase still delivers D-19, at plan 28, not at plan 20.

## Suggestions

- In `186-20`, change the must-have to the predicate that is actually executed: non-pooled rows with `training_window_end >= oos_start`, pooled rows untouched, whole-table D-19 closed in `186-28`.
- In `186-05`, `186-06`, and `186-09`, one sentence: phase 185 may already have consumed 380–392; take the next free number after the file exists and again immediately before `psql -f`.
- In `186-26` Task 1, name the blocked reasons separately (449 coverage, 185 D2b marker, 185 D-14 via `186-23`, disk guard) and pick the pilot unit-year explicitly (one early year and one late year) before extrapolating.
- In `186-06`'s context block, one line: `replace_where` is `186-14`'s extension; do not add it here.

## Risk assessment

**LOW-to-MEDIUM. No HIGH.** Nothing in the plans, executed as the task text is written, drops a kept table, edits the research package while the lane owns it, or starts the rebuild on a partial bar history. The irreversible steps (IC shrink, `forward_returns` drop, `feature_vectors` swap) each have a prior committed artifact and a refuse-and-stop gate. The MEDIUM items are misread predicates and scheduling, and each has a one-line fix.

## Cross-plan checks

- **Coverage.** Every D-01..D-38 and R-01..R-13 is in some plan's `requirements`. Deferred ideas from CONTEXT are absent from those fields.
- **Waves.** `depends_on` edges match the outline. Wave assignment is `max(dependency wave) + 1` for all 29. Plan numbers are not wave order (`186-17` is wave 2, `186-12` is wave 2, `186-29` is wave 4); the outline says IDs are stable and not execution order.
- **Card before drop.** `186-01` / `186-02` precede `186-11`, `186-16`, `186-22`, `186-23`, and `186-27`. `DROP_TABLES` in `186-01` names the D-14 tables plus `ctx_events`, `ctx_snapshots`, `construction_spreads`, `alpha_strategy_scores`, `forward_returns`, and `feature_vectors`.
- **Parity before purge before delete.** `186-20` Task 2 commits the report; Task 3 refuses without it. `186-23` refuses without that report and without 185 D-14. `186-28` refuses to delete legacy scopes until fresh rows and completed provenance exist.
- **`replace_where` handoff.** Absent from `186-06`. Specified, tested, and consumed in `186-14`. `186-25` and `186-28` call the landed signature.
- **Research lane.** No plan other than `186-29` edits `src/intelligence/research/` or the five HarnessConfig tests. `186-29` is wave 4, depends only on `186-16`, and is not on the rebuild's dependency path, so a held lane does not block the rebuild.
- **185 boundary.** `186-26` reads 185's D2b marker and does not start IBKR jobs (R-13). `186-23` reads 185 D-14 and does not implement it.

## Council pass (data integrity, one clock, one statistic)

Applied after the consistency pass, against `docs/foundation/principles.md`: one direction of flow, one meaning per column, failures loud, complexity deleted before it is optimized. The consistency pass found no HIGH. This pass does. The plans are executable. Two designs will write a silent wrong answer if left as specified.

### What already matches the standard

Raw bars stay. Derived tables are cache and are dropped only after a card. The research package is not edited while another lane owns it. The rebuild compresses per chunk and does not decompress `feature_vectors` in place (the failure mode of todo 426). The causality probe in `186-08` fails a kernel that normalizes over its full input, and once `186-12` registers kernels that test is no longer an empty parameter set. Those are the right instincts. Do not reopen the drops.

### Defect 1 — one column, two clocks

`186-14` states the choice in prose: fresh rows store `training_window_end` as the latest target exit, always before `oos_start`; legacy rows store the same column as the window bound, and every one of the 10,616,092 live rows sits exactly on `oos_start`. Both populations share `feature_ic_scores` from `186-14` until `186-28`, which is after the rebuild and the name swap.

`training_window_end` is the hypertable time column. A reader who filters `training_window_end < oos_start` sees only the fresh scope. A reader who filters `>= oos_start` sees only the legacy scope, whose targets touch the forward span. `feature_lifecycle` and any ad hoc IC query that does not also filter `regime_scope` mixes or drops a population with no error. The integration test in `186-14` even seeds a legacy row and asserts it survives a fresh write. That is coexistence by design.

The phase already has the pattern that removes this: `feature_vectors_v2`, write, prove, swap, drop. Fresh IC rows belong in a new table with one clock. The legacy table stays untouched until `186-28` deletes it. `replace_where` against a mixed table, and a write session that decompresses the legacy population in order to append a different population, both go away. `186-20`'s must-have hazard (purge predicate wider than its SQL) is the same defect showing up as an instruction bug.

### Defect 2 — parity certifies a function the writer does not run

`186-20` replays stored cell masks through the IC function, once with table targets and once with kernel targets. That is the right test of the rank statistic. It is not a test of `services/ic_measure.py`.

The writer, in `186-14`, builds S0 panels with `end_exclusive = oos_start`, stacks symbol chunks, aligns features, and chooses stride from APR. The parity harness feeds the stored observation set. R-06 is explicit that no stored cell has an exact kernel counterpart, so nothing in the plan requires those two assemblies to match. The `186-14` integration test checks that a hand-built predictive column gets a positive IC on 8 symbols. A sign check is not parity.

`186-23` then deletes the old engine and `forward_returns`. `186-27` drops the old feature table. `186-28` is the first time the production assembly writes the numbers anyone will read. If chunk stacking or `align_features` shifts a target by one bar, the result is a clean table of the wrong statistic, and the artifact that could have caught it has already been dropped. Raw bars can rebuild features. They cannot tell you the new IC matches the old one.

The missing gate is small: one frozen cell, production path only (`build_target_panels` → `align_features` → the same IC function the harness uses), compared to the harness output on that cell, committed before `186-23`. Same function, two callers, one expected number. If they differ, stop.

### Defect 3 — provenance records two recipes for one row

D-24 says a rerun of the same key is a no-op. `186-14` case 3 expects a changed bar to replace the data rows and leave **two** `completed` provenance rows for the unit. Both keys claim the current rows. A later resume that recomputes the old digest finds the old key completed and skips, leaving the new rows in place under the old recipe. Lineage is the invariant that makes a result auditable. A log of attempts is not the identity of the stored batch. On replace, the previous key has to stop meaning "these rows." Mark it superseded in the same transaction as the delete-and-COPY, or the record is a lie.

### Complexity to delete, not tune

`186-25` fetches from series start for every calendar-year unit because the kernel set contains path-dependent kernels. Declared memory was built in `186-08` so a unit can fetch its warmup and nothing else. One expanding kernel, if any exists, should be named and either given an explicit expanding memory or removed. Three hundred columns should not recompute twenty years because one of them might need to. The `186-26` pilot will measure that cost and then treat it as a property of the machine. It is a property of the decision.

`replace_where` on the append-only primitive exists to edit a mixed table in place. Defect 1 removes the need. An append-only `COPY` whose conflict is loud is the whole primitive.

The sync `asyncio.run` around `build_target_panels` is not the defect. This is a batch job whose contract is a deterministic `COPY`. Making it async would add a second runtime for the same numbers.

### What Simons would require before execution

1. Fresh IC writes a new table. One meaning of `training_window_end`. Legacy rows are not neighbors of fresh rows.
2. One committed cell where the writer path and the parity harness agree, before any drop.
3. A replaced batch has one completed provenance row.
4. Rebuild warmup is `max(declared memory)` over the registry actually used, measured, not "from the first bar."

None of these add a stage. They delete a coexistence protocol, a second statistic, and a full-history refetch. The rest of the phase can run as written.
