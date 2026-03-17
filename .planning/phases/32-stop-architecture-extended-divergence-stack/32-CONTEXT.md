# Phase 32: Stop Architecture + Extended Divergence Stack - Context

**Gathered:** 2026-03-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Centralize stop placement in `trade_framer.py` with a 3-tier `stop_basis` label and per-signal structural metadata, add Chandelier GARCH-adaptive trailing stop + staleness expiry with shadow tracking to the lifecycle layer, and upgrade `DivergenceStack` from a 2-input AND-gate to a 5-input regime-conditioned weighted convergence score — with three new I5 divergence plugins, regime-adaptive weight infrastructure, and continuous feature logging on every bar.

Design framing: Renaissance — instrument everything, segment relentlessly, earn the right through proof.

</domain>

<decisions>
## Implementation Decisions

### stop_basis Classification

- **All structural levels = `structure_snap`**: demand zone, sweep level, OB bottom/top, swing low/high, S/R nearest support/resistance — any stop that landed on a structural level regardless of tier
- **`garch_adaptive`**: ATR fallback path when `garch_vol_regime` is present (0/1/2) — GARCH scaling always applied (0.8×/1.0×/1.35×)
- **`atr_static`**: ATR fallback path only when `garch_vol_regime` is missing/null — in practice a rare/dead-code path given I4 is always running
- **Explicit 1.5×ATR proximity gate**: structural stop must be within 1.5×ATR of the raw ATR fallback level to qualify as `structure_snap`; if outside that band, degrade to `garch_adaptive`
- **FVG low added to stop hierarchy**: `fvg_bottom` (longs) / `fvg_top` (shorts) added as a structural stop candidate in `trade_framer.py` — currently missing from the hierarchy despite being in the SIG-01 spec
- **`stop_basis` → `intelligence_features`**: field must appear in the intelligence features written per bar (not just `signal_ledger`) so ML pipeline can use it as a predictor

### stop_basis Feature Fields (Renaissance: instrument everything)

- **`stop_structure_type`**: which specific structural level was used — `"ob_bottom"` | `"ob_top"` | `"demand_zone"` | `"supply_zone"` | `"sweep_level"` | `"swing_low"` | `"swing_high"` | `"sr_support"` | `"sr_resistance"` | `"fvg_low"` | `"fvg_high"` | `"atr_fallback"`; logged per signal for per-type performance segmentation
- **`stop_structure_age_bars`**: how old the structural level is (bars since it was established); fresh structure vs stale structure is signal — Renaissance: freshness is a learnable predictor
- **`structural_stop_distance_atr`**: `abs(structural_stop - atr_fallback_stop) / atr`; the 1.5×ATR gate is a hypothesis — log the actual distance so training pipeline can find the empirically optimal threshold
- All three fields logged in both `signal_ledger` and `intelligence_features`

### Chandelier Trailing Stop (SIG-03)

- **Volatility source**: `garch_sigma` (I4 GARCH output) preferred over ATR-14 — GARCH is the statistically correct time-varying volatility estimate for financial time series with volatility clustering. ATR-14 as fallback when GARCH unavailable
- **`chandelier_vol_source`**: `"garch_sigma"` | `"atr_14"` — logged per signal as a training feature
- **Formula**: `highest_high_since_entry - 3×vol` (long); `lowest_low_since_entry + 3×vol` (short); stop tightens monotonically, never widens
- **`trailing_stop_price` in `signal_ledger`**: persisted as a JSONB array `[{ts, price}]` — full tightening history per bar while signal is active; not scalar overwrite. Rationale: the tightening trajectory is signal — rate of tightening predicts outcome class (fast tightening = strong trend = target_full; slow/flat = chop = stopped_in_trade)
- **`trailing_stop_tightening_rate`**: slope of the last 5 bars of trailing stop movement — pre-computed scalar alongside the JSONB history so ML layer has a ready-to-consume feature
- **`highest_high_since_entry` / `lowest_low_since_entry`**: tracked per signal in lifecycle state from activation bar

### Staleness Score + condition_expired (SIG-04)

- **Primary trigger**: HMM regime flip — `hmm_regime` at current bar ≠ `hmm_regime_at_fire`. Store `hmm_regime_at_fire` in `signal_ledger` at signal generation time
- **Secondary trigger**: continuous sigma ratio — `sigma_drift_ratio = current_garch_sigma / garch_sigma_at_fire`. Threshold > 2.0× (initial hypothesis — log actual ratio so training pipeline finds optimal threshold). Store `garch_sigma_at_fire` in `signal_ledger` at generation time
- **`staleness_score`**: composite 0.0–1.0 per bar = weighted blend of regime drift magnitude + sigma ratio; computed and logged per bar for every active signal (training feature, not just trigger)
- **Confirmation window**: `condition_expired` fires when `staleness_score > threshold for 3 consecutive bars` — prevents a single noisy bar killing a valid signal
- **`staleness_trigger_reason`**: `"hmm_regime_flip"` | `"vol_drift"` | `"both"` — logged for per-reason outcome segmentation; enables training pipeline to evaluate whether regime-based vs vol-based expiry has different alpha implications
- **Termination**: signal terminated immediately as `condition_expired` (real outcome for position management)
- **Shadow tracking** (Renaissance: earn the right through proof on the staleness logic itself):
  - When `condition_expired` fires, set `shadow_tracking_start_ts`
  - Continue tracking `shadow_mae`, `shadow_mfe`, `shadow_outcome` for remaining TTL — no position, pure data
  - After N≥30 condition_expired events, training pipeline answers: "what % would have hit T1 anyway?" — validates or invalidates the staleness thresholds
  - Fields added to `signal_ledger`: `shadow_tracking_start_ts`, `shadow_mae`, `shadow_mfe`, `shadow_outcome`

### Divergence Stack — 5-Input Weighted Convergence Score (DIV-04)

- **Full replacement of AND-gate**: the "LOCKED DESIGN: dual-gate non-negotiable" docstring is a human prior; the new weighted score replaces it entirely. RSI and volume are inputs with assigned weights (0.30+0.20), not a mandatory gate. Data will prove which inputs matter
- **Initial weights** (hypotheses, not permanent): RSI=0.30, MACD=0.25, Volume=0.20, OBV=0.15, CMF=0.10
- **Weights stored in config** (not hardcoded): tunable without a code deploy; weight updater modifies them after N≥30 divergence signals per input
- **Regime-conditioned weights**: separate weight sets per `hmm_regime` (0=ranging, 1=trending, 2=strong_trend); initially all regimes use same weights; training pipeline discovers per-regime optimal weights. Structure: `{hmm_regime: {input: weight}}`
- **Gate**: `weighted_score > 0.40 AND n_agreeing >= 3` — both thresholds are initial hypotheses; 0.40 and 3 are starting points for the training pipeline to validate
- **Log every bar (not just on fire)**: `div_weighted_score`, `div_n_agreeing`, per-input scores always logged to `intelligence_features` — near-misses (score=0.38) are as valuable as fires for threshold learning
- **Per-input feature fields logged on every bar**:
  - `{input}_divergence_age_bars` — consecutive bars each divergence has been active (persistence = conviction)
  - `{input}_divergence_magnitude` — actual slope delta between price and indicator (not just binary/strength)

### Three New I5 Divergence Plugins (DIV-01, DIV-02, DIV-03)

- **DIV-01 — `macd_divergence.py`**: peak/trough detection approach matching `rsi_divergence.py` (min_lookback=50, neighbor=5); consumes existing `macd_histogram_12_26_9` from I1; outputs `macd_div_bullish`, `macd_div_bearish`, `macd_div_strength`
- **DIV-02 — OBV divergence — extend `volume_divergence.py`**, NOT a new plugin: `volume_divergence.py` already computes OBV internally (cumulative close-direction volume + linear regression slope). Creating a separate `obv_divergence.py` would duplicate the computation and introduce correlated features (multicollinearity in training data). Solution: extend `volume_divergence.py` to also output `obv_div_bullish`, `obv_div_bearish`, `obv_div_strength` alongside existing `vol_div_*` outputs
- **DIV-03 — `cmf_divergence.py`**: linear regression slope approach matching `volume_divergence.py` (min_lookback=30, lookback=20); consumes existing `cmf_20` from I1; outputs `cmf_div_bullish`, `cmf_div_bearish`, `cmf_div_strength`
- **`divergence_lookback_bars`**: logged per plugin output so training pipeline can run sensitivity analysis on the lookback period; initial lookbacks match existing pattern family, data finds the optimal
- All three plugins compute and log on every bar regardless of whether a signal fires — always flowing into `intelligence_features`

### Claude's Discretion
- Exact staleness score formula (weighting of regime drift vs sigma ratio components)
- Exact `structural_stop_distance_atr` implementation in trade_framer (verify epsilon handling)
- JSONB array append vs separate trailing stop history table (if JSONB write contention arises at scale)
- Exact config format for regime-conditioned divergence weights (nested dict vs DB table)
- `divergence_age_bars` reset condition (reset to 0 when divergence flips direction vs decays below threshold)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Stop Architecture
- `src/intelligence/trading/trade_framer.py` — existing 5-tier structural stop hierarchy; SIG-01/SIG-02 extend this with stop_basis label, FVG addition, and GARCH multipliers
- `src/intelligence/schemas.py` — canonical IntelligenceEvent fields; verify `garch_sigma`, `garch_vol_regime`, `fvg_bottom`, `fvg_top` exist before planning

### Signal Lifecycle
- `src/intelligence/trading/lifecycle_tracker.py` — pure `evaluate_signal()` function; SIG-03 Chandelier and SIG-04 staleness added here
- `services/signal_lifecycle_service.py` — orchestrates lifecycle ticks; shadow tracking fields written here
- `src/intelligence/trading/signal_ledger.py` — `LedgerEntry` dataclass; new fields: `stop_basis`, `stop_structure_type`, `stop_structure_age_bars`, `structural_stop_distance_atr`, `hmm_regime_at_fire`, `garch_sigma_at_fire`, `trailing_stop_price` (JSONB), `trailing_stop_tightening_rate`, `staleness_score`, `staleness_trigger_reason`, `shadow_tracking_start_ts`, `shadow_mae`, `shadow_mfe`, `shadow_outcome`

### Divergence Plugins
- `src/intelligence/trading/divergence_stack.py` — current 2-input AND-gate; fully replaced by weighted score
- `src/intelligence/patterns/rsi_divergence.py` — pattern to follow for `macd_divergence.py` (peak/trough approach, min_lookback=50, neighbor=5)
- `src/intelligence/patterns/volume_divergence.py` — extend to add `obv_div_*` outputs; also pattern for `cmf_divergence.py` (linear regression slope, lookback=20)
- `src/intelligence/register_plugins.py` — TIER_I5 and TIER_I7 lists; `macd_divergence`, `cmf_divergence` added to TIER_I5; `volume_divergence` already in TIER_I5 (extended in place)

### Plugin Protocol
- `src/intelligence/CLAUDE.md` — tier protocol, plugin interface, `regime_type` attribute requirements
- `src/intelligence/trading/signal_schema.py` — signal output field schema; new stop fields must be consistent with this

### Requirements
- `.planning/REQUIREMENTS.md` SIG-01 through SIG-05, DIV-01 through DIV-04 — full specs

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `trade_framer.py`: existing 5-tier stop hierarchy (demand→sweep→OB→swing→S/R→ATR fallback) — extend with stop_basis label, FVG tier, and GARCH multiplier; don't rewrite
- `lifecycle_tracker.py` `evaluate_signal()`: add Chandelier tracking state (`highest_high_since_entry`, JSONB history) and staleness score computation here
- `rsi_divergence.py` `find_peaks()` / `find_troughs()`: reuse for `macd_divergence.py` — identical peak/trough detection approach
- `volume_divergence.py`: OBV already computed here; extend outputs rather than create new plugin; reuse for `cmf_divergence.py` pattern
- `garch_volatility.py` (I4): outputs `garch_sigma` and `garch_vol_regime` — both consumed by Phase 32; confirm field names in `IntelligenceEvent`

### Established Patterns
- GARCH-first, ATR fallback: consistent theme across SIG-01/SIG-02/SIG-03 — `garch_sigma or atr_14` is the canonical pattern
- `_state` dict keyed by `(symbol, timeframe)`: required for Chandelier's `highest_high_since_entry` tracking and divergence age tracking
- Plugin always-log pattern: compute on every bar, fire signal only when threshold crossed — divergence plugins follow this already
- `signal_ledger.py` `LedgerEntry` dataclass: add new fields here; `insert_signals()` passes them to DB

### Integration Points
- DB migration required: new columns on `signal_ledger` (all new fields above); new migration `035_stop_basis_and_divergence_stack.sql`
- `feature_writer_service.py`: `stop_basis`, `stop_structure_type`, `div_weighted_score`, per-input divergence scores must flow through to `intelligence_features` JSONB — verify enrichment path
- `signal_generator_service.py`: writes `hmm_regime_at_fire` and `garch_sigma_at_fire` at signal fire time — these are point-in-time snapshots, not lifecycle fields
- `services/signal_lifecycle_service.py`: writes Chandelier JSONB updates and staleness score per lifecycle tick; writes shadow tracking fields at `condition_expired`

</code_context>

<specifics>
## Specific Ideas

- Renaissance framing throughout: fixed thresholds (1.5×ATR, score>0.40, n_agreeing≥3, sigma_drift>2.0×) are initial hypotheses, not permanent gates — log the continuous values so the training pipeline can find empirically correct thresholds
- The "LOCKED DESIGN" docstring in `divergence_stack.py` is explicitly overridden — the AND-gate was a human prior; the weighted score replaces it completely
- Regime-conditioned divergence weights is the long-term architecture: initially all regimes use the same weights, training pipeline discovers per-regime optimal weights after N≥30 per regime per setup
- Shadow tracking on `condition_expired` is the mechanism to validate the staleness logic itself — without counterfactual data, you can't know if your staleness thresholds are adding or destroying alpha
- `volume_divergence.py` extension (not new `obv_divergence.py`) is important for ML data quality — duplicate OBV computation introduces correlated features; one canonical computation per feature

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 32-stop-architecture-extended-divergence-stack*
*Context gathered: 2026-03-16*
