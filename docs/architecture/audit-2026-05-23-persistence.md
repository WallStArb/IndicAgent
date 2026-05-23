# Persistence Pattern Audit — 2026-05-23

**Scope:** 13 writer services across `services/` + repositories in `src/persistence/repository/`
**Reference implementation:** `services/contract_metadata_writer_agent.py`
**Migrations audited:** `093_ml_signal_training_compression.sql`, `094_signal_ledger_cis_columns.sql`

---

## Finding P-1: LLMWriterAgent — AttributeError crash on `_parse_update` messages

**Severity:** CRITICAL
**Category:** Information Destruction
**Files:** `services/llm_writer_service.py:695`

**Description:**
`_process_calls_message()` references `self._pool` when `payload.get("_parse_update")` is truthy:

```python
async with self._pool.acquire() as conn:
    await conn.execute(_UPDATE_PARSE_SQL, call_id, parse_success)
```

`self._pool` is never initialized anywhere in `LLMWriterAgent`. The class only initializes `self.db_manager` (a `DatabaseManager`). Neither `BaseWriterAgent` nor `BaseAgent` define `_pool`. Any `_parse_update` message arriving on `{env}.llm.calls` raises `AttributeError: 'LLMWriterAgent' object has no attribute '_pool'`. This exception propagates to `_process_loop` where it is caught by the outer `except Exception` and swallowed with a log entry — the `parse_success` back-fill is silently dropped. Over time, the `llm_calls` table accumulates rows where `parse_success` remains NULL/True even when the agent failed JSON parsing. This corrupts the LLM calibration feedback loop.

**Fix:** Replace `self._pool.acquire()` with `await self.db_manager.execute_command(_UPDATE_PARSE_SQL, call_id, parse_success)`.

---

## Finding P-2: CtxWriterAgent — no DLQ topic configured; validation failures silently discarded

**Severity:** HIGH
**Category:** Information Destruction
**Files:** `services/ctx_writer_agent.py` (no `_dlq_topic` override), `src/core/agent/base.py:390-395`

**Description:**
`CtxWriterAgent` calls `self._maybe_route_to_dlq(payload, ...)` at line 186 when `_parse_payload` returns `None` (all four validation failure paths). However, the class does not override `_dlq_topic()`, so `BaseAgent._send_to_dlq()` resolves the DLQ topic to `None` and falls through to the log-and-discard path:

```python
if dlq_topic is None:
    self.logger.error("agent.dlq_discard", ...)
    return
```

Every rejected CTX event (wrong `event_type`, oversized payload, missing required keys, invalid `event_ts`) is permanently discarded. There is no way to replay these events. CTX events drive macro context in `intelligence_features` — a lost earnings or macro event means bars during that window have a NULL `ctx` column. Downstream LLM prompts and regime analysis receive incomplete context.

**Fix:** Add `def _dlq_topic(self) -> str | None: return topic_ctx_snapshot_dlq(self.settings.env_name)` and register that topic in `stream_keys.py`.

---

## Finding P-3: OTel `.inc()` method calls crash at runtime on flush

**Severity:** HIGH
**Category:** Information Destruction
**Files:** `services/ctx_writer_agent.py:343,351`, `services/llm_writer_service.py:822`

**Description:**
OTel counter objects created via `metrics.counter()` expose `.add(delta, attributes)` per the OTel SDK API. Three call sites use the non-existent `.inc()` method:

- `ctx_writer_agent.py:343` — `self._events_written.inc(len(event_batch))`
- `ctx_writer_agent.py:351` — `self._snapshots_written.inc(len(snapshot_batch))`
- `llm_writer_service.py:822` — `self.i8_writes_total.inc(len(batch))`

These raise `AttributeError` at flush time. In `CtxWriterAgent._flush()`, the exception propagates up through `_do_flush()`, which catches it and increments `_flush_errors_total` — causing the buffers to never clear. Every subsequent flush attempt re-fails for the same reason, growing the buffer until overflow drops rows. For `LLMWriterAgent._flush_i8()`, the exception propagates to the `except Exception` block at line 825, leaving `_i8_buffer` intact (correct retry intent) but the i8 data never flushes.

**Fix:** Replace all `.inc(n)` calls with `.add(n)` (no attributes needed for these counters).

---

## Finding P-4: SwarmLedgerWriterAgent — no DLQ, no error counter, errors silently swallowed

**Severity:** HIGH
**Category:** Alpha Leakage / Feedback Loop Gap
**Files:** `services/swarm_ledger_writer_agent.py:69,114-116`

**Description:**
`SwarmLedgerWriterAgent` extends `BaseAgent` (not `BaseWriterAgent`) and implements no DLQ routing. The main loop at line 114 catches all exceptions and downgrades them to `WARNING`:

```python
except Exception as exc:
    self.logger.warning("swarm_ledger_writer.handle_failed", error=str(exc))
```

There is no error counter, no DLQ, and no dead-letter mechanism. Any persistent failure (DB unavailable, schema mismatch, asyncpg type error) results in continuous silent drops of swarm aggregate adjustments. The `SWARM_SIGNAL_LEDGER_UPDATE_TOTAL` counter only fires inside `_apply_projection` after the retry loop — it is never incremented when `_handle_event` itself raises (e.g., invalid field type on `.get()`). More critically, `_apply_projection` tracks `status="miss"` only after retry exhaustion, but network/DB errors during the UPSERT are not counted at all.

The downstream impact: `signal_ai_enrichment` rows never get `swarm_multiplier`/`adjusted_confidence` populated. Any downstream read that depends on these columns (dashboard, narrative compute, ML scorer) silently reads NULL.

**Fix:** Add an error counter, wrap the outer exception handler to increment it, and consider routing failed payloads to a DLQ topic (or at minimum `signal_ai_enrichment` shadow table for replay).

---

## Finding P-5: FeatureWriterAgent — silent DB connection failure enables ghost-run mode

**Severity:** HIGH
**Category:** Information Destruction
**Files:** `services/feature_writer_agent.py:406-414`

**Description:**
`_connect_database()` catches all DB connection exceptions and silently sets `self.db_manager = None`:

```python
except Exception as e:
    self.logger.warning("Database unavailable, persistence disabled", error=str(e))
    self.db_manager = None
```

When `db_manager` is `None`, `_flush_batch()` raises `RuntimeError("No database connection")`. `BaseWriterAgent._do_flush()` catches this and increments `_flush_errors_total` but does NOT crash the service. The `FeatureWriterAgent` continues consuming Kafka messages and filling its buffer. After `MAX_BUFFER_SIZE=10_000` rows are buffered, the overflow logic silently drops the oldest rows. No alert fires to the operator. The service looks healthy (consuming, logging health checks) but writes zero rows to `intelligence_features`. This is the highest-volume persistence path in the system — ~4 bars/min × 10 symbols × 4 timeframes = ~160 rows/min, all lost.

**Fix:** Raise in `_connect_database()` rather than swallowing, so `_setup()` fails hard and systemd restarts the service. Add a connectivity health metric (`feature_writer_db_connected`) to make this state visible in Grafana.

---

## Finding P-6: SignalWriterAgent — `signals=[]` payload triggers DLQ instead of no-op

**Severity:** MEDIUM
**Category:** Feedback Loop Gap
**Files:** `services/signal_writer_agent.py:105-107`

**Description:**
`_parse_payload` returns `None` when `payload.get("signals", [])` is empty:

```python
if not signals:
    return None  # comment says: "base class will DLQ the whole message"
```

Per the `_parse_payload` contract (CLAUDE.md): `None` = truly unparseable, `[]` = valid-but-empty. An `intelligence.i7.signals` payload with `signals=[]` is semantically valid — it means the bar was processed but no signals fired. The intelligence pipeline currently guards against emitting `signals=[]` (only publishes when `result.signals_payload` is truthy), but any backfill tool, replay script, or test fixture that publishes an empty-signals payload will have it routed to DLQ as if it were corrupted. This creates DLQ noise that obscures real parse failures during incident response.

**Fix:** Change the guard to `return [] if not signals else None` — or more accurately, return `[]` for empty `signals` and reserve `None` for missing required fields (`symbol`, `tf`).

---

## Finding P-7: SignalMetricsWriterAgent — per-row DB inserts inside `_flush_batch`

**Severity:** MEDIUM
**Category:** Alpha Leakage (latency)
**Files:** `services/signal_metrics_writer_agent.py:251-271`

**Description:**
`_flush_batch` iterates over events and calls separate `conn.execute()` per event:

```python
async with self._db.get_connection() as conn:
    for event in batch:
        ...
        await _handle_metrics_computed(conn, event_dict)
```

Each `_handle_metrics_computed` call issues 1-2 `conn.execute()` calls (one UPSERT to `signal_metrics`, one conditional UPSERT to `setup_performance`). With `BATCH_SIZE=50`, a full batch requires 50-100 serial round-trips inside a single connection. At p95 DB latency of ~1ms per round-trip, this is 50-100ms per flush cycle. More critically, a DB error on any single row raises and propagates — the entire batch is retried on next flush, causing duplicate UPSERTs on already-written rows (safe due to ON CONFLICT but wasteful). There is also no custom error counter on this writer — failures are only tracked via `BaseWriterAgent._flush_errors_total`.

**Fix:** Refactor `_handle_metrics_computed` to accept a list and use `conn.executemany()` for the `signal_metrics` UPSERT. The `setup_performance` shim can remain per-row since it's gated on 4 conditions that rarely all match.

---

## Finding P-8: LLMWriterAgent — `auto_offset_reset="latest"` on a writer with critical data

**Severity:** MEDIUM
**Category:** Information Destruction
**Files:** `services/llm_writer_service.py:568`

**Description:**
The Kafka consumer is configured with `auto_offset_reset="latest"`:

```python
kafka_consumer = KafkaConsumerClient(
    ...
    auto_offset_reset="latest",
)
```

All other writer agents use `"earliest"`. A service restart or crash during normal operation will skip any messages that arrived while the service was down. LLM call audit records, outcome back-fills, and i8 enrichments published during the outage window are permanently lost. The `llm_calls` hypertable will have gaps, and `llm_model_scores` recomputation will train on incomplete data — degrading model quality silently.

**Fix:** Change to `auto_offset_reset="earliest"`. Idempotency is already guaranteed by `ON CONFLICT (call_id, called_at) DO NOTHING` in `_INSERT_LLM_CALL_SQL`.

---

## Finding P-9: BarWriterAgent — uses private histogram metric, excluded from shared dashboard

**Severity:** MEDIUM
**Category:** Feedback Loop Gap (observability)
**Files:** `services/bar_writer_agent.py:71-75,118,186`

**Description:**
`BarWriterAgent` creates its own histogram `bar_writer_persistence_batch_latency_seconds` with label key `"agent"` and never records to `PERSISTENCE_BATCH_LATENCY`. All other writers record to the shared `persistence_batch_latency_seconds` histogram with label key `"agent_id"`. Grafana queries using `persistence_batch_latency_seconds{agent_id=~".*"}` will exclude bar writer latency entirely. The label key inconsistency (`"agent"` vs `"agent_id"`) also means the bar writer's own metric cannot be compared against others on a shared panel.

**Fix:** Remove `_BATCH_LATENCY` and replace with `PERSISTENCE_BATCH_LATENCY.record(..., {"agent_id": "bar_writer_agent"})` to match the fleet-wide pattern.

---

## Finding P-10: FeatureWriterAgent — `_batch_latency_attrs` label value is truncated

**Severity:** LOW
**Category:** Feedback Loop Gap (observability)
**Files:** `services/feature_writer_agent.py:276`

**Description:**
`self._batch_latency_attrs = {"agent_id": "feature_writer"}` uses a truncated label value. All other writers use the full service name: `"signal_writer_agent"`, `"lifecycle_writer_agent"`, `"graduation_writer_agent"`. This makes Grafana label selectors inconsistent and breaks any dashboard filter that uses the agent name to match against `systemctl` service names (which are derived from the full agent name).

**Fix:** Change to `{"agent_id": "feature_writer_agent"}`.

---

## Finding P-11: GraduationWriterAgent — `_parse_payload` returns `None` for missing required keys without counter increment

**Severity:** LOW
**Category:** Feedback Loop Gap
**Files:** `services/graduation_writer_agent.py:87-92`

**Description:**
When required keys are missing, `_parse_payload` returns `None` (triggering DLQ) but does not increment any validation error counter. The base class will increment `_parse_failures_total`, which is correct, but the graduation writer has its own `_write_errors` counter that is only incremented in `_flush_batch`. A systematic upstream schema change causing all graduation events to be rejected would be invisible to the `graduation_writer_write_errors_total` metric — operators would only see `graduation_writer_agent_parse_failures_total` (the BaseWriterAgent-managed metric).

**Fix:** Add a validation counter (e.g., `graduation_writer_validation_errors_total`) and increment it in `_parse_payload` before returning `None`.

---

## Finding P-12: LifecycleWriterAgent — exit transitions use per-row `execute_command` instead of `executemany`

**Severity:** LOW
**Category:** Alpha Leakage (latency)
**Files:** `services/lifecycle_writer_agent.py:162-181`

**Description:**
`_flush_exit_items` iterates over exit transition items and issues one `execute_command()` per item to support the idempotency guard (`WHERE exit_at IS NULL`):

```python
for entry in items:
    result: str = await self._db.execute_command(self._EXIT_IDEMPOTENT_SQL, ...)
```

This is architecturally intentional — the "first writer wins" design requires per-row feedback on whether rows were updated. However, at high exit rates (e.g., TTL expiry sweep during batch lifecycle replay), a batch of 100 exits requires 100 serial DB round-trips. In production with ~10 signals/day × 10 symbols this is negligible, but lifecycle replay of historical data (100k+ exits) can cause queue backlog.

**Fix:** Document the intentional design choice with an inline comment noting the tradeoff. No immediate code change needed unless replay performance becomes an issue.

---

## Finding P-13: Migration 093/094 — no stale column references found in active writer paths

**Severity:** LOW (resolved)
**Category:** Information Destruction (historically)
**Files:** `src/persistence/repository/signal_ledger_repository.py`

**Description:**
Migration 093 (`093_ml_signal_training_compression.sql`) only adds TimescaleDB compression policy to `ml_signal_training` — no columns dropped. Migration 094 (`094_signal_ledger_cis_columns.sql`) adds `cis_score`, `bucket_scores`, and `weights_version` back to `signal_ledger` (previously dropped in Phase 104 storage redesign).

Commit `e58e0e87` already resolved the stale column references in `signal_ledger_repository.py`. Current writer code (`signal_writer_agent.py`, `signal_ledger_repository.py`) correctly references all three columns added by migration 094. `weight_updater.py` queries `bucket_scores` and `outcome` from `signal_ledger` — both exist post-094. No active writer paths reference dropped columns.

**Fix:** None required. Confirm migration 094 has been applied to production before deploying services that reference the new columns.

---

## Compliance Matrix

| Writer | Named Params | Batch Inserts | DLQ Wired | Pydantic Validation | Error Counter | `_parse_payload` Contract |
|---|---|---|---|---|---|---|
| `contract_metadata_writer_agent.py` | YES | YES | YES | YES (RollEvent) | YES | N/A (custom `_run`) |
| `signal_writer_agent.py` | YES (via `_to_row()`) | YES (`execute_batch`) | YES | PARTIAL (`validate_signal`) | YES | PARTIAL (returns `None` for `signals=[]` — P-6) |
| `feature_writer_agent.py` | YES (positional tuples, 31-param) | YES (`execute_batch`) | YES | YES (BarIntelligenceRecord) | YES | YES |
| `lifecycle_writer_agent.py` | YES (positional tuples) | YES (`execute_batch`) / per-row for exits (P-12) | YES | PARTIAL (`from_dict` validation) | YES | YES |
| `lineage_writer_agent.py` | YES (positional tuples, 10-param) | YES (`conn.executemany`) | YES | YES (`payload_model = LineageEvent`) | NO (base only) | YES |
| `llm_writer_service.py` | YES (positional tuples, 27-param) | YES (calls only) / per-row (outcomes) | YES | NO (hand-rolled `_parse_llm_call_fields`) | YES | YES (but `_pool` crash — P-1) |
| `ctx_writer_agent.py` | YES (positional tuples) | YES (`conn.executemany`) | NO (P-2) | NO (hand-rolled key checks) | YES | YES (but `.inc()` crash — P-3) |
| `bar_writer_agent.py` | YES (positional tuples, 10-param) | YES (`conn.executemany`) | YES | YES (BarMessage) | NO (base only; own histogram — P-9) | YES |
| `swarm_ledger_writer_agent.py` | YES (positional in `conn.execute`) | NO (per-signal — low vol) | NO (P-4) | NO (hand-rolled field extraction) | NO (P-4) | N/A (no `_parse_payload`, custom run) |
| `graduation_writer_agent.py` | YES (via repository) | YES (`execute_batch`) | YES | NO (manual key check) | PARTIAL (no validation counter — P-11) | YES |
| `signal_metrics_writer_agent.py` | YES (positional) | NO (per-row in loop — P-7) | YES (ad-hoc `.dlq` suffix) | YES (`payload_model = SignalMetricsEvent`) | NO (base only) | YES |
| `bar_writer_agent.py` *(duplicate row for completeness)* | | | | | | |
| `feature_writer_agent.py` *(duplicate row for completeness)* | | | | | | |

**Notes on 13 total writers:**
The `services/` directory contains 11 Python writer files. The DAG order lists `feature-writer`, `signal-writer`, `lifecycle-writer`, `lineage-writer`, `llm-writer`, `ctx-writer`, `bar-writer`, `swarm-ledger-writer`, `graduation-writer`, `signal-metrics-writer`, and `contract-metadata-writer` = 11 service units. `feature-snapshot-writer` (`ml-training` batch service writes to `feature_snapshots`) is the 12th distinct persistence service but has no standalone writer agent file in `services/`. The 13th referenced in the audit scope appears to be `contract_metadata_writer_agent.py` (the reference implementation). Matrix above covers all 11 service files.

---

## Summary by Severity

| Severity | Count | Findings |
|---|---|---|
| CRITICAL | 1 | P-1 (`_pool` AttributeError in LLMWriter) |
| HIGH | 4 | P-2 (CtxWriter no DLQ), P-3 (`.inc()` crash), P-4 (SwarmLedger swallows errors), P-5 (FeatureWriter ghost-run mode) |
| MEDIUM | 4 | P-6 (SignalWriter DLQ contract), P-7 (SignalMetrics per-row), P-8 (LLMWriter latest offset), P-9 (BarWriter metric isolation) |
| LOW | 4 | P-10 (truncated label), P-11 (graduation counter), P-12 (lifecycle per-row exits), P-13 (migrations resolved) |

*Audit performed 2026-05-23 against git HEAD on branch `main` (pre-reboot state save).*
