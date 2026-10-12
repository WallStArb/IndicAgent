# 533: one raw bar table for every vendor and timeframe; canonical is a selection from it

Filed: 2026-10-12 (widened the same day from the vendor/kind column split, owner direction)
Owner: pending
Priority: P0 (owner, 2026-10-12: immediate priority; get the data layer to its final state).
Phase-sized: steps 1-2 open it, then promote it to a phase (`/gsd-phase`) for steps 3-9.

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

0. **Now, before the design (stop the bleeding):**
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
- **492** Tradier vs IBKR before D: which vendor's closes are canonical pre-2026-10-07 is a
  selection-policy row, and raw keeps both.
- **518** volume basis change at D: kind per span makes the basis explicit; the tradeable view
  and S0 labels read it.
- **433** listing-venue truncation: venue bars become kind `venue` in raw; the policy decides
  where they enter canonical.
- **519** names frozen at their last Tradier bar: per-name policy rows (fix, review or freeze).

**Adjacent: touch the same layer, run on their own clock**
- **512** exclusion and delete policy: the design doc states what an exclusion deletes in raw
  (the CLAUDE.md data rule: bar data and derived data go, metadata and tombstone stay).
- **525** single-day provider gaps: a fetch-ledger (`ohlcv_empty_history`) change; independent
  of the raw layout but read by the same gap planner.
- **531** schema names without glossary entries: the new raw table and the `kind` vocabulary get
  glossary entries in step 1; fold 531's `market_data_5m` and related names into that pass.
- **505, 513** nightly lane budget and stage contract: the nightly writes through the step 3
  writer; their markers and budgets are written against it.
