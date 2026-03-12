# Signal Drift Detection — Design Document

**Date:** 2026-03-11
**Status:** Design — ready for implementation planning
**Research ref:** `docs/ideas/renaissance-gap-analysis.md` § T3-A, T3-B
**Milestone target:** v1.8

---

## Problem

IndicAgent collects labeled training data indefinitely, but has no mechanism to detect when:

1. **Market microstructure has shifted** — the I1/I4 feature distributions that our signals were calibrated on have drifted away from the current market. A signal firing on "high RSI in trending regime" is less meaningful if the RSI distribution has structurally shifted.

2. **Signal performance is degrading** — a setup that had a 55% win rate in the first 200 trades may be at 40% now, but the rolling 30-day `setup_performance` table only shows a lagged aggregate. No mechanism fires an alert when performance starts drifting downward.

Renaissance principle: **"Degrade gracefully, adapt automatically."** Systems that require manual tuning are fragile. We need feedback loops that detect degradation before it becomes a crisis — not after someone notices the dashboard looks wrong.

---

## Scope

Two monitors, one service:

| Monitor | What it detects | Source data | Frequency |
|---------|----------------|-------------|-----------|
| **KS Feature Drift** | Market microstructure shift — input feature distributions changed | `intelligence_features` i1/i4/smc JSONB | Every 4h |
| **CUSUM Performance Drift** | Signal performance shift — rolling pnl_r trending away from baseline | `signal_ledger` outcomes | Every 1h |

Both monitors write to a shared `drift_monitor` DB table and emit live Prometheus metrics at `:9118`.

---

## Architecture

Standalone `indicagent-drift-monitor` service (`services/drift_monitor_service.py`). `Restart=always`. Port `:9118`.

Rationale for standalone service (vs timer/oneshot or tacking onto an existing service):
- Prometheus gauges hold their last value between check cycles. With a timer + oneshot pattern, the metrics endpoint goes dark between runs. An always-on service means Grafana always has current values to alert on.
- Decoupled lifecycle: the drift monitor can be restarted, tuned, or disabled without touching the hot pipeline (indicator → market analysis → signal generator).
- Consistent with every other background concern in this repo.

Internal structure: two `asyncio` tasks on a single event loop, each with its own sleep cycle.

```
drift_monitor_service.py
├── KSDriftMonitor.run_forever()    # wakes every 4h
│   ├── _check_symbol_tf(symbol, tf)
│   │   └── _ks_test(feature, reference_values, current_values)
│   └── _write_results() → drift_monitor table
└── CUSUMMonitor.run_forever()      # wakes every 1h
    ├── _check_setup(symbol, setup_plugin)
    │   └── _compute_cusum(pnl_r_series, μ₀, σ₀)
    └── _write_results() → drift_monitor table
```

---

## KS Feature Drift Monitor

### Concept

The Kolmogorov-Smirnov two-sample test asks: *are these two samples drawn from the same distribution?* We apply it per feature per symbol/TF to ask: *does the current 7 days of data look like the prior 30 days?*

If it doesn't, the market microstructure has shifted. Signals calibrated on the prior regime may be firing on stale assumptions.

### Reference and current windows

| Window | Interval | Purpose |
|--------|----------|---------|
| **Reference** | NOW − 37d to NOW − 8d | "What normal looks like" (29 days of bars) |
| **Current** | NOW − 7d to NOW | "What's happening now" |

Both windows query `intelligence_features` live. No separate baseline storage table. The reference window slides forward naturally — this is intentional. We want to detect *recent* drift vs *recent history*, not drift from a fixed historical snapshot. A sliding comparison is self-correcting: after a regime change persists long enough, it becomes the new reference.

### Monitored features

8 continuous features per symbol/TF combination, using KS test only. Categorical regime features are **deferred** (see below).

**KS test (continuous distributions):**

| Feature | Source path | Why it matters |
|---------|------------|----------------|
| `rsi_14` | `i1->>'rsi_14'` | Primary momentum indicator; distribution shift = trend/range regime change |
| `atr_14` | `i1->>'atr_14'` | Absolute volatility level; shift = different risk environment |
| `macd_histogram_12_26_9` | `i1->>'macd_histogram_12_26_9'` | Momentum sign and magnitude distribution |
| `adx_14` | `i1->>'adx_14'` | Trend strength distribution; ADX > 25 normal vs not |
| `volume_ratio` | `i1->>'volume_ratio'` | Relative institutional participation |
| `stoch_k_14_3` | `i1->>'stoch_k_14_3'` | Oscillator distribution; flat in trending markets |
| `garch_vol` | `i4->>'garch_vol'` | Conditional volatility estimate; model-fitted, drift = GARCH calibration stale |
| `bb_width` | computed: `(i1->>'bb_20_2_upper')::float - (i1->>'bb_20_2_lower')::float` | Bollinger band width = raw volatility proxy, independent of GARCH |

**Categorical features (chi-squared test) — DEFERRED to a follow-up phase:**
`volatility_regime`, `trend_regime`, `momentum_regime`, `hmm_regime_state`. These require separate schema columns (`chi2_statistic`, `chi2_pvalue`), distinct SQL frequency-counting queries, and different alert thresholds. The continuous KS features catch the same structural shifts indirectly (e.g., RSI distribution shift captures what a `trend_regime` frequency shift would also detect). Defer to avoid scope inflation.

### Alert criteria

Two-gate filter to avoid false positives from small N:

```
ALERT when: p_value < 0.05 AND ks_statistic > 0.10 AND current_n >= 50
```

- `p_value < 0.05`: standard significance threshold
- `ks_statistic > 0.10`: minimum effect size (avoids statistically-significant-but-tiny shifts on large N)
- `current_n >= 50`: minimum sample guard (7 days × 390 1m bars/day per symbol/TF is always >> 50 in practice; guard exists for tests run on short-history TFs)

Alert severity:
- `warning`: p_value < 0.05 AND ks_stat in [0.10, 0.25)
- `critical`: p_value < 0.01 AND ks_stat >= 0.25 (large, highly significant shift)

### DB query pattern

All 8 features for a given (symbol, tf) pair are extracted in a **single query per window** (not 8 separate queries) to avoid hammering compressed chunks repeatedly.

```sql
-- Reference window: fetch all 8 features in one pass
SELECT
    (i1->>'rsi_14')::float                                                      AS rsi_14,
    (i1->>'atr_14')::float                                                      AS atr_14,
    (i1->>'macd_histogram_12_26_9')::float                                      AS macd_histogram,
    (i1->>'adx_14')::float                                                      AS adx_14,
    (i1->>'volume_ratio')::float                                                AS volume_ratio,
    (i1->>'stoch_k_14_3')::float                                                AS stoch_k,
    (i4->>'garch_vol')::float                                                   AS garch_vol,
    ((i1->>'bb_20_2_upper')::float - (i1->>'bb_20_2_lower')::float)            AS bb_width
FROM intelligence_features
WHERE symbol = $1 AND tf = $2
  AND ts >= NOW() - INTERVAL '37 days'
  AND ts <  NOW() - INTERVAL '7 days';

-- Current window: same projection, different time range
SELECT ... FROM intelligence_features
WHERE symbol = $1 AND tf = $2
  AND ts >= NOW() - INTERVAL '7 days';
```

After fetching, split columns in Python and run `scipy.stats.ks_2samp(reference_col, current_col)` per feature. This reduces 23 symbols × 4 TFs × 8 features × 2 windows = 1,472 queries down to 23 × 4 × 2 = **184 queries** per check cycle. Both queries benefit from `idx_intel_features_sym_tf_ts` on `(symbol, tf, ts DESC)`.

**Compressed chunk note:** The 37-day window spans ~5 compressed chunks per symbol/TF (7-day compression policy). TimescaleDB decompresses on-the-fly for SELECT; no `decompress_chunk()` calls needed. Monitor `drift_monitor_check_duration_seconds` at first deployment — if a 4h cycle exceeds 20 minutes, reduce the feature set or add a `source = 'live'` filter to skip backfill rows (which represent a disproportionate fraction of rows near chunk boundaries).

---

## CUSUM Performance Drift Monitor

### Concept

Page's CUSUM (cumulative sum control chart) is a sequential change-point detection algorithm. Unlike a rolling average (which can mask a slow drift), CUSUM accumulates evidence of a sustained shift over time. It fires when the cumulative deviation from baseline exceeds a decision threshold.

We apply it per setup plugin × symbol to ask: *has this setup's performance statistically shifted from its calibration baseline?*

CUSUM is independent of `setup_performance`. It reads `signal_ledger` directly and applies its own 20-outcome minimum-N gate. A setup absent from `setup_performance` (sample_size < 30) may still have a CUSUM if it has ≥ 20 resolved outcomes — these are different gates for different purposes.

### Data source

```sql
SELECT pnl_r
FROM signal_ledger
WHERE symbol = $1
  AND setup_plugin = $2
  AND outcome IS NOT NULL
  AND pnl_r IS NOT NULL
ORDER BY timestamp ASC;  -- signal fire time; proxy for chronological order
```

`timestamp` is the signal fire time (set at determination). It is the correct ordering column: `signal_ledger` has no `exit_at` column; `timestamp` (from migration 015, `determined_at` alias) provides the chronological sequence needed for CUSUM.

Skip if `COUNT(*) < 20`.

### Algorithm

**Baseline estimation** — first 20 resolved outcomes for a given (symbol, setup_plugin) pair:

```
μ₀ = mean(pnl_r[0:20])
σ₀ = std(pnl_r[0:20])   # if σ₀ < 0.5, clamp to 0.5 (avoids degenerate scale)
```

**Normalized CUSUM** (two-sided, in units of σ₀):

```
x_n = (pnl_r[n] - μ₀) / σ₀           # normalize to baseline scale

S+_n = max(0, S+_{n-1} + (x_n - k))   # detects upward shift (improvement)
S-_n = max(0, S-_{n-1} + (-x_n - k))  # detects downward shift (degradation)
```

**Parameters:**
- `k = 0.5` (allowance): the minimum shift we care about, in σ units. Shifts smaller than 0.5σ are noise; we only care about shifts ≥ 1σ.
- `h = 4.0` (decision threshold): alert fires when cumulative evidence reaches 4σ units. Standard CUSUM literature recommends h = 4–5 for a false-alarm rate of ~0.01 per 1000 observations.

**Alert criteria:**

| Condition | Severity | Meaning |
|-----------|----------|---------|
| S- > h (4.0) | `warning` | Performance degrading — sustained downward drift detected |
| S- > 2h (8.0) | `critical` | Severe degradation — stop using this setup until investigated |
| S+ > h (4.0) | `info` | Performance improving — worth noting, no action required |
| n < 20 | — | Skip (insufficient baseline) |

We check degradation (S-) primarily; improvement (S+) is logged as `info` only. The goal is not to over-react to improvement; it's to catch degradation before it compounds.

### State persistence across restarts

CUSUM statistics (S+, S-) are in-memory during a check cycle. On each 1h write to `drift_monitor`, the current S+ and S- values are persisted to the `cusum_pos` / `cusum_neg` columns. On service startup, `CUSUMMonitor.__init__()` bootstraps by reading the most recent `drift_monitor` row per (symbol, setup_plugin) where `check_type = 'cusum_performance'` and re-loading `cusum_pos`, `cusum_neg`, `baseline_mean`, and `baseline_std`. This means a restart loses at most ~1h of accumulation (one cycle), not the full history.

If no prior row exists (first run), the monitor starts fresh from S+ = S- = 0.

### Reset policy

The CUSUM statistic resets when a `critical` alert fires and is manually acknowledged. Reset mechanism: standalone script `production/scripts/reset_cusum.py --symbol ES --setup trad_TrendFollowing`. The script writes a `check_type = 'cusum_reset'` row to `drift_monitor` and re-estimates μ₀/σ₀ from the 20 most recent outcomes. On the next startup or check cycle, `CUSUMMonitor` detects the reset row and reinitializes state.

Never resets automatically — a silent self-reset would mask recurring degradation.

### Scope

Per-setup tracking for all 17 I7 plugins × active contracts. Also one aggregate CUSUM per symbol (all setups combined, `setup_plugin = '_all'`) to catch system-wide degradation not visible in per-setup metrics.

---

## DB Schema

### Migration 026: `drift_monitor` table

```sql
CREATE TABLE IF NOT EXISTS drift_monitor (
    id              BIGSERIAL       PRIMARY KEY,
    check_type      TEXT            NOT NULL,       -- 'ks_feature' | 'cusum_performance' | 'cusum_reset'
    symbol          TEXT            NOT NULL,
    timeframe       TEXT,                           -- KS only; NULL for CUSUM
    setup_plugin    TEXT,                           -- CUSUM only; NULL for KS; '_all' for aggregate CUSUM
    feature_name    TEXT,                           -- KS only; NULL for CUSUM
    checked_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- KS fields (NULL for CUSUM rows)
    ks_statistic    FLOAT,
    ks_pvalue       FLOAT,
    reference_n     INTEGER,
    current_n       INTEGER,

    -- CUSUM fields (NULL for KS rows)
    cusum_pos       FLOAT,          -- S+ statistic (improvement); persisted for restart bootstrap
    cusum_neg       FLOAT,          -- S- statistic (degradation); persisted for restart bootstrap
    cusum_threshold FLOAT,          -- h_actual = h × σ₀ (warning threshold)
    baseline_mean   FLOAT,          -- μ₀
    baseline_std    FLOAT,          -- σ₀
    total_outcomes  INTEGER,        -- n at time of check

    -- Shared
    alert_triggered BOOLEAN         NOT NULL DEFAULT FALSE,
    alert_severity  TEXT,           -- 'info' | 'warning' | 'critical'
    alert_message   TEXT
);

SELECT create_hypertable(
    'drift_monitor', 'checked_at',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_drift_monitor_sym_type
    ON drift_monitor (symbol, check_type, checked_at DESC);

CREATE INDEX IF NOT EXISTS idx_drift_monitor_alerts
    ON drift_monitor (alert_triggered, checked_at DESC)
    WHERE alert_triggered = TRUE;
```

Making `drift_monitor` a hypertable (not a plain table) keeps it consistent with every other time-series table in this DB and avoids unbounded row growth. 30-day chunk interval. No retention policy — every alert is a labeled event in the system history.

---

## Prometheus Metrics

Port `:9118`. All metrics labeled with `symbol`; KS metrics additionally labeled with `timeframe` and `feature`; CUSUM metrics labeled with `setup_plugin`.

**Registration pattern:** All drift metrics use labels, so they must be created as module-level constants using `prometheus_client.Counter` / `prometheus_client.Gauge` / `prometheus_client.Histogram` directly — **not** through the `metrics.counter()` / `metrics.gauge()` helpers in `src/observability/metrics.py`, which do not accept `labelnames`. Follow the same pattern as `PLUGIN_EXECUTION_TOTAL` and `SERVICE_HEALTH_GAUGE` in `metrics.py`.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `drift_ks_pvalue` | Gauge | `symbol, timeframe, feature` | Most recent KS p-value (lower = more drift) |
| `drift_ks_statistic` | Gauge | `symbol, timeframe, feature` | Most recent KS statistic (0–1) |
| `drift_ks_alert_total` | Counter | `symbol, timeframe, feature, severity` | Cumulative KS alerts fired |
| `drift_cusum_neg` | Gauge | `symbol, setup_plugin` | Current S- statistic (degradation accumulator) |
| `drift_cusum_pos` | Gauge | `symbol, setup_plugin` | Current S+ statistic (improvement accumulator) |
| `drift_cusum_threshold` | Gauge | `symbol, setup_plugin` | Current warning threshold (h × σ₀) |
| `drift_cusum_alert_total` | Counter | `symbol, setup_plugin, severity` | Cumulative CUSUM alerts fired |
| `drift_monitor_check_duration_seconds` | Histogram | `check_type` | Time to complete one full check cycle |

Grafana alert rules on:
- `drift_ks_pvalue < 0.05` (filter by `drift_ks_statistic > 0.10`)
- `drift_cusum_neg > drift_cusum_threshold`

---

## API Endpoint

New file: `src/api/routes/drift.py`. Register in `src/api/main.py` alongside existing route modules (`signals.py`, `features.py`, etc.).

```
GET /api/drift
```

Returns current active alerts from `drift_monitor` (most recent row per symbol/feature/setup with `alert_triggered = TRUE`). Used by dashboard to render a "Drift Alerts" panel.

Response shape:
```json
{
  "ks_alerts": [
    {
      "symbol": "ES",
      "timeframe": "1m",
      "feature": "rsi_14",
      "ks_statistic": 0.18,
      "ks_pvalue": 0.003,
      "severity": "warning",
      "checked_at": "2026-03-11T14:00:00Z"
    }
  ],
  "cusum_alerts": [
    {
      "symbol": "ES",
      "setup_plugin": "trad_TrendFollowing",
      "cusum_neg": 5.2,
      "threshold": 4.0,
      "total_outcomes": 87,
      "severity": "warning",
      "checked_at": "2026-03-11T13:00:00Z"
    }
  ]
}
```

---

## Service Deployment

### `services/drift_monitor_service.py`

Mirrors the structure of `llm_writer_service.py` (simple async main loop, no Redis streams). Two internal monitors instantiated at startup, each running an `asyncio.sleep` cycle.

```python
async def main():
    ks_monitor = KSDriftMonitor(db, settings)
    cusum_monitor = CUSUMMonitor(db, settings)
    await asyncio.gather(
        ks_monitor.run_forever(interval_seconds=4 * 3600),
        cusum_monitor.run_forever(interval_seconds=3600),
    )
```

### `services/indicagent-drift-monitor.service`

```ini
[Unit]
Description=IndicAgent Drift Monitor — KS + CUSUM signal and feature drift detection
After=network-online.target

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/drift_monitor_service.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-drift-monitor

[Install]
WantedBy=multi-user.target
```

Not a oneshot+timer (unlike `weight-updater`) because we need a live Prometheus endpoint between check cycles. Gauges hold their last value as long as the process is alive — dead Prometheus endpoint = silent failure in monitoring.

---

## Implementation Plan Inputs

### Files to create

| File | Purpose |
|------|---------|
| `production/migrations/026_drift_monitor.sql` | `drift_monitor` hypertable + indexes |
| `services/drift_monitor_service.py` | Service entrypoint + main loop |
| `src/monitoring/__init__.py` | Module init |
| `src/monitoring/ks_drift_monitor.py` | KS monitor class |
| `src/monitoring/cusum_monitor.py` | CUSUM monitor class |
| `src/api/routes/drift.py` | `GET /api/drift` endpoint |
| `services/indicagent-drift-monitor.service` | systemd unit |
| `production/scripts/reset_cusum.py` | Manual CUSUM reset tool |
| `tests/unit/monitoring/__init__.py` | Test package init |
| `tests/unit/monitoring/test_ks_drift_monitor.py` | KS monitor unit tests |
| `tests/unit/monitoring/test_cusum_monitor.py` | CUSUM monitor unit tests |

### Files to modify

| File | Change |
|------|--------|
| `src/api/main.py` | Register `drift` router |

### Dependencies

- `scipy` — already in use (GARCH/Kalman) — no new dependencies
- `asyncpg` — already used by all services
- `prometheus_client` — already used; drift metrics registered directly (not via `metrics.py` helpers — see Prometheus section)

### Migration order

026 must run before the service starts. No dependency on other pending migrations.

---

## What's Deferred

| Item | Why deferred |
|------|-------------|
| Chi-squared tests for categorical features | Requires separate schema columns, distinct SQL, and different alert thresholds. Continuous KS features (RSI, ATR, GARCH) already capture the same structural shifts indirectly. |
| Automatic CUSUM reset | Requires human investigation before re-baselining; auto-reset would mask recurring degradation |
| Dashboard drift panel UI | Depends on `GET /api/drift` endpoint; deferred to dashboard completion phase |
| Per-TF CUSUM (not just per-symbol) | Data volume: most setups don't have 20 resolved outcomes per TF yet. Add TF dimension after 3+ months of signal history |
| Adaptive parameter tuning (k, h) | k=0.5, h=4.0 are literature-standard starting points. Tune empirically once we have false-alarm history |

---

## Success Criteria

1. `drift_monitor` table populated with rows every 4h (KS) and every 1h (CUSUM) for all active contracts.
2. KS test fires a `warning`-level alert in unit tests when fed synthetic reference/current arrays with `ks_stat > 0.10, p < 0.05` (e.g., reference = `Normal(0, 1)`, current = `Normal(1.5, 1)` with N=200).
3. CUSUM fires a `warning`-level alert in unit tests when fed a pnl_r series that starts at μ₀=0.3 for 20 samples, then shifts to -0.5 for 30 more samples.
4. CUSUM bootstraps correctly from DB on restart: a monitor started with prior `cusum_neg=3.5` in `drift_monitor` continues accumulation from 3.5, not from 0.
5. `GET /api/drift` returns correct alert data; returns `{"ks_alerts": [], "cusum_alerts": []}` when no alerts are active.
6. Prometheus metrics visible at `:9118` between check cycles (gauges hold last value after first run).
7. Service survives DB connection failure at startup — logs ERROR, sleeps `RestartSec=10`, retries. Does not crash with unhandled exception.
