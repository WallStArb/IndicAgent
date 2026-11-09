# Data adjacency register

**Status:** active reference, seeded 2026-11-09 (todo 603, rung 0). Refreshed at the quarterly
scouting pass; rows change only with a verified source finding or a capture decision.
**Author:** Claude worker session, 2026-11-09, executing todo 603 step 1.
**Informed by:** `docs/ideas/base-feature-scouting-and-the-research-ladder.md` (rung 0 and the
seed table), todo 603 ("Source findings 2026-11-09", verified by reading Massive docs, and the
owner rulings), `docs/plans/2026-11-09-massive-pilot-basis-study.md` (the Massive fields the
pilot measures), `docs/foundation/glossary.md` (`data adjacency register`, `base feature`,
`admission gate`).

## Purpose

The proposer measures every numeric column that exists; nothing asks what columns should exist.
This register is the rung-0 answer: one row per field each source serves or could serve, seeded
only from the idea doc's seed table and the verified source findings in todo 603. Rows are not
invented vendor fields; a source not yet seeded (Alpaca quotes, for example) is listed as
unseeded, not populated from memory.

## How to read a row

Columns: source, field, availability time (the point-in-time answer: when is the value knowable),
history start, retrieval cost, license note, stored (yes/no/partial, against our tables), base
features it enables, status.

Status vocabulary (glossary `data adjacency register`):

- `stored`: the field lands in a table we hold.
- `captured-not-used`: stored but no base feature reads it (verify before assuming).
- `worth-capturing`: the diff says we should capture it; capture rides todo 600 and the admission
  gates, carries no look count.
- `rejected-with-reason`: recorded so the same region is not rediscovered and recounted.

Any availability-time or history-start claim not confirmed by reading the vendor's own docs is
marked **(unverified)** and must be verified before capture (todo 603 step 1). Verification is a
property of a row, not of a source.

## Bars and bar-adjacent fields

### Massive flat files (`us_stocks_sip/minute_aggs_v1`)

Admission pending the pilot basis study (`docs/plans/2026-11-09-massive-pilot-basis-study.md`);
nothing below is captured today. Column units, timestamp timezone and price scale are measured in
step 0 of that plan, not taken from docs.

| Field | Availability time | History start | Retrieval cost | License note | Stored | Base features enabled | Status |
|---|---|---|---|---|---|---|---|
| open, high, low, close (per-minute) | file publication, next day (unverified) | eras from 2007 sampled in the pilot; full start unverified | one bulk download per day-file, then archive raw (plan precondition 2) | owner 2026-11-07: purchase approved; licensing is the owner's job | no (candidate daily source; stored equivalents from Alpaca and IBKR) | every price-derived base feature, at a deeper span | worth-capturing (gated on the basis study) |
| volume (per-minute) | as above | as above | as above | as above | no (candidate; Alpaca SIP stored from 2016-01-04) | volume, turnover, volume-basis features | worth-capturing (volume basis recorded, not gated) |
| transactions (trade count) | as above | as above | free with the bars (same rows) | as above | no | activity, average trade size, bar-quality witness | worth-capturing (todo 600 step 2) |
| window_start (bar timestamp) | as above | as above | free with the bars | as above | yes (as `ohlcv_raw.timestamp`) | (the join key; unit disagreement seconds versus nanoseconds measured in step 0, not trusted) | stored (pending admission, unit unverified) |
| extended-hours rows | session continuous (unverified) | as above | free with the bars | as above | no | pre-market return, range, volume share, after-hours return (later, from a separate kernel) | worth-capturing, raw only (owner ruling 2026-11-09: stored, never selected; canonical 5m stays the RTH grid) |
| listing_end | file publication (unverified) | as above | free with the bars | as above | yes (`listing_end`) | survivorship witness, universe spans | stored |

### Alpaca (bars)

| Field | Availability time | History start | Retrieval cost | License note | Stored | Base features enabled | Status |
|---|---|---|---|---|---|---|---|
| open, high, low, close, volume (SIP 5m, 1d) | bar close; nightly capture holds the end 20 min back | 2016-01-04 (5m and 1d, D-191-Q) | nightly timer, already running | captured under the capture law (528) | yes (`ohlcv_raw`, vendor `alpaca`) | the existing bar kernels | stored |
| vwap (`vw` bar field) | bar close (unverified) | unverified | free with bars already pulled | same capture law | no | VWAP deviation without our own estimate; check against the `vp_sr` kernels | worth-capturing |
| trade count (`n` bar field) | bar close (unverified) | unverified | free with bars already pulled | same capture law | no | activity, average trade size, bar-quality witness | worth-capturing |
| extended-hours bars | unverified whether the nightly window covers them | unverified | free with bars already pulled | same capture law | no | pre-market and after-hours summaries (raw only per the owner ruling) | worth-capturing (raw only; coverage unverified) |
| quote fields (NBBO and the rest) | not seeded | not seeded | not assessed | not assessed | no | unseeded; scout at the quarterly pass from the vendor schema, never from memory | unseeded |

### IBKR (bars and contract data)

| Field | Availability time | History start | Retrieval cost | License note | Stored | Base features enabled | Status |
|---|---|---|---|---|---|---|---|
| open, high, low, close, volume (5m pre-2016, 1d) | bar close; nightly gateway restart looks like an outage | pre-2016 5m (the 534 fallback until Massive is admitted) | nightly fetcher, about 1M bars/h at concurrency 4 | captured under the capture law | yes (`ohlcv_raw`, vendor `ibkr`) | the existing bar kernels | stored |
| borrow availability | 16:30 ET timer snapshot | unverified | captured already (timer) | captured under the capture law | yes (`borrow_availability_snapshots`) | crowding, squeeze state; whether any base feature reads it is unverified, check before counting it | captured-not-used (verify) |

## Corporate actions and events

### Massive REST

| Field | Availability time | History start | Retrieval cost | License note | Stored | Base features enabled | Status |
|---|---|---|---|---|---|---|---|
| dividends: declared, record, ex and pay dates, plus `historical_adjustment_factor` | unverified | unverified | cheap REST, all plans (verified finding) | purchase approved | partial: `dividend_events` holds only `ex_date` and `amount`; declaration, record and pay dates missing | declaration-announcement features, cleaner total return | worth-capturing (check Yahoo for the same dates before buying anything) |
| splits | unverified | unverified | cheap REST | purchase approved | yes: `corporate_action` (effective_date, factor, recorded_at, supersedes), stronger on point in time than Massive's (verified finding) | split-adjusted spans; the Massive copy is an independent witness, a cross-check for todo 592 | stored (Massive copy: cross-check only) |
| ticker events (entity map) | unverified; endpoint marked experimental (verified finding) | unverified | cheap REST | purchase approved | no | the ticker-to-entity map (todo 600 step 5), ticker-change features | worth-capturing (experimental upstream; verify before capture) |
| market holidays | forward-looking only (verified finding) | no history | cheap REST | purchase approved | no | session calendar; a forward-looking-only feed cannot reconstruct past sessions | rejected-with-reason: no historical depth, so not point in time for backtests |
| earnings: Benzinga partner feed (`date`, `time` EST, `date_status`, estimates and actuals, `last_updated`) | announcement `date` plus `time`; `date_status` projected versus confirmed; no revision history stated, no before-open or after-close flag (verified findings) | 2010-04-30 (verified) | needs a Benzinga expansion plan (cost decision for the owner) | expansion-plan cost is an owner decision | no | event-window features, post-announcement drift; the projected date is not point in time without a stored history of the estimate | worth-capturing (point-in-time caveat recorded; the `time` or acceptance timestamp is the knowable-by time) |
| corporate events (TMX / Wall Street Horizon) | unverified | 2018 (verified) | expansion plan | expansion-plan cost is an owner decision | no | corporate-event features | unseeded beyond the source finding; assess against EDGAR first |
| income statements | `filing_date` is the most recent filing containing the period, no as-of parameter (verified finding) | unverified | cheap REST | purchase approved | no | fundamentals; not point in time as served | rejected-with-reason: `filing_date` is the latest filing, not the original; use EDGAR's own index instead |
| EDGAR filing index (filing dates, accession numbers) | filing acceptance (unverified) | unverified | cheap REST | purchase approved | no | filing-timing features, event timing | worth-capturing (prefer EDGAR direct for original dates) |

### SEC EDGAR (direct)

| Field | Availability time | History start | Retrieval cost | License note | Stored | Base features enabled | Status |
|---|---|---|---|---|---|---|---|
| 8-K Item 2.02 acceptance timestamp (earnings release) | the acceptance timestamp itself; free, and the actual release only (seed table) | EDGAR's own depth (unverified) | free, self-serve | public data | no | post-announcement drift, event-window features; the acceptance timestamp is the knowable-by time | worth-capturing (the point-in-time-clean earnings source) |

### Yahoo (dividends cross-check)

| Field | Availability time | History start | Retrieval cost | License note | Stored | Base features enabled | Status |
|---|---|---|---|---|---|---|---|
| dividend dates (declaration, record, pay) and amounts | unverified | unverified | free scrape, per-name isolation landed (todo 428) | scrape; no paid terms | partial: `dividend_events` holds `ex_date` and `amount` | total-return construction; declaration features if the dates are served | stored partial (check whether Yahoo serves declaration, record and pay before buying the Massive dividend history) |

## Macro, index and calendar series

### FRED and NY Fed

| Field | Availability time | History start | Retrieval cost | License note | Stored | Base features enabled | Status |
|---|---|---|---|---|---|---|---|
| economic series (macro layer) | `available_at` on every observation (populated on all 235,212 rows, counted 2026-11-09); historical reload as-released (phase 184 B8) still deferred | unverified | captured already (FRED key held) | captured under the capture law | yes (`economic_series_observation`) | regime inputs, macro conditioners | stored |

### Cboe and FRED (volatility)

| Field | Availability time | History start | Retrieval cost | License note | Stored | Base features enabled | Status |
|---|---|---|---|---|---|---|---|
| index and volatility series (VIX family, term structure) | end of session (unverified) | unverified | Cboe direct or FRED; the macro layer already holds FRED | licensing unverified | no (unverified whether the loaded FRED set covers VIX) | regime inputs | worth-capturing (verify coverage and terms before capture) |

### Exchange calendars

| Field | Availability time | History start | Retrieval cost | License note | Stored | Base features enabled | Status |
|---|---|---|---|---|---|---|---|
| index rebalances, option expiry calendar | calendar publication (unverified) | unverified | calendar kernel exists (seed table) | licensing unverified | partial (a calendar kernel exists; what it stores is unverified) | calendar primitives | worth-capturing (scope against the existing kernel first) |

## Microstructure and lending

### FINRA (direct)

| Field | Availability time | History start | Retrieval cost | License note | Stored | Base features enabled | Status |
|---|---|---|---|---|---|---|---|
| short volume | the publication date is the availability time, not the settlement date (seed table) | unverified | self-serve (unverified) | unverified | no | crowding, squeeze state | worth-capturing (verify publication schedule and terms before capture) |
| short interest | the publication date is the availability time (unverified) | unverified | self-serve (unverified) | unverified | no | crowding, squeeze state at the slower cadence | worth-capturing (verify before capture) |

## The diff script

`scripts/ops/ops_adjacency_diff.py` holds the same seed rows as a literal mapping and diffs them
against the stored columns it discovers from `information_schema` (schema `public`). It is
read-only: SELECTs only, connection forced read-only, nothing written. Run:

```
.venv/bin/python scripts/ops/ops_adjacency_diff.py
```

Output: a per-source table of servable versus stored counts, plus the not-stored list. The
mapping and this doc must move together; `tests/unit/test_ops_adjacency_diff.py` asserts every
script field appears in a table row here.

## Composition vocabulary: adopted by the lead, 2026-11-09 (amended to one code)

The worker proposal below suggested two codes. The lead adopted it amended: **one code,
`external`** (migration 584, applied 2026-11-09). Two reasons, recorded for the same-region rule:

1. **Name collision.** `calendar` already names a legacy `concept_registry` feature_group
   (`calendar primitive`'s **Not** note, todo 116) and `calendar primitive` itself is composition
   `base` (timestamp alone). One word, one meaning (glossary rule).
2. **The split was unsound.** A published calendar is an external observation with a publication
   date; reading the 2015 option-expiry calendar in a 2015 backtest requires the calendar
   published before that date. "Deterministic time" does not exempt it from availability-time
   discipline, so the admission gate checks `external` uniformly and no weaker category is seeded.

Adopted definition (migration 584): `external` = a feature computed from a dated external-source
observation joined to the name; every input carries its availability time. Existing `base` and
`interaction` rows are unchanged; nothing recomputes. `vocabulary_drift.py` reads the namespace,
so no audit change.

<details><summary>The original two-code proposal (superseded, kept for the record)</summary>

**Problem.** `composition` has exactly two codes (verified against `controlled_vocabulary`,
2026-11-09): `base` (computed from a name's own bars or the timestamp) and `interaction` (built
from other features). External-source features fit neither: a dated shares-outstanding value, a
FINRA short-volume ratio, an earnings-announcement window flag or a FRED macro series is
computed from data that is not the name's bars and not another feature. Forcing them into `base`
silently redefines the code; forcing them into `interaction` corrupts the grammar-depth contract
(todo 440).

The proposed second code `calendar` (computed from the timestamp and a published calendar) is
folded into `external` by the ruling above.

</details>

## Open items carried from the seed

- Alpaca quote fields, IBKR contract and history fields beyond bars: sources named in todo 603
  step 1, not yet seeded. Populate at the quarterly pass from the vendor schemas.
- Whether any base feature reads `borrow_availability_snapshots` (unverified).
- Whether the loaded FRED set already covers the VIX family (unverified).
