WINDOW STILL OPEN, fetcher stopped. Held units (all inactive or failed, none cleared, none resumed): indicagent-bar-reconciliation-audit.timer, indicagent-dividend-event-writer-yahoo.timer, indicagent-ibkr-history-fetcher.timer, indicagent-bar-aggregator.service, indicagent-bar-auditor.service, indicagent-bar-derivation.service, indicagent-bar-reconciliation-audit.service, indicagent-bar-writer.service, indicagent-dividend-event-writer@yahoo.service, indicagent-ibkr-history-fetcher.service. Record: `logs/raw_cutover_window.json` (opened 2026-10-13T19:00:40Z). The four 191-04 balance checks were still running at the end of this plan (shards at 100, 100, 100 and 125 of about 390 symbols, no new report written).

---

---
phase: 191-unified-raw-bar-table
plan: 05
subsystem: bar data layer
tags: [ohlcv_raw, ingress-contract, durable-refusal, fetcher, alpaca-loader, migration-477]
requires: [191-04]
provides:
  - persist_chunk_atomically writing raw through apply_raw_contract (request rows, coverage, one transaction)
  - durable refusal: ohlcv_revision origin pending, ohlcv_raw untouched (migration 477)
  - services/bar_load.py load_frame, load_series, LoadResult, frame_to_raw_rows
  - store_bars through the raw-first contract
affects: [191-06, 191-07, 191-08, 191-10, 191-11, 191-16]
key-decisions:
  - a refused series writes no raw row; the offered values that differ from the stored rows are pending revisions (D-191-I)
  - preview_series stays; the deferrable ohlcv_revision FK is declined (item 14)
  - raw is per source: no fetch or write path asks what another vendor holds
requirements-completed: []
metrics:
  tasks: 2 plus review items
  completed: 2026-10-13
---

# Phase 191 Plan 05: fetch path and Alpaca loader onto the raw-first contract Summary

Every writer in the fetch path (IBKR chunks of 1m, 5m, 15m, 1h and the daily answers, the Alpaca loader, `store_bars`) now writes `ohlcv_raw` through `apply_raw_contract`, a vendor restating its own history beyond the threshold is held as pending revisions instead of replacing the stored rows, and the cross-vendor refusal path is deleted.

## What was done

Commits: `3a6af601d` (writer-level review items), `7b8e13808` (the switch). Documentation follows in the commit that carries this file.

1. Durable refusal (review finding 4). Plan 07's `refused_self_restatement` is only a compare class that excludes refused slots from the zero requirement; it does not stop a later selection from promoting the refused values, so it is not the mechanism and I built the hold here without a second one. `apply_raw_contract` now classifies each series with `preview_series`, and a series that `should_refuse` judges refused gets its `ohlcv_load` row (outcome refused) and `hold_pending`: the offered rows that differ from the stored rows (changed and new) become `ohlcv_revision` rows of origin `pending` (the old_* columns carry the offered value) and `write_raw` is not called. The stored raw rows stay current, so selection, which reads only current raw, cannot promote a refused value, now or on a later call. An unchanged re-offer is refused again (a new load row each time, raw never moves). Release is a waived write; no operator release command is built. Migration 477 admits `pending` in the origin check (a `pending` row is never a restatement: `ops_data_bar_check` now filters `origin <> 'pending'`, found by grep as the one reader that counted any revision). Tests: unit (refuse, unchanged re-offer, raw and selection untouched, other series still land) and integration under `SET LOCAL ROLE bar_derivation_writer` (raw and canonical `xmin` unchanged across two refused offers, 100 pending rows, zero non-pending revisions). Plan 07 got an amendment (the class should count zero; add a gate that no pending value is in canonical); design doc gained D-191-I.
2. Item 9: `pg_advisory_xact_lock(hashtextextended(symbol|timeframe|vendor|kind))` before the stored-row read in `write_raw` and `preview_series` (re-entrant in one session, sorted series order, so two writers of one series cannot both log the same old value and the preview/write agreement check now holds by construction).
3. Item 11: a chunk offering one key twice with different values raises `ValueError` before any SQL (identical repeats collapse); applies to `write_raw`, `preview_series` and `hold_pending`.
4. Item 12: `_Buffer.take_rows` swaps the list (`rows, self._requests = self._requests, []`) and a failed flush calls `restore`, so a request added while the async flush awaits its COPY is kept and a failed flush keeps order. Tests for the append-during-COPY race, failure restore, and the sync path.
5. Item 14 decision: no deferrable FK. The refusal decision needs the counts before any write (a refused series writes no raw row), so a pre-write classification is required whatever the FK does; `preview_series` is that classification, and the advisory lock removes the only reason for the agreement check to ever fire. Recorded in `preview_series`'s docstring and in todo 535.
6. Persist helper (`_intraday_persist.py`): contract settings are read as the connection's user, then `SET LOCAL ROLE bar_derivation_writer`, `apply_raw_contract`, then `SET LOCAL ROLE ohlcv_observation_writer` and the request rows, then (if asked) the coverage row, all in one transaction. A refusal is returned (`PersistResult.ingress.refused`), not raised; the request rows of a refused chunk still commit with a NULL digest. The answering request id is the last request that answered with bars. `chunk_digest` takes `RawRow`.
7. Fetch item: `_ChunkPersister` builds `RawRow` (intraday kind from the bar label via `label_to_vendor_kind`; a daily answer's kind from its request's route and what_to_show via `observation_kind`, arriving through `on_observation`, so smart_trades, smart_adjusted and `venue_<route>` land as ohlcv_raw kinds), judges the update lane's overlap against the same source's own raw rows (`read_stored_closes`), and fails the item only on `IngressResult.refused` (a vendor restating its own rows). The fetcher builds a `RequestSink`; the parity-eligibility SQL reads `ohlcv_raw`; `_ARCHIVE_TFS`, `_capture_kwargs`'s observation branch, `_load_ohlcv_insert_batch_size_config` and the `_STORE_*` machinery are gone.
8. Deleted outright, as directed: `_authored_by_other_vendor`, `policy_refusals`, the `chunk_refused_archived` path and the `LABEL_VENDOR` lookup in the item (tests assert their absence in source); `apply_ingress_contract`, `RevisionRefused`, `record_refused_load`, `read_stored`, `DESTINATION_GRID/ARCHIVE`, `MARKET_DATA_*` and `write_market_data_batches` in the contract; `insert_fetched_archive_rows` and `archive_refusal_rows` in `intraday_raw_archive.py` (now only `ARCHIVE_FROM_TABLE_SQL` for bar_derivation until plan 08); `_fx_derive`, `aggregate_bars_from_1m`, `fetch_bars`; bar_load's `split_series`, `archive_rows`, `archive_frame_to_tuples`, `drop_stored_rows`, `stored_range_stamps` and the three grid helpers; `scripts/ops/bars/ops_alpaca_raw_archive_backfill.py` (a one-shot whose result is in raw from the plan 03 backfill) and `tests/unit/test_alpaca_5m_load_slots.py`.
9. Alpaca loader: `load_frame` / `load_series` offer every served row (session and extended hours) to raw as (alpaca, sip_rth) with `LoadResult` counts (offered, new, changed, unchanged, held, refused); the LoadPolicy fence is unchanged. `ops_bar_load` and `ops_bar_nightly` were adapted to the new return type and `read_raw_params` (the nightly's 1d capture is `load_frame(coverage=False)`); their other conversions stay with plans 10 and 11.
10. `store_bars` keeps its dict interface: bars map to (vendor, kind) by label, one transaction, a refused series raises so no caller counts it stored. Callers: per-contract futures mode, backfill feature factory, venue recovery, chunk probe.

## Deviations from plan

1. [Rule 1 - Bug] Under the real role `bar_derivation_writer` has no SELECT on `controlled_vocabulary`, `config_state` or `bar_source_policy`, so `read_raw_params` after `SET LOCAL ROLE` fails (`permission denied for table controlled_vocabulary`). The 191-04 integration tests read the params before switching role and hid it. The persist helper now reads them before the switch (unit test pins the order); no grant added.
2. [Rule 3] The raw write runs before the request rows (the plan text lists requests first) because a refused chunk's request row must carry a NULL digest, which is known only after the contract ran.
3. [Rule 3] The FX/crypto 1m-derived fallback (`_fx_derive`) is deleted, not ported: its output is derived bars, which raw refuses by design, and no FX or crypto instrument is active (4 fx and 18 futures rows, all inactive).
4. [Rule 3] The waiver now also applies to 1d items (the old code ignored it because 1d stored nothing). Without it a full-depth 1d refetch after a recorded split would be refused and held forever.
5. [Rule 3] The plan's "nothing imports `ohlcv_observation_writer` after this plan" is false: `ops_bar_nightly`, `ops_venue_study` and `ops_d1_bootstrap` still do until plans 10 and 11. The fetcher, persist helper and loader no longer do. The `TEMPORARY retire: 191-16` registry reason says this.
6. [Rule 3] `infra.backfill.ohlcv_insert_batch_size` lost its only reader; it sits in `_PENDING_RETIREMENT` (`retire: 191-16`) and plan 16 got an amendment to delete the key.
7. [Rule 2] Coverage destinations stay 'archive' (15m, 1h) and 'grid' (the rest) through a local `_VENDOR_PARITY_TFS`, and the tradeable-only count for 'grid' is kept, because plan 06 owns the coverage rewrite; the new-row set now comes from the contract (rows raw found new), not from canonical.
8. Review-driven additions beyond the file list: migration 477, `hold_pending` and `read_stored_closes` in `ohlcv_raw_writer.py`, `IngressResult.n_held/new_timestamps`, `RefusedSeries.n_held`, the `ops_data_bar_check` filter, plan 07 and 16 amendments, design doc D-191-I, todo 535 status, glossary code surface line, `src/providers/alpaca.py` comment.

## Verification

- `pytest tests/unit -q`: full suite green (run after the last code change).
- `pytest tests/integration/test_ingress_write_contract.py test_ohlcv_coverage_atomic_write.py test_ohlcv_observation_store.py`: passed (one skip: no compressible `ohlcv_raw` chunk on the test database). The rewritten ingress file covers: same chunk twice then one changed bar (raw xmin), below-floor restatement logged, breaching chunk held with raw and canonical xmin unchanged, durable refusal after an unchanged re-offer, a 1d chunk of kinds smart_trades and venue_nyse side by side with no revision, request and raw rolling back together on a bad kind, coverage moving with new rows only, and the loader's no-drop identity (every offered row in raw or in the pending list).
- Greps from the plan: no `INSERT INTO ohlcv_intraday_raw_archive` outside `ARCHIVE_FROM_TABLE_SQL`; no `LABEL_VENDOR` under `scripts/infrastructure`, `bar_load.py`, the contract; `_intraday_persist.py` and the fetcher mention `ohlcv_observation_writer` only as the role name. Old-store reads that remain in the fetch path are plan 06's: `_d1_gaps.py` (archive and observation SQL) and `ohlcv_coverage_writer.py` (archive table in `DESTINATION_TABLES`, `rebuild_from_stored_state`).
- vulture: no new finding (removed the dead `fx_derived` field and the grid helpers). mypy on the touched modules: no new error (pandas stubs and the HistoryProvider protocol errors are pre-existing).
- No file under `src/intelligence/research` or `statistics` changed, so `repro_frozen` is not required.

## Unresolved and pending

1. Migration 477 is committed and tested on `indicagent_test` but NOT applied to the live database: its `ALTER TABLE ohlcv_revision` needs ACCESS EXCLUSIVE and the four balance checks hold long ACCESS SHARE locks (the apply timed out on `lock_timeout`). Apply it after the checks end and before any resume: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -v ON_ERROR_STOP=1 -f production/migrations/477_ohlcv_revision_origin_pending.sql`.
2. Held units, pending (do none until the four `logs/raw_backfill_balance_*.json` reports from the 17:57 EDT shards exist and exit 0 or their residue is explained, and 477 is applied). The fetcher timer must not resume after this plan alone: the gap planner and coverage still read the old stores (plan 06), and an IBKR 5m chunk over an Alpaca-canonical span would replace Alpaca canonical rows until plan 07 seeds the Alpaca policy spans (review finding 5, D-191-C). Per D-191-F the commands are `.venv/bin/python -m scripts.ops.bars.ops_raw_cutover_window status`, then per unit as its reader cuts over `... resume --unit <unit>` (all units at the window close in plan 11: `... resume --all`), with `clear` first where the unit needs evidence.
3. The Alpaca loader and `store_bars` write raw rows whose `request_id` has no `ohlcv_request` row (no FK, recorded in the `store_bars` docstring and the bar_load header); the nightly's ledger rows come from the old `ObservationSink` until plan 10.
4. No operator command releases a pending hold; a waived write is the only release. A full-depth 1d refetch after a split needs the waiver (item 4 above).
5. Review items 2, 3, 4 of todo 535 (selection removal and NULL-volume winner, reconstructed `loaded_at`, UTC date versus session date) and the `bar_derivation_writer` grant on `ohlcv_raw` are untouched, as scoped.
6. STATE.md, ROADMAP.md and REQUIREMENTS.md were not advanced: plan 04 is still INCOMPLETE and the coordinator owns that bookkeeping.

## Known stubs

None.

## Self-Check: PASSED

Files created or changed exist (`production/migrations/477_ohlcv_revision_origin_pending.sql`, `services/bar_load.py`, `tests/integration/test_ingress_write_contract.py`); commits `3a6af601d` and `7b8e13808` are in `git log`.
