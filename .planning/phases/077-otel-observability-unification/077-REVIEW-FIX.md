---
phase: 077-otel-observability-unification
fixed_at: 2026-04-29T07:02:45Z
review_path: .planning/phases/077-otel-observability-unification/077-REVIEW.md
iteration: 1
findings_in_scope: 9
fixed: 8
skipped: 1
status: partial
---

# Phase 077: Code Review Fix Report

**Fixed at:** 2026-04-29T07:02:45Z
**Source review:** .planning/phases/077-otel-observability-unification/077-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 9 (CR-01, CR-02, CR-03, WR-01 through WR-06)
- Fixed: 8
- Skipped: 1

## Fixed Issues

### CR-01: Trace Exporter Protocol Mismatch

**Files modified:** `src/observability/otel.py`
**Commit:** 8f17fac4
**Applied fix:** Changed `OTLPSpanExporter` import from `opentelemetry.exporter.otlp.proto.http.trace_exporter` to `opentelemetry.exporter.otlp.proto.grpc.trace_exporter`. Updated span exporter construction to use the bare `grpc_endpoint` (host:port) with `insecure=True` instead of the HTTP URL pattern, making traces and metrics use the same gRPC transport to port 4317.

---

### CR-02: `_OTelLabeledGauge.inc()` Does Not Accumulate

**Files modified:** `src/observability/metrics.py`
**Commit:** a1f383c3
**Applied fix:** Changed `inc()` from `self._last_value = amount` to `self._last_value += amount` so repeated calls accumulate correctly. The `_gauge.set()` call now receives the running total rather than the raw addend.

---

### CR-03: Hardcoded Langfuse Secrets in docker-compose.yml

**Files modified:** `production/docker-compose.yml`
**Commit:** 0bcad4d4
**Applied fix:** Replaced `NEXTAUTH_SECRET: dev-secret-replace-in-production` and `SALT: dev-salt-replace-in-production` with `${LANGFUSE_NEXTAUTH_SECRET}` and `${LANGFUSE_SALT}` environment variable substitutions. Values must be generated with `openssl rand -hex 32` and stored in `.env` (already gitignored).

---

### WR-01: `_send_alert()` Reads Wrong Attribute Name

**Files modified:** `src/core/agent/base.py`
**Commit:** 0e09e31f
**Applied fix:** Replaced `getattr(self, "_settings", None)` (which always returned None) with direct access to `self.settings.env_name` — the correct attribute name set in `BaseAgent.__init__`. Alerts now respect the `INDICAGENT_ENV` topic prefix.

---

### WR-02: otel-collector Missing loki Dependency

**Files modified:** `production/docker-compose.yml`
**Commit:** f3969d91
**Applied fix:** Added `- loki` to the `otel-collector` service's `depends_on` list so the Collector waits for Loki before starting, preventing log export failures at startup.

---

### WR-03: ProviderDataStoppage Alert Fires Outside Market Hours

**Files modified:** `production/alertmanager-rules.yml`
**Commit:** 821a8b30
**Applied fix:** Added `and (hour() >= 6 and hour() <= 21)` UTC time-of-day filter to the `ProviderDataStoppage` alert expression. Also increased `for:` duration from `30s` to `5m` to suppress transient false positives at session boundaries.

---

### WR-04: `setup_service_logging()` Called on Every `BaseAgent.__init__()`

**Files modified:** `src/core/agent/base.py`
**Commit:** 4a0d6768
**Applied fix:** Added a class-level `_log_configured_path` guard so `setup_service_logging()` is only called when the log path differs from the previously configured path. This prevents multiple agent instantiations (common in tests) from redirecting all logging to the most recently created agent's log file.

---

### WR-05: `_discover_services()` Drops Failed Units with Bullet Prefix

**Files modified:** `services/service_auditor_agent.py`
**Commit:** 01ad9990
**Applied fix:** Added `lstrip("●").strip()` to strip the unicode bullet character systemctl prepends to failed unit lines before parsing the unit name. If the stripped token is empty, falls back to `parts[1]`. Empty unit strings are guarded before appending.

---

## Skipped Issues

### WR-06: `mlflow` Container Has No `restart: unless-stopped` Policy

**File:** `production/docker-compose.yml:160-173`
**Reason:** Code context differs from review — `restart: unless-stopped` is already present in the file at line 174. Inspection of `git show 803e057d:production/docker-compose.yml` confirms the directive was already present in the commit the reviewer examined. No change needed.
**Original issue:** mlflow service missing restart policy, Docker default `no` means crashes or reboots leave MLflow down until manually restarted.

---

_Fixed: 2026-04-29T07:02:45Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
