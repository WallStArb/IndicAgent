# Intelligence Layer — Developer Reference

## Plugin Tiers (88 total + 2 aggregation)

### I1 Technical Indicators (23) — incremental `compute_next()`
Trend, Momentum, Volatility, Volume. Full list: `TIER_I1` in `register_plugins.py`.

### I2 Composite Events (6) — on I1 features, before I3
MACDEvents, RSIEvents, StochasticEvents, ADXEvents, VolumeEvents, MomentumAcceleration.
Defined in `composites/`. Shared utilities in `composites/common.py`: `is_num`, `crossover_detect`, `threshold_cross`, `track_bars_ago`.

### I3 Structure (7) · I4 Context (7)
- **I3**: swing detector, S/R, trend structure, MarketProfile, SessionLevels, AnchoredVWAP, FibonacciZones
- **I4**: vol/trend/momentum regime, GARCH volatility, Kalman trend, SessionContext, MTFVolatility

### I5 Patterns (14) · I6 SMC (13) · I6 Confluence (1)
- **I5**: RSI divergence, squeeze, vol divergence, confluence, trend confluence, DoubleTopBottom, HeadShoulders, TriangleWedge, Candlestick, FlagPennant, CupHandle, MeasuredMove, VolumeProfile, KeyLevelReaction
- **I6 SMC**: BOS/CHoCH, FVG, Order Blocks, HMM regime, liquidity pools, supply/demand, BOCPD changepoint, liquidity sweeps, ICTKillzones, AMDCycle, BreakerBlocks, MitigationBlocks, PremiumDiscount
- **I6 Confluence**: CrossTimeframeConfluence — recency-weighted multi-TF alignment (10 output fields)

### I7 Trading Setups (17) + Aggregation (2)
TrendFollowing, MeanReversion, LiquiditySweepReclaim, MTFAlignment, SqueezeExpansion, VWAPDeviation, MomentumBreakout, LiquidityHunt, SupplyDemandSetup, CHoCHReversal, FVGFill, PatternCompletion, DivergenceStack, RegimeTransition, GapAnalysisSetup, CandlestickPatternSetup, SessionExtremesSetup.

**GARCH/Kalman quality gates** wired into MeanReversion, VWAPDeviation, SqueezeExpansion.

## Plugin Protocol

- Class: `PatternPlugin`. Register in `register_all_plugins()`, add to `TIER_*` constant.
- Use `frozenset[str]` for `outputs`/`capability_tags`, `tuple[InputSpec, ...]` for `inputs` — not `set`/`list`.
- Tier lists (`TIER_I1`…`TIER_I7`) in `register_plugins.py` — single source of truth; `validate_tier()` hard-crashes on missing names.

## AI Narrative Service

- Consumer group: `"ai_narrative"`, starts at `"$"` (skips backlog on restart)
- Timeframes: `["1m", "5m", "15m", "1h"]` — matches signal_generator_service
- Ollama timeout: 120s (qwen3:8b needs ~90s on CPU at num_predict=500)

## LLM Provider Chain (`llm_providers.py`)

| Tier | Provider | Model | Role |
|------|----------|-------|------|
| 1 | `ZAIProvider` | GLM-5 (Z.ai) | Primary |
| 2 | `OpenRouterProvider` | 100+ models | Fallback |
| 3 | `OllamaProvider` | qwen3:8b / phi4-mini:3.8b | Offline |

- `LLMChain` tries in order, returns first non-None. `chain.last_provider_id` = which succeeded.
- Adding providers: implement `async generate(prompt, system, max_tokens, timeout) -> str | None`, add Settings fields `*_api_key`, `*_base_url`, `*_model`, `*_timeout_sec`.
- Keys in `.env`: `zai_api_key`, `openrouter_api_key` (empty string → chain skips).

## Signal Lifecycle (trading/)

### Key files
- `lifecycle_tracker.py` — pure `evaluate_signal()` function; returns `Transition | None`
- `signal_ledger.py` — `LedgerEntry` dataclass + `insert_signals()` / `update_signal_status()`
- `trade_framer.py` — `frame_trade()` → `TradeFrame` with `zone_low/zone_high`

### Zone-aware activation
`_check_zone_activation()` fires when `low <= zone_high AND high >= zone_low` (bar range overlaps zone).
`zone_entry_pct`: 0.0 = proximal (ideal edge), 1.0 = distal (risky edge).

### Entry zone bounds (trade_framer._resolve_zone_bounds)
- `supply_demand_*` → nearest_demand/supply_low + high from features
- `fvg_*` → fvg_bottom + fvg_top
- `choch_*` / OB setups → ob_bottom + ob_top
- `sweep_*` / `liquidity_hunt_*` → entry ± 0.5×ATR
- All others → entry − 1.0×ATR to entry + 0.5×ATR

### 8-class outcome taxonomy
`never_activated` · `stopped_at_entry` · `stopped_in_trade` · `target_1` · `target_1_2` · `target_full` · `ttl_expired_ahead` · `ttl_expired_behind`

Stop outcomes (`stopped_at_entry` vs `stopped_in_trade`) resolved in `signal_lifecycle_service._classify_stop_outcome()` using `bars_in_trade` and MFE threshold.

### TTL computation
`bars_elapsed = (current_bar_time - signal_timestamp).total_seconds() / tf_seconds` — timestamp-based, not counter-based (fixes old silent TTL bug).

### DB fields written progressively
- **At signal fire** (signal_generator_service): `determined_at`, `ask_at_signal`, `bid_at_signal`, `market_price_at_signal`, `entry_zone_low`, `entry_zone_high`, `zone_valid_at_signal`
- **At activation** (signal_lifecycle_service): `activation_price`, `zone_entry_pct`, `bars_to_activation`
- **At exit** (signal_lifecycle_service): `mae`, `mfe`, `bars_in_trade`, `outcome`

## Gotchas

- **Qwen3 thinking mode**: `content` empty if `num_predict < 500` (thinking tokens consume budget). Use `/no_think` prefix or `num_predict ≥ 500`.
- **Local Ollama models**: qwen3:8b, gemma3n:e4b, qwen3:4b, phi4-mini:3.8b, deepscaler:1.5b (Docker `:11434`).
- **Plugin state write-back is load-bearing**: GARCH/HMM fully reassign `_state` — always write back after `compute_full()`.
