# Architecture Decision: I6 Confluence Expansion

**Version:** 1.0
**Status:** adopted
**Priority:** high
**Milestone:** v2.8
**Last Updated:** 2026-05-16
**Tags:** i6, confluence, cross-timeframe, cross-asset, architecture, kafka, adr, intelligence

## Decision

Hybrid architecture: cross-TF plugins run in-process; cross-asset/macro plugins run in a dedicated service with Kafka injection.

## Rationale

### Cross-TF: In-Process (No New Infrastructure)

Cross-timeframe confluence reads `frames["intel_*"]` — intelligence dicts already cached per-bar by `IntelligencePipelineComputeAgent`. The data is in-memory, per-symbol, and doesn't need cross-symbol coordination.

- **Zero new topics.** Zero new services. Zero new DB tables.
- **Pattern match:** Existing `CrossTimeframeConfluencePlugin` already does this successfully.
- **Compute cost:** O(TFs × fields) per bar per symbol — negligible.

Tier 1 cross-TF ideas (MomentumDivergence, S/R Confluence, RegimeAgreement, SqueezeExpansion, OrderFlowAlignment) all follow this pattern.

### Cross-Asset: Service-Injected (New Infrastructure)

Cross-asset confluence requires intelligence from *other symbols* — USD strength needs EURUSD+GBPUSD+USDJPY+USDCHF; yield curve needs ZN+ZB+ZT; sector rotation needs 11 GICS ETFs. This is fundamentally different from cross-TF:

- **Data crosses symbol boundaries.** Pipeline runs per-symbol; cross-asset reads N other symbols.
- **Compute-once, consume-many.** USD strength is the same for ES, NQ, RTY, YM — compute once, inject everywhere.
- **Independent lifecycle.** Macro context computation has different latency requirements than signal generation. If macro service lags, pipeline degrades gracefully (partial confluence, not zero).
- **Separate scaling.** Macro context is compute-heavy (50+ instruments × rolling correlations). Signal pipeline stays lean.

### Why Not Options A or C (from idea doc)

**Option A (expand `frames["intel_*"]` to cross-symbol):** Couples pipeline to all subscribed instruments. Memory: 50 instruments × 6 TFs = 300+ intelligence dicts per pipeline instance. Pipeline already uses ~2GB for I1-I7; adding 300 dicts doubles that. Wrong trade-off.

**Option C (read directly from bar history):** Couples I6 plugins to `BarHistory` internals. Plugins should be functions of `frames`, not functions of service infrastructure. Violates plugin protocol.

**Chosen: Option B (service-injected via `frames["macro"]`)** extends the existing `frames["cross_asset"]` pattern already used by `ctx_CrossAssetContext`. Proven, decoupled, degrades gracefully.

## Architecture Diagram

```
market.bars ──→ MacroContextComputeAgent ──→ intelligence.macro_context ──┐
                                                                          │
market.bars ──→ IntelligencePipelineComputeAgent ────────────────────────→ I1-I7
                    ↑                                                     │
                    └─── frames["macro"] (injected from Kafka) ←─────────┘
                    └─── frames["intel_*"] (in-process cache)
```

## MacroContextComputeAgent Design

```
Subscribes: market.bars (all instruments)
Computes:  USD strength, yield curve, flight-to-quality, credit stress,
           sector rotation, factor regime, crypto sentiment, EM divergence
Publishes: intelligence.macro_context (compacted topic)
Frequency: Per bar (only when any subscribed instrument produces a bar)
```

**Key design constraint:** Macro context is bar-level, not symbol-level. Every bar from any instrument triggers a recompute. Pipeline consumes the latest macro snapshot.

## Gradient-First Scoring (Design Principle)

All I6 outputs must be continuous gradients in [-1, +1] or [0, 1]. Never use step functions or hard thresholds.

**Approved techniques:**
- `np.tanh(z / threshold)` — soft saturation
- `1.0 / (distance + 1)` — proximity decay
- `sum(weights * signs) / sum(weights)` — weighted agreement fraction
- `(value - rolling_min) / (rolling_max - rolling_min)` — percentile normalization

**Forbidden patterns:**
- `if spread_z > 2.0: return 1.0 else: 0.0`
- `"If all 3 agree → 1.0"`
- Any step function that discards magnitude information

**Why:** Renaissance principle — "never drop data that could contain signal." Binary scoring causes zero-variance failures in IC computation. A credit spread at 3σ is meaningfully different from 2.1σ.

## Build Discipline

Renaissance: build 1 plugin, track to `signal_ledger`, wait 7-30 days, validate with p < 0.05 before building next.

**Build order (Tier 1 first — zero new data needed):**
1. CrossTFMomentumDivergence (2 fields) — HTF vs LTF momentum shape
2. CrossTFSRConfluence (2 fields) — multi-TF S/R level agreement
3. CrossTFRegimeAgreement (2 fields) — HMM regime combination scoring
4. SqueezeExpansionDivergence (2 fields) — coiled-spring vs blow-off
5. CrossTFOrderFlowAlignment (2 fields) — OFI/CVD direction agreement

**Then Tier 2 (requires MacroContextComputeAgent):**
6. MacroContextComputeAgent — foundation service
7. USD strength, yield curve, flight-to-quality, credit stress
8. Sector rotation, factor regime

**Then Tier 3 (higher complexity):**
9. Volume profile confluence, cascade detection
10. Correlation stress, lead-lag detection

## Schema Growth

I6Confluence currently has 16 fields. Tier 1 adds ~10 fields. Tier 2 adds ~12 fields. Total ~38 fields.

If schema becomes unwieldy (>40 fields), split into sub-schemas:
- `I6TFConfluence` — cross-timeframe scores
- `I6AssetConfluence` — cross-asset/macro scores
- `I6Confluence` — union of both (backward-compatible)

This is a future concern — not actionable now.
