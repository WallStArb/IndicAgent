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
3. (Superseded 2026-10-14 by D-191-N: every vendor re-serve is written last-wins and reported by the restatement detector; nothing below about refusal or pending holds applies any more.) Refusal moves from "changed ratio against whatever is canonical" to "changed ratio against the same vendor's own stored raw rows". A vendor restating more than the allowed share of its own overlap (APR `max_revision_ratio`, today 0.02, at least `revision_ratio_min_stored` rows stored) is refused, and the refusal is durable (D-191-I): no raw row of the series is written or replaced, the offered values that differ from the stored rows are logged as `ohlcv_revision` rows of origin `pending` (the old_* columns hold the offered value) under a refused `ohlcv_load`, and the stored rows stay current, so selection, which reads only current raw, can never promote a refused value, however often the same values are offered again. Only an explicit decision (a waived write, for a recorded corporate action) replaces the stored row. A cross-vendor difference never refuses.
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

Status: superseded 2026-10-14 by D-191-N (owner decision: last-wins, nothing held, no refusal). Kept as the record of what ran until then.

This deviates from Ingress contract item 3 as first written ("raw still records it, because a refused answer is evidence"). Replacing the raw current row with a refused value let the next selection that touched the slot promote it into canonical (review finding 4, plan 191-05). The evidence survives as `pending` revisions (migration 477) instead, and the stored row stays current. Readers of restatement history filter `origin <> 'pending'`. The release is a waived write; an operator release command is not built.

### D-191-J: a forming 1d bar is not a vendor answer

Status: planner decision, owner acknowledgement pending

A 1d bar served before its NYSE session closes (`session_complete_at(bar_date, answered_at)`, early closes included) is still forming. It is not a complete answer for the day and its later completion is not the vendor restating its own history. Raw is last-wins, so the rule has two halves. Live: `_ChunkPersister` does not offer such a bar to raw (the request row is kept; the planner leaves the session a gap until a run sees it whole). Reconstruction: a value run first served before the close is never superseded evidence, so `--revisions` skips it and keeps the other runs' ordinals; `--prune-forming-revisions` rebuilt the 929 smart_trades rows (929 symbols) the unfiltered reconstruction had logged. The boundary is the close instant, with no grace period: a bar answered at or after the close is complete. A date with no calendar session counts as complete once the date has passed. Origin: review finding 1 of plans 191-04 and 191-05.

### D-191-K: the fetch question is per source

Status: planner decision (owner principle, 2026-10-13), owner acknowledgement pending

Raw is stored per source and agnostic to every other source, so the gap planner asks one question: for this vendor, which slots of [A, B] are missing from its own `ohlcv_raw` rows, minus its own answered request windows (a definitive `no_data` included)? Every planner read carries the vendor (`ohlcv_raw.vendor`, `ohlcv_request.source`); the empty-history probes (`has_bar_before`, `has_bar_between`, `load_first_bars`), the queue's 1d currency read and the coverage ledger follow. No date cutoff restricts the question, and another vendor's rows, answers or the canonical selection never cover a slot. A stored 1d bar counts only when its session was complete when it was served (D-191-J). Two kinds of ask are not gaps and stay outside the planner (`_with_verification_asks`): the update lane's 5m overlap, the 1d session overlap, and the escalation refetch. They re-ask slots the vendor already holds, because a restated history (a split, a rescaled level) is visible only by comparing a fresh serve with the same source's stored values, which is what split detection and the 5m waiver read (plans 191-08 and 191-10). Deleting them would leave no restatement ever observed.

### D-191-L: the selection session rule, session-date spans, and what a loader reports

Status: planner decision (plan 191-07, review of plans 191-04 and 191-05), owner acknowledgement pending

Four rules in selection and the loaders, each from the review of the raw-first writers.

1. Session rule by kind. A raw kind defined as regular-hours (`sip_rth`, D-191-A) is a selection candidate only on the regular trading hours grid (open inclusive, close exclusive, 5 minute step, early closes from the NYSE calendar). Raw keeps every bar Alpaca served, pre- and post-market stamps included, and they never reach canonical 5m or the 15m/1h derivation. The rule is by kind, not a calendar filter on every vendor: IBKR answers an RTH request with its own session (bars to 16:00 ET on early-close days, a 14:30 UTC open on 2006-12-27 where the calendar says 14:32), canonical holds exactly those, and a vendor-blind filter would drop real rows.
2. Spans match the NYSE session date (the `America/New_York` calendar date of the stamp), not the UTC date.
3. One writer per series at a time: `select_and_write` takes `pg_advisory_xact_lock` on `bar_selection|symbol|timeframe` in sorted symbol order before reading, and every insert carries the upsert tail, so two writers of different vendors on one series neither collide on the canonical unique key nor overwrite each other's choice.
4. A loader reports what it did not select. A slot that reached raw but that no ranked vendor holds is counted (`unselected`) and the loader and nightly status are not APPLIED and exit non-zero, the same way held rows are. Coverage is credited only for rows that landed in raw (a refused chunk credits nothing).

The gate for plan 191-07 (`scripts/ops/bars/ops_selection_gate.py`) counts, beside its zero, the slots a recorded refusal explains (refused self restatement, refused cross-vendor, restated after the raw copy); each class needs ledger evidence for the exact key, and an unexplained difference is never folded into one.

### D-191-M: explained is not clean; legacy refusals and chunk edges

Status: planner decision (review of plan 191-07), owner acknowledged 2026-10-14 ("we need complete bars from each source if they are available")

1. The gate exits 0 only when canonical equals the selection exactly. Explained differences, or a held refused value the selection would take, exit 3 (explained residue); nothing resumes on 3.
2. A refused serve is tied to the exact key: a raw row whose `load_id`, or (backfill copies) whose `served_at`, names a refused `ohlcv_load` of the same vendor, unless an applied vendor serve with destination raw covered the slot after the refusal. It is held (D-191-I) when it displaced the vendor's own value at that key. A retired-path refusal that judged the vendor against another vendor's canonical row is not a refusal under the per-source contract (D-191-K): where the vendor has no other value of its own at the key, its row is its own answer and selection takes it, once, as a catch-up.
3. An intraday request that ends inside a bar truncates it. The IBKR leaf asks on the bar grid and drops any bar that straddles the request end or is still forming (the intraday analogue of D-191-J). Stored truncated bars are repaired from the vendor (the fetcher's `--reserve-keys` lane), never from canonical; where raw already holds the whole bar, selection takes it.
4. `scripts/ops/bars/ops_raw_repair.py` makes raw the vendor's accepted answer on the explained slots: the accepted value goes back through the raw writer under a `raw-repair-191` load, the refused value becomes a `pending` revision under its original refused load where no later serve answered the slot, and no raw or revision row is deleted.
5. A direct-timeframe policy span effective before today is written only with `--reselect`, which re-selects the window it changes in the same transaction.

#### D-191-M amendment (second review of plan 191-07, 2026-10-14)

Status: superseded 2026-10-14 by D-191-N. Applied once on 2026-10-14; its holds were released by D-191-N and its tool deleted. No owner acknowledgement is owed. Items 7 and 8 (served-range evidence and the complete-bar rule) and item 9 (whole-session selection) survive in D-191-N; items 2, 4 and 6 (refused serves, the raw repair's holds, the per-load re-judgment) do not.

The amendment replaces items 2 to 4 where they differ.

6. A legacy refused load is judged once, as a whole, under the per-source contract (D-191-K). The first repair split each such load key by key: new keys went to raw as a catch-up, changed keys were held. That matches neither outcome of the contract. `scripts/ops/bars/ops_refusal_rejudge.py` judged each of the 75 legacy refused 5m loads with `should_refuse` (`threshold.bar_integrity.max_revision_ratio` 0.02, `revision_ratio_min_stored` 500).
   - The offer is the rows the load archived; complete bars only (item 8).
   - The judgment is against the vendor's own values at the refusal, never another vendor's canonical row.
   - Accepted: the offered values land last-wins; raw holds the vendor's latest complete answer at each key, and pending rows the first repair made for that load are released.
   - Refused: every complete offered value that differs from the vendor's stored value is held pending under the original refused load, new keys included. Raw keeps the stored value. A key only that load supplied is withdrawn from raw, its value logged, and canonical is retracted there unless another vendor holds the session (missing is NaN).
   - A load whose offer was never archived cannot be judged and is left as it is.
7. A later serve excuses a refused value only on exact-key evidence: a raw or revision row of that load at the key, or the request window it persisted holding the whole bar (`infra.selection_gate.request_load_match_s` ties a legacy load to its request). A load whose dates include the slot is no evidence. A held value that the vendor serves again and the contract accepts is answered again and no longer held.
8. A bar is a complete vendor answer only when its block ended at or before the request end and before the answer, and, for a bar ending at the session close, the answer came at least `threshold.bar_integrity.session_close_settle_s` (1,800 s) after the close.
   - This is `src/intelligence/bars/complete_bars.py`, applied in the shared fetch layer to every vendor. It replaces item 3's leaf rule: policy never enters a leaf.
   - A held-back bar is written on its request row (`ohlcv_request.partial_bars`), and the gap planner does not count its slot as answered.
9. Selection takes each session whole from one vendor: the first ranked vendor holding every slot any ranked vendor holds. With none complete, it takes the vendor holding most, and the other vendor's slots are left empty. A session spliced from two vendors is never written, and the gate counts one as residue.

Applied (`logs/refusal_rejudge_191_apply.json`): 53 accepted, 7 held, 15 unjudgeable.
- Raw writes: 1,299 changed values, 438,346 rows restamped (served_at and lineage only), 3,469 withdrawn.
- Pending rows: 3,542 added and 1,290 released, from 2,400 to 4,652.
- Canonical: 1,331 rows replaced and 446 retracted.
- Afterwards the selection gate over the 57 series exits 0.
- 3,525 keys wait for an IBKR re-serve (`logs/reserve_keys_191_07.json`).

The review expected ADM, AEP, AMT, ASML and BA to refuse above 2%. Judged against the vendor's own values (its denominator excludes Alpaca rows), they refuse at 3.9 to 5.8%, and AMZN refuses at 3.1% as well. The loads at about 0.3 to 0.7% apply. ECL, ELV and EMR apply at 1.3 to 1.4% of 3,393 own values, and TLT at 1.3%. GE d2adcf51 (the 2021-11 two-decimal serve) refuses at 40%.

Per-load decisions ("Share" is changed over own stored; "Partial" is offered bars that were not complete answers). **Superseded by D-191-N.** The third review found the six 2026-10-12 23:23 loads (ADM, AEP, AMT, AMZN, ASML, BA) judged against 48 values a later load first wrote at 04:27; corrected they stand at 623 stored and 14, 19, 18, 15, 14 and 16 changed (2.25%, 3.05%, 2.89%, 2.41%, 2.25%, 2.57%). Every hold in this table was released last-wins under D-191-N, so the table is history only:

| Series | Refused load | Loaded (UTC) | Offered | Partial | Own stored | Changed | New | Share | Outcome |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| ADM | b0a0f500 | 2026-10-10 06:38 | 0 | 0 | 0 | 0 | 0 | 0.00% | unjudgeable |
| ADM | 898c4a50 | 2026-10-12 23:23 | 1,248 | 0 | 671 | 27 | 577 | 4.02% | held |
| AEP | c69d6aef | 2026-10-10 06:38 | 0 | 0 | 0 | 0 | 0 | 0.00% | unjudgeable |
| AEP | 04f17062 | 2026-10-12 23:23 | 1,248 | 0 | 671 | 39 | 577 | 5.81% | held |
| AGG | 6fa42c0e | 2026-10-10 06:38 | 0 | 0 | 0 | 0 | 0 | 0.00% | unjudgeable |
| AMT | 02320e48 | 2026-10-10 06:38 | 0 | 0 | 0 | 0 | 0 | 0.00% | unjudgeable |
| AMT | 59097ead | 2026-10-12 23:24 | 1,248 | 0 | 671 | 32 | 577 | 4.77% | held |
| AMZN | fd861b88 | 2026-10-10 06:38 | 0 | 0 | 0 | 0 | 0 | 0.00% | unjudgeable |
| AMZN | 86c21967 | 2026-10-12 23:24 | 1,248 | 0 | 671 | 21 | 577 | 3.13% | held |
| ASML | 04f5be01 | 2026-10-10 06:38 | 0 | 0 | 0 | 0 | 0 | 0.00% | unjudgeable |
| ASML | 49aa4190 | 2026-10-12 23:24 | 1,248 | 0 | 671 | 26 | 577 | 3.87% | held |
| AVGO | a5fff3ac | 2026-10-10 13:04 | 0 | 0 | 0 | 0 | 0 | 0.00% | unjudgeable |
| BA | dd4c7a43 | 2026-10-10 07:11 | 0 | 0 | 0 | 0 | 0 | 0.00% | unjudgeable |
| BA | 4e945cfd | 2026-10-12 23:24 | 1,248 | 0 | 671 | 31 | 577 | 4.62% | held |
| BAC | c2b4b7f7 | 2026-10-10 07:11 | 0 | 0 | 0 | 0 | 0 | 0.00% | unjudgeable |
| BKNG | 88664ca1 | 2026-10-10 07:12 | 0 | 0 | 0 | 0 | 0 | 0.00% | unjudgeable |
| CAT | ac03aadb | 2026-10-10 07:45 | 0 | 0 | 0 | 0 | 0 | 0.00% | unjudgeable |
| CCJ | 4b85467d | 2026-10-10 07:45 | 0 | 0 | 0 | 0 | 0 | 0.00% | unjudgeable |
| CRWD | 9c5587e4 | 2026-10-10 13:04 | 0 | 0 | 0 | 0 | 0 | 0.00% | unjudgeable |
| ECL | 5b018953 | 2026-10-12 08:55 | 11,700 | 0 | 3,393 | 47 | 8,307 | 1.39% | accepted |
| EDV | 3e454cb8 | 2026-10-10 13:04 | 0 | 0 | 0 | 0 | 0 | 0.00% | unjudgeable |
| EEM | 08b0749b | 2026-10-12 08:56 | 11,700 | 0 | 11,152 | 57 | 548 | 0.51% | accepted |
| EFA | da4f32a1 | 2026-10-12 08:57 | 11,700 | 0 | 11,152 | 59 | 548 | 0.53% | accepted |
| ELV | 55da0971 | 2026-10-12 08:57 | 11,700 | 0 | 3,393 | 49 | 8,307 | 1.44% | accepted |
| EMLC | 83e58b42 | 2026-10-10 13:05 | 0 | 0 | 0 | 0 | 0 | 0.00% | unjudgeable |
| EMR | 274b2833 | 2026-10-12 08:58 | 11,700 | 0 | 3,393 | 43 | 8,307 | 1.27% | accepted |
| EPD | 925de110 | 2026-10-12 08:59 | 11,700 | 0 | 11,152 | 52 | 548 | 0.47% | accepted |
| EQIX | 219ce71b | 2026-10-12 08:59 | 11,700 | 0 | 11,152 | 48 | 548 | 0.43% | accepted |
| ETR | 3c3027fd | 2026-10-12 09:00 | 11,700 | 0 | 11,152 | 46 | 548 | 0.41% | accepted |
| EWG | 28d5b981 | 2026-10-12 09:01 | 11,700 | 0 | 11,152 | 73 | 548 | 0.65% | accepted |
| EWJ | 952fc697 | 2026-10-12 09:01 | 11,700 | 0 | 11,152 | 53 | 548 | 0.48% | accepted |
| EWT | 3398a7b5 | 2026-10-12 09:02 | 11,700 | 0 | 11,152 | 50 | 548 | 0.45% | accepted |
| EWY | c7449de7 | 2026-10-12 09:03 | 11,700 | 0 | 11,152 | 19 | 548 | 0.17% | accepted |
| EWZ | 60348c89 | 2026-10-12 09:03 | 11,700 | 0 | 11,152 | 80 | 548 | 0.72% | accepted |
| EXEL | 272ac2d9 | 2026-10-12 09:04 | 11,700 | 0 | 11,152 | 2 | 548 | 0.02% | accepted |
| EZU | a9442add | 2026-10-12 09:05 | 11,700 | 0 | 11,152 | 52 | 548 | 0.47% | accepted |
| F | a05bd2c0 | 2026-10-12 09:05 | 11,700 | 0 | 11,152 | 72 | 548 | 0.65% | accepted |
| FCX | e49b26a6 | 2026-10-12 09:06 | 11,700 | 0 | 11,153 | 32 | 547 | 0.29% | accepted |
| FDX | e397e14a | 2026-10-12 09:07 | 11,700 | 0 | 11,152 | 53 | 548 | 0.48% | accepted |
| FXE | 6743298b | 2026-10-12 10:27 | 11,699 | 0 | 11,183 | 31 | 516 | 0.28% | accepted |
| FXI | 7319d39a | 2026-10-12 11:00 | 11,700 | 0 | 11,175 | 82 | 525 | 0.73% | accepted |
| GDX | 05661ed6 | 2026-10-12 11:34 | 11,700 | 0 | 11,174 | 22 | 526 | 0.20% | accepted |
| GE | 2b653430 | 2026-10-12 12:07 | 11,700 | 0 | 11,174 | 31 | 526 | 0.28% | accepted |
| GE | d2adcf51 | 2026-10-12 12:14 | 11,664 | 0 | 11,664 | 4,680 | 0 | 40.12% | held |
| GILD | 925bad59 | 2026-10-12 12:40 | 11,700 | 0 | 11,174 | 0 | 526 | 0.00% | accepted |
| GLD | 6a570f7c | 2026-10-12 13:13 | 11,700 | 0 | 11,174 | 12 | 526 | 0.11% | accepted |
| GOOGL | a0fdcec7 | 2026-10-12 13:46 | 11,700 | 0 | 11,173 | 11 | 527 | 0.10% | accepted |
| GS | 2944e456 | 2026-10-12 14:19 | 11,700 | 0 | 11,173 | 0 | 527 | 0.00% | accepted |
| HD | 0e9536f4 | 2026-10-12 16:18 | 11,646 | 1 | 11,079 | 1 | 566 | 0.01% | accepted |
| HON | 54e14410 | 2026-10-12 16:51 | 11,701 | 2 | 11,133 | 1 | 566 | 0.01% | accepted |
| IGV | 66b17962 | 2026-10-12 17:25 | 11,646 | 1 | 11,078 | 33 | 567 | 0.30% | accepted |
| IHF | 4d65df86 | 2026-10-12 17:58 | 11,646 | 1 | 11,078 | 0 | 567 | 0.00% | accepted |
| ISRG | 8c8f9cb4 | 2026-10-12 18:31 | 11,646 | 1 | 11,114 | 0 | 531 | 0.00% | accepted |
| ITA | 82b09c9d | 2026-10-12 19:04 | 11,646 | 1 | 11,113 | 46 | 532 | 0.41% | accepted |
| ITB | 55044fd9 | 2026-10-13 05:31 | 11,700 | 0 | 11,085 | 0 | 615 | 0.00% | accepted |
| IWM | 30482284 | 2026-10-13 11:15 | 11,622 | 0 | 11,055 | 12 | 567 | 0.11% | accepted |
| IYT | 6c575da6 | 2026-10-13 07:05 | 11,700 | 0 | 11,075 | 32 | 625 | 0.29% | accepted |
| IYZ | 541f33b1 | 2026-10-13 07:21 | 11,700 | 0 | 11,075 | 0 | 625 | 0.00% | accepted |
| JBHT | 01b9182e | 2026-10-13 11:17 | 11,700 | 0 | 11,133 | 0 | 567 | 0.00% | accepted |
| JNJ | b80dd12f | 2026-10-13 11:21 | 11,700 | 0 | 11,134 | 0 | 566 | 0.00% | accepted |
| JPM | 8c44bee8 | 2026-10-13 12:22 | 11,700 | 0 | 11,134 | 0 | 566 | 0.00% | accepted |
| KO | 0d96feff | 2026-10-13 12:27 | 11,700 | 0 | 11,134 | 0 | 566 | 0.00% | accepted |
| KRE | 6e29d04e | 2026-10-13 15:31 | 11,629 | 1 | 10,997 | 40 | 631 | 0.36% | accepted |
| LEN | 736509eb | 2026-10-13 15:33 | 11,629 | 1 | 10,997 | 9 | 631 | 0.08% | accepted |
| LLY | a2f00e53 | 2026-10-13 16:36 | 11,629 | 1 | 10,997 | 0 | 631 | 0.00% | accepted |
| LMT | fde6219c | 2026-10-13 16:41 | 11,629 | 1 | 10,997 | 0 | 631 | 0.00% | accepted |
| LQD | 488a21b2 | 2026-10-13 17:41 | 11,629 | 1 | 10,997 | 36 | 631 | 0.33% | accepted |
| MCD | da38f5a9 | 2026-10-13 17:47 | 11,629 | 1 | 10,998 | 0 | 630 | 0.00% | accepted |
| RLAY | bb2badd4 | 2026-10-13 04:25 | 624 | 0 | 486 | 0 | 138 | 0.00% | accepted |
| SHY | d40e3f28 | 2026-10-13 03:51 | 624 | 0 | 545 | 3 | 79 | 0.55% | accepted |
| TLT | 7f973c29 | 2026-10-13 03:51 | 624 | 0 | 545 | 7 | 79 | 1.28% | accepted |
| TMUS | 9b5d5a86 | 2026-10-13 03:52 | 624 | 0 | 546 | 3 | 78 | 0.55% | accepted |
| VIXY | ccad251e | 2026-10-13 04:25 | 624 | 0 | 613 | 0 | 11 | 0.00% | accepted |
| VIXY | a48de0d4 | 2026-10-13 10:47 | 7,884 | 0 | 4,842 | 0 | 3,042 | 0.00% | accepted |
| VIXY | 1c4d9f60 | 2026-10-13 10:49 | 11,700 | 0 | 10,140 | 0 | 1,560 | 0.00% | accepted |


### D-191-N: last-wins; a restatement is detected and reported, never refused or held

Status: owner decision, 2026-10-14 (supersedes D-191-I, the refusal parts of Ingress contract item 3, and D-191-M items 2, 4 and 6 with its amendment)

A vendor's own re-serve always overwrites its raw value last-wins, and the old value is logged as an `ohlcv_revision` row (origin raw) under the load that replaced it. Nothing is held pending and no load is refused. The revision log already makes every overwrite recoverable; routine restatements (the closing auction's volume on the 15:55 ET bar, late prints) are the vendor correcting itself; the refusal machinery cost far more than the risk it guarded.

1. Ingress (`services/ohlcv_ingress_contract.py`) writes every series of a chunk last-wins and selects the touched sessions. `should_refuse` stayed only in the derivation stage (`services/bar_derivation.py`) until D-191-O replaced it with a flag there too.
2. A restatement detector (`src/intelligence/bars/restatement.py`, migration 481) reports each load's changed share of the vendor's stored rows and two basis-change signatures: a near-constant price ratio over many changed bars, and a one-bar time shift. A flagged load is logged as a warning, counted on `ohlcv_restatement_flags_total` and recorded in `ohlcv_restatement_flag` for review. It never blocks a write. Thresholds are APR (`threshold.bar_integrity.restatement_*`).
3. The holds that existed were released once (`scripts/ops/bars/ops_pending_release.py`, 2026-10-14) by latest answer per key: the offer was timed at the answer of the request its refused load persisted, the raw value at its writing serve or the served range of a later serve (exact-key evidence, `scripts/ops/bars/_ledger_evidence.py`). 4,572 offers were written to raw with the displaced values logged; 80 offers (the six 2026-10-12 loads' keys the vendor answered again at 04:27 to 05:31) were older than raw and kept as ordinary revisions. Migration 482 removed the `pending` origin.
4. Removed with the decision: the pending hold writers, the held-key skip in selection, the re-serve excuse logic, the refused and explained classes of the selection gate, `ops_refusal_rejudge.py` and `ops_raw_repair.py`. Kept: the revision log, the archive, the complete-bar rule (D-191-M item 8) and whole-session selection (item 9).
5. The selection gate proves canonical equals the selection of raw exactly; any difference is real. Residue (exit 3) is a canonical session mixing vendors or a session choice the durable record (`bar_session_choice`, migration 480) does not hold.
6. Session choices are data. `bar_session_choice` keeps every session not taken plainly (the fallback vendor, no complete vendor, or fewer slots than the calendar grid), so features can condition on the vendor of a session. The vendors' volume levels differ (IBKR to Alpaca 5m volume about 0.38 on BKNG and 0.62 to 0.95 on MSFT, 2023 to 2025), so a fallback session is a day-level volume step. That is a recorded property of the data; no volume rescaling is applied. The record tells a fallback by absence (the primary held nothing that session: 3,060,986 of 3,081,879 choices on 2026-10-15, IBKR-first names whose 5m backfill has not reached the date) from a fallback by shortfall (354) through `n_primary_grid_slots` (migration 484); a session short of the calendar grid is mostly an Alpaca session of a thin name with no-trade slots.
7. The gap planner never counts the window of a request whose own load was refused as answered (third review of 191-07, finding 3). Historical refused loads remain in `ohlcv_load`; their windows stay gaps until the vendor answers them.

Measured before the release (owner request, 2026-10-14): every changed bar the six 2026-10-12 loads were judged on lies in one session, 2026-09-23, 19 days before the serve and mid-session, not at the close. ADM 14 and AMT 18 changed bars are price-only; AEP 16 price, 2 volume, 1 both; AMZN 2 price, 11 volume, 2 both; ASML 9 price, 5 volume; BA 14 price, 1 volume, 1 both. Price changes are at most one cent (at most 1.2 bp); volume changes at most 8.3%. Every one of the six held 77 of 78 IBKR bars that day. Alpaca's bars match neither value. A volume-only settle-window rule would therefore not have changed these refusals (none of the bars was within a settle window of its close or serve); under it the shares would have been unchanged. Under D-191-N the question is moot.

### D-191-O: the derivation stage applies restatements last-wins; a failed name never fails the run

Status: decided 2026-10-15 by the orchestrator under the owner's standing direction ("why not just overwrite it, we are being pedantic"); extends D-191-N to the derivation stage (todo 535 item 40)

On 2026-10-15 the daily stage refused GYRE (132 changed of 4,665 stored rows, ratio 0.0283; IBKR re-served its 2015 values and canonical equals IBKR raw on every key), and the stage's non-zero exit withheld the fetcher's 1d ledger refresh for all 1,502 names of the run.

1. The derivation stages (`services/bar_derivation.py`, daily and grid) apply a vendor restatement last-wins like raw does. The revision ratio (changed plus removed over stored, APR `threshold.bar_integrity.max_revision_ratio` over at least `revision_ratio_min_stored` rows) is a non-blocking flag: `revision_flag` in the daily load's detail, `revision_flags` in the grid loads' detail, a `bar_derivation.revision_flag` warning, and a run-level count. Old values still go to `ohlcv_revision`. `should_refuse` is deleted (`src/intelligence/bars/write_contract.py` now has `revision_flagged` and `refuse_removal`).
2. Removal is not a restatement: no vendor served a new value, the canonical rule stopped choosing the stored one. Removed rows above the same share still refuse that one name, with the existing waiver (a recorded corporate action, a 1d policy change or a restore). The case that motivated keeping it: AVA's 22:48 UTC run would have deleted 2,766 `ibkr_fallback` rows (2005 to 2016) whose IBKR raw rows still exist. A basis-change signature on a raw load still gates through the restatement detector's unreviewed-basis flag (D-191-N item 2).
3. Per-name isolation. Each name is its own transaction, so a refused or failed name never discards another name's writes. The batch closes `partial` (migration 493) when some names failed and at least one wrote, `failed` only when none wrote; the failures are listed in the batch detail. The fetcher refreshes the 1d ledger bounds for every name whose daily load applied in the run, whatever the stage's exit code.

### D-191-H: explicit deferrals

Status: planner decision, owner acknowledgement pending

Phase 191 does not deliver: the D7 condition for todo 520, todo 524's D7 tolerance rule and price/volume split, todo 531's `market_data_5m` naming pass, and todo 527's 5m shaper dedup. Plan 18 records each as a deferral in its todo.
