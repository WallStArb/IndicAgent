# Unified raw bar table design

Author: Claude (Sonnet 5.5), 2026-10-12, at Brandon's direction (todo 533, P0: "one raw table for every vendor and timeframe", "ohlcv_observation is unnecessary", "reach the final state")
Status: reviewed (AGY, 2026-10-12; all ten findings verified against the code and database and folded in); ready to promote to a phase
Informed by: `.planning/todos/pending/533-bar-source-column-split-vendor-and-kind.md`, `docs/plans/2026-10-06-data-layer-integrity-design.md`, `docs/plans/2026-10-10-raw-capture-enforcement.md` (528), `docs/plans/2026-10-09-provider-history-plane-unification-design.md` (190), `docs/reference/databento-api.md`, live read-only queries on 2026-10-12.

## Problem

Raw vendor answers live in three places, none of them complete or uniform:

| Store | Holds | Rows (2026-10-12) | Shape |
|---|---|---|---|
| `market_data_ohlcv` | winners only, plus derived rows | 5m alpaca 220.1M, 5m ibkr 89.1M, 15m derived 106.0M, 1h derived 29.1M, 1m ibkr 9.8M, 1d tradier 6.7M, 1d ibkr 0.4M | key (timestamp, symbol, timeframe); `source` label |
| `ohlcv_intraday_raw_archive` | losers, refused chunks, 15m/1h parity | 201.8M (7.2 GB) | key adds `source`; last-wins |
| `ohlcv_observation` | 1d answers, one set per request | 15.8M (3.6 GB) | append per request; route and what_to_show |

Consequences observed this month: the bar `source` label mixes vendor (`alpaca`), vendor plus kind (`ibkr_named`) and a computation (`derived_5m`), while `ohlcv_load.source` holds vendors only, which broke every IBKR ingress write from 2026-10-10 15:03 UTC to 2026-10-12 (33a177772). Canonical holds the only copy of winning bars, so canonical is not rebuildable. Two vendors disagreeing on a slot is treated as a revision and refused (ratio 0.46 on IBKR 5m over Alpaca-canonical), which fails the fetch item for the source policy working as designed. A refusal on the archive timeframes upserts the refused rows over the archive rows they were meant to protect.

## Principles

1. Raw is one table: every vendor, every timeframe the vendor served, at the timeframe it served.
2. Raw is a current-state table, not an append log. A refetch replaces the earlier answer (last-wins). What a vendor said before is kept only when it changed (revision log).
3. A revision is one vendor changing its own answer. A disagreement is two vendors answering one slot differently. They are different facts with different records.
4. Canonical (`market_data_ohlcv`) is a selection from raw by policy, plus derived rows. It is rebuildable from raw at any time.
5. Vendors are data (controlled vocabulary), not schema. Onboarding a vendor is a CVR row, a `history_leaf`, a `VendorIngress` row and APR seeds, never a migration.
6. One writer per table, one direction: fetch -> ingress contract -> raw -> selection -> canonical -> derivation.

## Schema

### `ohlcv_raw` (new hypertable)

```
timestamp   timestamptz  not null   bar open time; 1d uses the canonical 1d convention (00:00 UTC of the session date)
symbol      text         not null   references instruments
timeframe   text         not null   what the vendor served (1m, 5m, 1d, ...); CHECK against CVR is not used (see below)
vendor      text         not null   CVR namespace bar_vendor: ibkr, alpaca, tradier (stored history only), databento (pending admission)
kind        text         not null   CVR namespace bar_kind: named, venue, fallback, continuous, official, generic, smart_trades, smart_adjusted, ...
open, high, low, close  double precision not null (finite CHECK as ohlcv_observation)
volume      bigint
served_at   timestamptz             when this value was first served (a changed value sets it again; an unchanged re-offer writes nothing); legacy rows: archived_at / fetched_at, else NULL
request_id  uuid                    the ohlcv_request that first served this value (fetch_run_id and the TRADES / ADJUSTED_LAST run alignment resolve through it); NULL for legacy rows and loader-written rows
load_id     uuid                    the ohlcv_load write that set the row; NULL for legacy rows
primary key (timestamp, symbol, timeframe, vendor, kind)
```

- `served_at`, `request_id` and `load_id` are nullable only for rows migrated from stores that never captured them (canonical vendor rows, archive rows without a load); the ingress contract refuses a new write without them. No dummy ids and no `now()` stamps: a migrated `served_at` is the true archive or fetch time or NULL, so a point-in-time query never treats an unknown arrival as late.
- `kind` carries what the label suffix and the observation `route` / `what_to_show` carry today. Two IBKR answers for one session (SMART TRADES and SMART ADJUSTED_LAST) coexist as two kinds.
- No CHECK constraint on `vendor` or `kind`: the writer validates against `VocabularyService` (cached at init). A new vendor then needs no migration. `ohlcv_load_source_check` (four hardcoded names) is dropped in the same migration.
- Hypertable on `timestamp`, 30-day chunks, compression segmented by (symbol, timeframe, vendor), the same policy as the archive it replaces. Migration checklist per `docs/foundation/timescaledb-compressed-column-migration.md`.
- Raw holds what the vendor served only. Databento has no 5m schema (1s/1m/1h/1d), so its raw rows are 1m, and a 5m from it is a derivation on the canonical side, labeled derived, never stored in raw as if served.
- Clear Street is an execution venue with no market data; its fills belong to the execution path, never to the bar tables.

### `ohlcv_revision` (existing, extended)

Existing columns (`load_id, symbol, timeframe, timestamp, old_*, old_source, origin`) hold the previous value of a row a vendor restated. Changes: add `vendor` and `kind`, populated from `old_source` through `sources.LABEL_VENDOR` for the 3.9M existing rows and then made NOT NULL; widen the primary key to `(load_id, symbol, timeframe, timestamp, vendor, kind)` (a single load can restate two coexisting kinds); add `request_id` (nullable) so corporate-action evidence (`evidence_request_ids`) and `daily_rule`'s current-scale test keep resolving by request; widen `origin` to admit `raw`. The raw writer classifies each incoming row against the same (vendor, kind) key:

- unchanged: no write, no log;
- new: insert;
- changed: old values to `ohlcv_revision`, row replaced.

`services/split_detection.py` reads vendor restatement history from here instead of from observation history.

### Canonical `market_data_ohlcv`

- Selection, not authoring: for each (symbol, timeframe, timestamp) the row comes from raw by `bar_source_policy` or, for derived timeframes and D2's 1d, from derivation. Selection resolves cross-vendor disagreement; the loser stays in raw and is never an error.
- Selection is a pure function of raw and policy, not of write order. "First-writer-stays" is path-dependent and is retired as a selection rule: the policy ranks vendors per span (`primary_source`, then `fallback_source`), and a slot takes the highest-ranked vendor holding a row there. `bar_source_policy` today admits only tradier, ibkr and derived (CHECKs on `primary_source` and `fallback_source`) and carries no alpaca row, although 220.1M canonical 5m rows are Alpaca; the migration widens both CHECKs to the CVR `bar_vendor` vocabulary (dropping them in favor of writer validation) and seeds the Alpaca spans explicitly. Step 5 is the gate: if selection from raw differs from today's canonical anywhere, the difference is resolved by seeding an explicit span row that reproduces canonical, never by letting the rebuild change canonical.
- `source` is split into `vendor` and `kind` (derived rows: vendor `derived`, kind the rule, e.g. `5m_grid`, `d2_v2`). `market_data_ohlcv_tradeable` nulls volume by kind (venue and fallback volume is not consolidated), not by label suffix. `sources.LABEL_VENDOR` retires.
- The split cannot be an in-place change: `UPDATE market_data_ohlcv` is banned (`test_compressed_hypertable_write_boundary.py`; a compressed chunk has no per-row index), and the dependent views (`market_data_ohlcv_tradeable`, `market_data_ohlcv_scrub_input`, `market_data_5m`, `canonical_bar_lineage`) block a column drop. Because canonical is rebuildable (principle 4), step 7 builds `market_data_ohlcv_v2` with `(vendor, kind)` by `INSERT ... SELECT` from `ohlcv_raw` plus derived rows, proves it equal to the live table, swaps the names in one transaction, and recreates the four views. `ohlcv_venue_head` is checked in the same pass. The old table is dropped after `VACUUM` and one nightly cycle; the template's bare `VACUUM` rule applies to the surviving table.

### Fetch ledger

`ohlcv_request` stays: answered and `no_data` windows cannot be read off bars. Its row-writing sink (`ObservationSink` in `services/ohlcv_observation_writer.py`, the `ohlcv_observation_writer` role, used by `_intraday_persist.py` and the fetcher) survives: step 6 moves it to `services/ohlcv_request_writer.py` and removes only the observation buffer and COPY branch, so the fetch ledger keeps one writer. `ohlcv_load` stays as the per-write record; its `source` check is dropped, `destination` gains `raw`, and `destination in (d1, archive)` retire with their tables.

### Compressed-chunk writes

Raw is a compressed hypertable, so a last-wins replacement of a row in a compressed chunk is a decompress-and-update. New rows into old chunks (the deep 5m tail) are inserts and stay cheap. Restatements are rare by construction (unchanged writes nothing); the raw writer wraps them in `compressed_hypertable_write_session` like the existing writers, and the compression policy leaves the newest 30 days of chunks uncompressed, where nightly refetches land.

### Deleted

`ohlcv_observation` (folds into raw) and `ohlcv_intraday_raw_archive` (folds into raw). The archive's no-delete trigger and the `bar_derivation_batch` FK are retired in the same step that drops the table.

## Ingress contract

One writer, `services/ohlcv_ingress_contract.py`, behind the existing `VendorIngress` rows:

1. Write raw first (classify, insert, log revisions), always, for every served bar including losers.
2. Run canonical selection for the touched (symbol, timeframe, span). A slot whose policy primary is another vendor changes nothing in canonical.
3. Refusal moves from "changed ratio against whatever is canonical" to "changed ratio against the same vendor's own stored raw rows". A vendor restating more than the allowed share of its own overlap (APR `max_revision_ratio`, today 0.02, at least `revision_ratio_min_stored` rows stored) is refused, and the refusal is durable (D-191-I): no raw row of the series is written or replaced, the offered values that differ from the stored rows are logged as `ohlcv_revision` rows of origin `pending` (the old_* columns hold the offered value) under a refused `ohlcv_load`, and the stored rows stay current, so selection, which reads only current raw, can never promote a refused value, however often the same values are offered again. Only an explicit decision (a waived write, for a recorded corporate action) replaces the stored row. A cross-vendor difference never refuses.
4. Fetch item status follows: a refusal is an error, and the only refusal left is a vendor restating its own stored raw rows. Raw is stored per source and agnostic to every other source: no fetch or write path asks what another vendor holds (the interim stored-label heuristic of 0f066c302 and its policy-refusal path are deleted).

This removes the archive-overwrite hazard: there is no archive timeframe path, and 15m/1h vendor parity rows are ordinary raw rows keyed by vendor.

## Owner exception: Tradier deletion (dated 2026-10-12)

CLAUDE.md says raw market data is permanent except for names excluded under a written data-quality rule. The owner ruled 2026-10-12 that Tradier is not used at all and its data is junk. This design records a second, source-scoped exception: Tradier-sourced rows (`market_data_ohlcv` source `tradier`, `ohlcv_observation` route `TRADIER`, their `ohlcv_load` rows) are deleted after IBKR has been asked for every span Tradier covers and the residue is measured (todo 533, Tradier retirement steps 1-4). Preconditions, in order:

1. IBKR 1d depth raised to 9800 days and the planner stops counting Tradier answers as coverage (done, 4fa3db578; the depth change runs).
2. One full gap-fill cycle completes; measure per name the sessions answered only by Tradier.
3. Canonical switches to IBKR for every pre-D span; D2 re-derives 1d; D7 judges it.
4. `pg_dump` of the Tradier rows kept until about 2026-11-12 (precedent: the 185-45 backup, todo 510). Names left with a shorter history get a recorded first-bar change, never a silent truncation.

CLAUDE.md gets the one-line exception when step 4 runs, not before. Until then Tradier rows migrate into raw like any other (vendor `tradier`), so the deletion is one predicate on one table.

## Migration plan

Steps 0 (pause the parity lane, fix run status; done 0f066c302) and 1 (this document) are complete when this document is reviewed. The rest becomes a phase:

3. Schema and writer. Create `ohlcv_raw`; seed CVR namespaces `bar_vendor` and `bar_kind`; extend `ohlcv_revision`; the raw writer behind the ingress contract; the fetcher and `services/bar_load.py` (Alpaca) switch to it. Dual-write is not used: the fetcher timer stops for the cutover window, and the Alpaca nightly (`ops_bar_nightly`, still unscheduled) is not yet running, so there is a single clean cutover per writer.
4. Backfill raw without refetching, from canonical vendor rows (`market_data_ohlcv` where source is a vendor label), `ohlcv_intraday_raw_archive` and `ohlcv_observation`. Balance check, R6 style: every source row has its raw twin or an explained exclusion; zero unexplained. Leave `infra.backfill.grid_parity_sample_names_per_week` at 0.
5. Selection rebuild check: canonical selected from raw equals today's canonical row for row (vendor rows), and `feature_vectors` inputs are unchanged. Nothing reads the new path before this passes.
6. Cut readers over from `ohlcv_observation` and `ohlcv_intraday_raw_archive` to raw. 1d readers: `bar_derivation` (daily rule), `bar_reconciliation_audit` (D7), `split_detection`, `listing_venue_writer`, `dividend_event_writer` (pairs TRADES and ADJUSTED_LAST only when their `request_id`s share a `fetch_run_id`), `bar_load`, `bar_hold`, `_d1_gaps`, `_history_fetch`, `ops_bar_nightly`, the ops scripts (`ops_head_rerun`, `ops_source_policy`, `ops_venue_study`, `ops_d1_bootstrap`, `ops_capture_completeness`) and the research scripts (`swap_1d_primary_measure`, `vendor_basis_study`). Archive readers: `bar_auditor`, `ohlcv_coverage_writer` (its `_REBUILD_SQL` and destination map), `intraday_raw_archive`, `bar_derivation`, `bar_reconciliation_audit`, `_d1_gaps`, `_intraday_persist`, `_history_fetch`. The `canonical_bar_lineage` view is redefined to join `ohlcv_raw` and `ohlcv_load` in this step, before any drop. `ObservationSink` moves as described under the fetch ledger. Order: writers, then the daily rule, then D7, then the rest, each with its own balance check. Re-run `grep -rn` over `src services scripts tests` for both table names before step 8; the list above is the 2026-10-12 inventory, not a contract.
7. Canonical `source` to `vendor` plus `kind`: the tradeable view by kind; D7, the 1d digest, `CANONICAL_1D_SOURCES`, the completeness report's `CASE` and `integrity_checks._PRIMARY_LABEL` read the new columns; `sources.LABEL_VENDOR` retires.
8. Drop `ohlcv_observation` and `ohlcv_intraday_raw_archive`; `VACUUM`; restore `infra.backfill.grid_parity_sample_names_per_week` to 10 only after the fetcher's parity path is verified writing to `ohlcv_raw` and nothing else.
9. Close: R6 and D7 green on the new tables; `repro_frozen` bit-identical if anything under `src/intelligence/research|statistics` moved; todo 530 closes with it.
10. Tradier retirement (steps 1-5 of the todo), gated as in the exception section.

Ordering against 186-26 (the `feature_vectors` rebuild): canonical values do not change (step 5 proves it), so the rebuild does not wait on this phase. It must not run during steps 4-7's table rewrites.

## Invariant mapping

- `single_writer`: the ingress contract writes raw; selection writes canonical; derivation writes derived rows. No reader writes.
- `lineage`: `ohlcv_raw.load_id` ties a row to its write; `ohlcv_revision` ties a restatement to its load.
- `no_fill` and `temporal_integrity`: raw rows carry `fetched_at`, so "what was knowable by t" is answerable for the current answer; earlier answers are in the revision log.
- `determinism`: canonical is a pure function of raw plus `bar_source_policy` plus derivation rules; step 5 is the proof.
- `asset_agnostic`: vendor and kind are data; no asset-class branch.

## Risks and answers

- Storage: raw adds about one copy of vendor canonical rows (~330M) beside the archive's 202M it replaces; net +130M rows against 654 GB free (26% used, 2026-10-12). Accepted; the observation and archive drops return about 11 GB plus compression gains.
- Hypertable rewrites contend with the live backfill: the fetcher timer is stopped for steps 3, 4 and 7 only; the backfill is lossless and resumes from the ledger.
- 450M-row column change in step 7: done per the compressed-column template (decompress per chunk window, alter, recompress, bare `VACUUM`), after step 5 has proven equality so a rollback is a column drop.
- A wrong cross-vendor classification would hide a real vendor restatement: step 3's classification is vendor-scoped by key, and the interim stored-label heuristic is replaced, not extended.

## Glossary entries to add (with the phase)

`ohlcv_raw` (the one table of vendor answers), `bar_vendor`, `bar_kind`, `revision` (a vendor changing its own answer) versus `disagreement` (two vendors differing on a slot). Retired on completion: `ohlcv_observation`, `intraday raw archive`, `parity lane` as a separate path.

## Resolved at planning (2026-10-12)

Decisions taken while planning phase 191 (`.planning/phases/191-unified-raw-bar-table/`). Plan numbers are those in ROADMAP.md phase 191. Each carries the line `Status: planner decision, owner acknowledgement pending`.

### D-191-A: kind rules

Status: planner decision, owner acknowledgement pending

Raw `kind` is what the vendor served, so `fallback` is a canonical-only kind: a selection outcome the daily rule assigns, never written to `ohlcv_raw`. Tradier's kind is `consolidated` and Alpaca's is `sip_rth` (the RTH-window SIP aggregates, `docs/plans/2026-10-09-alpaca-5m-admission-build.md`). The IBKR 1d observation routes map to `smart_trades` and `smart_adjusted` (a listing-venue route with TRADES maps to `venue`). `derived` is the vendor only of the 15m/1h grid (kind `5m_grid`); the rule version stays in `bar_derivation_batch`, not on the row. The single definition is `src/intelligence/bars/vendor_kind.py`.

### D-191-B: canonical 1d rows keep the winning raw (vendor, kind)

Status: planner decision, owner acknowledgement pending

This deviates from the Canonical section above, whose example gives derived rows the rule as kind (`d2_v2`) and does not say what a selected 1d row carries. A canonical 1d row keeps the winning raw row's (vendor, kind) (`canonical_kind_for_raw`: `smart_trades` becomes `named`, `venue` stays, `consolidated` stays; adjusted bars are never canonical), so the tradeable view can null volume by kind. The `d2_v2` kind example is superseded.

### D-191-C: Alpaca policy spans are data, seeded at the selection gate

Status: planner decision, owner acknowledgement pending

The schema migration drops the `bar_source_policy` CHECKs on `primary_source` and `fallback_source` but seeds no span. Alpaca spans are seeded data-driven through `scripts/ops/bars/ops_source_policy.py` in the selection gate plan (07), reproducing today's canonical wherever selection from raw differs.

### D-191-D: conservative fetch_run_id pairing

Status: planner decision, owner acknowledgement pending

This deviates from the Migration plan text in step 6, which has the dividend writer pair TRADES and ADJUSTED_LAST when their `request_id`s share a `fetch_run_id`. Last-wins raw keeps the `request_id` of the request that first served each value, so a later unchanged re-offer leaves the old request on the row. The dividend writer's, D7's and the daily rule's pairing becomes a conservative rule: `served_at` ordering is accepted only when neither row has `ohlcv_revision` history after the adjusted serve; otherwise the same `fetch_run_id` through `request_id` is required. Split detection orders restatement history by `ohlcv_request.answered_at` through the revision `request_id`, never by `ohlcv_load.loaded_at`.

### D-191-E: revision evidence is reconstructed in the backfill

Status: planner decision, owner acknowledgement pending

The backfill reconstructs `ohlcv_revision` rows from observation value history so split detection keeps its evidence: one real `ohlcv_load` row per (symbol, vendor, restatement ordinal), caller `raw-backfill-191`. It runs in plan 04, after the revision key is widened to include vendor and kind.

### D-191-F: one cutover window

Status: planner decision, owner acknowledgement pending

The bulk backfill (plan 03) only reads and runs with the fetcher live. The fetcher timer and every timer or service that writes or reads the old stores stop in plan 04 and resume per unit as each reader cuts over. The fetcher resumes only after the selection gate (plan 07) passes.

### D-191-G: the v2 canonical table is a copy-with-map

Status: planner decision, owner acknowledgement pending

This deviates from the Canonical section, which builds `market_data_ohlcv_v2` by `INSERT ... SELECT` from `ohlcv_raw` plus derived rows. Plan 12 builds v2 by copy-with-map from the live canonical table (label to (vendor, kind) through `vendor_kind`), and plan 14 swaps the names. The selection gate (plan 07) re-run on v2 is the proof that canonical is rebuildable from raw, so the build path does not need to be the selection path.

### D-191-I: a refusal holds, it does not record

Status: planner decision, owner acknowledgement pending

This deviates from Ingress contract item 3 as first written ("raw still records it, because a refused answer is evidence"). Replacing the raw current row with a refused value let the next selection that touched the slot promote it into canonical (review finding 4, plan 191-05). The evidence survives as `pending` revisions (migration 477) instead, and the stored row stays current. Readers of restatement history filter `origin <> 'pending'`. The release is a waived write; an operator release command is not built.

### D-191-J: a forming 1d bar is not a vendor answer

Status: planner decision, owner acknowledgement pending

A 1d bar served before its NYSE session closes (`session_complete_at(bar_date, answered_at)`, early closes included) is still forming. It is not a complete answer for the day and its later completion is not the vendor restating its own history. Raw is last-wins, so the rule has two halves. Live: `_ChunkPersister` does not offer such a bar to raw (the request row is kept; the planner leaves the session a gap until a run sees it whole). Reconstruction: a value run first served before the close is never superseded evidence, so `--revisions` skips it and keeps the other runs' ordinals; `--prune-forming-revisions` rebuilt the 929 smart_trades rows (929 symbols) the unfiltered reconstruction had logged. The boundary is the close instant, with no grace period: a bar answered at or after the close is complete. A date with no calendar session counts as complete once the date has passed. Origin: review finding 1 of plans 191-04 and 191-05.

### D-191-H: explicit deferrals

Status: planner decision, owner acknowledgement pending

Phase 191 does not deliver: the D7 condition for todo 520, todo 524's D7 tolerance rule and price/volume split, todo 531's `market_data_5m` naming pass, and todo 527's 5m shaper dedup. Plan 18 records each as a deferral in its todo.
