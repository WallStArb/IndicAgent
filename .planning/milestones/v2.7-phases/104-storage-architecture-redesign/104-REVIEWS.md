---
phase: 104
reviewers: [gemini, codex]
reviewed_at: 2026-05-22T16:30:00Z
plans_reviewed: [104-01-PLAN.md, 104-02-PLAN.md, 104-03-PLAN.md, 104-04-PLAN.md]
---

# Cross-AI Plan Review — Phase 104


## Gemini Review

### Storage Architecture Redesign (Phase 104) Review

#### Summary
Phase 104 is a well-structured, tactical intervention that directly addresses the documented storage bloat through systematic migration and cleanup. The plan demonstrates a strong understanding of the "3-store" architectural requirement, prioritizing database hygiene and data lifecycle management. By separating configuration (Wave 1), destructive/schema operations (Wave 2 & 3), and materialization (Wave 4), the plan effectively minimizes operational risk and aligns with the project's existing DAG-based service patterns.

#### Strengths
*   **Logical Wave Separation**: Isolating configuration changes from schema migrations reduces the "blast radius" and complexity of individual deployments.
*   **Tactical "Concept Name" Mapping**: Retaining Python attribute names (`i1..i8`) while updating SQL columns is a pragmatic choice that balances long-term schema clarity with immediate code maintenance costs.
*   **Performance Optimization**: Moving from full shadow tables to a SQL freshness function and utilizing `LATERAL JOIN` for the dashboard API are significant wins for both storage efficiency and query performance.
*   **Automation Focus**: The introduction of nightly materialization and standardized retention policies ensures the 39 GB/week growth is eliminated permanently, not just temporarily.

#### Concerns
*   **Wave 2 Atomic Migration (HIGH)**: Stopping 7 services, applying migrations, and updating 30+ files in one window is high-risk. There is no explicit mention of a **rollback strategy** if the schema change causes an unexpected conflict or if application code expects the old column names during the migration transition.
*   **Kafka Consumer Group Orphans (MEDIUM)**: Applying `retention.bytes` caps on active topics may cause consumers to lag if they fail to process data faster than the retention pressure, potentially leading to data loss if consumers aren't tuned to handle the smaller retention window.
*   **Dashboard API Latency (MEDIUM)**: Replacing direct columns with `LATERAL jsonb_array_elements` in the dashboard API may introduce query performance overhead depending on the size of the JSONB fields.
*   **Service Auditing (LOW)**: Ensuring that the removal of `parity_auditor` doesn't leave "ghost" metrics in Prometheus/Grafana that trigger stale alerts.

#### Suggestions
*   **Rollback Strategy**: For Plan 104-03, implement a "Canary" or "Blue-Green" deployment pattern for the database migration if possible (e.g., creating the new columns/tables in parallel before dropping the old ones). If not feasible, ensure a complete snapshot/backup is taken immediately before the migration.
*   **Validation Step**: Add a mandatory validation check in the maintenance window (e.g., `SELECT count(*)...` across old and new structures) before fully restarting the dependent services.
*   **Kafka Monitoring**: Before applying retention caps, monitor current consumer group lag. If lag exists, prioritize optimizing those consumers before imposing the byte limit.
*   **Dashboard Testing**: Include a pre-deployment step to run explain plans on the new `LATERAL JOIN` queries to ensure they meet the response time requirements for the dashboard.
*   **Metrics Cleanup**: Add a specific task in Wave 2 to audit and remove any deprecated labels or metrics from `src/observability/metrics.py` to prevent alert noise.

#### Risk Assessment: MEDIUM
*Justification*: While the plan is robust, the atomic maintenance window (Plan 03) is a potential failure point. If the migration fails, the platform faces significant downtime. The risk is mitigated by the clear wave structure and the project's existing expertise in DAG/service management, but the lack of a documented rollback/recovery mechanism for the SQL migration increases the severity.

---

## Codex Review

## Summary

Phase 104 is directionally strong: it addresses the actual storage violations rather than treating disk growth as an ops cleanup problem. The 3-store split is coherent: canonical event/features store, slim lifecycle ledger, and typed ML training store. The main weakness is operational safety. Wave 1 is low risk, but Wave 2 combines column renames, destructive ledger slimming, service shutdowns, dashboard query rewrites, and multi-service callsite changes into one maintenance window. That is the right conceptual boundary, but the plan needs sharper rollback, compatibility, preflight validation, and post-migration smoke tests before it is production-safe.

---

## Plan 104-01: Storage Audit Doc + Retention Policies + Kafka Byte Caps

### Strengths

- Pure configuration/data-lifecycle work with no schema changes, so it is correctly placed in Wave 1.
- Directly addresses unbounded growth from hypertables and Kafka topics.
- Retention choices are domain-specific rather than one-size-fits-all.
- Storage audit doc is valuable as the canonical rationale for later destructive changes.

### Concerns

- **HIGH**: Kafka `retention.bytes=500MB` may truncate topics faster than consumers can process during outages or backfills. This can silently break replay assumptions.
- **HIGH**: Retention policies on hypertables can delete data needed by downstream ML, audits, dashboards, or compliance unless access requirements are explicitly checked.
- **MEDIUM**: Existing Timescale policies may already exist on some tables. Migration should be idempotent or guarded.
- **MEDIUM**: `add_retention_policy()` can fail if a policy already exists; plan should specify `if_not_exists => true` if supported by the installed TimescaleDB version, or use catalog checks.
- **MEDIUM**: No mention of compression policy interaction. Retention and compression ordering should be verified.
- **LOW**: Storage audit estimates should include current table sizes, index sizes, chunk counts, and topic sizes, not only table names.

### Suggestions

- Add a preflight query that inventories existing retention/compression policies from `timescaledb_information.jobs`.
- Confirm all 6 Kafka topics are replay-tolerant before applying byte caps.
- Use both `retention.ms` and `retention.bytes` intentionally, or document why byte-only retention is acceptable.
- Add a rollback command list for Kafka configs and Timescale policies.
- Add post-change validation:
  - `SELECT * FROM timescaledb_information.jobs WHERE proc_name = 'policy_retention';`
  - `kafka-configs --describe` for all capped topics.
- Consider topic-specific byte caps instead of uniform 500 MB if message volume differs materially.

### Risk Assessment

**MEDIUM**. The database side is manageable if migrations are idempotent. Kafka byte caps are the bigger risk because they can destroy replay buffers and orphan slow consumers without obvious immediate failure.

---

## Plan 104-02: Drop `feature_snapshots_shadow` + Retire Parity Services

### Strengths

- Correctly removes the largest direct duplicate store.
- Replaces byte-for-byte parity with a cheaper freshness check, which matches the storage redesign goal.
- Properly includes service DAG cleanup, systemd cleanup, code deletion, and metric removal.
- Independent from Plan 104-01, so Wave 1 parallelism is reasonable.

### Concerns

- **HIGH**: Dropping `feature_snapshots_shadow` immediately removes rollback/debug evidence. A backup/export step is needed before destructive deletion.
- **HIGH**: A freshness check is not equivalent to parity validation. It detects stalled pipelines, not corrupted or incomplete field writes.
- **MEDIUM**: Removing parity metrics may break dashboards, alerts, or Prometheus scrape expectations.
- **MEDIUM**: Deleting systemd unit files without first verifying units are inactive can leave stale processes running.
- **MEDIUM**: Consumer groups for retired services may remain in Kafka and create misleading lag alerts.
- **LOW**: `feature_parity_violations` may contain useful incident history; retention/archive decision should be explicit.

### Suggestions

- Rename/archive before drop:
  - stop writers
  - verify no writes for N minutes
  - snapshot table size/count/checksum
  - optionally `pg_dump` schema/data or retain compressed backup for short period
  - drop only after validation
- Define what `check_feature_pipeline_freshness()` validates:
  - newest event age per instrument
  - expected tier presence
  - minimum event count over lookback
  - optional null-rate checks for critical columns
- Keep parity metrics as deprecated zero/absent-compatible gauges for one deploy if dashboards depend on them.
- Delete or document retired Kafka consumer groups:
  - `indicagent-feature-snapshot-writer`
  - `indicagent-parity-auditor`
- Add a service auditor smoke test proving the freshness function failure path alerts correctly.

### Risk Assessment

**MEDIUM**. The storage win is real, but parity removal reduces observability unless the replacement freshness check includes quality checks, not only recency.

---

## Plan 104-03: Rename `intelligence_features` Columns + Slim `signal_ledger`

### Strengths

- Correctly identifies this as the atomic maintenance-window step.
- Keeps Python attributes `i1..i8` unchanged, which reduces code churn and migration risk.
- Separates canonical feature storage from lifecycle/outcome ledger responsibilities.
- Updating dashboard API to rehydrate fire-time fields via `intelligence_features.trading_signals` aligns with the single-source-of-truth design.

### Concerns

- **HIGH**: This is the riskiest plan. It combines renames, destructive column drops, 30+ code updates, dashboard query changes, and service restarts.
- **HIGH**: No rollback strategy is described. `DROP COLUMN` is difficult to reverse without a backup or shadow copy.
- **HIGH**: Backward compatibility for `/api/signals/active` is not guaranteed. The LATERAL join can change cardinality, omit rows, or duplicate active signals if JSON array matching is imprecise.
- **HIGH**: “Stop 7 services” needs an exact list, order, health criteria, and confirmation that no other writers exist.
- **HIGH**: Applying `DROP COLUMN` in the same window as callsite updates leaves no compatibility bridge. A failed deploy mid-window can strand services between old and new schemas.
- **MEDIUM**: Renaming SQL columns while keeping Python attributes unchanged requires careful ORM/SQLAlchemy mapping or query aliasing.
- **MEDIUM**: LATERAL `jsonb_array_elements` may be expensive on active dashboard paths unless filtered tightly and indexed around the parent row lookup.
- **MEDIUM**: Dropping duplicate ledger fields may break historical dashboards, exports, notebooks, or ad hoc queries outside the main codebase.
- **MEDIUM**: The migration numbering skips `091` if Plan 104-02 adds the freshness function there; numbering/order should be explicit.
- **LOW**: Column comments, views, grants, and dependent materialized views may not survive renames/drops cleanly.

### Suggestions

- Split into safer substeps even if executed in one window:
  1. Pre-deploy code that can read both old and new schemas where practical.
  2. Rename feature columns.
  3. Validate all writers/readers.
  4. Create compatibility view or aliases for dashboard/API if needed.
  5. Only then drop ledger columns.
- For `signal_ledger`, strongly consider a two-phase destructive migration:
  - Phase A: stop writing duplicate columns and update readers.
  - Phase B: after validation period, drop columns.
- Add explicit rollback:
  - full `pg_dump --schema-only` and targeted data backup of `signal_ledger` columns to be dropped
  - reverse rename SQL
  - service version rollback order
  - dashboard rollback path
- Define exact stopped services and order. Include all writers to `intelligence_features` and `signal_ledger`, plus API/dashboard if query shape changes.
- Add preflight dependency checks:
  - `pg_depend` for views/functions/materialized views
  - `rg` for old SQL column names
  - dashboard endpoint contract tests
- For `/api/signals/active`, require tests covering:
  - active signal with matching `signal_id`
  - multiple trading signals in one feature row
  - missing feature row
  - duplicate JSON matches
  - resolved signal excluded/included correctly
- Prefer joining JSON signals by stable `signal_id` or event ID, not timestamp/instrument heuristics.
- Run `EXPLAIN ANALYZE` for dashboard active signal query on production-like data.

### Risk Assessment

**HIGH**. The architecture is correct, but this plan needs stronger migration choreography. The destructive ledger drop and dashboard LATERAL rewrite are the main failure points.

---

## Plan 104-04: `ml_signal_training` Materialized Store + Nightly Automation

### Strengths

- Completes the 3-store architecture cleanly.
- Typed flat columns are appropriate for ML training and avoid repeated JSON extraction.
- Nightly materialization decouples analytical workloads from OLTP lifecycle writes.
- Compression and retention are included from the start.
- Service auditor registration is consistent with existing operational patterns.

### Concerns

- **HIGH**: “Handle outcome backfill as signals resolve” is underspecified. Outcomes may resolve after the nightly run, requiring idempotent updates.
- **HIGH**: The materializer must be idempotent. Re-running the same day should not duplicate training rows.
- **MEDIUM**: 02:00 UTC may run before all prior-day outcomes or late-arriving features are available.
- **MEDIUM**: JOIN + LATERAL JSON extraction could be heavy if run over broad ranges without tight predicates.
- **MEDIUM**: Schema evolution risk: typed ML columns need a versioning strategy when intelligence fields change.
- **MEDIUM**: Registering a nightly oneshot job in `_DAG_ORDER` may be semantically odd if `_DAG_ORDER` represents always-on services.
- **LOW**: Retention of 1 year may be too short for model training if regimes are long-cycle, especially rates/volatility/agriculture.

### Suggestions

- Define a unique key, likely `(signal_id)` or `(instrument, signal_ts, signal_type, horizon)`, and use `INSERT ... ON CONFLICT DO UPDATE`.
- Separate materialization into:
  - initial insert for prior-day fired signals
  - recurring outcome refresh for unresolved/recent signals
- Track materialization watermark and job status:
  - `materialized_for_date`
  - rows inserted
  - rows updated
  - unresolved outcomes
  - last success/failure
- Add a schema/version column such as `feature_schema_version` or `training_schema_version`.
- Consider materializing a rolling window, for example prior 7 days, to catch late arrivals.
- Benchmark the LATERAL query before scheduling and add indexes on join keys.
- Clarify whether this belongs in service auditor as a service, scheduled job, or both.

### Risk Assessment

**MEDIUM**. The design is sound, but correctness depends on idempotency, late outcome handling, and stable join keys.

---

## Cross-Plan Dependency And Ordering Review

### Strengths

- Wave sequencing is mostly correct:
  - Wave 1 removes immediate unbounded growth and duplicate storage.
  - Wave 2 changes canonical/lifecycle schemas.
  - Wave 3 builds the ML projection after schemas stabilize.
- Plan 104-04 depending on Plan 104-03 is appropriate because the training table should consume the final schema.

### Concerns

- **HIGH**: Wave 2 should not depend merely on “Wave 1 complete”; it should depend on Wave 1 validated.
- **HIGH**: Plan 104-03 should have an explicit maintenance runbook with go/no-go gates.
- **MEDIUM**: Kafka consumer group cleanup is missing across Plans 104-01 and 104-02.
- **MEDIUM**: External consumers of `IntelligenceEvent`, dashboard API, notebooks, and ML jobs need compatibility review.
- **MEDIUM**: No global success metric is defined for eliminating 39 GB/week growth.

### Suggestions

- Add phase-level acceptance criteria:
  - weekly disk growth reduced from 39 GB/week to target range
  - no unbounded Kafka topics remain
  - no duplicate feature snapshot writer running
  - `signal_ledger` reduced to lifecycle/outcome columns only
  - `ml_signal_training` populated for at least one full day
  - `/api/signals/active` contract tests pass
- Add a central migration checklist:
  - backup
  - preflight SQL dependency scan
  - service stop confirmation
  - migration execution
  - service restart order
  - health checks
  - dashboard smoke tests
  - rollback deadline
- Add consumer group cleanup/alert cleanup as explicit tasks.
- Add post-phase monitoring for 7 days: hypertable sizes, Kafka log dirs, Timescale job failures, dashboard latency, materializer success.

---

## Overall Risk Assessment

**Overall risk: HIGH**

The storage architecture is well-designed and should achieve the phase goals if implemented carefully. Plans 104-01, 104-02, and 104-04 are individually manageable. The high risk comes from Plan 104-03: destructive schema slimming, column renames, multi-service coordination, and dashboard query rewrites in one atomic window.

The biggest improvements would be:

- make Plan 104-03 reversible;
- delay destructive `DROP COLUMN` until readers are proven migrated;
- add exact service stop/start ordering;
- add dashboard backward-compatibility tests;
- clean up Kafka consumer groups and alerts;
- define measurable storage-growth acceptance criteria.

With those additions, the phase would move from high operational risk to medium risk while preserving the same architecture.

---

## Consensus Summary

### Agreed Strengths
- Well-structured dependency order (Wave 1 config-only, Wave 2 breaking schema, Wave 3 new store)
- Comprehensive retention policies address the root cause of unbounded growth
- SQL-only column renames (Python i1-i8 attributes unchanged) is smart — halves code churn
- 3-store architecture aligns with Renaissance principles: single source of truth, access pattern drives schema
- Nightly materialization (ml_signal_training) eliminates JSONB unnesting tax during ML training

### Agreed Concerns
- **HIGH**: Wave 2 maintenance window has no explicit rollback strategy if DDL fails mid-way
- **HIGH**: 7 services stopped atomically — what is the exact systemctl command sequence? Plan lists services but not the stop/start order
- **MEDIUM**: Dashboard API LATERAL JOIN performance — does jsonb_array_elements scale with 1M rows?
- **MEDIUM**: Orphaned Kafka consumer group offsets after feature_snapshot_writer retirement — Plan 02 deletes group but what if offsets lag?
- **MEDIUM**: ml_signal_training backfill when outcomes resolve — what is the UPDATE strategy for rows already inserted?

### Divergent Views
- **gemini**: Focuses on plan completeness; minimal concerns raised
- **codex**: Detailed operational concerns: systemctl restart coordination, Kafka consumer group lag, LATERAL JOIN query performance, row-level backfill strategy
