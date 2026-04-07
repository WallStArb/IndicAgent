# Intelligence Layer — Developer Reference

## Plugin Tiers (121 + 2 aggregation)

**Tier Flow:**
```
I1 (indicators) → I2 (composite events) → I3 (structure) → I4 (context) → I5 (patterns) → I6 (SMC/confluence) → I7 (signals)
```

**I1** (27): Trend/Momentum/Volatility/Volume indicators — see `TIER_I1` in `register_plugins.py`
**I2** (11): Composite events (MACDEvents, RSIEvents, etc.) — defined in `composites/`
**I3** (7): Structure (swing, S/R, MarketProfile, SessionLevels) · **I4** (13): Context (GARCH, Kalman, VWAP, VolumeProfile)
**I5** (15): Patterns (divergence, squeeze, chart patterns) · **I6** (14): SMC + confluence (BOS/CHoCH, FVG, OB, multi-TF alignment)
**I7** (36): Trading setups (TrendFollowing, MeanReversion, LiquiditySweepReclaim, etc.) + 2 aggregators

**GARCH/Kalman quality gates** wired into MeanReversion, VWAPDeviation, SqueezeExpansion.

**I7 shared utilities (check before writing any I7 code):**
All live in `src/intelligence/trading/`:

| File | Key exports | Purpose |
|------|-------------|---------|
| `plugin_utils.py` | `no_signal()`, `extract_ohlcv()`, `signal_type_for_direction()` | Canonical no-signal dict, OHLCV extraction, signal type naming |
| `atr_utils.py` | `get_atr(features)` | Null-safe I1 ATR accessor — never recompute ATR in I7 |
| `state_utils.py` | `track_consecutive_state()`, `reset_consecutive_state()` | Consecutive bar state counting |
| `confidence_utils.py` | `compose_confidence(raw)`, `capture_signal_features()`, `ConfluenceWeightProfile` | **ALL I7 confidence values must route through `compose_confidence()`** (clamps to [0.10, 0.95], rounds to 4dp). `capture_signal_features()` writes `_shadow` dict (15 keys: 2 metadata, 6 I6 CTF, 4 I4 macro, 3 exhaustion) for ML training — zero confidence modification. ML scoring (XGBoost) planned for v2.3. |
| `microstructure_utils.py` | `detect_spike_signal()` | Shared spike detection for OFI/CVD — preserves signal identity (Renaissance) |
| `volume_profile_utils.py` | `check_reversal_gate()`, `format_reversal_supporting_factors()` | POC/HVN reversal detection logic |
| `exhaustion_utils.py` | `apply_exhaustion_boost()`, `apply_exhaustion_guard()` | Exhaustion-based confidence modifiers |
| `signal_schema.py` | `make_signal()`, `validate_signal()` | Signal dict construction + validation |

**`regime_type` class attribute** (mandatory on all I7 plugins): `"trend"` | `"mean_reversion"` | `"any"`. Used by aggregator regime gate — trend plugins suppressed in ranging regime (hmm_regime=0), mean-reversion plugins suppressed in trending regime (hmm_regime=1/2). New I7 plugins must declare this or `validate_tier()` will not catch the omission but the gate will silently misfire.

**Aggregator `perf_multiplier`**: reads `setup_performance` table at startup and every 15 min. Setups with `sample_size < 30` use multiplier=1.0 (no effect). Outperforming setups rank higher in `all_ranked`. `active` must always be derived from `all_ranked`, not raw `signals` — see gotchas.

## Plugin Protocol

- Class: `PatternPlugin`. Register in `register_all_plugins()`, add to `TIER_*` constant.
- Use `frozenset[str]` for `outputs`/`capability_tags`, `tuple[InputSpec, ...]` for `inputs` — not `set`/`list`.
- Tier lists (`TIER_I1`…`TIER_I7`) in `register_plugins.py` — single source of truth; `validate_tier()` hard-crashes at missing names.

### Creating a New I7 Plugin
1. Create file in `src/intelligence/trading/<name>.py`
2. Extend `PatternPlugin`, set `regime_type` class attribute (`"trend"` | `"mean_reversion"` | `"any"`)
3. Implement `compute()` using shared utilities from table above (esp. `compose_confidence()`, `make_signal()`)
4. Add to `TIER_I7` list in `register_plugins.py`
5. Add unit test to `tests/unit/intelligence/`
6. Run integration test: `.venv/bin/pytest tests/unit/test_intelligence_pipeline_agent.py`
7. Restart service: `sudo systemctl restart indicagent-intelligence-pipeline`
8. Verify output: `docker exec redpanda rpk topic consume intelligence --from-end`

## LLM Provider Chain (`llm_providers.py`)

**AI Narrative Service:** consumer group `"ai_narrative"`, starts at `"$"` (skips backlog), timeframes `["1m", "5m", "15m", "1h"]`, Ollama timeout 60s (gemma4:e4b on AMD ROCm iGPU).

| Tier | Provider | Model | Role |
|------|----------|-------|------|
| 1 | `OpenRouterProvider` | free models | Primary |
| 2 | `OllamaProvider` | gemma4:e4b / phi4-mini:3.8b | Offline fallback |

- `LLMChain` tries in order, returns first non-None. `chain.last_provider_id` = which succeeded.
- Adding providers: implement `async generate(prompt, system, max_tokens, timeout) -> str | None`, add Settings fields `*_api_key`, `*_base_url`, `*_model`, `*_timeout_sec`.
- Keys in `.env`: `openrouter_api_key` (empty string → chain skips, falls back to Ollama).

**LLM audit streams**: every call → `llm.calls` (Kafka); every signal exit → `llm.outcomes`. `indicagent-llm-writer` consumes both, writes to `llm_calls` hypertable, back-fills outcome fields, recomputes `llm_model_scores` every 15 min. Adaptive routing: when a model reaches `is_significant=True` (p<0.05, n≥30), it moves to position 0 in the provider chain for that `call_type + regime` combination.

## Signal Lifecycle (trading/)

`lifecycle_tracker.py` — evaluate_signal() → Transition | None
`signal_ledger.py` — LedgerEntry dataclass + insert/update_status
`trade_framer.py` — frame_trade() → TradeFrame with zone_low/zone_high

**Zone activation:** bar range overlaps zone (`low <= zone_high AND high >= zone_low`)
**Outcomes:** 8-class taxonomy (never_activated · stopped_at_entry/in · target_1/1_2/full · ttl_expired_ahead/behind)
**TTL:** timestamp-based: `bars_elapsed = (current - signal_ts) / tf_seconds`
**DB fields:** written progressively (fire → activation → exit); `bar_close_price` implicit via JOIN to `intelligence_features`

## Gotchas

- **Qwen3 thinking mode**: `content` empty if `num_predict < 500` (thinking tokens consume budget). Use `/no_think` prefix or `num_predict ≥ 500`.
- **Local Ollama models**: gemma4:e4b (per-signal), phi4-mini:3.8b (group synthesis) (Docker `:11434`).
- **Plugin state write-back is load-bearing**: GARCH/HMM fully reassign `_state` — always write back after `compute_full()`.
- **Aggregator `active` must come from `all_ranked`**: `_build_all_ranked()` copies signal dicts so raw signals never get `adjusted_rank`. Derive `active` from `all_ranked`, not from the raw `signals` list — otherwise `perf_weights` silently have no effect on winner selection.

**After plugin changes:** Restart `indicagent-intelligence-pipeline` (unified I1-I7). See root CLAUDE.md Active Services table for canonical service names and metrics ports.

### Plugin Testing Workflow

1. **Unit test:** Add test to `tests/unit/intelligence/` — use `__new__()` pattern per CLAUDE.md to avoid `__init__`
2. **Integration test:** Run `.venv/bin/pytest tests/unit/test_intelligence_pipeline_agent.py` to verify I1-I7 pipeline
3. **Service restart:** `sudo systemctl restart indicagent-intelligence-pipeline` (unified I1-I7)
4. **Verify output:** `docker exec redpanda rpk topic consume intelligence --from-end` — check IntelligenceEvent output

**Quick reference — `regime_type` values:**
- `"trend"` — TrendFollowing, MomentumBreakout, etc.
- `"mean_reversion"` — MeanReversion, VWAPDeviation, SqueezeExpansion
- `"any"` — RegimeTransition, GapAnalysisSetup (works in all regimes)
