# Front-weighted put ladder - Idea

**Status:** Idea. Not planned, never tested, no chain saved. One observed book, not a
verdict. Not a family on the S1 residual panel.
**Author:** interactive session, 2026-10-05. The inventory and greeks below were read off a
single OptionNet risk-chart screenshot. The owner corrected two strikes the same day: the
14 Oct long is 7350, and the 15 Oct short is 7475.
**Origin:** Owner, 2026-10-05. An SPX put package whose constant-vol price slice pays a
capped credit if the index rallies and a much larger amount if it drops 1–2% before the
front expiry.

---

## The structure

Net contracts are flat, and the average long strike (7487) is above the average short
strike (7444). That is not one reverse diagonal. A reverse diagonal is long one nearer,
higher put and short one later, lower put, in equal size. This book is a ladder: two
same-strike calendars, each short twice the back leg, a strip of front longs with no short
at their strike, and a wing that is short twice the size of the longs underneath it.

Counted in 25-lot units:

| Piece | Long | Short | What it is |
|---|---|---|---|
| 7500 | 25 × 13 Oct | 50 × 14 Oct | 1:2 calendar, one day |
| 7475 | 25 × 14 Oct | 50 × 15 Oct | 1:2 calendar, one day |
| Near puts | 25 × 13 Oct 7650, 25 × 14 Oct 7660 | — | outright longs, about 30 delta |
| Belly | 25 × 13 Oct 7450, 25 × 14 Oct 7450 | — | outright longs, about 16 delta |
| Wing | 25 × 13 Oct 7360, 25 × 14 Oct 7350 | 100 × 15 Oct 7400 | 50 long against 100 short, short strike 50–60 points higher, one to two days later |

The 15 Oct 7400 is half of every short contract in the book. The two calendars are pure
term: same strike, long the front, short twice the back. The 7650 and 7660 longs are the
convexity that pays on a small drop. The 7400 short, oversized and later, is the financing
and the tail.

The chart's credit is thin. The right-hand plateau near +$19,700 is about one index point
per contract on a 200-lot book. The interesting part of the picture is the convexity, not
a fat premium.

While every long is still alive, a crash does not become an unlimited loss. Two hundred
puts against two hundred puts, with the longs struck higher, has a finite intrinsic gap:
about 8,625 contract-points, about $860k, if every strike were deep in the money at the
same moment. The expiries are not the same moment, so that number is a bound, not a
settlement. It is why the left side of the chart rises.

The package is closed before any long expires. Owner, 2026-10-05. The first longs settle
on 13 Oct, and they are 100 of the 200, so the deadline is the 13 Oct settlement, not the
15th. Missing it leaves 100 longs against 200 shorts for the 14 Oct session, and after the
14 Oct legs settle, including the 50-lot 7500 short, what remains is short 150 on 15 Oct:
100 of the 7400 and 50 of the 7475. That book is the cost of a missed exit. It is not the
trade.

SPX and SPXW options are European and cash-settled, so there is no early assignment. The
forward embeds the dividend yield. That is a pricing input.

## The motivating book

Projection date on the chart: **2026-10-02**. Spot **7721.46**. Vol adjust **0**. All legs
are puts. Per-line deltas on the chart are contract deltas in points (a print of −28.61 is
about −0.29), not position deltas.

| Qty | Expiry | Strike | Contract delta |
|---|---|---|---|
| +25 | 13 Oct | 7650 | −27.29 |
| +25 | 13 Oct | 7500 | −20.50 |
| +25 | 13 Oct | 7450 | −15.31 |
| +25 | 13 Oct | 7360 | −8.65 |
| +25 | 14 Oct | 7660 | −28.61 |
| +25 | 14 Oct | 7475 | −19.20 |
| +25 | 14 Oct | 7450 | −16.79 |
| +25 | 14 Oct | 7350 | −9.93 |
| −50 | 14 Oct | 7500 | −21.92 |
| −100 | 15 Oct | 7400 | −13.87 |
| −50 | 15 Oct | 7475 | −20.18 |

Realized P&L on the chart: −200.

Net contracts: 200 long, 200 short. By expiry: **+100 on 13 Oct, +50 on 14 Oct, −150 on
15 Oct**. The decomposition is in the structure section above.

Chart greeks at the spot, vol adjust 0:

| | P&L | Delta | Gamma | Theta | Vega |
|---|---|---|---|---|---|
| Spot 7721 | −1,250 | +25.62 | +1.35 | +1,360 | −3,716 |
| About −1% | +216,213 | −793 | −1.85 | +6,701 | −15,817 |
| About −2% | +283,665 | −540 | −2.86 | −8,197 | −13,951 |

The right-hand side of the same slice rises from the spot mark and flattens near **+19,700**.
That is the T+0 value of the package with the puts marked toward zero, volatility unchanged.
It is the chart's credit, not a fill.

Read as a price slice, the book is slightly long delta at the spot, collects about $1,360 of
theta per day there, and is short vega throughout. Gamma is positive near the spot and
negative once price is into the short strikes. The fan on the left of the chart is the
front longs lighting up. The flat line on the right is the credit if the index rallies.

## What that chart does not show

Vol adjust was 0. Vega at the spot is about −$3,700 per vol point, and about −$16,000 per
vol point once spot is 1% lower. A down day in the index usually arrives with higher implied
vol, and that marks the short back-month puts up. The constant-vol slice is the upper bound
on the crash payoff, not the payoff.

The chart's lines run from 2 Oct through 13 Oct, which is the hold. The trade is over
before the next session.

One package on one afternoon is an observation. It is not a frequency, not a costed
expectancy, and not a license to search a grid and keep the winner.

## Margin

This book is a portfolio-margin trade. Owner, 2026-10-05. Strategy margin does not
recognize a long that expires before the short, so the 15 Oct puts are naked. At 7721 the
Cboe broad-based haircut, on top of the premium, is about **$8.37 million** on the 100-lot
7400 and **$4.56 million** on the 50-lot 7475, **$12.9 million** together. The $20k credit
does not pay that. The 200-lot size only fits in an account whose margin is the portfolio
scan.

The OCC customer scan for a broad-based index is ten prices from −8% to +6%, with the
implied-volatility curve held unchanged. While all 200 longs are alive, every one of those
prices is a gain versus the current mark. The −$1,250 at the spot is the mark against the
cost basis, and it is the low point of the slice, so the further loss inside the scan is
about zero. That is the requirement on the way in and on each day through the 13 Oct close,
when those longs are still in the position. A house overlay that also shocks volatility
(IBKR stresses broad-index implied vol by ±75%) is a different, larger number. The book is
short about $3,700 of vega per point at the spot and about $16,000 per point near −1%.

The exit keeps it that way. The package comes off before the 13 Oct settlement, so the
longs are still in the scanner for the whole hold. The requirement jumps only if that
exit is missed: after the 13th the book is net short 100, and after the 14th it is short
150 into the 15th, where a −8% print from 7721 (about 7104) makes those 15 Oct puts
intrinsic by about **$4.8 million** before whatever premium is left in them. That number
is the penalty for still being in the position on the morning the longs cash-settle.

## What to price first

Price this inventory. A cleaned-up 1:1 diagonal, long about 30 delta and short about 15
delta in equal size, is a different trade. Matched size locks the strike gap once both
puts are in the money. This book is short twice the wing, and those longs expire first. A
search that only keeps 1:1 diagonals will draw the flattering chart and will not contain
the short that makes the book a question.

Once a chain exists, mark these eleven legs. No grid.

- Shocks: spot +2%, 0, −1%, −2%, −4%. Unchanged vol, and a second arm with **+5 vol
  points on the three down shocks**. Five points is declared, not searched.
- The same shocks on the book after the 13 Oct longs are removed, and again after the
  14 Oct legs are removed. These two are the missed exit, priced once so the deadline has
  a number. They are not held.
- The same shocks on the two calendars alone (the 7500 1:2 and the 7475 1:2) and on the
  rest of the book alone (the 7650, 7660, 7450, 7360, and 7350 longs, and the 7400 short).
- The portfolio-margin requirement (ten prices from −8% to +6%, implied vol unchanged, as
  in the OCC customer scan) on the intact book, on the book after the 13 Oct longs are
  removed, and on the 15 Oct shorts alone. The P&L can be fine on a slice where the
  requirement is not.

The credit is about one point a contract, so a rule of the form "the down move pays
several times the credit" passes on its own and tests nothing. The held trade is the
intact book, closed before the 13 Oct settlement. The number that matters is its −1%
value under the vol shock, at a mark that buys the shorts back on the ask and sells the
longs on the bid. The book with the 13 Oct longs removed is written down next to it as
the cost of missing that close.

Neighboring ladders are a later look. They wait until this one has been priced and written
down.

## Where it sits

This is a single-underlying options package. S1 residualizes equity-panel returns and has
no option in it. Family 8 (options expiry flows: pinning and release) asks whether the
underlying drifts around expiry. This idea asks what the option package itself is worth.
The implied-borrow idea (`docs/ideas/signal-implied-borrow-cost-from-listed-derivatives.md`)
needs a few near-the-money quotes per name. This one needs a band of SPX puts across two
near expiries. Same missing asset class, different extract.

Nothing in the repo prices an option. `instruments.contract_details->>'asset_class'` is
equity, futures, or fx. A full surface, GEX, and a derivatives platform are a different
and larger project. This idea needs none of that to take its next step.

## Next step: save an SPX chain

A snapshot is enough to price this inventory. A history is a separate decision, taken only
after that pricing is written down.

The snapshot has to include the 13 Oct, 14 Oct, and 15 Oct puts from 7350 through 7660,
plus the surrounding strikes in that band so a vol shock is read off the surface rather
than off one quote. Per quote: timestamp, expiry, strike, right, bid, ask, multiplier, and
the vendor's implied vol, delta, and open interest when they come with the quote. Quote
time is the availability time. A close-only row with no bid and ask cannot separate the
calendars from the wing.

IBKR is already the history path (`src/providers/ibkr.py`). Any new request belongs there.
Scope the request to this band. A full chain backfill is a different project and is not
required to price one cell.

## Open questions

1. Whether every leg is SPXW. The strikes are confirmed.
2. The book already splits term from strike. The 7500 and 7475 pieces are 1:2 calendars.
   The 7650 and 7660 longs against the 7400 short are the tilt and the ratio. Marking them
   separately answers which piece is the credit and which piece is the convexity.
3. Whether +5 vol points is a fair downside shock for a 1% SPX drop over a few days, or
   whether the first saved chain's own recent down days should set that number before the
   cell is scored. Set it before looking at the cell's P&L either way.
4. Snapshot versus history. The snapshot answers "does this shape survive a vol shock at
   these prices." Only a history can say how often the credit was there and what the
   package did along the path.
