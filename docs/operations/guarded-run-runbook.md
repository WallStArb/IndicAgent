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
3. `infra.feature_factory.workers` = 4 *, and `alpha.ic.feature_block_columns` = 16 *: the run pins the IC block width at `--new-run` and `ic_measure_launch.sh` refuses any other, so it is set before the pilot (todo 471), never after; the pilot launcher reads both back and refuses otherwise. The lead sets it, with a reason:
   `ConfigService(dsn).set("infra.feature_factory.workers", 4, changed_by="indicagent-ee",
   reason="DIMM thermal budget: 4 workers until a measured run holds both DIMMs under 85 C (2026-11-23 fault)")`
   (a one-line async script; the write is reversible by setting 12 and is recorded in `config_history`).
4. Clock: `host_gate` refuses a start between 01:00 and 05:00Z and while the service of a blocking timer runs (the service is read from systemd: the dividend timer starts a template instance of the dividend event writer, whose name does not follow from the timer's, so a 06:30Z start refuses while it runs; `NOW_H` injects the hour in tests) *. Every launcher then quiesces the blocking timers for the run: the pilot and the IC measure hold them on failure (a resumed run needs the bars unchanged), the family 10 launcher and the block 2 rerun release them on any exit (`hold_timers`, an exit trap), because a counted run or a battery is not resumable. The pilot's own length is unknown
   (the last one took 10 minutes for 25 names).
5. Main checkout fast-forwards cleanly and `rebuild_code_key()` starts with the expected prefix *.
6. Thermal cap is on (`systemctl is-active indicagent-host-thermal-cap` = active).
7. Member 1d verdicts are fresh *, and taken after the nightly capture: `ops_capture_delivered.py` refuses ("wait for the nightly capture") while the last completed session's 1d bars are missing or under 90% of the session before it, because a verdict taken in that gap fails session_coverage for every name under 1,000 sessions and the data gate then refuses them (pilot 0e020c5a, 2026-11-25; todo 675). Freshness: the pin gate (`d2_landed`) refuses when the latest verdict of a member is older than `threshold.bar_integrity.report_max_age_hours` (30 h; `verdict_gate.load_report_max_age_hours`). The launcher counts the stale members (read-only SQL, `verdict_preflight` in `guarded_run_common.sh`) and prints the refresh command. The 06:00Z bar-reconciliation audit judges active names only; dead members' verdicts come from `scripts/ops/bars/ops_member_verdicts_1d.py --apply` (about 1.8 h measured 2026-11-25 (the judging checks sum to 47 min; the rest is the per-name reads; the report logs a progress line with an ETA about every 5% of names), one DB connection; `--symbols` does not narrow its whole-table lineage scan, so a one-name run still takes about 10 minutes), which has no timer: the owner of record is the operator of a pilot or stage launch, who runs the command the preflight prints (lead ruling 2026-11-24; a timer would join the quiesce set and the verdicts only matter right before a pin). Any pause of more than 30 h between the refresh and the pin gate repeats the refusal (pilot 7c5612f0, 2026-11-24: 11,350 of 12,857 members at 61.4 h).
8. Free disk comfortably above `disk_reserve_bytes` plus the plan's peak; the plan prints the table.

## Run
`setsid -f bash scripts/ops/corpus_pilot.sh <expected_rebuild_code_key_prefix> [commit_sha]` (the key prefix is `rebuild_code_key()` on the pinned commit). It: quiesces; `--new-run --data-gate-scope 1d`;
reads the run id; runs `--run-id <id> --through pilot` from the run's worktree (the corpus run walks only `--through feature_complete` until todos 670 and 671 exist: ic_measure cells count as attempts under E21, ledger 2026-11-24f) under `run_guarded` (watchdog:
STOP at 92 C, CONT at 80 C, TERM and ABORT at 100 C or 20 minutes paused); writes `rss_mb` of the whole process
group every 20 s; releases the timers on a clean exit (rc 0) or on a failure before the run exists, and holds them on any other exit once the run exists. Status lines go to
`logs/family10_run_status.txt`; the pilot's output to `logs/corpus_pilot_<run id>.out`; run log
`logs/corpus_rerun.log`.

Resume the same run (same pin, timers already held): `setsid -f bash scripts/ops/corpus_pilot.sh --resume <run_id>`. It repeats the status-file, workers, host, nightly-window and verdict preflights, refuses unless the run's worktree HEAD equals the `code_commit` recorded in `corpus_run` (a read-only query), runs `--run-id <id> --through pilot` from the run's worktree under the watchdog, releases the timers on exit 0 and holds them otherwise. Output: `logs/corpus_pilot_<run id>_resume.out`.

## Ticker ends: record the listing end first
An active member whose ticker ends (a merger, a rename, a delisting) needs a `listing_end` row before its 6th missing session: the 1d verdict judges it to the last completed session until then, and `proven_start_1d` turns false once session coverage over the proven span falls under the floor (BKH, 2026-11-24: passed with 5 trailing sessions missing, 0.99914; failed with 6, 0.99897), which refuses the data gate. `listing_end` is written by a migration only (append-only; pattern in migrations 609 and 616; reasons acquired, merged, taken_private, delisted). Then re-judge the name with `ops_member_verdicts_1d.py --symbols <name> --apply`. Todo 673 plans the nightly guard.

## Read after it ends
- `corpus_run.measured`: `pilot_seconds_1d_unit`, `extrapolated_seconds.stage_1d`, `pilot_bytes_per_row_1d`,
  `compression_ratio_measured`, `pilot_db_load`, `pilot_hmm_written_share` (todo 661 disclosure), and
  `summary.gates` (G1-G3, G4-G5, G6-objects).
- Peak `rss_mb` and the peak DIMM temperature from `logs/family10_dimm_temp.log` (the measurement that decides
  workers 4 versus 8).
- Pilot timing is a pessimistic bound (disclosure, run eca9e854, 2026-11-26). The pilot measures the whole pilot across resumes:
  seconds are the stage calls alone (the sample's setup is outside), the divisor is units loaded, and a stage_1d projection runs over
  every planned 1d unit. Two biases remain, both upward: a failed unit's compute stays in the numerator, and each stage call ends
  with a fixed `compression_bound` replan of about 600 s (todo 682) spread over the units that call loaded. On eca9e854 the
  recorded figures were written by the older code on the run's pin and are invalid: `pilot_seconds_1d_chunk` 16.5 and
  `extrapolated_seconds.stage_1d` 8,477 s divided one resumed invocation's 9 loaded units' time by all 63 chunks (units_total 63,
  units_skipped 54, units_loaded 9); `pilot_bytes_per_row_1d` 1,174.99 and `pilot_stored_per_spool` 0.4423 read the resumed
  invocation alone and understate by 10.7 and 10.9 percent (run-level maxima: 1,315.27 and 0.4962). The measured steady rate was 8
  units per 6.5 minutes at 4 workers; with the two fixed tails and setups taken out the replay gives 46.3 s per unit and about 6.8 h
  for 515 units, against 9.6 h from the recorded method. `compression_ratio_measured` (1.2426, a scratch-hypertable copy of the
  pilot rows) and the gates are sound. The corpus_run row is not edited.

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

## First IC measure at the scope-1d pin (todo 471)
- `setsid -f bash scripts/ops/ic_measure_launch.sh <run_id> <expected_rebuild_code_key_prefix>` drives the corpus run's `ic_measure` step (`services.corpus_rerun --run-id <run_id> --through ic_measure`) under the DIMM watchdog, with output in `logs/guarded_run/ic_measure_<run_id>.out`. It is a new launcher that sources `guarded_run_common.sh` and adds no function to it; the same landing replaces that file's `free -g` memory test with `mem_gate` (MemAvailable in kB against 40 GiB, exact GiB in the message).
- Preflights (all refuse loudly, status file): the run's recorded scope is 1d (so only 1d is measured); `alpha.ic.feature_block_columns` reads 16 from APR (never a flag; the live value was 32 on 2026-11-25; the lead sets 16 through `ConfigService` with a recorded reason after the four family 10 runs and before `--new-run`, because the run pins it; no launcher or worker writes it); `pilot` and `feature_complete` are `completed` for the run and `ic_measure` is not; the run worktree HEAD equals its recorded `code_commit` and `rebuild_code_key()` starts with the expected prefix; no corpus run, `ic_measure`, sweep recorder or rebuild process is live, and then `host_gate` (with its heavy-job list and the 40 GiB MemAvailable check), the IDENTICAL block 2 line, the verdict freshness check and the 04:40Z window. Timers are quiesced before the run and released after exit 0; on any other exit they stay held and the log says how to resume.
- `corpus_pilot.sh --check [--resume <run_id>]` prints every refusal a launch would meet, read-only and all at once: the host gate (segfault, DIMM, MemAvailable, disk, window, timers), the two APR keys, verdict freshness, then the runner's own `services.corpus_rerun --check` (with `--resume`: the run's pin checks, the pinned APR keys that moved since `--new-run`, and the stored units that would block the stage's units; without it: the main checkout must be at origin/main with no uncommitted tracked edits, since the check plans batch keys from the checked-out code and the launch pulls first, then `--new-run --check`, the data gate, d2_landed, the span plan's disk budget and the same blockers; only completed units block, a started or failed row holds no rows). It changes no state (no status line, no timer change, no run row; the runner's own log gains its startup lines) and exits 1 on any refusal. `PREFLIGHT_ONLY=1` belongs to `ic_measure_launch.sh` only: set on `corpus_pilot.sh` it launches the real pilot (run 04db3930, 2026-11-26). `ic_measure_launch.sh` runs the checks that read the database and the worktree, prints to the terminal and exits; it touches no timer and writes no status line. `RSS_CHECK=1 RSS_SYMBOLS_FILE=<25 names>` instead runs `ic_measure --tf 1d --dry-run` on those names under the watchdog and logs the peak `rss_mb` at the live width, then stops; record it in todo 471.
- Ledger 2026-11-24f holds the corpus chain at `feature_complete` until the sweep-cell writer (todos 670, 671) exists; this launcher does not lift that, so do not start it before the lead records the first IC pass and its cell count.

## Watchdog behaviour (fail closed, tested in `tests/unit/test_guarded_run_watchdog.py`)
- A poll that cannot read both DIMM sensors as numbers stops the group (`watchdog STOP: DIMM sensors unreadable`); three such polls in a row kill it (`ABORT ... DIMM sensors unreadable for 3 polls`, rc 143). A valid reading of 80 C or less resumes a stopped group; a pause over 20 minutes kills it.
- A kill is TERM, then KILL after 30 s if the group still has a live member, then a check that the group is empty (`watchdog escalated to KILL`, `ABORT ... still has live members after KILL`).
- `host_gate` also refuses while a corpus run, the feature rebuild, the sweep recorder or the member verdict refresh is live.

## Memory peak of each run (todo 681)
- Each guarded launcher re-executes itself in a transient systemd user scope (`systemd-run --user --scope -p MemoryAccounting=yes`), so the cgroup holds every process of the run, pool workers and orphans included. `run_guarded` reads the scope's `memory.peak`, `memory.swap.peak`, `oom_kill` and leftover processes after each job, on a normal exit, a watchdog kill and a launcher TERM, INT or HUP, and writes one status line (`run_resource workload=... stage=... memory_peak_gib=... oom_kill=... leftover_processes=... max_c=...`) plus `/var/lib/node-exporter-textfile/run_resource_<workload>_<stage>.prom` for node_exporter.
- Dependencies: a running systemd user manager. `loginctl show-user bg -p Linger` must read `Linger=yes` (enabled 2026-11-27), because with `Linger=no` the manager stops when the last session closes and takes the run's scope with it. The textfile directory must be writable by the launcher user.
- Refusals are loud and happen before the job starts: no user manager answering, no `memory.peak` in the new scope, or an unwritable textfile directory exits 3 with the reason in the status file. A report that fails after the job is logged as `WARN run_resource_emit failed` and never changes the job's exit code.
- Reading it: the peak includes page cache, so it is an upper bound on resident need. `memory_peak_bytes` is the scope's running maximum, so a launcher with several jobs (`family10_launch.sh`) reports an exact first stage and an upper bound for later ones; the one-job launchers (`corpus_pilot.sh`, `ic_measure_launch.sh`, `family10_block2_rerun.sh`) are exact. `oom_kill` counts the kernel OOM killer only. Exit code 143 is a TERM (the watchdog, including its KILL escalation, the launcher's own signal trap, or an operator); 137 with `oom_kill=0` is a SIGKILL from elsewhere (systemd-oomd, `cgroup.kill`). A nonzero `leftover_processes` is an orphaned worker.
- The host memory budget built from these peaks is in `docs/operations/operations-infrastructure.md` (Host memory budget); the cells for a heavy job and an I/O transfer fill in as the first real runs report.

## One-time live smoke of `hold_timers` (first quiet window after the pilot)
`hold_timers` and the service lookup behind `timers_gate` were tested against fakes only. Run this once, between 12:00 and 22:00Z, with no pilot, IC measure, rebuild or counted run live (about 10 seconds; the six timers are off for that long, none of them is due in this window).

Before: every blocking timer enabled and active, the dividend timer mapping to its template instance, and no record file.
```bash
cd /home/bg/dev/indicagent
for u in $(PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tAc "select json_array_elements_text(config_value::json) from config_state where config_key='infra.corpus_rerun.blocking_timers'"); do echo "$u $(systemctl is-enabled $u) $(systemctl is-active $u) -> $(systemctl show -p Triggers --value $u)"; done
ls logs/corpus_rerun_quiesce.json
```
Expected: six lines `<timer> enabled active -> <service>`, and `ls` reports no such file.

The smoke (status lines go to the terminal):
```bash
NOW_H=12 bash -c 'source scripts/ops/guarded_run_common.sh; STATUS=/dev/stdout; window_gate; timers_gate; hold_timers; echo "-- while held:"; for u in $(blocking_timer_units); do echo "$u $(systemctl is-enabled $u) $(systemctl is-active $u)"; done; ls logs/corpus_rerun_quiesce.json; exit 0'
```
Expected, in order: `quiesce`; `quiesced 6 timers; the prior set is in <repo>/logs/corpus_rerun_quiesce.json`; `-- while held:`; six lines `<timer> disabled inactive`; the record file path; then the exit trap prints `timers released (exit trap)` and `released: [...]` naming all six timers. Drop `NOW_H=12` if the real hour is already inside 05:00 to 24:00Z.

After: repeat the Before loop. Expected: six `enabled active` lines, and `ls logs/corpus_rerun_quiesce.json` reports no such file.

Failure branch (optional): repeat the smoke with `fail smoke-failure` in place of `exit 0`. Expected: the same release lines, `ABORT smoke-failure` in the output and exit code 3.

If a timer is left disabled: `.venv/bin/python -m services.corpus_rerun --release`; as a last resort `sudo systemctl enable --now <timer>` for each of the six. The smoke appends its status lines to the terminal only; nothing else is touched. Record the result in this section's commit message or the status file.
