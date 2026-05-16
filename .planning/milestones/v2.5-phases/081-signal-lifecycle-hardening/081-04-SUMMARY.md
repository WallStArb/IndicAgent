---
phase: "081"
plan: "04"
subsystem: bar-replay-provider
tags: [bar-replay, kafka, one-shot, ohlcv, metrics]
dependency_graph:
  requires: ["081-02 (TF_SECONDS in stream_keys)", "081-03 (lifecycle tracker refactor)"]
  provides: ["services/bar_replay_provider_agent.py", "production/systemd/indicagent-bar-replay.service"]
  affects: ["market.bars topic", "market.bars.htf topic", "indicagent-ibkr-provider", "indicagent-bar-aggregator"]
tech_stack:
  added: []
  patterns: ["one-shot L1 provider", "asyncpg pool", "checkpoint file", "ExecStopPost restart chain"]
key_files:
  created:
    - services/bar_replay_provider_agent.py
    - production/systemd/indicagent-bar-replay.service
  modified:
    - src/observability/metrics.py
decisions:
  - "INDICAGENT_ENV omitted from unit file — matches all other production units (unset = no env prefix)"
  - "Restart=no — one-shot service; ExecStopPost handles live-mode handoff on clean exit"
  - "Rate limited to 10 bars/s by default; tunable via BAR_REPLAY_BARS_PER_SEC env var"
  - "Batch size 1000 rows per DB fetch; checkpoint persisted after each batch"
metrics:
  duration: "~10 minutes"
  completed: "2026-05-08"
  tasks_completed: 3
  files_modified: 3
---

# Phase 81 Plan 04: BarReplayProviderAgent Summary

**One-liner:** One-shot L1 provider that replays `market_data_ohlcv` chronologically into `market.bars` / `market.bars.htf`, self-terminating when caught up, then hands off to live ingestion via `ExecStopPost`.

## What Was Built

### Task 1 — Bar replay metrics registered (`src/observability/metrics.py`)

Two new Prometheus metrics:
- `BAR_REPLAY_PROVIDER_BARS_PUBLISHED_TOTAL` — Counter with labels `(symbol, timeframe)`: tracks per-symbol/TF publish progress
- `BAR_REPLAY_PROVIDER_LAG_SECONDS` — Gauge (no labels): tracks seconds between `last_replayed_ts` and `NOW()`; drops to 0.0 on completion

Both use `prometheus_client.Counter` / `Gauge` directly (same pattern as adjacent Phase 81 metrics).

### Task 2 — `BarReplayProviderAgent` (`services/bar_replay_provider_agent.py`)

Key design decisions:

**DB query ordering** — `ORDER BY timestamp ASC, CASE timeframe ... END ASC` ensures same-timestamp bars publish smallest-TF first (1m=1, 5m=5, 15m=15, 1h=60, 4h=240, 1d=1440).

**Topic routing** — `tf == "1m"` → `topic_market_bars(env)` ; any other tf → `topic_market_bars_htf(env)`.

**Self-termination** — After each batch, checks `datetime.now(UTC) - last_replayed_ts <= timedelta(minutes=5)`. Returns 0 when caught up; systemd ExecStopPost then restarts live services.

**Checkpoint** — `cache/bar_replay_checkpoint.json` stores `{"last_replayed_ts": "<isoformat>"}`. Loaded at startup to resume interrupted runs. Saved after each 1000-bar batch and in the `finally` block.

**Rate limiting** — `BAR_REPLAY_BARS_PER_SEC` env var (default 10/s) throttles publish loop via `asyncio.sleep(1/rate)`. Prevents overwhelming the intelligence pipeline during replay.

**Signal handling** — SIGINT/SIGTERM set `_stop` asyncio.Event; inner loop checks it between bars for clean shutdown.

### Task 3 — systemd unit (`production/systemd/indicagent-bar-replay.service`)

- `Type=simple`, `Restart=no` — one-shot; systemd does not auto-restart
- `ExecStopPost=/bin/systemctl start indicagent-ibkr-provider.service` — restores live data feed after replay completes
- `ExecStopPost=/bin/systemctl start indicagent-bar-aggregator.service` — restores HTF bar aggregation
- No `WatchdogSec` / `NotifyAccess` — agent does not implement `sd_notify`
- `INDICAGENT_ENV` omitted — matches all production units (unset = empty env prefix)

## Service Interface

```
Class:    BarReplayProviderAgent
agent_id: bar_replay_provider   # Prometheus label
Module:   services.bar_replay_provider_agent

Entry:    asyncio.run(BarReplayProviderAgent().main())
          → setup_service_logging("logs/bar_replay_provider_agent.log")
          → asyncpg pool + KafkaProducerClient
          → _run() loop until caught-up or SIGTERM
          → returns int exit code (0 = clean completion)
```

## Checkpoint File Format

```json
{"last_replayed_ts": "2026-04-01T09:30:00+00:00"}
```

Path: `cache/bar_replay_checkpoint.json` (relative to `WorkingDirectory`).
Delete this file to replay from the beginning of `market_data_ohlcv`.

## Deployment Steps

```bash
# 1. Stop live ingestion before replay (avoids duplicate bars in pipeline)
sudo systemctl stop indicagent-ibkr-provider indicagent-bar-aggregator

# 2. Install unit file
sudo cp production/systemd/indicagent-bar-replay.service /etc/systemd/system/
sudo systemctl daemon-reload

# 3. Optional: delete checkpoint to replay from scratch
rm -f cache/bar_replay_checkpoint.json

# 4. Optional: adjust replay speed
# Edit unit file: Environment=BAR_REPLAY_BARS_PER_SEC=50

# 5. Start replay
sudo systemctl start indicagent-bar-replay

# 6. Monitor progress
journalctl -u indicagent-bar-replay -f
# Or watch Grafana: bar_replay_provider_lag_seconds (drops to 0 on completion)

# 7. On clean exit, ExecStopPost automatically starts:
#    indicagent-ibkr-provider + indicagent-bar-aggregator
```

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

Files created:
- `services/bar_replay_provider_agent.py` — FOUND
- `production/systemd/indicagent-bar-replay.service` — FOUND

Commits:
- `7d22b46a` feat(081-04): register bar_replay_provider metrics
- `01acaaa4` feat(081-04): create BarReplayProviderAgent
- `40d2c324` chore(081-04): add systemd unit indicagent-bar-replay.service

## Self-Check: PASSED
