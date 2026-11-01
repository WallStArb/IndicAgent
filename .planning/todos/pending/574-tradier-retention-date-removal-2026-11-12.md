---
status: pending
priority: P2
filed: 2026-10-31
source: plan 191-25 execution; the retention gate the key readers recorded when plan 191-18 landed
---

# Tradier retention-date removal: on or after 2026-11-12

The Tradier deletion (plan 191-20) is undoable until its backup retention date. The restore
toolchain stays whole until then; this todo removes it in one pass. Everything here is gated on
2026-11-12 and must not land earlier:

- delete `scripts/ops/bars/ops_tradier_delete.py`, `scripts/ops/bars/ops_tradier_residue.py`,
  `scripts/ops/bars/ops_tradier_residue_gate.sh` and `src/intelligence/bars/source_admission.py`
  (dormant since the sweep arm left `ops_source_policy.py` in plan 191-25; it keeps the
  restore-path evidence judge whole until this date);
- remove `data/backups/191/` and `scripts/ops/bars/ops_old_store_backup.py`;
- remove the allow-list entries and `_PENDING_RETIREMENT` rows that name this todo (the five
  boundary files' `ops_tradier_delete`/`ops_tradier_residue` rows and the two
  `infra.tradier_delete.*` rows in `test_table_and_apr_key_readers.py`);
- note: migration 548 (2026-10-31) already retired the two `infra.tradier_delete.*` APR keys, so
  the script reads its defaults if it ever runs before this date; it self-refuses on the raw read
  first (no Tradier rows exist), so that path is unreachable without a backup restore.

Done when: the four files, the backup directory and the backup script are gone; the five boundary
files and the key readers hold no entry naming this todo; the full unit suite is green.
