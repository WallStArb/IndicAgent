---
status: pending
priority: P1
filed: 2026-09-25
source: adversarial review of docs/plans/2026-09-25-multi-timeframe-horizon-design.md (finding 4)
---

# No dividend history: daily targets and price-level features are price-only

## What

Equity bars are fetched as IBKR `TRADES` (`src/providers/ibkr.py::_hist_what_to_show`), which is
split-adjusted but not dividend-adjusted, and no table in the database holds dividends or
corporate actions. Every daily open-to-open target therefore carries the ex-dividend drop as a
negative return, and every price-level feature (52-week high distance, price percentile,
VWAP deviation) sees a high-yield name drift down in price terms.

## Why it matters

- Family 9 (anchoring, slow reversal): "far from the 52-week high predicts a lower return" can be
  produced by yield alone on high-dividend ETFs (HYG, TLT, utilities), since both the feature and
  the price-only residual return lean the same way. S1 keeps each name's drift
  (`src/intelligence/research/factors.py`), so it does not remove this.
- Family 2 (overnight versus intraday): ex-dividend drops land entirely in the overnight leg, so
  the overnight return is biased down for high-yield names.
- The intraday book is unaffected: its targets never cross a session.

## Done when

A point-in-time dividend history (ex-date, amount) is stored for the universe; S0 can emit a
total-return-adjusted open series for targets and kernels; a guard shows a synthetic high-yield
name with no alpha produces no family 9 signal. Until then, daily-clock books with price-level
members do not go to confirmation, and family 2 discloses the bias.

## Update 2026-09-25: what E16 covers

E16's timing statistic demeans returns by their causal expanding mean per symbol, so a steady
yield-driven price drift no longer enters the tested series through the static tilt. That covers
the static half only. Ex-dividend drops are lumpy (a few dates a year, known in advance), so a
predictor that reacts to price level (52-week distance, percentile, VWAP deviation) moves on
exactly those dates, and the drop lands in the next open-to-open return: a timing artifact the
demeaning does not remove. Family 2's overnight leg is unaffected by the demeaning. The done-when
condition above stands.

## Update 2026-09-26: dividend history stored (part 1 of 3)

Migration 376 and `services/dividend_event_writer.py` store dividends from two independent
sources with per-source coverage, and reconcile them:

- `yahoo`: declared cash dividends, full history (73,940 events over 932 active equities).
- `ibkr_adjusted_last_ratio`: the ex-date step in IBKR's ADJUSTED_LAST / TRADES daily ratio.
  Rounding noise has a hard bound (0.005/close on each of two days), so no false events
  (unit-tested at the exact bound on $4, $75 and $600 walks).

Two sources because each has holes the other fills and neither can see its own: IBKR lacks SPY's
2001-2005 dividends and five HYG months; Yahoo lacks HYG's November 2012 distribution. Where
both report an event their yields agree to a median 0.3-1.2% relative. A dividend reported on
different dates by the two sources rolls the symbol back (the reader view would count it twice).

Reader surface: `dividend_events_reconciled` (per-source yields plus a default Yahoo-first
`dividend_yield`) and `dividend_event_coverage` (outside Yahoo's span: unknown, never zero). Use
`amount / prev_close` only; amounts are in the split units of the day they were derived.

Remaining for done-when (updated below): the S0 consumer and the nightly chain.

## Update 2026-09-26: S0 total-return prices (part 2 of 3)

A spec opts in with `panel.total_return: {suspect_yield: <x>}` (optional, left out of the
canonical form when unset: family 1 and book_v1 keep their hashes). S0 then captures a
per-session dividend grid into the content-hashed snapshot, and the runner applies
`research/dividends.py::total_return` after the members-universe filter and before the
session-legs transform:

- Prices are multiplied by F(s) = product of 1 / (1 - y) over ex-dates up to s (the CRSP and
  IBKR convention; a price drop of exactly the dividend is a zero return). F is constant within
  a session and reads only past ex-dates, so intraday targets are unchanged and nothing looks
  ahead; daily targets, daily bar returns, family 2's overnight leg and price levels are all
  corrected at the root.
- Outside Yahoo coverage prices are NaN. An event above suspect_yield that one source alone
  reports, or a session yield of 1 or more, splits the symbol into `<symbol>~<k>` from that
  ex-date (no return or window spans it; nothing earlier moves). Live: MO splits at 2007-04-02
  (Kraft) and 2008-03-31 (Philip Morris International).
- Family 9 guard: `tests/unit/research/test_dividends.py` shows a price-level feature on the
  corrected panel equals the feature of the zero-alpha total-return walk for high-yield names.
- Snapshots without dividends are byte-identical; repro_frozen is bit-identical.

Remaining: chain `dividend_event_writer.py --sources yahoo` into the nightly job (new ex-dates
daily; IBKR cross-check weekly). The first full IBKR pass hits IBKR soft pacing on 25-year
daily requests (pacing errors, retry backoff); a 20-year window is one request per series.
