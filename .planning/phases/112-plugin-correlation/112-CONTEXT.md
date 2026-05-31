# Phase 112: Plugin Correlation Analysis & Automated Pruning — Context

**Gathered:** 2026-05-31
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-05-31-plugin-correlation-analysis.md)

<domain>
## Phase Boundary

Measure effective statistical independence across 132 I7 plugins, identify redundant pairs via directional correlation, auto-suppress redundant plugins in shadow_registry, and emit production metrics for effective plugin count. This is a weekly batch job (oneshot timer) plus schema additions and minimal plumbing changes to the pipeline and aggregator. No changes to plugin logic, shadow_registry promotion/demotion rules, or the AI inference stack.

</domain>

<decisions>
## Implementation Decisions

### Batch Job
- D-01: Batch script lives at `production/scripts/plugin_correlation_batch.py`. Follows `roll_batch.py` pattern exactly — oneshot, idempotent, emits D-06 job_completed_total on exit.
- D-02: Trigger: systemd timer, weekly Monday, alongside `ml-discovery`. Unit file in `production/systemd/`.
- D-03: Direction matrix built from `signal_ledger` last 90 days. Group by `(feature_ts, symbol, timeframe)`. Direction: +1 (long), -1 (short), 0 (no fire).
- D-04: Minimum gate for pairs: `co_fire_count >= 30`. Pairs below this threshold not written to DB.
- D-05: Pairwise directional_r = agree_count / co_fire_count where agree_count = bars where both fired AND direction matched.
- D-06: Canonical ordering enforced in code and DB: plugin_a < plugin_b always (prevents duplicate pairs).
- D-07: effective_n via participation ratio on correlation matrix eigenvalues: `1 / Σ(λ_i / Σλ)²`.

### Auto-Suppression Logic
- D-08: All three conditions required for suppression: (1) directional_r >= 0.80, (2) co_fire_count >= 100, (3) inferior plugin has strictly lower bootstrap_ci_lower(pnl_r) from setup_performance.
- D-09: Suppression is reversible and self-expiring. When suppressed, co_fire_count stops accumulating. After ~13 weeks pair drops below co_fire_count >= 30 gate → batch auto-clears correlation_suppressed. No manual re-activation needed. Data starvation IS the expiry mechanism.
- D-10: `correlation_suppressed` column owned exclusively by correlation batch. Performance logic (shadow_registry promotion/demotion) never touches it.

### Schema
- D-11: `plugin_correlation_pairs` table — plugin_a, plugin_b, directional_r, co_fire_count, computed_at. PRIMARY KEY (plugin_a, plugin_b) for UPSERT. CHECK (plugin_a < plugin_b).
- D-12: `plugin_correlation_summary` table — computed_at (PK), effective_n, redundant_pairs. History kept (1 row per weekly run, ~52/year).
- D-13: `shadow_registry` migration: ADD COLUMN correlation_suppressed boolean NOT NULL DEFAULT false.
- D-14: `shadow_registry_active` VIEW: WHERE promoted = true AND NOT correlation_suppressed. All consumers use this view, never base table directly.

### Pipeline Integration
- D-15: `intelligence_pipeline` loads shadow_registry_active at startup (same pattern as existing shadow_registry load). Suppressed plugins excluded from execution set before any `_compute()` call. Inference is not free — do not run models to produce output that will be discarded.
- D-16: `aggregator` queries shadow_registry_active instead of shadow_registry directly.

### Observability
- D-17: `effective_plugin_count` point gauge, label `scope='global'`. Emitted at batch completion and via Prometheus scrape of API (reads latest plugin_correlation_summary row). Alert: < 6 → warning.
- D-18: `plugin_correlation_redundant_pairs_total` point gauge. `plugin_correlation_suppressed_total` point gauge. Alert: > 5 → warning.
- D-19: `job_completed_total{job="plugin-correlation-batch", status}` — D-06 oneshot contract. Label `job` MUST match systemd unit `%n` suffix exactly.

### Claude's Discretion
- Migration file naming and number (follow existing migration conventions).
- Whether to use numpy/scipy for eigenvalue computation or manual implementation.
- Error handling strategy for insufficient data (< 30 bars) at first run.
- Database query optimization approach for the 90-day signal_ledger scan.
- API endpoint path for serving effective_plugin_count metric (existing /metrics OTel endpoint or new endpoint).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Pattern References
- `production/scripts/roll_batch.py` — exact structural pattern to follow for the batch script (oneshot, idempotent, D-06 exit emit)
- `services/shadow_auditor.py` — shadow_registry query patterns, bootstrap_ci_lower usage
- `src/core/stream_keys.py` — topic key construction (not needed for batch but needed for any Kafka output)
- `src/observability/metrics.py` — OTel SDK metrics creation (point_gauge, create_gauge)

### Schema References
- `docs/plans/2026-05-31-plugin-correlation-analysis.md` — full data model DDL (plugin_correlation_pairs, plugin_correlation_summary, migration)
- Existing migration files in `production/migrations/` — naming convention and format

### Config / Settings
- `src/config/settings.py` — Settings class, get_active_contracts() pattern
- `src/core/database_manager.py` — asyncpg connection pooling pattern

### OTel Contract
- CLAUDE.md `## OTel Health Contract` — D-06 oneshot contract (job_completed_total)

### Intelligence Pipeline Integration
- `src/intelligence/intelligence_pipeline.py` — where shadow_registry load happens at startup
- `services/aggregator.py` — where shadow_registry query happens

</canonical_refs>

<specifics>
## Specific Ideas

- The spec calls out: run `EXPLAIN ANALYZE` post-implementation on the 90-day signal_ledger query to confirm TimescaleDB index `idx_signal_ledger_symbol_tf` is used.
- The spec explicitly notes suppression is NOT shadow mode — shadow mode = plugin runs with is_shadow=true; suppressed = plugin does not run at all.
- The view `shadow_registry_active` should be designed so future suppression types (e.g. regime_suppressed) only extend the VIEW definition, not the consumers. The view is the single interface.
- `plugin_correlation_pairs` uses UPSERT (ON CONFLICT DO UPDATE) — latest snapshot only. `plugin_correlation_summary` uses plain INSERT — full history.

</specifics>

<deferred>
## Deferred Ideas

- Per-symbol or per-timeframe correlation (YAGNI — global is sufficient for pruning decisions per spec)
- Runtime concentration discount in the aggregator (auto-suppression handles concentration; Prometheus alert handles visibility)
- I1–I6 feature-level correlation (I7 signal direction is the right level)

</deferred>

---

*Phase: 112-plugin-correlation*
*Context gathered: 2026-05-31 via PRD Express Path*
