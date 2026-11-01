---
phase: 191-unified-raw-bar-table
plan: 25
subsystem: bars
tags: [tradier-retirement, ops-scripts, borrow-capture]
requires: [191-24]
provides: [ops scripts free of Tradier branches, migration 550 retired APR keys, todo 533 closed]
affects: [574]
metrics:
  completed: 2026-10-31
---

# Phase 191 Plan 25: ops scripts, the sweep and the phase close

## What landed

- **ops_source_policy.py:** the `--admission-sweep` arm (Tradier-vs-IBKR admission,
  `src/intelligence/bars/source_admission.py` its evidence judge) is deleted; the script keeps
  `--add`, scrub flags and selection. Its four action constants and two APR-key reads went with
  it (migration 550 retires the keys; 524 and 548 hold the recorded rows' history).
- **ops_data_bar_check.py:** the Tradier-history exclusion from condition 3
  (`late_name_dispositions`) is gone; every unresolved IBKR-sourced late name is named, the
  residue not a sample. `_stored_label` loses its special case.
- **ops_head_rerun.py:** dead Tradier branch removed.
- **Migration 550 (`550_retire_tradier_arm_apr.sql`):** retires the two
  `infra.tradier_delete.*` keys and the two
  `threshold.bar_integrity.tradier_admission_*` keys, history then state then schema, by
  literal key, idempotent. Applied live 2026-10-31 (verified: zero matching rows in
  `config_state`). Reader check in the migration header.
- **todo 574** records the owner's retention gate: `ops_tradier_delete.py`,
  `ops_tradier_residue.py`, its gate script and `source_admission.py` stay whole (dormant;
  the delete self-refuses on the raw read) until the 2026-11-12 backup retention date, then
  go with `data/backups/191/` and `ops_old_store_backup.py`. The boundary allow-list rows now
  point at 574 instead of 191-25. Migration 550's header matches this (source_admission
  retained dormant, not deleted).
- **Swap/basis research scripts:** `swap_1d_primary_measure.py` and `vendor_basis_study.py`
  were already gone on main (earlier plan); no caller remained.
- **Docs:** glossary `listing end` drops the `ops_tradier_residue.py` code surface;
  `databento-api.md`'s admission path now describes the measured-basis standard without the
  retired Tradier-era script.
- **Riding in the same batch (todo 438, separate concern):**
  `services/borrow_availability_capture.py` (BaseBatch oneshot, migration 549 hypertable,
  `IBKRProvider.fetch_borrow_snapshots` tick 236, systemd units, 20:30 UTC timer installed
  and active), `ops_head_rerun`'s and the fetcher's small cleanups, and the verification
  updates to todos 411, 421, 426, 485 (closed) and 509.

## The sweep

`grep -rliE tradier src services scripts tests docs/foundation`, classified:

- Accepted remainders per plan: the nine historical migration contract tests; the daily
  rule's policy admission tuple and route constants in `src/intelligence/bars/daily_rule.py`
  (d2-v3 still reads stored pre-D Tradier rows as data; not edited); fixtures documenting
  retired data; the `ops_d191q_arbitration.py` `_cfg` fallback (equal default 0.9, behavior
  unchanged); the 574-retained restore toolchain; foundation docs describing history.
- Everything else: comments and docstrings describing retired history, left as written.

## Close

- Todo 533 moved to completed; PRIORITIES row removed. Todo 519 stays open (IBKR side:
  PSKY/SKYD repoint waits on the owner's rescale-hold decision; the Tradier side of its
  story is settled by 191-20).
- Todo 485 closed (landed a23af3551, migration 545).
- ROADMAP phase 1 (191) marked complete.
- Gates: `tools/gate.py` green (unit suite, 32 files vs origin/main); /simplify ran as four
  review agents on the borrow capture with every finding applied; a second code review of
  the full batch returned eight findings, seven applied (ET-local timer calendar so the DST
  shift never moves the ask into RTH, one qualification retry before the whole batch stores
  NULL, loud duplicate-symbol refusal, empty-universe guard before the --limit slice, the
  corrected migration numbers in the ops docstring and the 457 contract test, five new
  provider unit tests for the batch loop), one rejected with evidence (the `migration:NNN`
  changed_by spelling is the current convention, migrations 545/547/548 all use it).

## Integration

The raw-first ingress contract, canonical-as-selection and the Tradier retirement hold
together end to end: no ops or research script names Tradier except the 574-retained record
scripts, the sweep leaves only accepted remainders, and `market_data_ohlcv` remains a pure
function of `ohlcv_raw` plus `bar_source_policy` (selection gate unchanged).
