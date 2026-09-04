<!-- generated-by: gsd-doc-writer -->
# Configuration Reference

**Version:** 2.9
**Status:** current
**Last Updated:** 2026-09-04

Settings, environment variables, and contract definitions for IndicAgent. This covers
`Settings` (deployment-time, env-var-backed, requires a process restart to change). For
runtime-tunable numeric parameters (thresholds, weights, periods) that change without a
deployment, see the Adaptive Parameter Registry — `docs/foundation/adaptive-parameter-registry.md`
— which owns `config_state`/`config_history`/`ConfigService` and is a separate system from
the `Settings` class documented here.

---

## Settings Class

`src/config/settings.py` — `Settings` extends `pydantic_settings.BaseSettings`. All fields load from `.env` via environment variable aliases listed below. There is no `.env.example` in the repo — `.env` is the only source; the defaults below are the code fallback when a variable is unset.

**Access pattern:** Call `get_settings()` or pass a `Settings` instance to helpers. Never instantiate `Settings()` directly in service code.

**`get_active_contracts(settings)`** is a module-level function, not a method on `Settings`. Call it as `get_active_contracts(settings)` or `get_active_contracts()` (uses singleton).

---

## Environment Variables

### General

| Variable | Default | Description |
|----------|---------|-------------|
| `INDICAGENT_ENV` | `""` | Environment prefix for Redpanda topic namespacing |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/indicagent` | asyncpg/psycopg2 connection string |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:19092` | Redpanda bootstrap address |
| `INTELLIGENCE_THREAD_POOL_WORKERS` | `0` (auto: cpu_count × 2) | Thread pool workers for intelligence pipeline |
| `FEATURE_VECTOR_PIPELINE_SYMBOL_FILTER` | `[]` (all) | Comma-separated symbol filter for pipeline sharding |
| `INTELLIGENCE_OUTPUT_DRAIN_BATCH_SIZE` | `20` | Max items drained per OutputQueue iteration |
| `FEATURE_VECTOR_PIPELINE_QUEUE_MAXSIZE` | `100` | Per-key worker queue depth (back-pressure) |
| `REPLAY_BATCH_SIZE` | `100` | Max signals per replay-auditor cycle |
| `REPLAY_INTERVAL_SECONDS` | `300` | Seconds between replay-auditor cycles (5 min) |

### IBKR

| Variable | Default | Description |
|----------|---------|-------------|
| `IBKR_HOST` / `IB_HOST` | `172.18.176.1` | IBKR Gateway host (Docker network IP — see Infrastructure note) |
| `IBKR_PORT` / `IB_PORT` | `7497` | IBKR TWS port |
| `IB_CLIENT_ID` | `35` | IBKR client ID for provider |
| `IBKR_TIMEOUT_SEC` | `20.0` | Timeout (seconds) for IBKR API operations |
| `IBKR_MAX_SUBSCRIPTIONS` | `80` | Market data subscription cap |

> **Infrastructure note:** The IBKR Gateway runs in the `ib-gateway` Docker container. The host address used by services on the Docker network differs from the host machine loopback. The `ib-gateway` container publishes port `7497` and is accessible from the host at `127.0.0.1:7497`. Services inside Docker use the Docker network gateway IP (default `172.18.176.1`).

### LLM Providers

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_ENABLED` | `true` | Set `false` to skip local Ollama and use OpenRouter as primary |
| `OLLAMA_MODEL` | `gemma4:e4b` | Local Ollama model tag. The code default is not pulled locally — `.env` sets the effective model (`nemotron-3-nano:4b` as of 2026-09-04); a missing `.env` entry breaks all LLM calls |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_NUM_CTX` | `16384` | Ollama context window (tokens) |
| `LLM_TIMEOUT_SEC` | `60.0` | Timeout (seconds) for LLM provider API calls |
| `OPENROUTER_API_KEY` | `""` | OpenRouter API key (optional fallback provider) |
| `OPENROUTER_MODELS` | see settings.py | Comma-separated OpenRouter model slugs in priority order |

> **OpenRouter note:** `openrouter_api_key` and `openrouter_models` fields exist in `Settings` but OpenRouter is the fallback provider only when `OLLAMA_ENABLED=false` or Ollama is unavailable. The LLM chain primary is always local Ollama.

> **Ollama deployment:** Ollama runs in a Docker container (`ollama/ollama:rocm`), not systemd. Commands: `docker exec ollama ollama <cmd>`. Live services (`alpha_swarm`, `narrative_compute`) hold persistent connections — stop them before swapping models.

### Alerting

| Variable | Default | Description |
|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | `""` | Telegram bot token (empty = channel disabled) |
| `TELEGRAM_CHAT_ID` | `""` | Telegram chat ID |
| `DISCORD_WEBHOOK_URL` | `""` | Discord webhook URL (empty = channel disabled) |

### Roll Monitoring

| Variable | Default | Description |
|----------|---------|-------------|
| `ROLL_MONITOR_WINDOW_SIZE` | `100` | Rolling window size for roll detection |
| `ROLL_MONITOR_THRESHOLD_DEFAULT` | `1.2` | Volume ratio threshold for roll signal |
| `ROLL_MONITOR_POSTROLL_BARS` | `10` | Post-roll monitoring bars |
| `ROLL_MONITOR_COOLDOWN_MIN` | `30` | Cooldown minutes after roll detection |
| `ROLL_CONFIRMATION_BARS` | `3` | Bars required to confirm roll |
| `ROLL_TIME_OF_DAY_GATED` | `true` | Gate roll detection by time of day |

> **Roll-batch:** Roll detection runs as a nightly systemd timer (`indicagent-roll-batch`) at 8pm via `scripts/ops/roll/ops_roll_batch.py`. It replaces the former 24/7 `roll-compute` + `contract-metadata-writer` daemons. `inactive (dead)` between runs is correct — do not treat as failure.

### Swarm / AI

| Variable | Default | Description |
|----------|---------|-------------|
| `SWARM_MIN_TF_MINUTES` | `5` | Minimum timeframe (minutes) for swarm enrichment — skips 1m bars |
| `SWARM_MIN_CONFIDENCE` | `0.6` | Minimum `winner_confidence` for swarm enrichment |
| `SWARM_WEIGHT_MIN_SAMPLES` | `30` | Min resolved predictions before weight learning activates |
| `SWARM_WEIGHT_FLOOR` | `0.05` | Minimum agent weight before formal demotion |
| `SWARM_MAX_CONCURRENT_CALLS` | `8` | Max concurrent LLM calls (asyncio.Semaphore) |

### Regime Gate

| Variable | Default | Description |
|----------|---------|-------------|
| `REGIME_PROB_MIN` | `0.30` | Minimum regime probability — safety floor, not quality filter |
| `REGIME_DUR_MIN` | `1` | Minimum regime duration bars |
| `REGIME_PROB_SOFT_MAX` | `0.55` | Soft-band upper boundary for confidence attenuation |

### ML Foundation

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_SEMANTIC_CACHE_SIZE` | `500` | SemanticCache LRU max entries |
| `DATA_QUALITY_MIN_SCORE` | `0.85` | Min quality score for ML discovery gate |
| `ML_DISCOVERY_LOOKBACK_DAYS` | `90` | tsfresh rolling lookback window (days) |
| `ML_DISCOVERY_IC_THRESHOLD` | `0.05` | Min information coefficient to include in discovery report |

---

## Database Connection

Always use the full connection string — plain `psql -U postgres` fails (password required):

```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT ..."
```

Or via Docker:

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "SELECT ..."
```

---

## Instrument Configuration

Active contracts are resolved at runtime from the database, not from static config. The canonical query is in `get_active_contracts()` in `src/config/settings.py`:

- Futures templates: queries `instruments WHERE contract_details->>'asset_class' = 'futures'` (JSONB filter — no top-level `asset_class` column on `instruments`, per CLAUDE.md's Instrument asset class filter gotcha) to inherit `point_value`/`tick_size`/`session_id`/etc.
- Futures front-month rows: queries `contract_metadata WHERE is_front_month = true AND asset_class = 'futures'` — `contract_metadata.asset_class` IS a plain top-level column, unlike `instruments.contract_details->>'asset_class'`; don't conflate the two tables' schemas.
- Non-futures (equities, FX, crypto): queries `instruments WHERE is_active = true AND contract_details->>'asset_class' != 'futures'`
- Results merged and cached for 60 seconds; on DB error, returns the last valid cache (or `[]` cold)

**Never hardcode contract symbols.** Always call `get_active_contracts(settings)` — daemons read contracts at startup; restart on futures expiry for the new front month.

---

## Concepts

- [Data Pipeline](../data/data-pipeline.md)
- [Stream Keys](../../src/core/stream_keys.py) — all topic construction
- [Adaptive Parameter Registry](../foundation/adaptive-parameter-registry.md) — runtime-tunable `config_state` parameters; not the same system as the `Settings` class above
