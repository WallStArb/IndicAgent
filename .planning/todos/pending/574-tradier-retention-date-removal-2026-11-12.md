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
  `scripts/ops/bars/ops_tradier_residue_gate.sh`, `scripts/ops/bars/ops_tradier_restore.py`
  (the 2026-11-01 restore driver; a restore script that outlives its purpose is an orphan) and
  `src/intelligence/bars/source_admission.py`
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

## 2026-11-01: the backup holds the only copy of Tradier-era daily history; owner decision required before deletion

Traced 2026-11-01 while running down the symbol H load-ledger anomaly (benign: the 4,435 missing
H 1d rows are exactly the 191-20 Tradier delete; they survive only in
`data/backups/191/tradier_market_data_ohlcv_2026-10-28.csv.gz`):

- For some names the Tradier 1d history is materially deeper than IBKR's (H: Tradier from
  2006-07-19, IBKR smart_trades from 2009-11-05). That era survives nowhere else; the vendor no
  longer serves it (account unfunded by owner decision 2026-10-07).
- The owner's raw-coverage target (2026-10-31: deepest daily per name; history depth beats
  freshness) values exactly this data. Deleting the backups on 2026-11-12 as this todo plans makes
  it unrecoverable forever.
- Option A (recommended by the coordinator): before 2026-11-12, restore the raw CSVs into
  `ohlcv_raw` under `vendor='tradier'` (last-wins ingress, revision log; raw capture law 528,
  nothing a vendor served is dropped). Canonical stays D-191-Q untouched: `bar_source_policy`
  does not select tradier, so `market_data_ohlcv` and every consumer are unchanged, and the
  selection gate still proves canonical is a pure function of raw plus policy. Then this todo
  proceeds as written (backups and toolchain still removable on the date; the raw rows are the
  permanent record).
- Option B: confirm the deletion; the pre-IBKR Tradier era is discarded. 574 then runs as written.

Either way this todo cannot run before the owner answers. The restore toolchain
(`ops_tradier_delete.py` restore path, `ops_old_store_backup.py`) stays whole until then, which
this todo already requires.
