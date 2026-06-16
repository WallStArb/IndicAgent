# CLAUDE.md

Version: 5.47.0

**Project nature:** Passion/learning project — not a production system. Architectural decisions prioritize correctness, rigor, and institutional-grade thinking. Renaissance Capital / Jim Simons principles are the north star. When giving advice, apply the same rigor you would to a system built to last — do not hedge around operational risk that doesn't apply.

**Skill commands:** Always use `/gsd-<name>` syntax (e.g. `/gsd-plan-phase`). Never suggest `gsd:<name>`.
**Principles:** Instrument everything · shadow mode first · data quality over model complexity · never drop data that could contain signal · earn promotion through proof (p<0.05, sufficient N) · segment by regime · automate manual tasks · empirical over theoretical · resist overfitting. Full doc: `docs/foundation/principles.md`.
**Design mindset:** Think as a council of senior engineers at Renaissance Technologies. Data integrity is paramount. Ruthlessly eliminate complexity. Silent wrong answers are worse than loud crashes. Deterministic DAG topology — every node does one thing, data flows one direction, no cycles. SoC: compute ≠ persistence ≠ transport. Async-first. Before committing to a design: (1) survives 10x volume? (2) what fails silently or introduces hidden bias? (3) does the DAG still hold? (4) what manual step does this eliminate?
**Naming:** Concept name (`snake_case`) derives all layer names — `signal_tracker` → `SignalTracker`, `indicagent-signal-tracker.service`, `topic_signal_tracker()`, `signal_trackers` table. **Ring rule:** `src/core/` = Ring 0 portable infrastructure (no domain vocab); `src/intelligence/` = Ring 1 domain; `services/` = Ring 2 daemons. Topics: dots only, via `stream_keys.py`. Full spec: `docs/foundation/naming-system.md`.
**Glossary:** Every domain term has exactly one definition. Check before naming new concepts; glossary wins over existing code on collision. Full spec: `docs/foundation/glossary.md`.
**Doc locations:** `docs/foundation/` canonical home. `docs/` root is index only.
**Gotchas:** `docs/reference/gotchas.md` — rare pitfalls moved out of per-turn context.
**Agentic DAG:** ComputeAgents (I1-I6) are DB-ignorant, publish to tiered topics, DataWriterAgents manage persistence.

## Done-Coding SOP

```
1. code-simplifier agent   # clean up changed code (invoke automatically)
2. /review                 # peer code review
3. pytest tests/unit/ -q   # must be green
4. commit on feature branch
5. git checkout main && git merge --ff-only <branch>
6. git branch -d <branch> && git worktree prune
7. git push origin main
```

**Commands:** `.venv/bin/pytest tests/unit/ -v` · `.venv/bin/ruff check . --fix` · `.venv/bin/black .` · `docs/cheatsheet.md` for full reference.

## Architecture

**Layers:** I1-I4 Mathematical · I5-I7 Pattern/Signal · I8 AI (Ollama, default `nemotron-3-nano:4b` via `OLLAMA_MODEL`)
**Pipeline:** `IBKR TWS → intelligence_pipeline (I1-I7 in-process) → signal_ledger + intelligence_features → feature_writer → TimescaleDB → SSE → Dashboard`
**Typed Bus:** `IntelligenceEvent` (`src/intelligence/schemas.py`) — tiered JSONB (i1/i2/i3/i4/i5/smc/i6), persisted to `intelligence_features` by `feature_writer`.

**Service DAG:** canonical registry is `_DAG_ORDER` in `services/service_auditor.py`. Live state: `systemctl list-units --all | grep indicagent`. Monitoring: Grafana `:3001`.
**ML batch services** (`ml-training`, `ml-orchestrator`, `ml-data-quality`, `ml-discovery`, `roll-batch`): `inactive (dead)` between runs is correct.

## Core Runtime Files

- **DB queries:** `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "..."`. Plain `psql -U postgres` fails.
- **Historical backfill:** `run_historical_pipeline.py --client-id 40` (provider uses 35; default 56 exceeds `_MAX_CLIENT_ID=50`).
- `src/core/stream_keys.py` — all stream/topic key construction
- `src/core/database_manager.py` — PostgreSQL/TimescaleDB with connection pooling
- `src/core/service_utils.py` — `setup_service_logging()`, `min_bars_for_tf()`, `normalize_session_type()`, `format_iso_ts()`, `parse_iso_ts()`
- `src/core/ai/` — AI agent infrastructure (`BaseAIWorker`, `Evaluator`, `AgentOutput`, `WorkerContext`, `IAIAgent`). `SignalContext` in `src/intelligence/ai/context.py`. `BaseGroupCoordinator` in `src/intelligence/ai/group_coordinator.py`.
- `src/intelligence/schemas.py` — canonical typed bus schemas
- `src/config/settings.py` — `Settings`, `get_active_contracts()`, `Instrument` definitions
- `src/providers/ibkr.py` — all ib_insync logic (no imports outside this file)
- **Narrative service:** `services/narrative_swarm.py` (`NarrativeSwarm`) → `indicagent-narrative-compute`. Worker: `NarrativeSynthesizer` in `src/intelligence/ai/narrative/narrative_agent.py`.

## Data Flow

```
Hot:  IBKR TWS → Redpanda Streams → Services              (sub-ms)
Warm: Streams → indicator/analysis/signal pipeline        (<10ms)
Cold: BarWriter + feature_writer → TimescaleDB (batch, async)
```
**Real-time pipeline never touches the database directly.**

### TimescaleDB Tables

- `market_data_ohlcv` — raw OHLCV. Primary time column: `timestamp` (not `ts`)
- `intelligence_features` — full feature vectors per bar. Column name: `ts` (not `feature_ts`)
- **Signal Ledger Architecture (SLA, Phase 128+):**
  - `signal_events` — detection layer: one row per I7 plugin fire. Fields: `raw_confidence` (ICC), `factor_scores`, `context_features`, `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `status`. Primary time: `ts`.
  - `trade_frames` — hypothesis layer: one row per entry_type per signal. Fields: `counterfactual_pnl_r` (CFL, always populated). ML trains on this.
  - `trade_executions` — execution layer: one row per live trade. Fields: `actual_pnl_r`, `actual_fill_price`, `exit_reason`.
  - `signal_ledger` — JOIN view (renamed from signal_ledger_full in Phase 130). Provides backward-compat query surface joining signal_events + trade_frames + trade_executions. Legacy monolith and signal_outcomes dropped in Phase 130.
- `llm_calls` — full LLM audit log; outcome back-filled by `llm_writer`
- `setup_performance` — per-setup rolling 30d stats; drives `perf_multiplier`; `sample_size >= 30` gate
- **Volume Profile**: `poc_price`/`vah`/`val` = session VP (1m/5m); `poc_price_rolling`/`vah_rolling`/`val_rolling` = rolling VP (15m/1h)

**Gotchas:** `docs/operations/operations-database.md` — `instruments.symbol` = base, contract code in `contract_details`.

## Adaptive Parameter Registry (APR)

All tunable numeric values live in `config_state` under `<domain>.<concept>.<param>` — accessed via `ConfigService.get(key, default=X)`. Hard-coded numeric thresholds, weights, periods, or counts in `src/` are an architecture violation. Full spec: `docs/foundation/adaptive-parameter-registry.md`.

**Namespaces:** `threshold.*` · `weights.*` · `feature.*` · `regime.*` · `shadow.*` · `signal.*` · `swarm.*` · `roll.*` · `ui.*` (dashboard preferences)

**Parameter lifecycle:** seed → user/operator preference → ml_learned → user_override. Every write recorded in `config_history` with `changed_by` and `reason`.

**Adding a parameter:** (1) INSERT into `config_schema` + `config_state` in a migration; (2) load via `ConfigService.get()` at init; (3) remove the hard-coded constant. Description must note provenance: `[initial_estimate]`, `[conventional]`, `[rca_analysis]`, or `[user_preference]`, and whether it is an ML learning target.

**Migrate-as-you-go:** Any numeric threshold, weight, period, or count encountered in `src/` that is not APR-backed MUST be migrated in the same session. Module-level constants and inline magic numbers are architecture violations. Pattern for module-level utilities: `_config_service: Any | None = None` + `set_config_service()` + `get_sync()` wrapper, registered in `intelligence_pipeline._prewarm_threshold_config()`. Pattern for plugin dataclasses: `_config_service: Any = field(default=None, compare=False, repr=False)`, read via `cfg.get_sync(key, fallback) if cfg else fallback`.

**`ui.*` requires one-line change first:** add `"ui."` to `OPS_PREFIXES` in `src/config/config_service.py`.
**Dashboard:** `/config/parameters` — view/edit all parameters, full change history per key.

## Plugin System

138 plugins across tiers I1–I7. See `src/intelligence/CLAUDE.md` for tier details.
- Tier lists: `TIER_I1`…`TIER_I7` in `src/intelligence/register_plugins.py` — single source of truth
- **Shadow Governance:** `shadow_registry` DB table. Promotion: `n >= 100` AND `bootstrap_ci_lower(pnl_r) > 0.0`. Demotion: EV[R] < -0.05 for 3 consecutive cycles.
- **Confluence requirement:** Every signal-generation plugin must consume `ctf_*` sub-scores (`requires_i6_confluence=True`). Enforced by `validate_tier()` — raises `ArchitectureViolation` otherwise.
- **Signal-generation plugin integrity:** 6 GOOD patterns: 4-factor ICC, dual regime+confluence gate before OHLCV extraction, `shadow_only=True`. Full pattern spec: `docs/signals/signals-confidence-patterns.md`.

**Adding an AI Agent:** Full protocol: `src/intelligence/ai/AUTHORING.md`. Skeleton: `TEMPLATE.py`. Mandatory attrs: `agent_id`, `group`, `tiers_needed`, `latency_budget_ms`, `shadow_only`, `prompt_version`. Register in group service + call `shadow_registry_ensure()` at startup.

## DAG Invariants

Non-negotiable. Any violation is wrong regardless of whether it works locally.

1. **`ProviderMerger` is the sole writer to `market.bars`**
2. **I1–I7 runs entirely in-process** — `IntelligencePipeline` is DB-ignorant; Kafka is a sink, not an inter-stage pipe.
3. **No analyzer or pipeline daemon touches the database** — only `BaseWriter`, `BaseTracker`, `BaseAuditor` subclasses do DB ops.
4. **All topic keys via `stream_keys.py`** — no hardcoded topic strings.
5. **No agent calls another agent directly** — topics are the only coupling.
6. **All timestamps UTC** — `datetime.now(UTC)` only; never `datetime.now()` or `datetime.utcnow()`.
7. **Scaling via systemd + Prometheus lag** — no Kubernetes HPA.

## Key Rules

**Core Patterns**
- **Parallel dicts → dataclass**: 3+ `dict[str, X]` attributes keyed by same ID → consolidate into `dict[str, MyState]` with `_state(key)` factory. Pattern: `SignalTracker._signal_states`.
- **`KafkaProducerClient.publish()` kwarg is `msg=`** — not `value=`. Wrong kwarg silently fails at flush.
- **`BaseGroupCoordinator` agent construction**: agents needing `self._llm_chain` must be constructed in `_setup()` after `super()._setup()` — `_llm_chain` is `None` in `__init__`.
- **AI agents MUST use `self._llm_generate(context, ...)`** — never call `self._llm.generate()` directly.
- **`prompt_version` class attribute** on every `BaseAIWorker` subclass — set from agent's `ACTIVE_VERSION` constant.
- **`llm_calls` composite PK: `(call_id, called_at)`** — ON CONFLICT must use both columns.
- **Kafka is transport, not state store.** Hot state → local file checkpoint. Bar history → TimescaleDB.
- **Timestamp serialization**: use `format_iso_ts(dt)` from `service_utils.py`. Never inline `.isoformat().replace("+00:00", "Z")`.
- **`get_active_contracts()`** is a module-level function in `settings.py`. Call as `get_active_contracts(settings)`, not `settings.get_active_contracts()`.
- **asyncpg**: JSONB → `dict` (no `json.loads()`/`json.dumps()`). Timestamps → `datetime`. UUIDs → `str()` before Kafka.
- **structlog `event` kwarg collision**: Never pass `event=<value>` — use `signal=`, `payload=`, `data=` instead.
- **Service registry**: when adding a service, update `_DAG_ORDER`, `_LAG_THRESHOLDS`, `_AGENT_ID_TO_UNIT` in `service_auditor.py`.
- **`INDICAGENT_ENV` consistency**: Mixed env prefixes → services subscribe to different topics → zero data flow.
- **Settings**: use `src/config/Settings`. Never `os.environ` directly.
- **Metrics**: `src/observability/metrics.py` (direct OTel SDK — `prometheus_client` fully removed). Counters → `.add(1, attrs)`, histograms → `.record(val, attrs)`, up-down gauges → `.add(delta, attrs)`, point gauges → `.set(value, attrs)`. Never import `prometheus_client`.
- **Spans**: `observed_span(name, attributes={...})` from `src/observability/spans.py` — auto-records ERROR on raise. Use `ATTR_*` constants from same module.
- **`BaseWriter._parse_payload` return contract**: `None` → DLQ whole payload. `[]` → all-invalid (no DLQ). Only return `None` for truly unparseable payloads.
- **Exception variable name is `error`** — `except X as error:`, not `exc`.
- **File/class renames require test sweep:** `grep -r "OldName" tests/` — test imports break at pytest collection, not lint.
- **`BaseWriter.__init__` requires `name: str`** (non-optional): when removing `name=` from any writer, also update `BaseWriter.__init__` to accept `name: str | None = None`.
- **Oneshot `_agent.py` exceptions:** `services/feature_validation_agent.py`, `services/hmm_training_agent.py`, `services/ml_training_agent.py`, `services/ml_signal_training_agent.py` — `_agent` suffix intentionally preserved.
- **API health router prefix is `/health`** not `/api/health`. Routes: `/health/system`, `/health/database`, etc.
- **`agent_last_message_timestamp_seconds` label key is `agent_id`** — use `r["metric"].get("agent_id")` when querying from Prometheus.
- **Ollama JSON enforcement (nemotron-3-nano:4b):** system message MUST start with `"OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE."` Add `"Begin your response with { and end with }."` at end of user prompt.
- **Swarm raw signal confidence**: `calibrated_confidence` is null in Kafka payloads. Gate on `raw_signal.get("confidence")` or `raw_signal.get("pre_quality_confidence")`.

**Signal Logic**
- **Aggregator `active` must come from `all_ranked`**: `active = [s for s in all_ranked if s.get("regime_eligible", True)]` — never from raw `signals`.
- **SLA column reference (Phase 128+):** `signal_events`: `raw_confidence`, `factor_scores`, `context_features`, `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `status`. `trade_frames`: `entry_type`, `entry_price`, `stop_price`, `target_price`, `counterfactual_pnl_r`, `was_selected`. `trade_executions`: `actual_pnl_r`, `actual_fill_price`, `exit_reason`. Query via `signal_ledger` (the JOIN view, renamed from signal_ledger_full in Phase 130).
- **signal_schema_version**: single constant `SIGNAL_SCHEMA_VERSION` in `src/intelligence/trading/signal_schema.py` — no hardcoded version strings.
- **entry_type values**: `at_close`, `at_pullback`, `at_limit`, `at_reclaim`, `zone_proximal`.
- **Signal status strings**: `"pending"`, `"active"`, `"regime_suppressed"`, `"expired"` — raw string literals, no enum.
- **`signal_computed_at` is nullable**: always `COALESCE(signal_computed_at, timestamp)` in SQL.

**Services**
- **Logging**: `structlog` → `logs/<snake_case_class_name>.log` via `setup_service_logging("logs/<name>.log")`. NOT journald.
- **`PERSISTENCE_BATCH_LATENCY` label key is `agent_id`** — not `agent=`.
- **`intelligence_pipeline` subscribes to:** `topic_market_bars` (1m) AND `topic_market_bars_htf` (HTF).
- **Tests**: `tests/unit/`, `tests/integration/`, `tests/e2e/`. Unit tests must be CI-clean.

## OTel Health Contract

Every `BaseDaemon` subclass auto-inherits 5 mandatory OTel signals (D-26, non-negotiable): `agent_last_message_timestamp_seconds`, `agent_crash_total`, `agent_dlq_total`, `watchdog_notify_total`, `watchdog_notify_suppressed_total` — all labeled `agent_id`. No per-service code needed.
**Oneshot (D-06):** emit `job_completed_total{job, status}` at exit. `job` label matches systemd unit `%n` suffix exactly (kebab-case).

## Infrastructure

- **Server:** `192.168.68.53` — Claude Code runs ON this machine; never SSH.
- **IBKR Gateway:** Docker (`ib-gateway` container), bound to `127.0.0.1:7497`. All ib_insync in `src/providers/ibkr.py` only. VIX=`"VX"`, client IDs 35+.
- **Redpanda**: Kafka-compatible. Topics: dots, via `stream_keys.py`. Retention: minimal (transport, not storage).
- **Contracts**: always `get_active_contracts()` — never hardcode. Restart daemons on futures expiry.
- **Roll flow:** `roll-batch` nightly 8pm (`production/scripts/roll_batch.py`) — promotes front-month in `contract_metadata`, broadcasts via Kafka.
- **Docker**: `cd production && docker compose up -d` after `docker-compose.yml` changes.
- **Ollama:** Docker (`ollama/ollama:rocm`). `docker exec ollama ollama <cmd>`. Kill `alpha_swarm` + `narrative_compute` before swapping models.

> Sudo, INDICAGENT_ENV debug, more: `docs/operations/operations-infrastructure.md`
