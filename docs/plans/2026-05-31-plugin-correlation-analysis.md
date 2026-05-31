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

aggregator (no changes)
  — already respects promoted flag in shadow_registry; respects correlation_suppressed via same path
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
```

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
- **Suppression is reversible:** batch clears `correlation_suppressed` when correlation drops below threshold. No manual re-activation needed.
- **No aggregator changes:** aggregator already gates on `promoted` in shadow_registry. Adding `AND NOT correlation_suppressed` to that query is the only required change — and it may already be implicit if the aggregator filters on `promoted = true` and suppressed plugins retain their promoted status.
- **Suppression vs demotion:** `correlation_suppressed` is orthogonal to `promoted`. A plugin can be `promoted=true, correlation_suppressed=true` — it passed the performance gate but is redundant. The aggregator must check both.

---

## Out of Scope

- Per-symbol or per-timeframe correlation (YAGNI — global is sufficient for pruning decisions)
- Runtime concentration discount in the aggregator (auto-suppression handles concentration; Prometheus alert handles visibility)
- I1–I6 feature-level correlation (I7 signal direction is the right level — it captures what actually enters the decision)
