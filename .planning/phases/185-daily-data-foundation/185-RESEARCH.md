# Phase 185: Daily data foundation - Research

**Researched:** 2026-09-26
**Domain:** Market-data integrity layer on TimescaleDB (raw IBKR observation store, versioned canonical-bar derivation, scrubbing, corporate actions, reconciliation audits)
**Confidence:** HIGH for the current-state facts (all read from live code and the live DB, read-only); MEDIUM for sizing (extrapolated from measured unit costs); LOW where flagged `[ASSUMED]`

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Sources and scope
- **D-01:** IBKR only for prices. No new data sources (owner, 2026-09-26). Yahoo's dividend history stays as reference data in `dividend_events` (todo 428); it is never a price source. Stage V (vendor) stays closed. Stages are source-agnostic so a vendor later becomes one more `source` value in D1.
- **D-02:** Daily bars are the scope of D1, D2 and D5. Intraday keeps its current table; only D3's venue-move inventory and recovery, D7's daily-vs-aggregated-intraday check and D2b's derived 15m/1h grid reach intraday in this phase.
- **D-03:** D8 (forward survivorship capture) is descoped. Todo 438 (borrow snapshots) is outside this phase. A delisted name is never soft-deleted (`is_active` untouched).

#### D0 data-quality labels
- **D-04:** Every research attempt carries typed data-quality labels recorded with the attempt: venue truncation share (daily and intraday cells on names whose history starts at a venue move), dividends (total-return flag plus share of cells without dividend coverage), survivorship bound (literature haircut plus delisting-return sensitivity per unified design 12.2), and scrub-flag share (cells on D2a-flagged bars). Old verdicts are not re-run (they are UCR summary cards). Reruns happen only for reopened ideas, on canonical bars.

#### D1 raw observation store
- **D-05:** Append-only `ohlcv_observation` table for 1d: symbol, bar date, OHLCV, `source` (ibkr), `route` (SMART or a venue code), `what_to_show` (TRADES, ADJUSTED_LAST), `fetched_at`, request id. Every IBKR answer lands here first, including routes not chosen. Expected size 12-18M rows. Loaded with `COPY`; D1 writer and D2 derivation are separate database roles (unified design 14.5).

#### D2 canonical derivation
- **D-06:** A deterministic, versioned rule derives 1d rows from D1 and writes them into `market_data_ohlcv`. The derivation is the only writer of 1d rows there (owner decision 2). Every consumer keeps reading the same table and view. Each canonical row carries the rule version and the observations it came from.
- **D-07:** Revisions propagate through the unified design's provenance batches keyed by an input content digest per (symbol, tf, range) (design 3.3), so downstream writers recompute only affected cells. Every research snapshot records the D2 rule version it read.

#### D2a scrubbing
- **D-08:** Scrubbing is a stage of the derivation, not a side audit. Rules are APR-parameterized pure functions over D1 observations: OHLC invariants, non-positive/zero prices, volatility-scaled jumps with no recorded corporate action, repeated stale prints, volume outliers, IBKR view disagreement (D7).
- **D-09:** Flag, never delete. Each canonical bar carries a quality flag and the rule that set it. Raw observations are permanent. S0 excludes flagged bars by default (quarantine).
- **D-10:** Every rule is validated on known answers before it touches research data: known splits/reverse splits, known corporate events, the 15 `confirmed_corrupt` rows, hand-checked real extreme moves, and the 2026-09-26 dry run of `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py --tf 1d` (45 unflagged corrupt bars; 27 bars wrongly cleared by cross-symbol corroboration, 26 of them 2010-05-06 Flash Crash stub prints plus EWW 2006-11-07; 1,864 ambiguous edge bars that are not candidates).
- **D-11:** Cross-symbol corroboration must not clear a print beyond the magnitude threshold. The Flash Crash date is a known answer for that rule.
- **D-12:** One historical batch pass over all 1d history (minutes), then the same rules on every nightly derivation. Folds in todos 155, 347 and 052.
- **D-13:** Reuse `classify_candidate_bar` in `src/intelligence/statistics/price_sanity.py` as one D2a rule, run as a batch rule (not through the disabled `bar_auditor`).
- **D-14:** `forward_return_writer`'s bar-describing flags (`return_*_suspect`, cross-symbol corroboration, `has_gap_before_entry`) move to bar flags before phase 186 deletes that writer (UD-25, design 14.7). Intraday gets the rules once proven at 1d.

#### D2b derived 15m and 1h grid (UD-25, todo 446)
- **D-15:** The derivation writes 15m and 1h bars from 5m on session-anchored edges (09:30, 09:45, ...; 09:30, 10:30, ...): first open, last close, max high, min low, summed volume, never across a session boundary. These become the only 15m/1h rows readers see; stored IBKR 15m/1h become raw observations. Must land before phase 186's `feature_vectors` rebuild. Test: derived bars equal a direct computation from 5m and none spans a session.

#### D3 venue-move recovery (todo 433)
- **D-16:** The merged 433 fix (0d225b312) is rebased on D1: store every venue's answer, leave the choice to D2.
- **D-17:** Venue bars are used only after a validation study on at least 30 names with known listing venues across NYSE, Nasdaq and NYSE Arca shows (a) the listing venue has the most volume on nearly every day and (b) only its closes match SMART's. If either fails, venue bars stay stored and unused. The study fetches its own SMART and venue bars and does not wait on D1.
- **D-18:** Venue volume stays NULL in the tradeable view (owner decision). Recovered intraday bars get the same NULL-volume treatment and no intraday feature reads them until the study covers intraday too.
- **D-19:** Recovered intraday history enters through content-digest keys after phase 186's rebuild, never under a live or resumable ic_engine run. The rebuild does not wait on D3 and D3 does not wait on the rebuild.

#### D4 empty history
- **D-20:** A span is recorded empty only when every route answered a definitive "no data", answers kept in D1. Verify-only mode already shipped (0d225b312, migrations 374/375; `infra.ibkr.venue_fallback.store_bars` = false). The intraday `ohlcv_empty_history` rows need the same re-verification once verify-only covers intraday.

#### D5 corporate actions
- **D-21:** Splits: nightly fetch overlaps the last N stored days; a constant price ratio across the overlap is a split, recorded in a new `corporate_action` table with the inferring observations; D2 re-derives on one scale.
- **D-22:** IBKR dividends derived from ADJUSTED_LAST vs TRADES stored in D1, written to `dividend_events` with `source = 'ibkr_adjusted_last_ratio'`. D5 replaces only the I/O of `services/dividend_event_writer.py --sources ibkr` and reuses its pure functions unchanged (`join_adjustment_pairs`, `derive_ibkr_events` with the lockstep rule `threshold.dividend_event.stable_sessions`, `reconcile`, `research/dividends.DisputeRule`). Validate on known dividends (JPM, KO, XLU) before research uses IBKR rows alone.
- **D-23:** D5 needs a rule for 1-5 day date disagreements between sources (26 events on 18 names). Conservative choice: a disputed-date record that marks the spanning returns unknown.
- **D-24:** Split-seam audit of the existing corpus runs early (no D1/D2 dependency): compare stored closes with a fresh TRADES fetch; a constant ratio over a date range is a seam. MRNA 2026-08-19 and ALMS 2026-09-01 first.

#### D6 listing-venue history
- **D-25:** Point-in-time `listing_venue` (symbol, venue, valid_from, valid_to), inferred from D3's recovered spans.

#### D7 reconciliation
- **D-26:** A daily audit chained after the nightly backfill reports into `integrity_monitor` and Grafana: SMART vs venue, TRADES vs ADJUSTED_LAST outside explained factors, daily vs aggregated intraday (close = last regular-session 5m close, volume = intraday sum), unexplained seams, heads later than first known trade, empty-history rows not confirmed by every route, and dividend freshness (Yahoo coverage end vs last session). Thresholds in APR.

#### Order and minimum data bar
- **D-27:** Order: (1) D0 in parallel throughout; (2) 1d re-run under verify-only for the 384 late-starting names, the D3 validation study, the D5 seam audit and the D2a historical scrubbing pass with known-answer validation, none needing D1; (3) D1 then D3 rebased on it; (4) D2 derivation, then moved names re-backfilled through it if the study passed; (5) D5 split detection on the nightly overlap and the ADJUSTED_LAST dividend route; (6) D7; (7) D6. D2b lands before phase 186's rebuild.
- **D-28:** Daily attempts 3, 3b and 4 run only after: seam audit and scrubbing pass done (flagged bars quarantined); moved names flagged and excluded before their move unless recovered; total-return targets (todo 428 opt-in); survivorship bound. Step (2) of D-27 clears this bar.

### Claude's Discretion
- Plan decomposition, wave layout, migration numbering, module placement (respecting the Ring rule), table column details beyond those named above, APR key names under existing namespaces, and the exact known-answer test fixtures.

### Deferred Ideas (OUT OF SCOPE)
- D8 forward survivorship capture (descoped by owner 2026-09-26).
- Stage V vendor source (gated on owner lifting the no-new-sources constraint).
- Raw observation store for intraday (after the pattern proves itself at 1d).
- Todos 395 and 387 (nightly backfill reliability and staleness observability) sit in the same data lane but are not phase 185 deliverables; D7 consumes their output.
- Todo 438 (borrow snapshots) is outside this phase.
</user_constraints>

<phase_requirements>
## Phase Requirements

No requirement IDs are mapped (ROADMAP: "Requirements: TBD"; `.planning/REQUIREMENTS.md` does not exist). CONTEXT decisions D-01..D-28 are the contract. The planner should map each plan to the D-numbers it satisfies; the table below says which research finding enables each.

| ID | Description | Research support |
|----|-------------|------------------|
| D-04 | D0 labels on attempts | Findings 6, 13; survivorship seeds in "Code examples" |
| D-05 | D1 observation store | Findings 1, 2, 9 (request log + observation rows, same-run pairing for ADJUSTED_LAST) |
| D-06, D-07 | D2 derivation, sole 1d writer, revisions via digest | Findings 2, 3, 7, 8 (writer inventory, lineage-column conflict, digest ownership with 186) |
| D-08..D-14 | D2a scrubbing | Findings 4, 5, 10 (corroboration defect, flag storage measured, flag ports) |
| D-15 | D2b derived grid | Finding 11 (1h grid changes for all names, not 39; 15m/1h flag re-keying; writer switch-over) |
| D-16..D-19 | D3 | Findings 1, 12 (inventory is lost today; 186 D-32 conflict with D-19) |
| D-20 | D4 | Finding 1 (verify-only state, 84 of 381 heads re-verified) |
| D-21..D-24 | D5 | Findings 9, 14 (overlap fetch cost, same-run pairing, MRNA/ALMS look like events) |
| D-25 | D6 | Derived from D1 venue answers |
| D-26 | D7 | Finding 15 (the close rule as written fails on about 85% of days; no Postgres datasource in Grafana) |
| D-27, D-28 | Order and bar | "Recommended plan decomposition" |
</phase_requirements>

## Summary

Phase 185 turns `market_data_ohlcv` from "whatever a fetch wrote" into "a derived, versioned, scrubbed view of permanent raw observations". The existing code gives a good base: the verify-only venue fallback (0d225b312) already asks former venues, `classify_candidate_bar` is a clean pure function, the dividend writer's derivation functions are pure and tested, `market_data_ohlcv_tradeable` is already the one read boundary (CI-enforced), and TimescaleDB 2.27 handles per-segment inserts into compressed chunks natively. Nothing of D1, D2, D2a (as a stage), D5 splits, D6 or D7 exists yet, and no provenance-batch or content-digest code exists anywhere in the repo.

Six facts change how the phase should be planned. (1) The moved-name inventory the spec relies on is not being captured: `ibkr.py` logs `hist_venue_fallback_recovered` through stdlib `logging` with `extra=`, and the captured logs show only the event name, no symbol, venue or dates. The re-run must write its answers somewhere durable before it runs, and the nightly backfill will re-ask the deleted 1d heads on its own the next time it runs. (2) Design 12.1's `lineage` invariant forbids per-row provenance columns on compressed hypertables, while D-06 says each canonical row "carries" its rule version and observations; the two reconcile only through side tables keyed by (symbol, tf, timestamp) or (symbol, tf, range). (3) A quarantine anti-join in the tradeable view costs nothing measurable (33 ms vs 37 ms on a 98k-row 5m read with 5,000 flags), so flags can live in an uncompressed side table instead of UPDATEs on compressed chunks. (4) D-15's 1h edges (09:30, 10:30, ...) move every name's 1h timestamps, not only the 39 missing the open; stored 1h rows sit at :00, so derived and stored rows would coexist unless the stored ones are moved out. (5) D-26's "daily close = last regular-session 5m close" fails on about 85% of days (the daily close is the closing auction; median gap 1-2 bp, max 23 bp in 2024), while opens and volumes match exactly. (6) Phase 186's CONTEXT (D-32, committed after 185's CONTEXT) makes the rebuild wait on 185's intraday venue recovery, which contradicts 185's D-19.

**Primary recommendation:** Build the D1 request log and observation table first (one small plan) so every IBKR fetch in step 2 (the 381-name re-run, the D3 study, the seam audit) lands its raw answers in D1 from day one. Store scrub flags in an uncompressed `bar_quality_flag` side table that the tradeable view anti-joins. Keep derivation provenance (rule version, observation ids, content digest) in side tables, never as columns on the hypertable. Write every new pure rule in new modules so no ic_engine-imported module is edited.

## Findings the planner cannot guess

1. **Todo 433 fix, current state.** `src/providers/ibkr.py` (1,653 lines): `_fetch_historical_bars_impl` walks SMART, then for `STK` in `_VENUE_FALLBACK_TIMEFRAMES` (1d only) calls `_fetch_pre_move_history`, which walks each of NYSE, ARCA, ISLAND, AMEX, BATS (skipping the current primary) over the uncovered head, keeps the highest-volume venue, and returns its bars only if `_VENUE_FALLBACK_STORE_BARS` is true. Venue bars carry `SOURCE_IBKR_VENUE`. Every venue's definitive "no data" counts as a confirmation toward the empty-history record; any ambiguous venue failure leaves the head unverified (asked again next run). APR keys (migration 374): `infra.ibkr.venue_fallback.exchanges` = the five codes, `.timeframes` = `["1d"]`, `.min_gap_days` = 7, `.store_bars` = false; the backfill overlays them onto module globals in `_load_ibkr_venue_fallback_config`. Migration 375 seeded `infra.ibkr.rate_limit_max_requests_by_tf`, now `{"1d": 200}` per 600 s window. [VERIFIED: code read, config_state query]
   - **The inventory is lost.** Logs use stdlib `logging.getLogger(__name__)` with `extra={...}`; a captured run (`backfill113.log`, another session's scratchpad) shows bare `ibkr.hist_venue_fallback_recovered` lines with no symbol, venue or span. The venue bars in verify-only mode are discarded after the volume comparison. [VERIFIED: log inspection]
   - **Re-run status.** 381 names (not 384) have their first `ibkr_named` 1d bar after 2006-11-01; 84 of them already have a re-verified 1d `ohlcv_empty_history` row (verified 2026-09-26 12:27-13:21 UTC, the onboarding run after migration 374); 297 have neither. 89 of the 381 are in the 233 intraday names. [VERIFIED: DB]
   - **The nightly will re-run it implicitly.** `indicagent-nightly-backfill` (05:00 UTC) runs the compute leg with default timeframes (`1d,1h,15m,5m,1m`) and a `compute_1d` leg for the rest, so it re-asks every deleted 1d head with venue fallback. But it skips the whole night when any `infrastructure_run_historical_pipeline.py` process is running (`_is_another_backfill_running`), and four such processes (client IDs 40-43, `--timeframes 1h,15m`, expansion names) are running now from another session. [VERIFIED: process list, code]
2. **1d rows in `market_data_ohlcv`.** One hypertable for every timeframe: time-only partitioning, 258 chunks (30-day ranges on disk; the dimension now says 90 days), compression after 30 days, `segmentby = symbol, timeframe`, `orderby = timestamp`. 242 chunks have status 9 (compressed + partial): recent backfills inserted into compressed chunks natively. TimescaleDB 2.27.1 on PostgreSQL 18.4. 1d is equity-only (931 names): 3,871,890 `ibkr_named` rows (2006-03-22 to 2026-09-24) plus 1,646,636 `synthetic_fill` rows (calendar grid including weekends; volume 0). No `ibkr_venue` rows exist. [VERIFIED: DB]
   - **Every writer of 1d rows today:** (a) `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` `store_bars` and `_persist_chunk` (multi-row VALUES INSERT ... ON CONFLICT DO NOTHING, after `normalize_bars` adds synthetic fills); (b) its `run_normalize` pass; (c) its FX/crypto 1m-derivation fallback (no 1d FX names are active, so dormant for 1d); (d) `services/backfill_feature_factory.py --fetch-only` (`_STORE_OHLCV_SQL`, legacy stage 1); (e) `services/bar_writer.py` for `market.bars.htf` (dormant: live streaming down) with source `live_htf`; (f) `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py --apply` and `services/bar_auditor.py` (both UPDATE `price_sanity_status`). "Exactly one writer" means (a)-(e) stop writing 1d rows and (f) moves into the derivation or the flag table. [VERIFIED: grep of `INSERT INTO market_data_ohlcv` and `UPDATE market_data_ohlcv`]
   - **`detect_gaps` depends on placeholders.** The pipeline finds 1d gaps against the calendar grid in `market_data_ohlcv`; once the backfill writes 1d observations to D1 instead, 1d gap detection must read D1 (or the derivation's output), or it will re-fetch everything every night.
   - **Tradeable view** (migration 374): `SELECT timestamp, symbol, timeframe, open, high, low, close, CASE WHEN source='ibkr_venue' THEN NULL ELSE volume END AS volume, source, base, price_sanity_status FROM market_data_ohlcv WHERE volume > 0 AND price_sanity_status IS DISTINCT FROM 'confirmed_corrupt'`. `CREATE OR REPLACE VIEW` must keep this column list and order. [VERIFIED: `\d+`]
3. **Lineage-column conflict.** Design 12.1 `lineage`: "bulk tables get a provenance batch record ... no per-row column on compressed hypertables (the 768 GB disk-full class)". 186-CONTEXT D-24 repeats it. D-06's "each canonical row carries the rule version and the observations it came from" must therefore be met by a side table (`bar_derivation` keyed (symbol, timeframe, timestamp) with `rule_version`, observation ids) plus a provenance batch record per (symbol, tf, range), not by new columns on `market_data_ohlcv`. Adding a nullable column is metadata-only in TimescaleDB 2.x `[ASSUMED]`, but the design forbids it regardless. [VERIFIED: design text]
4. **Scrub-flag storage, measured.** A hash anti-join against a 5,000-row flag set added no measurable cost to a 97,789-row SPY 5m read (37.0 ms without, 33.1 ms with; CTE proxy, read-only). A side table is therefore viable as the quarantine source, and it avoids row-level UPDATEs on compressed chunks, which `services/_batch_utils.py` documents as about 1000x a decompressed update (feature_vectors, 2026-08-14) and todo 155 measured at 7.55 s per 500 rows on this table. Native upsert of a whole (symbol, 1d) segment into compressed chunks was measured at 3.9 s for 4,834 rows with no disk growth (`compressed_hypertable_write_session` docstring, 2026-09-25). [VERIFIED: EXPLAIN ANALYZE here; CITED: `_batch_utils.py` docstring]
5. **Price-sanity classifier and the Flash Crash defect.** `classify_candidate_bar` (pure) returns CONFIRMED_CORRUPT only when a field is off by at least `magnitude_threshold` (APR `alpha.quant.price_sanity.magnitude_threshold` = 10.0) and the neighbors agree within `neighbor_agreement_threshold` (2.0). The defect is in `apply_cross_symbol_downgrade`: it turns any CONFIRMED_CORRUPT into MARKET_EVENT when `n_corroborating + 1 >= min_symbols` (APR `alpha.quant.cross_symbol_corroboration.min_symbols` = 4), whatever the magnitude. Because CONFIRMED_CORRUPT already requires a 10x field, every downgrade clears a 10x print; on 2010-05-06 the exchanges broke trades more than 60% from the 2:40 p.m. reference [CITED: SEC/CFTC findings], so no genuine print in that event is 10x off. Consequence: with a ceiling below 10x, corroboration can never clear a CONFIRMED_CORRUPT bar. The fix is a new rule function in a new module (do not change the shared function's behavior silently; `bar_auditor` and the cleanup script import it). The dry-run report with all 45 + 27 + 1,864 rows exists only in another session's scratchpad (`/tmp/claude-1000/-home-bg-dev-indicagent/4d54d9a0-f5fc-432f-802a-c4f5389344f1/scratchpad/corrupt_1d.txt`, 273 KB); it must be copied into the repo as a fixture before `/tmp` is cleaned. [VERIFIED: code, DB, file]
   - Existing `price_sanity_status` values: 1d 15 `confirmed_corrupt`; 15m 19; 5m 20; 1h 13 `confirmed_corrupt`, 16 `ambiguous`, 484 `plausible`. The 15m and 1h ones are keyed to stored-grid timestamps that D2b replaces. [VERIFIED: DB]
   - Todo 347's index `idx_market_data_ohlcv_price_sanity_unaudited (symbol, timeframe, timestamp) WHERE price_sanity_status IS NULL` (about 500 MB, 0 scans) serves only `bar_auditor`'s scan. The batch pass replaces that scan, so the index can be dropped (plain `DROP INDEX`, no decompression).
   - The bodies of todos 155, 347 and 052 were overwritten to a 5-line fold note in commit 73d4cda86; the originals (measurements, the 6-check list of 052) are recoverable with `git show 73d4cda86^:.planning/todos/pending/<file>`.
6. **Research snapshot and ledger (D0, D-07).** S0 (`src/intelligence/research/snapshot.py`) reads `open, close, volume` from `market_data_ohlcv_tradeable` (not high/low) and writes a content-hashed panel with a manifest (`source`, span, `oos_start`, dividends block with the dispute rule). `research_run` stores `snapshot_hash` and `evidence` jsonb; the S6 ledger is its sole writer (`tests/unit/research/test_ledger_sole_writer.py`). There is no data-quality field and no D2 rule version anywhere yet. Phase 183's session owns `src/intelligence/research/` until plan 10 and family 2 finish (STATE.md lanes), so the S0 manifest change (rule version, digests) and the D0 label hook are a coordination point: 185 ships pure functions and a read helper outside `research/`, and the two small call-site edits land through, or after, the 183 owner. [VERIFIED: code, STATE.md]
7. **No provenance or digest code exists.** Nothing named provenance batch, content digest or bar revision exists in `src/` or `services/`; `research/provenance.py` is git provenance for specs. 186-CONTEXT D-23/D-24 assign the bar content digest and the COPY + provenance primitive to phase 186 (`services/_batch_utils.py`). 185 writes derived bars before 186's rebuild, so 185 must define the bar-side digest record (design 3.3 accepts "a revision counter bumped by the ingest writer per (symbol, tf, range)" as the cheaper equivalent) and 186 consumes it. Do not put it in `_batch_utils.py` (ic_engine imports it). [VERIFIED: grep; 186-CONTEXT]
8. **ic_engine import boundary.** `services.ic_engine` loads 37 first-party modules; the ones this phase might touch are `services._batch_utils`, `src.core.bar_normalizer` and `src.core.market_calendar`. `src/providers/ibkr.py` and `price_sanity.py` are not imported. No ic_engine process is running and no corpus run is resumable today (the 2026-09-25 bundle "forces a full recompute, NOT yet run"), so the rule does not block now; it will once 186 starts a run or the rebuild (186 D-32a applies the same rule to rebuild-imported modules). New code goes in new modules; D2b reads session bounds through a new helper instead of editing `market_calendar.py`. [VERIFIED: import probe, process list, memory]
9. **ADJUSTED_LAST pairing.** `fetch_adjusted_daily_closes` requests back from now (`endDateTime=""`, which ADJUSTED_LAST requires) and IBKR "re-bases this series on every new dividend, so it is only meaningful next to TRADES closes fetched in the same run" (docstring). D1 therefore needs a fetch-run id shared by the TRADES and ADJUSTED_LAST requests of one pairing, not only a per-request id; D5's `join_adjustment_pairs` raises on any day present in one series and not the other, so pairs must come from the same run. [VERIFIED: code]
10. **`forward_return_writer` flags.** `return_{fast,mid,slow,extended}_suspect` = |return| over `alpha.quant.max_abs_return.{tf}` (1d 0.50, 1h 0.40, 15m 0.30, 5m 0.25) scaled by sqrt(lookahead); corroboration clears suspects when at least `min_symbols` distinct symbols are suspect within `window_minutes` (60) of the same bar; `has_gap_before_entry` = next traded bar more than `alpha.forward_returns.gap_multiplier` (3) bar lengths later and less than `gap_max_seconds` (14,400) later. Live counts: 1d 32 suspect, 0 gap (the gap flag cannot fire at 1d: 3 x 86,400 s exceeds 14,400 s); 1h 44/0; 15m 105/367; 5m 129/3,001. As bar flags they become: a return-magnitude rule (already covered by the vol-scaled jump rule, keep the fixed ceiling as a floor), a corroboration modifier (with the D-11 ceiling), and an intraday "gap before next traded bar" flag (informational, not quarantine). [VERIFIED: code, DB]
11. **D2b derived grid.** 5m bars are stamped at bar start, RTH only, 09:30-15:55 ET (78 bars; 42 on the 2025-11-28 half day). Stored 1h for AAPL sits at 09:30 (partial) then 10:00, 11:00, ... 15:00. D-15's session-anchored 1h edges are 09:30, 10:30, ..., 15:30 (the last one a half-hour bar; 12:30-13:00 on half days). So every name's 1h timestamps change, and because the primary key is (timestamp, symbol, timeframe) the stored :00 rows would stay visible beside derived :30 rows unless removed from the table. Stored 15m already sits on the derived edges and equals aggregated 5m exactly (todo 446), so 15m is mostly a no-op write. [VERIFIED: DB]
    - Measured 2024, six names: 1d open equals the first 5m open on every day and 1d volume equals the RTH 5m volume sum on every day; 1d high/low match the 5m max/min on all but a handful of days. This gives D2b a free exact cross-check (sum of derived 1h volume = 1d volume). [VERIFIED: DB]
    - Names with 15m/1h but no 5m exist now (14 expansion names, being backfilled at `1h,15m` by the running lanes). Todo 449 (filed after those lanes started) says only 5m should be fetched for the 698 names. Derivation from 5m leaves those stored 15m/1h rows as raw observations with no derived replacement until their 5m exists.
    - `pandas_market_calendars` 5.4.0 is installed and `MarketCalendar._build_daily_sessions` already yields per-date `(market_open_utc, market_close_utc)` including early closes and both DST transitions; expose it through a new function rather than editing the module.
    - Existing 15m/1h `price_sanity_status` flags do not carry over to derived bars; derived bars take the union of their constituent 5m flags.
12. **Cross-phase conflict on intraday D3.** 186-CONTEXT D-32 (commit 3fe092479, after 185's CONTEXT): "'Backfill complete' ... includes phase 185 D3's venue-move recovery of intraday history, which supersedes 185 D-19's 'the rebuild does not wait on D3'". 185-CONTEXT D-19 still says the opposite. The planner cannot resolve this alone; it decides whether intraday D3 (verify-only extension to 5m, the study covering intraday, 5m venue recovery for moved names) sits on 186's critical path in this phase. [VERIFIED: both CONTEXT files]
13. **Survivorship literature seeds.** Shumway and Warther (1999): a -55% corrected return for missing performance-related Nasdaq delisting returns; 1.2% of NYSE/AMEX and 5.6% of Nasdaq stocks delisted for poor performance per year [CITED: Shumway 1999, J. Finance]. The -30% NYSE/AMEX figure attributed to Shumway (1997) is `[ASSUMED]` (the paper exists; the number was not confirmed in this session). The spec's "roughly 1-2% a year in small caps" haircut is `[ASSUMED]`. All seed as `[conventional]` APR values.
14. **Seam candidates.** MRNA 2026-08-18 close 62.96, 2026-08-19 open 116.05 close 174.38 on 126.6M shares (about 50x normal); ALMS 2026-08-31 21.81 to 9.47 on 22.6M shares (about 30x). Volume did not scale by the price ratio, so both look like news events rather than splits; the fresh-fetch comparison decides. Using log-return thresholds, 441 daily closes move more than ln(1.5) and 2,668 more than ln(1.25) in the tradeable view (the spec's 253 and 1,901 used a different definition; the pass should record its own). [VERIFIED: DB]
15. **D7 facts.** (a) The close rule as written would alarm on about 85% of sessions (2024: 199-236 of 252 per name; median 0.75-2.2 bp, max 23 bp) because IBKR's daily close is the closing auction and the last 5m TRADES bar is not; opens and volumes match exactly. Use exact checks for open and volume and an APR tolerance for close. (b) Grafana has no Postgres datasource (Prometheus, Loki, Tempo only); the one `rawSql` panel in `operations.json` has nothing to query. D7 reaches Grafana through OTel metrics (Prometheus) plus `job_completed_total`; `integrity_monitor` rows are the detailed record. (c) `integrity_monitor` has a helper (`src/core/integrity_monitor.py`, `emit_integrity_fact_sync/async`, never raises). [VERIFIED: DB, provisioning files, code]

## Architectural Responsibility Map

The standard web tiers do not apply; this maps capabilities to the project's rings and pipeline stages.

| Capability | Primary tier | Secondary tier | Rationale |
|------------|-------------|----------------|-----------|
| IBKR requests, per-request outcome capture | `src/providers/ibkr.py` (Ring 1 provider, sole ib_async user) | caller callback | CLAUDE.md: all ib_async in ibkr.py; provider stays DB-ignorant (callbacks) |
| Append raw answers (D1) | Ring 2 writer (`services/` job, `ohlcv_observation_writer` role) | Postgres triggers (append-only) | Persistence separate from compute and transport |
| Scrub rules, seam detection, session aggregation, derivation rule, D0 labels | Ring 1 pure modules (`src/intelligence/bars/`) | - | Pure functions over arrays; testable without a DB |
| Canonical 1d, derived 15m/1h writes, flags, digests | Ring 2 batch job (`bar_derivation`, `ohlcv_derivation_writer` role) | TimescaleDB native DML | One writer per table (design `single_writer`) |
| Quarantine visibility | Database view `market_data_ohlcv_tradeable` | `bar_quality_flag` table | The view is already the one read boundary (CI) |
| Corporate actions, listing venue | Ring 2 writers into new point-in-time tables | Ring 1 inference functions | Same split |
| D7 audit | Ring 2 oneshot chained in the nightly unit | `integrity_monitor`, OTel metrics to Prometheus/Grafana | Existing observability surfaces |
| D0 labels on attempts | Ring 1 pure function | S0 manifest + S6 ledger (phase 183 owner) | Ledger is sole writer of `research_run` |

## Standard stack

### Core (all already installed; no new packages)
| Library | Version | Purpose | Why standard here |
|---------|---------|---------|--------------|
| TimescaleDB | 2.27.1 | Hypertable, native DML on compressed chunks | Live DB [VERIFIED] |
| PostgreSQL | 18.4 | Tables, triggers, roles, views | Live DB [VERIFIED] |
| ib_async | 2.1.0 | IBKR historical data (`reqHistoricalDataAsync`, returns `BarDataList` with `.reqId`) | Only in `ibkr.py` [VERIFIED: venv] |
| asyncpg | 0.31.0 | Reads, `copy_records_to_table` for COPY | Project standard [VERIFIED] |
| psycopg | 3.3.4 | Sync batch writers (`cursor.copy`) | Used by the backfill pipeline [VERIFIED] |
| numpy / pandas | 2.4.2 / 3.0.1 | Vectorized rules and aggregation | [VERIFIED] |
| pandas_market_calendars | 5.4.0 | NYSE sessions, early closes, DST | Already behind `src/core/market_calendar.py` [VERIFIED] |
| structlog + OTel metrics | project | Logging (`setup_service_logging`), `job_completed_total`, gauges | CLAUDE.md mandates [VERIFIED] |

### Supporting (project modules to reuse)
| Module | Purpose | When to use |
|--------|---------|-------------|
| `src/intelligence/statistics/price_sanity.py` | `classify_candidate_bar` as one D2a rule | Import; do not change behavior in place |
| `services/dividend_event_writer.py` | `join_adjustment_pairs`, `derive_ibkr_events`, `reconcile`, `vanished_ex_dates` | D5 I/O swap only |
| `src/intelligence/research/dividends.py` | `DisputeRule`, `ibkr_rounding_bound` | D5 (read-only import; 183-owned file) |
| `src/core/integrity_monitor.py` | `emit_integrity_fact_*` | D2a pass facts, D7 |
| `scripts/infrastructure/backfill/_empty_history.py` | `ohlcv_empty_history`, `ohlcv_provider_head` I/O | D4 re-derivation from D1 |
| `services/_batch_utils.py` `load_apr_dict_async`, `cfg` | APR loading | Read only; do not edit (ic_engine import) |

### Alternatives considered
| Instead of | Could use | Tradeoff |
|------------|-----------|----------|
| `bar_quality_flag` side table + view anti-join | Mirror quarantine into `price_sanity_status` via UPDATE | UPDATE on compressed chunks is the documented slow path, and it makes the flag job a second 1d writer; use only if a measured view read regresses |
| Separate `ohlcv_request` log + `ohlcv_observation` | One table with nullable OHLCV for "no data" rows | "No data" answers (D4) and failed requests have no bar date; a request log keeps the observation table dense and typed |
| Plain Postgres table for D1 | Compressed hypertable on bar date | 12-18M rows (about 2-3 GB) does not need compression; plain table keeps append-only triggers simple. Revisit at about 50M rows (nightly overlap adds about 9M a year, see sizing) |
| Latest-fetch-wins derivation after a split (re-fetch full history) | Apply split factors to old observations | IBKR TRADES history is split-adjusted at fetch time, so a full re-fetch gives one scale with no factor arithmetic; factors stay in `corporate_action` as the record |

**Installation:** none. No new external packages.

## Package legitimacy audit

No external packages are installed in this phase; every library above is already in `.venv` (versions verified by import). slopcheck is present at `/home/bg/.local/bin/slopcheck` but has nothing to check.

| Package | Registry | Disposition |
|---------|----------|-------------|
| (none new) | - | - |

**Packages removed due to slopcheck [SLOP] verdict:** none. **Packages flagged [SUS]:** none.

## Architecture patterns

### System architecture diagram

```
                IBKR gateway (127.0.0.1:7497)
                          |
     ibkr.py: SMART walk, venue walks, ADJUSTED_LAST back-from-now
                          |  on_request(RequestRecord)  on_bars(route, what_to_show, bars)
                          v
   [D1 writer role] ohlcv_request (every request: outcome bars | no_data | failed | timeout)
                    ohlcv_observation (every bar answered, every route, append-only)
                          |
            +-------------+-----------------------------+------------------------+
            |                                           |                        |
   D5 overlap / pairing                         D2 derivation (rule vN)      D4 empty history
   splits -> corporate_action                   choose route per bar         from request outcomes
   ADJUSTED_LAST/TRADES -> dividend_events      (SMART; venue if study      -> ohlcv_empty_history
                                                 passed; one scale)
                                                        |
                                              D2a scrub rules (pure)
                                                        |
               [derivation role] market_data_ohlcv (1d canonical; 15m/1h from 5m = D2b)
                                 bar_derivation (rule_version, observation ids per bar)
                                 bar_quality_flag (rule, fields, severity, quarantine)
                                 bar_content_digest (symbol, tf, range -> digest, rule_version)
                                                        |
                     market_data_ohlcv_tradeable (volume > 0, venue volume NULL, NOT EXISTS quarantine flag)
                                                        |
            +-------------------------+-----------------+----------------------+
            |                         |                                        |
     S0 snapshot (records rule    feature rebuild (186, reads digests)     D7 audit (nightly)
     version, digests; D0 labels)                                          -> integrity_monitor, OTel
            |
     S6 ledger research_run.evidence.data_quality
```

### Recommended project structure (new files only)
```
src/intelligence/bars/            # Ring 1, pure, no DB
    derivation.py                 # rule vN: choose observation per (symbol, date); RULE_VERSION
    scrub_rules.py                # OHLC invariants, non-positive, vol-scaled jump, stale, volume outlier,
                                  #   corroboration with ceiling, gap-before (intraday), view disagreement
    seams.py                      # constant-ratio seam / split detection over two close series
    session_grid.py               # 5m -> 15m/1h on session edges (calendar injected)
    digest.py                     # content digest of canonical rows per (symbol, tf, range)
    venue_study.py                # D3 study statistics (volume share, close match)
    labels.py                     # D0 labels (venue truncation, dividends, survivorship, scrub share)
    corporate_actions.py          # split inference, disputed-date rule (D-23)
services/
    ohlcv_observation_writer.py   # D1 writer (COPY), used by the backfill and study/audit jobs
    bar_derivation.py             # D2/D2a/D2b batch job (historical pass + nightly)
    bar_reconciliation_audit.py   # D7 oneshot
scripts/ops/bars/                 # one-off jobs: venue study, seam audit, D1 bootstrap, legacy import
production/migrations/380_*.sql   # onward
tests/unit/bars/                  # pure-function tests + known-answer fixtures
tests/fixtures/bars/              # dry-run report, 15 confirmed rows, split/event cases (CSV)
```
Naming: concept `bar_derivation` gives `BarDerivation`, `indicagent-bar-derivation.service`, `logs/bar_derivation.log`. Check `docs/foundation/glossary.md` before naming; "observation", "canonical bar", "scrub flag", "quarantine", "corporate action", "listing venue", "bar content digest" are not defined there yet and need entries. `docs/foundation/canonical-truth-registry.md` lists `BarWriter` as canonical writer of higher-timeframe bars; update it.

### Pattern 1: Provider stays DB-ignorant, emits request records
**What:** `fetch_historical_bars` gains an optional `on_request: Callable[[RequestRecord], None]` (symbol, tf, route, what_to_show, window, reqId, outcome, error code/text, n_bars, fetched_at, fetch_run_id) and delivers venue bars to an `on_observation` callback even when `store_bars` is false. `store_bars` keeps governing only whether venue bars reach `market_data_ohlcv` (until D2 owns that choice). Mirrors the existing `on_chunk` and `on_empty_history` callbacks (DAG invariant 3).
**When:** every IBKR history request in this phase.

### Pattern 2: Flag table plus view anti-join (quarantine)
**What:** `bar_quality_flag(symbol, timeframe, timestamp, rule, rule_version, fields text[], severity, quarantine bool, detail jsonb, flagged_at, batch_id)`, PK (symbol, timeframe, timestamp, rule). The view adds `AND NOT EXISTS (SELECT 1 FROM bar_quality_flag q WHERE q.quarantine AND q.symbol = m.symbol AND q.timeframe = m.timeframe AND q.timestamp = m.timestamp)`. Keep the existing `confirmed_corrupt` predicate until those 67 rows are migrated into the flag table.
**Check:** `EXPLAIN ANALYZE` of the S0 read, a full-corpus `backfill_feature_factory` chunk read and `detect_gaps` before and after the migration (performance SOP).

### Pattern 3: Append-only tables by trigger
**What:** the SCH pattern (migrations 367/368) and `research_run` triggers (`fn_research_run_no_delete`): BEFORE UPDATE OR DELETE and BEFORE TRUNCATE triggers that raise. Apply to `ohlcv_request`, `ohlcv_observation`, `corporate_action` (corrections are new rows with a supersedes pointer), `listing_venue` (close `valid_to` + insert, same-UTC-day rule as SCH).

### Pattern 4: Roles via SET ROLE (D-05)
**What:** only the `postgres` superuser exists and every service connects with it. Create NOLOGIN roles `ohlcv_observation_writer` (INSERT on `ohlcv_request`, `ohlcv_observation`; no UPDATE/DELETE) and `bar_derivation_writer` (SELECT on D1; INSERT/UPDATE on `market_data_ohlcv`, `bar_derivation`, `bar_quality_flag`, `bar_content_digest`), and have each writer `SET ROLE` at connection start. No new credentials or `.env` entries; the database refuses a cross-writer insert. Phase 187 generalizes this from the DAG manifest.

### Pattern 5: Session-anchored aggregation (D2b)
```python
# Source: session bounds from pandas_market_calendars via src/core/market_calendar.py (_build_daily_sessions)
def aggregate_session(ts_utc, o, h, l, c, v, session_open_utc, session_close_utc, minutes):
    """5m bars stamped at bar start inside [open, close) -> bars on edges open + k*minutes.
    Pure. Buckets never cross close; the last bucket may be short (15:30-16:00, 12:30-13:00)."""
    k = (ts_utc - session_open_utc) // np.timedelta64(minutes, "m")
    # first open, max high, min low, last close, sum volume per k; stamp = open + k*minutes
```
Aggregate from tradeable 5m only (quarantine excluded); a bucket with no traded 5m bar produces no row.

### Anti-patterns to avoid
- **Per-row provenance columns on `market_data_ohlcv`:** forbidden by design 12.1; side tables instead.
- **Row-level UPDATEs over many 1d rows on compressed chunks:** use the flag table; if canonical values must change, upsert whole (symbol, tf) segments (3.9 s per 4.8k-row segment measured) or plain INSERT for rows that do not exist.
- **Editing `bar_normalizer.py`, `market_calendar.py`, `_batch_utils.py`:** ic_engine imports them; new modules instead.
- **Logging structured data through stdlib `extra=`:** it is dropped in this setup; persist inventory to tables, log through structlog.
- **Letting the flag pass be a second 1d writer:** before D2 exists, the pass writes only `bar_quality_flag`, never `market_data_ohlcv`.
- **Deleting the stored 15m/1h rows without archiving:** copy them into a raw archive table first and verify counts and a checksum.

## Don't hand-roll

| Problem | Don't build | Use instead | Why |
|---------|-------------|-------------|-----|
| NYSE session bounds, half days, DST | Hand-typed 09:30/16:00 and a holiday list | `pandas_market_calendars` via `MarketCalendar` sessions | Early closes and both DST transitions are already right there |
| Dividend derivation from ADJUSTED_LAST | New ratio logic | `derive_ibkr_events`, `join_adjustment_pairs`, `reconcile` | Tested, lockstep rule measured on NVR/AXON |
| Corrupt-print classification | A second magnitude check | `classify_candidate_bar` | CLAUDE.md and its own docstring: two implementations drift |
| integrity facts | Raw INSERT into `integrity_monitor` | `emit_integrity_fact_sync/async` | One ON CONFLICT shape, never raises |
| Bulk loads | Row-at-a-time or multi-row VALUES | `COPY` (psycopg `cursor.copy`, asyncpg `copy_records_to_table`) | Design 14.5 audit finding |
| Empty-history bookkeeping | New table | `ohlcv_empty_history` + `_empty_history.py`, fed from `ohlcv_request` outcomes | Nightly already honors it |

**Key insight:** most defects here are silent (a seam, a truncated head, a stub print), so the value is in recording every answer and every rule decision, not in clever rules.

## Runtime state inventory

This phase migrates the 1d write path and the 15m/1h grid, so runtime state matters.

| Category | Items found | Action required |
|----------|-------------|------------------|
| Stored data | 1d: 3.87M `ibkr_named` + 1.65M `synthetic_fill` rows; 15m 148.7M rows (27.4M real), 1h 38.8M (7.4M real) on 243/247 names; 67 non-null `price_sanity_status` rows across tfs; `ohlcv_empty_history` 84 (1d) / 88 / 89 / 88 rows; `ohlcv_provider_head` 612 rows; `dividend_events` 73,940 Yahoo + 44,745 IBKR rows | Legacy-import 1d rows into D1 as observations (tagged import, no request); archive stored 15m/1h real rows before replacement; migrate the 67 status rows into `bar_quality_flag` |
| Live service config | APR keys `infra.ibkr.venue_fallback.*`, `infra.ibkr.rate_limit_max_requests_by_tf` = `{"1d": 200}`, `alpha.quant.price_sanity.*`, `alpha.quant.cross_symbol_corroboration.*`, `alpha.quant.max_abs_return.*`, `alpha.forward_returns.gap_*`, `threshold.dividend_event.*` | New keys by migration; `store_bars` stays false until the study passes |
| OS-registered state | `indicagent-nightly-backfill.timer` (05:00 UTC, enabled; skips if any backfill runs), `indicagent-dividend-event-writer-yahoo.timer` (06:30 UTC); dormant `indicagent-bar-writer`, `indicagent-bar-auditor` units | Chain D7 inside the nightly unit; fence `bar_writer` to 1m/5m or document it dormant with a test; nightly default timeframes drop 15m/1h once D2b lands |
| Secrets/env vars | None change (SET ROLE, no new logins); IBKR client IDs in use: 35 provider, 40-43 running lanes, 45 nightly and dividend writer (collide; auto-rotate on 326) | Give 185 jobs fixed IDs 46-49 (all at most `_MAX_CLIENT_ID` 50) |
| Build artifacts | None | - |

## Common pitfalls

### Pitfall 1: The re-run happens before the inventory sink exists
**What goes wrong:** tonight's (or any) nightly re-asks the deleted 1d heads; venue answers are logged without fields and lost.
**How to avoid:** land the D1 capture (or at minimum a structlog event with symbol, venue, first, last, n_bars) before any 1d head re-run; accept that a nightly run before then re-verifies empty history correctly but loses the inventory, which a re-run can rebuild at about 5 requests per late name.
**Warning signs:** `ohlcv_empty_history` 1d rows appearing with no matching D1 request rows.

### Pitfall 2: Two 1h grids visible at once
**What goes wrong:** derived 1h rows at :30 are inserted beside stored rows at :00; S0 builds slots from data and sees both.
**How to avoid:** archive, then delete the stored 1h rows per (symbol, '1h') segment, then insert derived rows, per symbol in one transaction; the backfill stops writing 15m/1h to `market_data_ohlcv` in the same change. Test: no symbol has 1h rows at both :00 and :30 on one session.

### Pitfall 3: Writers you forgot
**What goes wrong:** `backfill_feature_factory --fetch-only`, `bar_writer` (`live_htf`), `run_normalize` or the running expansion lanes write 1d/15m/1h after the switch.
**How to avoid:** a CI source-grep test (the `test_market_data_ohlcv_boundary.py` pattern) listing every `INSERT INTO market_data_ohlcv` site with the timeframes it may write, plus the database role grants; a nightly D7 check that counts rows with sources other than the derivation's in 1d/15m/1h.

### Pitfall 4: ADJUSTED_LAST paired across runs
**What goes wrong:** ratio steps appear on days a dividend was re-based between fetches.
**How to avoid:** `fetch_run_id` on every request; D5 pairs only within a run.

### Pitfall 5: Quarantining real returns
**What goes wrong:** a vol-scaled jump rule quarantines MRNA-type news days.
**How to avoid:** D-10 known answers include hand-checked real moves; jump flags without a corroborating defect (non-positive, OHLC violation, stub price, seam) are informational, not quarantine, until validated.

### Pitfall 6: IBKR pacing contention
**What goes wrong:** four running lanes each keep their own per-process limiter (58 per 10 min default), so the account-level soft pacing is already hit (`ibkr.hist_pacing_error` in the lane logs); 185's fetch jobs make it worse, and todo 449's 698-name 5m backfill will run for days.
**How to avoid:** run 185's IBKR jobs when no lanes run, or measure a pilot first; never alongside the nightly.

### Pitfall 7: Nightly silently skipped for days
**What goes wrong:** `_is_another_backfill_running` skips the nightly while any long backfill runs; 1d freshness, D5 and D7 stall with no alarm.
**How to avoid:** D7 records "nightly skipped" as a failed fact; raise it through `job_completed_total{status}`.

### Pitfall 8: The D7 close rule
**What goes wrong:** exact close equality alarms on about 85% of sessions.
**How to avoid:** exact for open and volume; close within an APR tolerance (seed from the measured 2024 distribution, p99 about 15 bp, as `[rca_analysis]`).

## Code examples

### Corroboration with a clearing ceiling (D-11)
```python
# New module; wraps price_sanity's verdicts, leaves apply_cross_symbol_downgrade untouched.
def corroborated_verdict(verdict: CandidateVerdict, n_corroborating: int, *,
                         min_symbols: int, max_clearable_ratio: float) -> CandidateVerdict:
    """Corroboration clears a CONFIRMED_CORRUPT bar only when its worst field is within
    max_clearable_ratio of the reference. Seeded below the magnitude threshold (2.5, the inverse
    of the 60% break rule of 2010-05-06), so no 10x print is ever cleared."""
    if verdict.verdict != "CONFIRMED_CORRUPT" or verdict.max_ratio > max_clearable_ratio:
        return verdict
    return apply_cross_symbol_downgrade(verdict, n_corroborating, min_symbols)
```
Known answer: all 27 MARKET_EVENT rows of the 2026-09-26 dry run come back CONFIRMED_CORRUPT.

### Seam detection (D-24, D-21)
```python
def find_seams(days, stored_close, fresh_close, *, rel_tol, min_run):
    """Pure. ratio = stored / fresh per common day. A seam is a maximal run of at least min_run
    days whose ratio is constant within rel_tol and differs from 1 by more than rel_tol; the run's
    end is the corporate-action date and the ratio its factor (2.0 = 2-for-1, 0.125 = 1-for-8)."""
```
Known answers (real splits, dates `[ASSUMED]` from training knowledge, confirm against IBKR data before use as fixtures): NVDA 2024-06-10 10:1, AAPL 2020-08-31 4:1, TSLA 2020-08-31 5:1 and 2022-08-25 3:1, AMZN 2022-06-06 20:1, GOOGL 2022-07-18 20:1, GE 2021-08-02 1:8, USO 2020-04-29 1:8, C 2011-05-09 1:10. Because stored bars fetched after a split are already on one scale, these are fixtures for the detector (synthetic series built from them), and the live audit finds only splits crossed by incremental nightly fetches.

### Survivorship bound seeds (D0, APR, `[conventional]`)
```
alpha.survivorship.delisting_return.nasdaq        = -0.55   # Shumway and Warther 1999 [CITED]
alpha.survivorship.delisting_return.nyse_amex     = -0.30   # Shumway 1997 [ASSUMED]
alpha.survivorship.hazard.nasdaq_annual           = 0.056   # performance delistings per year [CITED]
alpha.survivorship.hazard.nyse_amex_annual        = 0.012   # [CITED]
alpha.survivorship.haircut.small_cap_annual       = 0.015   # spec "1-2% a year" [ASSUMED]
```
Sensitivity per daily cross-sectional book (design 12.2): apply the delisting return to held names at the hazard, report the statistic's change beside it.

## State of the art (in this repo)

| Old approach | Current approach | When changed | Impact |
|--------------|------------------|--------------|--------|
| SMART "no data" twice = verified empty | Every route must answer "no data" (verify-only) | 2026-09-26 (0d225b312) | 1d empty rows deleted and re-verified; intraday rows still the old kind |
| Price sanity by streaming `bar_auditor` | Batch rule inside the derivation | This phase | Todo 155's 4.1-year estimate becomes minutes |
| `forward_returns` suspect/gap flags | Bar flags | This phase, before 186 deletes the writer | Every reader sees them |
| Stored IBKR 15m/1h | Derived from 5m on session edges | This phase (UD-25) | 1h timestamps move to :30 for every name |

**Deprecated/outdated:** `services/bar_auditor.py` price-sanity task (disabled); the partial index of todo 347; `backfill_feature_factory --fetch-only` as a bar writer.

## Recommended plan decomposition

The phase is too large for one plan set of normal size (eight stages, three IBKR fetch campaigns, a table migration touching every 1h row, and two cross-phase dependencies). Recommend two plan sets in this phase directory, the first shaped to clear D-28 and unblock 186. If the planner prefers phase splitting, set A stays 185 and set B becomes 185.1 (add by hand, not `phase.add`).

### Set A: minimum data bar, D2b, D1 capture

| Wave | Plan | Content | IBKR | Satisfies |
|------|------|---------|------|-----------|
| 0 | 185-01 | Preserve known answers: copy `corrupt_1d.txt` into `tests/fixtures/bars/`, snapshot the 67 flagged rows and the MRNA/ALMS windows to CSV; restore todo 155/347/052 bodies from `73d4cda86^`; create `tests/unit/bars/` scaffolding; measure (on a scratch hypertable with the same compression settings) plain INSERT vs upsert vs segment delete cost | no | D-10 prereq |
| 1 | 185-02 | D1 schema + capture: migration (`ohlcv_request`, `ohlcv_observation`, append-only triggers, two NOLOGIN roles and grants); `ibkr.py` `on_request`/`on_observation` callbacks with `fetch_run_id`; `services/ohlcv_observation_writer.py` (COPY, `SET ROLE`); backfill passes every 1d answer (SMART and venues, bars and no-data) to D1; structlog event for venue recovery | no (unit tests with fakes) | D-05, D-16 capture, D-20 evidence |
| 1 | 185-03 | D2a rules and historical pass: `scrub_rules.py` (invariants, non-positive, vol-scaled jump, stale, volume outlier, corroboration ceiling, fixed-ceiling magnitude, intraday gap-before); known-answer tests must pass first; `bar_quality_flag` migration with view anti-join (EXPLAIN before/after), migrate the 67 status rows, drop the todo 347 index; batch pass over all 1d tradeable history writing flags + `integrity_monitor` facts; APR keys `threshold.bar_scrub.*` | no | D-08..D-13, D-14 (rule ports) |
| 1 | 185-04 | D2b grid: `session_grid.py` + calendar helper; tests (equals direct 5m computation, never spans a session, half day 2025-11-28, DST 2025-03-10 and 2025-11-03, sum of 1h volume = 1d volume, first open = 1d open); archive table for stored 15m/1h; `bar_derivation` 15m/1h writer per (symbol, tf) segment (archive, delete, insert, one transaction); derived bars inherit constituent 5m flags; stop 15m/1h writes in the backfill and nightly defaults; `bar_content_digest` table (the shared digest definition 186 D-23 consumes) | no | D-15, D-07 (digest) |
| 2 | 185-05 | 381-name 1d head re-run through the capture path (client ID 46, no lanes running); moved-name inventory = query over D1 (venue bars before the SMART head); empty-history re-verification counts | yes (about 2,000 requests, 2-3 h) | D-27(2), D-20 |
| 2 | 185-06 | D3 validation study: pre-registered thresholds written and committed before the fetch; at least 30 names across NYSE, Nasdaq, NYSE Arca with known primaries; SMART + five venues, 1d over 2 recent years and 5m over about 20 sessions; answers to D1; report pass or fail per criterion | yes (about 400 requests) | D-17 |
| 2 | 185-07 | D1 bootstrap + seam audit: legacy import of stored 1d rows into D1; fresh 20-year TRADES and ADJUSTED_LAST for all 931 names in one run (paired by `fetch_run_id`); `seams.py`; `corporate_action` table (append-only); MRNA and ALMS first, then all; seam report | yes (about 1,900 requests, 1.5-2 h) | D-24, D-21 table, D-22 input |
| 2 | 185-08 | D0 labels: `labels.py` (pure) + read helper (venue truncation from D1 inventory, dividend coverage share, scrub share, survivorship bound and delisting sensitivity), APR seeds; a `data_bar_check` script that asserts every D-28 condition and prints pass/fail; hand-off patch for S0 manifest and runner evidence, coordinated with the 183 owner | no | D-04, D-28 |

Set A clears the minimum data bar when 185-03, 185-05, 185-07 and 185-08 are done (plus the existing todo 428 opt-in). 185-04 is the 186 precondition.

### Set B: derivation takes over, audits

| Wave | Plan | Content | Satisfies |
|------|------|---------|-----------|
| 3 | 185-09 | D2 1d derivation rule v1 (SMART TRADES latest fetch; venue observation before the SMART head only if the study passed; `bar_derivation` side table; digests); backfill 1d path writes D1 only, 1d `detect_gaps` reads D1; fence `backfill_feature_factory --fetch-only` and `bar_writer` 1d; CI single-writer test for 1d/15m/1h; historical run writes only rows whose values differ | D-06, D-07 |
| 3 | 185-10 | D3 rebase and D4: moved names re-derived with venue bars if the study passed (`store_bars` retired as the switch, replaced by the derivation's rule); `ohlcv_empty_history` derived from `ohlcv_request` outcomes; verify-only extended to 5m (and the study's intraday verdict applied) | D-16..D-20 |
| 4 | 185-11 | D5: nightly overlap fetch (APR `infra.bar_derivation.overlap_sessions`), split inference to `corporate_action`, re-fetch and re-derive on detection; `dividend_event_writer --sources ibkr` reads D1; disputed-date record (D-23); JPM/KO/XLU validation | D-21..D-23 |
| 5 | 185-12 | D7 oneshot chained in the nightly unit: route disagreements, TRADES vs ADJUSTED_LAST outside explained factors, daily vs aggregated intraday (open/volume exact, close tolerance), unexplained seams, late heads, unconfirmed empty rows, dividend freshness, nightly-skipped; `integrity_monitor` facts + OTel gauges + a Prometheus panel | D-26 |
| 5 | 185-13 | D6 `listing_venue` from D1 venue spans; docs (glossary, canonical-truth registry, onboarding SOP second gap, operations) | D-25 |

Intraday venue recovery (5m for moved names) is placed by the owner's answer to Open Question 1: after 185-10 in set B if 186 waits on it, otherwise deferred to after 186's rebuild per D-19.

### Sizing (from measured unit costs)

| Job | Basis | Estimate |
|-----|-------|----------|
| D2a historical pass (1d) | 3.86M tradeable rows; a full 1d GROUP BY scan took 1.2 s; rules vectorized | Minutes; flag writes to an uncompressed table are seconds |
| 381-name re-run | 1 SMART + up to 4 venue requests each at 200 per 600 s, plus 65/130 s backoffs on ambiguous failures | About 2-3 h `[ASSUMED]` from rate math |
| D1 bootstrap | 931 x (TRADES + ADJUSTED_LAST) = 1,862 requests | About 95 min at the 1d limit; 20-year window is one request per series (spec measurement) |
| D3 study | 30-40 names x 6 routes x (1d + 5m) | 20-40 min |
| D2b 1h rewrite, 233 names | about 8M derived 1h rows; segment-level delete + insert | Measure in 185-01; upsert rate (0.8 ms/row) would give about 2 h, plain insert far less `[ASSUMED]` |
| D2b for the 698 names after todo 449 | about 25M 1h + 90M 15m rows, no existing rows to replace | Plain COPY; measure; upsert rate would be too slow (about 25 h) |
| Nightly D5 overlap | 931 x 2 requests | About 95 min added to the nightly; D1 grows about 9M rows a year at a 20-session overlap |

## Assumptions log

| # | Claim | Section | Risk if wrong |
|---|-------|---------|---------------|
| A1 | Shumway (1997) NYSE/AMEX delisting return about -30% | Code examples | Wrong seed for the sensitivity; `[conventional]` APR value is easy to correct |
| A2 | Small-cap survivorship haircut 1-2% a year | Code examples | Bound mis-sized; disclosed as a seed |
| A3 | Split dates listed for fixtures | Code examples | Fixture mismatch; confirm against IBKR data before use |
| A4 | Adding a nullable column to a compressed hypertable is metadata-only in 2.27 | Finding 3 | Irrelevant if the side-table design is followed |
| A5 | Plain INSERT/COPY into compressed chunks lands in the uncompressed part without decompression (supported by 242 partial chunks, not measured for rate) | Sizing | D2b and D1 bootstrap slower than planned; 185-01 measures it |
| A6 | Re-run duration 2-3 h | Sizing | Scheduling only |
| A7 | Deleting whole (symbol, tf) segments from compressed chunks avoids full decompression | Pitfall 2 | 1h rewrite slower; measure in 185-01 on a scratch hypertable |

## Open questions

1. **Does 186's rebuild wait on 185's intraday venue recovery?**
   - Known: 185 D-19 says no; 186 D-32 (later) says yes and claims to supersede it.
   - Unclear: which the owner intends; it decides whether 5m venue recovery is in set B.
   - Recommendation: treat 186 D-32 as the later owner decision and plan intraday D3 in set B, but confirm and fix whichever CONTEXT is stale in the same change.
2. **Should the running `1h,15m` expansion lanes continue?**
   - Known: todo 449 (filed after they started) says only 5m is needed; D2b makes stored 15m/1h raw observations; the lanes block the nightly and add IBKR pacing pressure.
   - Recommendation: the session that owns them stops them after the current names and switches to 5m (todo 449); their rows go to the 15m/1h archive in 185-04.
3. **D0 and S0 edits inside `src/intelligence/research/`.**
   - Known: the 183 owner holds that package until plan 10 and family 2 finish; family 2 waits on todo 447.
   - Recommendation: 185-08 ships the pure functions and a patch description; the S0 manifest (rule version, digests) and evidence hook land through the 183 owner or right after the lane is released. Daily attempts 3/3b/4 are gated on 185 anyway.
4. **Where the canonical-bar digest lives relative to 186 D-24.**
   - Recommendation: 185-04 defines `bar_content_digest` (schema and `digest.py`); 186's COPY primitive and provenance batch record reference it. Tell the 186 planner.
5. **Quarantine granularity.** Most 1d corrupt prints are high/low-only (sane open/close); S0 reads only open/close. Whole-bar quarantine drops a valid return on about 45-60 bars out of 3.86M. Recommendation: quarantine whole bars in v1 (simple, measured cost negligible); record `fields` on each flag so a later rule version can narrow it.

## Environment availability

| Dependency | Required by | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| IBKR gateway (Docker `ib-gateway`) | 185-05/06/07, D5 nightly | yes (up 2 days) | - | none; schedule around the nightly restart window |
| TimescaleDB | all | yes | 2.27.1 / PG 18.4 | - |
| Prometheus + Grafana | D7 | yes (containers up) | - | Grafana has no Postgres datasource: use OTel metrics |
| Python venv | all | yes | 3.14.4 | - |
| Disk | archive tables, D1 | 496 GB free of 914 GB | - | D1 plus archives are single-digit GB |
| Free IBKR client IDs | fetch jobs | 46-49 free | - | - |

**Missing dependencies with no fallback:** none. **With fallback:** Grafana SQL panels (use Prometheus).

## Validation architecture

### Test framework
| Property | Value |
|----------|-------|
| Framework | pytest (asyncio-mode auto), `pytest.ini` at repo root |
| Config file | `pytest.ini` |
| Quick run command | `.venv/bin/pytest tests/unit/bars/ tests/unit/providers/test_ibkr_provider.py -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` (CI also runs ruff, black, vulture, mypy-baseline) |

### Phase requirements to test map
| Req | Behavior | Test type | Automated command | File exists? |
|-----|----------|-----------|-------------------|-------------|
| D-10/D-13 | 45 dry-run CONFIRMED_CORRUPT rows flagged; 1,864 edge bars not flagged; the 15 existing 1d rows flagged | unit, fixture | `pytest tests/unit/bars/test_scrub_known_answers.py -x` | Wave 0 |
| D-11 | All 27 MARKET_EVENT rows (26 on 2010-05-06, EWW 2006-11-07) stay CONFIRMED_CORRUPT | unit | `pytest tests/unit/bars/test_corroboration_ceiling.py -x` | Wave 0 |
| D-08 | Each rule on synthetic cases (OHLC violation, zero price, stale run, volume spike, jump with and without a corporate action) | unit | `pytest tests/unit/bars/test_scrub_rules.py -x` | Wave 0 |
| D-14 | Ported flags agree with `forward_return_writer` semantics on fixtures (ceiling, window corroboration, gap-before never fires at 1d) | unit | `pytest tests/unit/bars/test_flag_parity.py -x` | Wave 0 |
| D-15 | Derived = direct 5m computation; no bucket spans a session; half day and both DST days; 1h volume sum = 1d volume; first open = 1d open | unit + one DB integration sample | `pytest tests/unit/bars/test_session_grid.py -x` | Wave 0 |
| D-15 | No symbol carries 1h rows at both :00 and :30 in one session after the switch | integration (DB, read-only query) | `pytest tests/integration/test_derived_grid_live.py -x` | Wave 0 |
| D-05 | Append-only triggers refuse UPDATE/DELETE/TRUNCATE; roles refuse cross-writes | migration contract + integration | `pytest tests/unit/test_ohlcv_observation_migration_contract.py -x` | Wave 0 |
| D-16/D-20 | Provider emits a request record per request (SMART, each venue, no-data, failure); venue bars reach `on_observation` with `store_bars` false | unit (fake IB) | `pytest tests/unit/providers/test_ibkr_provider.py -k request_record -x` | extend existing |
| D-24/D-21 | Seam detector finds synthetic 2:1, 1:8, 20:1 seams at the right date; no seam on MRNA/ALMS-shaped event series | unit | `pytest tests/unit/bars/test_seams.py -x` | Wave 0 |
| D-22 | D5 reading D1 reproduces the interim writer's events on stored fixtures (JPM, KO, XLU, NVR 2004 derives nothing) | unit | `pytest tests/unit/services/test_dividend_event_writer.py -x` | extend existing |
| D-23 | Disputed-date record marks spanning returns unknown | unit | `pytest tests/unit/bars/test_corporate_actions.py -x` | Wave 0 |
| D-06 | Single writer: no `INSERT INTO market_data_ohlcv` site outside the allow-list may write 1d/15m/1h | CI grep | `pytest tests/unit/test_market_data_ohlcv_writer_boundary.py -x` | Wave 0 |
| D-07 | Digest is stable under row order and changes when any value or flag changes | unit | `pytest tests/unit/bars/test_digest.py -x` | Wave 0 |
| D-04 | Labels on a synthetic panel (known truncation share, dividend-coverage share, scrub share, survivorship numbers) | unit | `pytest tests/unit/bars/test_labels.py -x` | Wave 0 |
| D-26 | Each audit check on fixtures, including the close tolerance and the nightly-skipped fact | unit | `pytest tests/unit/services/test_bar_reconciliation_audit.py -x` | Wave 0 |
| D-17 | Study statistics on synthetic venue data (volume share, close match) | unit | `pytest tests/unit/bars/test_venue_study.py -x` | Wave 0 |

Existing CI guards that constrain new code: `test_market_data_ohlcv_boundary.py` (new raw-table reads need an allow-list entry with a reason; the derivation and D7 need raw access and should be listed), `test_compressed_hypertable_write_boundary.py` (currently scoped to `feature_vectors`/`feature_ic_scores`; extend to `market_data_ohlcv` UPDATEs), `test_compressed_hypertable_migration_vacuum_check.py` (any migration doing decompress + recompress needs a bare `VACUUM`), `test_todo_priorities_link_integrity.py` (every new todo needs a PRIORITIES.md row), `test_service_auditor_registry_integrity.py` (new units registered in `_DAG_ORDER`/`_AGENT_ID_TO_UNIT` must exist as non-archived unit files), `test_ledger_sole_writer.py` (only S6 writes `research_run`).

### Sampling rate
- **Per task commit:** the quick run command.
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q` plus the read-only integration checks for any migration applied.
- **Phase gate:** full unit suite green; `data_bar_check` passes for D-28; D2b live check passes before 186 is told the precondition holds.

### Wave 0 gaps
- [ ] `tests/fixtures/bars/` with the dry-run report, the 67 flagged rows, MRNA/ALMS windows, SPY 2025-11-28 and DST-day 5m samples
- [ ] `tests/unit/bars/` package and shared builders (synthetic bar series, fake calendar sessions)
- [ ] Scratch-hypertable measurement of insert/upsert/segment-delete rates (185-01)
- [ ] Framework install: none needed

## Security domain

| ASVS category | Applies | Standard control |
|---------------|---------|-----------------|
| V2 Authentication | no | No new logins (NOLOGIN roles via SET ROLE) |
| V3 Session management | no | - |
| V4 Access control | yes | Per-writer NOLOGIN roles with table grants (D-05) |
| V5 Input validation | yes | IBKR answers validated by scrub rules; flags, never silent drops |
| V6 Cryptography | no (hashing only) | `hashlib.sha256` for digests; no hand-rolled hashing |
| V8 Data protection | yes | Append-only triggers on D1, `corporate_action`, `listing_venue`; raw observations permanent |

| Pattern | STRIDE | Mitigation |
|---------|--------|-----------|
| SQL built from symbol text | Tampering | Parameterized queries only (asyncpg `$n`, psycopg `%s`) |
| A writer overwriting raw observations | Tampering / repudiation | Triggers refuse UPDATE/DELETE/TRUNCATE; role grants |
| Silent revision of past bars | Repudiation | Digest per (symbol, tf, range) and rule version recorded per snapshot |
| Disk exhaustion from decompression | Denial of service | No decompress-all; side tables; VACUUM rule; 185-01 measurement |

## Project constraints (from CLAUDE.md)

- APR mandate: every threshold, window, count, batch size and tolerance in new rules and jobs is an APR key seeded by migration (config_schema + config_state + config_history, provenance tag in the description); namespaces `threshold.*`, `infra.*`, `alpha.*`.
- Ring rule: `src/core/` and `src/observability/` stay free of domain vocabulary; new domain modules go under `src/intelligence/`; daemons and jobs under `services/` or `scripts/`.
- DAG invariants: compute never persists its own output (pure rules in Ring 1, one writer per table); all timestamps UTC via `datetime.now(UTC)`; topic keys through `stream_keys.py` if any topic is added.
- `market_data_ohlcv` reads for compute go through `market_data_ohlcv_tradeable`; raw reads need a boundary allow-list entry with a reason.
- Compressed hypertables: any decompress/recompress migration ends with a bare `VACUUM <table>;` (CI-enforced); follow `docs/foundation/performance-investigation-sop.md` before any multi-million-row write.
- ProcessPoolExecutor workers compute only; one serial DB writer in the main process; after killing a pool-based job, kill orphaned workers and terminate leftover backends.
- Never edit a module ic_engine imports while a corpus run is live or resumable (`services/_batch_utils.py`, `src/core/bar_normalizer.py`, `src/core/market_calendar.py` are in that set).
- Never log per row inside corpus loops; accumulate counts.
- Never materialize wide full-corpus DataFrames; build arrays from asyncpg rows.
- asyncpg: bare connections need `_setup_codecs` for jsonb; derive dtypes from `get_attributes()`, not data.
- `except X as error`; structlog, never an `event=` kwarg; logs to `logs/<snake_case>.log`.
- Services register in `_DAG_ORDER`/`_AGENT_ID_TO_UNIT` with an `alert.lag.*` APR key if they are daemons; oneshots emit `job_completed_total{job, status}` with `job` equal to the unit suffix.
- `src/providers/ibkr.py` is the only ib_async user; client IDs at most 50.
- Onboarding SOP: never hand-write `instruments`, never deactivate a dead name.
- Migrations applied live are committed in the same breath; `git add` renamed paths alone.
- Glossary: check before naming; glossary wins on collision.
- Done-coding SOP: `/simplify`, `/review`, `pytest tests/unit/ -q` green, feature branch, ff-only merge.
- Writing: no em dashes, sentence-case headings, no AI attribution in commits.

## Sources

### Primary (HIGH confidence)
- Live code: `src/providers/ibkr.py`, `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py`, `infrastructure_nightly_backfill.py`, `_empty_history.py`, `src/intelligence/statistics/price_sanity.py`, `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py`, `services/forward_return_writer.py`, `services/dividend_event_writer.py`, `services/bar_writer.py`, `services/backfill_feature_factory.py`, `services/_batch_utils.py`, `src/core/integrity_monitor.py`, `src/core/market_calendar.py`, `src/intelligence/research/snapshot.py`, `runner.py`, `ledger.py`, migrations 374-379, CI tests listed above
- Live DB (read-only): schema, hypertable/compression/chunk status, row counts, APR values, 1d-vs-5m agreement 2024, anti-join EXPLAIN ANALYZE
- `docs/plans/2026-09-26-daily-data-foundation.md`, `docs/plans/2026-09-26-unified-research-to-production-design.md` (3.3, 10.2, 12.1, 12.2, 14.5-14.7, 16), `docs/plans/2026-09-25-multi-timeframe-horizon-design.md` (D4), `.planning/phases/186-*/186-CONTEXT.md`, todos 433, 446, 449, and pre-truncation 155/347/052

### Secondary (MEDIUM confidence)
- [Shumway 1999, The delisting bias in CRSP's Nasdaq data](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00192) and [author PDF](https://tylergshumway.org/Shumway-DelistingBiasCRSPs-1999.pdf): -55% Nasdaq correction; 1.2% and 5.6% annual performance delisting rates
- [Shumway 1997, The delisting bias in CRSP data](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1997.tb03818.x)
- [SEC/CFTC findings regarding the market events of May 6, 2010](https://www.sec.gov/files/marketevents-report.pdf) and [SEC testimony](https://www.sec.gov/news/testimony/2010/ts051110mls.pdf): trades 60% away from the 2:40 p.m. reference were broken

### Tertiary (LOW confidence)
- Split dates for fixtures (training knowledge, `[ASSUMED]`)

## Metadata

**Confidence breakdown:**
- Current state (code, DB, writers, APR): HIGH, read directly
- Architecture (side tables, anti-join, roles): HIGH for feasibility (measured or documented), MEDIUM for write rates (A5, A7)
- Pitfalls: HIGH, each observed in code, logs or data
- Sizing: MEDIUM, extrapolated from measured unit costs

**Research date:** 2026-09-26
**Valid until:** 2026-10-10 (fast-moving: concurrent backfills, phase 186 planning, 183 lane release)
