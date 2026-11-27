---
status: pending
priority: P2
filed: 2026-11-27
source: owner ruling 2026-11-27 (harness improvement SOP is a core SOP), docs/foundation/harness-improvement-sop.md
---

# Harness signals logger and the first lead retro

## What

Step 1 of `docs/foundation/harness-improvement-sop.md`: the harness records its own signals so harness changes are judged on evidence. Today none of them is recorded; the 2026-11-27 idle sessions were seen only because the owner looked.

## Scope

1. A read-only logger (`tools/harness_signals.py`, run by a user timer every 10 minutes) appends one JSONL line per run to `logs/harness/signals.jsonl`: UTC time, each session from `ListAgents`-equivalent state (name, busy, idle at a shell, gone), open claims and stale claims from `tools/todo_claims.py`, the CI status of `origin/main` from `tools/ci_status.py`. Never writes the database, never touches a run.
2. A `--summary <days>` mode: idle-session minutes, landings on `origin/main` (commits per day) and todos closed, CI reds. Owner interventions and review findings are logged by the lead with `--note <class> <text>`, since no tool can see them.
3. The lead loop runs the summary in its orient step and holds the first retro after seven days of data.
4. First prediction to judge: pull-based claiming (`1850fb596`) lowers idle-session minutes and owner interventions over the next 14 days against the 2026-11-27 baseline (two pokes, two of four sessions idle).

## Gates

/simplify and /review; unit tests for the summary on planted JSONL; the logger is read-only (a test asserts no DB connection). Timer unit reviewed before install.

## Not blocking

Nothing on the counted-test path waits on this.
