---
status: pending
priority: P2
filed: 2026-11-26
source: design review of the per-job memory and temperature request (lead brief 2026-11-26); read-only reads of src/observability, scripts/ops/guarded_run_common.sh, corpus_pilot.sh, production/, an AST-only import_closure run and one 300 MiB cgroup probe, no edit to code
---

# Per-run memory peak from the run's cgroup, and a host memory budget

## What

No run exposes its own memory peak. `process_resident_memory_bytes` exists only for the exporters; the guarded launchers log `rss_mb` of the process group every 20 s into `logs/family10_dimm_temp.log` (`run_guarded`, `scripts/ops/guarded_run_common.sh`), which misses any spike between polls and counts copy-on-write pages shared by forked ProcessPoolExecutor workers once per worker. The unit suite, battery runs started by hand and any job outside a guarded launcher record nothing. The owner wants a memory budget for ubuntu1 (a mini PC, 59 GiB usable; DIMMs at 117 C on 2026-11-23 under a 16-worker run), and the budget needs one measured peak per workload.

End state: every heavy run leaves its true peak (all processes of the run, orphans included, a SIGKILLed child included) in Prometheus and in the status file, attributed to workload, stage and run id; a Grafana panel puts it beside the node_exporter DIMM temperature and MemAvailable for the same window; a measured budget table replaces the guessed 40 GiB launch floor.

## Requirement check (Musk step 1)

- "A new Ring 0 Python module exporting through OTLP": dropped. The peak is a kernel cgroup counter that a surviving parent reads after the job dies; no Python, no SDK, no flush. An in-process call would sit in hashed modules, and a one-shot OTLP gauge must flush before exit (lost on SIGKILL) and is expired by the collector's Prometheus exporter a few minutes later.
- "DIMM and CPU temperature at run start and end": dropped. node_exporter already scrapes every hwmon sensor at 15 s and `production/alertmanager-rules.yml` already alerts on them; the run's start and end timestamps are enough for `max_over_time` over the window, and the watchdog's own readings are in `family10_dimm_temp.log`.
- "A Prometheus recording rule for per-job peak": dropped. A rule cannot express a per-run window, and the exported value is already the per-run answer.
- "Worker-child totals": kept, for free. The cgroup counts every process in the scope once, pool workers and orphans included.
- "A run-status line reading the same series": kept, but it reads the cgroup directly at exit, not Prometheus, so the line exists even when Prometheus is down.
- "A host memory budget doc": kept, as a section of `docs/operations/operations-infrastructure.md` (host facts already live there), not a new file; `operations-memory-performance.md` is the agent-memory subsystem, a different concept.

## Design

Concept `run_resource`. Each run executes in its own transient systemd user scope (`systemd-run --user --scope --collect -p MemoryAccounting=yes`); the process that stays alive after the job exits (the launcher for guarded runs, a thin wrapper otherwise) reads the scope's `memory.peak`, `memory.swap.peak`, `memory.events` (`oom_kill`) and the processes left in `cgroup.procs`, then writes one node_exporter textfile per workload (temp file plus `mv`, the `production/standby/standby_probe.sh` pattern) and one status line. This fits the DAG because telemetry stays at the edge and out of process (no compute module changes, `pure_compute` holds), and it holds at 10x because the cost per run is one scope and one file, and the live series count is bounded by the number of workloads, not runs.

Facts checked 2026-11-26:

- cgroup v2 with the memory controller delegated to the user manager (`user@1000.service` `DelegateControllers=cpu memory pids`); systemd 261; kernel 7.3, so `memory.peak` exists.
- Probe: a child allocating 300 MiB and SIGKILLing itself inside a user scope left `memory.peak` = 304 MiB, readable by the surviving parent shell (exit 137 seen). A killed run still leaves its peak.
- `Linger=no` for bg: the user manager stops when the last session closes and takes its scopes with it. Enabling linger (`sudo loginctl enable-linger bg`, reversible, `sudo -n` works on this host) is a precondition of part B.
- `/var/lib/node-exporter-textfile` exists, owned by bg, mounted into node-exporter (`production/docker-compose.yml:111-114`).
- Closures (`src/core/code_identity.py:import_closure`, AST only): `services.backfill_feature_factory` (69 modules), `services.ic_measure` (91) and `services.corpus_rerun` (119) hold `src.observability.metrics`, `src.observability.otel` and (the last two) `src.observability.corpus_manifest`; `src.intelligence.research.runner` and `null_battery_volume_shock` hold no `src.observability` module. `tools/` and `scripts/` are not first-party packages, so a shell tool is in no closure. `src/observability/` has no `__init__.py`: never add one, since an `__init__` enters every closure that imports `metrics` as an ancestor and moves every pin.
- The launch gate is in `scripts/ops/guarded_run_common.sh` (`mem_gate`, `MEM_FLOOR_KB` 40 GiB); there is no `f10_common.sh`.

Series (gauges, textfile, prefix `run_resource_`): `memory_peak_bytes`, `swap_peak_bytes`, `oom_kill`, `leftover_processes`, `exit_code`, `start_timestamp_seconds`, `end_timestamp_seconds`; labels `workload`, `stage`, `run_id` (never `job`, which Prometheus renames to `exported_job` on the node scrape). One file per workload (`run_resource_<workload>.prom`), overwritten by its next run: at most about 50 live series, one new short series per run in the TSDB.

Known limits, disclosed in the doc: `memory.peak` includes page cache charged to the scope, so it is an upper bound on resident need; Postgres backend memory used for the run's queries is charged to the database container, not the scope, so the budget counts it in its own row (host MemAvailable minimum over the run window covers the sum); a `kill -9` of the surviving parent loses that run's file and the 20 s `rss_mb` log is the fallback; a host reboot loses both.

Shadow first: no `MemoryMax` until part D has measured each workload once; then the cap is an APR key (`infra.run_resource.memory_max_bytes`, read by the launcher like `infra.corpus_rerun.blocking_timers`) set from the measured peak, so a runaway job is killed loudly inside its scope (exit 137, `oom_kill` 1) before the host swaps or the kernel kills Postgres.

## Split

Classes: (b) edits a module in a hashed closure, hold until no fingerprinted run is live or resumable; (h) not hashed but read by a live launcher (bash reads a running script as it executes), hold until the launchers are quiet; (c) safe now. No part is class (b).

| Part | Scope | Class | Owner | Gates |
|---|---|---|---|---|
| A | `tools/run_resource.sh`, sourceable and executable: `run_resource_scope` (re-exec into a user scope, refuse loudly with exit 3 when `systemd-run --user` fails), `run_resource_emit <workload> <stage> <run_id> <rc>` (read the scope files, write the textfile atomically, print the status line), and a wrapper mode `run_resource.sh <workload> <stage> <run_id> -- cmd...` that runs the command in its own process group, forwards TERM and INT to it and emits on every exit. `CGROUP_ROOT` and `TEXTFILE_DIR` overrides, like `DIMM_HWMON_ROOT`. Tests in `tests/unit/` against a fake cgroup tree and a temp textfile dir (peak, SIGKILLed child, oom_kill, leftover process, refusal without a user manager). Add `run_resource_` to `EXPORTER_PREFIXES` in `tests/unit/observability/test_alert_and_dashboard_metric_refs.py`. | c | worker | `bash -n`; the new test and the metric-refs test by exit code; `/simplify`, `/review`; one real wrapped `pytest tests/unit/ -n auto` writes a file node_exporter serves |
| B | Lead enables linger. `guarded_run_common.sh` sources `tools/run_resource.sh`; each launcher calls `run_resource_scope` first, and `run_guarded` calls `run_resource_emit` on the normal path, the watchdog-kill path and inside the launcher's TERM, INT and HUP trap; the existing exit lines (`pilot exit=$rc ...`) gain `memory_peak_gib`, `swap_peak_gib`, `oom_kill`, `leftover_processes` and the max `max_c` of the run's `family10_dimm_temp.log` lines. The watchdog's process-group model is unchanged. | h | worker, after the pilot, `stage_1d` and the 471 IC measure launchers have exited and none is resumable | `tests/unit/test_guarded_run_watchdog.py` plus the part A test by exit code; `bash -n` on every launcher; one smoke of `run_guarded` on a dummy command under a fake hwmon tree; `/simplify`, `/review` |
| C | `production/grafana/dashboards/operations.json`: a table of the last run per workload (peak, swap peak, oom_kill, leftover processes, exit code, start, end) and a time series of the spd5118 temperatures and `node_memory_MemAvailable_bytes` with run windows from the start and end series. Two rules in `alertmanager-rules.yml` with a promtool test file like `alertmanager-rules.dimm.test.yml`: `RunOomKilled` (`run_resource_oom_kill > 0`) and `RunLeftoverProcesses` (`run_resource_leftover_processes > 0`, the orphaned-worker case in `docs/reference/gotchas.md`). | c, after A has written one real file | worker | metric-refs test; promtool rule test; Grafana reload shows the panel with the part A file |
| D | Budget section in `docs/operations/operations-infrastructure.md` (host paragraph): rows for kernel and OS, Postgres (`shared_buffers` 14 GB, `work_mem` 256 MB times active hash and sort nodes), the other containers (redpanda `mem_limit` 6g), one heavy compute job (measured peak at 4 workers and the per-worker slope from one 8-worker run when the owner raises workers), one I/O-only transfer, headroom; the derived launch floor compared with the 40 GiB `MEM_FLOOR_KB`, and the `MemoryMax` value for the APR key. Measured, never estimated: one run each of the pilot, `stage_1d`, the IC measure, a battery block and the unit suite. | c (docs), after B has measured those runs | lead | `test_doc_schema_numbers.py`, link integrity; the floor change, if any, is a part B style edit under class h with its own gates |

## Rejected

- Python module in `src/observability/` with OTLP gauges: needs an in-process call in hashed code or a separate emitter; a one-shot gauge must flush before exit and is lost on SIGKILL; the peak still has to come from the cgroup.
- `/usr/bin/time -v`: its max RSS is the largest single descendant, not the pool sum, and it reports only when `time` itself exits normally.
- A `/proc` sampling sidecar: already exists as the 20 s `rss_mb` log; it misses spikes between polls and double counts shared pages; kept only as the fallback.
- A systemd service unit with `MemoryMax` for guarded runs: moves the job out of the launcher's process group, which the tested STOP, CONT and TERM watchdog relies on; a scope keeps the group and takes `MemoryMax` too.
- A system scope through `sudo systemd-run`: sudo may start the command on a new pty and session, which breaks the group model; the user scope needs no root.
- A recording rule and start and end temperature gauges: see the requirement check.

## Gates

Each part: `/simplify`, `/review`, its tests by exit code (never a tail), independent review before push. Part B waits for quiet launchers; no part edits `src/`, `services/` or any module in a pin closure. Run `import_closure` on the three service entries before landing A and B and confirm `tools.run_resource` is absent (it cannot appear: `tools/` is not a first-party package).

## Done when

Every guarded launcher and the wrapped unit suite leave a `run_resource_<workload>.prom` and a status line with the true peak, including a watchdog-killed run; the Grafana panel shows the last run per workload against DIMM temperature and MemAvailable; the budget section holds one measured peak per workload and a ruled `MemoryMax`.
