# VIL Platform Ideas — Substrate-Enabled Extensions Not Yet Promoted

**Version:** 1.0
**Status:** under-review
**Priority:** medium
**Last Updated:** 2026-06-01
**Tags:** vil, ideas, regime-discovery, lead-lag, backtest, episodic-memory, decay, cost-model, holding-doc

---

## Purpose

This is a holding doc. The Vector Intelligence Layer is not infrastructure for three specific applications — it is a general **similarity-and-outcome fabric**: embed any entity, retrieve its analogs, know what followed. A large fraction of the research questions this firm asks are exactly that shape. This document collects the substrate-enabled ideas that are *good and real* but do not yet warrant their own doc — each reuses the VIL fabric near-free or constitutes a measurable edge, but none is developed enough (or urgent enough) to stand alone.

The bar to graduate from this doc to its own `intel-NN`: the idea is being actively built or is large enough that a standalone design adds value. Until then it lives here, one section each, kept at idea altitude.

**The pruning rule (applied to everything below).** An idea earns a place only if it (a) reuses the substrate cheaply — compounding, not new infrastructure — or (b) is a genuine measurable edge. Anything that is neither was cut. "Embeddings for everything," text-embedding models, and parametric prediction models did not make it.

---

## 1. Cost-Aware Net Scoring

**Idea.** intel-12's E[R] is gross. Make expected return *net of modeled transaction cost* before anything consumes it. A cost model (spread + slippage as a function of size and liquidity) is subtracted from the raw analog-distribution mean.

**Why it's real.** At the short horizons this system targets, cost is frequently larger than the edge. A gross +0.2R that costs 0.25R to capture is a losing trade dressed as a winner. Renaissance treats cost modeling as *part* of the edge, not an afterthought.

**Reuses.** Nothing new — it is a transform on intel-12's existing `expected_r`. The combiner (intel-13) explicitly consumes the net number.

**Caveats / open.** Slippage is regime- and size-dependent; the model itself needs calibration against realized fills (which this system may not yet have). Start with a conservative static spread+slippage estimate; refine when fill data exists.

**Where it lands.** A transform in intel-12's pipeline (`E[R] → E[R]_net`) plus a flag that the score is cost-adjusted. Likely folds into intel-12 rather than graduating to its own doc.

---

## 2. Regime Discovery (Unsupervised)

**Idea.** Instead of (only) I4's parametric regime labels, *discover* regimes by clustering `bar` embeddings. Natural groupings in embedding space are data-defined regimes. Extension: **regime-transition forecasting** — embed the current regime trajectory, retrieve historical analogs of this transition, ask what regime tended to follow.

**Why it's real.** Parametric regime definitions encode prior assumptions about what regimes exist. Clustering lets the data say. And transition forecasting ("we are sliding from trending toward chop") is more actionable than a static label.

**Reuses.** `bar` embeddings already exist for the whole VIL substrate. Clustering and trajectory-analog retrieval are the existing k-NN primitive, scoped differently.

**Caveats / open.** Discovered clusters need interpretation to be trustworthy (a cluster is only useful if it is stable and has a forward-return signature). Validate against I4 labels before trusting — agreement is reassurance, divergence is a research lead, not automatically a discovery.

---

## 3. Cross-Asset Lead-Lag

**Idea.** Embed each instrument's state. Find historical cases where instrument A's current state *preceded* instrument B moving — a directional, time-shifted similarity. Surfaces lead-lag and contagion structure.

**Why it's real.** This is stat-arb-flavored: the firm's edge has historically included cross-sectional relationships, not just single-instrument prediction. "When ES intelligence looks like this, NQ tended to follow at T+5" is a genuinely different signal source.

**Reuses.** Per-symbol embeddings already stored. The new ingredient is *time-shifted* outcome joining (A at T vs B at T+k) — a variation on the outcome-label join, not new infrastructure.

**Caveats / open.** Lead-lag is notoriously unstable and prone to spurious discovery across many instrument pairs — FDR correction (intel-11) is mandatory here, not optional. Few instruments today (~handful), so the cross-section is thin; this grows in value as the instrument set expands.

---

## 4. Non-Parametric Hypothesis Backtester

**Idea.** Point the Analog Finder at a *proposed* setup rather than the live bar: serialize the hypothesis as a query vector, retrieve historical analogs, read the empirical outcome distribution. A backtest with no parametric model — the analogs *are* the backtest.

**Why it's real.** It answers "is this edge real?" for any hypothesis a researcher (or an LLM agent) can express as a feature state, without building or maintaining a parametric backtester. The outcome distribution speaks for itself, with conviction (analog count, distance) attached.

**Reuses.** Exactly the intel-11 Analog Finder + intel-12 distribution, with a hand-constructed query vector. Zero new infrastructure.

**Caveats / open.** Garbage hypotheses retrieve garbage analogs; the null result (no close analogs) must be surfaced honestly as "untestable from history" rather than filled. Look-ahead in hypothesis construction is the usual trap — the query must be expressible point-in-time.

---

## 5. Agent Episodic Memory

**Idea.** Give LLM swarm agents long-term memory via the substrate: embed `SignalContext` at decision time, and at inference retrieve the agent's own most-similar past situations and what followed. Promote the `signal_context` retrieval from a footnote in earlier docs to a first-class platform pillar.

**Why it's real.** Agents currently reason from pattern intuition in a vacuum. Grounding them in "the last time you saw conditions like these, here is what happened" is the difference between recall and improvisation — and it is the same retrieval the scoring stack already uses.

**Reuses.** `signal_context` embeddings + the `_find_analogs` retrieval path already specified in intel-11. The memory *is* the VIL fabric scoped to one agent's history.

**Caveats / open.** Memory of bad past decisions can entrench bad behavior (a feedback loop) — retrieval should be grounded in *outcomes*, not the agent's prior *opinions*, so the agent learns from what happened, not from what it previously thought.

---

## 6. Plugin / Feature Decay Observatory

**Idea.** A research surface that fuses intel-11's IC decay with intel-10's correlation drift: which plugins/features are losing predictive power, which are becoming redundant, in which regimes — over time. Queryable in Superset.

**Why it's real.** Edges have half-lives; the firm's job is to notice decay before it costs money. Today IC decay (intel-11) and redundancy (intel-10) are measured separately. Fused over time, they answer the research question that actually matters: "what is dying, and what is crowding?"

**Reuses.** Pure read layer over `feature_ic_stats` (intel-11) and the correlation history (intel-10). No new computation — a Superset view and the queries behind it.

**Caveats / open.** Observational only; it informs human research and does not act. The value is in surfacing trends early, so the cadence of the underlying batches (weekly) bounds how fresh the observatory can be.

---

## What Would Graduate First

Rough order, by value-per-effort:

1. **Cost-aware net scoring** — cheapest, and intel-13 already depends on it. Likely folds into intel-12 rather than standing alone.
2. **Agent episodic memory** — high value (grounds the whole swarm), and the retrieval already exists.
3. **Non-parametric hypothesis backtester** — turns the substrate into a research tool with near-zero new code.
4. **Decay observatory** — pure read layer, high research value, trivial to build.
5. **Regime discovery / cross-asset lead-lag** — higher value but more validation work and more spurious-discovery risk; later.

---

## Relationship to Existing Work

| Component | Relationship |
|---|---|
| `vil-01` | The fabric every idea here reuses. Each is the embed/retrieve primitive scoped to a new entity or question. |
| `intel-11` | Source of IC, the Analog Finder, and FDR correction — load-bearing for backtester, lead-lag, decay observatory. |
| `intel-12` | Cost-aware net scoring folds in here; the backtester reuses its distribution. |
| `intel-13` | Consumes cost-aware net scoring directly. |
| `intel-10` | Source of correlation history for the decay observatory. |

---

## Principles Alignment

| Principle | How this doc satisfies it |
|---|---|
| **Reuse** | Every idea here exists *because* it reuses the substrate near-free. That is the entry criterion. |
| **Compounding** | Each is a new entity type or new question on the same fabric — the substrate gets more valuable with every one added, at no new infrastructure cost. |
| **Separation of concerns** | A holding doc keeps half-formed ideas out of the focused application docs until they earn their own home. |
| **Data quality over model complexity** | The pruning rule cut everything that was complexity without a measurable edge. FDR correction is mandated where spurious discovery is a risk (lead-lag). |
