# Signals Schema

**Version:** 1.0
**Status:** current
**Last Updated:** 2026-06-16

---

## 1. Purpose

Data contracts for the 3-table Signal Ledger Architecture (SLA), introduced in Phase 128. Verified against `db/migrations/137_3table_schema.sql`.

**Who reads this:** Engineers writing queries against signal data, building ML training pipelines, or implementing signal writers. Start here before touching any signal table.

---

## 2. Architecture

```
signal_events (hypertable)     — one row per I7 plugin fire
       │
       ├─ trade_frames          — one row per entry_type per signal fire
             │
             └─ trade_executions — one row per live trade execution
```

**signal_ledger_full** — join view across all three tables. Phase 128 backward-compat surface. Renamed to `signal_ledger` in Phase 129 when the legacy monolith is dropped.
<!-- src: db/migrations/137_3table_schema.sql -->

---

## 3. Data Contracts

### signal_events (hypertable)

Detection layer. Written once at I7 fire time, never updated.
<!-- src: db/migrations/137_3table_schema.sql — signal_events DDL -->

| Column | Type | Description |
|--------|------|-------------|
| `signal_id` | uuid | Signal identity — composite PK with `ts` (hypertable requirement) |
| `ts` | timestamptz | Bar timestamp at fire time — **primary time column**, partition dimension |
| `symbol` | text | Instrument symbol |
| `tf` | text | Timeframe |
| `setup_plugin` | text | I7 plugin that fired |
| `direction` | text | `long` / `short` |
| `raw_confidence` | float8 | Intrinsic composite confidence (ICC output); immutable after emit |
| `calibrated_confidence` | float8 | Nullable; async-populated by calibration pipeline |
| `cis_score` | float8 | CIS composite |
| `factor_scores` | jsonb | Per-plugin factor breakdown; used for ML weight optimization |
| `context_features` | jsonb | Full flat_features snapshot at fire time; SignalRanker feature matrix |
| `ctf_score` | float8 | Cross-timeframe score |
| `ctf_confirmed` | bool | Whether I6 CTF gate passed |
| `zone_friction_score` | float8 | Zone friction annotation (extrinsic; not a gate) |
| `hmm_regime_at_fire` | int4 | HMM regime at fire time |
| `plugin_regime_type` | text | Plugin-declared regime |
| `garch_sigma_at_fire` | float8 | GARCH volatility estimate |
| `is_shadow` | bool | Shadow-mode signal (not production) |
| `is_backfill` | bool | Historical backfill signal |
| `status` | text | `pending` / `active` / `regime_suppressed` / `expired` |
| `signal_schema_version` | int4 | Schema version (int4, not text — correction from legacy monolith) |
| `ttl_bars` | int4 | Time-to-live in bars |
| `expires_at` | timestamptz | Expiry wall-clock time |
| `signal_computed_at` | timestamptz | Pipeline write wall-clock from payload; `latency = signal_computed_at - ts`. Nullable — use `COALESCE(signal_computed_at, ts)` in queries. |
| `created_at` | timestamptz | DB insertion time — distinct from `signal_computed_at` |

**Primary key:** `(signal_id, ts)` — composite required by TimescaleDB hypertable.
**Compression:** `segmentby = 'symbol,tf'`, `orderby = 'ts DESC'`, policy at 7 days.

---

### trade_frames

Hypothesis layer. One row per `entry_type` per signal fire. ML trains on `counterfactual_pnl_r`.
<!-- src: db/migrations/137_3table_schema.sql — trade_frames DDL -->

| Column | Type | Description |
|--------|------|-------------|
| `frame_id` | uuid | Primary key |
| `signal_id` | uuid | FK to `signal_events` (composite with `signal_ts`) |
| `signal_ts` | timestamptz | Denormalized from `signal_events.ts` — required for FK to hypertable composite PK |
| `entry_type` | text | `at_close` / `at_pullback` / `at_limit` / `at_reclaim` / `zone_proximal` |
| `direction` | text | `long` / `short` |
| `entry_price` | float8 | Hypothetical entry |
| `stop_price` | float8 | Hypothetical stop |
| `target_price` | float8 | Hypothetical target |
| `r_multiple` | float8 | `(target - entry) / (entry - stop)` |
| `counterfactual_pnl_r` | float8 | **ML target variable.** Always populated by CounterfactualTracker. |
| `counterfactual_mfe` | float8 | Max favorable excursion (counterfactual) |
| `counterfactual_mae` | float8 | Max adverse excursion (counterfactual) |
| `counterfactual_bars` | int4 | Bars held (counterfactual) |
| `counterfactual_exit_reason` | text | `target_hit` / `stop_hit` / `ttl_expired` |
| `counterfactual_measured_at` | timestamptz | When CounterfactualTracker resolved the frame |
| `was_selected` | bool | Whether this frame was selected for actual execution |
| `frame_details` | jsonb | Stop architecture provenance; historical shadow fields during Phase 129 migration |
| `created_at` | timestamptz | DB insertion time |

**FK:** `(signal_id, signal_ts) REFERENCES signal_events(signal_id, ts)` — composite required by TimescaleDB.

---

### trade_executions

Execution layer. One row per live trade. Most frames have zero rows here.
<!-- src: db/migrations/137_3table_schema.sql — trade_executions DDL -->

| Column | Type | Description |
|--------|------|-------------|
| `execution_id` | uuid | Primary key |
| `frame_id` | uuid | FK to `trade_frames` |
| `actual_fill_price` | float8 | Actual entry fill |
| `actual_exit_price` | float8 | Actual exit price |
| `actual_pnl_r` | float8 | Realized P&L in R |
| `actual_mfe` | float8 | Realized max favorable excursion |
| `actual_mae` | float8 | Realized max adverse excursion |
| `actual_bars` | int4 | Bars held |
| `market_entry_price` | float8 | Market price at entry time |
| `market_entry_gap_bars` | int4 | Bars between signal fire and actual entry |
| `exit_reason` | text | How the trade exited |
| `executed_at` | timestamptz | Entry fill timestamp |
| `exited_at` | timestamptz | Exit timestamp |

---

### signal_ledger_full (view)

Backward-compat join view across all three tables. `signal_computed_at` is `COALESCE`d in the view — callers need not apply it.
<!-- src: db/migrations/137_3table_schema.sql — signal_ledger_full view -->

```sql
-- Query pattern
SELECT * FROM signal_ledger_full
WHERE symbol = 'ES' AND ts > now() - INTERVAL '7 days';
```

Phase 128: query via `signal_ledger_full`. Phase 129+: `signal_ledger` (same view, renamed after legacy monolith drop).

---

## 4. Query Patterns

### ML training dataset

```sql
SELECT
    se.signal_id, se.ts, se.symbol, se.tf, se.setup_plugin,
    se.raw_confidence, se.factor_scores, se.context_features,
    se.ctf_score, se.ctf_confirmed, se.zone_friction_score,
    se.hmm_regime_at_fire,
    tf.entry_type, tf.counterfactual_pnl_r, tf.counterfactual_mfe,
    tf.counterfactual_mae, tf.counterfactual_exit_reason
FROM signal_events se
JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
WHERE tf.counterfactual_pnl_r IS NOT NULL
  AND se.is_shadow = false;
```

### Signal lifecycle check

```sql
-- COALESCE required on signal_computed_at — nullable in signal_events
SELECT signal_id, COALESCE(signal_computed_at, ts) AS computed_at, status
FROM signal_events
WHERE symbol = 'ES' ORDER BY ts DESC LIMIT 100;
```

---

## 5. Canonical Constants

- **`SIGNAL_SCHEMA_VERSION`** in `src/intelligence/trading/signal_schema.py` — all producers/consumers import from here; no hardcoded version strings.
- **entry_type values**: `at_close`, `at_pullback`, `at_limit`, `at_reclaim`, `zone_proximal` — raw string literals, no enum.
- **status values**: `pending`, `active`, `regime_suppressed`, `expired` — raw string literals, no enum.
<!-- src: src/intelligence/trading/signal_schema.py -->

---

## 6. See Also

- `docs/signals/signal-trade-separation-ADR.md` — design rationale for 3-table split
- `docs/signals/signals-confidence-patterns.md` — `raw_confidence` integrity requirements
- `docs/signals/signals-lifecycle.md` — status transition rules
- `db/migrations/137_3table_schema.sql` — canonical DDL source
