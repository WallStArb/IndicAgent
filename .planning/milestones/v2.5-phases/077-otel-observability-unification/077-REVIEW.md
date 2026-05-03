---
phase: 077-otel-observability-unification
reviewed: 2026-04-28T00:00:00Z
depth: standard
files_reviewed: 20
files_reviewed_list:
  - production/otel-collector-config.yaml
  - production/grafana/provisioning/datasources/datasource-loki.yml
  - production/docker-compose.yml
  - production/tempo.yaml
  - production/prometheus.yml
  - tests/unit/test_otel_metrics_wrappers.py
  - requirements.txt
  - src/observability/otel.py
  - src/observability/metrics.py
  - src/core/agent/base.py
  - tests/unit/test_base_agent.py
  - src/observability/log_bridge.py
  - services/service_auditor_agent.py
  - tests/unit/service_tests/test_service_auditor_agent.py
  - tests/conftest.py
  - production/alertmanager-rules.yml
  - production/alertmanager.yml
  - services/intelligence_pipeline_agent.py
  - src/core/agent/base_writer.py
  - src/providers/base_provider_agent.py
findings:
  critical: 3
  warning: 6
  info: 4
  total: 13
status: issues_found
---

# Phase 077: Code Review Report

**Reviewed:** 2026-04-28T00:00:00Z
**Depth:** standard
**Files Reviewed:** 20
**Status:** issues_found

## Summary

This phase adds OTel Collector integration (metrics push via OTLP gRPC, trace export to Tempo, log forwarding to Loki), migrates BaseAgent metrics instrumentation from prometheus_client HTTP scrape to OTel push wrappers (`OTelCounter`/`OTelGauge`/`OTelHistogram`), and delivers the `ServiceAuditorAgent` for graduated pipeline self-healing. The core design is sound and the graceful-degradation pattern is correct. The critical findings are: a protocol mismatch in `otel.py` (trace exporter imports the HTTP variant but constructs a gRPC URL), a semantic bug in `_OTelLabeledGauge.inc()` that silently discards the addend, and hardcoded Langfuse secrets in `docker-compose.yml`. Several warnings relate to missing defensive guards, a wrong attribute name in `_send_alert`, and an incomplete `otel-collector` startup dependency.

---

## Critical Issues

### CR-01: Trace Exporter Protocol Mismatch — HTTP Importer Used with gRPC URL

**File:** `src/observability/otel.py:7,57`
**Issue:** `OTLPSpanExporter` is imported from `opentelemetry.exporter.otlp.proto.http.trace_exporter` (the HTTP/protobuf exporter), but the constructed endpoint on line 57 is `http://{grpc_endpoint}/v1/traces` — a URL pattern the HTTP exporter expects. Meanwhile the `grpc_endpoint` variable was stripped of its `http://` scheme prefix on line 27, so this actually works for HTTP. The bug is the inconsistency: the metric exporter (`OTLPMetricExporter`) is imported from `...proto.grpc...` and receives a bare `host:port` gRPC endpoint (correct), while the trace exporter is imported from `...proto.http...` and receives a URL with an `http://` prefix re-added (also technically correct, but the two transports differ silently). If a caller passes an `https://` endpoint the trace exporter will use TLS while the metric exporter's gRPC will not, leading to asymmetric behavior with no error. More directly: the OTel Collector is configured with a gRPC receiver on port 4317; the HTTP receiver is on port 4318. The default endpoint `http://localhost:4317` will succeed for the HTTP trace exporter only if the Collector's HTTP receiver also happens to listen on 4317, which it does not — it listens on 4318. In the default configuration, traces are being sent to the wrong port.

**Fix:** Either use the gRPC trace exporter consistently with the other exporters, or explicitly use port 4318 for the HTTP trace exporter. The gRPC-consistent approach:

```python
# Change import at line 7:
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

# Change span exporter construction (lines 56-58):
exporter = OTLPSpanExporter(
    endpoint=grpc_endpoint,
    insecure=True,
)
```

---

### CR-02: `_OTelLabeledGauge.inc()` Does Not Accumulate — Sets to Amount, Not Current+Amount

**File:** `src/observability/metrics.py:539-542`
**Issue:** `_OTelLabeledGauge.inc()` sets the gauge to the raw `amount` parameter (default `1.0`) rather than adding it to the current value. This breaks any caller that relies on gauge increment semantics (e.g., `gauge.inc()` repeatedly to count up). The implementation:

```python
def inc(self, amount: float = 1.0) -> None:
    # Gauge.inc() pattern -- set to amount (OTel gauge does not support increment)
    self._last_value = amount
    self._gauge.set(amount, self._labels)
```

The comment says "OTel gauge does not support increment" but the correct approach is to track state locally and set to `self._last_value + amount`. The OTel SDK gauge `set()` call would still be used — just with the accumulated value. Any code calling `inc()` on a labeled gauge will see it permanently stuck at `1.0` (or whatever the first call's amount was).

`DLQ_DEPTH` is a `Gauge` (prometheus_client, not OTelGauge) so the specific `DLQ_DEPTH.labels(...).inc()` calls in `base.py` lines 372/383 are not affected by this. However, `SERVICE_UP_GAUGE` in `service_auditor_agent.py` is an `OTelGauge` — if any caller uses `.inc()` on it, the value is wrong.

**Fix:**
```python
def inc(self, amount: float = 1.0) -> None:
    self._last_value += amount
    self._gauge.set(self._last_value, self._labels)
```

---

### CR-03: Hardcoded Secrets in `docker-compose.yml` (Langfuse)

**File:** `production/docker-compose.yml:183-184`
**Issue:** `NEXTAUTH_SECRET` and `SALT` are hardcoded as `dev-secret-replace-in-production` and `dev-salt-replace-in-production`. These are cryptographic secrets used by Langfuse for session signing and password hashing. If this `docker-compose.yml` is deployed to a server (which it is — the file lives in `production/`), the secrets are trivially known to anyone who reads the repo. An attacker who can reach the Langfuse port (3010) can forge sessions.

**Fix:** Use environment variable substitution so actual secret values are never committed:
```yaml
environment:
  DATABASE_URL: postgresql://postgres:postgres@timescaledb:5432/langfuse
  NEXTAUTH_URL: http://localhost:3010
  NEXTAUTH_SECRET: ${LANGFUSE_NEXTAUTH_SECRET}
  SALT: ${LANGFUSE_SALT}
```
Generate values with `openssl rand -hex 32` and store them in a `.env` file that is gitignored.

---

## Warnings

### WR-01: `_send_alert()` in `base.py` Reads `self._settings` — Attribute That Does Not Exist

**File:** `src/core/agent/base.py:438-439`
**Issue:** `_send_alert()` retrieves the env prefix via `getattr(self, "_settings", None)` — but `BaseAgent.__init__` stores the settings object under `self.settings` (no leading underscore), not `self._settings`. The `getattr` call always returns `None`, so `env_name` is always `""` and alerts are always published to the no-prefix topic. This is a silent bug: no error is raised, but in an environment where `INDICAGENT_ENV` is set (e.g., `"dev"`), alerts go to `alert.requests` instead of `dev.alert.requests`.

**Fix:**
```python
# Line 438 — use the correct attribute name:
env_name = self.settings.env_name or ""
await self._producer.publish(topic_alert_requests(env_name), payload)
```

---

### WR-02: `otel-collector` in `docker-compose.yml` Does Not Depend on `loki`

**File:** `production/docker-compose.yml:134-135`
**Issue:** The `otel-collector` service has `depends_on: [prometheus, tempo]` but not `loki`. The OTel Collector's log pipeline is configured to export to `http://loki:3100/loki/api/v1/push`. If Loki starts after the Collector, the Collector's log exporter will fail on its initial connection attempt. While the Collector retries, there is a startup window where logs are silently dropped.

**Fix:**
```yaml
otel-collector:
  depends_on:
    - prometheus
    - tempo
    - loki
```

---

### WR-03: `ProviderDataStoppage` Alert Rule Fires Outside Market Hours

**File:** `production/alertmanager-rules.yml:4-10`
**Issue:** The `ProviderDataStoppage` alert expression is:
```
rate(provider_bars_produced_total[5m]) == 0 and indicagent_service_up{unit="indicagent-ibkr-provider"} == 1
```
This fires whenever the bar rate drops to zero while the service is up — including overnight, on weekends, and on market holidays. The `ServiceAuditorAgent` correctly gates data-stoppage detection on `_any_active_session_open()`, but the Prometheus alert rule has no equivalent guard. The result is false-positive alerts every night/weekend. The IBKR futures market is 23 hours/day Mon–Fri, so this fires every Friday night and every weekend.

**Fix:** Either add a time-of-day filter using a recording rule that captures session-open windows, or accept that this alert is informational only and set `severity: info` with a longer `for:` duration (e.g., `for: 30m`) to filter out brief overnight quiet periods. A simple time-based approach:
```yaml
expr: >
  rate(provider_bars_produced_total[5m]) == 0
  and indicagent_service_up{unit="indicagent-ibkr-provider"} == 1
  and (hour() >= 6 and hour() <= 21)
```
(Adjust hours to match RTH + ETH combined schedule.)

---

### WR-04: `setup_service_logging()` Called on Every `BaseAgent.__init__()` — Overwrites Prior Configuration

**File:** `src/core/agent/base.py:99-101`
**Issue:** `BaseAgent.__init__()` unconditionally calls `setup_service_logging(log_path)` on every instantiation. In a process that instantiates multiple agents (or re-instantiates after a test), the logging configuration is overwritten each time. If `IntelligencePipelineAgent` already called `setup_service_logging("logs/intelligence_pipeline_agent.log")` before `super().__init__()`, the `BaseAgent.__init__()` will call `setup_service_logging("logs/intelligence_pipeline_agent.log")` again (same path, redundant but harmless). However, if a test constructs two different agents in sequence, the second agent's `setup_service_logging()` call redirects all logging to the second agent's log file, corrupting log output for the first agent. This is particularly problematic in `test_base_agent.py` where multiple `MinimalAgent` and `OrderAgent` instances are created in sequence within one process.

**Fix:** Guard the call so it only executes if the log path has not already been configured:
```python
# Only configure if not already done for this path
if not getattr(BaseAgent, "_log_configured_path", None) == log_path:
    setup_service_logging(log_path)
    BaseAgent._log_configured_path = log_path
```
Or alternatively check if a structlog processor is already writing to a file before reconfiguring.

---

### WR-05: `_discover_services()` Does Not Strip `.service` from Units That Include `@` or Template Suffixes

**File:** `services/service_auditor_agent.py:261-264`
**Issue:** `removesuffix(".service")` only removes the suffix if the string ends in `.service`. Systemd template unit instances (e.g., `indicagent-foo@1.service`) will not be stripped and will appear as `indicagent-foo@1.service` in the sorted list. They will not match any `_DAG_ORDER` key and will be sorted to position 99. While no template units are currently deployed, this is a latent robustness bug. More immediately: `systemctl list-units --all --no-legend --no-pager indicagent-*` can return lines with the `●` unicode bullet (failed units) prepended, making `parts[0]` the bullet character and `parts[1]` the actual unit name. Unit names parsed from such lines will not match `_DAG_ORDER` keys, silently skipping failed units from the sorted list.

**Fix:**
```python
for line in stdout.decode().strip().splitlines():
    parts = line.split()
    if not parts:
        continue
    # Strip leading bullet character (● for failed units)
    unit_raw = parts[0].lstrip("●").strip()
    if not unit_raw:
        unit_raw = parts[1] if len(parts) > 1 else ""
    unit = unit_raw.removesuffix(".service")
    if unit:
        units.append(unit)
```

---

### WR-06: `mlflow` Container Has No `restart: unless-stopped` Policy

**File:** `production/docker-compose.yml:160-173`
**Issue:** All other containers in `docker-compose.yml` have `restart: unless-stopped`. The `mlflow` service definition omits the `restart:` directive entirely. Docker's default restart policy is `no`, meaning a crash or server reboot will leave MLflow down until manually restarted. This is inconsistent with the documented behavior: "Docker containers on reboot: timescaledb and redpanda both have `restart: unless-stopped` — no manual start needed."

**Fix:**
```yaml
mlflow:
  image: ghcr.io/mlflow/mlflow:latest
  restart: unless-stopped   # add this line
  ...
```

---

## Info

### IN-01: `OTelHistogram` Silently Ignores `buckets` Parameter

**File:** `src/observability/metrics.py:596-603`
**Issue:** `OTelHistogram.__init__()` accepts a `buckets` parameter but never passes it to `self._meter.create_histogram()`. The OTel SDK's `create_histogram` does not expose bucket configuration in the same way as prometheus_client — histogram views are configured on the `MeterProvider`. The `buckets` parameter is accepted to maintain API compatibility with prometheus_client callers but has no effect. Callers with custom bucket configurations (e.g., `PERSISTENCE_BATCH_LATENCY` with fine-grained sub-second buckets) will get the OTel SDK default buckets instead. This is a documentation/behavioral gap that callers should be aware of.

**Fix:** Add a comment making this explicit, and/or add a `warnings.warn()` if a non-None `buckets` argument is passed:
```python
def __init__(self, name: str, documentation: str, labelnames: list[str] | None = None,
             buckets: list[float] | None = None):
    if buckets is not None:
        # OTel SDK bucket configuration requires MeterProvider Views — ignored here.
        # Configure bucket boundaries via OTel Collector view config if needed.
        pass
```

---

### IN-02: `requirements.txt` Has Duplicate `scipy` Entry

**File:** `requirements.txt:66-67`
**Issue:** `scipy` appears twice with different constraints:
```
scipy==1.17.1
scipy>=1.15.0
```
The pinned `==1.17.1` and the `>=1.15.0` floor constraint coexist. pip resolves this without error (picks `1.17.1`) but the redundancy is confusing and will cause issues if the version is ever bumped in only one place.

**Fix:** Remove the duplicate, keeping only the pinned version or the floor constraint depending on the project's versioning policy.

---

### IN-03: `tempo.yaml` Lacks `query_frontend` Config — Grafana Datasource Won't Work Without It

**File:** `production/tempo.yaml`
**Issue:** The Tempo config has no `query_frontend` block. Grafana's Tempo datasource queries Tempo's HTTP API on port `3200` (configured under `server.http_listen_port`). While this works for single-node deployments, the Grafana datasource in `production/grafana/provisioning/datasources/` is missing — only a Loki datasource is provisioned. There is no `datasource-tempo.yml` or `datasource-prometheus.yml` in the provisioning directory. Grafana will start without any configured datasources for Prometheus or Tempo, requiring manual setup.

**Fix:** Add provisioning files for Prometheus and Tempo:
```yaml
# production/grafana/provisioning/datasources/datasource-prometheus.yml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://indicagent-prometheus:9090
    isDefault: true

# production/grafana/provisioning/datasources/datasource-tempo.yml
apiVersion: 1
datasources:
  - name: Tempo
    type: tempo
    access: proxy
    url: http://indicagent-tempo:3200
```

---

### IN-04: `log_bridge.py` Attaches OTLP Handler Only at `WARNING` Level — DEBUG/INFO Logs Not Forwarded

**File:** `src/observability/log_bridge.py:52-53`
**Issue:** The `LoggingHandler` is configured with `handler.setLevel(logging.WARNING)`, meaning only `WARNING` and above log records are forwarded to Loki via OTLP. The structlog pipeline (used throughout all agents) outputs INFO-level records for normal operational events (e.g., `agent.starting`, `agent.setup_complete`, bar processing counters). These will not appear in Loki, making log correlation between traces (in Tempo) and logs (in Loki) incomplete — only error conditions will be visible in Loki.

This may be intentional to control log volume, but it is inconsistent with the stated purpose of "full log forwarding to OTel Collector." If the intent is to forward all operational logs, the level should be `logging.DEBUG` or `logging.INFO`.

**Fix:** If full forwarding is desired:
```python
handler.setLevel(logging.INFO)
```
If the WARNING-only behavior is intentional, document it explicitly in the docstring.

---

_Reviewed: 2026-04-28T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
