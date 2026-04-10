# Parallel Self-Healing Auditor Pipeline

**Date:** 2026-04-10  
**Status:** Approved — ready for implementation  
**Phase:** TBD (assign after roadmap review)

---

## Problem

The four auditor services make hundreds of sequential DB roundtrips per 5-minute cycle:

| Service | Current roundtrips/cycle | Root cause |
|---|---|---|
| `BarAuditorAgent` | 354 | Nested `for instrument × for days_back × await fetchval()` |
| `SignalAuditorAgent` (coverage) | 236 | `for instrument × for tf × await fetchval()` |
| `SignalAuditorAgent` (lag) | 236 | `for instrument × for tf × await fetchrow()` |
| `ServiceAuditorAgent` (systemd) | 12 sequential subprocess calls | — |
| Gap fulfillment | Serial (one at a time) | Kafka consumer loop processes synchronously |

With 59 active instruments × 4 timeframes, each 5-minute audit cycle burns 826+ sequential DB roundtrips. The bar auditor only fills 1m gaps — HTF gaps (5m, 15m, 1h, 4h) are logged but never healed. Signal coverage gaps have no self-healing trigger at all.

---

## Renaissance Principles Applied

- **Instrument everything** — all TFs get gap detection and gap fill, not just 1m
- **Let the system run** — concurrent, bounded self-healing without manual intervention
- **Never drop data** — canonical signals for every bar, every TF, every session
- **Segment relentlessly** — one utility module, each auditor owns its domain
- **Degrade gracefully** — semaphore caps IBKR concurrency; auditors survive transient failures
- **Data quality over complexity** — batch SQL does in 1 query what N loops do in N×M

---

## Architecture

```
[BarAuditorAgent]      batch SQL (1 query) → BarGapRequest(all TFs) → [BaseProviderAgent]
                                                                              │ semaphore(3)
                                                                              ↓
                                                                       [BarWriterAgent]
                                                                       [BarAggregatorAgent]

[SignalAuditorAgent]   batch SQL (2 queries) → SignalReplayRequest → [BarReplayAgent]
                                                                           │ DB → Kafka
                                                                           ↓
                                                                 [IntelligencePipelineAgent]
                                                                           ↓
                                                                      signal_ledger

[ServiceAuditorAgent]  asyncio.gather(12 parallel) → systemd checks

[src/core/audit_utils.py]  pure functions — shared by Bar + Signal auditors
```

**New topic:** `market.events.signal_replay_requests`  
**New module:** `src/core/audit_utils.py`  
**New service:** `BarReplayAgent` (`services/bar_replay_agent.py`)  
**Modified:** `BarAuditorAgent`, `SignalAuditorAgent`, `ServiceAuditorAgent`, `BaseProviderAgent`, `stream_keys.py`  
**Minimal change:** `IntelligencePipelineAgent` — one-line monotonic guard fix (see Section 8)

---

## Component Designs

### 1. `src/core/audit_utils.py` — Batch SQL Utilities

Pure async functions. No Prometheus, no Kafka, no logging. Callers own those concerns.

**Dataclasses returned:**

```python
@dataclass
class BarCompletenessResult:
    symbol: str
    tf: str
    session_start: datetime
    session_end: datetime
    expected: int   # derived from session math in Python
    actual: int

@dataclass  
class SignalCoverageResult:
    symbol: str
    tf: str
    session_start: datetime
    session_end: datetime
    signal_count: int
    p50_lag_ms: float | None
    p95_lag_ms: float | None
```

**`batch_bar_completeness(pool, instruments, lookback_days=3) → list[BarCompletenessResult]`**

Session window math (TradingSession logic) stays in Python — it's not SQL-expressible. We compute `(symbol, tf, session_start_utc, session_end_utc, expected)` tuples for all `(instrument × date × tf)` combinations (1m + all HTF), then pass them to Postgres as UNNEST arrays. Including `tf` in the UNNEST ensures every combination returns a result row — even with `actual=0` when no bars exist for that TF/session (a pure GROUP BY on a nullable JOIN column would silently drop zero-bar rows):

```sql
SELECT
    ref.symbol, ref.tf, ref.session_start, ref.session_end, ref.expected,
    COUNT(m.timestamp) AS actual
FROM UNNEST($1::text[], $2::text[], $3::timestamptz[], $4::timestamptz[], $5::int[])
    AS ref(symbol, tf, session_start, session_end, expected)
LEFT JOIN market_data_ohlcv m
    ON  m.symbol    = ref.symbol
    AND m.timeframe = ref.tf
    AND m.timestamp >= ref.session_start
    AND m.timestamp <  ref.session_end
GROUP BY ref.symbol, ref.tf, ref.session_start, ref.session_end, ref.expected
```

**354 roundtrips → 1.**

Python pre-computes expected counts per TF: `expected_1m` for 1m rows, `expected_1m // tf_minutes` for HTF rows — all passed in the UNNEST, no post-query math needed.

**`batch_signal_coverage(pool, instruments, coverage_tfs, lookback_days=1) → list[SignalCoverageResult]`**

Coverage count + P50/P95 lag per `(symbol, tf)` pair in one GROUP BY:

```sql
SELECT
    ref.symbol, ref.tf, ref.session_start, ref.session_end,
    COUNT(s.feature_ts)                                                    AS signal_count,
    percentile_cont(0.50) WITHIN GROUP (ORDER BY s.pipeline_lag_ms)       AS p50,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY s.pipeline_lag_ms)       AS p95
FROM UNNEST($1::text[], $2::text[], $3::timestamptz[], $4::timestamptz[])
    AS ref(symbol, tf, session_start, session_end)
LEFT JOIN signal_ledger s
    ON  s.symbol     = ref.symbol
    AND s.timeframe  = ref.tf
    AND s.feature_ts >= ref.session_start
    AND s.feature_ts <  ref.session_end
    AND s.pipeline_lag_ms IS NOT NULL
GROUP BY ref.symbol, ref.tf, ref.session_start, ref.session_end
```

**472 roundtrips → 1** (coverage + lag in a single pass).

---

### 2. `BarAuditorAgent` Changes

- Replace `_detect_gaps` body: call `batch_bar_completeness(self._db_pool, instruments)` — one DB roundtrip
- Publish `BarGapRequest` for **all TFs** with gaps (1m, 5m, 15m, 1h, 4h), not just 1m
- Dedup key: `(symbol, date_str, tf)` — prevents infinite retry per TF independently
- HTF expected counts: `expected_htf = result.expected // _HTF_TF_MINUTES[tf]` (same math, already available)
- Completeness gauge: label with `tf` as before — now updated for all TFs in one cycle

**Self-healing scope expanded:** bar aggregator downtime (like today's incident) leaves HTF gaps. The auditor now detects and fills them directly from IBKR, not waiting for the aggregator to replay.

---

### 3. `SignalAuditorAgent` Changes

- Replace `_check_coverage` + `_check_pipeline_lag` with single `batch_signal_coverage(...)` call — one DB roundtrip covers both metrics
- On coverage gap (`signal_count == 0`): publish `SignalReplayRequest` to `topic_signal_replay_requests`
- `_check_cis_distribution` stays as-is — already a clean GROUP BY tf query
- `SignalCoverageGapEvent` to Kafka (`intelligence.signal.audit`) — unchanged, still published as audit trail

**Signal gap taxonomy:**
- Gap caused by bar gap → self-heals through bar gap fill pipeline (BarAuditorAgent handles root cause)
- Gap caused by pipeline downtime (bars exist, signals don't) → `SignalReplayRequest` → `BarReplayAgent`

The signal auditor doesn't distinguish — it publishes replay requests for all coverage gaps. If bars are also missing, bar gap fill runs first, and the replay request fills in signals once bars are present.

---

### 4. `ServiceAuditorAgent` Changes

Single change — `_systemd_check_loop`:

```python
# Before: 12 sequential subprocess calls (~12s wall time)
for spec in _SORTED_REGISTRY:
    active, sub = await self._check_systemd_state(spec.unit)
    ...

# After: 12 concurrent subprocess calls (~1s wall time)
results = await asyncio.gather(
    *[self._check_systemd_state(spec.unit) for spec in _SORTED_REGISTRY],
    return_exceptions=True,
)
for spec, result in zip(_SORTED_REGISTRY, results):
    if isinstance(result, Exception):
        continue
    active, sub = result
    if active in ("failed", "inactive") or sub == "start-limit-hit":
        await self._evaluate_service(spec, active, sub, 0, False)
```

DAG order (`dag_order` field) is preserved for the restart policy — `_evaluate_service` still respects it. The parallelism is in detection only; remediation remains ordered.

---

### 5. `BaseProviderAgent` — Semaphore-Bounded Gap Fill

Current: serial Kafka consumer loop — one gap at a time.

New: fire-and-track task pool. Consumer loop creates tasks immediately; semaphore caps concurrent IBKR historical data requests at 3 (IBKR pacing limit). Tasks drain on SIGTERM.

```python
_MAX_CONCURRENT_GAP_FILLS: int = 3  # IBKR pacing: exceed this → Error 162

async def _gap_requests_loop(self) -> None:
    sem = asyncio.Semaphore(_MAX_CONCURRENT_GAP_FILLS)
    tasks: set[asyncio.Task] = set()
    try:
        async for _topic, _key, payload in gap_consumer.messages():
            if self._stop_event.is_set():
                break
            req = BarGapRequest.model_validate(payload)
            task = asyncio.create_task(self._fill_gap(req, sem))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
    finally:
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await gap_consumer.stop()

async def _fill_gap(self, req: BarGapRequest, sem: asyncio.Semaphore) -> None:
    async with sem:
        # existing fetch + publish logic — unchanged
```

---

### 6. `BarReplayAgent` (New Service)

**Single responsibility:** consume `SignalReplayRequest` events, fetch historical bars from `market_data_ohlcv`, republish to `market.bars` or `market.bars.htf`. The intelligence pipeline processes them naturally — zero changes to the hot path.

**Key design decisions:**
- No IBKR dependency — reads from DB (data is already there)
- Reuses existing `BarMessage` schema — no schema changes
- Bounded concurrency: `asyncio.Semaphore(5)` — up to 5 concurrent (symbol, tf) replays
- Dedup guard: `_replay_in_progress: set[str]` — prevents duplicate replays for same `(symbol, tf, date)`
- Routes by timeframe: 1m bars → `topic_market_bars`, HTF bars → `topic_market_bars_htf`
- Publishes in chronological order within each window — BarAccumulator state stays coherent
- Metrics port: `:9135`
- Systemd unit: `indicagent-bar-replay`

**Schema — `SignalReplayRequest`:**
```python
class SignalReplayRequest(BaseModel):
    request_id: UUID = Field(default_factory=uuid4)
    symbol: str
    tf: str
    session_start: datetime
    session_end: datetime
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
```

**Routing logic:**
```python
topic = topic_market_bars(env) if req.tf == "1m" else topic_market_bars_htf(env)
```

**Golden Signals (Prometheus):**
- `bar_replay_requests_total` — replays consumed
- `bar_replay_bars_published_total{symbol,tf}` — bars re-published
- `bar_replay_errors_total` — failures
- `bar_replay_duration_seconds` — per-replay latency

---

### 7. `stream_keys.py` Addition

```python
def topic_signal_replay_requests(env_name: str) -> str:
    """Kafka topic for SignalReplayRequest events from SignalAuditorAgent.

    BarReplayAgent consumes these and re-publishes historical bars from
    market_data_ohlcv to market.bars / market.bars.htf so the intelligence
    pipeline can recompute missing signals.
    """
    return f"{env_prefix(env_name)}market.events.signal_replay_requests"
```

---

## Data Flow (Post-Implementation)

### Bar gap self-healing
```
BarAuditorAgent (startup + every 5min)
  → batch_bar_completeness() [1 SQL query]
  → BarGapRequest(symbol, tf) for all TFs with gaps
  → market.events.gap_requests
  → BaseProviderAgent._fill_gap() [semaphore(3) concurrent]
  → market.bars.raw.ibkr
  → ProviderMergerAgent
  → market.bars / market.bars.htf
  → IntelligencePipelineAgent → signal_ledger
```

### Signal gap self-healing
```
SignalAuditorAgent (startup + every 5min)
  → batch_signal_coverage() [1 SQL query]
  → SignalReplayRequest(symbol, tf, session_start, session_end)
  → market.events.signal_replay_requests
  → BarReplayAgent._replay() [semaphore(5) concurrent]
  → SELECT from market_data_ohlcv [chronological]
  → market.bars / market.bars.htf
  → IntelligencePipelineAgent → signal_ledger
```

---

## Performance Impact

| Metric | Before | After |
|---|---|---|
| Bar audit DB roundtrips | 354/cycle | 1/cycle |
| Signal audit DB roundtrips | 472/cycle | 2/cycle |
| Systemd check wall time | ~12s | ~1s |
| Gap fill throughput | 1 at a time | 3 concurrent |
| HTF gaps self-healed | Never | Yes — all TFs |
| Signal gaps self-healed | Never | Yes — pipeline downtime case |

---

### 8. `IntelligencePipelineAgent` — Monotonic `_last_bar_ts` Guard

Replay bars arrive with historical timestamps. Without a guard, a replay bar for yesterday would overwrite `_last_bar_ts[symbol:tf]` with a past value — making the next live bar appear as a massive gap to the gap detector.

Fix: only update `_last_bar_ts` if the incoming bar is more recent than what we already have. One line in `_process_bar`:

```python
# Before
self._last_bar_ts[key] = bar.ts.timestamp()

# After
if bar.ts.timestamp() > self._last_bar_ts.get(key, 0):
    self._last_bar_ts[key] = bar.ts.timestamp()
```

This is a correctness fix independent of replay — monotonic timestamp tracking should always have been the behaviour. Replay just exposed it.

---

## Testing Requirements

- `tests/unit/test_audit_utils.py` — pure function tests for `batch_bar_completeness` and `batch_signal_coverage` with mock pool
- `tests/unit/service_tests/test_bar_auditor_agent.py` — update to mock `batch_bar_completeness`
- `tests/unit/service_tests/test_signal_auditor_agent.py` — update to mock `batch_signal_coverage`
- `tests/unit/service_tests/test_bar_replay_agent.py` — new, test replay routing logic
- `tests/unit/service_tests/test_service_auditor_agent.py` — verify `asyncio.gather` path
- `tests/unit/test_base_provider_agent.py` — verify semaphore concurrency cap

---

## Files Changed

| File | Change |
|---|---|
| `src/core/audit_utils.py` | **New** — batch SQL utilities |
| `src/core/stream_keys.py` | Add `topic_signal_replay_requests` |
| `src/core/schemas/market_events.py` | Add `SignalReplayRequest` schema |
| `services/bar_auditor_agent.py` | Use `batch_bar_completeness`, all-TF gap requests |
| `services/signal_auditor_agent.py` | Use `batch_signal_coverage`, publish replay requests |
| `services/service_auditor_agent.py` | `asyncio.gather` for systemd checks |
| `services/bar_replay_agent.py` | **New** — replay consumer |
| `src/providers/base_provider_agent.py` | Semaphore-bounded gap fill |
| `services/intelligence_pipeline_agent.py` | Monotonic `_last_bar_ts` guard (1 line) |
| `production/systemd/indicagent-bar-replay.service` | **New** — systemd unit template |
| `tests/unit/test_audit_utils.py` | **New** |
| `tests/unit/service_tests/test_bar_replay_agent.py` | **New** |
| Updated existing test files | 5 files updated |
