# Phase 16: LLM Intelligence Layer - Research

**Researched:** 2026-03-05
**Domain:** LLM call instrumentation, stream-based persistence, adaptive model routing
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Architecture: Event-Driven, Tiered**
Every LLM call emits to `{env}:llm_calls:stream` (DragonflyDB). `llm_writer_service` is the only writer to TimescaleDB — identical to `feature_writer_service`. The real-time pipeline never writes to the database directly. No special paths.

**Stream Keys**
- `{env}:llm_calls:stream` — emitted by `ai_narrative_service` after every call
- `{env}:llm_outcomes:stream` — emitted by `signal_lifecycle_service` on signal exit
- Redis score cache: `{env}:llm_scores:{call_type}:{regime}` as HSET: `{model}` → JSON score blob

**Migration: 019_llm_intelligence_layer.sql**
Creates:
- `llm_calls` — TimescaleDB hypertable, `called_at` partition key
- `llm_model_scores` — aggregate table, PK `(model, regime, setup_type, call_type)`

`llm_calls` schema (all fields locked per design doc):
- `call_id UUID PRIMARY KEY`, `called_at TIMESTAMPTZ NOT NULL`, `call_type TEXT NOT NULL`
- `signal_id UUID REFERENCES signal_ledger(signal_id)` (nullable for group/counterfactual)
- `group_name TEXT`, `symbol TEXT NOT NULL`, `timeframe TEXT NOT NULL`
- LLM call: `model TEXT`, `provider TEXT`, `prompt TEXT`, `response TEXT`, `latency_ms INTEGER`, `tokens_est INTEGER`, `succeeded BOOLEAN DEFAULT TRUE`
- Market context: `regime TEXT`, `session TEXT`, `entry_price`, `stop_loss`, `target_price`, `confidence`, `cis_score`, `entry_zone_low`, `entry_zone_high`, `setup_type TEXT`
- Outcome (back-filled): `outcome TEXT`, `pnl_r DOUBLE PRECISION`, `mae`, `mfe`, `bars_in_trade INTEGER`, `win BOOLEAN`, `outcome_at TIMESTAMPTZ`

Indexes: `(signal_id)`, `(model, regime)`, `(called_at DESC)`

**ai_narrative_service Instrumentation**
- After every LLM call (success OR failure): `xadd llm_calls:stream` with full payload
- Counterfactuals: signals below confidence threshold produce a call log entry with `call_type='counterfactual'`, prompt built, `response=NULL`, `succeeded=False`
- At startup + every 5 min: read Redis `llm_scores`, re-sort provider chain if `is_significant=True` winner exists for current call_type + regime

**signal_lifecycle_service Emission**
- On signal exit (any outcome): `xadd llm_outcomes:stream` with `signal_id`, `outcome`, `pnl_r`, `mae`, `mfe`, `bars_in_trade`

**llm_writer_service (New Service)**
- Consumer groups on both `llm_calls:stream` and `llm_outcomes:stream`
- Batch INSERT to `llm_calls` (mirror feature_writer batch pattern)
- UPDATE `llm_calls SET outcome fields WHERE signal_id = $1` on outcomes
- Every 15 min: recompute `llm_model_scores` from `llm_calls WHERE outcome IS NOT NULL`
- Update Redis score cache after recompute
- Systemd unit: `indicagent-llm-writer`, Prometheus metrics on next available port
- Consumer group: `llm_writer` (use `ensure_consumer_group_with_reset`)

**Adaptive Routing Logic**
```python
scores = get_scores_from_redis(call_type, current_regime)
significant = [s for s in scores if s.is_significant]  # p < 0.05 AND n_outcomes >= 30
if significant:
    best = max(significant, key=lambda s: s.avg_pnl_r)
    move best.model to position 0 in provider chain
```
Promotion gate: `p < 0.05 AND n_outcomes >= 30` — binomial test vs baseline win rate.

**llm_model_scores Schema**
Fields: `model`, `regime`, `setup_type`, `call_type`, `n_calls`, `n_outcomes`, `win_rate`, `avg_pnl_r`, `avg_latency_ms`, `p_value`, `is_significant BOOLEAN`, `score_updated_at`

### Claude's Discretion
- Exact port number for `llm_writer_service` metrics (use next available after 9116)
- Whether score recompute uses raw SQL or SQLAlchemy ORM (match existing service pattern)
- Batch size and flush interval for `llm_calls:stream` consumer (mirror `feature_writer_service` defaults)
- p-value computation library (scipy.stats.binomtest preferred — already available in .venv)
- `__all__` regime/setup_type rows in `llm_model_scores` for aggregate view (aggregate across all regimes)

### Deferred Ideas (OUT OF SCOPE)
- Dashboard panels for model comparison (explicitly out of scope per design doc)
- Automated fine-tuning pipeline (separate phase — needs training infrastructure)
- Cross-model ensemble voting (backlog)
- Multi-regime promotion gate (must hold across 2+ regimes) — v2 enhancement; this phase uses single-regime p-value only
- Latency-adjusted promotion (demoting high-latency models even with good win rates) — backlog
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| LLM-01 | Migration `019_llm_intelligence_layer.sql` creates `llm_calls` TimescaleDB hypertable and `llm_model_scores` aggregate table | Schema locked in CONTEXT.md; migration number confirmed as 019 (018 is latest existing) |
| LLM-02 | `ai_narrative_service` emits to `{env}:llm_calls:stream` after every LLM call (success, failure, counterfactual) | Call sites: `_process_single_message()` per-signal path, `_synthesize_group()` group path; counterfactual hook: lines 436-443 where confidence gate fires |
| LLM-03 | `signal_lifecycle_service` emits to `{env}:llm_outcomes:stream` when any signal exits | Exit sites: two code paths — normal exit at line 356 (Active→Exit) and shadow exit at line 267; both call `update_signal_status()` with final pnl_r/outcome/mae/mfe |
| LLM-04 | New `llm_writer_service` mirrors feature_writer_service — batch INSERTs, outcome back-fill, score recompute every 15 min, Redis score cache update | feature_writer_service fully read; pattern documented below |
| LLM-05 | `ai_narrative_service` reads Redis score cache at startup and every 5 min; promotes `is_significant=True` model to position 0 in provider chain | Provider chain is `LLMChain(list[LLMProvider])` built in `_build_chains()`; `self.per_signal_chain.providers` and `self.group_chain.providers` are mutable lists |
</phase_requirements>

---

## Summary

Phase 16 adds a complete instrumentation layer over the existing `ai_narrative_service` LLM pipeline. Every call — per-signal, group synthesis, and counterfactual (signals below the 0.70 confidence threshold) — emits to a DragonflyDB stream. A new `llm_writer_service` (mirroring `feature_writer_service` exactly) consumes both the call stream and an outcome stream emitted by `signal_lifecycle_service` on signal close, persisting everything to a TimescaleDB hypertable. Every 15 minutes it recomputes aggregate model scores and writes them to a Redis HSET cache. The `ai_narrative_service` reads that cache and dynamically reorders its provider chains when a model reaches statistical significance (p < 0.05, n >= 30).

The three existing source files that need modification are well-understood: `ai_narrative_service.py`, `signal_lifecycle_service.py`, and `src/core/stream_keys.py`. The new `llm_writer_service.py` follows the `feature_writer_service.py` template nearly line-for-line. All architecture decisions are locked; the planner's job is to sequence the work into concrete, dependency-ordered tasks.

Two plans already exist (16-01 and 16-02) covering migration + schema + TDD RED (16-01) and `llm_writer_service` implementation GREEN (16-02). Three more plans are needed: ai_narrative_service instrumentation (LLM-02 + LLM-05), signal_lifecycle_service emission (LLM-03), and systemd + integration wiring (LLM-04 deployment).

**Primary recommendation:** Follow the feature_writer_service pattern exactly — batch size 50, flush interval 5s, single xreadgroup call for multi-stream reading. Port 9117 for Prometheus (next after feature_writer at 9116). Use `scipy.stats.binomtest` which is confirmed available in the project venv.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| redis.asyncio | project venv | Stream emit (xadd), score cache (hset), consumer groups (xreadgroup) | All existing services use this client |
| asyncpg (via DatabaseManager) | project venv | Batch INSERT and UPDATE to TimescaleDB | `execute_batch(sql, list[tuple])` is the project-standard pattern |
| scipy.stats.binomtest | confirmed in .venv | p-value computation for model promotion gate | Confirmed available: `from scipy.stats import binomtest` |
| structlog | project venv | Structured logging with fields `timestamp, service, symbol, timeframe, level` | Project-wide standard |
| prometheus_client (via src/observability/metrics.py) | project venv | Prometheus counter/gauge via project wrapper | All services use `counter()`, `gauge()`, `start_metrics_server(port=N)` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| src/core/stream_utils.ensure_consumer_group_with_reset | internal | Safe consumer group creation with stale-position reset | All consumer group setup — never use raw xgroup_create |
| src/core/stream_keys | internal | Stream key construction with env_prefix | Always — never construct stream keys inline |
| src/core/database_manager.DatabaseManager | internal | PostgreSQL/TimescaleDB with connection pooling + JSONB codecs | All DB access |
| asyncio.create_task | stdlib | Fire-and-forget stream emission without blocking LLM call latency | `xadd llm_calls:stream` after LLM call |

---

## Architecture Patterns

### Pattern 1: Feature Writer Mirror (llm_writer_service)

The `feature_writer_service.py` is the exact template. Key structural decisions:

```python
# Module-level constants (confirmed defaults to mirror)
BATCH_SIZE: int = 50
FLUSH_INTERVAL_SECS: float = 5.0
CONSUMER_GROUP: str = "llm_writer"
CONSUMER_NAME: str = "llm_writer_1"
SCORE_RECOMPUTE_INTERVAL_SECS: float = 900.0   # 15 minutes
SCORE_MIN_N_OUTCOMES: int = 30
SCORE_P_THRESHOLD: float = 0.05
```

Three async loops in `start()`:
- `_calls_process_loop()` — xreadgroup on `llm_calls:stream`, buffer → batch INSERT
- `_outcomes_process_loop()` — xreadgroup on `llm_outcomes:stream`, immediate UPDATE (low volume)
- `_score_recompute_loop()` — runs every 900s: query DB, upsert llm_model_scores, write Redis
- `_health_monitor_loop()` — uptime gauge, periodic log

### Pattern 2: ai_narrative_service Instrumentation

**Where to add xadd for per-signal calls:**
The call happens in `_process_single_message()` around lines 446-453. After `await self.per_signal_chain.generate(...)` returns, `self.per_signal_chain.last_provider_id` is set. This is the insertion point for the xadd.

```python
# After the chain.generate() call, before the if narrative_text: branch
# Fire-and-forget to avoid blocking the narrative publish path
asyncio.create_task(self._emit_llm_call(
    call_type="per_signal",
    signal_data=signal_data,
    prompt=prompt,
    response=narrative_text,
    latency_ms=latency_ms,
    succeeded=narrative_text is not None,
))
```

**Where to add counterfactual emission:**
Lines 436-443 — confidence gate. Before `return True`, build the prompt (reuse `build_narrative_prompt()`) and emit with `call_type='counterfactual'`, `response=None`, `succeeded=False`.

**Where to add xadd for group synthesis calls:**
In `_synthesize_group()`, after `await self.group_chain.generate(...)` returns (line 616-622 area). Same fire-and-forget pattern.

**Provider chain structure (LLMChain):**
```python
# src/intelligence/llm_providers.py — LLMChain wraps a list of LLMProvider
class LLMChain:
    def __init__(self, providers: list[LLMProvider]) -> None:
        self.providers = providers          # mutable list — safe to reorder
        self.last_provider_id: str | None = None
```

`self.per_signal_chain.providers` is a Python list — adaptive routing reorders it by moving the best model to `providers[0]`. No API needed, direct list manipulation.

**Provider id format:** `"zai:glm-5"`, `"openrouter:meta-llama/llama-3.3-70b-instruct:free"`, `"ollama:qwen3.5:9b"` — set by each provider's `__init__` as `self.provider_id`.

**Where to add score refresh:**
Add `_score_refresh_loop()` as a new task in `start()` — reads Redis HSET, promotes significant winner by reordering `self.per_signal_chain.providers` and `self.group_chain.providers` in place.

### Pattern 3: signal_lifecycle_service Exit Emission

Two exit code paths — both need `xadd llm_outcomes:stream`:

**Normal exit (Active → Exit), lines ~356-403:**
```python
elif transition.exit_reason:
    exit_at = now
    bit = _bars_in_trade(...)
    outcome = ...
    # ADD xadd here — all fields available: sid, outcome, transition.pnl_r, transition.mae, transition.mfe, bit
    await update_signal_status(...)
```

**Shadow signal exit (regime_suppressed), lines ~267-309:**
```python
if transition.exit_reason:
    exit_at = now
    bit = _bars_in_trade(...)
    outcome = ...
    # ADD xadd here — same fields available
    await update_signal_status(...)
```

Signal id is `sid = str(sig["signal_id"])` — already a string representation of UUID at this point. The stream message should emit it as a string; the llm_writer_service uses `$1::uuid` cast in the UPDATE SQL.

### Pattern 4: Stream Key Additions

Current `get_stream_maxlen` Literal type must be extended:
```python
# Current Literal (from stream_keys.py line 70-73):
kind: Literal[
    "ticks", "market", "indicators", "intelligence",
    "intelligence_i7", "intelligence_i8",
    "signals", "signals_aggregated", "narratives", "narratives_group",
]

# Must add: "llm_calls", "llm_outcomes"
# Recommended maxlen: "llm_calls" → 500, "llm_outcomes" → 200
```

Three new functions needed:
```python
def llm_calls_stream(env_prefix: str) -> str:
    return f"{env_prefix}llm_calls:stream"

def llm_outcomes_stream(env_prefix: str) -> str:
    return f"{env_prefix}llm_outcomes:stream"

def llm_scores_cache(env_prefix: str, call_type: str, regime: str) -> str:
    return f"{env_prefix}llm_scores:{call_type}:{regime}"
```

### Pattern 5: Systemd Unit File

One existing unit file found: `production/systemd/indicagent-weight-updater.service`. The long-running services (feature_writer, signal_lifecycle) follow a different pattern as `Type=simple` (not oneshot). The planner must create `production/systemd/indicagent-llm-writer.service` modeled on existing long-running service files. The weight-updater is oneshot — not the right template.

The correct template (inferred from all other running services) is:
```ini
[Unit]
Description=IndicAgent LLM Writer Service
After=network-online.target
Documentation=https://github.com/bg/indicagent

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/llm_writer_service.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-llm-writer

[Install]
WantedBy=multi-user.target
```

**CLAUDE.md confirms:** All services use `Restart=always`. Systemd files live in `production/systemd/`.

### Anti-Patterns to Avoid

- **Direct DB write from ai_narrative_service:** Never. The real-time pipeline never touches the database directly. All DB writes through llm_writer_service only.
- **Blocking LLM call latency with xadd:** Use `asyncio.create_task()` for fire-and-forget stream emission — do not `await` the xadd in the hot path.
- **Sequential xreadgroup calls:** The service reads two distinct streams (`llm_calls:stream` and `llm_outcomes:stream`). Since they have very different volume profiles (calls are high-frequency, outcomes are low-frequency), two separate loops are appropriate — unlike the multi-symbol intelligence streams where a single combined call eliminates lag.
- **Buffering outcome updates:** Do not buffer outcome UPDATEs. They are low-volume and time-sensitive. Execute immediately.
- **raw xgroup_create:** Always use `ensure_consumer_group_with_reset` — raw xgroup_create silently fails when group exists, leaving stale position.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| p-value for model significance | Custom stats math | `scipy.stats.binomtest` | Confirmed in venv; handles edge cases (n=0, all wins) |
| Stream consumer group reset | `redis.xgroup_create` directly | `ensure_consumer_group_with_reset` from `src/core/stream_utils` | Existing gotcha: silent stale position on group already exists |
| DB connection pooling | asyncpg pool directly | `DatabaseManager` from `src/core/database_manager` | Handles JSONB codecs, pool init, reuse pattern |
| Prometheus metric registration | `prometheus_client` directly | `counter()`, `gauge()` from `src/observability/metrics.py` | Prevents duplicate registration crash |
| Stream key construction | f-strings inline | `src/core/stream_keys` functions | Consistency across publishers and consumers |

---

## Common Pitfalls

### Pitfall 1: Missing market context fields at per-signal call time

**What goes wrong:** The `parse_aggregated_signal()` function reads from the aggregated signal stream. It captures `confidence`, `setup_plugin`, `entry_price`, `stop_loss`, `profit_target`, `regime_context`. However, the `llm_calls` schema also requires `cis_score`, `entry_zone_low`, `entry_zone_high`, `signal_id` (UUID). These are NOT in the aggregated signal fields parsed by `parse_aggregated_signal()`.

**Why it happens:** The aggregated signal stream was designed before the LLM instrumentation requirement. It carries the fields needed for narrative generation, not for full signal reconstruction.

**How to avoid:** The `signal_id` is not available from the aggregated signal stream message. For per-signal calls, `signal_id` should remain NULL in `llm_calls` unless the aggregated signal stream is extended. The design doc already specifies `signal_id` as nullable for group/counterfactual — but it may also be nullable for per-signal if the UUID is not in the stream. Check the aggregated signal schema before assuming signal_id is capturable. `cis_score`, `entry_zone_low`, `entry_zone_high` are also likely missing from the aggregated stream — capture what's available, leave others NULL.

**Warning signs:** `KeyError` on `fields.get(b"signal_id")` or similar during instrumentation implementation.

### Pitfall 2: Adapter scoring recompute skips NULL pnl_r rows

**What goes wrong:** `_SELECT_OUTCOME_ROWS_SQL` groups by model/regime/setup_type/call_type `WHERE outcome IS NOT NULL`. But `pnl_r` can be NULL even when `outcome` is set (e.g., group_synthesis calls have no trade outcome). `win_rate` computed as `AVG(CASE WHEN win THEN 1.0 ELSE 0.0 END)` with `win=NULL` will produce incorrect averages.

**How to avoid:** The score recompute query should additionally filter `WHERE call_type = 'per_signal'` or handle NULL pnl_r explicitly. Aggregate non-per-signal call types separately with different metrics (latency-focused, not win-rate-focused).

### Pitfall 3: Provider chain reorder during active LLM call

**What goes wrong:** `_score_refresh_loop()` in ai_narrative_service mutates `self.per_signal_chain.providers` list. If this runs concurrently with `_process_loop()` or `_group_synthesis_loop()` which iterate the chain, the list could be modified mid-iteration.

**How to avoid:** The LLMChain iterates `self.providers` in a simple for loop. Python list is not thread-safe for concurrent modification. Use an `asyncio.Lock` around the provider chain reorder, or replace the list atomically: `self.per_signal_chain.providers = new_order[:]`. Atomic list replacement is safer and simpler.

### Pitfall 4: Consumer group stale position on service restart

**What goes wrong:** `ensure_consumer_group_with_reset` resets to `"$"` on restart, which means messages emitted while the service was down are skipped. For `llm_outcomes:stream`, this means outcome back-fills could be missed if `llm_writer_service` was restarted.

**How to avoid:** This is acceptable behavior given the architecture — the signal outcome data is in TimescaleDB (`signal_ledger`) and can be reconciled offline. Document this as a known limitation. Do not attempt to read historical positions on restart for either stream.

### Pitfall 5: Migration number conflict

**What goes wrong:** CONTEXT.md says migration `016_llm_intelligence_layer.sql` but 16-01-PLAN.md says `019_llm_intelligence_layer.sql`. The actual next migration number is 019 (018 is the latest existing migration).

**How to avoid:** Use `019_llm_intelligence_layer.sql`. The plan files (16-01, 16-02) already use 019 — they are correct. The CONTEXT.md reference to "016" is the original design doc number before migrations were added. **The planner must use 019.**

---

## Code Examples

### xadd emission pattern (fire-and-forget, from ai_narrative_service)
```python
# Source: services/ai_narrative_service.py _process_single_message() + services/feature_writer_service.py pattern
# After await chain.generate() returns, before acking the message:
asyncio.create_task(self.redis_client.xadd(
    llm_calls_stream(self.env_prefix),
    {
        "call_id":      str(uuid.uuid4()),
        "called_at":    datetime.now(tz=UTC).isoformat(),
        "call_type":    "per_signal",
        "signal_id":    "",              # not in aggregated stream — emit empty string
        "group_name":   "",
        "symbol":       signal_data["symbol"],
        "timeframe":    signal_data["timeframe"],
        "model":        self.per_signal_chain.last_provider_id or "unknown",
        "provider":     (self.per_signal_chain.last_provider_id or "unknown").split(":")[0],
        "prompt":       prompt,
        "response":     narrative_text or "",
        "latency_ms":   str(int(latency_ms)),
        "tokens_est":   str(len((narrative_text or "").split())),
        "succeeded":    "1" if narrative_text else "0",
        "regime":       signal_data.get("regime_context", ""),
        "confidence":   str(signal_data["confidence"]),
        "setup_type":   signal_data.get("setup_plugin", ""),
    },
    maxlen=500, approximate=True
))
```

### Outcome emission (signal_lifecycle_service exit path)
```python
# Source: services/signal_lifecycle_service.py — both exit code paths
# Add after outcome is resolved, before update_signal_status() call:
if self.redis_client:
    asyncio.create_task(self.redis_client.xadd(
        llm_outcomes_stream(self.env_prefix),
        {
            "signal_id":     sid,                              # str UUID
            "outcome":       outcome or "",
            "pnl_r":         str(transition.pnl_r or ""),
            "mae":           str(transition.mae or ""),
            "mfe":           str(transition.mfe or ""),
            "bars_in_trade": str(bit or ""),
            "outcome_at":    datetime.now(tz=UTC).isoformat(),
        },
        maxlen=200, approximate=True
    ))
```

### binomtest usage (llm_writer_service)
```python
# Source: scipy.stats — confirmed available in .venv
from scipy.stats import binomtest

def _build_score_insert_params(
    model, regime, setup_type, call_type,
    n_calls, n_outcomes, win_rate, avg_pnl_r, avg_latency_ms,
) -> tuple:
    if n_outcomes > 0:
        wins = int(round(win_rate * n_outcomes))
        result = binomtest(wins, n_outcomes, 0.50, alternative="greater")
        p_value = result.pvalue
    else:
        p_value = 1.0
    is_significant = (p_value < SCORE_P_THRESHOLD) and (n_outcomes >= SCORE_MIN_N_OUTCOMES)
    return (model, regime, setup_type, call_type, n_calls, n_outcomes,
            win_rate, avg_pnl_r, avg_latency_ms, p_value, is_significant)
```

### Score cache write (Redis HSET)
```python
# Source: CONTEXT.md locked decision + redis.asyncio docs
# After score recompute, write each score row to Redis:
from src.core.stream_keys import llm_scores_cache
import json

cache_key = llm_scores_cache(self._env_prefix, call_type, regime)
score_blob = json.dumps({
    "model": model,
    "win_rate": win_rate,
    "avg_pnl_r": avg_pnl_r,
    "n_outcomes": n_outcomes,
    "p_value": p_value,
    "is_significant": is_significant,
    "score_updated_at": datetime.now(tz=UTC).isoformat(),
})
await self.redis_client.hset(cache_key, model, score_blob)
```

### Provider chain reorder (ai_narrative_service adaptive routing)
```python
# Source: src/intelligence/llm_providers.py — LLMChain.providers is a plain list
# Atomic replacement to avoid mid-iteration mutation:
def _promote_model_in_chain(chain: LLMChain, model_provider_id: str) -> None:
    """Move model with given provider_id to position 0. Atomic list replacement."""
    current = chain.providers
    target = next((p for p in current if p.provider_id == model_provider_id), None)
    if target is None or current[0].provider_id == model_provider_id:
        return  # already at position 0 or not found
    rest = [p for p in current if p.provider_id != model_provider_id]
    chain.providers = [target] + rest  # atomic replacement
```

### execute_batch signature (DatabaseManager)
```python
# Source: src/core/database_manager.py line 70
async def execute_batch(self, statement: str, params: list[list[Any]] | list[tuple]) -> None:
    # Used in feature_writer_service as:
    await self.db_manager.execute_batch(_INSERT_LLM_CALL_SQL, list_of_tuples)
```

---

## Existing Plans Coverage (16-01 and 16-02)

### What 16-01 covers (Wave 1 — foundation):
- `production/migrations/019_llm_intelligence_layer.sql` — both tables + 3 indexes
- `src/core/stream_keys.py` — 3 new functions + Literal extension
- `tests/unit/service_tests/test_llm_writer_service.py` — 10 failing tests (RED)

### What 16-02 covers (Wave 2 — implementation):
- `services/llm_writer_service.py` — complete implementation
- All 10 TDD RED tests turned GREEN
- Full unit suite regression check

### What remains unplanned (3 more plans needed):

**Plan 16-03 (Wave 3): ai_narrative_service instrumentation + adaptive routing**
- LLM-02: xadd after per-signal, group synthesis, and counterfactual calls
- LLM-05: `_score_refresh_loop()` reads Redis HSET, promotes significant models
- Files: `services/ai_narrative_service.py` + tests

**Plan 16-04 (Wave 4): signal_lifecycle_service outcome emission**
- LLM-03: xadd on both exit paths (normal + shadow regime_suppressed)
- Files: `services/signal_lifecycle_service.py` + tests

**Plan 16-05 (Wave 5): Systemd + integration + migration apply**
- LLM-01 (deployment): Apply migration 019 to production DB
- LLM-04 (deployment): `production/systemd/indicagent-llm-writer.service` + enable + start
- Integration smoke test: verify llm_calls rows appear within 30s of signal
- Files: `production/systemd/indicagent-llm-writer.service` + migration applied

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (project venv: `.venv/bin/pytest`) |
| Config file | `pytest.ini` or `pyproject.toml` in project root |
| Quick run command | `.venv/bin/pytest tests/unit/service_tests/test_llm_writer_service.py -v` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LLM-01 | `019_llm_intelligence_layer.sql` creates hypertable + scores table | smoke (grep) | `grep -c "create_hypertable\|llm_model_scores" production/migrations/019_llm_intelligence_layer.sql` | Wave 1 (16-01) |
| LLM-01 | `llm_calls_stream()` key format correct | unit | `.venv/bin/pytest tests/unit/service_tests/test_llm_writer_service.py::test_llm_calls_stream_key_format` | Wave 1 (16-01) |
| LLM-01 | `llm_outcomes_stream()` key format correct | unit | `.venv/bin/pytest tests/unit/service_tests/test_llm_writer_service.py::test_llm_outcomes_stream_key_format` | Wave 1 (16-01) |
| LLM-01 | `llm_scores_cache()` key format correct | unit | `.venv/bin/pytest tests/unit/service_tests/test_llm_writer_service.py::test_llm_scores_cache_key_format` | Wave 1 (16-01) |
| LLM-04 | `_parse_llm_call_fields` parses valid stream message | unit | `.venv/bin/pytest tests/unit/service_tests/test_llm_writer_service.py::test_parse_llm_call_fields_valid` | Wave 1 (16-01) |
| LLM-04 | `_parse_llm_call_fields` returns None on missing required fields | unit | `.venv/bin/pytest tests/unit/service_tests/test_llm_writer_service.py::test_parse_llm_call_fields_missing_required_returns_none` | Wave 1 (16-01) |
| LLM-04 | `_parse_outcome_fields` parses valid exit message | unit | `.venv/bin/pytest tests/unit/service_tests/test_llm_writer_service.py::test_parse_outcome_fields_valid` | Wave 1 (16-01) |
| LLM-04 | `_parse_outcome_fields` returns None on missing signal_id | unit | `.venv/bin/pytest tests/unit/service_tests/test_llm_writer_service.py::test_parse_outcome_fields_missing_signal_id_returns_none` | Wave 1 (16-01) |
| LLM-04 | Score recompute: n < 30 → is_significant=False | unit | `.venv/bin/pytest tests/unit/service_tests/test_llm_writer_service.py::test_build_score_insert_params_below_min_n_not_significant` | Wave 1 (16-01) |
| LLM-04 | Score recompute: n=35 + p=0.02 → is_significant=True | unit | `.venv/bin/pytest tests/unit/service_tests/test_llm_writer_service.py::test_build_score_insert_params_meets_gate_significant` | Wave 1 (16-01) |
| LLM-04 | Score recompute: n=40 + p=0.10 → is_significant=False | unit | `.venv/bin/pytest tests/unit/service_tests/test_llm_writer_service.py::test_build_score_insert_params_high_p_not_significant` | Wave 1 (16-01) |
| LLM-02 | ai_narrative_service emits per-signal xadd payload | unit | `.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py -k llm_call` | Wave 3 (16-03) |
| LLM-02 | Counterfactual emission on low-confidence signal | unit | `.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py -k counterfactual` | Wave 3 (16-03) |
| LLM-05 | Provider chain reorders when significant winner exists | unit | `.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py -k promote` | Wave 3 (16-03) |
| LLM-05 | Chain unchanged when no significant winner | unit | `.venv/bin/pytest tests/unit/service_tests/test_ai_narrative_service.py -k no_promote` | Wave 3 (16-03) |
| LLM-03 | signal_lifecycle emits on normal exit | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_lifecycle_service.py -k llm_outcome` | Wave 4 (16-04) |
| LLM-03 | signal_lifecycle emits on shadow (regime_suppressed) exit | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_lifecycle_service.py -k shadow_outcome` | Wave 4 (16-04) |
| LLM-01/04 | End-to-end: llm_calls row appears within 30s | integration | manual-only (requires live services) | Wave 5 (16-05) |
| LLM-03 | End-to-end: outcome back-fill within 60s of signal close | integration | manual-only (requires live services + closed signal) | Wave 5 (16-05) |
| LLM-04 | Score recompute runs every 15 min | integration | manual-only (check `journalctl -u indicagent-llm-writer`) | Wave 5 (16-05) |
| LLM-05 | Provider chain promotion: model at position 0 after significance | integration | manual-only (requires 30+ outcome rows) | Wave 5 (16-05) |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/service_tests/test_llm_writer_service.py -v`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q`
- **Phase gate:** Full suite green + `ruff check .` 0 errors before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/service_tests/test_llm_writer_service.py` — 10 TDD RED tests (created in 16-01)
- [ ] `services/llm_writer_service.py` — implementation (created in 16-02)
- LLM-02 and LLM-05 tests require additions to existing `test_ai_narrative_service.py` (Wave 3)
- LLM-03 tests require additions to existing `test_signal_lifecycle_service.py` (Wave 4)

---

## Open Questions

1. **signal_id availability in per-signal calls**
   - What we know: `parse_aggregated_signal()` reads from `signals:{SYMBOL}:{TF}:aggregated` stream. The fields parsed are: symbol, timeframe, timestamp, direction, confidence, setup_plugin, entry_price, stop_loss, profit_target, regime_context, supporting_factors. No `signal_id` field is currently emitted to this stream.
   - What's unclear: Is signal_id available anywhere in the `fields` dict that arrives in `_process_single_message()`? The original `xadd` in `signal_generator_service` for the aggregated stream may include `signal_id` even if `parse_aggregated_signal()` doesn't capture it.
   - Recommendation: During 16-03 implementation, check `fields.get(b"signal_id")` in `_process_single_message()`. If present, capture it. If not, signal_id stays NULL for per-signal calls (schema allows it).

2. **cis_score, entry_zone_low, entry_zone_high availability for per-signal calls**
   - What we know: These fields are in the `signal_ledger` and in the `IntelligenceEvent`, but not obviously in `signals:aggregated` stream fields parsed by `parse_aggregated_signal()`.
   - What's unclear: Same as above — the raw `fields` dict may contain these even if the parser ignores them.
   - Recommendation: Same approach — check raw fields during implementation. Emit what's available, NULL what isn't.

3. **Group synthesis signal_id linkage**
   - What we know: Group synthesis in `_synthesize_group()` aggregates across multiple symbols/TFs. There is no single signal_id to link to.
   - What's unclear: Nothing — the design doc explicitly says `signal_id` is nullable for group_synthesis.
   - Recommendation: Always NULL for group synthesis. `group_name` is the linking key instead.

---

## Sources

### Primary (HIGH confidence)
- Direct code read: `services/ai_narrative_service.py` — full file, all methods
- Direct code read: `services/signal_lifecycle_service.py` — full file, all methods
- Direct code read: `services/feature_writer_service.py` — full file, pattern template
- Direct code read: `src/core/stream_keys.py` — full file, current state
- Direct code read: `src/intelligence/llm_providers.py` — LLMChain and provider structure
- Direct code read: `.planning/phases/16-llm-intelligence-layer/16-CONTEXT.md` — locked decisions
- Direct code read: `.planning/phases/16-llm-intelligence-layer/16-01-PLAN.md` — Wave 1 coverage
- Direct code read: `.planning/phases/16-llm-intelligence-layer/16-02-PLAN.md` — Wave 2 coverage
- Direct shell: `ls production/migrations/` — confirmed next migration is 019
- Direct shell: `.venv/bin/python -c "from scipy.stats import binomtest"` — confirmed available
- Direct code read: `src/core/database_manager.py` (grep) — `execute_batch` signature confirmed

### Secondary (MEDIUM confidence)
- Inferred from CLAUDE.md: systemd `Restart=always` pattern, production/systemd/ location
- Inferred from weight-updater.service: exact [Unit]/[Service]/[Install] format for new service file

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries confirmed in project venv and existing code
- Architecture patterns: HIGH — read directly from all three source files
- Pitfalls: HIGH — derived from reading actual code paths and CLAUDE.md gotchas section
- Migration numbering: HIGH — confirmed by listing production/migrations/ directory
- Existing plan coverage: HIGH — read both 16-01 and 16-02 plan files in full

**Research date:** 2026-03-05
**Valid until:** 2026-04-05 (stable domain — no fast-moving external dependencies)

---

## RESEARCH COMPLETE
