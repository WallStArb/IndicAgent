---
status: pending
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
