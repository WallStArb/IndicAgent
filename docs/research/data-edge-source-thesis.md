# Edge Source Thesis — Where Does Our Edge Come From?

**Version:** 1.0
**Status:** draft — standing document; every claim here is falsifiable and must be revisited
as evidence lands
**Priority:** high (the least-examined assumption in the tree; nothing above Phase 142A fully
makes sense until this doc has an answer)
**Milestone:** standing — not tied to a phase
**Last Updated:** 2026-07-01
**Tags:** edge, thesis, counterparty, renaissance, falsifiable, first-principles

---

## The Question Nobody Has Answered

The entire v3.0 stack — Feature Factory, IC engine, ensemble, frames — assumes edge exists
in this feature × universe × horizon combination and pours rigor into *measuring* it. No
document states what the edge *is*: a falsifiable claim about **who is on the other side of
the trade and why they are systematically wrong**.

Every durable trading edge is one of a small number of things:
1. **Information** someone else doesn't have (unique data, faster data, better-cleaned data)
2. **Processing** someone else can't do (better models on the same data)
3. **A counterparty constraint** — someone must trade for non-price reasons (index rebalance,
   fund flows, hedging mandates, tax, margin calls) and pays for immediacy
4. **A behavioral bias** stable enough to persist after being published
5. **A risk premium** — compensation for bearing a risk others won't (this is beta wearing a
   costume, and it's fine, but it should be named as such, not called alpha)

Renaissance's actual moat was overwhelmingly #1 and #2 at a time when almost nobody else did
either — data nobody else had cleaned, on instruments nobody else priced carefully. It was
never "better statistical validation of features everyone can compute."

## The Uncomfortable Facts About Our Setup

Stated plainly so they can be argued with, not glossed:

- **The features are public.** All 54 are OHLCV-derived quantities (momentum z-scores, VWAP
  deviation, ATR, calendar position) computable by anyone with a market data subscription.
  Every systematic shop has tested them.
- **The universe is the most efficient corner of the market.** 58 of the most liquid,
  most-studied ETFs on earth. SPY's order book is the most competitive pricing environment
  in existence.
- **The horizons are heavily mined.** 5m-1d is exactly where institutional stat-arb operates.
- **The early evidence is consistent with the skeptical read.** Top qualifying features are
  calendar effects (`quarter_position`, `days_to_month_end`, `dow_sin`) and macro proxies
  (`yield_slope_z`), ICs 0.02-0.08 gross. Calendar anomalies are the most published, most
  arbitraged effects in the literature.

None of this proves there is no edge. It proves the *default hypothesis must be no edge*,
and the burden of proof sits on every positive result — which is exactly the posture the
gate stack (FDR, shrinkage, OOS, cost hurdle) implements. This doc's job is to name what a
surviving result would actually *be*.

## Candidate Edge Theses (each falsifiable)

### T1 — Small-scale immediacy provision (counterparty: constrained flow)
At this account size (retail, no capacity pressure), the system can take the other side of
flows too small for institutions to bother with: end-of-day rebalance pressure in
lower-liquidity sector ETFs, overnight-gap mean reversion where market makers widen out.
**Why we might win:** capacity constraints don't bind at this size; institutions leave
crumbs below their minimum ticket. **Falsification:** the surviving cells should
concentrate in the less-liquid half of the universe and around session boundaries; if edge
concentrates in SPY/QQQ mid-session, T1 is wrong.

### T2 — Regime-conditional persistence (counterparty: unconditional models)
Features with zero pooled IC but real conditional IC (the whole stratification premise).
Participants running unconditional models mis-price bars in minority regimes.
**Why we might win:** most simple systematic flows are not regime-conditioned; conditioning
is our one genuine structural bet. **Falsification:** regime-stratified IC must materially
exceed pooled IC for the same features OOS (not just in-sample, where stratification
mechanically inflates cell significance), and the regime labels themselves must pass the
026 validation. If conditional ≈ pooled OOS, T2 is dead and most of the stratification
machinery is measurement theater.

### T3 — Cross-sectional relative mispricing (counterparty: single-name flows)
Individual ETFs get pushed off fair relative value by idiosyncratic flows (sector rotation,
thematic retail); the *ranking* across 58 correlated instruments mean-reverts even when no
single instrument is predictable directionally. **Why we might win:** relative-value noise
cancellation is statistically much easier than directional prediction; this is the
lowest-IC-requirement thesis on the list. **Falsification:** cross-sectional long-short
spread portfolios built from feature rankings must show positive net return where per-symbol
directional trades on the same features don't. Requires the cross-sectional rank IC measurement
mode (`docs/research/intel-15-measurement-engine.md`, "Addendum: Cross-Sectional Rank IC") to even
test. If the spread portfolio is no better than directional, T3 is dead.

### T4 — Horizon arbitrage at 1h/1d (counterparty: nobody — risk premium)
The honest fallback: at longer horizons with low turnover, small conditional tilts
(vol-conditioned momentum, flight-to-quality) earn modest risk-adjusted returns that are
partly repackaged risk premia. **Why we might win:** we don't need to win against anyone;
we need to harvest systematically without behavioral errors. **Falsification:** returns
should survive but shrink substantially when regressed against standard factor exposures.
This thesis caps expectations at "good systematic beta," which is a legitimate but
different product.

### What is deliberately NOT on this list
"Our features are better" (they are public) and "our ML is better" (we run a linear
IC-weighted combiner; the institutions we'd be beating run more). Any future thesis of type
#2 (processing) must name the specific processing advantage — e.g., regime-conditional
structure (T2) or the AnalogEngine's non-parametric retrieval — not assert generic model
superiority.

## Breadth Is the Binding Constraint (added 2026-07-01, Simons-lens review)

Whatever thesis survives, the arithmetic above it is fixed: IR ≈ IC × √(effective breadth).
This universe has effective breadth ~8-15 (58 correlated ETFs; Phase 152's 79 barely moves it —
more sector funds are more of the same bets). At IC ≈ 0.03 and breadth 10, there is almost
nothing to harvest; at breadth 300, the *same IC* is a business. Medallion's expansion to
higher frequency and thousands of instruments was this arithmetic, not bigger edges. The
concrete long-term move this pipeline is well-positioned for: liquid single-name equities
(e.g., S&P 500 constituents) for cross-sectional work — the pipeline is symbol-agnostic and
the trade-construction layer is exactly what monetizes wide universes.

**Sequencing decision (operator, 2026-07-01):** universe expansion waits until the end-to-end
system is proven — pipeline through P&L, validated through the canonical simulator
(`docs/research/canonical-simulator.md`). Multiplying the universe before the path is trusted
multiplies unvalidated machinery, not returns. Breadth is the biggest lever; it is deliberately
pulled last.

## What This Doc Demands From the Roadmap

1. **Todo 030's external cost floor runs first — DONE 2026-07-01, verdict recorded.**
   5m fast/mid and 15m fast are net-negative-to-marginal against realistic spread (0.26,
   0.84, 0.55 bps gross vs 1-10bp cost floors, on unshrunk IC — the real numbers are worse).
   1h/1d and the longer-lookahead 5m/15m cells clear comfortably. Full table:
   `.planning/todos/pending/030-cost-hurdle-apr-calibration.md`. **This kills or badly
   wounds T1 (immediacy provision) as a short-horizon thesis** — if the crumbs institutions
   leave below their minimum ticket can't clear spread either, T1 only survives at longer
   holds, which changes what "small-scale immediacy" means. T2/T3/T4 are horizon-agnostic
   and unaffected in direction, though T3 (cross-sectional) may specifically rescue some of
   the dead directional cells — a spread portfolio's cost dynamics differ from a directional
   trade's (see `docs/research/trade-construction-layer.md`).
2. **Every future analysis report tags which thesis its result supports or damages.** A
   qualifying feature is not evidence of edge; it is evidence *for a specific thesis* or it
   is unexplained (and unexplained results get the skeptical prior).
3. **T3 requires the PortfolioTrack to be testable at all** — this is the strongest
   argument for scoping intel-11's PortfolioTrack, stronger than "firms do it."
4. **If, after 142A OOS + cost hurdle, no thesis has supporting evidence** — the honest
   conclusion is T4-only: reframe the system as systematic conditional risk-premium
   harvesting at 1h/1d, cut the 5m/15m compute, and stop calling it alpha. That outcome is
   a success of the process, not a failure of the project.

## References

- `docs/intelligence/intelligence-alphaengine.md` — the epistemology this doc completes:
  "the data discovers confluence" answers HOW to find edge; this doc asks WHY edge should
  exist at all
- `docs/research/intel-15-measurement-engine.md` — Cross-Sectional Rank IC addendum (T3's test
  vehicle; retired from `intel-11`, see `docs/research/archive/intel-11-dual-system-discrete-vs-portfolio.md`)
- `.planning/todos/pending/030-cost-hurdle-apr-calibration.md` — the first falsification
- `docs/plans/2026-06-29-feature-scoring-beyond-ic.md` — marginal contribution / shrinkage
  (the machinery that keeps thesis evidence honest)
