# CLAUDE.md

Version: 5.46.0

**Project nature:** Passion/learning project — not a production system, not relied upon. Architectural decisions prioritize correctness, rigor, and institutional-grade thinking over operational caution. Renaissance Capital / Jim Simons principles are the north star. The platform and the builder improve together — every refinement compounds. When giving advice, do not hedge around operational risk that doesn't apply; apply the same rigor you would to a system built to last.

**Skill commands:** Always use `/gsd-<name>` syntax (e.g. `/gsd-plan-phase`). Never suggest `gsd:<name>` — that is the old convention.
**Principles:** Instrument everything · shadow mode first · data quality over model complexity · never drop data that could contain signal · earn promotion through proof (p<0.05, sufficient N) · segment by regime · automate manual tasks · let the system run · empirical over theoretical (if data says it works, it works — don't require a narrative) · resist overfitting (simpler models that generalize beat complex models that memorize). Full doc: `docs/foundation/principles.md`.
**Design mindset:** Think as a council of senior engineers at Renaissance Technologies. Data integrity is paramount. The codebase is a highly efficient machine — balance ultra-high performance with extreme simplicity. Ruthlessly eliminate complexity. Guard against hidden biases and edge-case failures (silent wrong answers are worse than loud crashes). Deterministic DAG topology — every node does one thing, data flows one direction, no cycles, no shortcuts. Modular microservices: each service owns exactly one responsibility. SoC: compute ≠ persistence ≠ transport. Async-first — blocking I/O in the hot path is a defect. Aggressive component reuse over duplication. Ruthlessly call out manual tasks, latent inefficiencies, and technical debt — provide an uncompromising first-principles blueprint, not a patch. Before committing to a design: (1) survives 10x volume? (2) what fails silently or introduces hidden bias? (3) does the DAG still hold? (4) what manual step does this eliminate?
**Naming:** Concept name (`snake_case`) derives all layer names — `signal_tracker` → `SignalTracker`, `indicagent-signal-tracker.service`, `topic_signal_tracker()`, `signal_trackers` table. **Ring rule:** `src/core/` = Ring 0 portable infrastructure (no domain vocab — e.g. `BaseDaemon`, `WorkerContext`); `src/intelligence/` = Ring 1 domain (`BaseAIWorker`, `SignalContext`); `services/` = Ring 2 daemons (pure role nouns, no suffix required for plain role nouns). Topics: dots only, via `stream_keys.py`. Full spec: `docs/foundation/naming-system.md`.
**Documentation:** Domain-first taxonomy, verified `current` status, recipe-card format. Full spec: `docs/foundation/documentation-system.md`.
**Glossary:** Every domain term has exactly one definition — no synonyms, no loose usage. Check before naming new concepts; glossary wins over existing code on collision. Full spec: `docs/foundation/glossary.md`.
**Doc locations:** `docs/foundation/` is the canonical home for principles/naming/documentation-system docs. Check there before creating new docs — `docs/` root is index only.
**Gotchas:** See `docs/gotchas.md` — rare pitfalls moved out of per-turn context.
**Agentic DAG:** ComputeAgents (I1-I6) are DB-ignorant, publish to tiered topics, DataWriterAgents manage persistence. Scaling: systemd + Prometheus lag monitoring (no Kubernetes HPA).

## Quick Start

```bash
uv venv .venv && source .venv/bin/activate && uv pip install -r requirements.txt
.venv/bin/pytest tests/unit/ -v
.venv/bin/ruff check . --fix && .venv/bin/black .
sudo systemctl start indicagent-intelligence-pipeline
cd dashboard && npm run dev
/review  # pre-commit mandatory (code-simplifier agent runs automatically post-coding)
```

**Requires:** Python 3.11+, Docker (TimescaleDB, Redpanda), systemd, Node.js 18+.

## Done-Coding SOP

Run these steps in order when a coding session is complete, before pushing.

```
1. code-simplifier agent   # clean up changed code (invoke automatically, not a slash command)
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
**Health check:** `systemctl list-units --all | grep indicagent` · **Logs:** `tail -20 logs/<service>.log`
**Dashboard:** `cd dashboard && npm run dev` (`:3000`)
**API:** `uvicorn src.api.main:app` (`:8000`)
**Consumer lag:** `docker exec redpanda rpk group describe feature_pipeline -t`
**Full reference:** `docs/cheatsheet.md` · **Roadmap:** `.planning/ROADMAP.md`

## Architecture Overview

```
Layer 4: AI Intelligence (I8)              -> LLM analysis, local Ollama (default nemotron-3-nano:4b, set via OLLAMA_MODEL in .env)
Layer 3: Pattern Intelligence (I5-I7)      -> Pattern detection, confluence, trading signals
Layer 2: Mathematical Intelligence (I1-I4) -> Technical indicators, context classification
Layer 1: Data Foundation                   -> HF collection, aggregation, typed event bus
```

**Intelligence Pipeline:**
```
IBKR TWS → intelligence_pipeline (I1-I7 unified, in-process) →
  signal_ledger + intelligence_features →
  feature_writer → TimescaleDB → SSE → Dashboard
```

**Typed Bus:** `IntelligenceEvent` (`src/intelligence/schemas.py`) — tiered JSONB (i1/i2/i3/i4/i5/smc/i6), persisted to `intelligence_features` hypertable by `feature_writer`.

## Service DAG

Canonical registry: `_DAG_ORDER` in `services/service_auditor.py`. Never maintain a parallel list here.
**Live state:** `systemctl list-units --all | grep indicagent` · **Monitoring:** Grafana `:3001`


**ML batch services (timer-triggered, not daemons):** `inactive (dead)` between runs is correct — do not treat as failures.
- `ml-training` (nightly 11pm), `ml-orchestrator`/`ml-data-quality`/`ml-discovery` (weekly Mon). Design: `docs/ideas/ai-02-ml-agent-architecture.md`
- `roll-batch` (nightly 8pm) — calendar-based futures roll detection + contract promotion. Replaces 24/7 `roll-compute` + `contract-metadata-writer` daemons.

## Core Runtime Files

- **DB queries:** `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "..."`. Plain `psql -U postgres` fails.
- **Pipeline capacity:** sequential bar processing (`await _process_bar`), latency at `intelligence_pipeline_pipeline_latency_ms` gauge (`:8000/metrics`). Backfill replay throttled (`BAR_REPLAY_BARS_PER_SEC`) — not representative of live ceiling.
- **Historical backfill:** `run_historical_pipeline.py --client-id 40` (provider uses 35; default 56 exceeds `_MAX_CLIENT_ID=50`). Gotchas: `docs/gotchas.md`.
- **Lifecycle replay:** `lifecycle_replay.py` — re-run picks up where it left off. Gotchas: `docs/gotchas.md`.
- `src/core/stream_keys.py` — all stream/topic key construction
- `src/core/database_manager.py` — PostgreSQL/TimescaleDB with connection pooling
- `src/core/service_utils.py` — `setup_service_logging()`, `min_bars_for_tf()`, `normalize_session_type()`, `format_iso_ts()`, `parse_iso_ts()`
- `src/core/ai/` — AI agent infrastructure (BaseAIWorker, Evaluator, AgentOutput, WorkerContext, IAIAgent protocol). `SignalContext` lives in `src/intelligence/ai/context.py`. `BaseGroupCoordinator` (shared group dispatcher) lives in `src/intelligence/ai/group_coordinator.py`.
- `src/intelligence/schemas.py` — canonical typed bus schemas
- `src/config/settings.py` — `Settings`, `get_active_contracts()`, `Instrument` definitions
- `src/providers/ibkr.py` — all ib_insync logic (no imports outside this file)
- **Narrative service:** `services/narrative_swarm.py` (`NarrativeSwarm`) maps to `indicagent-narrative-compute`. The AI worker class is `NarrativeSynthesizer` in `src/intelligence/ai/narrative/narrative_agent.py`.

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
  - `signal_events` — detection layer: one row per I7 plugin fire event. Contains `raw_confidence` (ICC output), `factor_scores`, `context_features`, `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `status`. Primary time: `ts`.
  - `trade_frames` — hypothesis layer: one row per entry_type per signal. Contains `counterfactual_pnl_r` (CFL output, always populated by CounterfactualTracker). ML trains on this.
  - `trade_executions` — execution layer: one row per live trade execution. Contains `actual_pnl_r`. Most frames have zero rows here.
  - `signal_ledger_full` — join view across all three tables (Phase 128). Renamed to `signal_ledger` in Phase 129 when the legacy monolith is dropped.
  - `signal_ledger` — legacy monolith (read-only during SLA migration; dropped in Phase 129; name reclaimed by join view).
- `llm_calls` — full LLM audit log per call; outcome back-filled by `llm_writer`
- `setup_performance` — per-setup rolling 30d stats; drives aggregator `perf_multiplier`; `sample_size >= 30` gate
- **Volume Profile**: `poc_price`/`vah`/`val` = session VP (1m/5m); `poc_price_rolling`/`vah_rolling`/`val_rolling` = rolling VP (15m/1h)

**Gotchas:** `docs/operations/timescaledb-gotchas.md` — `instruments.symbol` = base, contract code in `contract_details`.

## Adaptive Parameter Registry (APR)

All tunable numeric values live in `config_state` under `<domain>.<concept>.<param>` — accessed via `ConfigService.get(key, default=X)`. Hard-coded numeric thresholds, weights, periods, or counts in `src/` are an architecture violation. Full spec: `docs/foundation/parameter-store.md`.

**Namespaces:** `threshold.*` (plugin detection gates) · `weights.*` (confidence weights) · `feature.*` (indicator periods e.g. SMA/RSI/ATR) · `regime.*` · `shadow.*` · `signal.*` · `swarm.*` · `roll.*` · `ui.*` (dashboard preferences)

**Parameter lifecycle:** seed → user/operator preference → ml_learned → user_override. Every write recorded in `config_history` with `changed_by` and `reason`. ML discovery writes learned values via `ConfigService.set(changed_by="ml_discovery", reason="n=N, p=P")` — outbox broadcasts hot reload without restart.

**Adding a parameter:** (1) INSERT into `config_schema` + `config_state` in a migration; (2) load via `ConfigService.get()` at init; (3) remove the hard-coded constant. Description field must note provenance: `[initial_estimate]`, `[conventional]`, `[rca_analysis]`, or `[user_preference]`, and whether it is an ML learning target.

**`ui.*` requires one-line change first:** add `"ui."` to `OPS_PREFIXES` in `src/config/config_service.py`.

**Dashboard:** `/config/parameters` — view/edit all parameters, see full change history per key.

## Plugin System

138 plugins across tiers I1–I7 (I1=29, I2=11, I3=9, I4=13, I5=16, SMC=16, I6=7, I7=37 incl. 2 aggregators). See `src/intelligence/CLAUDE.md` for tier details and LLM provider chain.
- Tier lists: `TIER_I1`…`TIER_I7` in `src/intelligence/register_plugins.py` — single source of truth
- **Shadow Governance (SG):** `shadow_registry` DB table. Auto-enroll at startup. Promotion: `n >= 100` AND `bootstrap_ci_lower(pnl_r) > 0.0`. Demotion: EV[R] < -0.05 for 3 consecutive cycles.
- **Confluence requirement:** Every signal-generation plugin must consume relevant `ctf_*` sub-scores (`requires_i6_confluence=True`)
- **Signal-generation plugin integrity:** All signal-generation plugins follow the 6 GOOD patterns: 4-factor ICC, dual regime+confluence gate before OHLCV extraction, `shadow_only=True`. Enforced by `validate_tier()` which raises `ArchitectureViolation` unless `requires_i6_confluence=True`. The `_CONFLUENCE_EXEMPT_PLUGINS` carve-out (8 plugins) is deleted in Phase 126. Full pattern spec: `docs/architecture/setup-confidence-patterns.md`

## Adding an AI Agent

Full protocol: `src/intelligence/ai/AUTHORING.md`. Skeleton: `src/intelligence/ai/TEMPLATE.py`. Reference: `skeptic_agent.py`.
- **Mandatory attrs**: `agent_id`, `group`, `tiers_needed`, `latency_budget_ms`, `shadow_only`, `prompt_version`
- **Files**: `src/intelligence/ai/<group>/<name>_agent.py` + `<name>_prompts.py` (expose `PROMPT_REGISTRY`, `ACTIVE_VERSION`)
- **`_compute()` contract**: Build prompt → call LLM → parse → `AgentOutput`. Never raise; `self._neutral(error=...)` on failure.
- Register in group service (e.g., `AlphaSwarm._agents`) + call `shadow_registry_ensure()` at startup.

## DAG Invariants

These are non-negotiable architectural constraints. Any code that violates one of them is wrong regardless of whether it works locally. Full rationale: `docs/foundation/foundation-design-principles.md` (Principle 11) and `docs/architecture/architecture-dag-topology.md`.

1. **`ProviderMerger` is the sole writer to `market.bars`** — all downstream agents are isolated from provider topology.
2. **I1–I7 runs entirely in-process** — `IntelligencePipeline` is DB-ignorant; Kafka is a sink, not an inter-stage pipe.
3. **No analyzer or pipeline daemon touches the database** — only `BaseWriter`, `BaseTracker`, and `BaseAuditor` subclasses perform DB operations.
4. **All topic keys via `stream_keys.py`** — no hardcoded topic strings anywhere.
5. **No agent calls another agent directly** — topics are the only coupling between agents.
6. **All timestamps UTC** — `datetime.now(UTC)` only; never `datetime.now()` or `datetime.utcnow()`.
7. **Scaling via systemd + Prometheus lag** — no Kubernetes HPA; consumer lag monitored via `persistence_consumer_lag`.

## Key Rules

**Core Patterns**
- **Parallel dicts → dataclass**: When a class has 3+ `dict[str, X]` attributes all keyed by the same ID, consolidate into `dict[str, MyState]` where `MyState` is a `@dataclass`. Use a `_state(key)` factory method for lazy init (required when the dataclass needs constructor args like `deque(maxlen=N)`). Pattern: `SignalTracker._signal_states`. Benefits: co-located memory, impossible mismatched state across dicts.
- **`KafkaProducerClient.publish()` kwarg is `msg=`** — not `value=`. Wrong kwarg silently fails at flush.
- **`BaseGroupCoordinator` agent construction**: agents needing `self._llm_chain` must be constructed in `_setup()` after `super()._setup()` — `_llm_chain` is `None` in `__init__`.
- **AI agents MUST use `self._llm_generate(context, ...)`** — never call `self._llm.generate()` directly. Auto-injects audit_context (call_id, symbol, signal_id, regime, agent_id, prompt_version).
- **`prompt_version` class attribute** on every BaseAIWorker subclass — set from agent's `ACTIVE_VERSION` constant. Auto-injected into `llm_calls` for prompt A/B testing.
- **`llm_calls` composite PK: `(call_id, called_at)`** — ON CONFLICT must use both columns.
- **Kafka is transport, not state store.** Hot state (plugin_states, kalman) → local file checkpoint. Bar history → TimescaleDB.
- **Timestamps: always UTC.** `datetime.now(UTC)` only. Never `datetime.now()` or `datetime.utcnow()`. All DB columns `timestamptz`; stream timestamps UTC ISO-8601 (`Z` suffix).
- **Timestamp serialization**: use `format_iso_ts(dt)` from `service_utils.py` for Kafka/JSON. Never inline `.isoformat().replace("+00:00", "Z")`.
- **`get_active_contracts()`** is a module-level function in `settings.py`, not a method on `Settings`. Call as `get_active_contracts(settings)`, not `settings.get_active_contracts()`.
- **asyncpg**: Use for all new DB code. JSONB → `dict` (no `json.loads()`/`json.dumps()`). Timestamps → `datetime`. UUIDs → `str()` before Kafka. Edge cases: `docs/gotchas.md`.
- **structlog `event` kwarg collision**: Never pass `event=<value>` as keyword — use `signal=`, `payload=`, `data=` instead.
- **Service registry**: `_DAG_ORDER` in `services/service_auditor.py`. When adding a service, update `_DAG_ORDER`, `_LAG_THRESHOLDS`, `_AGENT_ID_TO_UNIT`.
- **Stream keys**: always via `src/core/stream_keys.py`. Include `env_prefix` from `Settings`.
- **`INDICAGENT_ENV` consistency**: Mixed env prefixes → services subscribe to different topics → zero data flow.
- **Settings**: use `src/config/Settings`. Never `os.environ` directly.
- **Metrics**: create via `src/observability/metrics.py` (direct OTel SDK — `prometheus_client` fully removed in Phase 83). Call patterns: counters → `.add(1, {"label": val})`, histograms → `.record(val, {"label": val})`, up-down gauges (`create_up_down_counter`) → `.add(delta, {"label": val})`, point gauges (`create_gauge` / `point_gauge()`) → `.set(value, {"label": val})`. Never import `prometheus_client`.
- **Spans**: use `observed_span(name, attributes={...})` from `src/observability/spans.py` for new spans — auto-records ERROR status + exception on raise. Use ATTR_* constants from same module instead of raw strings.
- **Documentation accuracy**: Docs may contain fabricated content (forward-looking specs never implemented). Verify against code before trusting.
- **`BaseWriter._parse_payload` return contract**: returning `None` triggers `_maybe_route_to_dlq` on the whole payload. When doing per-signal validation, return `[]` for the all-invalid case to prevent the base writer from double-DLQ-ing the payload; only return `None` for a truly empty/unparseable payload with no signals at all.
- **Exception variable name is `error`** — `except X as error:`, not `exc`. Not enforced by pre-commit; must be followed by convention.
- **File/class renames require test sweep:** After renaming any `src/` file or class, run `grep -r "OldName" tests/` — test imports break at pytest collection, not at lint time.
- **`BaseWriter.__init__` requires `name: str`** (non-optional, unlike BaseDaemon post-Phase-111): when removing `name=` from any writer service, also update `BaseWriter.__init__` to accept `name: str | None = None` with pass-through to super.
- **Oneshot `_agent.py` exceptions (not daemons, not rename targets):** `services/feature_validation_agent.py`, `services/hmm_training_agent.py`, `services/ml_training_agent.py`, `services/ml_signal_training_agent.py` — thin entrypoints for timer-triggered scripts; `_agent` suffix intentionally preserved.
- **API health router prefix is `/health`** not `/api/health`: `app.include_router(health.router, prefix="/health", ...)` at `src/api/main.py:131`. Routes are `/health/system`, `/health/database`, etc.
- **`agent_last_message_timestamp_seconds` label key is `agent_id`**: `self._last_msg_ts_attrs = {"agent_id": name}` in `src/core/agent/base.py`. Use `r["metric"].get("agent_id")` when querying this metric from Prometheus.
- **Ollama JSON enforcement (nemotron-3-nano:4b):** outputs prose preamble without an explicit system message starting with `"OUTPUT ONLY RAW JSON. NO PROSE. NO EXPLANATION. NO PREAMBLE."` Also add `"Begin your response with { and end with }."` at end of user prompt. `_strip_thinking_tags` only removes `<think>` tags — does not catch prose.
- **Swarm raw signal confidence field:** `calibrated_confidence` is null in Kafka signal payloads. Gate on `raw_signal.get("confidence")` or `raw_signal.get("pre_quality_confidence")`.

**Signal Logic**
- **Aggregator `active` must come from `all_ranked`**: Derive `active = [s for s in all_ranked if s.get("regime_eligible", True)]` — never from raw `signals`.
- **SLA column reference (Phase 128+):** Detection fields on `signal_events`: `raw_confidence` (ICC), `factor_scores` (JSONB), `context_features` (JSONB), `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `status`. Hypothesis fields on `trade_frames`: `entry_type`, `entry_price`, `stop_price`, `target_price`, `counterfactual_pnl_r` (CFL), `was_selected`. Execution fields on `trade_executions`: `actual_pnl_r`, `actual_fill_price`, `exit_reason`. Query via `signal_ledger_full` view (Phase 128) or `signal_ledger` view (Phase 129+). Pre-Phase-128: `signal_ledger` monolith; query via `signal_ledger_full` view (migration 095).
- **signal_schema_version**: single canonical constant `SIGNAL_SCHEMA_VERSION` in `src/intelligence/trading/signal_schema.py`. All producers/consumers import from there — no hardcoded version strings.
- **entry_type values**: `at_close`, `at_pullback`, `at_limit`, `at_reclaim`, `zone_proximal`.
- **Signal status strings**: `"pending"`, `"active"`, `"regime_suppressed"`, `"expired"` — 4 values, raw string literals, no enum.
- **`signal_computed_at` is nullable in `signal_ledger`:** Historical signals may have NULL `signal_computed_at`. Always use `COALESCE(signal_computed_at, timestamp)` in direct SQL — otherwise ORDER BY and WHERE clauses silently exclude rows.

**Services**
- **Logging**: `structlog` → `logs/<service>.log` via `setup_service_logging()`. NOT journald.
- **Log file names**: `logs/<snake_case_class_name>.log` (e.g. `alpha_swarm.log`, `bar_aggregator.log`). BaseDaemon auto-derives this from the class name.
- **`setup_service_logging` requires full path**: `"logs/<name>.log"`, not bare name.
- **`PERSISTENCE_BATCH_LATENCY` label key is `agent_id`** — not `agent=`.
- **`intelligence_pipeline` subscribes to:** `topic_market_bars` (1m) AND `topic_market_bars_htf` (HTF).
- **Tests**: `tests/unit/`, `tests/integration/`, `tests/e2e/`. Unit tests CI-clean.

## OTel Health Contract (Phase 108 SOP)

Every new daemon that inherits BaseDaemon MUST emit these five OTel signals; non-compliance is a code review rejection (D-26). All five are inherited automatically from BaseDaemon - no per-service code is needed.

**Mandatory signals (D-04):**
- `agent_last_message_timestamp_seconds` (gauge, label `agent_id`) - liveness; updated on every processed message
- `agent_crash_total` (counter, label `agent_id`) - uncaught exceptions in `_run()` (BaseDaemon method)
- `agent_dlq_total` (counter, label `agent_id`) - DLQ routing events
- `watchdog_notify_total` (counter, label `agent_id`) - successful sd_notify WATCHDOG=1 pings (Phase 108)
- `watchdog_notify_suppressed_total` (counter, label `agent_id`) - suppressed pings: agent alive but idle/stalled (Phase 108)

**Oneshot contract (D-06):** Oneshot timer-triggered scripts MUST emit `job_completed_total{job, status}` at script exit. Label `job` MUST match the systemd unit `%n` suffix exactly (kebab-case).

**Grafana SLO alerts (D-27):**
- `agent_last_message_timestamp_seconds` stale > 120s -> page
- `watchdog_notify_suppressed_total` rate > 0 -> warning
- `dlq_quarantine_total` increment > 0 -> warning
- `api_health` = 0 -> page
- `rate(bars_processed_total[5m])` drops > 50% from baseline -> warning
- `consumer_stall_detected_total` rate > 0 -> warning
- Any oneshot `job_completed_total{status="failure"}` increment -> warning; `time_since_last_success{job=X} > 25h` -> page


## Infrastructure

- **Server:** `192.168.68.53` (Ethernet) — Claude Code runs ON this machine; never SSH, run commands directly.
- **IBKR Gateway:** runs in Docker (`ib-gateway` container, `ghcr.io/gnzsnz/ib-gateway:stable`), bound to `127.0.0.1:7497` (TWS port 4003 mapped). No longer a remote host at `192.168.1.157`.
- **IBKR**: VIX=`"VX"`, client IDs 35+. TWS host `127.0.0.1`, port `7497`. All ib_insync in `src/providers/ibkr.py` only.
- **Redpanda**: Kafka-compatible. Topic naming: dots not colons. Via `stream_keys.py` always. Retention: minimal (transport, not storage).
- **Contracts**: always `get_active_contracts()` — never hardcode. Daemon reads contracts at startup; restart on futures expiry.
- **Roll flow:** Nightly `roll-batch` timer (`production/scripts/roll_batch.py`) runs at 8pm, detects calendar-based rolls, promotes front-month contracts in `contract_metadata` table, and broadcasts updates via Kafka. Provider picks up changes on next `get_active_contracts()` call. See `docs/ideas/futures-roll-simplification.md` for architecture analysis.
- **Docker**: All 14 containers `restart: unless-stopped`. After `docker-compose.yml` changes: `cd production && docker compose up -d`.
- **Systemd:** `production/systemd/` is reference. Installed in `/etc/systemd/system/`. Check `systemctl status` for authoritative state.
- **Ollama:** runs in Docker (`ollama/ollama:rocm` container), not systemd. Use `docker exec ollama ollama <cmd>`. Live services `alpha_swarm` and `narrative_compute` hold persistent connections — kill them before swapping models or benchmarking.

> Sudo, INDICAGENT_ENV debug, more: `docs/operations/infrastructure-reference.md`
