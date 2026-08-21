# 315 - `regime_writer.log` rotates every ~7-15min (unknown trigger), stranding the process's fd on a deleted inode

**Filed:** 2026-08-14
**Source:** Found live while babysitting the 5th `regime_writer` relaunch (post-todo-312/314 fix
verification). Two Monitor stall-watchdog alarms fired ("`logs/regime_writer.log` has not grown
in 15 minutes") that were both false positives -- confirmed via py-spy (active `hmmlearn`/`einsum`
stack) and by tailing the process's actual fd (`/proc/<pid>/fd/4`, which was seconds-fresh both
times) that the run was healthy and progressing normally.

**Root cause of the false alarms:** `logs/regime_writer.log*` has been rotating every ~7-15
minutes all evening (`.log` -> `.log.1` -> `.log.2` -> `.log.3`, confirmed via `stat` mtimes ~7-15
min apart), nowhere near the daily cadence in `production/indicagent-logrotate.conf` (confirmed
via `systemctl list-timers`: `logrotate.timer` next fires 00:30 EDT, hours away). Nothing in
`scripts/` or `production/` calls `logrotate` manually (`grep -rn logrotate` came up empty
outside the conf file itself). Trigger not yet identified -- candidates not yet ruled out: a
Monitor/watchdog implementation detail (some watchdogs may rotate/truncate a log as part of
bounding how much they re-read each poll), a concurrent session, or a separate cron/script not
yet found.

**Consequence, worse than the noisy alarms:** because nothing signals `regime_writer`'s Python
process to reopen its log handles after a rename, its stdout/stderr fd (`fd1`/`fd2`, from the
wrapper script's `>> logs/regime_writer.log` shell redirection) stays pinned to whatever inode
existed at process start. Confirmed via `lsof -p <pid>`: that inode is now unlinked ("(deleted)")
after `rotate 3` cycled past it, meaning further rotations before the process exits will destroy
that data permanently -- including any future crash traceback, since Python's default behavior on
an uncaught exception writes to stderr. The process's *actual* live-appending stream turned out to
be a separate internal file handle (`fd4`, likely `setup_service_logging`'s own `FileHandler`,
possibly reopened by path on some cadence) that tracks whichever generation is currently named
`logs/regime_writer.log` at any instant -- this is the one with real, fresh content; `fd1`/`fd2`
are the ones actually stuck and losing data.

**Status:** pending, P2 -- not blocking the current relaunch (confirmed healthy via the real fd),
but will keep generating false stall alarms on every future long batch job that logs this way, and
risks silently losing stderr/crash-traceback output the next time this pattern recurs during an
actual failure (exactly when that output matters most).

## Scope

1. Find the actual trigger for the ~7-15min rotation cadence -- check whether the Monitor tool's
   stall-watchdog polling implementation itself rotates/truncates target logs, before assuming an
   external cron/script.
2. Decide the fix shape: either (a) stop whatever is rotating this file mid-run, or (b) make
   `regime_writer`'s logging setup rotation-safe (e.g. `WatchedFileHandler` instead of a plain
   `FileHandler`, so a rename is detected and the file reopened by path automatically) -- (b) is
   probably the more durable fix since it protects against *any* future rotation trigger, known or
   not.
3. Audit whether `setup_service_logging()` (`src/core/service_utils.py`) uses a rotation-safe
   handler already for the stream that ended up on `fd4` in this incident, and if so, why `fd1`/
   `fd2` (the shell-redirected stdout/stderr) didn't get the same protection -- likely needs the
   wrapper script itself to stop using `>>` redirection and rely solely on the app's own handler.
4. Once the trigger is found: confirm no other long-running batch service (`ic_engine`, corpus
   pipeline scripts) sharing the same wrapper-script `>>`-redirection pattern has the same
   exposure.

## Where

- `logs/regime_writer.log*` -- the file exhibiting the fast rotation
- `production/indicagent-logrotate.conf` -- the (uninvolved) daily rotation config, ruled out as
  the trigger
- `src/core/service_utils.py` -- `setup_service_logging()`, likely home of the eventual fix
- Whatever wrapper script launched the 5th relaunch (`>> logs/regime_writer.log 2>&1` shell
  redirection pattern) -- the other half of the exposure

## Closed 2026-08-21

**Scope item 1 (trigger) resolved.** `setup_service_logging()` (`src/core/service_utils.py`)
uses stdlib's `RotatingFileHandler(maxBytes=10 * 1024 * 1024, backupCount=3)` --
a **size**-based rotation, completely independent of `production/indicagent-logrotate.conf`'s
daily cadence, Monitor, or any cron. The "~7-15min, trigger unidentified" cadence this todo
opened with is just `regime_writer.py`'s own log volume organically hitting the 10MB
threshold during a busy run -- confirmed by direct read of the handler config, not
inferred. `ic_engine.log` was checked live for comparison (same `setup_service_logging()`
call, same corpus run currently in progress) and shows clean ~daily rotation siblings with
matching mtimes -- consistent with lower log volume per unit time not hitting 10MB as
often, not a different mechanism.

`RotatingFileHandler.doRollover()` already reopens its own stream correctly after every
rotation -- that's the `fd4` this todo's incident narrative already identified as "the one
with real, fresh content." The genuinely broken half is any **external** shell-level `>>`/`>`
redirect onto the same path (opened once at process start, e.g. a manual
`nohup ... >> logs/regime_writer.log 2>&1 &`) -- confirmed no checked-in script or systemd
unit does this (`ops_corpus_pipeline_run.sh`'s own `run_step` wrapper redirects to a
separate, uniquely-timestamped `step2_regime_writer_<timestamp>.log` instead, so the
scripted path was never actually exposed -- only ad-hoc manual invocations redirecting
straight onto `logs/regime_writer.log` are).

**Scope item 2 (fix) landed, scope items 3-4 (audit other services) resolved as a side
effect of the fix's own location, not separately.** Rather than patch the wrapper-script
half (impossible to close for *every* future ad-hoc manual invocation), fixed the other
side of the gap: Python's default `sys.excepthook` writes an uncaught exception's
traceback straight to `sys.stderr`, bypassing `RotatingFileHandler` entirely -- exactly
the one thing a stale shell-redirect fd could still lose, and precisely the moment it
matters most (a crash). `setup_service_logging()` now installs a `sys.excepthook`
replacement that routes the traceback through the same rotation-safe logger (landing
reliably in whichever generation is currently `regime_writer.log`), then still calls the
original hook (preserves the stderr print for a live terminal -- durable addition, not a
behavior change for anyone watching interactively). `KeyboardInterrupt` explicitly
excluded from the crash-log path (operator-initiated, not a real failure).

Because the fix lives in the shared Ring 0 `setup_service_logging()`, it automatically
covers every consumer -- confirmed `ic_engine.py`, `regime_writer.py`, and
`forward_return_writer.py` all call it -- closing scope item 4 without a separate
per-service audit. Zero risk to the live corpus run: source-level changes don't affect an
already-running process's loaded code, and the fix takes effect on each script's *next*
invocation (including the watcher's queued `--from-step 4` recompute for `ic_engine.py`).

**New test coverage added where none existed before** -- `setup_service_logging()` had
zero dedicated tests prior to this fix. New `tests/unit/core/test_service_utils_logging.py`
(6 tests): excepthook installation, idempotency (second call doesn't reinstall), the
actual bug this fixes (an uncaught exception reaches the log file), the original hook
still fires (stderr preserved), `KeyboardInterrupt` isn't logged as a crash, and normal
log statements are unaffected. One incidental fix needed to make the tests hermetic:
`logging.basicConfig()` is itself a separate "first call in the process wins" global
independent of this module's own `_configured_log_file` guard -- added `force=True` so
each test's setup call actually reconfigures the root logger; zero production behavior
change since `_configured_log_file`'s own guard already ensures `basicConfig()` only
ever runs once per real process. Full `tests/unit/` suite green (no regressions),
ruff/black clean.
