---
phase: 067
slug: observability-alerting-automation
status: verified
threats_open: 0
asvs_level: 1
created: 2026-04-14
---

# Phase 067 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| BarAuditorAgent → IBKR | Gap fill requests trigger IBKR API calls | Market data requests (low sensitivity) |
| Provisioning script → Redpanda | DLQ topic creation | Error payloads (internal, no PII) |
| ServiceAuditorAgent → systemctl | Service restart commands via sudo | System control commands (one service, one command) |
| ServiceAuditorAgent → Webhook | Alert notifications to external endpoints | Severity/title only, no credentials in payload |
| LLMWriterService → Kafka | DLQ publishing to Kafka topic | Error payloads (internal) |
| LLMWriterService → TimescaleDB | Score writing via existing patterns | Metric data (low sensitivity) |
| Grafana → Prometheus | Dashboard/alert queries | Operational metrics only |
| Internal metric emission | Prometheus gauge updates in async methods | Numeric counters (no sensitive data) |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-067-08-01 | Denial of Service | alert-rules.yml | accept | Metric name typo causes alert to never fire — fix already resolves it | closed |
| T-067-09-01 | Denial of Service | bar_auditor_agent.py | mitigate | Dedup via `_requested_today` set prevents duplicate gap requests to IBKR (confirmed: `services/bar_auditor_agent.py:117`) | closed |
| T-067-09-02 | Information Disclosure | provision_dlq_topics.sh | mitigate | All 17 DLQ topics provisioned including 6 previously-missing: roll, service_auditor, signal, swarm, ml, gap_fill (confirmed: `production/scripts/provision_dlq_topics.sh`) | closed |
| T-067-10-01 | Repudiation | cross_asset_service.py | accept | Purely cosmetic rename, no security impact | closed |
| T-067-11-01 | Denial of Service | stall watchdog | accept | Watchdog only logs warnings, does not kill the service — by design | closed |
| T-067-12-01 | Denial of Service | _report_consumer_lag | accept | Metric emission is lightweight, no external calls | closed |
| T-067-13-01 | Information Disclosure | dashboard panels | accept | Only shows operational metrics, no sensitive data | closed |

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-067-01 | T-067-08-01 | Alert rule typo already existed; this phase's fix resolves it rather than introducing new risk | Claude (gsd-security-auditor) | 2026-04-14 |
| AR-067-02 | T-067-10-01 | Internal rename with no external trust boundary or security impact | Claude (gsd-security-auditor) | 2026-04-14 |
| AR-067-03 | T-067-11-01 | Stall watchdog is log-only by design; killing the service would be more disruptive than the stall itself | Claude (gsd-security-auditor) | 2026-04-14 |
| AR-067-04 | T-067-12-01 | Consumer lag reporting is a lightweight gauge update with no network calls beyond existing Kafka consumer | Claude (gsd-security-auditor) | 2026-04-14 |
| AR-067-05 | T-067-13-01 | Grafana dashboards display only operational metrics (lag, error counts, health scores) — no PII or credential data | Claude (gsd-security-auditor) | 2026-04-14 |

---

## Additional Mitigations (Plan 067-01, 067-03)

These plans had security-relevant mitigations without formal threat models:

- **Webhook credentials in env vars only** — defaults are empty strings; no credential exposure in logs
- **Empty-string no-op** — disabled alert channels don't attempt HTTP calls
- **Systemctl safety** — restart commands use list args (no shell interpolation); sudoers scope is one command, one service
- **Subprocess injection** — `_restart_ibkr_provider` uses async `asyncio.create_subprocess_exec` with fixed command list (WR-02 fix)
- **DLQ payload** — contains no credentials

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-04-14 | 7 | 7 | 0 | Claude (gsd-security-auditor) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-04-14
