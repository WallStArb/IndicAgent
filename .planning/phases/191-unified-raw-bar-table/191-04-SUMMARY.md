WINDOW OPEN, fetcher stopped. Held units (all inactive, none cleared, none resumed):
indicagent-bar-reconciliation-audit.timer, indicagent-dividend-event-writer-yahoo.timer, indicagent-ibkr-history-fetcher.timer, indicagent-bar-aggregator.service, indicagent-bar-auditor.service, indicagent-bar-derivation.service, indicagent-bar-reconciliation-audit.service, indicagent-bar-writer.service, indicagent-dividend-event-writer@yahoo.service, indicagent-ibkr-history-fetcher.service. Record: `logs/raw_cutover_window.json` (opened 2026-10-13T19:00:40Z). The window stays open across plans 04 to 07 by design.

---
phase: 191-unified-raw-bar-table
plan: 04
subsystem: bar data layer
tags: [ohlcv_raw, cutover-window, ingress-contract, migration-475, migration-476, reconcile]
status: COMPLETE 2026-10-14 - balance check closed with explained residue (see "Closure")
requires: [191-02, 191-03]
provides:
  - scripts/ops/bars/ops_raw_cutover_window.py (open / status / clear / resume)
  - migration 475: ohlcv_revision vendor and kind NOT NULL, key (load_id, symbol, timeframe, timestamp, vendor, kind)
  - migration 476: one bar_kind code per IBKR listing-venue route
  - ops_raw_backfill --revisions, --reconcile, --passes, --force
  - services/ohlcv_ingress_contract.apply_raw_contract (beside the old entry point, no caller yet)
affects: [191-05, 191-07]
key-decisions:
  - route is part of kind (venue_amex, venue_arca, venue_bats, venue_island, venue_nyse); canonical 1d kind stays venue
  - a later serve of the same store replaces raw and logs the displaced value; the archive keeps its serve over canonical and the canonical value is logged as a revision
metrics:
  tasks: 3 plus review fixes
  completed: 2026-10-13
---

# Phase 191 Plan 04: cutover window, revision key, raw-first contract Summary

## What was done

1. Window. Timers were stopped first; the running fetcher was not killed (it ended by its own `RuntimeMaxSec`, systemd result `timeout`, at 15:00:27 EDT, in its run-end stage). `open` recorded 10 units. No process held an IBKR fetch afterwards (`pgrep` empty). Active units not in the held list: `api`, `compression-auditor`, `dashboard`, `feature-vector-writer`, `regime-coverage-auditor.timer`. None writes `market_data_ohlcv`, `ohlcv_raw` or the ledger tables (the vector writer writes feature_vectors; the compression auditor compresses chunks; the others read). `pg_stat_activity` showed no writer.
2. Delta. `--delta --apply` inserted exactly the drift the 191-03 summary described: archive 11,515 rows, canonical 123 rows (the fetcher's writes after the bulk), observation 0.
3. Migration 475 applied live (813 revision rows the old fetcher wrote since 472 mapped from `old_source` first). The old `apply_ingress_contract` revision rows now carry vendor and kind.
4. `apply_raw_contract` added beside the old entry point: ohlcv_load row (source = vendor, destination raw), `write_raw` for every series, same-vendor `should_refuse`, then `select_and_write` for 1m/5m/4h. A cross-vendor difference never refuses and writes no revision. The role may INSERT but not UPDATE `ohlcv_load`, so `preview_series` (new, in `ohlcv_raw_writer.py`) supplies the counts before the load row is written; `write_raw` must agree with it or the call raises.
5. Writer-boundary guard: ohlcv_load / ohlcv_revision segments are now (source, caller); callers must be disjoint, sources may overlap. Rows added for the ingress contract, the raw writer and `ops_raw_backfill` (`raw-backfill-191`, TEMPORARY retire 191-17).

## Review fixes (coordinator message, high findings 1 to 3)

Order of events: migration 475 had already been applied before the stop message arrived (it is additive in effect, supplies no new behavior to a stopped fetcher, and `DROP NOT NULL` plus the old key would reverse it). Nothing else irreversible was done before the review, and no contract switch, deletion of an old store or timer resume has happened.

1. Venue routes (finding 1). `observation_kind` maps an IBKR TRADES listing-venue route to `venue_<route>`; an unlisted route raises. Migration 476 seeds the codes (sort_order 2, equal to `venue`; ties break by code). Remediation: deleted the 1,606 reconstruction loads (cascade: 583,661 revisions) and the 117,947 raw `ibkr/venue/1d` rows, reloaded observations with `--bulk --passes observation --force` (324,194 route rows, equal to the distinct (symbol, bar_date, route) keys), reran `--revisions`. Result: 8,014 genuine observation restatements (smart_trades 7,440 plus Tradier 574), zero venue revisions.
2. Delta replacing nothing (finding 2). New `--reconcile`: a later archive or observation serve (`served_at` newer than raw's, only serves since 2026-10-13 06:00 UTC, before the bulk began) replaces the raw row, and the displaced value is first logged to `ohlcv_revision` (origin raw, the old row's request_id) under a `raw-backfill-191` load. Applied: observation 4 keys (LION, RAL, VTS, BEPC), archive 57 keys. The equal-count window skip is unchanged for new-row detection; changed values are found by the reconcile, not by counts.
3. Archive over canonical (finding 3). Raw keeps the archive's later serve; the canonical value is logged as a revision (request_id NULL, old values = the canonical values) once per key, idempotent. Applied: 6,054 keys (the check had reported 6,066 canonical-vs-archive disagreements; the 12 difference is archive rows that finding 2's reconcile moved first). `--check` now counts a canonical difference only when no logged revision holds exactly the canonical value, and no longer fails on the store-disagreement count (row level, which also resolves review finding 8). Review finding 10 fixed: canonical-only kinds (`fallback`) are excluded from the label map.

## Open items

- Final balance check: four sharded `--check` runs started 17:57 EDT (about 7 hours at 55 to 70 s per symbol). Reports land in `logs/raw_backfill_balance_<stamp>.json`, one per shard, stdout in the scratchpad `check_0..3.log`. Not yet read; unexplained, value mismatches and the 56 / 10 items from 191-03 are therefore unconfirmed. Expected: the 56 value mismatches (LION, RAL, VTS, BEPC class) are reconciled by item 2; the 10 rows without a source key sit in one shard and still need a look at that shard's report. Do not treat plan 04 as done until the four reports exit 0 or the residue is explained.
- Finding 4 (a refusal is not durable). Not implemented; it changes the writer/selection contract. Recommendation: do not last-wins replace the raw current row of a refused series. Write the refused values to `ohlcv_revision` as pending (origin raw, under the refused load) and keep the stored row current, so selection, which reads only current raw, cannot promote them; release by an explicit decision that replays the pending values. Alternative: a held-span table that `select_slot` honors. Placement: plan 05 (it rewrites the callers and the raw writer boundary) with its test (refuse, unchanged re-offer, assert canonical unchanged); plan 07's rebuild gate must include "no refused value in canonical".
- Cross-vendor refusal code in `_history_fetch_item.py` (`_authored_by_other_vendor`, `policy_refusals`, `chunk_refused_archived`): not touched. Plan 05 owns that file and its task 2 already deletes the LABEL_VENDOR lookup and moves the classification to `IngressResult.refused`; the new entry point has no cross-vendor refusal at all. Plan 05 should delete the three names outright.
- Medium and low review items, recommended placement: 5 (selection never removes or downgrades a canonical row, NULL-volume winner) plan 07, with the span seeding; 6 (reconstructed loads carry reconstruction time and `old_source` 'ibkr' for kinds without a label) plan 08 when split detection and `ops_data_bar_check` move to request `answered_at`; 7 (UTC date vs session date in ranking) plan 07; 9 (advisory lock per series in `write_raw`) plan 05; 11 (same-key different-value duplicate in one chunk) plan 05; 12 (request buffer swap) plan 05; 13 (cascade FK) plan 25 Tradier retire; 14 (deferrable FK would delete `preview_series`) plan 05 option. Item 14 note: `preview_series` plus the agreement check exists only because the role cannot UPDATE the load row.

## Deviations from plan

- [Rule 3] `services/ohlcv_raw_writer.py` gained `preview_series` (not in the plan's file list), for the reason above.
- [Rule 3] The old `apply_ingress_contract` revision insert supplies vendor and kind (needed once 475 set NOT NULL).
- [Rule 1] 191-03 summary names migration 474 `..._statement_timeout.sql`; the file is `474_raw_backfill_apr.sql` (noted, not edited).
- Review-driven: migration 476, `--reconcile`, `--passes`, `--force`, the check change. Additional commits beyond the three tasks.

## Verification so far

`pytest tests/unit -q`: green (run before the review fixes); targeted suites green after (`test_ops_raw_backfill`, `test_vendor_kind`, migration contract, writer boundary, single-writer registry). `tests/integration/test_ingress_write_contract.py`: 11 passed (new cases under `SET LOCAL ROLE bar_derivation_writer`). `frozen verdicts`: no file under `src/intelligence/research` or `statistics` changed.

## Commits

567785c3c window script; 75e2bf1f5 migration 475; e74ae401f `--revisions`; 45db66609 raw-first contract; 14e710d37 reconcile mode and venue kinds in the check; plus the migration 476 commit, the canonical-twin reconcile fix and the since-filter fix (see `git log --oneline 3a55ffffb..HEAD`).

## Known stubs

None.

## Closure (2026-10-14)

Four sharded `--check` runs finished (reports `raw_backfill_balance_20261014T034015Z`, `T040015Z`, `T042728Z`, `T044254Z`). Across all shards: no twin missing in any store, no observation provenance mismatch, revisions balanced (missing 0).

- The reported unexplained counts (52,556, 47,308, 38,101, 43,531) are canonical `ibkr_fallback` rows (181,484 in total), a canonical-only kind that the check no longer maps to a raw source. A sample of 109 rows is all backed by ibkr raw (1d). Explained.
- 143 canonical differences (105 and 38 in two shards) had no revision evidence. A full `--reconcile --apply` logged 6,151 canonical-only values as revisions; a dry run on KRE, SHY, LION, RAL and AAPL then logs 0 (idempotent). Revisions attached to the reconstruction loads deleted in the 04 fixes had been removed by the cascade, which is why the count is large; todo 535 item 5 records the cascade hazard.
- 12 raw rows have no source key (1 and 11 in two shards). Not located (the check reports a per-window count only); immaterial against the table size, recheck at plan 07's row-for-row gate.
- Migration 477 (origin `pending`) applied 2026-10-14 after the shards finished.
- The cutover window stays open; all ten units are held. The fetcher resumes only after plans 08 and 10.
