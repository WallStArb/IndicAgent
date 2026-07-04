# Trade Construction Layer — From Forecast to Position

**Version:** 1.0
**Status:** draft — design concept; PortfolioTrack's concrete half
**Priority:** high (weakness #5 from the 2026-07-01 council review: the layer is absent, and
its absence changes what "edge" means upstream)
**Milestone:** future — scoping trigger is Phase 142A's OOS gate, same as PortfolioTrack
**Last Updated:** 2026-07-01
**Tags:** trade-construction, portfolio, cross-sectional, long-short, sizing, cost, kelly

**Companion to:** `docs/ideas/edge-source-thesis.md` (thesis T3 is only testable through this
layer) and `docs/ideas/intel-15-measurement-engine.md`'s Cross-Sectional Rank IC addendum (T3's
falsification measurement, which must clear before this construction layer is warranted).
**Note (2026-07-03):** this doc's original companion, `intel-11-dual-system-discrete-vs-portfolio.md`,
was retired — see `docs/ideas/archive/intel-11-dual-system-discrete-vs-portfolio.md`. Per
`.planning/research/2026-07-03-intel10-11-fable-review.md` (F9), PortfolioTrack is not a track;
this doc's construction-layer content remains a v4.0 concern, gated on the addendum's falsification
result, not on a "PortfolioTrack" scoping event.

---

## The Core Point

A forecast is not a trade. The same per-bar conviction vector can be monetized at least four
structurally different ways, and they have *different edge requirements* — the construction
choice determines how much IC is enough:

| Construction | What it needs to win | IC bar | Beta exposure |
|---|---|---|---|
| Per-symbol directional (current implicit design) | Each symbol's signal beats that symbol's full vol + market moves | Highest | Full |
| Cross-sectional long-short (dollar-neutral) | Only the *ranking* across symbols has to be right | Lowest | ~Hedged |
| Directional with index hedge | Signal beats idiosyncratic vol only | Middle | Hedged per-position |
| Overlay tilts on a passive book | Conditional tilts beat their own turnover cost | Lowest, but capped upside | Deliberate |

Everything upstream (IC engine, ensemble, frames) is currently built for row 1 — the hardest
row. Phase 142B's stop/target/hold frames are per-symbol directional execution rules. Nothing
in the roadmap tests rows 2-4.

## Why Cross-Sectional Long-Short Is the Natural Fit for This Universe

- **58 correlated ETFs is a relative-value universe, not 58 independent directional bets**
  (effective breadth ~8-15; see feature-scoring-beyond-ic §4). Ranking within a correlated
  set is exactly what a cross-sectional portfolio monetizes and a directional book wastes.
- **Beta cancellation is free risk reduction.** Long the top decile of the ranking, short the
  bottom, dollar-neutral: the market factor nets out, so the P&L stream is the *spread* —
  driven by the forecast, not by whether SPY went up. The Sharpe of a hedged spread on weak
  IC routinely beats the Sharpe of unhedged directional trades on the same IC.
- **It changes the falsification story.** If per-symbol directional fails the cost hurdle
  (todo 030 Step 0) but the spread portfolio pays, the edge is real and relative (thesis T3).
  Without this layer, that outcome is indistinguishable from "no edge."
- **Costs differ:** a rebalanced spread portfolio trades *changes in the ranking*, not every
  signal — turnover control is a portfolio property, unavailable to independent per-symbol
  frames.

## Minimal Design (deliberately small — this is a v1 spec, not an optimizer)

Renaissance principle applied: no convex optimizer, no risk-model estimation, no borrow/
margin modeling in v1. Rank, bucket, weight, net, rebalance. Each step earns complexity later
through proof.

1. **Input:** per-bar calibrated conviction vector across the universe per tf — requires
   feature-scoring-beyond-ic 0c (calibration) so the vector is in return units. Uncalibrated
   z-scores can rank (enough for v1 spread construction) but cannot size.
2. **Ranking → buckets:** top-N / bottom-N by conviction (APR: `alpha.construction.n_legs`),
   within the symbol's validated regime_scope only.
3. **Weights:** v1 equal-weight per leg, vol-scaled per symbol (divide by trailing ATR/vol so
   one high-vol leg doesn't dominate the spread). Kelly-fraction scaling of gross exposure
   deferred until calibrated E[R] exists (the `alpha.*` Kelly APR keys already reserved).
4. **Netting:** dollar-neutral across legs per tf. Cross-tf netting (5m signal vs 1d signal
   on the same symbol) resolved by simple priority rule in v1 (APR:
   `alpha.construction.tf_priority`), learned later.
5. **Rebalance rule:** trade only ranking changes that clear a per-trade cost floor
   (todo 030's spread estimates) — turnover control as a first-class constraint, not an
   afterthought.
6. **Measurement:** the unit of account is the *portfolio*, not the trade. Daily spread P&L,
   net of modeled costs, vs. two benchmarks: flat, and the same construction with shuffled
   rankings (the construction-level null — a spread portfolio can show positive P&L from
   construction artifacts alone; the shuffled-ranking null catches that).

## What This Explicitly Defers

- Convex optimization / covariance-based risk models (v1 vol-scaling is the 80/20)
- Borrow cost / hard-to-borrow modeling (ETF universe is easy-to-borrow; revisit if universe
  expands)
- Capacity/market-impact modeling (irrelevant at this account size)
- Live execution — this layer is validated entirely in counterfactual/shadow mode first,
  same discipline as Phase 142B frames

## Validation Gates (same pattern as everything else)

1. **Shadow spread portfolio on the OOS window:** net-of-cost spread Sharpe > 0 at 95%
   bootstrap CI, and beats the shuffled-ranking null.
2. **Attribution honesty:** spread P&L must load on the forecast (rank-weighted return
   spread), not on a static factor tilt (e.g., permanently long low-vol sectors) — regress
   spread returns on static bucket membership; if a fixed membership explains most of it,
   the "forecast" is a factor exposure in disguise (edge thesis T4, cap expectations
   accordingly).
3. **Comparison to DiscreteTrack directional on the same features** — this comparison IS the
   T3 test from the edge-source thesis; record the verdict there.

## Sequencing

Blocked on Phase 142A (proven OOS ensemble IC — no point constructing portfolios from an
unproven forecast). Then this doc's v1 is deliberately buildable in 1-2 phases: construction
+ shadow measurement is queries and a batch service, not new infrastructure — it reads
`alpha_events`/`feature_vectors` and `forward_returns` like everything else.

## References

- `docs/ideas/archive/intel-11-dual-system-discrete-vs-portfolio.md` — retired strategic frame (historical only)
- `docs/ideas/intel-15-measurement-engine.md` — Cross-Sectional Rank IC addendum, T3's falsification gate
- `docs/ideas/edge-source-thesis.md` — thesis T3, which only this layer can test
- `.planning/todos/pending/030-cost-hurdle-apr-calibration.md` — Step 0 cost floors feed the
  rebalance rule and the net-of-cost measurement
- `docs/plans/2026-06-29-feature-scoring-beyond-ic.md` — 0c calibration (sizing prerequisite),
  §4 effective breadth (why relative-value fits this universe)
- ROADMAP.md Phase 142A (scoping trigger), Phase 142B (the per-symbol directional counterpart
  this doc complements, not replaces)
