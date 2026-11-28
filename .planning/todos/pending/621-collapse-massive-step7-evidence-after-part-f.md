---
status: pending
priority: P3
filed: 2026-11-15
source: cleanup review 2026-11-15; follow-up of 619
---

# Collapse logs/massive_step7 to a summary card after Part F

## What

`logs/massive_step7` is 718 MB (plus the dated `massive_step7_*` dirs): `partc_c5.log` 179 MB, `unexplained_20261114` 263 MB, three `delta*` dirs at about 57 MB each, plus gate and review dirs. Step 7 is live (the 5m rebuild runs against `rebuild_state.json`), so nothing here is removable now. After step 7 Part F closes, the record is the evidence README and the sha256 files, not the full dumps.

## Scope

1. Wait for Part D to pass and Part F to run (`docs/operations/massive-step7-runbook.md`); the rebuild and `rebuild_state.json` are out of scope until the run is closed.
2. Write the step 7 summary card: counts per timeframe, the gate results (`b4_gate_20261115_rerun`), the problem-name disclosure, the identity map version, and the sha256 of every file the card cites.
3. Keep: `*.sha256`, the README, `delta` (D1 verifies against it, and the runbook says to keep it unchanged), the gate and review outputs the card cites. Delete: `partc_c5.log`, `unexplained_*`, `delta_pre_reopen_*`, `delta_stale_*`, the `a3`/`a5`/`witness_rerun` dirs once the card holds their numbers.
4. Verify by grep that nothing in `src/`, `scripts/`, `tests/`, `docs/` or `.planning/` reads a path before it is deleted.

## Gates

- Part F complete and the lead rules the collapse.
- Every deleted path is absent from the card's citations and from a repo-wide grep.

## Boundaries

No deletion while any step 7 writer, timer or resumable job is live. The IBKR raw rows are handled by Part F, not here.

## Status 2026-11-24 (todo consolidation pass)

Part F is closed (eb734e451). `logs/massive_step7` is 1.2 GB; no top-level README exists. 619's remaining scope is folded in here.

## Status 2026-11-28 (housekeeping pass)

Compressed in place, content kept (gzip, reversible with `gunzip`): `partc_c5.log` is now `partc_c5.log.gz` (423 MB to 13 MB), and `switch_losses.csv` in `delta_stale_20261113` and `delta_pre_reopen_20261115` is now `switch_losses.csv.gz` (57 MB to 7 MB each). `logs/massive_step7` is 620 MB. The summary card and the lead's collapse ruling are still open; `unexplained_20261114` is untouched because the runbook commands name its CSVs.
