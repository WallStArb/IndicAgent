# Unified raw bar table design

Author: Claude (Sonnet 5.5), 2026-10-12, at Brandon's direction (todo 533, P0: "one raw table for every vendor and timeframe", "ohlcv_observation is unnecessary", "reach the final state")
Status: implemented (phase 191, plans 01-25; close evidence in `.planning/phases/191-unified-raw-bar-table/191-17-SUMMARY.md`, review-fix trail in the plan summaries and todo 535). Condensed 2026-11-14 to the principles, the schema, the ingress contract and the decision register (D-191-A to Q), which code and runbooks cite; the full text (problem measurements, migration plan, Tradier exception, D-191-M per-load table) is in git history at `1ec3bce55`. Current ownership and the provider matrix live in `docs/foundation/canonical-truth-registry.md`; the Massive admission design (`docs/plans/2026-11-10-massive-admission-db-design.md`, docs list) names an `_agg` amendment to this doc that has not been written yet.
Informed by: `.planning/todos/completed/533-bar-source-column-split-vendor-and-kind.md`, `docs/plans/archive/2026-10-06-data-layer-integrity-design.md`, `docs/plans/archive/2026-10-10-raw-capture-enforcement.md` (528), `docs/plans/archive/2026-10-09-provider-history-plane-unification-design.md` (190), `docs/reference/databento-api.md`, live read-only queries on 2026-10-12.

## Problem

Raw vendor answers lived in three stores, none complete or uniform: `market_data_ohlcv` (winners only, under a `source` label that mixed vendor, vendor plus kind and computation), `ohlcv_intraday_raw_archive` (losers and parity rows) and `ohlcv_observation` (1d answers per request). Canonical held the only copy of winning bars, so it was not rebuildable, and two vendors disagreeing on a slot was treated as a revision and refused.

## Principles

1. Raw is one table: every vendor, every timeframe the vendor served, at the timeframe it served.
2. Raw is a current-state table, not an append log. A refetch replaces the earlier answer (last-wins). What a vendor said before is kept only when it changed (revision log).
3. A revision is one vendor changing its own answer. A disagreement is two vendors answering one slot differently. They are different facts with different records.
4. Canonical (`market_data_ohlcv`) is a selection from raw by policy, plus derived rows. It is rebuildable from raw at any time.
5. Vendors are data (controlled vocabulary), not schema. Onboarding a vendor is a CVR row, a `history_leaf`, a `VendorIngress` row and APR seeds, never a migration.
6. One writer per table, one direction: fetch -> ingress contract -> raw -> selection -> canonical -> derivation.

## Schema

`ohlcv_raw`: primary key `(timestamp, symbol, timeframe, vendor, kind)`; `open, high, low, close` double precision with a finite CHECK; `volume` bigint; `served_at` (when this value was first served), `request_id` (the `ohlcv_request` that first served it) and `load_id` (the `ohlcv_load` that set the row). The three lineage columns are NULL only on rows migrated from stores that never captured them; the ingress contract refuses a new write without them, and a migrated `served_at` is the true archive or fetch time or NULL, never `now()`.

- 1d uses the canonical convention (00:00 UTC of the session date). Raw holds what the vendor served only: a timeframe a vendor does not serve is a derivation on the canonical side, never stored in raw as if served.
- `vendor` (CVR `bar_vendor`) and `kind` (CVR `bar_kind`) carry no CHECK; the writer validates against `VocabularyService`, so a new vendor needs no migration.
- Hypertable on `timestamp`, 30-day chunks, compression segmented by (symbol, timeframe, vendor).

`ohlcv_revision` holds the previous value of a row a vendor restated, keyed `(load_id, symbol, timeframe, timestamp, vendor, kind)`, with `request_id`, so corporate-action evidence and the daily rule's current-scale test resolve by request. The raw writer classifies each incoming row against the same key: unchanged writes nothing; new inserts; changed logs the old values and replaces the row.

### Canonical

Selection, not authoring: for each (symbol, timeframe, timestamp) the row comes from raw by `bar_source_policy`, or from derivation for derived timeframes and the daily rule's 1d. Selection is a pure function of raw and policy, never of write order: the policy ranks vendors per span (`primary_source`, then `fallback_source`) and a slot takes the highest-ranked vendor holding it (refined to whole sessions by D-191-M item 9). Canonical carries `(vendor, kind)` (derived rows: vendor `derived`, kind the rule); the tradeable view nulls volume by kind. The loser stays in raw and is never an error. `ops_selection_gate.py --compare` is the standing proof that canonical is a pure function of raw plus policy.

### Fetch ledger

`ohlcv_request` stays (answered and `no_data` windows cannot be read off bars), written by `services/ohlcv_request_writer.py`. `ohlcv_load` is the per-write record (`destination` `raw` or `market_data_ohlcv`).

## Ingress contract

One writer, `services/ohlcv_ingress_contract.py`, behind the `VendorIngress` rows:

1. Write raw first (classify, insert, log revisions), always, for every served bar including losers.
2. Run canonical selection for the touched (symbol, timeframe, sessions). A slot whose policy primary is another vendor changes nothing in canonical.
3. Every vendor re-serve is written last-wins and reported by the restatement detector (D-191-N). Nothing is refused or held, and a cross-vendor difference is never a revision.
4. Raw is stored per source and agnostic to every other source: no fetch or write path asks what another vendor holds (D-191-K).

## Migration plan (executed)

Steps as cited by code and migrations: 3 schema and writer (`ohlcv_raw`, CVR namespaces, widened `ohlcv_revision`, the raw writer behind the contract); 4 backfill raw from the three old stores with an R6-style balance check; 5 selection rebuild check (canonical selected from raw equals the live canonical row for row); 6 readers cut over to raw and `canonical_bar_lineage` redefined over `ohlcv_raw`; 7 canonical `source` split to `(vendor, kind)` by a built-and-swapped table; 8 old stores dropped; 9 close (R6, D7, `repro_frozen`); 10 Tradier retirement (done; migration 589 deleted the rows 2026-11-12).

## Invariant mapping

- `single_writer`: the ingress contract writes raw; selection writes canonical; derivation writes derived rows. No reader writes.
- `lineage`: `ohlcv_raw.load_id` ties a row to its write; `ohlcv_revision` ties a restatement to its load.
- `temporal_integrity`: raw rows carry `served_at`, so "what was knowable by t" is answerable for the current answer; earlier answers are in the revision log.
- `determinism`: canonical is a pure function of raw plus `bar_source_policy` plus derivation rules.
- `asset_agnostic`: vendor and kind are data; no asset-class branch.

## Decision register (resolved at planning, 2026-10-12, and after)

Every entry was acknowledged or superseded by the owner on or before 2026-10-27. Superseded entries keep one line as the record of what ran.

### D-191-A: kind rules

Raw `kind` is what the vendor served, so `fallback` is a canonical-only kind the daily rule assigns, never written to raw. Tradier `consolidated`, Alpaca `sip_rth` (RTH-window SIP aggregates, split-adjusted: an unadjusted answer must never land last-wins as `sip_rth`), Alpaca `iex_rth` (feed=iex, raw only, never selected), IBKR 1d `smart_trades` and `smart_adjusted` (a listing-venue route with TRADES maps to `venue`). `derived` is the vendor only of the 15m/1h grid (kind `5m_grid`); the rule version stays in `bar_derivation_batch`. The single definition is `src/intelligence/bars/vendor_kind.py`.

### D-191-B: canonical 1d rows keep the winning raw (vendor, kind)

`canonical_kind_for_raw`: `smart_trades` becomes `named`, `venue` and `consolidated` stay; adjusted bars are never canonical. The tradeable view then nulls volume by kind.

### D-191-C: policy spans are data, seeded at the selection gate

The schema migration dropped the `bar_source_policy` CHECKs on `primary_source` and `fallback_source` and seeded no span; spans are written through `scripts/ops/bars/ops_source_policy.py`. Mechanism kept; the seeded content was superseded by D-191-P.

### D-191-D: conservative fetch_run_id pairing

Last-wins raw keeps the `request_id` that first served each value. The dividend writer, D7 and the daily rule accept `served_at` ordering between TRADES and ADJUSTED_LAST only when neither row has `ohlcv_revision` history after the adjusted serve; otherwise the same `fetch_run_id` through `request_id` is required. Split detection orders restatement history by `ohlcv_request.answered_at`, never by `ohlcv_load.loaded_at`.

### D-191-E: revision evidence is reconstructed in the backfill

The backfill rebuilt `ohlcv_revision` rows from observation value history (one `ohlcv_load` per symbol, vendor and restatement ordinal, caller `raw-backfill-191`) so split detection kept its evidence.

### D-191-F: one cutover window

Writers and readers of the old stores stopped per unit and resumed as each reader cut over; the fetcher resumed only after the selection gate passed. No dual-write.

### D-191-G: the v2 canonical table is a copy-with-map

Step 7 built the new canonical by copy-with-map from the live table (label to `(vendor, kind)`), not by selection; the selection gate re-run on it is the rebuildability proof.

### D-191-H: explicit deferrals

Phase 191 did not deliver the D7 condition for todo 520, todo 524's tolerance rule, todo 531's `market_data_5m` naming pass or todo 527's 5m shaper dedup; each is recorded in its todo.

### D-191-I: a refusal holds (superseded)

Superseded 2026-10-14 by D-191-N. Refused values were held as `pending` revisions until then; migration 482 removed the origin.

### D-191-J: a forming 1d bar is not a vendor answer

A 1d bar served before its NYSE session closes (`session_complete_at`, early closes included) is still forming: it is not offered to raw, and its later completion is not a restatement. The boundary is the close instant, with no grace period; a date with no calendar session counts as complete once it has passed.

### D-191-K: the fetch question is per source

The gap planner asks, for one vendor, which slots of [A, B] are missing from its own `ohlcv_raw` rows, minus its own answered request windows (a definitive `no_data` included). Another vendor's rows or the canonical selection never cover a slot. Verification asks (an overlap re-ask, an escalation refetch) stay outside the planner, because a restated history is visible only by comparing a fresh serve with the same source's stored values.

### D-191-L: session rule, session-date spans, what a loader reports

1. A regular-hours kind (`sip_rth`) is a selection candidate only on the RTH grid (open inclusive, close exclusive, NYSE early closes); raw keeps every stamp served. The rule is by kind, not a vendor-blind calendar filter.
2. Spans match the NYSE session date (the `America/New_York` date of the stamp), not the UTC date.
3. One writer per series at a time: `select_and_write` takes `pg_advisory_xact_lock` on `bar_selection|symbol|timeframe` in sorted symbol order.
4. A loader reports what it did not select: a slot in raw that no ranked vendor holds is counted (`unselected`) and the load is not APPLIED; slots whose only candidates are a never-selected kind are counted apart and do not fail a loader.

### D-191-M: explained is not clean

Surviving items: the selection gate exits 0 only when canonical equals the selection exactly (item 1); a direct-timeframe policy span effective before today is written only with `--reselect` (item 5); a bar is a complete vendor answer only when its block ended at or before the request end and before the answer, and a bar ending at the session close was answered at least `threshold.bar_integrity.session_close_settle_s` after it (`src/intelligence/bars/complete_bars.py`, applied in the shared fetch layer to every vendor; a held-back bar is written on `ohlcv_request.partial_bars`) (item 8); selection takes each session whole from the first ranked vendor holding every slot any ranked vendor holds, else the vendor holding most, and never splices a session from two vendors (item 9). The refusal, hold and repair items (2, 3, 4, 6, 7) were superseded by D-191-N, and their tools were deleted.

### D-191-N: last-wins; a restatement is detected and reported, never refused or held

Owner decision 2026-10-14. A vendor's own re-serve always overwrites its raw value last-wins, and the old value is logged as an `ohlcv_revision` row (origin `raw`) under the load that replaced it. The revision log makes every overwrite recoverable; routine restatements (closing-auction volume on the last bar, late prints) are the vendor correcting itself.

1. Ingress writes every series of a chunk last-wins and selects the touched sessions.
2. The restatement detector (`src/intelligence/bars/restatement.py`, migration 481) reports each load's changed share of the vendor's stored rows and two basis-change signatures (a near-constant price ratio over many changed bars, a one-bar time shift); a flagged load is logged, counted on `ohlcv_restatement_flags_total` and recorded in `ohlcv_restatement_flag`. It never blocks a write. Thresholds are APR (`threshold.bar_integrity.restatement_*`).
3. The holds that existed were released once on 2026-10-14 (4,572 offers written, 80 kept as ordinary revisions); migration 482 removed the `pending` origin.
4. The selection gate proves canonical equals the selection of raw exactly; any difference is real. Residue is a canonical session mixing vendors or a session choice `bar_session_choice` (migration 480) does not hold.
5. Session choices are data: `bar_session_choice` keeps every session not taken plainly (fallback vendor, no complete vendor, fewer slots than the grid), with `n_primary_grid_slots` (migration 484) telling a fallback by absence from one by shortfall. A fallback session is a day-level volume step (IBKR to Alpaca 5m volume about 0.38 to 0.95); it is recorded, never rescaled.
6. The gap planner never counts the window of a request whose own load was refused as answered.

### D-191-O: the derivation stage applies restatements last-wins; a failed name never fails the run

Decided 2026-10-15 under the owner's standing direction; extends D-191-N to `services/bar_derivation.py`. The revision ratio is a non-blocking flag (`revision_flagged` in `src/intelligence/bars/write_contract.py`). Removal is not a restatement: removed rows above the same share still refuse that one name (`refuse_removal`), with the existing waiver (a recorded corporate action, a 1d policy change or a restore). Each name is its own transaction; the batch closes `partial` (migration 493) when some names failed and at least one wrote.

### D-191-P: canonical 5m, Alpaca SIP primary from 2016

Owner decision 2026-10-26. `(alpaca, sip_rth)` is primary for 5m from 2016-01-04 with IBKR as fallback; IBKR alone before. One fixed, documented seam replaces a canonical that moved vendor session by session as the IBKR backfill landed (IBKR 5m volume about 0.38 to 0.95 of SIP). Step 7 of the Massive admission replaces the pre-2016 leg (`docs/operations/massive-step7-runbook.md`).

### D-191-Q: canonical 1d, Alpaca SIP primary from 2016 after the Tradier deletion

Owner decision 2026-10-27. Measured then: IBKR daily volume 0.41 to 0.91 of consolidated (p10 to p90); IBKR lacked 494,567 of Tradier's 2016+ sessions on 311 names; Alpaca SIP 1d matched Tradier (opens p99 5.6 bp, open-to-open returns p90 0.16 bp, volume 1.03x). Decision: `(alpaca, sip_rth)` split-adjusted is primary for 1d from 2016-01-04 with IBKR fallback, IBKR alone before; a zero-volume bar never serves, from either vendor. Exceptions are dated per-name policy rows from a one-time three-vendor arbitration, never a runtime guard (OKE drifted 0.76 to 1.42 of Alpaca over 2018-2023; RJF sat at exactly 2/3 before 2021-09-22). The daily rule moved to d2-v4 (Alpaca matched by session date: Alpaca stamps 1d at midnight New York, IBKR at 00:00 UTC). The 2016 volume seam is recorded; specs reading volume across it normalize within each era. Step 7's policy switch (d2-v6) replaces the pre-2016 IBKR leg with Massive.
