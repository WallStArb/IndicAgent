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

## 2026-11-01 (later): the owner chose KEEP, Option A; the restore is done

Owner decision 2026-11-01: the Tradier-era history is KEEP, Option A — the raw backups
restore into `ohlcv_raw` before the retention date, and this todo then proceeds as written
(the backups and toolchain, now including `ops_tradier_restore.py`, are removed on
2026-11-12; the raw rows are the permanent record).

Restore (scripts/ops/bars/ops_tradier_restore.py, through `persist_chunk_atomically` under
`bar_derivation_writer`, rows grouped by original (served_at, request_id)):

- `ohlcv_raw` vendor='tradier': **7,140,397 rows** restored; live count equals the manifest
  exactly (1,529 symbols, kind `consolidated`, timeframe 1d, spans 2000-01-03 .. 2026-10-06).
- `ohlcv_revision`: **155,350 rows** restored as lineage (the tradier-predicate delete
  backup; other-vendor rows under tradier loads stay out per T-191-45).
- `ohlcv_coverage`: **1,529 ledger rows** recomputed by `refresh_1d_bounds` for provider
  tradier (2000-01-03 .. 2026-10-06, row count sums to 7,140,397 — raw and ledger agree).
- `market_data_ohlcv` backup deliberately NOT restored: canonical is a selection;
  bar_source_policy does not select tradier. `ops_selection_gate.py --compare` run after the
  load (result recorded below when it returns).
- H spot check: **4,435** daily rows back, 2006-07-19 .. 2026-10-06 — exactly the rows the
  191-20 delete removed.

Corrected magnitude (coordinator measurement, supersedes this todo's "only copy of the era"
framing): IBKR 1d raw is itself deep (earliest 1998-12-28; 628 names start 2000 or earlier;
median first year 2005), so the restore's value is that **166 of 1,432 names start strictly
earlier in Tradier**, about 54 of them by a decade or more, concentrated in the todo 433
venue-move class (APP 2000 vs 2021, CR 2000 vs 2023, EVRG 2000 vs 2018, BRSL 2000 vs 2015).
The load ran batched alongside the 534 campaign (no fetcher pause), disk never below 381G
free, and the per-chunk coverage refresh was replaced by one end-state refresh after the
first attempt measured 89k rows in 8 minutes.

Selection gate (`ops_selection_gate.py --compare`, finished 2026-11-01T18:58Z after a
1h43m derive on the rebuild-loaded host): **0 real differences across 349,496,830 canonical
rows** (1m: 9,775,958 == ; 5m: 339,720,872 == ; 1,762 series, 0 with real differences,
0 unmapped canonical rows, 0 unselected slots). Canonical is a pure function of raw plus
policy, and the restore changed neither the selection nor any consumer. The 2 unreviewed
basis flags are the known ETHA 3.0x wrong-basis restatements (todo 573 class 3), unrelated
to the restore.
