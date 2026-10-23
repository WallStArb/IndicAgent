# 533: one raw bar table for every vendor and timeframe; canonical is a selection from it

Filed: 2026-10-12 (widened the same day from the vendor/kind column split, owner direction)
Owner: pending
Priority: P0 (owner, 2026-10-12: immediate priority; get the data layer to its final state).
Phase-sized: steps 1-2 open it, then promote it to a phase (`/gsd-phase`) for steps 3-9.

## Status 2026-10-22 (plan 191-18)

Executing as phase 191. Steps 3 to 9 are done: plans 01 to 18 landed the one raw table
(`ohlcv_raw`, vendor plus kind, last-wins with the revision log), cut every reader and writer
over, dropped `ohlcv_observation`, `ohlcv_intraday_raw_archive` and `market_data_ohlcv_old`,
and closed green (R6 gate exit 0, D7 same known failures or better, selection gate exit 0, repro_frozen bit-identical;
191-17-SUMMARY.md). What remains is the Tradier retirement (step 10, owner direction above):
plans 191-19 to 191-25. Removal note: `scripts/ops/bars/ops_old_store_backup.py` and
`data/backups/191/` (2.9 GB gz old-store backup, manifest retained) are deleted on or after
2026-11-12, tracked here; the `infra.old_store_backup.disk_margin` APR key retires with them
(`retire: 191-25` in test_table_and_apr_key_readers.py).

## Owner direction (2026-10-12)

- Raw is one table: every timeframe, every vendor.
- Raw is NOT append-only: a refetch replaces the earlier answer (append-only wastes space when
  we refetch).
- `ohlcv_observation` is unnecessary and complicates a simple process; delete it.
- Make it an immediate priority and reach the final state.

## Target design

- **Raw** (`ohlcv_raw` or similar; glossary first): key (timestamp, symbol, timeframe, vendor,
  kind). `vendor` is the `ohlcv_load` vocabulary (ibkr, alpaca, tradier). `kind` carries what the
  label suffix carries today (named, venue, fallback, and the 1d route SMART vs a former listing
  venue), so two IBKR answers for one date coexist. Every served bar lands here, winners
  included. Upsert last-wins.
- **Revision log on raw:** the raw writer classifies incoming against the same vendor's stored
  row. Unchanged rows cost nothing; a changed row's old values go to `ohlcv_revision`. A vendor
  restating its own history (IBKR after a split) is evidence; `services/split_detection.py` reads
  observation history for exactly this today. Revisions are rare, so last-wins keeps the space
  saving without losing that evidence.
- **Canonical** (`market_data_ohlcv`): a pure selection from raw by `bar_source_policy`
  (first-writer-stays, per-span primary), plus derived rows (the 15m/1h grid from 5m, D2's 1d).
  Rebuildable from raw at any time, as "raw data is permanent, derived data is cache" implies.
  Today canonical holds the only copy of winning bars, so it is not rebuildable.
- **Revision vs disagreement:** a revision is one vendor changing its own answer (raw-level,
  logged). Two vendors disagreeing on a slot is not a revision; selection resolves it by policy
  and the loser stays in raw. Today's ingress contract conflates them: an IBKR 5m chunk over an
  Alpaca-canonical span is "refused" at ratio 1.00 and fails the fetch item, so the run reports
  errors for the source policy working as designed.
- **Vendors are data, not schema:** the vendor vocabulary lives in CVR (`controlled_vocabulary`,
  namespace for bar vendors), not a CHECK constraint (`ohlcv_load_source_check` hardcodes four
  today). Onboarding a vendor is one CVR row, one `history_leaf`, one `VendorIngress` row and
  APR seeds (the 528 onboarding rule), never a migration. Known now: ibkr, alpaca, tradier
  (stored history only), and Databento (key since 2026-10-10, `docs/reference/databento-api.md`;
  admission needs a measured basis study). Clear Street is an execution venue with no market
  data (`docs/reference/clearstreet-api.md`): its fills belong to the execution path, never to
  the bar tables.
- **Raw holds what the vendor served, at the timeframe it served:** Databento has no 5m schema
  (1s/1m/1h/1d only), so its raw rows are 1m and any 5m from it is a derivation on the canonical
  side, labeled as derived, never stored in raw as if Databento served it.
- **Fetch ledger:** `ohlcv_request` stays (answered and no_data windows can't be read off bars).
- **Deleted:** `ohlcv_observation` (1d only, append per request, 16M rows / 3.5 GB on
  2026-10-12) and `ohlcv_intraday_raw_archive` (folds into raw).
- **Canonical source column:** vendor plus kind in the raw vocabulary; `market_data_ohlcv_tradeable`
  nulls volume by kind (venue and fallback volume is not consolidated), not by a label suffix.

## Execution sequence

0. **DONE 2026-10-12 (stop the bleeding):** parity lane paused via `infra.backfill.grid_parity_sample_names_per_week = 0` (config_history v2; restore the 10 at step 8 of the design doc); run status `failed` when nothing succeeded, and a refusal over another vendor's rows counts as answered.
   - Pause the fetcher's 15m/1h parity lane until step 4: an archive-timeframe refusal upserts
     the refused rows into the same archive table, overwriting the stored rows it meant to
     protect (code review, 2026-10-12). The 5m backfill keeps running: everything it serves lands
     in canonical (new slots) or the archive (refused), both keyed by source, and migrates into
     raw at step 4 without a refetch.
   - Fetcher run status: a run with `n_ok = 0` reports `partial` (exit 0) and hides an all-error
     run (seen 2026-10-11: three 4h runs, 0 of ~300 items ok, all `partial`). Report `failed`
     when nothing succeeded, but count a policy refusal (another vendor already canonical) as
     answered, not as an error, so the fix doesn't turn the Alpaca-covered walk red.
1. **Design doc** `docs/plans/2026-10-12-unified-raw-bar-table-design.md`: schema, vocabulary
   (glossary entries for the raw table, vendor, kind; CVR namespace for kind), the selection
   rule, the revision rule, migration plan, reader cutover order. Amend
   `docs/plans/2026-10-06-data-layer-integrity-design.md` (capture law 528 becomes "raw takes
   every answer"). AGY/Codex review.
2. **Promote to a phase** with the design doc as its spec; plans follow steps 3-9.
3. **Schema and writer:** create the raw hypertable (compressed, policy as the archive's); one
   raw writer behind the ingress contract that always writes raw first, then runs canonical
   selection. The fetcher and the Alpaca loader (`services/bar_load.py`) switch to it.
4. **Backfill raw without refetching:** from canonical winners (`market_data_ohlcv` vendor rows),
   `ohlcv_intraday_raw_archive` and `ohlcv_observation`. Balance check: every canonical vendor
   row has its raw twin (R6-style, zero unexplained).
5. **Selection rebuild check:** canonical selected from raw equals today's canonical, row for
   row (vendor rows), before anything reads the new path.
6. **Cut 1d readers over** from `ohlcv_observation` to raw: `bar_derivation` (daily rule),
   `bar_reconciliation_audit` (D7), `split_detection`, `listing_venue_writer`,
   `dividend_event_writer`, `bar_load`, `bar_hold`, `ohlcv_observation_writer` (deleted),
   `_d1_gaps`, `_history_fetch`, the ops scripts (`ops_head_rerun`, `ops_source_policy`,
   `ops_venue_study`, `ops_d1_bootstrap`) and the two research scripts.
7. **Canonical `source` to vendor plus kind:** the tradeable view by kind; D7, the 1d digest,
   `CANONICAL_1D_SOURCES`, the completeness report's `CASE` and
   `integrity_checks._PRIMARY_LABEL` read the new columns; `sources.LABEL_VENDOR` retires. About
   450M rows on compressed hypertables (bare `VACUUM` per the compressed-column migration
   template).
8. **Drop** `ohlcv_observation` and `ohlcv_intraday_raw_archive`; `VACUUM`; resume the parity
   lane against raw.
9. **Close:** R6 and D7 green on the new tables; `repro_frozen` bit-identical if anything under
   `src/intelligence/research|statistics` moved; todo 530 closes with it.

Ordering against 186-26: canonical values do not change (step 5 proves it), so the
`feature_vectors` rebuild does not wait on this phase; it must not run during steps 4-7's table
rewrites (contention).

## Why (evidence, 2026-10-12)

- The bar `source` label mixes vendors (`alpaca`, `tradier`), vendor plus kind (`ibkr_named`,
  `ibkr_fallback`) and a computation (`derived_5m`). `ohlcv_load.source` holds vendors only; the
  mismatch broke every IBKR ingress write from 2026-10-10 15:03 UTC to 2026-10-12 (aaa67e637,
  fixed in 33a177772). `src/intelligence/bars/sources.LABEL_VENDOR` (31e61063c) is the single
  label-to-vendor map until step 7.
- Raw today is three places: canonical (winners only), `ohlcv_intraday_raw_archive` (losers,
  refusals, 15m/1h; keyed with source, last-wins) and `ohlcv_observation` (1d, append). The 82M
  Alpaca 5m archive rows came from a one-off archive campaign; canonical holds 220M.
- A refused chunk used to end the history walk (fixed in 9c0695b7a); names whose recent 5m span
  is Alpaca-canonical never reached older IBKR history.

## Tradier retirement (owner, 2026-10-12)

Owner: Tradier is not used for this at all; delete the old code (keep the connector only if
needed; recommendation: drop it too) and delete all Tradier data ("it's junk"). Agreed order,
because Tradier is the only source for about 2.96M canonical 1d bars (measured 2026-10-12: 2.45M
before IBKR's first 1d bar across 962 names, mostly 2000-2006; 508K interior holes across 623
names; one name with no IBKR 1d at all):

1. **Ask IBKR first (running):** `infra.backfill.depth_days.1d` 7300 -> 9800 (config_history,
   `user_override:owner`), and the 1d planner no longer counts Tradier answers as coverage
   (4fa3db578, `_d1_gaps.py`). About 2,000 extra 1d requests over 1,196 names, spread over
   the weekly gap-fill sessions. IBKR answers `no_data` where it has nothing, recorded in
   `ohlcv_empty_history`.
2. **Measure the residue** after one full gap-fill cycle: sessions still answered only by
   Tradier, per name. SMART cannot reach behind a listing-venue move (todo 433), so the
   venue-moved names are the expected residue.
3. **Switch canonical to IBKR** for every pre-D span (selection rule; replaces the Tradier rows of
   `bar_source_policy`), re-derive 1d, and let D7 judge it.
4. **Delete Tradier data:** `market_data_ohlcv` source `tradier`, `ohlcv_observation` route
   `TRADIER`, its `ohlcv_load` rows; a `pg_dump` of those rows kept until about 2026-11-12 (the
   185-45 backup precedent, todo 510). Names left with shorter history are recorded (per-name
   first-bar change), never silently truncated. This needs a dated owner exception to CLAUDE.md's
   "raw market data is permanent" rule, written into the design doc.
5. **Delete Tradier code:** `SOURCE_TRADIER`/`ROUTE_TRADIER`, the Tradier rows and branches in
   `CANONICAL_1D_SOURCES`, `daily_rule`, `vendor_basis`, `integrity_checks._PRIMARY_LABEL`,
   `source_admission`, the planner exclusion added in step 1, ops/research scripts and their
   tests (about 20 modules and 35 test files reference it on 2026-10-12).

Todo 492 (Tradier vs IBKR reconciliation) is closed as superseded: no arbitration is needed when
Tradier is deleted. Todo 519 stays open for its IBKR side only: PSKY, WBD and QRVO fail IBKR
contract qualification and MOD's fallback is refused, so each needs a contract fix or a recorded
freeze; its Tradier side goes with step 4.

## Related work (mapped 2026-10-12)

**Fold in: same tables or writers, done once inside this phase**
- **530** R6 derived-1d residue: the vendor plus kind key resolves it; closes at step 9.
- **527** simplify backlog: its answered-window consolidation (five copies) and 5m shaper dedup
  are the gap readers and writer this phase rewrites (steps 3 and 6). Apply those items here, not
  after.
- **520** future-timestamp guard: belongs in the one raw writer (step 3), with its D7 condition.
- **524** parity volume basis: the 15m/1h parity data moves into raw, and D7's dated tolerance
  rule and price/volume split are written against raw (steps 6 and 8).
- **504** dividend writer source registry: it reads `ohlcv_observation` (the IBKR adjusted-last
  ratio), so its cutover is step 6; build the source registry the same way vendors become CVR
  data.
- **521** Alpaca build's remaining piece, the nightly (`ops_bar_nightly`, unscheduled): wire it to
  the new raw writer, not the current contract, so it is built once.
- **189-11** (phase 189 completion check): its "vendor 15m/1h rows out of the canonical grid" is a
  step 7 outcome (canonical holds derived 15m/1h only; vendor rows live in raw). Check 189-11
  against this layout, not separately.

**Inputs: owner decisions the canonical selection rule (design doc, step 1) must encode**
- **492** closed 2026-10-12, superseded by the Tradier retirement above.
- **518** volume basis change at D: kind per span makes the basis explicit; the tradeable view
  and S0 labels read it.
- **433** listing-venue truncation: venue bars become kind `venue` in raw; the policy decides
  where they enter canonical.
- **519** the four frozen names: IBKR-or-nothing after the Tradier retirement (contract fix or
  recorded freeze).

**Adjacent: touch the same layer, run on their own clock**
- **512** exclusion and delete policy: the design doc states what an exclusion deletes in raw
  (the CLAUDE.md data rule: bar data and derived data go, metadata and tombstone stay).
- **525** single-day provider gaps: a fetch-ledger (`ohlcv_empty_history`) change; independent
  of the raw layout but read by the same gap planner.
- **531** schema names without glossary entries: the new raw table and the `kind` vocabulary get
  glossary entries in step 1; fold 531's `market_data_5m` and related names into that pass.
- **505, 513** nightly lane budget and stage contract: the nightly writes through the step 3
  writer; their markers and budgets are written against it.
