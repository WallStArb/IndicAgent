# Guarded heavy runs: block 2 rerun, family 10 counted runs, corpus pilot (scope 1d)

Scripts in `scripts/ops/`: `guarded_run_common.sh` (host gate, DIMM watchdog, RSS log: `rss_mb` goes into `logs/family10_dimm_temp.log` every 20 s), `family10_block2_rerun.sh`, `family10_launch.sh`, `corpus_pilot.sh`. Each passes `bash -n`. Output, worktrees and the operator file `memtester_clean` live under `logs/guarded_run/` (override with `GUARDED_RUN_DIR`). Why they exist: the 2026-11-23 DIMM overheating (117 C) corrupted memory and killed the family 10 counted runs (`.planning/STATE.md`, ledger 2026-11-24b).

## Order (lead ruling 2026-11-24)
1. Block 2 rerun to `block2 compare: IDENTICAL` in `logs/family10_run_status.txt`.
2. This pilot (65 names, 4 workers, DIMM watchdog), done before the 04:40Z Alpaca nightly (23:40 EST).
3. Four family 10 counted runs. 4. If the pilot passed, `stage_1d` after the counted runs, on the same pin, `--through feature_complete` and no further until todos 670 and 671 exist (ledger 2026-11-24f).

## Facts checked
- `sudo -n true` exits 0 on this host, so `--quiesce` (`sudo -n systemctl disable|stop`) and `--release` work.
- The six blocking timers (APR `infra.corpus_rerun.blocking_timers`) are all enabled now: alpaca-nightly
  (next 23:42 EST that day), bar-derivation-daily (00:20 EST), bar-derivation-grid (00:45), bar-reconciliation-audit
  (01:00), dividend-event-writer-yahoo (01:30), regime-coverage-auditor (01:00). Nothing fires before 23:42 EST,
  so a pilot started in the morning needs no quiesce for timing, but the pin gate refuses an enabled timer, so
  it is still quiesced and released.
- `--quiesce` records the enabled and active set in `logs/corpus_rerun_quiesce.json`, refuses while a corpus
  rerun, ic_measure or rebuild process is live, keeps the first record on a repeat; `--release` restores
  exactly that set. After a clean pilot (exit 0) the launcher releases; on any other exit with a run id (a watchdog abort is 143) it keeps the timers quiesced and logs `timers held: run <id>`, because a resumed run needs the bars unchanged under it. Re-quiesce before `stage_1d` if they were released.
- `infra.feature_factory.workers` is 12 (version 1, no `config_history` rows). It is a throughput key: not in
  `rebuild_apr_keys()`, so it is not pinned and may be set before or after `--new-run`; the pilot reads it
  live (`corpus_rerun.py:1404`). `ConfigService.set(key, value, changed_by, expected_version, reason)` validates
  against `config_schema` and writes `config_history`.
- Disk: write path is `/` with 1,467 GB free of 1,875 GB (19 percent used); `max_disk_fraction` 0.70,
  `disk_reserve_bytes` 50 GB, `bytes_per_row_uncompressed` 1379 (the pilot replaces it with the measured figure).
- `--new-run --plan-only --data-gate-scope 1d` printed nothing in 3 minutes (31 s CPU, DB-bound while block 2
  runs) and was killed; it is the first step of `--new-run` anyway, so do not rerun it alone while a heavy job is
  live. The 1d-first data gate took about 2 minutes on an idle host (run a4f6ad40).
- `rebuild_code_key()` on main today: `09708ae249f2`. The pin uses `--commit <sha>`: use an explicit SHA of main
  after the last closure edit; a docs-only commit does not move the key (checked: 79f6ec662, fc0df3189, cf7fa4a67,
  ea0dcba05 left it unchanged).

## Pre-flight (the launcher enforces the items marked *)
1. `block2 compare: IDENTICAL` in the status file *.
2. `memtester_clean` present *; no memtester, no other heavy job *; `/proc/sys/kernel/tainted` is 0 *; no
   segfault, Bad page, Bad swap or GPF in this boot's kernel log *; both DIMM sensors at 60 C or less *; 40 GB
   available *.
3. `infra.feature_factory.workers` = 4 *. The lead sets it, with a reason:
   `ConfigService(dsn).set("infra.feature_factory.workers", 4, changed_by="indicagent-ee",
   reason="DIMM thermal budget: 4 workers until a measured run holds both DIMMs under 85 C (2026-11-23 fault)")`
   (a one-line async script; the write is reversible by setting 12 and is recorded in `config_history`).
4. Clock: not inside the 04:40Z nightly window, which the launcher refuses *; the pilot's own length is unknown
   (the last one took 10 minutes for 25 names).
5. Main checkout fast-forwards cleanly and `rebuild_code_key()` starts with the expected prefix *.
6. Thermal cap is on (`systemctl is-active indicagent-host-thermal-cap` = active).
7. Member 1d verdicts are fresh *: the pin gate (`d2_landed`) refuses when the latest verdict of a member is older than `threshold.bar_integrity.report_max_age_hours` (30 h; `verdict_gate.load_report_max_age_hours`). The launcher counts the stale members (read-only SQL, `verdict_preflight` in `guarded_run_common.sh`) and prints the refresh command. The 06:00Z bar-reconciliation audit judges active names only; dead members' verdicts come from `scripts/ops/bars/ops_member_verdicts_1d.py --apply` (about 1 h, one DB connection; `--symbols` does not narrow its whole-table lineage scan, so a one-name run still takes about 10 minutes), which has no timer and no owner of record (todo 649). Any pause of more than 30 h between the refresh and the pin gate repeats the refusal (pilot 7c5612f0, 2026-11-24: 11,350 of 12,857 members at 61.4 h).
8. Free disk comfortably above `disk_reserve_bytes` plus the plan's peak; the plan prints the table.

## Run
`setsid -f bash scripts/ops/corpus_pilot.sh <expected_rebuild_code_key_prefix> [commit_sha]` (the key prefix is `rebuild_code_key()` on the pinned commit). It: quiesces; `--new-run --data-gate-scope 1d`;
reads the run id; runs `--run-id <id> --through pilot` from the run's worktree (the corpus run walks only `--through feature_complete` until todos 670 and 671 exist: ic_measure cells count as attempts under E21, ledger 2026-11-24f) under `run_guarded` (watchdog:
STOP at 92 C, CONT at 80 C, TERM and ABORT at 100 C or 20 minutes paused); writes `rss_mb` of the whole process
group every 20 s; releases the timers on a clean exit (rc 0) or on a failure before the run exists, and holds them on any other exit once the run exists. Status lines go to
`logs/family10_run_status.txt`; the pilot's output to `logs/corpus_pilot_<run id>.out`; run log
`logs/corpus_rerun.log`.

Resume the same run (same pin, timers already held): `setsid -f bash scripts/ops/corpus_pilot.sh --resume <run_id>`. It repeats the status-file, workers, host, nightly-window and verdict preflights, runs `--run-id <id> --through pilot` from the run's worktree under the watchdog, releases the timers on exit 0 and holds them otherwise. Output: `logs/corpus_pilot_<run id>_resume.out`.

## Ticker ends: record the listing end first
An active member whose ticker ends (a merger, a rename, a delisting) needs a `listing_end` row before its 6th missing session: the 1d verdict judges it to the last completed session until then, and `proven_start_1d` turns false once session coverage over the proven span falls under the floor (BKH, 2026-11-24: passed with 5 trailing sessions missing, 0.99914; failed with 6, 0.99897), which refuses the data gate. `listing_end` is written by a migration only (append-only; pattern in migrations 609 and 616; reasons acquired, merged, taken_private, delisted). Then re-judge the name with `ops_member_verdicts_1d.py --symbols <name> --apply`. Todo 673 plans the nightly guard.

## Read after it ends
- `corpus_run.measured`: `pilot_seconds_1d_chunk`, `extrapolated_seconds.stage_1d`, `pilot_bytes_per_row_1d`,
  `compression_ratio_measured`, `pilot_db_load`, `pilot_hmm_written_share` (todo 661 disclosure), and
  `summary.gates` (G1-G3, G4-G5, G6-objects).
- Peak `rss_mb` and the peak DIMM temperature from `logs/family10_dimm_temp.log` (the measurement that decides
  workers 4 versus 8).

## Abort and rollback
- Watchdog abort or any non-zero exit with a run id: the launcher keeps the timers quiesced (`timers held: run <id>` in the status file); after resuming to a clean pilot or abandoning the run, `services.corpus_rerun --release`; confirm with
  `systemctl is-enabled indicagent-alpaca-nightly.timer` (expect enabled) and that `logs/corpus_rerun_quiesce.json`
  is gone.
- A killed pilot resumes with `--run-id <id> --through pilot` (completed units are skipped); follow the worker-kill
  procedure in `docs/reference/gotchas.md` first so no orphaned worker holds a connection.
- A pilot failure that needs a rebuild-module edit: fix, new pin and run id (the old run does not resume), repilot
  before the counted runs (lead ruling).
- Workers back to 12 (`ConfigService.set(..., 12, reason=...)`) only after the owner confirms the cooling fix.
- `systemctl disable --now indicagent-host-thermal-cap` is not part of this rollback.

## Block 2 rerun and the four family 10 counted runs
- `setsid -f bash scripts/ops/family10_block2_rerun.sh`: the verification rerun of battery block 2 (seed base 12,000,000, commit 48a65742d, 1,000 simulations per cell, `--battery src.intelligence.research.null_battery_volume_shock`); seeds are by position, so the worker count does not change a result. It compares every field except `seconds` with `logs/e17_family10_s12m/block2.json` and writes `block2 compare: IDENTICAL` or `DIFFERENT [fields]` to `logs/family10_run_status.txt`. It charges nothing.
- `setsid -f bash scripts/ops/family10_launch.sh [spec ...]`: needs the IDENTICAL line, then the host gate, the commit-equality check against `c0832b091`, `repro_frozen`, then the primary spec and the core spec one at a time under the watchdog. A rerun with a spec argument resumes at core. The four dead attempts of 2026-11-24 are charged `failed` rows with no result, so they do not use up the spec hash (`ledger.py` RESULTLESS_FAILURE_SQL).
- Neither family 10 spec can be replayed after the fact (both declare `total_return`), so the host must be cool and clean before they start.
