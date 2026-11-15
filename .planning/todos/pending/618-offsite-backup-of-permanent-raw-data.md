---
status: pending
priority: P1
filed: 2026-11-14
source: owner request 2026-11-14 ("write the off-site backup todo"), after the lead confirmed the copies that exist today
---

# Off-site, encrypted, restore-tested backup of the permanent raw data

## What

Raw market data is permanent (CLAUDE.md research invariants). Copies that exist today, all inside one site: the working copy on ubuntu1 (`data/massive/files`, 82 GB, 11,666 files), the nightly pull mirror on ubuntu2 (`indicagent-data-mirror.timer`, 04:30 UTC, `/home/bg/mirror`, 88 GB), the streaming standby, WAL archive and base backups on ubuntu2 (`indicagent-pg-base-backup.timer`). The vendor listing is a fourth source, but the vendor can change or revoke access, so it does not count. A fire, theft, a power event or a ransomware run hits ubuntu1 and ubuntu2 together. There is no off-site copy and no restore has been rehearsed from the mirror.

What is rebuildable and what is not decides the set:

- Rebuildable from the files: Massive rows in `ohlcv_raw`, canonical bars, features, regimes (derived data is cache).
- Not rebuildable: Alpaca raw rows (vendor re-asks are bounded by retention and rate), `reference_raw`, `economic_series_observation`, `dividend_events`, `ticker_event`, `security_identifier`, `instrument_tags`, the identity map versions in `data/ticker_entity_map`, `config_state` and `config_history`, the research record tables and `docs/`/repo history.
- IBKR raw rows are deleted at runbook Part F with no export (owner 2026-11-13); this todo does not change that.

## Scope

1. Decision to the owner, once, with this recommendation: a cold object store with client-side encryption (rclone `crypt` over an S3-compatible bucket; Backblaze B2 or AWS S3 Glacier Deep Archive class), keys held by the owner outside both servers. Order of magnitude at 82 GB plus a few GB of dumps is under a dollar or a few dollars a month; confirm the current price page before the decision. The owner chooses the provider and creates the account and credentials; the lead does not create accounts or put secrets in the repo.
2. Set to ship: `data/massive/files` plus manifests (`data/massive/manifest`, inventory, etag drift report), `data/massive/reference`, `data/ticker_entity_map`, `data/openfigi`, `data/backups`, the frozen-verdict inputs `logs/phase179/rerun_e14` and `logs/phase181` (todo 620), and a compressed logical dump (`pg_dump -Fc` per table, or a base backup plus WAL range) of the non-rebuildable tables above, plus a tag-pinned `git bundle` of the repo. Not shipped: `ohlcv_raw` Massive rows, canonical tables, feature and regime tables (rebuildable).
3. Mechanism: one oneshot leaf and a weekly timer, pull or push from ubuntu2 only (ubuntu2 reads from ubuntu1's mirror; ubuntu1 holds no cloud credentials, so a compromise of the primary cannot delete the off-site copy). Append-only bucket policy or object lock where the provider supports it. Incremental by manifest hash (the archive is immutable per file, so each night adds a day or two). Registered in `_DAG_ORDER` and `_ONESHOT_UNITS` like other oneshots, metric `job_completed_total{job, status}`, loud non-zero exit on a partial upload.
4. Integrity: after each upload, verify remote object size and checksum against the local manifest sha256; a monthly sampled restore (download 1 percent of files, compare sha256) recorded in the log.
5. Rehearsed restore, once before this closes: from the off-site copy alone, rebuild one month of Massive `ohlcv_raw` into a scratch database through `ops_massive_load` and match row counts and content digest against live; restore one non-rebuildable table from the dump and diff it.
6. Document in `docs/operations/` (runbook: install, key custody, restore) and name the single recovery order; update `docs/reference/server-migration-runbook.md` step 5 to point at it.

## Gates

- Owner has chosen the provider and holds the encryption key outside the servers (irreversible and outward-facing: decided once with the lead's recommendation above).
- Remote checksum equals local manifest sha256 for every shipped file; the leaf exits 1 on any mismatch.
- The restore rehearsal in item 5 passes and its output is committed under `logs/` with the date.
- Standard code gate (`/simplify`, `/review`, unit suite exit code) for the leaf; no edit to a module a live fingerprinted run imports.

## Boundaries

No secrets in the repo, in the environment of ubuntu1 or in logs. Nothing is deleted locally because an off-site copy exists. Waits for nothing in step 7 except that the Massive nightly (todo-less leaf `ops_massive_nightly`) and this job must not write the manifest at the same time; the backup reads the manifest, never rewrites it.
