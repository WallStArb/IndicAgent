# Phase 36: Microstructure Plugins - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Add Order Flow Imbalance (OFI) and Cumulative Volume Delta (CVD) as live I1 features in
`indicator_service`, then create 7 new I7 plugins that transform those features into
tradeable microstructure signals. No new services. No new Kafka topics beyond a second
consumer in `indicator_service`. This phase delivers the system's first microstructure
signal layer.

Design framing: Renaissance — instrument everything, segment relentlessly, earn the right
through proof. Every plugin is independently tunable and composable.

</domain>

<decisions>
## Implementation Decisions

### Tick Data Strategy

- **True tick accumulation as primary path**: `indicator_service` adds a second Kafka
  consumer on `market.ticks` (topic via `topic_market_ticks()`). Buffer ticks per
  `(symbol, timeframe)` during each bar window; flush OFI/CVD at bar close.
- **Bar-level proxy as automatic fallback**: when tick data is missing for a bar (gaps,
  reconnects), fall back to `(close - low) / (high - low + ε) × volume`. No manual
  switching required.
- **Every bar logs `ofi_variant`**: value is `"tick"` or `"proxy"`. Logged in I1 output
  and surfaced in `intelligence_features` JSONB for post-hoc auditability. Satisfies
  OFI-01 audit requirement.
- Tick model fields used: `Tick.price`, `Tick.size`, `Tick.bid`, `Tick.ask` from
  `src/providers/base.py`. Tick rule: `price > prev_price` → buy volume; `price <
  prev_price` → sell volume; equal → neutral (no volume assigned).

### Plugin Structure

**7 separate I7 plugins** — full separation of concerns, independently tunable,
individually composable in the CIS aggregator. All registered in `TIER_I7` in
`src/intelligence/register_plugins.py`.

**OFI-based (3 plugins):**
- `trad_OFIContinuation` — sustained directional OFI over N bars; institutional
  accumulation/distribution; `regime_type="trend"`
- `trad_OFIDivergence` — OFI direction disagrees with price direction (exhaustion);
  `regime_type="mean_reversion"`
- `trad_OFISpike` — single-bar OFI > 2σ above rolling mean (breakout catalyst);
  `regime_type="any"`

**CVD-based (3 plugins):**
- `trad_CVDDivergence` — CVD direction disagrees with price direction; logs
  `dual_divergence=True` when OFI also diverges simultaneously; `regime_type="mean_reversion"`
- `trad_CVDSpike` — single-bar CVD spike > 2σ, symmetric with `trad_OFISpike`;
  `regime_type="any"`
- `trad_DeltaExhaustion` — large CVD spike but price fails to follow through (strong
  institutional buy, price can't hold); classic tape-reading exhaustion;
  `regime_type="mean_reversion"`

**Dual conviction plugin (1 plugin, shadow mode):**
- `trad_DualDivergence` — fires only when both OFI and CVD diverge simultaneously. Starts
  with `is_shadow=True`. Confidence calibrated from empirical win rates before promotion to
  production. Most modular approach: independently tunable fire conditions and confidence
  curve, not a boost on an existing plugin.

### Dual Divergence Handling

- `trad_DualDivergence` is a standalone plugin — not a confidence multiplier on
  `trad_CVDDivergence`
- Starts in shadow mode — earns production confidence through empirical win rate data
  (Renaissance principle: earn the right through proof)
- `trad_CVDDivergence` still logs `dual_divergence=True` as a metadata field for
  cross-referencing in `signal_ledger`
- The two plugins are decoupled: `trad_CVDDivergence` can fire without `trad_DualDivergence`
  promoting

### I1 Feature Outputs

From `indicator_service` per bar (feeding into I1Indicators via `extra='allow'`):
- `ofi_ewma_5` — 5-bar EWMA of OFI values
- `ofi_ewma_20` — 20-bar EWMA of OFI values (primary per OFI-02)
- `ofi_divergence` — OFI direction vs. price direction over same window (float, signed)
- `ofi_spike_z` — current OFI vs. 100-bar rolling mean in z-score units
- `ofi_variant` — `"tick"` or `"proxy"` (which path computed this bar)
- `cvd` — running cumulative volume delta (Σ buy_vol − sell_vol, reset per session)
- `cvd_slope_5bar` — 5-bar linear slope of CVD
- `cvd_divergence` — CVD direction vs. price direction (float, signed)
- `cvd_spike_z` — current single-bar CVD vs. 100-bar rolling mean in z-score units

### Claude's Discretion

- Exact EWMA decay factors (beyond the 5-bar and 20-bar spans specified in OFI-02)
- Session reset boundary for CVD (market open vs. continuous — default to session reset)
- Spike z-score lookback window (100-bar suggested in requirements, adjust based on data)
- Exact `trad_DualDivergence` N-bar confirmation window before firing

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements (phase scope)
- `.planning/REQUIREMENTS.md` §OFI-01, OFI-02, OFI-03, CVD-01, CVD-02 — full feature
  and plugin specifications including bar-proxy formula and EWMA spans

### I1 Plugin Pattern (reference implementation)
- `src/intelligence/indicators/obv.py` — canonical incremental I1 plugin: `compute_full` +
  `compute_next` with `_state` dict for per-bar accumulation. OBV is the closest
  structural analog to CVD.
- `src/intelligence/indicators/cmf.py` — reference for volume-flow indicator pattern

### I7 Plugin Pattern (reference implementation)
- `src/intelligence/trading/momentum_breakout.py` — canonical I7 plugin: `regime_type`,
  `_no_signal()` for early exits, `_state` dict only when cross-bar tracking needed
- `src/intelligence/trading/divergence_stack.py` — reference for divergence-type I7 plugin

### Schema and Bus
- `src/intelligence/schemas.py` — `I1Indicators` (uses `extra='allow'` — new OFI/CVD
  fields land without schema migration), `IntelligenceEvent` typed bus structure
- `src/providers/base.py` — `Tick` model: fields `price`, `size`, `bid`, `ask`,
  `bid_size`, `ask_size`, `source`

### Stream Keys and Topics
- `src/core/stream_keys.py` — `topic_market_ticks()` for second Kafka consumer;
  `topic_indicators()` for indicator output

### Plugin Registry
- `src/intelligence/register_plugins.py` — `TIER_I7` list; all 7 new plugins must be
  registered here; `registry.validate_tier()` hard-crashes at startup on any missing name

### Prior Phase Decisions
- `.planning/phases/35-calibration-tod-multiplier-cis-kalman-filter/35-CONTEXT.md` —
  calibration pipeline decisions; new plugins must be compatible with TOD multiplier and
  CIS Kalman filter flow

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `OBVPlugin` (`src/intelligence/indicators/obv.py`): incremental accumulator with state
  (prev_close + cumulative). CVD plugin is structurally identical — swap `obv` for `cvd`,
  use tick-rule buy/sell split instead of direction × volume.
- `exhaustion_utils.py` (`src/intelligence/trading/`): existing exhaustion guard logic
  usable in `trad_DeltaExhaustion`
- `CMFPlugin` (`src/intelligence/indicators/cmf.py`): volume-flow pattern similar to OFI
  proxy computation

### Established Patterns
- I1 plugins live in `src/intelligence/indicators/`, follow `compute_full` + `compute_next`
  interface with `_state: dict = field(default_factory=dict)`
- I7 plugins live in `src/intelligence/trading/`, must declare `regime_type`, `name`
  (prefixed `trad_`), `outputs`, `inputs`, and use `self._no_signal()` for early exits
- `I1Indicators` uses `extra='allow'` — new OFI/CVD field names don't require schema
  changes, just add the plugin outputs
- Plugin registry: `TIER_I7` in `register_plugins.py` is the single source of truth;
  `validate_tier()` enforces it at startup

### Integration Points
- `indicator_service`: currently one Kafka consumer (bars). Adding second consumer for
  `market.ticks`. Tick buffer per `(symbol, timeframe)`, flushed at bar close alongside
  existing bar processing.
- `trad_DualDivergence`: reads `ofi_divergence` and `cvd_divergence` from I1 features
  (both available in the IntelligenceEvent by the time I7 runs)
- All 7 plugins register in `TIER_I7` — aggregator picks them up automatically with no
  other wiring changes

</code_context>

<specifics>
## Specific Ideas

- Renaissance framing throughout: every plugin is independently tunable and composable.
  No cross-plugin dependencies. The aggregator is the composition layer.
- `trad_DualDivergence` earns its production confidence through empirical data — never
  assign a confidence multiplier without statistical proof (p < 0.05, N >= 30)
- `ofi_variant` field acts as a labeled training column — future ML can train separately
  on tick-derived vs proxy-derived OFI features to quantify proxy degradation
- User emphasis: modularity, separation of concerns, and flexibility throughout. Build
  for refinement and enhancement — each plugin should be adjustable in isolation.

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope. Cross-asset intelligence (XA plugins) is
  Phase 37.

</deferred>

---

*Phase: 036-microstructure-plugins*
*Context gathered: 2026-03-18*
