# Intelligence Layer — Developer Reference

> **ARCHIVED (2026-07-02): the I1-I7 plugin system this file documents has no live consumer.**
> `indicagent-intelligence-pipeline.service` is `failed`; its `ExecStart` points at a file
> deleted in commit `cb8f581a`. Root `CLAUDE.md` marks Feature Factory as the v3.0 replacement
> for I1-I4, with I5-I7 archived outright. Do not follow the "Creating a New I7 Plugin" or
> restart instructions below expecting them to work — kept for historical reference and for
> whenever/if this subsystem is formally reactivated or ported. LLM Provider Chain / LiteLLM /
> audit-stream sections below verified live and accurate as of 2026-07-05 (`src/core/llm/chain.py`,
> `litellm_backend.py`, `llm_writer` scoring). `shadow_registry`'s 36 rows all have `last_eval_at IS NULL` —
> confirmed dead, not just I5-I7.

## Throughput

Pipeline processes bars sequentially (one at a time). I1→4 waves→I7 = 6 sequential stages. Per-plugin timing via `_timed_plugin_call()` wrapper, histogram buckets [0.1-100ms]. Prometheus: `intelligence_pipeline_plugin_duration_ms{plugin_name=, tier=}`.

## Plugin Tiers

**Tier Flow:**
```
I1 (indicators) → I2 (composite events) → I3 (structure) → I4 (context) → I5 (patterns) → SMC → I6 (confluence) → I7 (signals)
```

**I1** (29): indicators · **I2** (11): composite events · **I3** (9): structure · **I4** (13): context (GARCH, Kalman, VWAP, VIXRegime) · **I5** (16): patterns · **SMC** (16): smart money (BOS/CHoCH, FVG, OB, HMM) · **I6** (7): confluence · **I7** (37): trading setups + 2 aggregators. See `TIER_I*` in `register_plugins.py`.

**GARCH/Kalman quality gates** wired into MeanReversion, VWAPDeviation, SqueezeExpansion.

**I7 shared utilities (check before writing any I7 code):**
All live in `src/intelligence/trading/`:

| File | Key exports | Purpose |
|------|-------------|---------|
| `plugin_utils.py` | `no_signal()`, `extract_ohlcv()`, `signal_type_for_direction()` | Canonical no-signal dict, OHLCV extraction, signal type naming |
| `atr_utils.py` | `get_atr(features)` | Null-safe I1 ATR accessor — never recompute ATR in I7 |
| `state_utils.py` | `track_consecutive_state()`, `reset_consecutive_state()` | Consecutive bar state counting |
| `confidence.py` | `compose_confidence(raw)`, `ConfluenceWeightProfile` | **ALL I7 confidence values must route through `compose_confidence()`** (clamps to [0.0, 0.95], rounds to 4dp). |
| `microstructure_utils.py` | `detect_spike_signal()` | Shared spike detection for OFI/CVD — preserves signal identity (Renaissance) |
| `volume_profile_utils.py` | `check_reversal_gate()`, `format_reversal_supporting_factors()` | POC/HVN reversal detection logic |
| `exhaustion_utils.py` | `apply_exhaustion_boost()`, `apply_exhaustion_guard()` | Exhaustion-based confidence modifiers |
| `signal_schema.py` | `make_signal_from_frame()`, `make_signal_id()`, `validate_signal()`, `REQUIRED_SIGNAL_FIELDS`, `REQUIRED_PIPELINE_FIELDS` | Sole public signal construction path, ID generation, structural validation |

**`regime_type` class attribute** (mandatory on all I7 plugins): `"trend"` | `"mean_reversion"` | `"any"`. Used by aggregator regime gate — trend plugins suppressed in ranging regime (hmm_regime=0), mean-reversion plugins suppressed in trending regime (hmm_regime=1/2). New I7 plugins must declare this or `validate_tier()` will not catch the omission but the gate will silently misfire.

**Aggregator `perf_multiplier`**: reads `setup_performance` table at startup and every 15 min. Setups with `sample_size < 30` use multiplier=1.0 (no effect). Outperforming setups rank higher in `all_ranked`. `active` must always be derived from `all_ranked`, not raw `signals` — see gotchas.

## Plugin Protocol

- Class: `PatternPlugin`. Register in `register_all_plugins()`, add to `TIER_*` constant.
- Use `frozenset[str]` for `outputs`/`capability_tags`, `tuple[InputSpec, ...]` for `inputs` — not `set`/`list`.
- Tier lists (`TIER_I1`…`TIER_I7`) in `register_plugins.py` — single source of truth; `validate_tier()` hard-crashes at missing names.
- **Shadow governance:** `shadow_registry` table; promotion requires `n >= 100 AND bootstrap_ci_lower(pnl_r) > 0.0`.
- **Adding an AI agent:** `src/intelligence/ai/AUTHORING.md`.

### Creating a New I7 Plugin

**Required reading:** `docs/signals/signals-confidence-patterns.md` - the 6 GOOD patterns, single HMM regime gate before OHLCV (I6 ctf_score is an ECL annotation, not a gate), 4-factor intrinsic confidence composite, and anti-patterns. New plugins MUST implement all 6 patterns to be compliant-by-default.

1. `src/intelligence/trading/<name>.py` — extend `PatternPlugin`, set `regime_type` (`"trend"` | `"mean_reversion"` | `"any"`), declare `shadow_only: bool = True`, use shared utilities above (esp. `compose_confidence()`, `make_signal_from_frame()`)
2. Add to `TIER_I7` in `register_plugins.py` + unit test in `tests/unit/intelligence/`
3. Restart `indicagent-intelligence-pipeline`; verify: `docker exec redpanda rpk topic consume intelligence --from-end`

## LLM Provider Chain (`src/core/llm/chain.py`)

**Unified pipeline:** cache -> rate limit -> LLM call -> guardrails -> tokens -> budget record (log only) -> metrics -> cache put -> audit. Single code path, no budget fork.

**Audit trail:** every call publishes to `llm.calls` Kafka with call_id, symbol, signal_id, regime, agent_id, prompt_version. Agents MUST use `BaseAIWorker._llm_generate()` which auto-injects all audit fields. Never call `self._llm.generate()` directly.

**Token usage:** `LiteLLMBackend.last_token_usage` populated from litellm response; `chain.last_token_usage` propagated to callers.

**AI Narrative Service:** consumer group `"ai_narrative"`, starts at `"$"` (skips backlog), timeframes `["1m", "5m", "15m", "1h"]`, Ollama timeout 60s (default nemotron-3-nano:4b; set via `OLLAMA_MODEL` in `.env`).

**NarrativeSynthesizer** (`src/intelligence/ai/narrative/narrative_agent.py`): deployed via `indicagent-narrative-compute` systemd service.

**Backend:** `LiteLLMBackend` — `litellm.acompletion()` unified interface. `OllamaProvider`/`LLMChain` classes removed. Provider configured via `OLLAMA_MODEL` in `.env` (default nemotron-3-nano:4b). `chain.last_provider_id` = which succeeded.
- Adding providers: configure via litellm model string (e.g., `"openai/gpt-4o"`) and API key env vars; see `src/core/llm/litellm_backend.py`.
- Keys in `.env`: `OLLAMA_MODEL` (overrides default).

**LLM audit streams**: every call -> `llm.calls` (Kafka); every signal exit -> `llm.outcomes`. `indicagent-llm-writer` consumes both, writes to `llm_calls` hypertable, back-fills outcome fields, recomputes `llm_model_scores` every 15 min. Per-agent scoring via `agent_id` + `prompt_version` columns. Adaptive routing: when a model reaches `is_significant=True` (p<0.05, n>=30), it moves to position 0 in the provider chain for that `agent_id + regime` combination.

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
- **Local Ollama models**: default nemotron-3-nano:4b; also available qwen3.5:4b. Set via `OLLAMA_MODEL` in `.env` (Docker `:11434`).
- **`OLLAMA_MODEL` unset = broken**: `settings.py` code default is `gemma4:e4b`, which is not pulled in the container — LLM calls fail model-not-found without the `.env` line.
- **Plugin state write-back is load-bearing**: GARCH/HMM fully reassign `_state` — always write back after `compute_full()`.
- **Aggregator `active` must come from `all_ranked`**: `_build_all_ranked()` copies signal dicts so raw signals never get `adjusted_rank`. Derive `active` from `all_ranked`, not from the raw `signals` list — otherwise `perf_weights` silently have no effect on winner selection.

**After plugin changes (v2.x, archived):** Restart `indicagent-intelligence-pipeline` (unified I1-I7). Canonical service registry: `_DAG_ORDER` in `services/service_auditor.py`.
