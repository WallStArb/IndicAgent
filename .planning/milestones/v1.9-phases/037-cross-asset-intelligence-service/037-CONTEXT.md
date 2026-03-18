# Phase 37: Cross-Asset Intelligence Service - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

New `cross_asset_service` microservice that computes spread features across equity index futures (ES, NQ, RTY, YM) and publishes them to a dedicated Kafka topic. One new I7 plugin (`trad_CrossAssetDivergence`) consumes these features via frame injection in `signal_generator_service`. No new I4/I5 plugins. No dashboard changes in this phase.

**Phase 37 scope: EQ_INDEX group only.** Architecture is group-configurable for future expansion (SECTOR_ETF, RATES, RISK_PROXY groups in later phases).

</domain>

<decisions>
## Implementation Decisions

### Architecture — Service Design (Renaissance: Microservice SoC, Plugin Modularity)

- New service: `services/cross_asset_service.py` following existing service template (signal_generator_service.py pattern)
- Feature flag: `CROSS_ASSET_ENABLED=false` default — zero behavioral change when disabled
- Service subscribes to `topic_intelligence(env_name)` with `group_id="cross_asset_group"` — separate consumer group gets its own copy of every intelligence message
- Publishes to `topic_cross_asset(env_name)` (new stream key in `src/core/stream_keys.py`)
- Metrics port: 9118 (next available after :9117)
- Logs: `logs/cross_asset_service.log` via `setup_service_logging()`
- Systemd unit: `production/systemd/indicagent-cross-asset.service`, `After=indicagent-market-analysis.service`

### Architecture — Group-Configurable Design (Renaissance: Segment Relentlessly)

Design the service to be group-configurable from day 1:
```python
CROSS_ASSET_GROUPS = {
    "EQ_INDEX": ["ES", "NQ", "RTY", "YM"],   # Phase 37 — implemented
    # "SECTOR_ETF": ["XLK", "XLE", "XLF", "XLV", "XLI", "XLU", "XLC", "XLY"],  # future
    # "RATES": ["ZN", "ZF", "ZB", "ZT"],  # future (yield curve)
    # "RISK_PROXY": ["ES", "TLT", "GLD", "VX"],  # future (risk-on/off)
}
```
Topic key: `"EQ_INDEX:1m"` (group:tf). Plugin receives `group` field in signal output.

### Startup Behavior — Seed from DB (Renaissance: Never Waste Labeled Data)

- On service start, query `intelligence_features` for last `window_bars` rows per (symbol, tf) to pre-warm rolling windows
- Fallback: if DB seed fails, wait for live bars (log warning, don't crash)
- Hard require all 4 symbols have ≥ `window_bars` history before publishing corr_break
- ES/NQ and ES/RTY spreads may compute independently when their pair has sufficient history

### Gap Handling (Renaissance: Data Quality Over Model Complexity)

- Track last-received bar timestamp per (symbol, tf)
- If any symbol in the group is stale > 1 TF-interval (1m→60s, 5m→300s, 15m→900s, 1h→3600s), stop publishing spread features for that tf
- Include `data_quality_score` (float 0-1: fraction of group symbols with fresh data) in every published payload
- Stale detection uses TF-specific TTL constants from `src/core/service_utils.py`

### Spread Features — Core (XA-02)

Three required features:
- `es_nq_spread_z`: z-scored 5-bar return spread (ES 5-bar return minus NQ 5-bar return), z-scored over 20-bar rolling window
- `es_rty_spread_z`: same computation for ES vs RTY pair
- `eq_corr_break`: abs diff between 5-bar rolling correlation and 20-bar rolling correlation of all 4 equity index returns

Z-score baseline: 20-bar rolling window. Guard: if rolling_std < 1e-8, publish spread=0 with a `low_vol_flag=True` field. Clamp output to (-10, 10).

### Spread Features — Renaissance Enhancements

Additional features published in cross_asset payload:
- `eq_vol_imbalance`: ratio of ES relative volume to NQ relative volume (ES_vol/ES_avg_vol ÷ NQ_vol/NQ_avg_vol). When >1.5, confirms ES is structurally leading. Confidence boost in plugin.
- `active_pair`: which pair has the highest |spread_z| — "ES_NQ" or "ES_RTY"
- `pairs_confirming`: count of pairs with |spread_z| > threshold (0, 1, or 2) — drives confidence multiplier
- `data_quality_score`: float 0-1 (fraction of group with fresh data)
- `low_vol_flag`: bool (true when spread std is near-zero, signal unreliable)

Leadership score (rolling 20-bar cross-correlation lag) deferred to future phase — complex, not required for v1.

### Timeframe Scope (Renaissance: Segment Relentlessly, Instrument Everything)

All 4 TFs (1m, 5m, 15m, 1h) from day 1. Different timeframes capture structurally different dynamics — 1m spread divergence is short-term noise, 1h spread divergence is structural leadership shift.

`signal_generator_service` caches latest cross_asset snapshot per tf: `_cross_asset_cache: dict[str, dict]` keyed by tf. Plugin receives current-tf snapshot. Service also injects the 5m snapshot when processing a 1m bar (for multi-TF confirmation).

### Multi-TF Snapshot Injection (Renaissance: Confirmation Across Resolutions)

When `signal_generator_service` constructs frames for a 1m bar, inject both:
- `frames["cross_asset"]` — current-TF snapshot (1m)
- `frames["cross_asset_5m"]` — 5m snapshot (if available in cache)

Plugin uses `cross_asset_5m` presence to boost confidence:
- 1m divergence only: base confidence
- 1m AND 5m both divergent in same direction: confidence × 1.2

### Feature Persistence (Renaissance: Never Drop Data, Every Measurement = Training Sample)

`feature_writer_service` subscribes to `topic_cross_asset(env_name)` and persists spread features to `intelligence_features` with tier field `"cross_asset"`. This is mandatory — spread features are labeled training samples that must survive service restarts.

Migration: no new table needed, `intelligence_features` JSONB `i7` or new `cross_asset` tier column in existing JSONB schema.

### Signal Direction Convention (Renaissance: Segment by Regime)

When `es_nq_spread_z > 2.0` (ES significantly outperformed NQ):
- Ranging regime (`hmm_regime=0`): ES overbought vs NQ → **short ES** (direction=-1) — mean reversion
- Trending up (`hmm_regime=1`): ES is the leader → **long ES** (direction=1) — continuation
- Trending down (`hmm_regime=2`): ES falling hardest → **short ES** (direction=-1) — continuation

Symmetric for negative spread_z (ES underperformed NQ): reverse direction.

When both pairs fire simultaneously: use the pair with highest |spread_z| as primary (`active_pair`). Report all firing pairs in `supporting_factors`. `pairs_confirming=2` gets confidence multiplier.

For `any` regime (hmm_regime not available): default to reversion logic (conservative).

### Plugin Architecture (Renaissance: Plugin Modularity, Single Responsibility)

- File: `src/intelligence/trading/cross_asset_divergence.py`
- Class: `CrossAssetDivergencePlugin`, `name="trad_CrossAssetDivergence"`
- `regime_type = "any"` — fires in all regimes, direction is regime-biased
- **Stateless** — no `_state` dict; all state injected via `frames["cross_asset"]`
- Guard: if symbol base not in `{"ES", "NQ", "RTY", "YM"}`, return `_no_signal()`
- Guard: if `frames.get("cross_asset", {}).get("ready") is not True`, return `_no_signal()`
- Fire threshold: `|spread_z| > 2.0` on the active pair
- Confidence formula:
  ```
  base = 0.55 + (|spread_z| - 2.0) * 0.05    # scale with magnitude
  if pairs_confirming == 2: base *= 1.2        # multi-pair confirmation
  if cross_asset_5m agrees: base *= 1.2        # multi-TF confirmation
  if eq_vol_imbalance > 1.5: base += 0.05      # volume confirms
  if hmm_regime_prob >= 0.75: base += 0.10     # regime clarity
  confidence = min(max(base, 0.0), 1.0)
  ```
- Registration: append `"trad_CrossAssetDivergence"` to `TIER_I7` in `src/intelligence/register_plugins.py`

### Shadow Mode / Rollout (Renaissance: Earn the Right Through Proof)

- `CROSS_ASSET_ENABLED=false` default
- Validation gate before enabling:
  - ≥30 `trad_CrossAssetDivergence` signals fired (not shadow) per regime type (trend, mean_reversion) in replay
  - p < 0.05 outcome analysis on fired signals (same bar as existing `validate_alpha.py` gate)
- Enable via `CROSS_ASSET_ENABLED=true` after validation — not a time-based gate

### Claude's Discretion

- Exact rolling window implementation (deque-based, no numpy dependency in service layer)
- Consumer group ID naming convention
- Error handling for malformed intelligence event payloads
- Exact `intelligence_features` JSONB tier key for cross_asset persistence (`"cross_asset"` vs sub-key of `"i7"`)
- Redpanda topic retention config command (follow existing pattern: `retention.ms=604800000`)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` §XA-01, XA-02, XA-03 — service spec, spread features, I7 plugin requirements

### Service Pattern (follow exactly)
- `services/signal_generator_service.py` — canonical service template: init, start/stop lifecycle, Kafka consumer/producer, SIGTERM handler, metrics, logging
- `services/tws_daemon.py` (RollMonitor) — pattern for feature-flagged conditional subscription

### Stream Keys
- `src/core/stream_keys.py` — all Kafka topic builder functions; `topic_cross_asset()` added here

### Plugin Pattern
- `src/intelligence/trading/failed_breakout.py` — canonical stateless I7 plugin: dataclass structure, `_no_signal()` shape, `outputs` frozenset, `regime_type` attr
- `src/intelligence/register_plugins.py` — `TIER_I7` list + `registry.validate_tier()` hard-crash gate

### Settings & Config
- `src/config/settings.py` — Settings class pattern, feature flag conventions, active instrument groups with sectors

### Frame Injection Pattern
- `services/signal_generator_service.py` lines 1448-1458 — `frames` dict construction; `cross_asset` key adds here
- `services/signal_generator_service.py` lines 986-1035 — `_run_setup_plugins(frames)` — how plugins receive frames

### Feature Persistence
- `services/feature_writer_service.py` — how to add a new Kafka topic subscription and persist to `intelligence_features`

### Metrics
- `src/observability/metrics.py` — `counter()`, `gauge()`, `start_metrics_server(port=9118)`

### Instrument Groups Reference
- `src/config/settings.py` lines 135-460 — all active instruments with asset_class and sector fields; defines natural group candidates

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `KafkaConsumerClient` (`src/core/kafka_utils.py`): async consumer; separate `group_id` gives cross_asset_service its own copy of intelligence messages
- `setup_service_logging()` (`src/core/service_utils.py`): standard structured logging to file
- `start_metrics_server(port)` (`src/observability/metrics.py`): Prometheus endpoint; use port 9118
- `get_active_contracts()` (`src/config/settings.py`): returns `list[Instrument]` — filter by `asset_class=FUTURES` and `sector="equity_index"` for group membership
- `IntelligenceEvent.model_validate_json()` (`src/intelligence/schemas.py`): parse intelligence topic payloads; extract `bar.c` (close) and `bar.v` (volume)

### Established Patterns
- Feature flag guard: `if not self._cross_asset_enabled: return` in all methods (Phase 38 roll monitor pattern)
- `_cross_asset_cache: dict[str, dict]` keyed by tf — same pattern as `_cross_asset_cache` and `_regime_cache` in signal_generator_service
- Kafka topic dispatch: `elif topic == _cross_asset_topic:` branch in `_process_loop` (after existing intel/ticks/sys_events branches)
- `frames` dict: currently `{"main": df, "features": features_dict}` — add `"cross_asset"` and `"cross_asset_5m"` as optional keys

### Integration Points
- `services/signal_generator_service.py` `_process_single_message()` lines 1448-1458: inject `frames["cross_asset"]` and `frames["cross_asset_5m"]` here
- `services/signal_generator_service.py` `_setup_kafka_clients()`: append `topic_cross_asset(env_name)` when `_cross_asset_enabled`
- `services/feature_writer_service.py`: subscribe to `topic_cross_asset(env_name)`, persist spread features to `intelligence_features`
- `src/intelligence/register_plugins.py` `TIER_I7`: append `"trad_CrossAssetDivergence"`
- `tests/unit/intelligence/test_i7_registration.py`: update TIER_I7 count assertion (28 + 2 from phase 36 + 1 = 31 after phase 37)

</code_context>

<specifics>
## Specific Ideas

- Renaissance framing applied throughout: "What would Jim Simons demand?" — segment relentlessly, instrument everything, earn the right through proof, never drop data
- Multi-pair confirmation (`pairs_confirming=2`) and multi-TF confirmation (1m + 5m) both apply confidence multipliers — layered confirmation, not just threshold crossing
- Group-configurable architecture from day 1 with `CROSS_ASSET_GROUPS` dict — EQ_INDEX implemented, SECTOR_ETF/RATES/RISK_PROXY defined as future groups
- SECTOR_ETF rotation (XLK, XLE, XLF, XLV, XLI, XLU, XLC, XLY) is the most natural next group — sector strength divergence signals sector rotation in progress
- `data_quality_score` in every published payload — downstream consumers can filter on signal quality, not just signal existence
- Feature persistence to `intelligence_features` is non-negotiable — cross-asset spread features are labeled training samples

</specifics>

<deferred>
## Deferred Ideas

- **Leadership score** (Granger causality proxy): rolling 20-bar cross-correlation lag — which symbol leads others by 1-2 bars. Architecturally clean addition to cross_asset payload in a future phase.
- **SECTOR_ETF group**: XLK/XLE/XLF/XLV/XLI/XLU/XLC/XLY sector rotation divergence — natural Phase 37+1
- **RATES group**: ZN/ZF/ZB/ZT yield curve spread (2s10s steepening/flattening as regime indicator) — future
- **RISK_PROXY group**: ES vs TLT vs GLD vs VX cross-class risk-on/risk-off regime — future
- **Per-pair win rate learning by regime**: track historical win rates per (pair, regime_type) and use as confidence weight — v2 ML phase
- **CIS contribution from cross-asset features**: if cross-asset divergence becomes an I4 context input feeding CIS scoring — requires schema evolution

</deferred>

---

*Phase: 037-cross-asset-intelligence-service*
*Context gathered: 2026-03-18*
