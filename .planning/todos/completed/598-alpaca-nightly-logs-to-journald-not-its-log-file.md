---
claimable: true
status: completed
priority: P2
filed: 2026-11-06
source: lead (indicagent-4d), from the 596 re-ask run
---

# The Alpaca nightly never configures structlog; its debug lines go to journald

## What

`scripts/ops/bars/ops_bar_nightly.py` never calls `setup_service_logging(...)`, so structlog runs
on its defaults: every `bar_selection.session_choice` debug line prints to stdout, which systemd
sends to journald (and the 596 re-ask log grows about 47 MB/h, about 1 GB per session). CLAUDE.md:
logging is structlog to `logs/<snake_case_class_name>.log` via `setup_service_logging()`, never
journald, and never per-row logging in a full-corpus loop. The per-session line is per-row.

## Decision (lead)

Call `setup_service_logging()` in the nightly's entry point; demote or aggregate the per-session
selection line to one summary per (symbol, window). Small change; it lands with the next
nightly-area change, in its own worktree (timer-run code).

## Done when

The nightly writes to its own log file at info level, journald holds only the unit's start, stop
and summary, and a re-ask session's log stays under about 50 MB.

Claim note (lead 2026-11-27): timer-run code (the Alpaca nightly, 04:40Z); edit it only in a detached worktree off `origin/main` and land only CI-green. The six blocking timers are quiesced until the 1d IC measure completes, so land it before their release, never during a nightly run.

## Closed 2026-11-27 (claimed and landed by indicagent-03)

`main()` calls `setup_service_logging("logs/ops_bar_nightly.log")` before any work, so structlog writes at info to a 10 MB rotating file (three backups, under 50 MB) and the per-session `bar_selection.session_choice` debug line is filtered. A failed window is a `ops_bar_nightly.window_failed` warning in that file instead of a stdout line; journald keeps only the unit's start and stop and the one summary line. The per-session line was already at debug, so no demotion was needed. Tests: `tests/unit/scripts/test_ops_bar_nightly_logging.py` (fail against the old script).
