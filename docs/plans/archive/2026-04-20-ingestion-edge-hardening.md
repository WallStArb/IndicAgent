---
created: 2026-04-20
updated: 2026-04-21
status: complete
context: Commits A, 1, 2, 3 landed + deployed (10 commits pushed to origin/main 2026-04-21). Commit 4 deferred (not bottleneck). L4 deferred (cosmetic). Next work: todo 030 (Kafka → DB writers audit).
---

# Ingestion-Edge Hardening Plan

**Version:** 1.0
**Status:** archived
**Last Updated:** 2026-05-27
Resume work on hardening the TWS → `base_provider_agent` → `market.bars` pipeline. Audit findings are in the 2026-04-20 session log (scope 1: ingestion edge). Scopes 2 and 3 are separate audits (see todos 030, 031).

## Current state

### Commit A — landed 2026-04-20 (`757c9da0`)

Bundled the earlier-session ad-hoc work with this-session's producer-durability fix into a single baseline commit:

- **`services/service_auditor_agent.py`** — data-stoppage counter-persistence bug fix + market-hours gate via `_any_active_session_open()`. Imports `get_active_contracts` + `SESSION_REGISTRY`. All 43 auditor tests pass.
- **`src/core/kafka_utils.py`** — `AIOKafkaProducer` now configured with `acks='all'`, `enable_idempotence=True`, `compression_type='lz4'`, `max_in_flight_requests_per_connection=5`. **Redpanda idempotence confirmed enabled** via `rpk cluster config get enable_idempotence → true`.
- **`src/providers/base_provider_agent.py`** — `_health_check_loop` added invoking `adapter.ping()` every 30s (interim; superseded by Commit 3).
- **`src/providers/ibkr.py`** — `ping()` method wrapping `reqCurrentTimeAsync` as active liveness probe.
- `_archived_*` services + test stubs deleted.
- `CLAUDE.md` — server IP correction.
- Filed `.planning/todos/pending/030-audit-kafka-to-db-writers-pipeline.md`, `031-audit-data-quality-loop.md`.

**Pre-existing ruff errors** (not introduced this session, discovered during staging):
- `services/service_auditor_agent.py:645, 677` — E501 line length
- `src/core/kafka_utils.py:204, 207` — E501 line length
- `src/providers/ibkr.py:276` — UP041 `asyncio.TimeoutError` alias (will be fixed by Commit 1/H4)

None block Commit A; fix during Commit 1 or as a separate cleanup.

### Deployment note

Commit A has NOT been deployed. Before `sudo systemctl restart indicagent-ibkr-provider`:
- Baseline `bars_per_sec` via `curl -s localhost:9129/metrics | grep provider_bars_produced_total`.
- Tail `logs/ibkr_provider_agent.log` for the first 10 minutes post-restart.
- `_health_check_loop` will be replaced by Commit 3. If you deploy Commit A first, expect two concurrent reconnect mechanisms (agent-side ping + adapter-side `_connection_watchdog`) — functional but redundant. Deploying all four commits together avoids this transient.

## Remaining work

### Commit 1 — landed 2026-04-21 (`7f193f2d`) ✅

H4 (narrow `ping()` except), L5 (split `PROVIDER_RECONNECTS_TOTAL` → `_ATTEMPTED` + `_SUCCEEDED`), M6 (extract `_normalize_ib_bar_ts`). 4 files, tests green.

### Commit 2 — landed 2026-04-21 (`26a57946`) ✅

M3 (dedup simplify: `_last_emitted_ts` dict), M4 (drop counters on 3 callbacks), M5 (bar_queue bounded at 10k with `_enqueue_bar` helper), M8 (gap-fetch pacing via `asyncio.Semaphore(1)` + 0.2s sleep), L1 (warning→error), L2 (tick callback try/except), L3 (rtb_queue uses `_tick_queue_size`). New metric `provider_bars_dropped_total{provider, agent, reason}`. 5 files, 64 provider tests green.

**L4 deferred:** `provider_name` attribute vs `_provider_name_str()` method — 24 method call-sites vs 3 attribute refs. Cosmetic only, not worth the churn this pass.

### Commit 3 — landed 2026-04-21 (`501619db`) ✅

Reconnect consolidation. H1 deleted `BaseProviderAgent._health_check_loop` and folded active-ping into adapter's `_bar_flow_watchdog` (5-min soft threshold → ping; fail → enqueue `_RECONNECT`; 20-min hard threshold unchanged). M1 added jittered backoff (base ≤30s, delay ≤45s). M2 resets `attempt=0` on every successful bar.

Post-landing fixes (discovered during deploy):
- `95b4304b` — dropped invalid `max_in_flight_requests_per_connection` kwarg (aiokafka rejects; idempotence internally caps ≤5).
- `ea5c2666` — replaced briefly-added `lz4` dep with `cramjam` (aiokafka's actual LZ4 backend via `has_lz4()` → `cramjam is not None`).
- `2decaaff` — docstring accuracy fix (CodeRabbit: jitter max ~45s, not 30s).

**Deployed:** all continuous services restarted cleanly; bars flowing; 26 services active. Failed oneshot timers (`ml-data-quality`, `ml-discovery`) have a pre-existing `producer.start()` bug unrelated to this work.

### Commit 4 — Kafka fire-and-batch — **DEFERRED**

**Renaissance rationale for deferral:** current bar rate is ~55 bars/min (futures + ETFs + FX + crypto). `send_and_wait` per-publish is not the bottleneck at this scale — measured end-to-end bar→Kafka latency is <10ms. Switching to fire-and-batch:
- Adds a `flush()` contract on shutdown (graceful-stop testing burden).
- Requires per-caller audit for durability semantics (some callers, e.g. `signal_writer` finalizing a ledger row, assume "publish returns → broker has acked").
- Saves milliseconds on a path that isn't tight.

Simons test: *don't optimize what you can't measure as the bottleneck*. Revisit when either (a) ingestion scales past ~1k bars/sec, or (b) backfill throughput becomes the critical path — at that point the `KafkaProducerClient.publish_batch(bars)` API (explicit batch, explicit flush) is cleaner than flipping a global default.

**Files if resumed:** `src/core/kafka_utils.py`, callers of `KafkaProducerClient.publish`

- **H2/M7** — `kafka_utils.py:111` change `send_and_wait` → `send` + add `flush()` in `stop()`.
- Tuning: `linger_ms=5, batch_size=16384`.
- **Caller audit required** — grep `KafkaProducerClient` and `producer.publish`. Any caller needing durability-after-return calls `await producer.flush()` explicitly, or we add a `publish_sync()` method.
- Run full test suite.

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
