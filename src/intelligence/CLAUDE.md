# Intelligence Layer — Developer Reference

## Plugin Tiers (111 total + 2 aggregation)

### I1 Technical Indicators (25) — incremental `compute_next()`
Trend, Momentum, Volatility, Volume. Full list: `TIER_I1` in `register_plugins.py`.

### I2 Composite Events (11) — on I1 features, before I3
MACDEvents, RSIEvents, StochasticEvents, ADXEvents, VolumeEvents, MomentumAcceleration, DonchianPosition, OBVMomentum, DerivativeOscillator, ExhaustionScore, AccelerationRegime.
Defined in `composites/`. Shared utilities in `composites/common.py`: `is_num`, `crossover_detect`, `threshold_cross`, `track_bars_ago`.

### I3 Structure (7) · I4 Context (11)
- **I3**: swing detector, S/R, trend structure, MarketProfile, SessionLevels, FibonacciZones, SwingMomentum
- **I4**: vol/trend/momentum regime, GARCH volatility, HurstExponent, ShannonEntropy, Kalman trend, SessionContext, MTFVolatility, AnchoredVWAP, VolumeProfile

### I5 Patterns (15) · I6 SMC (13) · I6 Confluence (1)
- **I5**: RSI divergence, squeeze, vol divergence, MACD divergence, CMF divergence, confluence, trend confluence, DoubleTopBottom, HeadShoulders, TriangleWedge, Candlestick, FlagPennant, CupHandle, MeasuredMove, KeyLevelReaction
- **I6 SMC**: BOS/CHoCH, FVG, Order Blocks, HMM regime, liquidity pools, supply/demand, BOCPD changepoint, liquidity sweeps, ICTKillzones, AMDCycle, BreakerBlocks, MitigationBlocks, PremiumDiscount
- **I6 Confluence**: CrossTimeframeConfluence — recency-weighted multi-TF alignment (10 output fields)

### I7 Trading Setups (28) + Aggregation (2)
TrendFollowing, MeanReversion, LiquiditySweepReclaim, MTFAlignment, SqueezeExpansion, VWAPDeviation, MomentumBreakout, LiquidityHunt, SupplyDemandSetup, CHoCHReversal, FVGFill, PatternCompletion, DivergenceStack, RegimeTransition, GapAnalysisSetup, CandlestickPatternSetup, SessionExtremesSetup, FailedBreakout, ORB15, ORB30, PrevDayLevelTest, SecondLegContinuation, VCP, AnchoredVWAPReversion, VWAPReclaim, POCRejection, HVNRejection, LVNBreakout.

**GARCH/Kalman quality gates** wired into MeanReversion, VWAPDeviation, SqueezeExpansion.

**`regime_type` class attribute** (Phase 12, mandatory on all I7 plugins): `"trend"` | `"mean_reversion"` | `"any"`. Used by aggregator regime gate — trend plugins suppressed in ranging regime (hmm_regime=0), mean-reversion plugins suppressed in trending regime (hmm_regime=1/2). New I7 plugins must declare this or `validate_tier()` will not catch the omission but the gate will silently misfire.

**Aggregator `perf_multiplier`** (Phase 14): reads `setup_performance` table at startup and every 15 min. Setups with `sample_size < 30` use multiplier=1.0 (no effect). Outperforming setups rank higher in `all_ranked`. `active` must always be derived from `all_ranked`, not raw `signals` — see gotchas.

## Plugin Protocol

- Class: `PatternPlugin`. Register in `register_all_plugins()`, add to `TIER_*` constant.
- Use `frozenset[str]` for `outputs`/`capability_tags`, `tuple[InputSpec, ...]` for `inputs` — not `set`/`list`.
- Tier lists (`TIER_I1`…`TIER_I7`) in `register_plugins.py` — single source of truth; `validate_tier()` hard-crashes on missing names.

## AI Narrative Service

- Consumer group: `"ai_narrative"`, starts at `"$"` (skips backlog on restart)
- Timeframes: `["1m", "5m", "15m", "1h"]` — matches signal_generator_service
- Ollama timeout: 60s (qwen3.5:9b on AMD ROCm iGPU)

## LLM Provider Chain (`llm_providers.py`)

| Tier | Provider | Model | Role |
|------|----------|-------|------|
| 1 | `OpenRouterProvider` | free models | Primary |
| 2 | `OllamaProvider` | qwen3.5:9b / phi4-mini:3.8b | Offline fallback |

- `LLMChain` tries in order, returns first non-None. `chain.last_provider_id` = which succeeded.
- Adding providers: implement `async generate(prompt, system, max_tokens, timeout) -> str | None`, add Settings fields `*_api_key`, `*_base_url`, `*_model`, `*_timeout_sec`.
- Keys in `.env`: `openrouter_api_key` (empty string → chain skips, falls back to Ollama).

**LLM audit streams** (Phase 16): every call → `llm_calls:stream` (maxlen=500); every signal exit → `llm_outcomes:stream` (maxlen=200). `llm_writer_service` consumes both, writes to `llm_calls` hypertable, back-fills outcome fields, recomputes `llm_model_scores` every 15 min. Adaptive routing: when a model reaches `is_significant=True` (p<0.05, n≥30), it moves to position 0 in the provider chain for that `call_type + regime` combination.

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
- **At signal fire** (signal_generator_service): `determined_at`, `signal_computed_at`, `ask_at_signal`, `bid_at_signal`, `market_price_at_signal`, `entry_zone_low`, `entry_zone_high`, `zone_valid_at_signal`
- **At activation** (signal_lifecycle_service): `activation_price`, `zone_entry_pct`, `bars_to_activation`
- **At exit** (signal_lifecycle_service): `mae`, `mfe`, `bars_in_trade`, `outcome`
- **`bar_close_price` is implicit** — not stored in `signal_ledger`; JOIN to `intelligence_features` on `(symbol, feature_ts, feature_tf)` gives full bar OHLCV
- **`intelligence_features` i7/i8 columns**: `i7` JSONB array = all ranked setups that fired on that bar; `i8` JSONB = LLM narrative metadata (model, confidence, summary). Written by `feature_writer_service` via enrichment streams.

## Gotchas

- **Qwen3 thinking mode**: `content` empty if `num_predict < 500` (thinking tokens consume budget). Use `/no_think` prefix or `num_predict ≥ 500`.
- **Local Ollama models**: qwen3.5:9b (per-signal), phi4-mini:3.8b (group synthesis) (Docker `:11434`).
- **Plugin state write-back is load-bearing**: GARCH/HMM fully reassign `_state` — always write back after `compute_full()`.
- **Aggregator `active` must come from `all_ranked`**: `_build_all_ranked()` copies signal dicts so raw signals never get `adjusted_rank`. Derive `active` from `all_ranked`, not from the raw `signals` list — otherwise `perf_weights` silently have no effect on winner selection.
