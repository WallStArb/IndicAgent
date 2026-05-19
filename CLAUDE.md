# CLAUDE.md

Version: 5.42.0 | Status: v2.5 complete — Phases 69–82 shipped. Next: v2.6 Signal Transform Architecture or backlog.

**Skill commands:** Always use `/gsd-<name>` syntax (e.g. `/gsd-plan-phase`). Never suggest `gsd:<name>` — that is the old convention.
**Principles:** See `docs/principles.md` — instrument everything, shadow mode first, data quality over model complexity.
**Naming:** Concept name (`snake_case`) derives all layer names — `alpha_signal` → `AlphaSignalService`, `indicagent-alpha-signal.service`, `topic_alpha_signal()`, `alpha_signals` table. Files: `*_service.py` / `*_agent.py` / `src/intelligence/trading/<name>.py`. Topics: dots only, via `stream_keys.py`. Full table: `docs/naming-conventions.md`.
**Gotchas:** See `docs/gotchas.md` — rare pitfalls moved out of per-turn context.
**Agentic DAG:** ComputeAgents (I1-I6) are DB-ignorant, publish to tiered topics, DataWriterAgents manage persistence. Scaling: systemd + Prometheus lag monitoring (no Kubernetes HPA).

## Quick Start

```bash
uv venv .venv && source .venv/bin/activate && uv pip install -r requirements.txt
.venv/bin/pytest tests/unit/ -v
.venv/bin/ruff check . --fix && .venv/bin/black .
sudo systemctl start indicagent-intelligence-pipeline
cd dashboard && npm run dev
/simplify && /coderabbit:code-review  # pre-commit mandatory
```

**Requires:** Python 3.11+, Docker (TimescaleDB, Redpanda), systemd, Node.js 18+.

## Done-Coding SOP

Run these steps in order when a coding session is complete, before pushing.

```
1. /simplify               # clean up changed code
2. /review                 # peer code review (or /coderabbit:code-review)
3. pytest tests/unit/ -q   # must be green
4. commit on feature branch
5. git checkout main && git merge --ff-only <branch>   # fast-forward merge to main
6. git branch -d <branch>                              # delete local feature branch
7. git worktree prune                                  # remove stale worktree refs
8. git push origin main
```

## Core Commands

**Tests:** `.venv/bin/pytest tests/unit/ -v` · **Lint:** `.venv/bin/ruff check . --fix` · **Format:** `.venv/bin/black .`
**Health check:** `systemctl list-units --all | grep indicagent` · **DB freshness:** `psql -U postgres -d indicagent -c "SELECT symbol, tf, MAX(ts) FROM intelligence_features GROUP BY symbol, tf ORDER BY MAX(ts) DESC LIMIT 5"` · **Logs:** `tail -20 logs/<service>_agent.log`
**Dashboard:** `cd dashboard && npm run dev` (`:3000`)
**API:** `uvicorn src.api.main:app` (`:8000`)
**Consumer lag:** `docker exec redpanda rpk group describe feature_pipeline -t`
**Full reference:** `docs/cheatsheet.md` · **Roadmap:** `.planning/ROADMAP.md`

## Architecture Overview

```
Layer 4: AI Intelligence (I8)              -> LLM analysis, local Ollama (default gemma4:e4b, .env may override)
Layer 3: Pattern Intelligence (I5-I7)      -> Pattern detection, confluence, trading signals
Layer 2: Mathematical Intelligence (I1-I4) -> Technical indicators, context classification
Layer 1: Data Foundation                   -> HF collection, aggregation, typed event bus
```

**Intelligence Pipeline:**
```
IBKR TWS → intelligence_pipeline_agent (I1-I7 unified, in-process) →
  signal_ledger + intelligence_features →
  feature_writer_service → TimescaleDB → SSE → Dashboard
```

**Typed Bus:** `IntelligenceEvent` (`src/intelligence/schemas.py`) — tiered JSONB (i1/i2/i3/i4/i5/smc/i6), persisted to `intelligence_features` hypertable by `feature_writer_service`.

## Service DAG

Canonical registry: `_DAG_ORDER` in `services/service_auditor_agent.py`. Never maintain a parallel list here.
**Live state:** `systemctl list-units --all | grep indicagent` · **Monitoring:** Grafana `:3001`

```
L1  ibkr-provider, bar-replay            — data ingestion + bar replay
L2  provider-merger                      — stream merge
L3  bar-aggregator, bar-auditor          — bar processing
L4  bar-writer                           — OHLCV persistence
L5  intelligence-pipeline, cross-asset, macro-compute — I1-I7 compute + context
L6  feature-writer, signal-writer, signal-tracker-compute, lifecycle-writer,
    lineage-writer, contract-metadata-writer, ctx-writer — persistence writers (parallel)
L7  alpha-swarm, narrative-compute, llm-writer, swarm-ledger-writer — AI/LLM layer
L8  roll-compute, signal-metrics-compute, signal-metrics-writer, graduation-compute,
    graduation-writer, feature-snapshot-writer, ml-training — analytics
L9  signal-auditor, signal-replay, parity-auditor, alerting-agent — audit, parity, alerting
L10 service-auditor                      — meta: monitors + restarts all above
```

**ML batch services (timer-triggered, not daemons):** `inactive (dead)` between runs is correct — do not treat as failures.
- `ml-training` (nightly 11pm), `ml-orchestrator`/`ml-data-quality`/`ml-discovery` (weekly Mon). Design: `docs/ideas/ai-02-ml-agent-architecture.md`

## Core Runtime Files

- **DB queries:** `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "..."`. Plain `psql -U postgres` fails.
- **Pipeline capacity:** sequential bar processing (`await _process_bar`), per-bar latency measured by `intelligence_pipeline_pipeline_latency_ms` gauge at `:8000/metrics`. 132 plugins across 6 stages, 12 thread-pool workers (GIL cap). Backfill replay throttled to 10 bps (`BAR_REPLAY_BARS_PER_SEC`) — not representative of pipeline ceiling.
- **Historical backfill:** `historical_backfill.py --client-id` defaults to 56, but `_MAX_CLIENT_ID=50` in `ibkr.py`. Must use `--client-id 40` (provider uses 35). ContFuture (`continuous=True`) hangs on multi-year requests — use named contracts with `--days 364` or `production/scripts/backfill_1d.py` which chunks automatically.
- **Lifecycle replay:** `lifecycle_replay.py` may hit PostgreSQL's 32,767 query argument limit on large (symbol, timeframe) pairs. Re-run picks up where it left off (skips resolved signals).
- `src/core/stream_keys.py` — all stream/topic key construction
- `src/core/database_manager.py` — PostgreSQL/TimescaleDB with connection pooling
- `src/core/service_utils.py` — `setup_service_logging()`, `min_bars_for_tf()`, `normalize_session_type()`, `format_iso_ts()`, `parse_iso_ts()`
- `src/core/ai/` — AI agent infrastructure (BaseAIAgent, BaseGroupService, AIContext, AgentOutput)
- `src/intelligence/schemas.py` — canonical typed bus schemas
- `src/config/settings.py` — `Settings`, `get_active_contracts()`, `Instrument` definitions
- `src/providers/ibkr.py` — all ib_insync logic (no imports outside this file)

## Data Flow

```
Hot:  IBKR TWS → Redpanda Streams → Services              (sub-ms)
Warm: Streams → indicator/analysis/signal pipeline        (<10ms)
Cold: BarWriterAgent + feature_writer_service → TimescaleDB (batch, async)
```
**Real-time pipeline never touches the database directly.**

### TimescaleDB Tables

- `market_data_ohlcv` — raw OHLCV. Primary time column: `timestamp` (not `ts`)
- `intelligence_features` — full feature vectors per bar. Column name: `ts` (not `feature_ts`)
- `signal_ledger` — ALL I7 signals + lifecycle outcomes. JOIN via `(symbol, feature_ts, feature_tf)`. Primary time: `timestamp`
- `llm_calls` — full LLM audit log per call; outcome back-filled by `llm_writer_service`
- `setup_performance` — per-setup rolling 30d stats; drives aggregator `perf_multiplier`; `sample_size >= 30` gate
- **Volume Profile**: `poc_price`/`vah`/`val` = session VP (1m/5m); `poc_price_rolling`/`vah_rolling`/`val_rolling` = rolling VP (15m/1h)

**Gotchas:** `docs/operations/timescaledb-gotchas.md` — `instruments.symbol` = base, contract code in `contract_details`.

## Plugin System

132 plugins + 2 aggregation across tiers I1–I7. See `src/intelligence/CLAUDE.md` for tier details and LLM provider chain.
- Tier lists: `TIER_I1`…`TIER_I7` in `src/intelligence/register_plugins.py` — single source of truth
- **Shadow governance:** `shadow_registry` DB table. Auto-enroll at startup. Promotion: `n >= 100` AND `bootstrap_ci_lower(pnl_r) > 0.0`. Demotion: EV[R] < -0.05 for 3 consecutive cycles.
- **I6→I7 confluence:** Every I7 must consume relevant `ctf_*` sub-scores

## Adding an AI Agent

Full protocol: `src/intelligence/ai/AUTHORING.md`. Skeleton: `TEMPLATE_agent.py`. Reference: `skeptic_agent.py`.
- **Mandatory attrs**: `agent_id`, `group`, `tiers_needed`, `latency_budget_ms`, `shadow_only`, `prompt_version`
- **Files**: `src/intelligence/ai/<group>/<name>_agent.py` + `<name>_prompts.py` (expose `PROMPT_REGISTRY`, `ACTIVE_VERSION`)
- **`_compute()` contract**: Build prompt → call LLM → parse → `AgentOutput`. Never raise; `self._neutral(error=...)` on failure.
- Register in group service (e.g., `AlphaSwarmComputeAgent._agents`) + call `shadow_registry_ensure()` at startup.

## Key Rules

**Core Patterns**
- **Parallel dicts → dataclass**: When a class has 3+ `dict[str, X]` attributes all keyed by the same ID, consolidate into `dict[str, MyState]` where `MyState` is a `@dataclass`. Use a `_state(key)` factory method for lazy init (required when the dataclass needs constructor args like `deque(maxlen=N)`). Pattern: `RollMonitor._states`, `SignalTrackerComputeAgent._signal_states`. Benefits: co-located memory, impossible mismatched state across dicts.
- **`KafkaProducerClient.publish()` kwarg is `msg=`** — not `value=`. Wrong kwarg silently fails at flush.
- **`BaseGroupService` agent construction**: agents needing `self._llm_chain` must be constructed in `_setup()` after `super()._setup()` — `_llm_chain` is `None` in `__init__`.
- **AI agents MUST use `self._llm_generate(context, ...)`** — never call `self._llm.generate()` directly. Auto-injects audit_context (call_id, symbol, signal_id, regime, agent_id, prompt_version).
- **`prompt_version` class attribute** on every BaseAIAgent subclass — set from agent's `ACTIVE_VERSION` constant. Auto-injected into `llm_calls` for prompt A/B testing.
- **`llm_calls` composite PK: `(call_id, called_at)`** — ON CONFLICT must use both columns.
- **Kafka is transport, not state store.** Hot state (plugin_states, kalman) → local file checkpoint. Bar history → TimescaleDB.
- **Timestamps: always UTC.** `datetime.now(UTC)` only. Never `datetime.now()` or `datetime.utcnow()`. All DB columns `timestamptz`; stream timestamps UTC ISO-8601 (`Z` suffix).
- **Timestamp serialization**: use `format_iso_ts(dt)` from `service_utils.py` for Kafka/JSON. Never inline `.isoformat().replace("+00:00", "Z")`.
- **`get_active_contracts()`** is a module-level function in `settings.py`, not a method on `Settings`. Call as `get_active_contracts(settings)`, not `settings.get_active_contracts()`.
- **asyncpg**: Use for all new DB code. JSONB: asyncpg returns `dict` (no `json.loads()`). Pass dicts for jsonb columns — never `json.dumps()`. Timestamps: asyncpg returns `datetime` objects. UUIDs: always `str()` before JSON/Kafka.
- **structlog `event` kwarg collision**: Never pass `event=<value>` as keyword — use `signal=`, `payload=`, `data=` instead.
- **Service registry**: `_DAG_ORDER` in `services/service_auditor_agent.py`. When adding a service, update `_DAG_ORDER`, `_LAG_THRESHOLDS`, `_AGENT_ID_TO_UNIT`.
- **Stream keys**: always via `src/core/stream_keys.py`. Include `env_prefix` from `Settings`.
- **`INDICAGENT_ENV` consistency**: Mixed env prefixes → services subscribe to different topics → zero data flow.
- **Settings**: use `src/config/Settings`. Never `os.environ` directly.
- **Metrics**: create via `src/observability/metrics.py` (direct OTel SDK — `prometheus_client` fully removed in Phase 83). Call patterns: counters → `.add(1, {"label": val})`, histograms → `.record(val, {"label": val})`, up-down gauges → `.add(delta, {"label": val})`. Never import `prometheus_client`.
- **Spans**: use `observed_span(name, attributes={...})` from `src/observability/spans.py` for new spans — auto-records ERROR status + exception on raise. Use ATTR_* constants from same module instead of raw strings.
- **Alpha swarm agent timeouts**: correlation, regime_coherence, counterfactual agents have 5s `latency_budget_ms` vs skeptic's 60s. Local Ollama (gemma4:e4b) cannot meet 5s. Swarm degrades gracefully (uses completing agents only).
- **Documentation accuracy**: Docs may contain fabricated content (forward-looking specs never implemented). Verify against code before trusting.
- **`CircuitBreaker` manual-tracking** (`src/observability/circuit_breaker.py`): `record_failure()` opens the breaker but `OPEN→HALF_OPEN` recovery only fires inside `call()`. For manual tracking outside `call()`, use `allow_request()` (time-based OPEN→HALF_OPEN check) and `record_success()` (resets failures, closes from HALF_OPEN) — both added in Phase 086.
- **`BaseWriterAgent._parse_payload` return contract**: returning `None` triggers `_maybe_route_to_dlq` on the whole payload. When doing per-signal validation, return `[]` for the all-invalid case to prevent the base writer from double-DLQ-ing the payload; only return `None` for a truly empty/unparseable payload with no signals at all.
- **API health router prefix is `/health`** not `/api/health`: `app.include_router(health.router, prefix="/health", ...)` at `src/api/main.py:131`. Routes are `/health/system`, `/health/database`, etc.
- **`agent_last_message_timestamp_seconds` label key is `agent`** not `agent_id`: `self._last_msg_ts_attrs = {"agent": name}` in `src/core/agent/base.py`. Use `r["metric"].get("agent")` when querying this metric from Prometheus.
- **gemma4:e4b JSON enforcement:** outputs prose preamble without an explicit system message starting with `"OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE."` Also add `"Begin your response with { and end with }."` at end of user prompt. `_strip_thinking_tags` only removes `<think>` tags — does not catch prose.
- **Swarm raw signal confidence field:** `calibrated_confidence` is null in Kafka signal payloads. Gate on `raw_signal.get("confidence")` or `raw_signal.get("pre_quality_confidence")`.
- **CIS weights never loaded:** `seed_cis_weights()` in `cache_manager.py` is never called externally — scorer runs bootstrap weights (equal ~0.2) forever despite `cis_weights` table having learned values. Avg CIS ≈ 0.046 is the symptom. Fix: load from DB on startup + 15m refresh.

**Signal Logic**
- **Aggregator `active` must come from `all_ranked`**: Derive `active = [s for s in all_ranked if s.get("regime_eligible", True)]` — never from raw `signals`.
- **signal_ledger columns**: `exit_at` (not `exit_ts`), `activated_at`, `outcome`, `exit_reason`, `pnl_r`, `mae`, `mfe`, `bars_in_trade`. Time column: `timestamp`.
- **signal_schema_version**: single canonical constant `SIGNAL_SCHEMA_VERSION` in `src/intelligence/trading/signal_schema.py`. All producers/consumers import from there — no hardcoded version strings.
- **entry_type values**: `at_close`, `at_pullback`, `at_limit`, `at_reclaim`, `zone_proximal`.
- **Signal status strings**: `"pending"`, `"active"`, `"regime_suppressed"` — raw string literals, no enum.

**Services**
- **Logging**: `structlog` → `logs/<service>.log` via `setup_service_logging()`. NOT journald.
- **Log file names**: `logs/<agent_snake_case>_agent.log` (e.g. `alpha_swarm_compute_agent.log`, not `alpha_swarm.log`). Check `logs/` for actual names.
- **`setup_service_logging` requires full path**: `"logs/<name>.log"`, not bare name.
- **`PERSISTENCE_BATCH_LATENCY` label key is `agent_id`** — not `agent=`.
- **intelligence_pipeline_agent subscribes to:** `topic_market_bars` (1m) AND `topic_market_bars_htf` (HTF).
- **Tests**: `tests/unit/`, `tests/integration/`, `tests/e2e/`. Unit tests CI-clean.

## Infrastructure

- **Server:** `192.168.68.53` (Ethernet) — Claude Code runs ON this machine; never SSH, run commands directly.
- **IBKR Gateway:** runs in Docker (`ib-gateway` container, `ghcr.io/gnzsnz/ib-gateway:stable`), bound to `127.0.0.1:7497` (TWS port 4003 mapped). No longer a remote host at `192.168.1.157`.
- **IBKR**: VIX=`"VX"`, client IDs 35+. TWS host `127.0.0.1`, port `7497`. All ib_insync in `src/providers/ibkr.py` only.
- **Redpanda**: Kafka-compatible. Topic naming: dots not colons. Via `stream_keys.py` always. Retention: minimal (transport, not storage).
- **Contracts**: always `get_active_contracts()` — never hardcode. Daemon reads contracts at startup; restart on futures expiry.
- **Roll flow:** `RollComputeAgent` → `RollEvent` → `ContractMetadataWriterAgent` → `is_front_month` → restart `indicagent-ibkr-provider`.
- **Docker**: All 11 containers `restart: unless-stopped`. After `docker-compose.yml` changes: `cd production && docker compose up -d`.
- **Systemd:** `production/systemd/` is reference. Installed in `/etc/systemd/system/`. Check `systemctl status` for authoritative state.
- **Ollama:** runs in Docker (`ollama/ollama:rocm` container), not systemd. Use `docker exec ollama ollama <cmd>`. Check VRAM: `cat /sys/class/drm/card1/device/mem_info_vram_total`. Benchmark: `curl -s http://localhost:11434/api/generate -d '{"model":"...","prompt":"...","stream":false}'`. Live services `alpha_swarm` and `narrative_compute` hold persistent connections — kill them before swapping models or benchmarking.

> Sudo, INDICAGENT_ENV debug, more: `docs/operations/infrastructure-reference.md`
