# Signal Metrics Redesign — Renaissance-Aligned Performance System

**Date:** 2026-04-05  
**Status:** Approved — ready for implementation planning  
**Phase:** 60

---

## Problem Statement

The current signal performance system has a data quality crisis feeding the live feedback loop:

1. **No pnl_r validation** — `pnl_r = pnl_ticks / risk`. When `stop_loss ≈ entry_price`, risk → 0 and pnl_r → ±∞. CVDDivergence shows Sharpe = -496.67 in the dashboard today. This value flows directly into `perf_multiplier` and corrupts live signal selection.

2. **Monolithic updater** — `setup_performance_updater.py` does query + validate + compute + persist + rank in one file. Violates every DAG principle established in the I1-I7 refactor.

3. **Inline API aggregation** — the attribution endpoint computes AVG/STDDEV from raw `signal_ledger` on every HTTP request. No separation of compute from serve.

4. **Two tracks collapsed** — zone track (`pnl_r`) and market track (`market_entry_pnl_r`) measure fundamentally different things. Zone = "did the structural setup deliver?", Market = "did this make money with a market-order entry?" They are currently conflated.

5. **No regime conditioning** — `setup_performance_updater.py` aggregates across all regimes. A mean-reversion setup's stats in a trending market pollute its performance profile in a ranging market. Violates "segment relentlessly."

---

## Design Principles Applied

- **Instrument everything** — every signal resolution is a labeled training sample; every DQ violation is logged, never silently discarded
- **Segment relentlessly** — metrics computed per (track × setup × tf × regime × window)
- **Earn the right through proof** — N < 30 excluded from feedback loop; p-value gate required
- **DAG architecture** — ComputeAgent is DB-ignorant, publishes events; WriterAgent owns persistence
- **Degrade gracefully** — `'all'` regime rollup ensures bootstrap phase has data when per-regime N is insufficient

---

## Architecture

### Component Map

```
NEW AGENTS:
  services/signal_metrics_compute_agent.py  → SignalMetricsComputeAgent
  services/signal_metrics_writer_agent.py   → SignalMetricsWriterAgent

NEW INTELLIGENCE MODULES:
  src/intelligence/metrics/__init__.py
  src/intelligence/metrics/validator.py     → DataQualityValidator (pure, no I/O)
  src/intelligence/metrics/compute.py       → compute_signal_metrics(), compute_ic_metrics() (pure, testable)

NEW STREAM KEY:
  src/core/stream_keys.py  →  topic_signal_metrics()  →  {env}.intelligence.signal_metrics

NEW SYSTEMD UNITS:
  indicagent-signal-metrics-compute.service  (metrics :9126)
  indicagent-signal-metrics-writer.service   (metrics :9127)

NEW DB TABLES:
  signal_metrics              zone + market track stats per segment
  signal_metrics_ic           IC per plugin × regime × window
  signal_metrics_dq_failures  permanent DQ violation audit log

MODIFIED:
  src/core/stream_keys.py                              + topic_signal_metrics()
  src/intelligence/setup_performance_updater.py        → thin shim reading signal_metrics
  src/api/routes/signals.py                            → reads signal_metrics, no inline SQL
  services/intelligence_pipeline_agent.py              → regime-conditioned perf_multiplier
  dashboard/src/components/signals/attribution-row.tsx → two tracks, IC column, N<30 dimming
```

### DAG Data Flow

```
signal_ledger (resolved signals, exit_at NOT NULL)
        │
        │  systemd timer: every 15 min
        ▼
┌──────────────────────────────────────┐
│  SignalMetricsComputeAgent           │  ← DB-ignorant output
│  ────────────────────────────────    │
│  1. Query signal_ledger (90d)        │
│  2. DataQualityValidator.check()     │
│     invalid → MetricsDQEvent         │
│  3. compute_signal_metrics()         │
│     → MetricsComputedEvent           │
│     (zone track + market track)      │
│  4. compute_ic_metrics()             │
│     → ICComputedEvent                │
│  Publishes all →                     │
│    intelligence.signal_metrics       │
└──────────────────────────────────────┘
        │
        │  Kafka: intelligence.signal_metrics
        ▼
┌──────────────────────────────────────┐
│  SignalMetricsWriterAgent            │
│  ────────────────────────────────    │
│  MetricsComputedEvent                │
│    → UPSERT signal_metrics           │
│  ICComputedEvent                     │
│    → UPSERT signal_metrics_ic        │
│  MetricsDQEvent                      │
│    → INSERT signal_metrics_          │
│      dq_failures                     │
│  All windows written                 │
│    → UPDATE setup_performance (shim) │
└──────────────────────────────────────┘
        │
        ├──▶ API /signals/attribution
        │      reads signal_metrics (pre-computed)
        │      zero inline aggregation
        │
        └──▶ intelligence_pipeline_agent
               perf_multiplier from signal_metrics
               WHERE track='market' AND regime=current_hmm
```

---

## Data Quality Validator

`src/intelligence/metrics/validator.py` — pure functions, zero I/O, fully unit-testable.

Four gates applied in order. First failure short-circuits:

| Gate | Rule | reason_code |
|------|------|-------------|
| 1 | `direction ∈ {-1, 1}` | `invalid_direction` |
| 2 | `\|entry_price - stop_loss\| >= instrument_tick_size` | `risk_below_min_tick` |
| 3 | `\|pnl_r\| <= MAX_VALID_R` (default 10.0, in Settings) | `pnl_r_outlier` |
| 4 | `hmm_regime_at_fire IS NOT NULL` | `missing_regime` |

Gate 2 is the direct fix for CVDDivergence Sharpe = -496: ES tick = 0.25; if `|entry - stop| < 0.25` the row is invalid.

`MAX_VALID_R = 10.0` — a 10R single-trade loss is a data anomaly, not market reality. Configurable in `Settings` for future per-setup tuning.

Invalid rows are logged to `signal_metrics_dq_failures` with signal_id, reason_code, and raw values. Raw `signal_ledger` rows are **never modified** — Renaissance principle: never drop data.

---

## Database Schema

```sql
-- signal_metrics: one row per (track × setup × tf × regime × window)
-- Full upsert on every 15-min compute run
CREATE TABLE signal_metrics (
    track               TEXT    NOT NULL,  -- 'zone' | 'market'
    setup_plugin        TEXT    NOT NULL,
    tf                  TEXT    NOT NULL,  -- '1m'|'5m'|'15m'|'1h'
    regime_type         TEXT    NOT NULL,  -- 'trend'|'mean_reversion'|'any'|'all'
    window_days         INT     NOT NULL,  -- 7 | 30 | 90
    -- Sample counts
    n                   INT     NOT NULL,
    n_outliers          INT     NOT NULL DEFAULT 0,
    never_activated_pct FLOAT,             -- zone track: % where pnl_r IS NULL (never entered zone)
    -- Performance
    win_rate            FLOAT,             -- fraction with outcome IN WIN_OUTCOMES
    avg_r               FLOAT,             -- AVG(pnl_r) over validated rows
    std_r               FLOAT,             -- STDDEV(pnl_r)
    sharpe              FLOAT,             -- avg_r / std_r (unnormalized, for ranking only)
    p_value             FLOAT,             -- two-sided t-test: H0 = avg_r == 0
    -- Efficiency
    avg_mae             FLOAT,
    avg_mfe             FLOAT,
    -- Audit
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (track, setup_plugin, tf, regime_type, window_days)
);

-- signal_metrics_ic: IC per setup × regime × window
CREATE TABLE signal_metrics_ic (
    setup_plugin        TEXT    NOT NULL,
    tf                  TEXT    NOT NULL,
    regime_type         TEXT    NOT NULL,
    window_days         INT     NOT NULL,
    n                   INT     NOT NULL,
    ic                  FLOAT,             -- Pearson r(confidence, binary_outcome)
    p_value             FLOAT,
    is_significant      BOOL,              -- p < 0.05 AND n >= 30
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (setup_plugin, tf, regime_type, window_days)
);

-- signal_metrics_dq_failures: permanent audit log — never delete, never truncate
CREATE TABLE signal_metrics_dq_failures (
    signal_id           UUID        NOT NULL,
    reason_code         TEXT        NOT NULL,
    entry_price         FLOAT,
    stop_loss           FLOAT,
    pnl_r               FLOAT,
    direction           INT,
    hmm_regime          INT,
    setup_plugin        TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON signal_metrics_dq_failures (reason_code);
CREATE INDEX ON signal_metrics_dq_failures (signal_id);
```

### Regime Mapping

`hmm_regime_at_fire` from `signal_ledger` maps to `regime_type` in `signal_metrics`:

| hmm_regime_at_fire | regime_type |
|--------------------|-------------|
| 0 (ranging) | `'any'` |
| 1 (uptrend) | `'trend'` |
| 2 (downtrend) | `'trend'` |
| NULL | → DQ failure (Gate 4) |

The compute agent also writes a `regime_type = 'all'` rollup row per (track, setup, tf, window) — aggregating across all regimes. This is the bootstrap fallback when per-regime N < 30.

---

## Compute Functions

`src/intelligence/metrics/compute.py` — pure functions, no I/O.

```python
def compute_signal_metrics(
    rows: list[dict],    # validated signal_ledger rows
    track: str,          # 'zone' | 'market'
    window_days: int,
) -> list[SignalMetricsRow]:
    """
    Groups by (setup_plugin, tf, regime_type).
    Computes per group: n, win_rate, avg_r, std_r, sharpe, p_value,
                        avg_mae, avg_mfe, never_activated_pct.
    Excludes groups with n < MIN_SAMPLE_SIZE (30).
    Also emits regime_type='all' rollup per (setup, tf).
    """

def compute_ic_metrics(
    rows: list[dict],    # validated rows with confidence + binary_outcome
    window_days: int,
) -> list[ICMetricsRow]:
    """
    Groups by (setup_plugin, tf, regime_type).
    Computes Pearson r(confidence, binary_outcome).
    Reuses src/intelligence/ml/information_coefficient.compute_ic().
    """
```

**WIN_OUTCOMES** (explicit, from `signal_outcome.py`):
```python
WIN_OUTCOMES = {'target_1', 'target_1_2', 'target_full'}
win_rate = sum(1 for r in group if r['outcome'] in WIN_OUTCOMES) / len(group)
```

Track-specific field selection:
- Zone track: uses `pnl_r`, `mae`, `mfe`, `outcome`
- Market track: uses `market_entry_pnl_r`, `market_entry_mae`, `market_entry_mfe`, `market_entry_outcome`

---

## Feedback Loop Change

### Before (broken)

```python
# intelligence_pipeline_agent.py
# Reads setup_performance — global, no regime conditioning
rows = await db.fetch(
    "SELECT setup_plugin, sharpe_ratio FROM setup_performance WHERE sample_size >= 30"
)
```

### After (Renaissance-aligned)

```python
# Regime-conditioned: only market track stats in current HMM regime count
rows = await db.fetch(
    """SELECT setup_plugin, sharpe FROM signal_metrics
       WHERE track = 'market'
         AND regime_type = $1
         AND window_days = 30
         AND n >= 30""",
    current_regime_label,  # 'trend' | 'mean_reversion' | 'any'
)
```

`setup_performance` table is populated by `SignalMetricsWriterAgent` as a backward-compatibility shim after each compute run. One source of truth: `signal_metrics`. `setup_performance` becomes a derived view.

---

## Dashboard Changes

`attribution-row.tsx` changes from one table to two sub-tables:

**Zone Track** (Setup Quality):
```
Setup   N   Win%   Avg R   IC    p-val
[dim if N<30 with tooltip "insufficient data — N={n}"]
```

**Market Track** (Tradeable Alpha):
```
Setup   N   Win%   Avg R   Sharpe   p-val
[dim if N<30]
```

- IC replaces Sharpe in the zone table (IC = "is confidence predictive?"; Sharpe = "did this make money?")
- `never_activated_pct` surfaced as tooltip on N column: hover → "X% never entered the zone"
- API endpoints: `?track=zone` and `?track=market` (new query param)

---

## Tests

All tests written before implementation (TDD):

| Test file | Coverage |
|-----------|----------|
| `tests/unit/intelligence/test_metrics_validator.py` | All 4 gates, valid/invalid rows, edge cases (risk exactly at threshold) |
| `tests/unit/intelligence/test_metrics_compute.py` | compute_signal_metrics(), compute_ic_metrics(), 'all' rollup generation, N<30 exclusion |
| `tests/unit/service_tests/test_signal_metrics_compute_agent.py` | Timer trigger, DQ routing, event publishing |
| `tests/unit/service_tests/test_signal_metrics_writer_agent.py` | Upsert idempotency, setup_performance shim update |

---

## Verification Steps

```bash
# 1. Unit tests pass
.venv/bin/pytest tests/unit/intelligence/test_metrics_validator.py -v
.venv/bin/pytest tests/unit/intelligence/test_metrics_compute.py -v

# 2. Services start
sudo systemctl start indicagent-signal-metrics-compute
sudo systemctl start indicagent-signal-metrics-writer
systemctl status indicagent-signal-metrics-compute indicagent-signal-metrics-writer

# 3. After first compute run (15 min or manual trigger)
docker exec timescaledb psql -U postgres -d indicagent \
  -c "SELECT track, setup_plugin, tf, regime_type, n, win_rate, avg_r, sharpe
      FROM signal_metrics ORDER BY track, setup_plugin LIMIT 30;"

# 4. DQ failures audited
docker exec timescaledb psql -U postgres -d indicagent \
  -c "SELECT reason_code, count(*) FROM signal_metrics_dq_failures GROUP BY reason_code;"

# 5. CVDDivergence no longer shows -496 Sharpe in dashboard
# Dashboard /signals → attribution row → CVDDivergence shows valid value or N<30 dim

# 6. perf_multiplier using regime-conditioned data
grep "perf_weights\|perf_multiplier" logs/intelligence_pipeline_agent.log | tail -10
```
