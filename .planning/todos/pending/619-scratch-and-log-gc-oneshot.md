---
status: pending
priority: P3
filed: 2026-11-15
source: owner request 2026-11-15 ("clean like Renaissance requires"), after a manual sweep freed about 25 MB and found the rest protected
---

# Scheduled garbage collection for logs, scratch and finished worktrees

## What

Clutter accumulates faster than hand sweeps remove it: rotated logs, `data/scratch/<todo-id>` dirs, `.planning/tmp`, and worktrees of finished workers (ten worktrees today, six with unlanded commits). A manual sweep on 2026-11-15 removed about 25 MB; the large items (`logs/phase179`, `logs/phase181` at 1.4 GB, `logs/massive_step7` at 718 MB) are protected evidence, so the sweep had to be judged by hand each time. The decision rule is mechanical enough to automate; the protection list is the part that must be explicit.

## Scope

1. One oneshot leaf `ops_scratch_gc` plus a daily timer, dry run by default, `--apply` from the timer once the dry run has matched a hand sweep. Registered in `_DAG_ORDER` and `_ONESHOT_UNITS`, metric `job_completed_total{job, status}`, a per-class summary line (files and bytes removed, files skipped and why).
2. Classes and rules, each window an APR `infra.scratch_gc.*` key (provenance `[initial_estimate]`):
   - Rotated logs (`logs/*.log.N`, `*.gz`) older than the retention window.
   - `data/scratch/<id>` and `.planning/tmp` entries older than the window whose id has no open todo in `pending/` and no reference in `.planning/STATE.md`.
   - Worktrees under `.claude/worktrees` and the sibling `wt-*` dirs: remove only when clean, unlocked, no commits absent from `origin/main` by `git cherry`, and not the cwd of a `ListAgents` peer; list (never remove) the rest in the summary.
3. Protection list, a JSON APR key read at init, never overridable by a flag: `logs/phase179`, `logs/phase181` (read by `repro_frozen`), `logs/massive_step7*` until runbook Part F closes, `data/massive`, `data/ibkr`, `data/backups`, `cache/*checkpoint.json`, and any path held open by a running process (`lsof`/`/proc` check) or named in a live `setsid` job's arguments.
4. Test: a fixture tree proves each class removes only what the rule allows and that every protected path survives with `--apply`; a guard test fails if a path read by `repro_frozen` is not on the protection list.
5. Runbook paragraph in `docs/operations/` (what it removes, how to protect a path, how to read the summary).

## Gates

- Dry run on the live tree lists no protected path and no worktree with unlanded commits.
- Standard code gate (`/simplify`, `/review`, unit suite exit code); no edit to a module a live fingerprinted run imports.
- Independent review of the protection list against `docs/reference/gotchas.md` and the step 7 runbook before `--apply` is enabled.

## Boundaries

Never deletes tracked files, raw data, backups or anything under `data/massive`. Never removes a dirty, locked or unmerged worktree. Tracked-file cleanup stays with the repo-simplify lane. Musk step 1: if the dry run shows under 100 MB per month of removable clutter, close this as unneeded and keep the hand sweep in the lead loop.
