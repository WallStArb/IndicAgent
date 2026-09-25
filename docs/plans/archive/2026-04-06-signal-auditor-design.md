# Signal Auditor & CIS Contract Enforcement Design

**Date:** 2026-04-06  
**Status:** Approved — pending implementation plan  
**Phase:** v2.2  

---

## Problem

The signals domain is missing the AuditorAgent that every other domain has:

```
Bars:    bar_aggregator → bar_writer → bar_auditor  ✓ self-healing DAG
Signals: intelligence_pipeline → signal_writer → ???  ✗ gap
```

`production/scripts/data_quality_check.py` is a cron script that patched this hole. It:
- Queries ALL-TIME signal_ledger with no time window — conflates pre-CIS era nulls with real violations
- Exits with code 1 on threshold breach — systemd marks service "failed", no self-healing
- Duplicates what bar_auditor already does for OHLCV completeness

Concurrently, `signal_ledger` has 649K rows with `cis_score IS NULL` because:
1. ~649K rows pre-date Phase 35 (CIS never existed for them) — pre-production dev data
2. ~61K recent rows (Apr 1–3) have null CIS for 55+ symbols — live pipeline bug (stale Kafka messages from before Phase 57 deployment consumed by signal_writer)

Renaissance violation: a metric that always fires is noise, not signal. The system can write a signal without CIS — that is structurally wrong, not just monitorable.

---

## Design

Four layers, each with single responsibility:

### Layer 1: Data Cleanup (one-time)

`TRUNCATE signal_ledger CASCADE` — clean pre-production slate.

Rationale: all 661K rows are pre-production dev data. The 649K null-CIS rows are worthless as training data (pre-CIS era, wrong ranking algorithm). The 12,918 non-null rows span only 3 symbols (HGK6/SIK6/USO) over 3 days — not a meaningful training dataset. A clean epoch start from today is worth more than 5 days of mixed-quality history.

Renaissance principle: *clean data from a known-good epoch beats more data with unknown provenance.*

**Steps:**
1. `TRUNCATE signal_ledger CASCADE` (handles child partition tables)
2. Restart `indicagent-signal-tracker` (clears stale in-memory open position state)
3. Reset `signal_writer_group` Kafka consumer offset on `intelligence.i7.signals` to latest — prevents signal_writer from replaying pre-Phase-57 messages that lack CIS fields

---

### Layer 2: Source Assertion + DLQ (prevention)

In `intelligence_pipeline_agent._run_i7_pipeline()`, before `_enqueue()`:

- Assert every signal in `ranked` has `raw_cis_score IS NOT None` and `filtered_cis_score IS NOT None`
- On assertion failure: publish to `intelligence.signal.dlq` topic with structured payload:
  ```json
  {
    "symbol": "CLK6",
    "tf": "1m",
    "bar_ts": "...",
    "reason": "cis_score_null",
    "signal_count": 3,
    "ts": "..."
  }
  ```
- Do NOT publish the bad signal to `intelligence.i7.signals` — drop it at source
- Increment `signal_pipeline_dlq_total` counter (existing metric pattern)

This is the existing DLQ pattern from CLAUDE.md applied to the signal publish path. Fail fast at source with full context. Never let a null-CIS signal enter the Kafka pipeline.

**Note:** The CISScorer already handles missing features via `_fval(key, default=0.0)` — all bucket inputs default to 0.0 when absent, so `cis_score` is always numerically computable. A null-CIS signal means the stamping code at lines 1299–1302 was bypassed — the assertion will catch any future regression of this kind.

---

### Layer 3: DB Contract (enforcement)

Migration applied after cleanup + pipeline fix are verified:

```sql
-- Migration: 057_signal_ledger_cis_not_null.sql
ALTER TABLE signal_ledger
  ALTER COLUMN cis_score            SET NOT NULL,
  ALTER COLUMN raw_cis_score        SET NOT NULL,
  ALTER COLUMN filtered_cis_score   SET NOT NULL,
  ALTER COLUMN bucket_scores        SET NOT NULL,
  ALTER COLUMN weights_version      SET NOT NULL;
```

Hard backstop: if Layer 2 fails due to any future regression, the DB write fails loudly. `signal_writer_agent` DLQ catches it. `signal_writer_write_errors_total` spikes → Prometheus alert fires. No silent corruption.

CIS is bar-level (one score per bar, stamped on all signals in that bar). All signal types — regime_suppressed, pending, shadow — go through the same CIS compute path. Constraint applies universally.

---

### Layer 4: `signal_auditor_agent.py` — complete the DAG

New agent following `bar_auditor_agent.py` pattern exactly.

**Identity:**
| Layer | Value |
|-------|-------|
| File | `services/signal_auditor_agent.py` |
| Class | `SignalAuditorAgent` |
| Unit | `indicagent-signal-auditor.service` |
| Port | `:9126` |
| Role | `AuditorAgent` — DB-aware, read-only on signal_ledger |

**Cadence:** 5-minute audit loop during market hours (same as bar_auditor). Skips audit outside RTH + 30 min buffer.

**What it checks (per audit cycle):**

1. **Signal coverage per `(symbol, tf)`**  
   For each active symbol × `["1m", "5m", "15m", "1h"]`: did at least one signal fire in the last completed session?  
   Metric: `signal_coverage_pct{symbol, tf}` (gauge, 0.0–1.0)  
   On gap: emit `SignalCoverageGapEvent` to `intelligence.signal.audit` topic

2. **Pipeline lag P50/P95**  
   Query `pipeline_lag_ms` from signal_ledger for last 1h window per `(symbol, tf)`.  
   Metric: `signal_pipeline_lag_p50_ms{symbol, tf}`, `signal_pipeline_lag_p95_ms{symbol, tf}`  
   Threshold: P95 > 500ms → WARNING log (not CRIT — lag is operational, not data integrity)

3. **CIS score distribution**  
   Mean and stddev of `cis_score` per `tf` over rolling 5-session window.  
   Metric: `signal_cis_mean{tf}`, `signal_cis_stddev{tf}`  
   Purpose: sudden shift in distribution signals a pipeline regression (e.g., a bucket always returning 0.0 due to a feature going missing upstream). Not threshold-alerting in v1 — just instrumented for Grafana.

**Golden Signals (per CLAUDE.md pattern):**
- Traffic: `signal_auditor_audits_run_total`, `signal_auditor_coverage_gaps_published_total`
- Latency: `signal_auditor_audit_duration_seconds` (histogram)
- Errors: `signal_auditor_audit_errors_total`
- Saturation: `signal_coverage_pct{symbol, tf}` (gauge)

**Self-healing path (v1 scope):**  
Emit `SignalCoverageGapEvent` to `intelligence.signal.audit` topic. The intelligence pipeline does not yet subscribe to this topic — that's v2 of this feature. In v1, the event is emitted and observable. A future phase can close the loop (pipeline replays bars for covered symbols on gap event).

**Does NOT do:**
- Write to signal_ledger or any DB table
- Check null rates (enforced by DB constraint — redundant)
- OHLCV completeness (bar_auditor owns this)
- IC health (deferred to v2.3 Renaissance observability)

---

### What Retires

| Artifact | Action |
|----------|--------|
| `production/scripts/data_quality_check.py` | Archive to `production/scripts/archive/` |
| `indicagent-data-quality.service` | Disable + remove systemd unit |
| `indicagent-data-quality.timer` | Disable + remove systemd unit |
| `src/observability/data_quality_metrics.py` | Delete `DQ_NULL_CIS_RATE`, `DQ_NULL_CONFIDENCE_RATE` metrics; keep staleness/lag/IC metrics if reused by signal_auditor |
| `tests/unit/intelligence/monitoring/test_data_quality_monitor.py` | Archive if only tests null-rate logic |

---

## Final DAG

```
intelligence_pipeline_agent
  │  [assert cis_score non-null before publish]
  │  [on failure → intelligence.signal.dlq]
  ▼
intelligence.i7.signals (Kafka)
  │
  ├──▶ signal_writer_agent ──▶ signal_ledger (NOT NULL constraint enforced)
  │
  └──▶ [future: signal_auditor subscribes here for lag measurement]

signal_auditor_agent
  │  [reads signal_ledger every 5 min]
  │  [emits coverage gap events]
  ▼
intelligence.signal.audit (Kafka)
```

Symmetric with bars:
```
bar_aggregator → bar_writer → bar_auditor → market.events.gap_requests → ibkr_provider (fills gap)
intelligence_pipeline → signal_writer → signal_auditor → intelligence.signal.audit → (future: replay)
```

---

## Sequencing

1. TRUNCATE + reset Kafka offset + restart signal_tracker
2. Add assertion + DLQ publish in intelligence_pipeline_agent
3. Verify all symbols generating non-null CIS in logs (1 trading session)
4. Apply DB migration (NOT NULL constraints)
5. Build signal_auditor_agent (new service + systemd unit)
6. Archive data_quality_check.py + disable timer
7. Verify Grafana shows signal_coverage_pct metrics

---

## Renaissance Alignment

| Principle | How this design satisfies it |
|-----------|------------------------------|
| Instrument everything | signal_coverage_pct per (symbol,tf) + CIS distribution continuously tracked |
| Never drop data that could contain signal | NOT NULL constraint prevents corrupt rows from ever entering the training dataset |
| Degrade gracefully, adapt automatically | CISScorer already degrades gracefully (defaults to 0.0 per missing feature). Assertion catches regressions. Future: auditor closes self-healing loop |
| No manual tasks | No scripts, no human intervention. Violations surface in Prometheus and Kafka DLQ |
| Microservices DAG | Completes the compute → write → audit pattern for the signals domain |
| Separation of concerns | Pipeline computes. Writer persists. Auditor validates. Each one job. |
