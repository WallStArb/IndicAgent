---
status: closed
closed: 2026-11-12
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

## 2026-11-09 prep: the verified execution runbook

Every path below was verified on disk, every reference class grepped repo-wide, and the DB
state read on 2026-11-09. Execution on 2026-11-12 is mechanical: top to bottom, no
judgement calls. Corrections to this todo's own text are marked **[correction]**.

### Pre-verification gate (all five, on the day)

1. The date is on or after 2026-11-12.
2. Permanent record intact: `SELECT count(*) FROM ohlcv_raw WHERE vendor='tradier'`
   returns 7,140,397 (verified 2026-11-09; equals the restore manifest exactly).
3. No Tradier restore activity since the 2026-11-01 verification: the last Tradier commit
   is `492280b25` ("the Tradier restore is verified"); `git log -i --grep=tradier
   --since=2026-11-02` must still be empty.
4. The residue report exists:
   `.planning/phases/191-unified-raw-bar-table/191-TRADIER-RESIDUE.md`
   (generated 2026-10-28 by `ops_tradier_residue.py`; the no-Tradier proof).
5. `data/backups/handoff-2026-11-07/` exists and is NOT touched by anything below (it
   holds the 186-31 WIP patch).

### Step 1: scripts and their tests (git rm, 12 files, one commit)

The six toolchain files plus the six test files that import them (keeping any test breaks
suite collection, against this todo's own "full unit suite green" gate; the test files are
a **[correction]**: the original text above lists only the scripts):

| Path | Size |
|---|---|
| `scripts/ops/bars/ops_tradier_delete.py` | 51.9 KB |
| `scripts/ops/bars/ops_tradier_residue.py` | 38.0 KB |
| `scripts/ops/bars/ops_tradier_residue_gate.sh` | 2.0 KB |
| `scripts/ops/bars/ops_tradier_restore.py` | 8.0 KB |
| `scripts/ops/bars/ops_old_store_backup.py` | 18.5 KB |
| `src/intelligence/bars/source_admission.py` | 3.5 KB |
| `tests/unit/scripts/test_ops_tradier_delete.py` | |
| `tests/unit/scripts/test_ops_tradier_residue.py` | |
| `tests/unit/scripts/test_ops_tradier_restore.py` | |
| `tests/integration/test_ops_tradier_delete_scratch.py` | |
| `tests/unit/bars/test_source_admission.py` | |
| `tests/unit/scripts/test_ops_old_store_backup.py` | |

Grep gate before the rm, per script basename, repo-wide: the only remaining hits must be
historical narrative (`.planning/`, dated `docs/plans/` and `docs/research/`,
`production/migrations/` comments, migration-contract tests). No import of any of these
modules exists outside its own test file (verified 2026-11-09; the successor
`scripts/ops/db/ops_table_backup.py` and `ops_source_policy.py`/`ops_d191q_arbitration.py`
do not import them).

### Step 2: allow-list rows (five boundary files, edit not delete)

Remove every row naming `ops_tradier_delete`, `ops_tradier_residue` or
`ops_tradier_restore` (grep `tradier` in each file to find them):

- `tests/unit/test_market_data_ohlcv_boundary.py` (2 rows: residue, delete)
- `tests/unit/test_market_data_ohlcv_writer_boundary.py` (2 rows)
- `tests/unit/test_ohlcv_raw_writer_boundary.py` (1 row)
- `tests/unit/test_ohlcv_coverage_writer_boundary.py` (1 row)
- `tests/unit/test_ohlcv_load_revision_writer_boundary.py` (the `_TRADIER_DELETE` /
  `_TRADIER_RESTORE` constants and their two rows)

### Step 3: APR retirement **[correction]**

The text above says "the two `infra.tradier_delete.*` rows in
`test_table_and_apr_key_readers.py`" and credits migration 548. Wrong on both counts:
migration **550** (not 548, which is the fetcher stall watchdog) retired the
`infra.tradier_delete.*` keys on 2026-10-31, and their pending-retirement rows are already
gone from the key-reader test. What actually remains:

- One `_PENDING_RETIREMENT` entry in `tests/unit/test_table_and_apr_key_readers.py`:
  `infra.old_store_backup.disk_margin` (seeded by migration 498; migration 553 left it for
  this date, and it is the only live `*tradier*`/`*old_store*` key in `config_state`,
  verified 2026-11-09). Retire the key with one new migration in the migration-550 pattern
  (config_history, then config_state, then config_schema, by literal key, idempotent) and
  remove the dict entry in the same commit.

### Step 4: data (no git action, gitignored)

- `rm -r data/backups/191/` (3.2 GB).
- Todo 510 the same session: `rm -r data/backups/185-38/` (142 MB) and
  `data/backups/185-43/` (832 KB). `185-45/` is already deleted (commit `4404303c8`);
  details in 510's prep note. Verify `df` shows about 3.4 GB freed.

### Step 5: doc repairs (live references that dangle once the files go)

- `docs/reference/gotchas.md`: the note naming `ops_old_store_backup.py` (about line 213).
- `docs/operations/operations-database.md`: the note about the backup and
  `ops_old_store_backup.py --verify-files` (about line 73).
- `.planning/STATE.md`: drop the `data/backups/191` row from the disk table.
- Dated narrative (the 2026-11-01 redundancy audit, `.planning/` phases, this todo) stays
  as history.

### Stays forever (never delete, whatever a grep shows)

- `ohlcv_raw` vendor='tradier' (7,140,397 rows), the `ohlcv_revision` lineage (155,350),
  every `ohlcv_load` row under Tradier loads including the IBKR revision rows, and the
  `ohlcv_coverage` provider=tradier ledger (1,529): the permanent record.
- The vendor value `tradier` in live code: `src/intelligence/bars/{vendor_kind,
  vendor_arbitration,daily_rule,vendor_basis,integrity_checks}.py` and their tests. The
  raw rows make the string data, not toolchain; do not sweep it.
- `production/migrations/*` (438, 440-457, 494-497, 518, 524, 537, 550 among them):
  immutable history. Their comments name deleted scripts as records, not dangling
  references; never edit a shipped migration to remove one.
- The migration-contract tests (`test_retire_tradier_apr_migration_contract.py`,
  `test_tradier_migration_contract.py`,
  `test_backfill_status_retirement_migration_contract.py`,
  `test_swap_1d_primary_migration_contract.py`,
  `test_cutover_admission_apr_migration_contract.py`,
  `test_bar_source_policy_migration_contract.py` and friends): they pin shipped SQL, not
  live scripts.
- The Grafana `tradier_refused` graveyard entry in
  `production/grafana/provisioning/alerting/alert-rules.yml` (plan 185-48's record).
- `191-TRADIER-RESIDUE.md` and every `.planning/` and dated-doc narrative of the era.
- `scripts/ops/db/ops_table_backup.py` with `infra.table_backup.disk_margin` (the
  successor, todo 578) and `ops_source_policy.py` / `ops_d191q_arbitration.py`.
- Every other backup directory: `handoff-2026-11-07/`, `185-48/`, `187-11/`, `191-11/`,
  `509-ml-chain/`, `509-signal-surface/`, `reset-2026-10-30/`, `worktree-salvage-*`.
- The local git tag `archive/v2x-ai-stack-2026-10`.

### Post-delete verification

1. `.venv/bin/pytest tests/unit/ -n auto` green.
2. `ruff check` and `black` on every touched file.
3. Repo grep `ops_tradier|ops_old_store_backup|source_admission`: remaining hits are
   historical only (the whitelist from step 1's gate).
4. The next nightly D7 is clean (split_continuity 1529/1529, digest_fresh 0; cf.
   `6d6c9e534`).
5. `data/backups/{191,185-38,185-43}` absent; the disk table in STATE.md updated.
6. Both todos (574, 510) closed and moved to `completed/` with closure notes.

## Closure 2026-11-12

Owner 2026-11-12: Tradier history is not needed (Massive covers 2003 onward, IBKR 1d reaches 1998); the 2026-11-01 KEEP ruling is superseded. Done: code tagged `archive/tradier-2026-11`, then `ops_tradier_delete/residue/residue_gate/restore`, `ops_old_store_backup`, `source_admission` and their tests deleted, with the allow-list and `_PENDING_RETIREMENT` rows; migration 589 deleted the vendor's `ohlcv_raw` (7,140,397), `ohlcv_revision` (155,350) and `ohlcv_coverage` (1,529) rows, left the tombstone in the CVR `bar_vendor` description, and retired `infra.old_store_backup.disk_margin`; `data/backups/191/` removed (it also held the dropped old stores' dumps; the 191-16 drop migration and summaries are their record). `ohlcv_load`/`ohlcv_request` lineage rows and three retired policy rows stay. Open follow-up: `daily_rule.py`, `vendor_arbitration.py` and `ops_d191q_arbitration.py` still carry D-191-Q Tradier logic; they are imported by live derivation code, so they retire with step 7's policy rework (todo 600).
