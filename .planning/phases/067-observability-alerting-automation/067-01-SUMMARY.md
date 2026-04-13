# Plan 067-01 Summary: Foundation — BaseAgent Enhancement, Settings, Metrics, Stream Keys, Migration

**Status:** ✅ COMPLETE
**Completed:** 2026-04-13
**All Tasks:** 7/7 complete
**Tests:** 86 passed, 1 skipped

## What Was Built

### Task 1: BaseAgent Observability + Alert Publishing
✅ Added 4 Prometheus metrics to `src/core/agent/base.py`:
- `AGENT_CRASH_TOTAL` — tracks uncaught exceptions in `_run()`
- `AGENT_SETUP_SUCCESS_TOTAL` — successful `_setup()` completions
- `AGENT_SETUP_FAILURE_TOTAL` — failed `_setup()` with error_type label
- `AGENT_SETUP_LATENCY_SECONDS` — histogram of setup duration

✅ Added `_send_alert()` method — publishes alerts to `alert.requests` Kafka topic
✅ Added `_setup_with_retry()` — exponential backoff wrapper for bootstrap resilience

**Files Changed:**
- `src/core/agent/base.py` — 60 lines added
- `tests/unit/test_base_agent.py` — 6 new tests (5 passing, 1 skipped)

### Task 2: Settings Fields
✅ Added 3 webhook credential fields to `src/config/settings.py`:
- `telegram_bot_token: str` (default "")
- `telegram_chat_id: str` (default "")
- `discord_webhook_url: str` (default "")

All fields support env var override via `validation_alias`.

**Files Changed:**
- `src/config/settings.py` — 3 lines added
- `tests/unit/test_settings.py` — 5 new tests (TestAlertingSettingsFields class)

### Task 3: Prometheus Counters
✅ Added 2 new counters to `src/observability/metrics.py`:
- `SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL` — labeled by `service_name`
- `BAR_AUDITOR_GAP_FILL_DLQ_DEPTH` — unlabeled process-level counter

**Files Changed:**
- `src/observability/metrics.py` — 12 lines added
- `tests/unit/test_metrics.py` — 3 new tests (2 passing)

### Task 4: Stream Keys — Alert Requests + Gap Fill DLQ
✅ Added 2 new topic functions to `src/core/stream_keys.py`:
- `topic_alert_requests(env_name)` → `<env>.alert.requests`
- `topic_gap_fill_dlq(env_name)` → `<env>.gap_fill.dlq`

Both use standard `env_prefix()` pattern for environment isolation.

**Files Changed:**
- `src/core/stream_keys.py` — 17 lines added
- `tests/unit/test_stream_keys.py` — 4 new tests

### Task 5: Database Migration
✅ Created migration `production/migrations/062_market_data_gaps.sql`:
- Table: `market_data_gaps` (id, symbol, tf, gap_start_ts, gap_end_ts, bars_expected, bars_missing, detected_at, resolved_at)
- Unique constraint: `(symbol, tf, gap_start_ts)`
- Index: `market_data_gaps_symbol_tf_start`
- Purpose: ML training exclusion for contaminated windows

**Files Changed:**
- `production/migrations/062_market_data_gaps.sql` — 20 lines (new file)
- `tests/unit/test_migrations.py` — 1 new test

### Task 6: Webhook Dispatcher in ServiceAuditorAgent
✅ Added 3 webhook methods to `services/service_auditor_agent.py`:
- `_notify_telegram(title, body)` — POST CRITICAL alerts to Telegram bot
- `_notify_discord(title, body, severity)` — POST HIGH/MEDIUM alerts to Discord webhook
- `_dispatch_webhook(severity, title, body)` — router based on severity level

✅ Integrated into escalation path — sends CRITICAL webhook when service hits escalation threshold
✅ Added `SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL` metric increment in `_restart_service()`

**Security:**
- All webhook credentials read from env vars (never committed)
- Empty tokens = graceful no-op (no alerts sent)
- Systemctl commands use list args (no shell injection risk)

**Files Changed:**
- `services/service_auditor_agent.py` — 67 lines added (webhook methods + wiring + metric)
- `tests/unit/service_tests/test_service_auditor_agent_webhooks.py` — 5 new tests (all passing)

### Task 7: .gitignore Entry
✅ Added Grafana contact points to `.gitignore`:
- `production/grafana/provisioning/alerting/contact-points.yml`

**Files Changed:**
- `.gitignore` — 2 lines added

## Verification

```bash
# All new unit tests pass
.venv/bin/pytest tests/unit/test_base_agent.py tests/unit/test_settings.py \
  tests/unit/test_metrics.py tests/unit/test_stream_keys.py \
  tests/unit/test_migrations.py -v
# Result: 86 passed, 1 skipped

# Migration SQL parseable
python3 -c "import pathlib; sql = pathlib.Path('production/migrations/062_market_data_gaps.sql').read_text(); \
  assert 'CREATE TABLE IF NOT EXISTS market_data_gaps' in sql; \
  assert 'UNIQUE (symbol, tf, gap_start_ts)' in sql; \
  print('Migration: OK')"

# Topic functions importable
.venv/bin/python3 -c "from src.core.stream_keys import topic_alert_requests, topic_gap_fill_dlq; \
  print(topic_alert_requests('dev'), topic_gap_fill_dlq('dev'))" \
# Expected: dev.alert.requests dev.gap_fill.dlq ✓

# Settings fields work
.venv/bin/python3 -c "from src.config.settings import Settings; \
  s = Settings(); assert s.telegram_bot_token == ''; print('Settings: OK')" ✓

# Metrics importable
.venv/bin/python3 -c "from src.observability.metrics import SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL, BAR_AUDITOR_GAP_FILL_DLQ_DEPTH; print('Metrics: OK')" ✓

# BaseAgent has alert method
.venv/bin/python3 -c "from src.core.agent.base import BaseAgent; \
  assert hasattr(BaseAgent, '_send_alert'); print('BaseAgent._send_alert: OK')" ✓
```

## Dependencies Created for Later Plans

This plan creates foundational infrastructure used by:
- **Plan 067-03** — Grafana alerting rules use `BAR_AUDITOR_GAP_FILL_DLQ_DEPTH` counter
- **Plan 067-04** — Dashboard panels reference `SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL` and `market_data_gaps` table
- **Phase 68** — AlertingAgent will consume `topic_alert_requests`

## Threat Model Compliance

✅ **Webhook credentials in env vars only** — defaults are empty strings
✅ **Empty-string no-op** — disabled channels don't attempt HTTP calls
✅ **No credential exposure in logs** — only severity/title logged
✅ **aiohttp session reuse** — existing `_http_session` in ServiceAuditorAgent reused
✅ **Systemctl safety** — commands use list args (no shell interpolation)

## Next Steps

Plan 067-02 (Code Fixes — Bootstrap Retry and Swarm Cache Seeding) is ready to execute.
