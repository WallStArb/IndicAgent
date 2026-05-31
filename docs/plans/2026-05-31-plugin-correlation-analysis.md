# Plugin Correlation Analysis & Automated Pruning

**Date:** 2026-05-31  
**Status:** Approved  
**Principle:** RC/Simons — measure everything, act systematically, no manual tasks

---

## Problem

132 plugins across I1–I7, but unknown effective independence. Two risks:

1. **Redundant signal pairs** — two I7 plugins with high directional agreement provide one independent bet, not two. Shadow_registry's performance gate won't catch this if both are individually profitable.
2. **Invisible concentration** — no visibility into how many truly independent signals the pipeline produces at any point in time.

Shadow_registry's existing demotion gate (`EV[R] < -0.05`) handles underperformers. It does not handle positively-performing-but-redundant plugins. This design closes that gap.

---

## Architecture

```
plugin_correlation_batch (weekly timer, Monday with ml-discovery)
  ├── reads signal_ledger (last 90 days)
  ├── builds direction matrix: (feature_ts, symbol, timeframe) × plugin → direction (+1/-1/0)
  ├── computes pairwise directional_r + co_fire_count
  ├── computes effective_n via participation ratio on correlation matrix eigenvalues
  ├── UPSERTs → plugin_correlation_pairs (latest snapshot)
  ├── INSERTs → plugin_correlation_summary (history kept, cheap)
  ├── sets correlation_suppressed=true in shadow_registry for qualifying pairs
  ├── emits effective_plugin_count Prometheus gauge
  └── emits job_completed_total{job="plugin-correlation-batch"} (D-06)

shadow_registry (existing table, new column)
  └── correlation_suppressed boolean NOT NULL DEFAULT false
      — owned exclusively by correlation batch; performance logic never touches it

shadow_registry_active (new VIEW)
  └── WHERE promoted = true AND NOT correlation_suppressed
      — single interface for all consumers; future suppression types extend the view, not the consumers

intelligence_pipeline (minimal change)
  └── checks shadow_registry_active before calling _compute() on each I7 plugin
      — suppressed plugins are skipped at inference, not just at aggregation
      — inference is not free; do not run models whose output will be discarded

aggregator (minimal change)
  └── queries shadow_registry_active instead of shadow_registry directly
```

---

## Batch Job

**Location:** `production/scripts/plugin_correlation_batch.py`  
**Trigger:** systemd timer, weekly Monday (alongside `ml-discovery`)  
**Pattern:** follows `roll_batch.py` exactly — oneshot, idempotent, emits D-06 on exit

### Direction Matrix

Query `signal_ledger` last 90 days. Group by `(feature_ts, symbol, timeframe)`. For each bar-group, build a vector over all I7 plugins:

```
direction[plugin] = +1 if fired long
                   -1 if fired short
                    0 if did not fire
```

90 days × ~60 active symbols × 6 timeframes × ~950 bars/day = O(10M) rows. TimescaleDB hypertable with `idx_signal_ledger_symbol_tf` handles this. Run `EXPLAIN ANALYZE` post-implementation to confirm.

### Pairwise Directional Agreement

For each plugin pair `(A, B)` where `A < B` (canonical ordering enforced in code — prevents duplicate pairs):

```
co_fire_count = bars where both A and B fired (direction != 0)
agree_count   = bars where both fired AND direction matched
directional_r = agree_count / co_fire_count
```

Minimum gate: `co_fire_count >= 30` before a pair is considered. Pairs below this threshold are not written to DB.

### Effective-N (Participation Ratio)

Build the plugin correlation matrix from `directional_r` values. Compute eigenvalues `λ_i`. Effective-N via participation ratio:

```
effective_n = 1 / Σ(λ_i / Σλ)²
```

Range: 1 (single dominant factor) to N (fully independent). Written to `plugin_correlation_summary`.

### Auto-Suppression

For each pair where all three conditions hold:

1. `directional_r >= 0.80`
2. `co_fire_count >= 100`
3. Superior plugin has strictly better `bootstrap_ci_lower(pnl_r)` (read from `setup_performance`)

Set `correlation_suppressed = true` on the inferior plugin in `shadow_registry`.

On each subsequent run: if a previously-suppressed pair drops below threshold (correlation decayed or data changed), clear `correlation_suppressed`. Fully automated — no human intervention.

**Demotion reason logged:** `correlation_suppressed` column implicitly captures this. Grafana can query `WHERE correlation_suppressed = true` for visibility.

---

## Data Model

### `plugin_correlation_pairs`

```sql
CREATE TABLE plugin_correlation_pairs (
    plugin_a      text        NOT NULL,
    plugin_b      text        NOT NULL,
    directional_r float       NOT NULL,
    co_fire_count int         NOT NULL,
    computed_at   timestamptz NOT NULL,
    PRIMARY KEY (plugin_a, plugin_b)   -- UPSERT, latest snapshot only
    CHECK (plugin_a < plugin_b)        -- enforce canonical ordering
);
```

### `plugin_correlation_summary`

```sql
CREATE TABLE plugin_correlation_summary (
    computed_at     timestamptz NOT NULL PRIMARY KEY,
    effective_n     float       NOT NULL,
    redundant_pairs int         NOT NULL   -- pairs above suppression threshold
);
```

History kept (1 row per weekly run, ~52 rows/year). Cheap. Enables effective-N trend analysis in Grafana.

### `shadow_registry` migration

```sql
ALTER TABLE shadow_registry
    ADD COLUMN correlation_suppressed boolean NOT NULL DEFAULT false;

CREATE VIEW shadow_registry_active AS
    SELECT *
    FROM shadow_registry
    WHERE promoted = true
      AND NOT correlation_suppressed;
```

All consumers query `shadow_registry_active`. Never the base table directly. Future suppression types (e.g. `regime_suppressed`) extend the view definition only.

---

## Observability

| Metric | Type | Labels | Alert |
|--------|------|--------|-------|
| `effective_plugin_count` | point gauge | `scope='global'` | < 6 → warning |
| `plugin_correlation_redundant_pairs_total` | point gauge | — | — |
| `plugin_correlation_suppressed_total` | point gauge | — | > 5 → warning |
| `job_completed_total` | counter | `job="plugin-correlation-batch", status` | failure → warning (D-06) |

`effective_plugin_count` emitted at batch completion and on Prometheus scrape of the API (reads latest `plugin_correlation_summary` row).

---

## Implementation Notes

- **Canonical ordering:** always store with `plugin_a < plugin_b`. Enforced by `CHECK` constraint and batch code.
- **Idempotency:** all writes are UPSERT or INSERT with conflict handling. Re-running produces identical output.
- **Bootstrap gate:** `co_fire_count >= 30` for pairs table; `>= 100` for suppression. Same statistical discipline as shadow_registry.
- **Suppression is reversible — and self-expiring:** when a plugin is suppressed, it stops running, so `co_fire_count` stops accumulating new data. After ~13 weeks the pair drops below the `co_fire_count >= 30` gate, the batch automatically clears `correlation_suppressed`, and the plugin re-activates. Data starvation IS the expiry mechanism. No manual re-activation needed.
- **Shadow mode vs suppression are distinct:** shadow mode = plugin runs, signals marked `is_shadow=true`, deliberate data collection. Suppressed = plugin does not run, inference suspended. Inference is not free — do not run models to produce output that will be discarded.
- **Single query surface:** all consumers use `shadow_registry_active` view. A plugin can be `promoted=true, correlation_suppressed=true` (passed performance gate, but redundant). The view hides this distinction from consumers.
- **Pipeline check point:** intelligence_pipeline loads `shadow_registry_active` at startup (same as existing shadow_registry load). Suppressed plugins are excluded from the execution set before any `_compute()` call.

---

## Out of Scope

- Per-symbol or per-timeframe correlation (YAGNI — global is sufficient for pruning decisions)
- Runtime concentration discount in the aggregator (auto-suppression handles concentration; Prometheus alert handles visibility)
- I1–I6 feature-level correlation (I7 signal direction is the right level — it captures what actually enters the decision)
