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

## Build status 2026-11-28 (indicagent-b9)

Scope items 1 and 2 are built: `tools/harness_signals.py` with its user timer in `tools/systemd-user/` (not installed), tests in `tests/unit/test_harness_signals.py`, glossary entry `harness signal`.

- Sessions come from the records Claude Code keeps in `~/.claude/sessions/<pid>.json`, for every session whose cwd is one of the repo's git worktrees: name, status (`busy` working, `idle` waiting for input, `shell` running a shell command; only `idle` counts as idle) and since when. A session is gone when its pid no longer runs the recorded process (`procStart` against `/proc/<pid>/stat`). A malformed record is counted (`sessions_unreadable`), never fatal. Only names, statuses, counts and times are stored, never transcript content.
- Claims: open and stale counts from `tools/todo_claims.py`. CI: origin/main's sha after a fetch (`fetch_ok` recorded), its verdict, and the finished checks whose conclusion is not success, cancelled (a superseded push), skipped or neutral; a final verdict already logged for the same sha is reused, which saves the shared 60-an-hour GitHub quota. A red commit superseded within ten minutes is not seen (sampling).
- `--note <class> <text>` records an owner intervention or a review finding by class (`NOTE_CLASSES`: `owner_intervention`, `review_correctness`, `review_rule_breach`, `review_stale_doc`, `review_test_gap`).
- `--summary <days>` pairs activity (minutes per status, idle minutes per session and per covered hour) with outcome (landings and landings per day on origin/main, todos closed, P0 and P1 closed, median filed-to-closed days, each closed todo read as its closing commit wrote it), CI red commits and notes by class, and states its coverage: the share of the window the snapshots cover (a snapshot's state holds until the next or for two cadences, `CADENCE` bound to the timer unit by a test), the last snapshot's age, unreadable records and torn log lines. A dead or never-started timer reads as low coverage, never as zero idle time; judge idle per covered hour.
- Not a pipeline service: a user unit that reads files and git, never the database (a test runs the timer's entry point in a fresh process whose driver connect calls and Postgres sockets refuse), so no `_DAG_ORDER`, `_AGENT_ID_TO_UNIT` or `alert.lag.*` entry, like the sweep recorder. It emits `job_completed_total{job="harness-signals"}` and logs to `logs/harness_signals.log`.

Left:
1. [ ] Install the timer, on the lead's word (one heavy-job slot is unaffected: it is a few seconds of git and file reads every 10 minutes, one unauthenticated GitHub read each, 6 of the 60 an hour allowed):
   `mkdir -p ~/.config/systemd/user && ln -sf /home/bg/dev/indicagent/tools/systemd-user/indicagent-harness-signals.{service,timer} ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now indicagent-harness-signals.timer`
2. [ ] Scope 3: the lead loop's orient step runs `tools/harness_signals.py --summary 1` (a CLAUDE.md line: owner veto); the lead notes owner interventions and review findings with `--note`.
3. [ ] First retro after seven days of data (about 2026-12-05 if installed on 2026-11-28).
4. [ ] Judge the 1850fb596 prediction on 2026-12-11 (14 days) against the 2026-11-27 baseline recorded above (two owner pokes, two of four sessions idle): `--summary 14`, idle minutes and `owner_intervention` notes, read with landings and P0 and P1 closed. The baseline itself was not logged, so it stays the counted figure written here.
