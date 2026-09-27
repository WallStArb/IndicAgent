# Phase 185: Daily data foundation - Context

**Gathered:** 2026-09-26
**Status:** Ready for planning
**Source:** PRD express path (`docs/plans/2026-09-26-daily-data-foundation.md`, accepted 2026-09-26, revision 2, owner decisions 1-9)

<domain>
## Phase boundary

Every daily bar research reads traces to raw IBKR observations and a versioned derivation rule,
and no data defect reaches a verdict unmeasured. The phase is the project's price-integrity
layer: D0 labels, D1 raw observation store, D2 canonical derivation (D2a scrubbing, D2b derived
15m/1h grid), D3 venue-move recovery, D4 empty history as a derived fact, D5 corporate actions,
D6 listing-venue history, D7 reconciliation audits. D8 is descoped. IBKR is the only price
source.

Alpha work runs in parallel (ALPHA FIRST). The early stages that clear the minimum data bar for
daily attempts 3, 3b and 4 come first because research waits on them.

</domain>

<decisions>
## Implementation decisions

### Sources and scope
- **D-01:** IBKR only for prices. No new data sources (owner, 2026-09-26). Yahoo's dividend history stays as reference data in `dividend_events` (todo 428); it is never a price source. Stage V (vendor) stays closed. Stages are source-agnostic so a vendor later becomes one more `source` value in D1.
- **D-02:** Daily bars are the scope of D1, D2 and D5. Intraday keeps its current table; only D3's venue-move inventory and recovery, D7's daily-vs-aggregated-intraday check and D2b's derived 15m/1h grid reach intraday in this phase.
- **D-03:** D8 (forward survivorship capture) is descoped. Todo 438 (borrow snapshots) is outside this phase. A delisted name is never soft-deleted (`is_active` untouched).

### D0 data-quality labels
- **D-04:** Every research attempt carries typed data-quality labels recorded with the attempt: venue truncation share (daily and intraday cells on names whose history starts at a venue move), dividends (total-return flag plus share of cells without dividend coverage), survivorship bound (literature haircut plus delisting-return sensitivity per unified design 12.2), and scrub-flag share (cells on D2a-flagged bars). Old verdicts are not re-run (they are UCR summary cards). Reruns happen only for reopened ideas, on canonical bars.

### D1 raw observation store
- **D-05:** Append-only `ohlcv_observation` table for 1d: symbol, bar date, OHLCV, `source` (ibkr), `route` (SMART or a venue code), `what_to_show` (TRADES, ADJUSTED_LAST), `fetched_at`, request id. Every IBKR answer lands here first, including routes not chosen. Expected size 12-18M rows. Loaded with `COPY`; D1 writer and D2 derivation are separate database roles (unified design 14.5).

### D2 canonical derivation
- **D-06:** A deterministic, versioned rule derives 1d rows from D1 and writes them into `market_data_ohlcv`. The derivation is the only writer of 1d rows there (owner decision 2). Every consumer keeps reading the same table and view. Each canonical row carries the rule version and the observations it came from.
- **D-07:** Revisions propagate through the unified design's provenance batches keyed by an input content digest per (symbol, tf, range) (design 3.3), so downstream writers recompute only affected cells. Every research snapshot records the D2 rule version it read.

### D2a scrubbing
- **D-08:** Scrubbing is a stage of the derivation, not a side audit. Rules are APR-parameterized pure functions over D1 observations: OHLC invariants, non-positive/zero prices, volatility-scaled jumps with no recorded corporate action, repeated stale prints, volume outliers, IBKR view disagreement (D7).
- **D-09:** Flag, never delete. Each canonical bar carries a quality flag and the rule that set it. Raw observations are permanent. S0 excludes flagged bars by default (quarantine).
- **D-10:** Every rule is validated on known answers before it touches research data: known splits/reverse splits, known corporate events, the 15 `confirmed_corrupt` rows, hand-checked real extreme moves, and the 2026-09-26 dry run of `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py --tf 1d` (45 unflagged corrupt bars; 27 bars wrongly cleared by cross-symbol corroboration, 26 of them 2010-05-06 Flash Crash stub prints plus EWW 2006-11-07; 1,864 ambiguous edge bars that are not candidates).
- **D-11:** Cross-symbol corroboration must not clear a print beyond the magnitude threshold. The Flash Crash date is a known answer for that rule.
- **D-12:** One historical batch pass over all 1d history (minutes), then the same rules on every nightly derivation. Folds in todos 155, 347 and 052.
- **D-13:** Reuse `classify_candidate_bar` in `src/intelligence/statistics/price_sanity.py` as one D2a rule, run as a batch rule (not through the disabled `bar_auditor`).
- **D-14:** `forward_return_writer`'s bar-describing flags (`return_*_suspect`, cross-symbol corroboration, `has_gap_before_entry`) move to bar flags before phase 186 deletes that writer (UD-25, design 14.7). Intraday gets the rules once proven at 1d.

### D2b derived 15m and 1h grid (UD-25, todo 446)
- **D-15:** The derivation writes 15m and 1h bars from 5m on session-anchored edges (09:30, 09:45, ...; 09:30, 10:30, ...): first open, last close, max high, min low, summed volume, never across a session boundary. These become the only 15m/1h rows readers see; stored IBKR 15m/1h become raw observations. Must land before phase 186's `feature_vectors` rebuild. Test: derived bars equal a direct computation from 5m and none spans a session.

### D3 venue-move recovery (todo 433)
- **D-16:** The merged 433 fix (0d225b312) is rebased on D1: store every venue's answer, leave the choice to D2.
- **D-17:** Venue bars are used only after a validation study on at least 30 names with known listing venues across NYSE, Nasdaq and NYSE Arca shows (a) the listing venue has the most volume on nearly every day and (b) only its closes match SMART's. If either fails, venue bars stay stored and unused. The study fetches its own SMART and venue bars and does not wait on D1.
- **D-18:** Venue volume stays NULL in the tradeable view (owner decision). Recovered intraday bars get the same NULL-volume treatment and no intraday feature reads them until the study covers intraday too.
- **D-19:** Recovered intraday history enters through content-digest keys after phase 186's rebuild, never under a live or resumable ic_engine run. The rebuild does not wait on D3 and D3 does not wait on the rebuild.

### D4 empty history
- **D-20:** A span is recorded empty only when every route answered a definitive "no data", answers kept in D1. Verify-only mode already shipped (0d225b312, migrations 374/375; `infra.ibkr.venue_fallback.store_bars` = false). The intraday `ohlcv_empty_history` rows need the same re-verification once verify-only covers intraday.

### D5 corporate actions
- **D-21:** Splits: nightly fetch overlaps the last N stored days; a constant price ratio across the overlap is a split, recorded in a new `corporate_action` table with the inferring observations; D2 re-derives on one scale.
- **D-22:** IBKR dividends derived from ADJUSTED_LAST vs TRADES stored in D1, written to `dividend_events` with `source = 'ibkr_adjusted_last_ratio'`. D5 replaces only the I/O of `services/dividend_event_writer.py --sources ibkr` and reuses its pure functions unchanged (`join_adjustment_pairs`, `derive_ibkr_events` with the lockstep rule `threshold.dividend_event.stable_sessions`, `reconcile`, `research/dividends.DisputeRule`). Validate on known dividends (JPM, KO, XLU) before research uses IBKR rows alone.
- **D-23:** D5 needs a rule for 1-5 day date disagreements between sources (26 events on 18 names). Conservative choice: a disputed-date record that marks the spanning returns unknown.
- **D-24:** Split-seam audit of the existing corpus runs early (no D1/D2 dependency): compare stored closes with a fresh TRADES fetch; a constant ratio over a date range is a seam. MRNA 2026-08-19 and ALMS 2026-09-01 first.

### D6 listing-venue history
- **D-25:** Point-in-time `listing_venue` (symbol, venue, valid_from, valid_to), inferred from D3's recovered spans.

### D7 reconciliation
- **D-26:** A daily audit chained after the nightly backfill reports into `integrity_monitor` and Grafana: SMART vs venue, TRADES vs ADJUSTED_LAST outside explained factors, daily vs aggregated intraday (close = last regular-session 5m close, volume = intraday sum), unexplained seams, heads later than first known trade, empty-history rows not confirmed by every route, and dividend freshness (Yahoo coverage end vs last session). Thresholds in APR.

### Order and minimum data bar
- **D-27:** Order: (1) D0 in parallel throughout; (2) 1d re-run under verify-only for the 384 late-starting names, the D3 validation study, the D5 seam audit and the D2a historical scrubbing pass with known-answer validation, none needing D1; (3) D1 then D3 rebased on it; (4) D2 derivation, then moved names re-backfilled through it if the study passed; (5) D5 split detection on the nightly overlap and the ADJUSTED_LAST dividend route; (6) D7; (7) D6. D2b lands before phase 186's rebuild.
- **D-28:** Daily attempts 3, 3b and 4 run only after: seam audit and scrubbing pass done (flagged bars quarantined); moved names flagged and excluded before their move unless recovered; total-return targets (todo 428 opt-in); survivorship bound. Step (2) of D-27 clears this bar.

### IBKR history-stream lease (added 2026-09-27, after todo 449's single-stream finding)
- **D-29:** IBKR serves one heavy historical stream at a time (todo 449, measured 2026-09-27: four parallel 5m lanes plus three 15m/1h lanes gave no more throughput than one and mostly timed out). Every process that sends IBKR historical requests holds one exclusive lease first: a session-level PostgreSQL advisory lock on a dedicated connection (released by the server when the process dies, so no stale lease), acquired by the process that talks to IBKR, never by an orchestrating parent (the nightly and campaign scripts pass a tier to their fetch subprocesses). Two tiers, carried in the connection's `application_name`: `bulk` (default; long backfills such as the todo 449 chain) releases the lease at every completed (symbol, timeframe) unit when any process is waiting and re-queues; `priority` (nightly legs, phase 185 campaigns, the D3 study) holds until done and yields only to a waiting `priority` holder. This replaces the nightly's `pgrep` skip (a whole night silently skipped whenever any backfill ran), plan 09's pilot-under-contention preflight and its clock blackout window. A nightly leg that cannot get the lease within an APR timeout fails loudly (job status and an integrity fact), never skips. A CI test fails any module that calls the provider's historical fetch without the lease.
- **D-30:** Client IDs are fixed per job, not negotiated: the todo 449 chain keeps 46 (15m/1h) and 40 (5m), the nightly and dividend writer 45, the live provider 35; phase 185 campaigns use 47 (head re-run), 48 (D1 bootstrap), 49 (D3 study, intraday verify). The lease, not the client ID, serializes the stream.
- **D-31:** DB-write jobs that race the nightly (grid rewrite, historical D2 apply, D3 re-derivation) check the nightly unit's actual state (`systemctl is-active indicagent-nightly-backfill.service`) at start and between chunks instead of a clock window, and rely on the content-digest `--changed-only` rerun for anything a concurrent append made stale.

### Claude's discretion
- Plan decomposition, wave layout, migration numbering, module placement (respecting the Ring rule), table column details beyond those named above, APR key names under existing namespaces, and the exact known-answer test fixtures.

</decisions>

<canonical_refs>
## Canonical references

**Downstream agents MUST read these before planning or implementing.**

### Phase spec
- `docs/plans/2026-09-26-daily-data-foundation.md` - the accepted phase spec, revision 2, with owner decisions 1-9
- `docs/plans/2026-09-26-unified-research-to-production-design.md` - sections 3.3 (provenance batches, content digests), 10.2 (summary cards), 12.2 (delisting sensitivity), 14.5 (per-writer roles), 14.7 (UD-25, targets from bars, `forward_return_writer` deletion), 16 (sequence)

### Todos owned or folded
- `.planning/todos/pending/433-ibkr-daily-history-truncated-at-primary-listing-venue-change.md` (P0)
- `.planning/todos/pending/446-stored-1h-bars-drop-first-half-hour-on-39-symbols.md`
- `.planning/todos/pending/155-price-sanity-status-historical-backfill.md`
- `.planning/todos/pending/347-price-sanity-index-column-order-mismatch-bar-auditor-query.md`
- `.planning/todos/pending/052-adversarial-data-error-hunt.md`
- `.planning/todos/pending/376-survivorship-bias-active-only-universe-no-owner.md`

### Existing code to reuse
- `src/providers/ibkr.py` - all ib_async logic; phase 185 owns its changes
- `src/intelligence/statistics/price_sanity.py` - `classify_candidate_bar`
- `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py` - dry-run source of the known-answer set
- `services/dividend_event_writer.py`, `src/intelligence/research/dividends.py` - D5 pure functions and `DisputeRule`
- `scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py` - nightly/historical backfill
- `services/forward_return_writer.py` - flags that move to bars (D-14)

### Project rules
- `CLAUDE.md` - APR mandate, DAG invariants, `market_data_ohlcv_tradeable` boundary test, compressed-hypertable migration VACUUM rule, ProcessPoolExecutor write rule, ic_engine live-run rule
- `docs/foundation/instrument-onboarding-sop.md` - onboarding chain whose second gap (scrubbing) D2a closes
- `docs/foundation/performance-investigation-sop.md` - before any multi-million-row batch against a hypertable

</canonical_refs>

<specifics>
## Specific ideas

- Measured 2026-09-26: 3.86M tradeable 1d bars; 0 OHLC invariant violations; 3 non-positive prices; `price_sanity_status` NULL everywhere except 15 `confirmed_corrupt`; 253 moves >50% and 1,901 >25% unexamined.
- Moved names with truncated history: AMD 2015-01-02, CSX 2015-12-22, IEF 2017-08-03, PEP 2017-12-20, TLT 2016-02-03, plus MAR, SHY, PFF. Former-venue routing recovers history (ADI 2009-10, UAL 2015-16). Venue codes: NYSE, ARCA, ISLAND, AMEX, BATS. Error 162 marks the gap.
- 384 names start 1d history after the request window's start; the other 547 start October 2006.
- Stored 1h lacks the 09:30-10:00 bar on 39 of 231 names (SPY included); stored 15m equals aggregated 5m exactly.
- Known-answer examples: IWO 2009-05-26 high 1,000,000; TRST 2007-07-26 high 500,000; ARE 2007-02-27 low 0.01; UHAL 2022-11-09 bad close; EQIX 2010-05-06 high 100000; EWW 2006-11-07 high 100000.
- Dividend route measurements: NVR 2004 lockstep failure; SPY 2001-2007 and five HYG months missing in IBKR; HYG November 2012 recovered; 606 of 42,926 value disputes (part-stock specials WY 2010, CXW 2013, IRM 2012, UDR 2008); 20-year window is one request per series.

</specifics>

<deferred>
## Deferred ideas

- D8 forward survivorship capture (descoped by owner 2026-09-26).
- Stage V vendor source (gated on owner lifting the no-new-sources constraint).
- Raw observation store for intraday (after the pattern proves itself at 1d).
- Todos 395 and 387 (nightly backfill reliability and staleness observability) sit in the same data lane but are not phase 185 deliverables; D7 consumes their output.
- Todo 438 (borrow snapshots) is outside this phase.

</deferred>

---

*Phase: 185-daily-data-foundation*
*Context gathered: 2026-09-26 via PRD express path*
