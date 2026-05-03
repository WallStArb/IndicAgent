# Phase 64: I6 Confluence Expansion - Context

**Gathered:** 2026-04-08
**Refined:** 2026-04-23 (Renaissance review — dropped stale IC fix, swapped plan order, merged macro into CrossAssetComputeAgent)
**Status:** Ready for execution

<domain>
## Phase Boundary

Expand I6 from single-plugin cross-timeframe confluence (16 fields) to multi-dimensional intelligence across two axes: cross-timeframe (in-process plugins reading cached `frames["intel_*"]`) and cross-asset (macro factors computed in existing CrossAssetComputeAgent). Build one plugin at a time; validate with IC > 0.05 AND p < 0.05 before building next. All new outputs are continuous gradients in [-1, +1] or [0, 1] — never binary step functions.

Includes: CrossTFMomentumDivergence (first plugin), remaining 4 Tier 1 cross-TF plugins (batch after validation), macro factors merged into CrossAssetComputeAgent (deferred until cross-TF validates).

Excludes (already shipped): IC fix (Phase 60/63.2 — `compute_ic()` already uses continuous `pnl_r`).

</domain>

<decisions>
## Implementation Decisions

### Plan Structure (revised 2026-04-23)

- **D-01:** Three plans with revised order — cheapest infrastructure first:
  - **Plan 01:** CrossTFMomentumDivergence + I6Confluence schema extension + cross-asset instrument constants + validation script
  - **Plan 02:** Remaining 4 Tier 1 cross-TF plugins (CrossTFSRConfluence, CrossTFRegimeAgreement, SqueezeExpansionDivergence, CrossTFOrderFlowAlignment) — requires Plan 01 validation gate
  - **Plan 03:** Macro factors (USD strength, yield curve, flight-to-quality) merged INTO CrossAssetComputeAgent — deferred until Plans 01+02 validate
- **D-02:** Validation gate between Plan 01 and Plan 02 — Plan 01 must ship, accumulate N>=30 signals, and validate IC > 0.05 AND p < 0.05 before Plan 02 execution begins. Effect size required, not just significance.
- **D-03:** Plan 03 (macro factors) deferred until cross-TF plugins prove signal — don't build infrastructure for features that may not have predictive value.

### Cross-TF Plugin Architecture (unchanged)

- **D-04:** Cross-TF plugins run in-process within `IntelligencePipelineComputeAgent`, reading `frames["intel_*"]` (already cached). Zero new Kafka topics, zero new services.
- **D-05:** Each cross-TF plugin is a standalone class following existing `CrossTimeframeConfluencePlugin` pattern — `compute_full()` method takes `frames`, returns dict of new I6 fields.
- **D-06:** CrossTFMomentumDivergence outputs: `ctf_momentum_divergence` [-1, +1] (HTF vs LTF momentum shape) and `ctf_momentum_regime` (categorical: aligned_htf_bull/aligned_htf_bear/pullback/bounce/mixed)

### Macro Factors — Merged into CrossAssetComputeAgent (revised 2026-04-23)

- **D-07 (revised):** Macro factors are computed within the existing `CrossAssetComputeAgent`, not a new separate service. One service for all cross-market intelligence. Extends existing `topic_cross_asset` with macro factor fields, not a new topic.
- **D-08 (revised):** Macro factor functions in `src/intelligence/macro/` are pure functions imported by `CrossAssetComputeAgent`. Each factor takes `bar_cache` and returns gradient score dict.
- **D-09 (unchanged):** Initial 3 factors (maximally orthogonal):
  1. **USD strength** — `src/intelligence/macro/usd_strength.py` — composite from FX pairs (EURUSD, GBPUSD, USDJPY, USDCHF)
  2. **Yield curve slope** — `src/intelligence/macro/yield_curve.py` — from rate futures (ZT, ZN, ZB, ZF)
  3. **Flight-to-quality** — `src/intelligence/macro/flight_to_quality.py` — from TLT, SPY, VX
- **D-10 (revised):** CrossAssetComputeAgent subscribes to both `topic_intelligence` (existing — EQ_INDEX features) AND `topic_market_bars` (new — macro instrument bar data). Publishes all cross-market intelligence in one topic: `topic_cross_asset`.
- **D-11 (unchanged):** Future factors (credit stress, sector rotation, factor regime, crypto sentiment, EM divergence) are added as new files in `src/intelligence/macro/` — no orchestrator changes needed.
- **D-24 (new):** Pipeline receives macro factors via existing `frames["cross_asset"]` injection — no new injection point, no new cache variable. Macro fields appear as additional keys in the cross_asset payload.

### I7 Consumption + _shadow Wiring (unchanged)

- **D-12:** New I6 fields captured in `_shadow` dict via `capture_signal_features()` extension. Available in I6Confluence schema and persisted to DB.
- **D-13:** New I6 fields NOT wired into I7 confidence scoring, CIS scorer, or aggregator until validated (p < 0.05, N>=30). "Capture everything, use nothing until proven."
- **D-14:** Post-validation: wire validated fields into relevant I7 plugins' confidence scoring as a separate follow-up task (not part of Phase 64 plans).

### Schema Strategy (unchanged)

- **D-15:** Keep single flat `I6Confluence` TypedDict. Add fields as needed. Split into sub-schemas only if it exceeds 40+ fields AND there's a concrete reason. Current growth: 16 → ~26 after Tier 1 → ~38 after Tier 2.

### Gradient-First Scoring (unchanged)

- **D-16:** All I6 outputs must be continuous gradients in [-1, +1] or [0, 1]. Never use step functions or hard thresholds.
- **D-17:** Approved gradient techniques: `np.tanh(z / threshold)`, `1.0 / (distance + 1)`, `sum(weights * signs) / sum(weights)`, `(value - rolling_min) / (rolling_max - rolling_min)`.
- **D-18:** Forbidden patterns: `if spread_z > 2.0: return 1.0`, `"If all 3 agree -> 1.0"`, any step function that discards magnitude information.

### Folded / Dropped Decisions

- **D-19 (dropped):** IC fix was folded from todo 028. Now OBSOLETE — `compute_ic()` already uses continuous `pnl_r` (shipped in Phase 60/63.2).
- **D-20 (unchanged):** Cross-asset instrument identifiers in `src/intelligence/macro/constants.py`.
- **D-21 (unchanged):** Macro instrument availability — each factor degrades gracefully when instruments absent.
- **D-22 (revised):** Macro computation efficiency — handled within CrossAssetComputeAgent's existing bar processing. Only recompute macro factors when a macro-relevant bar arrives (`symbol in MACRO_ALL_SYMBOLS`).
- **D-23 (unchanged):** Automated validation gate script `tools/validate_i6_field.py`.

### Validation Gate (strengthened 2026-04-23)

- **D-25 (new):** Validation gate requires BOTH IC > 0.05 AND p < 0.05 (Bonferroni-corrected for 5 tests: alpha / 5 = 0.01). Significance alone is insufficient — tiny IC with low p just means we have enough data to detect a negligible effect.
- **D-26 (new):** Regime-segmented validation — run validation separately for trending (hmm_regime 1/2) and ranging (hmm_regime 0). A feature that only works in one regime is still useful, but we need to know WHICH regime.

### Claude's Discretion

- Exact gradient formula parameters (thresholds, lookback windows)
- BaseAgent/Settings patterns (follow Phase 71 conventions: `self.settings`, auto `init_tracing()`)
- Test fixture patterns (follow existing `tests/unit/` conventions)
- Kafka consumer group naming

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design Specs
- `docs/ideas/i6-confluence-expansion.md` — 21 ideas, 3-tier roadmap, gradient-first principle
- `.planning/notes/i6-confluence-architecture.md` — Architecture decision (hybrid), compute cost analysis

### Existing I6 Implementation
- `src/intelligence/confluence/cross_timeframe.py` — Current I6 plugin (16 fields, recency weighting, proximity decay) — PATTERN TO FOLLOW
- `src/intelligence/schemas.py` line 701 — `I6Confluence` schema (extend this)
- `src/intelligence/trading/confidence_utils.py` line 95 — `capture_signal_features()` (extend with new I6 fields)
- `src/intelligence/register_plugins.py` line 435 — `TIER_I6` list (register new plugins), line 165 — `validate_schema_coverage()` I6 tier_checks

### Pipeline + Service Patterns
- `services/intelligence_pipeline_agent.py` — Unified I1-I7 pipeline, 4-wave execution, `frames["intel_*"]` caching
- `services/cross_asset_service.py` — CrossAssetComputeAgent (merge target for macro factors in Plan 03)
- `src/core/stream_keys.py` — `topic_cross_asset()` (reused for macro factors, no new topic)

### Core Infrastructure
- `src/config/settings.py` — `get_active_contracts()`, instrument definitions
- `src/observability/metrics.py` — Metric registration (prevent duplicate registration)

### Already Shipped (DO NOT RE-IMPLEMENT)
- `src/intelligence/ml/information_coefficient.py` — IC already uses continuous `pnl_r` (Phase 60/63.2)
- `src/intelligence/metrics/compute.py` — `compute_ic_metrics()` already passes `pnl_r`

### Existing Tests
- `tests/unit/intelligence/test_i2_plugins.py` — Plugin test patterns
- `tests/unit/intelligence/test_i5_new_plugins.py` — Plugin test patterns

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `CrossTimeframeConfluencePlugin`: Full implementation of cross-TF scoring with recency weighting, proximity decay, weighted composites — direct pattern to replicate for new Tier 1 plugins
- `capture_signal_features()` in `confidence_utils.py`: Already captures 15 keys (2 metadata, 6 I6 CTF, 4 I4 macro, 3 exhaustion) into `_shadow` dict — extend with new fields
- `frames["cross_asset"]` injection: Pipeline already injects cross-asset context from Kafka — macro factors will use same injection point
- `TIER_I6` in `register_plugins.py`: Registration list — add new plugins here
- `IntelligencePipelineComputeAgent._collect_plugin_results()`: Timed plugin execution with metrics — new I6 plugins use this automatically

### Established Patterns
- Plugin protocol: `@dataclass`, `name`, `outputs: frozenset[str]`, `compute_full(frames) -> dict`
- Gradient scoring: `np.tanh(z / threshold)` for soft saturation, `1.0 / (bars_since + 1)` for recency decay
- Wave execution: I6 runs in Wave 4 alongside I7; I6 plugins have access to all I1-I5 outputs via frames
- Kafka topic naming: `topic_*()` functions in `stream_keys.py`, dots not colons
- Agent pattern (Phase 71): `self.settings` (not `self._settings`), auto `init_tracing()`, default `_report_consumer_lag()`
- Test pattern: `__new__()` to bypass `__init__`, `isinstance(val, (int, float))` not `if val`

### Integration Points
- `src/intelligence/confluence/cross_timeframe.py` — existing I6 plugin executing in Wave 4
- `services/intelligence_pipeline_agent.py` `_build_frames()` — `frames["cross_asset"]` injection at line ~1012
- `I6Confluence` in `schemas.py` line 701 — schema merged into `IntelligenceEvent` JSONB
- `signal_ledger._shadow` — captured per signal — new fields automatically tracked for ML

</code_context>

<specifics>
## Specific Ideas

- CrossTFMomentumDivergence: extract momentum bias from each TF using I2 events + RSI/MACD direction, then compute HTF-LTF divergence as continuous gradient
- Each new I6 plugin should produce exactly 2 fields: one continuous score [-1,+1] and one categorical label (for segmentation in ML training)
- Categorical labels are strings (not int codes) — human-readable in SQL queries and dashboard debugging
- Macro factor functions are pure (no class, no state) — testable with simple dict input/output
- USD strength synthesis from FX pairs (DXY-like): inverse EURUSD + inverse GBPUSD + USDJPY change + USDCHF change, normalized via tanh
- Yield curve: price-based (rate futures trade inverse to yields) — ZT price up = short rates down = curve steepening
- Flight-to-quality: simultaneous TLT up + SPY down + VX up is the classic signal — use sign-weighted agreement fraction, not binary

</specifics>

<deferred>
## Deferred Ideas

- **Gradient-first audit of existing I1-I7 plugins** (from todo 028) — broader sweep to find binary scoring in non-I6 tiers. Separate from Phase 64 (Phase 65).
- **Tier 2 macro factors** (credit stress, sector rotation, factor regime, crypto sentiment, EM divergence) — build after initial 3 factors prove signal
- **Tier 3 ideas** (volume profile confluence, cascade detection, correlation stress, lead-lag, commodity-FX, VIX term structure, liquidity regime) — higher complexity, deferred
- **Dashboard visualization** for multi-dimensional confluence — UI work, separate phase
- **Schema split** into I6TFConfluence + I6AssetConfluence — only if exceeds 40+ fields with concrete reason
- **I7 confidence wiring** of validated I6 fields — separate follow-up task after Phase 64

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
*Refined: 2026-04-23 — Renaissance review: drop IC fix, swap plan order, merge macro into CrossAssetComputeAgent*
