# Phase 067 Plan 03: Grafana Alerting + Roll Automation + Bar Auditor DLQ Summary

**Phase:** 067 — Observability, Alerting & Automation
**Plan:** 3 of 4
**Wave:** 2
**Started:** 2026-04-13T18:33:32Z
**Completed:** 2026-04-13T18:33:50Z
**Duration:** 18 seconds

---

## Goal

Three gaps closed in one plan because they share a dependency chain: Plan 1's webhook dispatcher enables the roll automation alert, the DLQ counter enables the Grafana HIGH rule, and the migration enables the market_data_gaps write path. After this plan, a futures roll fires an automatic `ibkr-provider` restart, every detected gap is persisted for ML exclusion, and exhausted gap-fill retries land in a DLQ rather than silently disappearing.

---

## One-Liner

Grafana alerting infrastructure (contact points + 10 Prometheus rules), automatic futures roll handling via roll event consumer with sudo-controlled ibkr-provider restart, and BarAuditorAgent market_data_gaps persistence layer with DLQ routing for exhausted retries.

---

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Grafana Contact Points — Example + Production | 58cb0b12 | production/grafana/provisioning/alerting/contact-points.example.yml, tests/unit/test_grafana_provisioning.py |
| 2 | Grafana Alert Rules YAML | c70f082b | production/grafana/provisioning/alerting/alert-rules.yml, tests/unit/test_grafana_provisioning.py |
| 3 | Roll Event Consumer in ServiceAuditorAgent | bc96f3e5 | services/service_auditor_agent.py, tests/unit/service_tests/test_service_auditor_roll_consumer.py |
| 4 | BarAuditorAgent — market_data_gaps Write Path + DLQ Routing | ab5e442d | services/bar_auditor_agent.py, tests/unit/service_tests/test_bar_auditor_gaps.py |

---

## Deviations from Plan

### Auto-fixed Issues

None. Plan executed exactly as written.

### Auth Gates

None encountered.

---

## Threat Surface Scan

No new threat surfaces introduced beyond those documented in the plan's threat model:
- Subprocess injection mitigated via fixed command list in `_restart_ibkr_provider`
- Sudoers scope is minimal (one command, one service)
- Dedup prevents double restart within process lifetime
- DLQ payload contains no credentials
- Contact-points.yml is gitignored (example file committed)

---

## Files Changed

### Created
- `production/grafana/provisioning/alerting/contact-points.example.yml` — Grafana contact points template with placeholder values
- `production/grafana/provisioning/alerting/alert-rules.yml` — 10 alert rules across CRITICAL/HIGH/MEDIUM severity groups
- `tests/unit/test_grafana_provisioning.py` — YAML smoke tests for Grafana provisioning files
- `tests/unit/service_tests/test_service_auditor_roll_consumer.py` — 4 tests for roll consumer functionality
- `tests/unit/service_tests/test_bar_auditor_gaps.py` — 5 tests for market_data_gaps write path

### Modified
- `services/service_auditor_agent.py` — Added roll event consumer, `_handle_roll_event`, `_restart_ibkr_provider`, dedup set
- `services/bar_auditor_agent.py` — Added `_upsert_market_data_gap`, `_resolve_market_data_gap`, `_publish_gap_fill_dlq`, gap write path wired into `_detect_gaps`

---

## Key Decisions

1. **Contact-points.yml gitignored** — Real credentials live only in local file, example file committed with placeholders
2. **Roll automation only fires on roll_complete** — roll_imminent and roll_detected events are ignored; only actual contract transition triggers restart
3. **In-memory dedup for roll events** — `_handled_rolls: set[tuple[str, str]]` keyed by (symbol, new_expiry) prevents double restart from Kafka at-least-once redelivery; acceptable tradeoff since dedup clears on process restart
4. **Subprocess.run for systemctl restart** — Blocking call acceptable for infrequent operation (at most once per futures roll cycle, ~4x/year per contract)
5. **market_data_gaps UPSERT is idempotent** — ON CONFLICT (symbol, tf, gap_start_ts) DO UPDATE ensures safe repeated calls
6. **Gap resolution on completeness >= 1.0** — Marks open gaps as resolved when data reaches 100% completion
7. **DLQ payload structure** — {symbol, tf, start_ts, end_ts, retry_count, error} contains no PII or secrets

---

## Known Stubs

None. All functionality is fully implemented and wired.

---

## Verification

### Tests
```bash
# All plan 3 tests pass (11/11)
.venv/bin/pytest \
  tests/unit/test_grafana_provisioning.py \
  tests/unit/service_tests/test_service_auditor_roll_consumer.py \
  tests/unit/service_tests/test_bar_auditor_gaps.py \
  -v

# Full unit suite still clean
.venv/bin/pytest tests/unit/ -v --tb=short
```

### Manual Setup Required
The sudoers entry for roll automation MUST be added manually by the operator before the feature is functional:
```
# Add to /etc/sudoers.d/indicagent-roll:
bg ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart indicagent-ibkr-provider

# Verify with:
sudo -l | grep indicagent-ibkr-provider
```

### Verification Commands
```bash
# Alert rules YAML parses (10 rules defined)
python3 -c "
import yaml, pathlib
d = yaml.safe_load(pathlib.Path('production/grafana/provisioning/alerting/alert-rules.yml').read_text())
rules = [r['title'] for g in d['groups'] for r in g['rules']]
assert len(rules) == 10
print('OK — 10 rules defined')
"

# bar_auditor_agent DLQ code present
python3 -c "
import pathlib
src = pathlib.Path('services/bar_auditor_agent.py').read_text()
assert 'topic_gap_fill_dlq' in src
assert '_upsert_market_data_gap' in src
assert '_resolve_market_data_gap' in src
print('bar_auditor_agent: OK')
"

# service_auditor_agent roll consumer present
python3 -c "
src = open('services/service_auditor_agent.py').read()
assert '_handle_roll_event' in src
assert '_restart_ibkr_provider' in src
assert 'service_auditor_roll_consumer' in src
print('service_auditor_agent: OK')
"
```

---

## Performance Impact

- **Roll consumer loop** — Minimal impact; only processes roll events (~4x/year per contract)
- **market_data_gaps UPSERTs** — One additional DB write per detected gap per audit cycle (5 min intervals)
- **DLQ publishing** — Only on retry exhaustion (rare event)
- **Grafana alert evaluation** — Performed by Prometheus, not in Python agents

---

## Next Steps

1. **Manual sudoers setup** — Add `/etc/sudoers.d/indicagent-roll` entry for ibkr-provider restart
2. **Grafana provisioning** — Copy `contact-points.example.yml` to `contact-points.yml` and add real credentials
3. **Plan 067-04** — Next plan in phase (if applicable)

---

## Self-Check: PASSED

- [x] All 4 tasks committed individually
- [x] All 11 tests passing
- [x] YAML files parse correctly
- [x] DLQ topics wired in both agents
- [x] No security issues introduced
- [x] Documentation complete (manual sudoers step noted)
