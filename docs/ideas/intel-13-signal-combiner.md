# Signal Combiner — Many Weak Edges Into One Independent-Conviction View

**Version:** 1.0
**Status:** under-review
**Priority:** high
**Last Updated:** 2026-06-01
**Tags:** signal-combination, independent-conviction, effective-n, ic-weighting, decorrelation, shrinkage, vil, intel-10, intel-11, intel-12

---

## What This Combines (read this first)

A note on scope, because the obvious word for this is wrong. This is **not** a portfolio of capital positions — this system produces *intelligence*, not capital allocations. It generates scored signals; its only live lever is I7 raise/suppress; there is no position-sizing or capital layer.

What intel-13 combines is the **live set of scored signal-edges** — each (symbol × TF × setup) Score Object that is active right now. The output is a single **independent-conviction view**: relative conviction weights across those live edges that account for how much they overlap. Not dollar weights. If a capital/sizing layer is ever built, it becomes a downstream *consumer* of this view — but that is explicitly not this layer.

So whenever this doc says "weight" or "allocation," read **conviction weight across live signal-edges**, never capital.

---

## Foundation

This document is the capstone of the Vector Intelligence stack. It introduces no new substrate — it consumes three layers that already exist:

- **intel-10** measures *independence* — effective-N and the pairwise correlation of live edges
- **intel-11** measures *trust* — the IC and IC Sharpe of every predictor
- **intel-12** measures *each edge in isolation* — the Score Object: E[R], conviction, distribution, per (symbol × TF × setup)

intel-13 answers the question those three set up but none of them asks: **across all live edges at once, accounting for trust and overlap together, how much independent conviction does the set actually carry, and which edges contribute genuinely new information versus duplicate it?**

Do not read this as standalone. Without intel-10/11/12 beneath it, there is nothing to combine.

> **This is the terminal idea in the stack — recorded now, built last.** It earns implementation only after the layers below it produce IC-validated outputs *and* a consumer exists that does something with a combined conviction. As an idea it belongs on record (it is where the edge would live); as a build it is dead last, gated behind everything below being real. Sequencing it ahead of its inputs would be building the roof before the walls.

---

## What Simons Would See First

Medallion's edge was never a single brilliant signal. It was thousands of weak signals — each with an IC so small it would look like noise in isolation — combined across their statistical *independence*. The law of large numbers does the work: many small, uncorrelated edges sum to one large, stable conviction. The hard part, and the real intellectual property, is the **combination**: weight each edge by how much you trust it, penalize edges that are the same bet wearing two hats, and judge the whole set by how many genuinely independent reads it actually contains.

This system produces the raw materials and then stops at the threshold of the most important step. intel-12 scores each edge beautifully and in isolation; nothing combines them. We would count 18 live signals as 18 independent reads when intel-10's whole thesis — now repeated one level up — is that they might be 4. The aggregate conviction is inflated by exactly the redundancy nobody is measuring across the live set.

intel-13 is the missing layer. It is where the firm's actual edge would live.

---

## The Question Intel-13 Answers

**Of all the signal-edges live at this bar, weighted by how much history says to trust each and penalized for how much they overlap, what is the independent-conviction across the set — and which edges carry new information versus echo one already counted?**

Not "which signal is best" (that is intel-12, per-edge, in isolation). The combination question is about the set as a whole: two top-ranked signals may be the same underlying bet, and counting both as conviction is the inflation this layer exists to remove.

---

## What Simons Would Demand

**1. Never trust a raw expected return. Shrink it.**
A raw E[R] estimate is mostly estimation error. Every edge's expected return is shrunk toward zero in proportion to its IC Sharpe — a low-trust edge is pulled to ~zero weight before it can do damage. This is the James-Stein / Bayesian discipline: the input to combination is the *shrunk* read, never the raw one. Most of the combiner's robustness comes from this single rule.

**2. An edge's value is its marginal contribution, not its standalone strength.**
A live edge that correlates 0.9 with one already counted adds almost nothing — it is the same bet twice. Each edge is weighted by what it adds *after* accounting for everything already in the set, using the correlation fabric from VIL (`similarity_pairs`, signal-level). This is the live-set expression of intel-10's whole thesis: independence, not count.

**3. Aggregate conviction is bounded by effective-N, not edge count.**
Eighteen live signals at effective-N 4 carry four independent reads, not eighteen. The aggregate conviction of the set scales with effective-N (the independence it actually has), never with how many signals happen to be firing. This is the single most important honesty gate, and intel-10 already computes the number — at the signal level (see intel-10's effective-N-everywhere extension).

**4. Reads must be net of cost.**
A gross edge that evaporates after slippage is not an edge. Expected returns entering the combiner are net of modeled transaction cost (see intel-14's cost-aware net scoring). At the short horizons this system targets, cost is often larger than the edge — ignoring it is self-deception.

**5. Don't churn the view.**
The combined view drifts every bar. If anything downstream ever acts on it, acting on every drift incurs cost that destroys the edge. The combiner is hysteretic: it holds the current view until the change justifies the cost of moving. Stability is a feature, not laziness.

**6. Avoid naive mean-variance optimization — it amplifies estimation error.**
Inverting an estimated covariance matrix to maximize the combined Sharpe is famously unstable: it loads maximally on whichever edges have the noisiest inputs. Simons would reject it as written. The combiner favors a **robust** construction — greedy decorrelation (Gram-Schmidt-style: take the strongest edge, residualize the rest against it, repeat) or inverse-correlation weighting — which captures "don't double-count correlated bets" without inverting a noisy matrix.

**7. The combiner must prove it beats equal-weight — or be deleted.**
This is the discipline that outranks the rest. The combined read is *itself a predictor*, so it is accountable to the same IC machinery as everything else (intel-11). Measure the IC Sharpe of the decorrelated-combined conviction against the naive equal-weight aggregate, out-of-sample. If the elaborate combination does not beat equal-weight, it is complexity for nothing and gets cut. "Decorrelation is principled, therefore good" is not an argument Simons would accept — only the out-of-sample IC is. The combiner registers as a predictor in the IC Factory like any other.

**8. Correlation that is stale in stress is worse than no correlation.**
Decorrelation leans on the correlation matrix — but correlations spike toward 1 in stress regimes ("everything correlates in a crash"). A weekly matrix shows a healthy effective-N right up until a regime break collapses it, and would not know until the next batch — understating redundancy at the exact moment it matters most. The combiner therefore needs **regime-conditional or fast-updating correlation**, not the static weekly snapshot. This is the most important refinement over a naive version.

**9. Signal-level correlation is data-starved — gate it.**
Signals are far sparser than plugin outputs, so signal-pair correlations are estimated from few co-occurrences and are noisy. The combiner inherits that fragility. Trust a pair's correlation only past a minimum co-occurrence count (inherit intel-10's `co_event_count` discipline); below it, treat the pair as independent rather than guessing.

**10. Observational until explicitly wired. Shadow-first.**
intel-13 produces a *view*, not an action. The live system's only existing lever is I7 raise/suppress. The combined independent-conviction view is written to a research surface and may inform that lever or feed an eventual sizing consumer — but it takes no action on its own. No live consumer until one is deliberately wired.

---

## The Combination Pipeline

One pass over the live edge set, fed by the three layers below. No new retrieval.

```
Live edges  ── all current Score Objects (symbol × TF × setup), from intel-12
        │
        ▼
   Shrink ──── read_shrunk = E[R]_net · f(IC_Sharpe)      # trust-discount, toward zero
   (intel-11)  low-trust edges pulled to ~0 before they count
        │
        ▼
   Decorrelate ── greedy residualization against the live correlation matrix
   (intel-10)     (similarity_pairs, signal-level): take the strongest edge,
                  residualize the rest against it, repeat. Correlated edges
                  share one weight, not two.
        │
        ▼
   Bound ────── aggregate conviction capped by effective-N of the live set
   (intel-10)   4 independent reads → conviction of 4, not 18
        │
        ▼
   Hysteresis ── hold current view unless Δ exceeds the change-cost threshold
        │
        ▼
   Independent-conviction view ── per-edge conviction weight + set-level
                                  diagnostics (effective-N, concentration,
                                  marginal contribution of each edge) →
                                  research surface
```

The diagnostics matter as much as the weights. "You think you have 18 reads; you have 4" is the line that prevents over-confidence in a redundant set.

---

## What the View Looks Like

```
Live set — 2026-06-01 14:32:00
─────────────────────────────────────────────
Live edges:        18 candidate (symbol × TF × setup)
Effective-N:        4.2   ← genuine independent reads
Aggregate conviction: scaled to 4.2 reads (not 18)
Concentration:      top edge 31% of the conviction

Top contributors (IC-shrunk, decorrelated):
  ES.5m breakout      0.31   [E[R]_net +0.28R, IC-Sharpe 0.71, marginal +0.18]
  NQ.1m reclaim       0.19   [E[R]_net +0.22R, IC-Sharpe 0.55, marginal +0.12]
  ES.1m pullback      0.04   [corr 0.86 with ES.5m breakout → residualized down]
  ...
Redundant-by-overlap: 6 edges contribute ~0 (echo an already-counted read)
─────────────────────────────────────────────
Note: observational. Feeds research / the I7 lever. Takes no action itself.
```

The `marginal` column is the Renaissance-honest number: an edge's value *after* the set, not in isolation. `ES.1m pullback` looks strong standalone but is 0.86-correlated with an already-counted edge, so its marginal contribution — and its weight — collapse.

---

## Cadence and Compute

| Step | Cadence | Cost |
|---|---|---|
| Shrink + decorrelate + bound | per-bar (live set) | trivial — operates on ~dozens of live edges, not history |
| IC Sharpe weights | weekly (intel-11) | batch, off the hot path |
| Live correlation matrix | weekly (intel-10) | batch, off the hot path |
| View write | per-bar | one research-surface row |

The combiner is *live* (it concerns the current set) but *cheap* (it works on the handful of live edges, never on historical data). Its expensive inputs — IC and correlation — are pre-computed weekly by the layers below. This is the efficiency payoff of the layered design: the capstone adds almost no marginal compute.

---

## Separation of Concerns

```
intel-10 (independence)  ┐
intel-11 (trust)         ├──►  intel-13 (combine → independent-conviction view)  ──►  research / I7 lever / eventual sizing
intel-12 (per-edge score)┘
```

intel-13 measures nothing and scores nothing — it *combines* what the three layers below already measured and scored. It owns the combined view, the shrink/decorrelate/bound logic, and the set-level diagnostics. It owns no embeddings, no IC computation, no retrieval.

---

## What This Is Not

- **Not a capital portfolio.** It combines scored signal-edges into independent conviction, not money into positions. There is no sizing layer; if one is built, it consumes this view.
- **Not an executor.** It produces a view, not actions. Shadow-first; the live lever remains I7 raise/suppress.
- **Not naive Markowitz.** No inversion of an estimated covariance matrix. Robust construction by design — Simons would not tolerate an estimation-error amplifier.
- **Not a signal generator.** It combines existing edges; it never creates new ones.
- **Not a replacement for intel-12.** intel-12 scores each edge in isolation; intel-13 combines the set and removes cross-edge redundancy. Different questions — per-edge versus the set as a whole.

---

## Relationship to Existing Work

| Component | Relationship |
|---|---|
| `intel-12` (Scoring Engine) | Direct input. Each live Score Object is a candidate edge. intel-13 is intel-12's set-level consumer — it adds the cross-edge decorrelation intel-12 deliberately does not do. |
| `intel-11` (IC Factory) | Supplies the IC Sharpe used for shrinkage — how hard to pull each edge toward zero. |
| `intel-10` (Correlation) | Supplies signal-level effective-N (conviction bound) and the correlation matrix (decorrelation). intel-13 is the live-set expression of intel-10's independence thesis. |
| `intel-14` (cost-aware net scoring) | Supplies E[R] net of modeled cost — the input the combiner shrinks and combines. |
| `signal_ledger` | The live edge set derives from active signals; R-multiple convention shared throughout. |

---

## Open Questions

_Structure is designed from principle above; these constants come from evidence, not guessing. The combiner runs shadow-only until they are calibrated._

- **Combination method:** greedy decorrelation vs shrinkage-Markowitz vs inverse-correlation weighting? Start with greedy IC-shrunk decorrelation (most robust, no matrix inversion); validate against the others on accumulated history.
- **Shrinkage intensity:** the form of `f(IC_Sharpe)` — how aggressively low-trust edges are pulled to zero. Linear, convex, threshold?
- **Conviction-vs-effective-N function:** linear in effective-N, or concave (diminishing aggregate conviction as the set de-diversifies)?
- **Hysteresis:** what Δ (relative to modeled cost) justifies moving the view — only relevant once a downstream consumer acts on it?
- **Correlation freshness (the sharp one):** the weekly correlation matrix is stale in stress, when redundancy spikes and effective-N collapses. Regime-conditional correlation, a fast-updating estimate, or a stress-multiplier on the weekly snapshot — which, and how fast?
- **Regime-conditioning of weights:** separately from the correlation matrix, should the combination weights themselves be regime-dependent (an edge's marginal value may differ trending vs ranging)?
- **Validation baseline:** the combiner is registered as a predictor and must beat the equal-weight aggregate by IC Sharpe out-of-sample. What margin over baseline justifies keeping the added complexity?

---

## Alternatives Considered

**"Portfolio" framing (rejected).** The first draft of this doc called itself a Portfolio Combiner and spoke of allocating capital across positions. Rejected: this system has no capital or position-sizing layer — it produces intelligence. The honest object is a *set of scored signal-edges*, and the honest output is *independent conviction*, not dollar weights. Capital allocation, if ever built, is a downstream consumer of this view. The word "portfolio" imported a frame the system does not have.

**Full mean-variance optimization (rejected as the default).** Maximizing the combined Sharpe by inverting the edge covariance matrix loads maximally on estimation error — famously unstable, over-concentrating on whichever edges have the noisiest inputs. The robust constructions (greedy decorrelation, inverse-correlation) sacrifice theoretical optimality for stability, the correct trade when inputs are noisy. Shrinkage-Markowitz (Ledoit-Wolf) remains a candidate to evaluate later; it is not the starting point.

**Equal-weight the live edges (rejected).** Ignores both trust and overlap — counts correlated edges as independent (the exact inflation this stack exists to prevent) and gives a noise-edge the same weight as a validated one. Equal-weight is the null hypothesis the combiner must beat, not the design.

---

## Principles Alignment

| Principle | How intel-13 satisfies it |
|---|---|
| **Modularity** | One job: combine. No measuring, scoring, or retrieving — those are the three layers below. |
| **Reuse** | Consumes intel-10/11/12 outputs directly. Decorrelation reuses intel-10's correlation fabric; the conviction bound reuses its effective-N; the shrinkage reuses intel-11's IC. |
| **Separation of concerns** | Independence (intel-10), trust (intel-11), per-edge score (intel-12), combination (intel-13), action (a future consumer) are all distinct. |
| **Compute efficiency** | Live but cheap — operates on dozens of live edges; the expensive inputs are pre-computed weekly. |
| **Shadow mode first** | Produces an observational view; takes no action until a consumer is deliberately wired. |
| **Data quality over model complexity** | Shrinkage and robust construction over fragile optimization. The diagnostics surface the illusion of independence honestly. The combiner is accountable to its own IC — it must beat equal-weight out-of-sample or be deleted. |
| **Compounding** | The combiner improves automatically as the layers below improve — better IC, correlation, and scores all flow up into a better view with no change here. |
