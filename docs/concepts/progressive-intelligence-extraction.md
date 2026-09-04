# Progressive Intelligence Extraction

**Version:** 2.0
**Status:** current
**Last Updated:** 2026-09-04
**Tags:** intelligence-tiers, abstraction-layers, feature-extraction, statistical-pipeline

> Raw market data contains no signal — it must be transformed through sequential layers, each a prerequisite for the next, before an edge claim is possible.

> **Rewritten for v3.0 (2026-09-04):** The original version of this doc described the archived
> v2.x eight-tier I1-I8 `IntelligenceEvent` pipeline (no live consumer since 2026-07-02). The
> underlying principle — each layer is a hard prerequisite for the next, no skipping — still
> holds; the concrete tiers below now describe the live AlphaEngine (v3.0) stack instead. See
> `docs/architecture/architecture-v3-alphaengine-pipeline.md` for full layer detail and
> `docs/architecture/architecture-v2-event-driven-pipeline.md` for the superseded version.

## The Problem It Solves

Price and volume data are statistically noisy. A single OHLCV bar tells you almost nothing about whether to trade. The naive approach — "if RSI < 30, buy" — treats a single indicator as a decision, encoding a researcher's hypothesis about what matters before any data has weighed in. The gap between "data" and a defensible edge claim cannot be crossed in one step, and it cannot be crossed by asserting a rule either — it has to be crossed by measurement, one layer at a time.

## The Principle

Each layer consumes the outputs of previous layers and produces a step closer to an evaluable edge claim. No layer can skip its predecessors because each layer's outputs are prerequisites for the next:

- Clean raw bars are the necessary input for feature computation — nothing above computes anything without this being correct first.
- Atomic features are the necessary input for regime conditioning and IC measurement — nothing enters IC that didn't come through the Feature Factory first.
- Regime state and per-feature IC are necessary inputs for combination — an ensemble can't weight what hasn't been measured, per-regime, first.
- A combined, scored edge is the necessary input for trade construction — you can't size a position on a feature that hasn't cleared IC.
- A constructed trade hypothesis is the necessary input for governance — nothing is promoted toward production capital without a scored, gated hypothesis behind it.

The question answered gets more concrete at each layer. Layer 1 answers "does this quantity move independently of the others?" Layer 3 answers "does this quantity actually predict forward returns, and in which regime?" Layer 6 answers "has this cleared the bar to be trusted with capital?" These are genuinely different questions that require genuinely different computation — and, critically, each later question is only askable once the earlier one has been answered by measurement, not assumption.

## How IndicAgent Applies It

The live AlphaEngine (v3.0) pipeline is the current instance of this principle:

| Layer | Name | What it produces |
|-------|------|-------------------|
| 0 | Data Foundation | Clean OHLCV bars (`market_data_ohlcv_tradeable`) — no gaps, no synthetic fill treated as real |
| 1 | Feature Factory | Atomic, orthogonal `FeatureVector` rows (`compute_features()`) — a measured quantity, not a directional opinion |
| 2 | Regime Layer | Per-symbol idiosyncratic HMM state + cross-sectional systematic regime, as stratification variables |
| 3 | IC Measurement | `ic_engine` — per feature × symbol × TF × regime × lookahead, does this feature predict? |
| 4 | Combination / Ensemble | `ic_shrinkage` → `ensemble_trainer` — IC-weighted (and tested nonlinear) combination into a scored edge |
| 5 | Trade Construction | Turns a scored edge into a tradeable position hypothesis |
| 6 | Governance | Concept Registry, APR, shadow/promotion gates — decides what's allowed to reach the next stage |

Unlike the v2.x tier system this replaces, there is no single typed carrier object accumulating state across all layers — each layer reads its input from a TimescaleDB table the previous layer wrote (`feature_vectors`, IC results, ensemble scores), which is itself the DAG-invariant boundary (Ring rule: compute stages publish, a dedicated writer persists). The prerequisite ordering is enforced by what each layer's query depends on existing, not by a shared carrier type.

## Invariants

- No layer may read a table that a later layer wrote — the DAG runs one direction (Layer 0 → 6), never backward.
- A feature never skips IC to reach the ensemble — every feature in `ensemble_trainer`'s input has a measured, cited IC.
- Regime is a stratification variable for IC, never a gate — see `docs/concepts/regime-awareness.md` for why conditioning beats gating.
- Nothing reaches governance (Layer 6) without having cleared measurement at every layer below it — a plausible-sounding feature or trade construction idea is not evidence.

## Recipe

When designing a progressive extraction pipeline for any domain:

1. **Map the abstraction ladder first.** What is the equivalent of "raw data," "events," "structure," "regime," "patterns," "signals" in your domain? Each level should answer a qualitatively different question.
2. **Make prerequisites explicit.** If tier N uses tier N-1 outputs, enforce this in the DAG — do not rely on execution order being correct by convention.
3. **Make dependencies visible.** Either a typed carrier object that accumulates layer outputs as it flows forward, or a persisted table each later layer reads from — either makes the dependency explicit and prevents a later layer from silently running on stale or missing upstream state.
4. **Separate blocking from non-blocking layers.** Fast, synchronous layers should never wait on a slow one (an LLM call, a batch job). Let the slow layer run out-of-band and treat its output as commentary or a later-arriving input, not a gate.
5. **Keep layer boundaries clean.** A layer should not need to read ahead into a later layer's output — if it does, the layer assignment is wrong. Dependencies should flow in one direction only.

## See Also

- Implementation: `docs/architecture/architecture-v3-alphaengine-pipeline.md` — full layer-by-layer detail, what's built vs. measured vs. open
- Superseded: `docs/architecture/architecture-v2-event-driven-pipeline.md` — the archived I1-I8 tier system this doc previously described
- Related concept: `docs/concepts/dag-execution.md` — how layer ordering is enforced via DAG
- Related concept: `docs/concepts/regime-awareness.md` — why regime is a stratification variable, not a gate, at Layer 2
