# Daily data foundation (phase proposal)

**Author:** Claude (Opus 5.5), 2026-09-26, at Brandon's request ("write the phase proposal with
vendor shortlist; we can't add new data sources yet").
**Status:** accepted 2026-09-26 (all four decisions at the end); roadmap Phase 185.

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
3. **No dividends (todo 428).** Daily targets are price returns, not total returns.
4. **No corporate-action handling.** No table records splits or dividends. IBKR's TRADES
   history is split-adjusted at fetch time, so after a split the nightly job appends bars at the
   new scale beside stored bars at the old scale. Nothing detects the seam. Unchecked candidates:
   MRNA +177% on 2026-08-19, ALMS -57% on 2026-09-01.

Underneath all four is one design gap: `market_data_ohlcv` mixes what a source said with what we
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

Owner decision 2026-09-26. Stages D1-D7 below use IBKR only. They are built source-agnostic, so
a vendor later becomes one more source in the observation store rather than a rebuild. Stage V
holds the vendor shortlist until the constraint lifts.

## Scope (IBKR only)

Daily bars are the scope of D1, D2 and D5. Intraday (about 660M rows, mostly calendar
placeholders) keeps its current table; the raw-store pattern extends there once it has proven
itself at 1d. Two parts do reach intraday now: D3's venue-move inventory and recovery, and D7's
check of daily bars against aggregated intraday bars.

### D0. Measure the damage (runs in parallel from day one)

A verdict is not evidence until its data defects have been bounded. For each verdict the project
relies on:
- **Venue moves:** rerun it with moved names excluded before their move. If it survives, the
  defect did not matter for it.
- **Dividends:** re-score the ETF families, the most exposed (bond, utility and REIT funds earn
  much of their return as dividends), on approximate total returns from ADJUSTED_LAST.
- **Survivorship:** it cannot be fixed without delisted data, but it can be bounded. Apply a
  haircut of the size the literature reports (roughly 1-2% a year in small caps, less in large
  caps) and report whether the verdict survives it.

Each verdict carries the result as a data-quality label in the construction-verdict ledger.

### D1. Raw observation store

An append-only `ohlcv_observation` table for 1d: symbol, bar date, open, high, low, close,
volume, plus `source` (ibkr), `route` (SMART, a venue code), `what_to_show` (TRADES,
ADJUSTED_LAST), `fetched_at` and a request id. Every IBKR answer lands here first, including the
venues and routes not chosen. Size at 819 names: about 4M rows per route over 20 years, so
roughly 10-15M rows with the routes below, small next to the intraday tables.

### D2. Canonical daily bar

A deterministic, versioned rule derives the 1d rows research reads from D1 and writes them into
`market_data_ohlcv`, whose 1d rows then have exactly one writer: the derivation (owner decision
2026-09-26). Every consumer keeps reading the same table and view, while raw and canonical stay
separate. Changing the rule is a recompute, not a re-fetch, and each canonical row carries the
rule version and the observations it came from.

### D3. Venue-move recovery (todo 433), rebased on D1 (1d and intraday)

Branch `fix/433-venue-move-history` (a905709b4) already asks every former-venue candidate and
keeps the one with the most volume. Rebased on D1 it stores every venue's answer and leaves the
choice to D2. Before D2 uses venue bars, a validation study on names whose listing venue is known
today (at least 30 across NYSE, Nasdaq and NYSE Arca) must show two things: the listing venue
has the most volume on nearly every day, and only its closes match SMART's. If either fails,
venue bars stay stored and unused. Venue volume stays NULL in the tradeable view either way
(owner decision 2026-09-26).

Intraday uses the same routing. Volume matters more there (participation, dollar volume,
illiquidity), so recovered intraday bars get the same NULL-volume treatment, and no intraday
feature reads them until the validation study covers intraday bars too. Recovered intraday
history changes `feature_vectors` inputs, so it goes in through a planned corpus recompute, never
under a live or resumable ic_engine run.

### D4. Empty history as a derived fact

A span is recorded empty only when every route answered a definitive "no data", with the
answers kept in D1. The rule ships ahead of D1 in the 433 branch in verify-only mode (owner
decision 2026-09-26): former venues are asked, history found there blocks the empty record and
is logged for the D6 inventory, and no venue bar is stored until D3's study passes
(`infra.ibkr.venue_fallback.store_bars`, false). Migration 374 also deletes the existing 1d
`ohlcv_empty_history` rows for re-verification. The intraday rows (72 of 88 per timeframe) need
the same treatment once verify-only covers intraday.

### D5. Corporate actions, point in time

- **Splits.** Each nightly fetch overlaps the last N stored days. A constant price ratio across
  the overlap is a split (or a reverse split): record it in a new `corporate_action` table with
  the inferring observations, and let D2 re-derive the history on one scale.
- **Dividends from IBKR.** ADJUSTED_LAST history is adjusted for splits and dividends. Stored
  beside TRADES in D1, the ratio of the two series implies each ex-date and its factor. This is an
  IBKR-only route to total returns (todo 428), to be validated against known dividends (JPM, KO,
  XLU quarterly) before research uses it. ADJUSTED_LAST also starts at the last venue move, so
  moved names get total returns only after their move until a vendor fills the rest.
- **Audit the existing corpus** for split seams (MRNA and ALMS above first).

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

### D8. Survivorship, going forward

IBKR cannot fill the past, but the future can stop being survivor-only:
- Keep every onboarded name forever, and record a delisting (date, last bar, reason if known)
  when IBKR stops qualifying it. The panel from today onward then includes the names that later
  die.
- Store every holdings snapshot we already download (IWM, IWV, IVV) as dated, point-in-time
  index membership. It starts accumulating now, and seeded draws can later sample membership as
  of a date.

The retroactive fix needs Stage V.

## Research during the phase

Alpha work continues in parallel (ALPHA FIRST, 2026-09-24). Every daily-panel verdict is tagged
with the data vintage and the defects above. When D2-D5 land, the verdicts that matter are rerun
on the canonical bars, and the ledger records whether each verdict moved.

## Order

0. D0 damage measurement, in parallel with everything below.
1. D4's rule via the 433 branch (verify-only), then the D1 observation store.
2. D3 rebased on D1, then the validation study.
3. D2 canonical derivation, then the 433 re-backfill through it.
4. D5 splits, the ADJUSTED_LAST dividend study, the corpus seam audit.
5. D7 audits.
6. D6 and D8.

## Success criteria

- Every 1d bar research reads traces to the observations and rule version that produced it.
- No `ohlcv_empty_history` row exists that every route has not confirmed.
- Moved names' closes chain across the move date with no jump beyond normal daily moves, or the
  seam is explained by a recorded action.
- Split seams in the corpus: found, recorded, and re-derived, with an audit that catches the next
  one within a day.
- The dividend route is validated on known ex-dates or reported as unusable.
- The daily-panel verdicts that matter are rerun and their movement recorded.

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
