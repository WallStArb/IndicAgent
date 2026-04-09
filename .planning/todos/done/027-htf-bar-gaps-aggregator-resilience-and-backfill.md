---
id: "027"
title: HTF bar gaps — aggregator crash resilience + startup backfill
priority: high
created: 2026-04-04
---

# HTF Bar Gap — Root Cause & Fix Plan

**Discovered:** 2026-04-04 during canonical bar audit

## Root Cause

Redpanda blipped for ~10s at 14:00:23 on 2026-04-02. Bar aggregator crashed
(KafkaConnectionError on bootstrap), restarted, crashed again immediately in
`_setup()` before `setup_service_logging()`. Hit StartLimitBurst (5 failures
in 300s), systemd stopped restarting. Result: ~38% of HTF bars missing for
the rest of that day despite 1m bars being 99.9% complete.

## Evidence

- `journalctl -u indicagent-bar-aggregator-compute` shows crash at 14:00:23,
  one restart at 14:00:33, then silence
- `logs/bar_aggregator_agent.log` never created (crashed before setup_service_logging)
- BTCUSD Apr 2: 1439 1m bars, only 177/288 5m, 59/96 15m, 16/24 1h, 4/6 4h
- All HTF bars stop at 13:00-14:00 ET — exactly the crash time

## Two Fixes Required

### Fix 1: Kafka bootstrap retry in `_setup()` (prevents the cascading crash)

In `bar_aggregator_agent.py` or `src/core/kafka_utils.py`: retry Kafka
producer/consumer bootstrap with exponential backoff (e.g. 5 attempts, 2-16s)
instead of raising immediately. A 10s Redpanda hiccup should not kill the service.

Same fix likely needed across all agents that call `_kafka_producer.start()` in `_setup()` —
check `bar_writer_agent.py`, `bar_auditor_agent.py`, `signal_writer_agent.py`, etc.

### Fix 2: HTF backfill on restart (fills gaps retroactively)

At startup, query `market_data_ohlcv` for 1m bars from the last N hours
(e.g. last 4h to cover realistic downtime), replay them through BarAccumulator,
write any HTF bars that are missing. Unique constraint on `(timestamp, symbol, timeframe)`
makes retry-safe — just attempt insert, ignore conflicts.

## Key Files

- `services/bar_aggregator_agent.py` — `_setup()` method
- `src/core/bar_accumulator.py` — BarAccumulator (stateful, replay-compatible)
- `src/core/kafka_utils.py` — KafkaProducerClient/KafkaConsumerClient start()
- `src/persistence/repository/` — DB writes for HTF bars
