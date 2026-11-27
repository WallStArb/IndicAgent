---
status: completed
priority: P1
filed: 2026-11-18
source: B-S review (todo 609): amendment A2 requires the B2 size gate to rerun with the sixth member, and nothing enforces it
---

# Rerun the daily residual E17 H0 battery with M3 before the family registers

## What

`null_battery_daily_residual.MEMBERS` now lists M3 (`residual_momentum_12_1_continuity`) with the spec. `static_gate` is computed from
the scenarios, not from a recorded battery result, so the rerun that A2 requires (size at 0.05, 0.01 and 0.00167 over 1,000
simulations per cell, six members and the equal-weight book at full size, B3 minimum detectable IC for M3) is a manual step that can be
skipped silently.

## Done when

- The battery is run on the six-member family and its result is recorded where the static gate or the run preflight reads it, so a
  registration without it is refused.
- The recorded result names the spec hash of `daily_residual_h5.yaml` and the core twin.

## Why it matters

A precondition of the first counted daily family (E23, A2).

## Result of the first block and the pre-declared replication (2026-11-18, recorded before block 2 launches)

Block 1 (seed-base 0, run at e20c908c2 in two parts, 1,000 simulations per cell): the S1 cell and every M3 and book arm hold; two arms fail in `daily_static_means` at the deepest level, `reversal_5` and `reversal_5_skip1` at alpha 0.00167 (6 against a bound of 5). The base commit bd476c5f4 (five members, none of the I1, B-H or B-S changes) on the identical seeds gives the same 6 and 6, so the exceedance is a property of the draw, not of M3 or of any landed change. Files: `logs/e17_daily_residual_m3_e20c908c2/`, `logs/e17_daily_base_check/`.

Pre-declared before block 2 launches (lead ruling 2026-11-18): the whole battery (all eight cells, no cell picked) reruns once on seed-base 1,000,000 in a single driver call, at the same commit. Both blocks are kept in the record. The pass criterion is the pooled counts of the two blocks (2,000 simulations per cell): per cell, arm and alpha, the rejections of block 1 and block 2 summed and compared with the 0.99 binomial bound at n = 2,000 (123, 31 and 8 at alpha 0.05, 0.01 and 0.00167), with no other rule. Block 1, block 2 and pooled counts are reported separately. If the pooled run fails anywhere the family waits; a failure postpones the run and is never a verdict (E17). The gate is not changed. Expected arm-level exceedances of a correct statistic over a full run: the daily battery has 6 gating cells and 7 arms (six members and the book) at 3 alpha levels, 126 tests; at n = 1,000 each test exceeds its bound with probability 0.0074, 0.0069 and 0.0073, so the expected count is 0.91 and the probability of at least one exceedance, treating the tests as independent (they are positively correlated, which lowers it), is about 0.60. At n = 2,000 each test exceeds with probability 0.0095, 0.0078 and 0.0074. If that calibration looks wrong to the owner it is a separate proposal, not a change made here.

## Outcome of the pre-declared replication (2026-11-18): the pooled run FAILS, the family waits

Block 2 (seed-base 1,000,000, whole battery, one driver call, 1,000 simulations per cell, e20c908c2; `logs/e17_daily_residual_m3_block2/block2.json`) fails on its own in the same cell and the same two arms as block 1, at alpha 0.05 instead of 0.00167: `daily_static_means/reversal_5` 68 against a bound of 67 and `reversal_5_skip1` 72 against 67. Pooled over the two blocks (2,000 simulations per cell, bounds 123, 31 and 8, the declared and only criterion) the same two arms fail at alpha 0.05:

| Arm (cell `daily_static_means`) | Block 1 at 0.05 | Block 2 at 0.05 | Pooled at 0.05 (bound 123) | Pooled at 0.00167 (bound 8) |
|---|---|---|---|---|
| reversal_5 | 59 | 68 | 127 (6.35 percent) | 7 |
| reversal_5_skip1 | 57 | 72 | 129 (6.45 percent) | 8 |

Every other arm and cell holds pooled, M3 and the equal-weight book included, and the S1 cell holds. The two arms exceed the 5 percent level in both independent blocks, and the base commit bd476c5f4 (five members, before any I1, B-H or B-S change) gives the same block-1 counts on identical seeds, so this is a size excess of the five-session reversal members under static per-name mean returns that predates the amendment, not a result of M3 or of anything landed since. By the declaration the daily residual family waits: no pass record is bound (`battery_pass.make_record` refuses a failing pooled result), a real run is refused by `runner.static_gate`, and the failure postpones the run and is never a verdict on the hypothesis (E17). The gate is not changed.

Open for the owner (a decision, not a quiet change): whether the reversal members' excess size under static means is a statistic defect to fix (a design change to the static-mean handling of the E17 statistic, which moves the frozen verdicts and needs a methodology-change entry), or whether the family registers without its reversal members (a counted amendment: the momentum members M1, M2, M3 and the book hold), or the gate's calibration is to be reviewed (a separate proposal, since a correct statistic is expected to fail a full battery about 60 percent of the time at 126 independent tests, and here the same two arms fail in two blocks, which is not chance). H-C is not affected: its battery passed (its record is replaced by a rerun, see the Decision section below).

## Ruling (2026-11-18): the gate is family-wise; the battery reruns on fresh seeds

An independent analysis found the statistic calibrated (reversal_5 at 4.99 percent over 17,000 fresh simulations, spread ratio 0.999, no growth with static-mean size). The gate moves to a Bonferroni bound over the battery's gating tests (ledger E17 amendment 2026-11-18); the family keeps all five reversal and momentum members plus M3. Because the change follows a failure, the pass is not taken from blocks 1 and 2: `DECLARED_REPLICATIONS["daily_residual"]` is now `(2_000_000,)` and the whole battery runs once on seed base 2,000,000 with 2,000 simulations per cell, then `bind_battery_pass.py` binds it. Blocks 1 and 2 stay above as history.

## Correction (2026-11-18): the family-wise gate is withdrawn; the arms are oversized

The fresh-seed check on the battery's own path (pass rule fixed first; record `research/calibrations/e17_reversal_static_means_2026-11-18.json`, 12,000 simulations, seed base 77,000,000) fails for both reversal arms: `reversal_5` 674 at 0.05 (5.62 percent), 157 at 0.01, 39 at 0.00167; `reversal_5_skip1` 676, 149, 31. Controls hold. The earlier "calibrated" claim came from a reimplementation and is retracted (ledger correction under E17). The gate code is reverted to the per-test 0.99 bound; `DECLARED_REPLICATIONS` is back to `(0, 1_000_000)` and no record can be bound for this family. Block3 (seed base 2,000,000, `logs/e17_daily_residual_m3_block3/`) finishes for the record and is not bound. Open: fix the static-mean handling for the two reversal arms or drop them from the family; a reconciliation of the two implementations decides which (cause pending).

## Second correction (2026-11-18): the cause

Reconciliation: the battery's `simulate` and the earlier reimplementation are bit-identical on identical seeds; the 4.85 percent was another seed draw. The two five-session reversal arms carry a small persistent positive mean t (about +0.035, about 4 standard errors pooled), which gives about 5.4 percent at 0.05; across seed sets 4.6 to 5.6 percent. Static means are not the cause (paired run, static sd 0.06 vs 0: the same mean t). Source of the shift not isolated; not blocking if the two arms are dropped. See the ledger's second correction under E17.

## Decision (2026-11-18): amendment A3 drops the two 5-session reversal arms

Lead ruling (owner veto reserved). Ledger: "Amendment A3 to the daily residual family". Four members (M1, M2, M3, reversal_21) times two panels, 8 looks. Block 3 (seed base 2,000,000, 2,000 simulations per cell, the five-reversal six-member family, `logs/e17_daily_residual_m3_block3/`) finished for the record: under the per-test 0.99 bound one exceedance, `daily_gaussian/reversal_5_skip1` at 0.05 (125 against 123), with `reversal_5` 111 and `reversal_5_skip1` 108 in `daily_static_means`; not bound. The reduced-family rerun is pre-declared in the ledger (seed base 3,000,000, 2,000 simulations per cell, one driver call, per-test 0.99 bound); the seasonality battery reruns at the landing commit on seed base 0 for a rebind. Source of the shift: todo 638.

## Outcome of the pooled replication on seed bases 5,000,000 and 6,000,000 (2026-11-21): FAILS at one test, the family waits

Both declared blocks ran once, whole battery, 2,000 simulations per cell, at commit bc3656687 (no change under `src/intelligence/research`, `src/intelligence/statistics` or `research/specs` since the declaring commit f95f95da6); 12 workers, about 30 minutes each. Files: `logs/e17_daily_residual_pooled_5m6m/` (block1.json, block2.json, run.sh). `bind_battery_pass.py` with seed bases 5,000,000 and 6,000,000 refuses: `daily_s1_hostile/residual_momentum_12_1_continuity at 0.05: 240 > 233` (block 1 126, block 2 114; the per-block bound is 123, the pooled bound 233). It is the only pooled exceedance of the 90 tests; at 0.01 and 0.00167 the same arm holds. `reversal_21` holds at every cell and level pooled; its closest cells are `daily_late_listings` at 0.05 (227 of 233) and `daily_static_means` at 0.01 (48 of 55). The other near cell is `daily_static_vol_stress` / continuity at 0.05 (226 of 233). Block 2 alone exceeded its own bound once (`daily_static_means/reversal_21` at 0.01, 32 > 31); the pooled rule judges only the pooled counts. The failed cell is the same one that failed at seed base 4,000,000 (127 > 123), so it exceeded in three independent blocks of 2,000 (127, 126, 114): the continuity member's size under `daily_s1_hostile` is a pattern, not one unlucky draw (about 5.9 to 6.3 percent at the 5 percent level in two of three blocks).

Per the declaration the failure postpones the family and is not a verdict on the hypothesis. Both seed bases are spent; no record is bound; no gate, bound or arm is changed by this note. A fourth retry or any change (a fix to the continuity member under the S1-hostile cell, dropping M3, or a calibration review) needs a lead ruling and a dated declaration before it runs.

## Outcome of amendment A4 (2026-11-21): the reduced family passes and its record is bound

Ledger "2026-11-21c" dropped M3 and declared two fresh blocks for the reduced family (M1, M2, `reversal_21` and their book of three) before any run. Both blocks ran at commit 1f19476aa (12 workers, about 25 minutes each, 2,000 simulations per cell, seed bases 7,000,000 and 8,000,000; `logs/e17_daily_residual_a4_7m8m/`); each holds its per-block bound on its own and `bind_battery_pass.py` bound the pooled result (n = 4,000, bounds 233, 55 and 13) as `research/battery_passes/daily_residual_2026-11-21.json`. The tightest pooled cells are `daily_static_vol_stress/reversal_21` at 0.05 (224 of 233), `daily_static_means/reversal_21` at 0.01 (52 of 55) and at 0.05 (216 of 233). Removing M3 changed the code key of the H-C seasonality battery (it imports the daily battery and the daily family helpers), so that battery reran on the same seeds as the record it replaces (seed base 0, 1,000 simulations, two parts, `logs/e17_a4_seas/`) and was rebound as `research/battery_passes/seasonality_2026-11-21.json`; the 2026-11-19 record is removed (history in git). No look was spent. repro_frozen was bit-identical.

## Outcome of the counted runs (2026-11-22): both specs completed

`daily_residual_h5.yaml` and `daily_residual_h5_core.yaml` completed three members each after a first h5 launch was killed by the OOM killer (three failed rows, counted; ledger 2026-11-22b) and the spec-once guard was narrowed (migration 611). Numbers, run ids and disclosures are in ledger 2026-11-22c. Left: StepM selection across the counted looks, then the `reversal_21` pooled replication after the pin.

## Prepared 2026-11-24: the StepM read across the counted looks (indicagent-94; read-only preparation, nothing run on real data)

Command. One process, no workers, seconds on 16 series; it writes nothing and charges no look (unified design 7.3.2: a read, never a verdict). From the repo root on a clean checkout whose objects contain every recorded spec and code commit:

`.venv/bin/python scripts/research/select_books.py --battery research/certificates/records/stepm_null_battery_s4000_2026-11-23.json`

Add `--diagnostic` to print a set that is not a result (exit 3, key `unattested_set`) instead of refusing. APR keys it reads: `alpha.selection.stepm.fwer` 0.05, `.block_mean_sessions` 20, `.reps` 2,000, `.seed` 187, `alpha.research.vintage_id` (`vintage_1`).

The gates, and what each needs from the family 10 runs. The read is a result only when all hold (`select_books.py` docstring; `split_missing_series`, `selection_refusals`, `battery_refusals`):
1. Every charged row has a series, except a killed row: real mode, status `failed`, and `snapshot_hash`, `decision_t`, `decision_p`, `gross_sharpe` and `span_start` all NULL, whose (spec hash, concept) has a completed real row with a series (ledger 2026-11-22g). Today 20 rows are charged: 12 completed with series, 8 killed (three daily residual, one family 9, four family 10). After the family 10 relaunch: 24 charged rows, 16 series, 8 exempt. The four family 10 killed rows are exempt only if the relaunch completes the same four (spec, member) pairs: `family10_volume_shock_h5.yaml` (spec hash 597a275c45) with `volume_shock_1_50` and `volume_shock_5_50`, and `family10_volume_shock_h5_core.yaml` (7d4dbf497e) with the same two members. Editing either spec between the failed launch and the relaunch changes the hash, makes the four rows gaps, and the read refuses ("4 charged runs have no series"); a changed member list does the same.
2. One vintage: every charged row is on `vintage_1`; the relaunch must not start on another vintage (E18 re-evaluation onto an extended vintage is not built and the read refuses).
3. Spec and code objects readable: for every completed row the horizon is read with `git cat-file -p <spec_blob>` and `git show <code_commit>:<spec path>` (families), so each `code_commit` and `spec_blob` of a counted run must exist in the local object store (commit and push the specs before a run; never gc them away). The maximum horizon must stay below the block mean 20; family 10 is horizon 5.
4. The battery record attests this StepM: `stepm_sha256` df77186e1b35693db641b7bb146dcfba33e6176527ee7ad90efbe3ebd00c1483, complete, 4,000 sessions, fwer 0.05, block mean 20, studentize draw. Any edit to `src/intelligence/statistics/stepm.py` makes the record stale (the attestation took 29,133 s on 16 workers to regenerate). None of the held branches (`wip/670-671-sweep-recorder`, `wip/588e-volume-basis`) touches `stepm.py`.

Expected output after the family 10 runs: `result` true, `attempts` 16, `exempt_killed_rows` 8, `missing_series` empty, `max_horizon_sessions` 5, `reps` 2,000, a `selection_set` and a `not_selected` count. The 2026-11-23a read (10 attempts) selected the two `reversal_21` runs at adjusted p 0.0090 and 0.0025; six more series (family 9, two series; family 10, four) tighten the correction, so those p values may rise (ledger 2026-11-23d point 4 says to cite them with that note). The read is recorded in a ledger entry by the lead after it runs.

Dependency on todo 547. The read does not depend on the 547 ruling: it needs no input from it and computes the same set whatever the owner decides. What 547 governs is use of the result: whether `reversal_21` and its book are certified or the family is held (and, if the owner chooses a fresh S1 vintage and fresh pre-registration, the read must be run on `vintage_1` first, because a second vintage makes this command refuse). The phrase "pooled replication" is retired (ledger 2026-11-23b); R-1 is a non-gating disclosure and R-2 is the forward confirmation, so no further replication blocks the read.

Dry run (no database, no git, under 5 seconds, one process, well under 2 GB): `tests/unit/research/test_select_books.py` now builds a vintage of the family 10 shape (16 completed series, one planted, plus the eight killed rows) with the shipped `build_report`, `split_missing_series`, `battery_refusals` and `stepm` (300 reps), the loader and the spec reader replaced. It asserts the result, 16 attempts, 8 exempt rows, that only the planted series is selected, that an edited family 10 spec hash leaves four gaps and refuses, that a stale StepM hash refuses, and that a family 10 member that never completed is a gap. Run: `.venv/bin/pytest -n 0 tests/unit/research/test_select_books.py`.

## Launcher audit for the recording requirements and the new-pin plan (2026-11-24, indicagent-94; read-only, one light preflight run)

Scope: `scripts/ops/family10_launch.sh` and its shared `scripts/ops/guarded_run_common.sh` (the lead's "f10_common.sh" is the earlier scratch name of that file; the committed one is `guarded_run_common.sh`) against the four recording requirements above and the plan to run the counted runs after a possible closure change and fresh pilot.

Already enforced.
- Requirement 1 (same spec hashes), in effect: the runs build from a detached worktree at `BOUND` = c0832b091, the commit of the four killed rows, and `git diff --quiet BOUND origin/main -- src/intelligence/research src/intelligence/statistics research config` refuses a launch if specs or research code on main differ. The same spec text gives the same hash; the launcher does not compute or compare a hash.
- Requirement 4 (stepm.py untouched), in effect against `BOUND`: the same diff covers `src/intelligence/statistics`. It does not compare with the attested hash (df77186e…).
- `repro_frozen` bit-identical at the worktree; clean worktree; block 2 comparison IDENTICAL or ACCEPTED; host and DIMM gates; the watchdog; specs run in order and stop at the first non-zero exit.
- Requirement 3 in effect for the objects: BOUND is on origin/main (checked 2026-11-24, `merge-base --is-ancestor` true) and the run records `code_commit` = BOUND in the shared object store.

Gaps found.
1. No tie between the spec hashes and the recorded rows: a mistaken `BOUND` edit or a spec edit on main after launch would give new hashes and turn the four killed rows into gaps; nothing checks.
2. No check that BOUND is a commit on origin/main (needed for any other clone and for the StepM read's `git show code_commit:spec`).
3. The battery pass is verified only at run time by the runner (`static_gate(require_pass=True)`), after the worktree and the whole `repro_frozen` run have cost their heavy time; a stale battery key refuses uncharged, but late.
4. No check that `stepm.py` equals the attestation record's `stepm_sha256`; the diff gate only compares main with BOUND at launch time, and a later edit to `stepm.py` (todos 586, 669) stales the read.
5. `run_spec.py` exits 0 when every row reached any terminal status (completed, guard_failed, refused): `rc=0` does not mean four completed rows with a series, which is what requirement 2 needs.
6. New-pin plan: the launcher is already independent of the checkout it is called from for the run (worktree at a pinned commit, shared venv and logs by symlink), but the origin/main gate is pinned to the literal BOUND, so any research edit that lands on main first (the todo 674 R closure change) refuses the launch with no supported way to launch from the new commit. Launching from a newer commit is valid only if the battery key at that commit still equals the bound record, the spec hashes still equal the recorded rows, `repro_frozen` is bit-identical there and StepM is the attested one; none of the four is checked for a different commit.

Minimal diff, held: branch `wip/f10-launcher-preflight` (commit e62cf459b, off origin/main 5 minutes before the audit; 41 lines in `family10_launch.sh` only, `bash -n` clean). It adds `LAUNCH_COMMIT` (default BOUND) with an `is-ancestor origin/main` check and the research diff gate against it; in the launch worktree before `repro_frozen`: `stepm.py` sha256 equals the attestation's `stepm_sha256`; per spec, `runner.static_gate(require_pass=True)` (the runner's own battery-key and input-hash check) and the computed spec hash equal to the ledger's recorded hash for that spec path (when rows exist); after each spec, a count of completed real rows with a series for that spec hash equal to the spec's member count, aborting before the next spec and the read otherwise; and `PREFLIGHT_ONLY=1`, which runs all checks (no host gate, no block 2 requirement, no `repro_frozen`, no run) and exits 0. Verified 2026-11-24 with `PREFLIGHT_ONLY=1` from a scratch copy: "preflight family10_volume_shock_h5 hash=597a275c45 battery ok", "preflight family10_volume_shock_h5_core hash=7d4dbf497e battery ok", "preflight OK at c0832b091" in 8 seconds; a launch commit not on origin/main refuses with exit 3. Launchers are shared writers: the branch lives in a detached worktree and is not pushed; land it only when no launcher is live.

What the family 10 runs must record, restated against the launcher: the four rows must be completed with series (gap 5, closed by the post-run count), under unchanged spec hashes (gaps 1 and 6), at a commit whose objects stay in the store (gap 2), with StepM unchanged until the read (gap 4). The preflight can be run now, read-only, as a go or no-go before the heavy slot is used: `PREFLIGHT_ONLY=1 LAUNCH_COMMIT=<commit> bash scripts/ops/family10_launch.sh` from a checkout containing the branch.

## Launcher preflight landed (2026-11-24, indicagent-94)

The preflight is on main as f74ab5d76 and 1490be5d5 (`scripts/ops/family10_launch.sh` only), after indicagent-fb's review. The review found one hazard, fixed before landing: in `PREFLIGHT_ONLY` the script used the live run's worktree path, pruned worktrees and skipped the host gate. It now uses a throwaway `wt-f10pre-<pid>` removed on exit, never prunes, refuses while a `run_spec` process is live, and prints to the terminal instead of the status file; its header says what it writes (a `git fetch` and the throwaway worktree). Use it as the go or no-go before the heavy slot: `PREFLIGHT_ONLY=1 [LAUNCH_COMMIT=<commit>] bash scripts/ops/family10_launch.sh`. Checked 2026-11-24: "preflight OK at c0832b091" with both spec hashes (597a275c45, 7d4dbf497e), exit 0 in 8 seconds. Gaps 1 to 6 above are closed except the choice of a new `LAUNCH_COMMIT` after a closure change, which needs the battery key at that commit to equal the bound record (the preflight checks it) and a fresh `repro_frozen` (the launcher runs it).

## Closed 2026-11-27 (lead ruling)

Done. The reduced family's battery pass is bound (`research/battery_passes/daily_residual_2026-11-21.json`), both counted runs completed (ledger 2026-11-22c), and the StepM read across the counted looks ran on 16 series (ledger 2026-11-25b: `reversal_21` primary and core and `volume_shock_1_50` primary selected). The `reversal_21` "pooled read" is retired (ledger 2026-11-23b: R-1 is a non-gating disclosure, R-2 the forward confirmation). What is left is the owner's todo 547 ruling, which governs use of the result (certify `reversal_21` and its book, or hold the family), not the read; it is tracked on PRIORITIES rank 8.
