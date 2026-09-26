# Daily data foundation (phase proposal)

**Author:** Claude (Opus 5.5), 2026-09-26, at Brandon's request ("write the phase proposal with
vendor shortlist; we can't add new data sources yet").
**Status:** accepted 2026-09-26 (all four decisions at the end); roadmap Phase 185. **Revision 2
(2026-09-26):** aligned with the adopted unified design (`docs/plans/2026-09-26-unified-research-to-production-design.md`, E18): D0 re-aimed at
attempts, an explicit scrubbing stage (D2a), revision propagation, the minimum data bar for daily
attempts, intraday labels, one snapshot capture job, and the design's write mechanics. Decisions
5-7 at the end.

## Why now

Daily bars feed phase 183's research panel and every daily verdict since. They have four
defects, all confirmed on 2026-09-26. The first also reaches the intraday corpus: 5m and 1h
history for the moved names starts on exactly the same dates as their 1d history (AMD
2015-01-02, CSX 2015-12-22, IEF 2017-08-03, PEP 2017-12-20, TLT 2016-02-03), so every intraday
feature treats them as listed at their move too.

1. **History truncated at listing-venue moves (todo 433, P0).** A SMART-routed IBKR request
   serves history only from a stock's current primary listing on. AMD, CSX, PEP, MAR, TLT, IEF,
   SHY, PFF and others start years after they began trading, and `ohlcv_empty_history` records
   the missing years as verified empty, so the nightly backfill never asks again. Routing the
   same contract to the former venue serves those years (ADI 2009-10, UAL 2015-16).
2. **Survivors only (todo 376).** IBKR does not serve delisted names, so every panel and every
   small-cap draw holds only firms alive today.
3. **Dividends are Yahoo-only in practice (todo 428, closed 2026-09-26).** `dividend_events`
   (migration 376) holds Yahoo's declared dividends for all 932 active equities, refreshed daily
   (`indicagent-dividend-event-writer@yahoo`), and research specs opt into total-return prices
   with `panel.total_return`. The IBKR route in D5 is the second, independent source still to
   build: without it Yahoo's own holes are invisible (HYG's November 2012 distribution is missing
   there).
4. **No corporate-action handling.** No table records splits or dividends. IBKR's TRADES
   history is split-adjusted at fetch time, so after a split the nightly job appends bars at the
   new scale beside stored bars at the old scale. Nothing detects the seam. Unchecked candidates:
   MRNA +177% on 2026-08-19, ALMS -57% on 2026-09-01.
5. **Bad bars in stored history (todos 052, 155, 347; linked here in the 2026-09-26 backlog
   triage).** An adversarial data-error hunt, the price-sanity historical backlog (the
   `close=0` Flash Crash bar class), and the partial index that leaves the price-sanity scan
   unusable. Candidates for the same validation pass as D3 and the split-seam audit.

Underneath the first four is one design gap: `market_data_ohlcv` mixes what a source said with what we
believe. Each fetch writes straight into the table the research reads (ON CONFLICT DO NOTHING),
so no record says which source, route or fetch produced a bar, a correction overwrites nothing
and records nothing, and a better rule for choosing a bar needs a re-fetch.

## What Renaissance would do

- **Several sources, reconciled.** No single feed is trusted; agreement is measured and
  disagreement is logged and resolved by rule.
- **Raw observations separate from canonical values.** Every answer from every source is kept,
  with when it was received. The value research reads is a derived, versioned, reproducible
  choice over those observations.
- **Point in time.** Prices, corrections, corporate actions, index membership and listing venues
  are recorded as known at a date, so any past state can be rebuilt.
- **Validate before trusting.** A cleaning rule is measured on cases with a known answer before
  it touches research data.
- **Automated audits.** Disagreements, seams and gaps raise alerts every day, not when a
  researcher trips over them.

## Constraint: no new data sources yet

Owner decision 2026-09-26. Stages D1-D7 below use IBKR only. One exception, also 2026-09-26:
Yahoo's dividend history stays as reference data for `dividend_events` (decision 8); it is never
a price source. The stages are built source-agnostic, so
a vendor later becomes one more source in the observation store rather than a rebuild. Stage V
holds the vendor shortlist until the constraint lifts.

## Scope (IBKR only)

Daily bars are the scope of D1, D2 and D5. Intraday (about 660M rows, mostly calendar
placeholders) keeps its current table; the raw-store pattern extends there once it has proven
itself at 1d. Three parts do reach intraday now: D3's venue-move inventory and recovery, D7's
check of daily bars against aggregated intraday bars, and D2b's derived 15m and 1h grid.

### D0. Data-quality labels on attempts (runs in parallel from day one)

Revision 2: old verdicts become UCR summary cards and are never re-scored (unified design 10.2), so
D0 no longer re-runs them. Instead every research attempt carries typed data-quality labels,
recorded with the attempt:
- **Venue truncation:** the share of the attempt's (name, session) cells on names whose history
  starts at a venue move, daily and intraday alike (families 1 and 2 run on intraday panels that
  the same truncation cuts).
- **Dividends:** whether targets are total returns (todo 428's opt-in) and the share of cells
  without dividend coverage.
- **Survivorship bound:** a literature haircut (roughly 1-2% a year in small caps, less in large
  caps) and the delisting-return sensitivity of design section 12.2, reported beside the statistic.
- **Scrub flags:** the share of cells on bars D2a flagged.

Reruns happen only for ideas that are reopened, on canonical bars.

### D1. Raw observation store

An append-only `ohlcv_observation` table for 1d: symbol, bar date, open, high, low, close,
volume, plus `source` (ibkr), `route` (SMART, a venue code), `what_to_show` (TRADES,
ADJUSTED_LAST), `fetched_at` and a request id. Every IBKR answer lands here first, including the
venues and routes not chosen. Size at 932 names: about 4.5M rows per route over 20 years, so
roughly 12-18M rows with the routes below, small next to the intraday tables.

### D2. Canonical daily bar

A deterministic, versioned rule derives the 1d rows research reads from D1 and writes them into
`market_data_ohlcv`, whose 1d rows then have exactly one writer: the derivation (owner decision
2026-09-26). Every consumer keeps reading the same table and view, while raw and canonical stay
separate. Changing the rule is a recompute, not a re-fetch, and each canonical row carries the
rule version and the observations it came from.

**Revisions propagate.** D2 rule changes, D3 recovery and D5 split re-derivation all revise past
bars. The derivation writes through the unified design's provenance batches keyed by an input
content digest per (symbol, tf, range) (design 3.3), so downstream writers (the `feature_vectors`
rebuild, the shrunk ic_engine's targets) recompute only the affected cells. Every research snapshot records the
D2 rule version it read, so a frozen book's inputs are pinned and a revision is visible, never
silent. D1's writer and D2's derivation are separate database roles (design 14.5) and load with
`COPY`.

### D2b. Derived 15m and 1h bars (unified design UD-25, todo 446)

The derivation writes 15m and 1h bars from 5m on session-anchored edges (09:30, 09:45, ...;
09:30, 10:30, ...): open of the first 5m bar, close of the last, high max, low min, volume sum,
never across a session boundary. Those become the only 15m and 1h rows readers see; stored IBKR
15m and 1h bars become raw observations. Measured 2026-09-26: stored 15m equals aggregated 5m
exactly, so 15m changes no value; stored 1h has no 09:30 to 10:00 bar on 39 of 231 names (SPY
included, every year 2006 to 2025), only a zero-volume 09:00 placeholder, so 1h features and
targets for those names skip the open. This lands before phase 186's `feature_vectors` rebuild,
so 1h features are rebuilt once, on the right bars. Test: derived bars equal a direct
computation from 5m and none spans a session (multi-timeframe design D7 guard 4).

### D2a. Scrubbing (validation between raw and canonical)

Measured 2026-09-26 on the 3.86M tradeable 1d bars: OHLC invariants hold (0 violations), 3 bars
have non-positive prices, every bar's `price_sanity_status` is NULL (never classified; 15 rows are
`confirmed_corrupt`; `BarAuditor` is inactive), and 253 daily moves exceed 50% and 1,901 exceed
25% with no examination. Scrubbing is a stage of the D2 derivation, not a side audit:

1. **Rules**, each an APR-parameterized pure function over D1 observations: OHLC invariants,
   non-positive or zero prices, jumps beyond a volatility-scaled threshold with no recorded
   corporate action, repeated stale prints, volume outliers, disagreement between IBKR's views
   (D7).
2. **Flag, never delete.** Each canonical bar carries a quality flag and the rule that set it. Raw
   observations are permanent. S0 excludes flagged bars by default (quarantine), and the attempt's
   labels (D0) report how many it touched.
3. **Validate every rule on known answers first:** known splits and reverse splits, known
   corporate events (mergers, spin-offs), the 15 confirmed-corrupt rows, and hand-checked real
   extreme moves, so a rule neither misses seams nor quarantines real returns. A dry run of
   `scripts/ops/corpus/ops_known_corrupt_print_cleanup.py --tf 1d` over all 932 names
   (2026-09-26, no writes) adds to the known-answer set:
   - 45 bars classified confirmed-corrupt, not yet flagged, mostly 2006-2009 highs and lows of
     0.01, 999.99, 100000 or more on sane opens and closes (IWO 2009-05-26 high 1,000,000;
     TRST 2007-07-26 high 500,000; ARE 2007-02-27 low 0.01), plus UHAL 2022-11-09 with a bad
     close. About a dozen are in the 233 `compute_eligible` names, so their `feature_vectors`
     rows need recomputing once flagged (targets are computed from bars, UD-25).
   - A defect in the classifier's cross-symbol corroboration: 27 bars pass as market events
     because other symbols spike the same day. 26 are 2010-05-06 Flash Crash stub prints (lows
     of 0.01, EQIX high 100000), trades that were busted, so the prices are wrong however many
     symbols share them; EWW 2006-11-07 (high 100000, n=10) passes the same way. Corroboration
     must not clear a print beyond the magnitude threshold, and the Flash Crash date is a
     known answer for that rule.
   - 1,864 ambiguous bars, which on inspection are first and last bars with no neighbor, not
     candidates.
4. **One historical pass as a batch job** over all 1d history (minutes, not the 4.1 years todo 155
   estimated through the live auditor's cadence), then the same rules on every nightly derivation.
   Folds in todos 155 (historical price sanity), 347 (the unusable price-sanity index) and 052
   (the adversarial error hunt, as rule 3's known-answer set plus a search for new classes).
5. **Intraday** gets the same rules once they have proven themselves at 1d. The flags
   `forward_return_writer` sets on returns (`return_*_suspect`, the cross-symbol corroboration
   pass, `has_gap_before_entry`) describe bars, not returns; they move here as bar flags before
   that writer is deleted in phase 186 (unified design 14.7).
6. **Reuse, don't rewrite.** The existing price-sanity classifier
   (`src/intelligence/statistics/price_sanity.py`, `classify_candidate_bar`) becomes one D2a rule.
   It has never classified history because it only runs inside `bar_auditor`, a streaming-era
   daemon that is disabled; D2a runs it as a batch rule over the derivation instead.

D2a and D7 are the project's price-integrity layer. The existing integrity services check other
things (inventory 2026-09-26): the v2.x auditors (`data_quality_auditor`, `feature_parity_auditor`,
`signal_auditor`, `shadow_auditor`, `signal_probe_auditor`, `signal_replay_auditor`,
`shadow_validator`, `confidence_calibration_monitor`, `feature_validation_agent`) check archived
v2.x tables and are disabled; `bar_auditor` (gap detection plus price sanity) is disabled;
`regime_coverage_auditor` checks regime labels; `compression_auditor` checks storage; the
vocabulary drift and classification coverage audits check codes. None checks historical price
correctness.


### D3. Venue-move recovery (todo 433), rebased on D1 (1d and intraday)

The 433 fix (merged 0d225b312) already asks every former-venue candidate and keeps the one
with the most volume. Rebased on D1 it stores every venue's answer and leaves the
choice to D2. Before D2 uses venue bars, a validation study on names whose listing venue is known
today (at least 30 across NYSE, Nasdaq and NYSE Arca) must show two things: the listing venue
has the most volume on nearly every day, and only its closes match SMART's. If either fails,
venue bars stay stored and unused. The study fetches its own SMART and venue bars for recent
years, so it does not wait for D1; only storing the recovered history does. Venue volume stays NULL in the tradeable view either way
(owner decision 2026-09-26).

Intraday uses the same routing. Volume matters more there (participation, dollar volume,
illiquidity), so recovered intraday bars get the same NULL-volume treatment, and no intraday
feature reads them until the validation study covers intraday bars too. Recovered intraday
history changes `feature_vectors` inputs, so it goes in through the content-digest keys: only the
affected names and ranges recompute after phase 186's `feature_vectors` rebuild, with no second
full rebuild, and never under a live or resumable ic_engine run. The rebuild does not wait for D3,
and D3 does not wait for the rebuild.

### D4. Empty history as a derived fact

A span is recorded empty only when every route answered a definitive "no data", with the
answers kept in D1. The rule shipped ahead of D1 on 2026-09-26 (0d225b312, migrations 374 and
375 applied) in verify-only mode (owner decision 2026-09-26): former venues are asked, history found there blocks the empty record and
is logged for the D6 inventory, and no venue bar is stored until D3's study passes
(`infra.ibkr.venue_fallback.store_bars`, false). Migration 374 also deletes the existing 1d
`ohlcv_empty_history` rows for re-verification. The intraday rows (72 of 88 per timeframe) need
the same treatment once verify-only covers intraday.

### D5. Corporate actions, point in time

- **Splits.** Each nightly fetch overlaps the last N stored days. A constant price ratio across
  the overlap is a split (or a reverse split): record it in a new `corporate_action` table with
  the inferring observations, and let D2 re-derive the history on one scale.
- **Dividends from IBKR, as the second source.** ADJUSTED_LAST history is adjusted for splits
  and dividends. Stored beside TRADES in D1, the ratio of the two series implies each ex-date and
  its amount; D5 derives those from the stored observations, so every event is reproducible from
  the raw store. It writes `dividend_events` with `source = 'ibkr_adjusted_last_ratio'` beside
  Yahoo's rows (migration 376 already carries the source column, per-source coverage and the
  reconciled view). What the interim live-fetch writer (todo 428) measured, 2026-09-26:
  - **Holes.** IBKR's adjustment record misses SPY's 2001-2005 dividends and its December 2006
    and 2007 ones, and five HYG months. A missing adjustment cannot be seen from IBKR's data
    alone.
  - **Lockstep.** The rounding bound (0.005 on each adjusted close) only holds where both series
    use the same close. In parts of IBKR's early history they do not (NVR 2004: the ratio wanders
    0.3% a day, up to 150 times the bound), and the first pass derived hundreds of false events
    on names that paid nothing (NVR, AXON, MRVL, EQIX in 2004). A step counts only if the ratio
    stays within the bound for `threshold.dividend_event.stable_sessions` (3) rows on each side
    (migration 378). After that rule: NVR and AXON derive nothing, SPY and TLT match Yahoo
    exactly, HYG recovers Yahoo's November 2012 hole.
  - **Date disagreements.** 26 dividends on 18 names are reported by both sources 1 to 5 days
    apart, in both directions, 2006 to 2025. Keeping both rows would double count, so the writer
    rolls the symbol back. D5 needs a rule here (a disputed-date record that marks the spanning
    returns unknown is the conservative one); the interim writer has none.
  - **Pacing.** A 25-year daily request is two TRADES chunks and hit IBKR soft pacing (retry
    backoff); a 20-year window is one request per series.
  - ADJUSTED_LAST starts at the last venue move, so moved names get IBKR dividends only after it.
  - **Value disputes.** 606 of 42,926 two-source events disagree beyond IBKR's rounding bound
    (0.02 / prior close). The large ones are part-stock specials (WY 2010: Yahoo 63%, IBKR 24%;
    CXW 2013, IRM 2012, UDR 2008): Yahoo records the whole distribution, while IBKR's factor is
    the one that reconciles IBKR's own TRADES series, which is what we store. The reader already
    resolves this (`research/dividends.resolve_event`, migration 379; the writer's APR values,
    recorded in each snapshot): agreement uses Yahoo,
    a dispute applies IBKR's yield and counts as unconfirmed, so the spec's suspect_yield splits
    the symbol when the dispute is large.
  The interim IBKR writer (`services/dividend_event_writer.py --sources ibkr`) has no timer. D5
  replaces only its I/O: read ADJUSTED_LAST and TRADES from D1 instead of fetching them, and reuse
  the tested pure functions unchanged (`join_adjustment_pairs`, `derive_ibkr_events` with the
  lockstep rule, `reconcile`, and `research/dividends.DisputeRule`, the one dispute predicate the
  writer and the research reader share). Validate on known
  dividends (JPM, KO, XLU quarterly) before research uses IBKR rows alone. D7's daily audit should
  also watch dividend freshness (Yahoo coverage end against the last session), since a timer that
  stops running raises no failure alert.
- **Audit the existing corpus** for split seams (MRNA and ALMS above first). This part needs
  neither D1 nor D2 and runs early: 195 of the 932 names are small caps, where splits and
  reverse splits are common, and every one the nightly job crosses today leaves a seam. The
  audit compares each name's stored closes with a fresh TRADES fetch over the same span; a
  constant ratio over a date range is a seam, recorded in `corporate_action` once that table
  exists.

### D6. Listing-venue history

A point-in-time `listing_venue` record per symbol (venue, valid from, valid to), inferred from
D3's recovered spans. It replaces guessing when inventorying moved names and documents why a
series has a seam.

### D7. Reconciliation and audits

With one vendor, redundancy comes from IBKR's own independent views of a bar: SMART against
each venue, TRADES against ADJUSTED_LAST, and daily bars against our own intraday bars
aggregated up (the daily close must equal the last regular-session 5m close, daily volume must
match the intraday sum). They are different requests and code paths, so disagreement is signal.
A daily audit, chained after the nightly backfill, reports into `integrity_monitor` and Grafana:
- route disagreements (SMART against venue, TRADES against ADJUSTED_LAST outside explained
  factors)
- daily against aggregated intraday: close and volume mismatches
- unexplained seams: a close-to-close jump beyond a threshold with no corporate action recorded
- heads that start later than the instrument's first known trade
- empty-history rows not confirmed by every route

Thresholds live in APR.

### D8. Survivorship, going forward (descoped, owner 2026-09-26)

Not built. Forward capture of delistings and dated index-holdings snapshots was proposed here;
the owner descoped it: few names in this universe stop existing in any given period, and the
past cannot be fixed from IBKR (that needs Stage V). D0 still bounds each verdict's
survivorship exposure. The daily short-borrow snapshot (todo 438) is not survivorship work and
stands on its own (unified design 9.3).

Consequence to keep in mind: a name that does delist must not be soft-deleted
(`is_active = false`), because the research snapshot selects its universe from the current
`instruments` flags and would drop the name's whole history. Leave its flags alone; the nightly
backfill finds nothing new for it.

## Research during the phase

Alpha work continues in parallel (ALPHA FIRST, 2026-09-24). Every attempt carries D0's labels.

**Minimum data bar for daily attempts.** The price-only daily families on the 931 names (unified
design attempts 3, 3b and 4) run only after: the D5 split-seam audit and the D2a historical
scrubbing pass (flagged bars quarantined); moved names flagged, and excluded before their move
unless D3 recovered them; total-return targets (todo 428's opt-in); and the survivorship bound.
When D2-D5 land, reopened ideas are re-evaluated on canonical bars, and under E18 prior attempts
are re-evaluated on the extended data rather than reset.

## Order

0. D0 labels, in parallel with everything below.
1. (D8 descoped 2026-09-26; borrow snapshots are todo 438, outside this phase.)
2. The 1d re-run under the merged verify-only rule (moved-name inventory, empty history
   re-verified) for the 384 names whose first 1d bar is after the request window's start (the
   other 547 start in October 2006, so nothing before a move is missing from the window), the D3 validation study, the D5 corpus seam audit, and the D2a historical
   scrubbing pass with its known-answer validation. None needs D1. Together they clear the minimum
   data bar for daily attempts.
3. D1 observation store, then D3 rebased on it.
4. D2 canonical derivation, then the moved names re-backfilled through it (if the study passed).
5. D5 split detection on the nightly overlap and the ADJUSTED_LAST dividend study.
6. D7 audits.
7. D6.

## Success criteria

- Every 1d bar research reads traces to the observations and rule version that produced it, and
  every research snapshot records that rule version.
- Every 1d bar carries a scrub flag from validated rules; flagged bars are quarantined, never
  deleted.
- Every attempt carries D0's data-quality labels.
- No `ohlcv_empty_history` row exists that every route has not confirmed.
- Moved names' closes chain across the move date with no jump beyond normal daily moves, or the
  seam is explained by a recorded action.
- Split seams in the corpus: found, recorded, and re-derived, with an audit that catches the next
  one within a day.
- The dividend route is validated on known ex-dates or reported as unusable.
- Reopened ideas are re-evaluated on canonical bars and their movement recorded.

## Stage V (gated): a second source

Adding a vendor needs the owner to lift the constraint above. The vendor then writes into D1 as
`source = <vendor>`, and D7 reconciles it against IBKR. The shortlist below was checked on
2026-09-26; items marked unverified must be confirmed with the vendor before any decision.

| Vendor | Delisted US | Historical index membership | Dividends, splits | History | Access | Price |
|---|---|---|---|---|---|---|
| Norgate Data, Platinum | Yes | Yes, including Russell 2000/3000 and S&P 500 | Yes | Daily from 1990 | Updater is Windows-only (Windows 10/11); needs a Windows VM or bridge host | Not shown on the pricing page (calculator only); unverified |
| Sharadar (Nasdaq Data Link) SEP/SFP + S&P 500 table | Yes, about 21,000 active and delisted tickers | S&P 500 only, from 1957; no Russell | Corporate actions table (unverified detail) | Prices from 1998 | REST API, Linux-friendly | Unverified |
| EODHD, EOD Historical Data All World | Yes, US mostly from 2000 | Not verified | Splits and dividends, adjusted series | 30+ years | REST API | $19.99/month ($16.58 annual), personal use only |
| CSI Data, Unfair Advantage | Paid add-on | Index components managed over time (detail unverified) | Yes | Long | Windows software, FTP | Unverified ("a few hundred dollars a year" per third parties) |
| CRSP (via WRDS) | Yes, the academic standard | Yes | Yes | From 1925 | Requires academic or institutional licence | Likely unavailable |

**Recommendation for when Stage V opens:** Norgate Platinum, if a small Windows VM is acceptable.
It is the only candidate with historical Russell membership, and that is what fixes survivorship
in the small-cap draws (todo 376). Otherwise Sharadar for prices, corporate actions and S&P 500
membership, with EODHD as a cheap reconciliation source. In either case IBKR stays the source for
intraday and live data.

## Decisions (owner, 2026-09-26)

1. Accepted into the roadmap.
2. D2 writes derived 1d bars into `market_data_ohlcv`, with the derivation as their only writer.
3. The 433 branch ships D4's rule now in verify-only mode; venue bars are stored only after
   D3's validation study passes.
4. Stage V stays closed: no new data sources for now.
5. Revision 2 (2026-09-26, with the unified design): D0 labels attempts instead of re-running old
   verdicts; D2a scrubbing is part of the derivation, flag-never-delete, rules validated on known
   answers; revisions propagate through content-digest keys and every snapshot records the rule
   version.
6. Superseded by decision 9: D8 is descoped, and todo 438's borrow snapshots stand alone.
7. Daily attempts 3, 3b and 4 wait on the minimum data bar above.
8. Yahoo's dividend history stays as reference data (todo 428, 2026-09-26): it is the only
   complete dividend record available and total-return research depends on it. It is not a price
   source; D5's IBKR route is its independent check.
9. D8 (forward survivorship capture: delisting record, holdings snapshots) is descoped (owner,
   2026-09-26): few delistings in this universe going forward, and the past cannot be fixed from
   IBKR. D0 still bounds survivorship exposure.
