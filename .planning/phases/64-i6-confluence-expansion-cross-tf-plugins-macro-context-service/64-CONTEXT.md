# Phase 64: I6 Confluence Expansion - Context

**Gathered:** 2026-04-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Expand I6 from single-plugin cross-timeframe confluence (16 fields) to multi-dimensional intelligence across two axes: cross-timeframe (in-process plugins reading cached `frames["intel_*"]`) and cross-asset (MacroContextComputeAgent service computing macro regime factors from bar history). Build one plugin at a time; validate with p < 0.05 before building next. All new outputs are continuous gradients in [-1, +1] or [0, 1] — never binary step functions.

Includes: CrossTFMomentumDivergence (first plugin), MacroContextComputeAgent (factor factory), remaining Tier 1 cross-TF plugins (batch after validation), IC fix prerequisite (continuous pnl_r for non-null IC), and cross-asset instrument identifier constants.

</domain>

<decisions>
## Implementation Decisions

### Plan Structure

- **D-01:** Three plans matching ROADMAP structure:
  - **Plan 01:** CrossTFMomentumDivergence + I6Confluence schema extension + IC fix prerequisite
  - **Plan 02:** MacroContextComputeAgent (factor factory) + 3 initial macro factors (USD strength, yield curve, flight-to-quality) + cross-asset instrument identifiers
  - **Plan 03:** Remaining 4 Tier 1 cross-TF plugins (CrossTFSRConfluence, CrossTFRegimeAgreement, SqueezeExpansionDivergence, CrossTFOrderFlowAlignment)
- **D-02:** Validation gate between Plan 01 and Plan 03 — Plan 01 must ship, accumulate N≥30 signals, and validate before Plan 03 execution begins
- **D-03:** Plan 02 (MacroContextComputeAgent) can execute in parallel with Plan 01 validation waiting period — no dependency between cross-TF and cross-asset tracks

### Cross-TF Plugin Architecture

- **D-04:** Cross-TF plugins run in-process within `IntelligencePipelineComputeAgent` in Wave 4, reading `frames["intel_*"]` (already cached). Zero new Kafka topics, zero new services.
- **D-05:** Each cross-TF plugin is a standalone class following existing `CrossTimeframeConfluencePlugin` pattern — `compute()` method takes `frames`, returns dict of new I6 fields
- **D-06:** CrossTFMomentumDivergence outputs: `ctf_momentum_divergence` [-1, +1] (HTF vs LTF momentum shape) and `ctf_momentum_regime` (categorical: aligned_htf_bull/aligned_htf_bear/pullback/bounce/mixed)

### MacroContextComputeAgent (Factor Factory)

- **D-07:** MacroContextComputeAgent is a thin orchestrator that runs self-contained "macro factor plugins" from `src/intelligence/macro/`. Each factor is an independent, testable module.
- **D-08:** Factor plugin protocol: function/module that takes bar history (or relevant instrument data) and returns gradient scores. Register in a `MACRO_FACTORS` list (mirrors `TIER_I*` registration pattern).
- **D-09:** Initial 3 factors (maximally orthogonal):
  1. **USD strength** — `src/intelligence/macro/usd_strength.py` — composite from FX pairs (EURUSD, GBPUSD, USDJPY, USDCHF)
  2. **Yield curve slope** — `src/intelligence/macro/yield_curve.py` — from rate futures (ZT, ZN, ZB, ZF)
  3. **Flight-to-quality** — `src/intelligence/macro/flight_to_quality.py` — from TLT, SPY, VX
- **D-10:** MacroContextComputeAgent subscribes to `market.bars` for all instruments, computes macro factors per bar, publishes to `intelligence.macro_context` Kafka topic. Pipeline injects via `frames["macro"]`.
- **D-11:** Future factors (credit stress, sector rotation, factor regime, crypto sentiment, EM divergence) are added as new files in `src/intelligence/macro/` + registration — no orchestrator changes needed.

### I7 Consumption + _shadow Wiring

- **D-12:** New I6 fields captured in `_shadow` dict via `capture_confluence_features()` extension. Available in I6Confluence schema and persisted to DB.
- **D-13:** New I6 fields NOT wired into I7 confidence scoring, CIS scorer, or aggregator until validated (p < 0.05, N≥30). "Capture everything, use nothing until proven."
- **D-14:** Post-validation: wire validated fields into relevant I7 plugins' confidence scoring as a separate follow-up task (not part of Phase 64 plans).

### Schema Strategy

- **D-15:** Keep single flat `I6Confluence` TypedDict. Add fields as needed. Split into sub-schemas only if it exceeds 40+ fields AND there's a concrete reason (different consumers, different update frequencies, different persistence). Current growth: 16 → ~26 after Tier 1 → ~38 after Tier 2.

### Gradient-First Scoring (Design Principle)

- **D-16:** All I6 outputs must be continuous gradients in [-1, +1] or [0, 1]. Never use step functions or hard thresholds.
- **D-17:** Approved gradient techniques: `np.tanh(z / threshold)`, `1.0 / (distance + 1)`, `sum(weights * signs) / sum(weights)`, `(value - rolling_min) / (rolling_max - rolling_min)`.
- **D-18:** Forbidden patterns: `if spread_z > 2.0: return 1.0`, `"If all 3 agree → 1.0"`, any step function that discards magnitude information.

### Folded Todos

- **D-19:** **IC fix** (from todo 028): Replace binary `±1.0` outcomes in `compute_ic()` with continuous `pnl_r`. This is a prerequisite for validating new I6 fields — without it, `signal_metrics_ic` stays all NULL. Scope: `src/intelligence/ml/information_coefficient.py` + `src/intelligence/metrics/compute.py` + relevant tests.
- **D-20:** **Cross-asset instrument identifiers** (from todo 011): Define shared constants for FX pairs, rate futures, sector ETFs, factor ETFs in `src/intelligence/schemas.py` or `src/intelligence/cross_asset_constants.py`. Macro factor plugins import from here — no hardcoded instrument strings.

### Claude's Discretion

- Exact asyncpg pool usage and Kafka consumer group naming (follow existing agent patterns)
- BaseAgent inheritance for MacroContextComputeAgent
- Test fixture patterns (follow existing `tests/unit/` conventions)
- Exact gradient formula parameters (threshold values, lookback windows) for each plugin — use existing I6 plugin as reference

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design Specs
- `docs/ideas/i6-confluence-expansion.md` — 21 ideas, 3-tier roadmap, gradient-first principle, I7 consumption table
- `.planning/notes/i6-confluence-architecture.md` — Architecture decision: hybrid (cross-TF in-process, cross-asset via service injection), MacroContextComputeAgent design, build discipline

### Existing I6 Implementation
- `src/intelligence/confluence/cross_timeframe.py` — Current I6 plugin (16 fields, recency weighting, proximity decay) — PATTERN TO FOLLOW
- `src/intelligence/schemas.py` — `I6Confluence` schema (extend this), `capture_confluence_features()` in `confidence_utils.py`
- `src/intelligence/register_plugins.py` — `TIER_I6` list (register new plugins here)

### Pipeline + Service Patterns
- `services/intelligence_pipeline_agent.py` — Unified I1-I7 pipeline, 4-wave execution, `frames["intel_*"]` caching, `frames["macro"]` injection point
- `services/cross_asset_service.py` — Existing cross-asset service (pattern reference for MacroContextComputeAgent)
- `services/roll_compute_agent.py` — Example of a compute-only agent (BaseAgent pattern reference)

### Core Infrastructure
- `src/core/stream_keys.py` — Add `topic_macro_context()` here
- `src/core/schemas/market_events.py` — Schema patterns for Kafka payloads
- `src/core/database_manager.py` — DB connection pool patterns
- `src/config/settings.py` — All instrument definitions (50+ instruments), `get_active_contracts()`
- `src/observability/metrics.py` — Metric registration (prevent duplicate registration)

### IC Fix (Folded Todo 028)
- `src/intelligence/ml/information_coefficient.py` — `compute_ic()` — replace binary outcomes with continuous pnl_r
- `src/intelligence/metrics/compute.py` — `compute_ic_metrics()` — passes data to IC
- `services/signal_metrics_compute_agent.py` — Ensure pnl_r available in rows

### Instrument Identifiers (Folded Todo 011)
- `src/intelligence/trading/cross_asset_divergence.py` — Current hardcoded pair strings to refactor
- `src/intelligence/schemas.py` — Location for shared instrument constants

### Existing Tests
- `tests/unit/intelligence/test_i2_plugins.py` — Plugin test patterns
- `tests/unit/intelligence/test_i5_new_plugins.py` — Plugin test patterns

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `CrossTimeframeConfluencePlugin`: Full implementation of cross-TF scoring with recency weighting, proximity decay, weighted composites — direct pattern to replicate for new Tier 1 plugins
- `capture_confluence_features()` in `confidence_utils.py`: Already captures all I6 fields into `_shadow` dict — extend with new fields
- `frames["cross_asset"]` injection: Pipeline already injects cross-asset context from Kafka — `frames["macro"]` follows same pattern
- `TIER_I6` in `register_plugins.py`: Registration list — add new plugins here
- `IntelligencePipelineComputeAgent._collect_plugin_results()`: Timed plugin execution with metrics — new I6 plugins use this automatically

### Established Patterns
- Gradient scoring: `np.tanh(z / threshold)` for soft saturation, `1.0 / (bars_since + 1)` for recency decay
- Plugin protocol: `compute(frames, bar, ctx)` → dict of fields merged into tier output
- Wave 4 execution: I6 + I7 run together; I6 plugins have access to all I1-I5 outputs via frames
- Kafka topic naming: `topic_*()` functions in `stream_keys.py`, dots not colons
- Agent pattern: BaseAgent with `_setup()`, `_teardown()`, metrics port, consumer group

### Integration Points
- `IntelligencePipelineComputeAgent._run_i6_plugins()`: Where new I6 plugins execute
- `IntelligencePipelineComputeAgent._inject_cross_asset_frames()`: Where `frames["macro"]` gets injected from Kafka
- `I6Confluence` in `schemas.py`: Schema that gets merged into `IntelligenceEvent` JSONB
- `signal_ledger._shadow`: Captured per signal — new fields automatically tracked for ML

</code_context>

<specifics>
## Specific Ideas

- MacroContextComputeAgent should follow the same lifecycle as other compute agents: subscribe to `market.bars`, compute per-bar, publish to Kafka, systemd unit for management
- Macro factor computation is bar-level, not symbol-level — every bar from any subscribed instrument triggers a recompute of all factors
- USD strength synthesis from FX pairs (DXY-like): inverse EURUSD + inverse GBPUSD + USDJPY change + USDCHF change, normalized
- Yield curve: price-based (rate futures trade inverse to yields) — ZT price up = short rates down = curve steepening
- Flight-to-quality: simultaneous TLT up + SPY down + VIX up is the classic signal — use sign-weighted agreement fraction, not binary "all 3 agree"
- CrossTFMomentumDivergence: extract momentum bias from each TF using I2 events + RSI/MACD direction, then compute HTF-LTF divergence as continuous gradient
- Each new I6 plugin should produce exactly 2 fields: one continuous score [-1,+1] and one categorical label (for segmentation in ML training)

</specifics>

<deferred>
## Deferred Ideas

- **Gradient-first audit of existing I1-I7 plugins** (from todo 028) — broader sweep to find binary scoring in non-I6 tiers. Separate from Phase 64.
- **Tier 2 macro factors** (credit stress, sector rotation, factor regime, crypto sentiment, EM divergence) — build after initial 3 factors prove signal
- **Tier 3 ideas** (volume profile confluence, cascade detection, correlation stress, lead-lag, commodity-FX, VIX term structure, liquidity regime) — higher complexity, deferred
- **Dashboard visualization** for multi-dimensional confluence (radar chart, heatmap, separate panels) — UI work, separate phase
- **Schema split** into I6TFConfluence + I6AssetConfluence — only if exceeds 40+ fields with concrete reason

### Reviewed Todos (not folded)
- `008-implement-plugin-validation-layer.md` — General plugin validation framework, not specific to I6
- `012-normalize-float-raw-pairs-optional-pattern.md` — Code quality cleanup, lower priority
- `017-dashboard-intelligence-field-gaps.md` — Dashboard work, separate phase
- `029-audit-plugins-for-gil-release.md` — Threading optimization, unrelated to I6 expansion
- `030-fix-plugin-dependency-violations-for-wave-execution.md` — Already done per ROADMAP

</deferred>

---

*Phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service*
*Context gathered: 2026-04-08 via interactive discuss-phase*
