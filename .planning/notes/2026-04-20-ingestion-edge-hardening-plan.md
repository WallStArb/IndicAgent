---
created: 2026-04-20
status: in-progress
context: Session pause — context window hit 80%. Resume from this plan.
---

# Ingestion-Edge Hardening Plan

Resume work on hardening the TWS → `base_provider_agent` → `market.bars` pipeline. Audit findings are in the 2026-04-20 session log (scope 1: ingestion edge). Scopes 2 and 3 are separate audits (see todos 030, 031).

## Current state

### Done this session

1. **`services/service_auditor_agent.py`** — data-stoppage counter-persistence bug fix + market-hours gate via new `_any_active_session_open()` helper. Imports `get_active_contracts` + `SESSION_REGISTRY`. All 43 auditor tests pass.
2. **`src/core/kafka_utils.py`** — `AIOKafkaProducer` now configured with `acks='all'`, `enable_idempotence=True`, `compression_type='lz4'`, `max_in_flight_requests_per_connection=5`. **Caveat before restarting services:** verify Redpanda idempotence support is enabled (`rpk cluster config get enable_idempotence`). Check existing consumer groups (feature_writer, signal_writer, bar_writer) are not disturbed by the producer-side change — they shouldn't be since acks/idempotence are producer-only concerns.
3. **Audit todos filed:** `.planning/todos/pending/030-audit-kafka-to-db-writers-pipeline.md`, `031-audit-data-quality-loop.md`.

### Uncommitted files

```
M  services/service_auditor_agent.py   (from earlier session)
M  src/core/kafka_utils.py              (producer durability)
```

Plus the earlier-session changes to `CLAUDE.md`, `src/providers/base_provider_agent.py`, `src/providers/ibkr.py`, and the batch of `_archived_*` deletions.

**Decision needed at resume:** commit producer-durability change on its own, or bundle with the rest of Commit 1 (ping narrow-catch + metric split + timestamp normalizer). Recommend: commit standalone so it can be rolled back independently if Redpanda compat turns out to be an issue.

## Remaining work — 4 commits

### Commit 1 — small-risk quick wins

**Files:** `src/providers/ibkr.py`, `src/providers/base_provider_agent.py`, `src/observability/metrics.py`

- **H4** — `ibkr.py:276` `ping()` broad except. Narrow to `(asyncio.TimeoutError, ConnectionError, OSError)`. Unexpected exceptions should propagate, not silently flag the connection unhealthy.
- **L5** — `base_provider_agent.py:255` split `PROVIDER_RECONNECTS_TOTAL` into `_attempted` and `_succeeded`. Current single counter increments before the attempt, conflating "trying" with "reconnected." Add `PROVIDER_RECONNECTS_SUCCEEDED_TOTAL` in `src/observability/metrics.py` alongside the existing counter (or rename existing → `_attempted` and add `_succeeded`). Update Grafana queries in `production/grafana/` if any reference the old metric name.
- **M6** — extract `_normalize_ib_bar_ts(raw_date) -> datetime` at module top of `ibkr.py`. Replace the two duplicated blocks at lines 369–375 (`fetch_historical_bars`) and 729–735 (`stream_official_bars`).

### Commit 2 — hardening pass

**Files:** `src/providers/ibkr_adapter.py`, `src/providers/ibkr.py`, `src/providers/base_provider_agent.py`, `src/observability/metrics.py`

- **M3** — `ibkr_adapter.py:57-59` replace `_seen_ts` + `_seen_ts_order` (set + deque(maxlen=30)) with a single `_last_emitted_ts: dict[str, datetime]` and check `if ts <= self._last_emitted_ts.get(sym): return None`. Deletes deque import.
- **M4** — `ibkr.py:659` silent drop in `stream_real_time_bars._on_bar`: add a counter `PROVIDER_BARS_DROPPED_TOTAL{provider, agent, reason="rtb_queue_full"}` and log at warning. Same pattern needed at `ibkr.py:751` (silent drop in `_on_official_bar`) — reason="official_queue_error" or similar.
- **M5** — `ibkr_adapter.py:95` `bar_queue` currently unbounded. Cap at `maxsize=10000`; use `put_nowait` with drop-counter (reuse metric from M4).
- **M8** — `base_provider_agent.py:291 _gap_requests_loop`: add IBKR pacing guard. Simple approach: `asyncio.Semaphore(1)` + `asyncio.sleep(0.2)` between fetches (5 req/sec sustained) OR `AsyncLimiter` from aiolimiter (10 req / 10 sec). Protects against Error 162.
- **L1** — `ibkr_adapter.py:144` change `logger.warning` → `logger.error` in `_official_bars_stream` exception path.
- **L2** — `ibkr.py:608` wrap `_handle_pending_tickers` callback body in try/except with logger.exception.
- **L3** — `ibkr.py:639` use `self._tick_queue_size` instead of hardcoded `10_000`.
- **L4** — unify naming. Pick `provider_name_str` (method — the agent-side choice) or `provider_name` (attribute — the adapter-side choice). Whichever is less disruptive.

### Commit 3 — reconnect consolidation (biggest change)

**Files:** `src/providers/base_provider_agent.py`, `src/providers/ibkr_adapter.py`, `src/providers/ibkr.py`

Approach: single coordination point is the adapter's `bar_queue._RECONNECT` sentinel. All reconnect signals flow through it.

- **H1** — delete `BaseProviderAgent._health_check_loop` (lines 384–415) and remove it from the gather in `_run()` (lines 169, 173). Move the active-ping idea into the adapter's `_bar_flow_watchdog`:
  - When `silence_s > threshold_soft` (e.g. 5 min) and `is_connected()` returns True, call `ping()` to disambiguate "quiet market" from "dead subscription."
  - If ping fails → enqueue `_RECONNECT` sentinel immediately.
  - If ping succeeds but silence continues past `_NO_BAR_TIMEOUT_S` (20 min) → keep existing behavior (force restart).
  - Now we have one reconnect path, active detection available, no race between `_health_check_loop` calling `disconnect()` and the adapter's own cleanup.
- **M1** — `base_provider_agent.py:254`: change `delay = min(2 ** (attempt + 1), 10)` → `base = min(2 ** (attempt + 1), 30); delay = base * random.uniform(0.5, 1.5)`. Raise cap from 10 → 30s and add jitter. Import `random` at top.
- **M2** — `base_provider_agent.py:216-246 _stream_loop`: reset `attempt = 0` after receiving N bars successfully (say first bar after the `async for` starts yielding). Cleanest: set `attempt = 0` inside the `async for` at the top of the loop body, before `_publish_bar`. That way every successful bar resets the backoff state.

### Commit 4 — Kafka fire-and-batch

**Files:** `src/core/kafka_utils.py`, callers of `KafkaProducerClient.publish`

- **H2/M7** — `kafka_utils.py:98` change `await self._producer.send_and_wait(...)` → `await self._producer.send(...)` (returns future immediately after buffering, lets aiokafka batch internally). Add a `flush()` call in `stop()` before `producer.stop()`.
- Tuning: add `linger_ms=5, batch_size=16384` to the `AIOKafkaProducer` constructor (low linger so latency-sensitive callers aren't hurt; batch_size is default).
- **Caller audit required** — some callers may expect synchronous durability (e.g. signal_writer finalizing a ledger write before acknowledging). Grep for `KafkaProducerClient` and `producer.publish` usages; any caller that needs "after publish() returns, it's durable" should call `await producer.flush()` explicitly, OR we add a `publish_sync()` method that preserves the old semantics.
- Run full test suite after this one — it's the most behavior-changing.

## Risk / rollback

Each commit is self-contained and independently revertable. Commit 3 and 4 are the behavior-changing ones; 1 and 2 are localized hardening.

After all four land, restart the ingestion stack in order:
```bash
sudo systemctl restart indicagent-ibkr-provider
# wait ~30s, check bars_per_sec via curl localhost:9129/metrics
sudo systemctl restart indicagent-service-auditor
```

Watch `logs/ibkr_provider_agent.log` and `logs/service_auditor_agent.log` for the first 10 minutes post-deploy.

## Open question for resume

If scope 2 (Kafka → DB writers) audit happens before these fixes ship, findings may overlap (particularly around idempotency / durability). Worth considering whether to bundle everything into a coherent "data-pipeline v2" milestone rather than landing this ad-hoc. Neutral recommendation — depends on how urgently the H1/H3 fixes are needed.
