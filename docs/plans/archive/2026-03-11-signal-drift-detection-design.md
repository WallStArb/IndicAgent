# Signal Drift Detection — Design Document

**Date:** 2026-03-11
**Status:** Shipped — KS drift_penalty in aggregator.py; CUSUM in setup_performance_updater.py + drift_state table; runs in service layer (not as plugin)
**Research ref:** `docs/research/renaissance-gap-analysis.md` § T3-A, T3-B
**Milestone target:** v1.8

---

## Problem

IndicAgent collects labeled training data indefinitely, but has no mechanism to detect when:

1. **Market microstructure has shifted** — the I1/I4 feature distributions that our signals were calibrated on have drifted away from the current market. A signal firing on "high RSI in trending regime" is less meaningful if the RSI distribution has structurally shifted.

2. **Signal performance is degrading** — a setup that had a 55% win rate in the first 200 trades may be at 40% now, but the rolling 30-day `setup_performance` table only shows a lagged aggregate. No mechanism fires an alert when performance starts drifting downward.

Renaissance principle: **"Degrade gracefully, adapt automatically."** Systems that require manual tuning are fragile. We need feedback loops that detect degradation before it becomes a crisis — not after someone notices the dashboard looks wrong.

---

## Design Philosophy: Feedback Loops, Not Monitoring Dashboards

An earlier version of this design was a monitoring system: drift detected → DB row → Prometheus alert → human responds. That is not the Renaissance approach.

**Jim Simons would say:** A detection system that waits for a human to act is a system that requires human tuning. Human-tuned systems are fragile — they degrade at 3am on a holiday weekend while you're asleep. The whole point of building the measurement infrastructure is to close the loop: detection feeds directly back into the pipeline without human intervention.

This design therefore includes two automated response components alongside the monitoring infrastructure:

| Layer | Component | What it does |
|-------|-----------|-------------|
| Detection | KS Feature Drift Monitor | Detects when input feature distributions have shifted |
| Detection | CUSUM Performance Drift Monitor | Detects when signal pnl_r is trending away from baseline |
| **Response** | **KS → CIS confidence modifier** | **Automatically reduces signal confidence when feature drift is active** |
| **Response** | **CUSUM → perf_multiplier adjustment** | **Automatically reduces setup weight when performance has degraded** |
| Observability | DB table, Prometheus, API | Instruments everything so we can see what the system is doing |

Detection without response is expensive logging. Response without detection is thrashing. Both layers are required.

**On the false positive risk:** Automated adjustment means a false CUSUM positive will temporarily under-weight a healthy setup, or a false KS alert will briefly penalize signal confidence. Renaissance's tradeoff: the cost of briefly under-weighting a healthy setup is bounded and recoverable (setup weight returns to normal when CUSUM resets). The cost of missing a genuine degradation signal is unbounded — you continue trading a broken setup at full weight, compounding losses. Accept the false positive risk. Document the starting parameters so we can tune them empirically.

---

## Scope

Two monitors + two feedback integrations, one service:

| Component | Source data | Frequency |
|-----------|-------------|-----------|
| KS Feature Drift Monitor | `intelligence_features` i1/i4 JSONB | Every 4h |
| CUSUM Performance Drift Monitor | `signal_ledger` outcomes | Every 1h |
| KS → CIS confidence modifier | Redis cache written by drift service | Per bar (read at signal aggregation time) |
| CUSUM → perf_multiplier adjustment | `drift_monitor` DB table | Daily (via `weight_updater` extension) |

---

## Architecture

Standalone `indicagent-drift-monitor` service (`services/drift_monitor_service.py`). `Restart=always`. Port `:9118`.

Rationale for standalone service (vs timer/oneshot or tacking onto an existing service):
- Prometheus gauges hold their last value between check cycles. With a timer + oneshot pattern, the metrics endpoint goes dark between runs. An always-on service means Grafana always has current values to alert on.
- Decoupled lifecycle: the drift monitor can be restarted, tuned, or disabled without touching the hot pipeline.
- Consistent with every other background concern in this repo.

Internal structure: two `asyncio` tasks on a single event loop, each with its own sleep cycle.

```
drift_monitor_service.py
├── KSDriftMonitor.run_forever()          # wakes every 4h
│   ├── _check_symbol_tf(symbol, tf)
│   │   └── _ks_test(feature, ref_vals, cur_vals) → KSResult
│   ├── _write_results() → drift_monitor table
│   └── _publish_drift_state()            # writes Redis drift:ks:{symbol}:{tf}
└── CUSUMMonitor.run_forever()            # wakes every 1h
    ├── _check_setup(symbol, setup_plugin)
    │   └── _compute_cusum(pnl_r_series, μ₀, σ₀) → CUSUMResult
    └── _write_results() → drift_monitor table
                                          # CUSUM → perf_multiplier handled by weight_updater
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

8 continuous features per symbol/TF combination, using KS test.

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

**Categorical features (chi-squared test) — DEFERRED:**
`volatility_regime`, `trend_regime`, `momentum_regime`, `hmm_regime_state`. Require separate schema columns, distinct SQL, different alert thresholds. The continuous KS features capture the same structural shifts indirectly. Defer to avoid scope inflation; add once chi-squared integration value is empirically demonstrated.

### Alert criteria

Two-gate filter to avoid false positives from small N:

```
ALERT when: p_value < 0.05 AND ks_statistic > 0.10 AND current_n >= 50
```

- `p_value < 0.05`: standard significance threshold
- `ks_statistic > 0.10`: minimum effect size (avoids statistically-significant-but-tiny shifts on large N)
- `current_n >= 50`: minimum sample guard

Alert severity:
- `warning`: p_value < 0.05 AND ks_stat in [0.10, 0.25)
- `critical`: p_value < 0.01 AND ks_stat >= 0.25 (large, highly significant shift)

A `warning` for any single feature triggers the drift state for the entire symbol/TF pair. The worst-case severity across all 8 features is what gets cached in Redis and applied to signal confidence.

**Decision rationale for per-symbol/TF aggregation:** We could apply feature-specific penalties (RSI drifted → penalize RSI-heavy setups only). That's more precise but requires mapping setups to their dominant features — complex to maintain as plugins evolve. A symbol/TF-level confidence penalty is simpler, more conservative, and cannot develop blind spots as new setups are added. Revisit feature-level granularity once we have empirical evidence that the coarser approach over-penalizes.

### DB query pattern

All 8 features for a given (symbol, tf) pair are extracted in a **single query per window** (not 8 separate queries) to avoid hammering compressed chunks repeatedly:

```sql
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
  AND ts >= NOW() - INTERVAL '37 days'   -- reference: swap upper bound to NOW()-7d
  AND ts <  NOW() - INTERVAL '7 days';
```

After fetching, split columns in Python and run `scipy.stats.ks_2samp(ref_col, cur_col)` per feature. This reduces 23 symbols × 4 TFs × 8 features × 2 windows = 1,472 queries down to 23 × 4 × 2 = **184 queries** per check cycle. Both queries benefit from `idx_intel_features_sym_tf_ts` on `(symbol, tf, ts DESC)`.

**Compressed chunk note:** The 37-day window spans ~5 compressed chunks per symbol/TF (7-day compression policy). TimescaleDB decompresses on-the-fly for SELECT. Monitor `drift_monitor_check_duration_seconds` at first deployment — if a 4h cycle exceeds 20 minutes, add a `source = 'live'` filter to skip backfill rows.

---

## CUSUM Performance Drift Monitor

### Concept

Page's CUSUM (cumulative sum control chart) is a sequential change-point detection algorithm. Unlike a rolling average (which can mask a slow drift), CUSUM accumulates evidence of a sustained shift over time. It fires when the cumulative deviation from baseline exceeds a decision threshold.

We apply it per setup plugin × symbol to ask: *has this setup's performance statistically shifted from its calibration baseline?*

CUSUM is independent of `setup_performance`. It reads `signal_ledger` directly with its own 20-outcome minimum-N gate. A setup absent from `setup_performance` (sample_size < 30) may still have a CUSUM if it has ≥ 20 resolved outcomes.

### Data source

```sql
SELECT pnl_r
FROM signal_ledger
WHERE symbol = $1
  AND setup_plugin = $2
  AND outcome IS NOT NULL
  AND pnl_r IS NOT NULL
ORDER BY timestamp ASC;  -- signal fire time; chronological order for sequential CUSUM
```

Skip if `COUNT(*) < 20`.

### Algorithm

**Baseline estimation** — first 20 resolved outcomes per (symbol, setup_plugin):

```
μ₀ = mean(pnl_r[0:20])
σ₀ = std(pnl_r[0:20])   # clamped to minimum 0.5 to avoid degenerate scale
```

**Normalized CUSUM** (two-sided, in units of σ₀):

```
x_n = (pnl_r[n] - μ₀) / σ₀

S+_n = max(0, S+_{n-1} + (x_n - k))    # detects upward shift (improvement)
S-_n = max(0, S-_{n-1} + (-x_n - k))   # detects downward shift (degradation)
```

**Parameters (starting values — tune empirically):**
- `k = 0.5`: allowance in σ units. Shifts < 0.5σ are treated as noise.
- `h = 4.0`: decision threshold. Alert fires when cumulative evidence reaches 4σ. CUSUM literature recommends h = 4–5 for false-alarm rate ~0.01 per 1000 observations.

**Alert criteria:**

| Condition | Severity | Auto-response |
|-----------|----------|--------------|
| S- > h (4.0) | `warning` | `perf_multiplier` reduced (see below) |
| S- > 2h (8.0) | `critical` | `perf_multiplier` reduced more aggressively |
| S+ > h (4.0) | `info` | No action — improvement noted, logged only |
| n < 20 | — | Skip |

### State persistence across restarts

S+/S- are in-memory during a cycle. On each 1h write to `drift_monitor`, current S+ and S- are persisted. On startup, `CUSUMMonitor.__init__()` bootstraps by reading the most recent `drift_monitor` row per (symbol, setup_plugin) and re-loading `cusum_pos`, `cusum_neg`, `baseline_mean`, `baseline_std`. Restart loses at most one cycle (~1h) of accumulation, not the full history.

### Reset policy

Manual reset only via `production/scripts/reset_cusum.py --symbol ES --setup trad_TrendFollowing`. Script writes a `cusum_reset` row to `drift_monitor` and re-estimates μ₀/σ₀ from the 20 most recent outcomes. Monitor detects reset row on next cycle and reinitializes.

Never auto-resets — silent self-reset would mask recurring degradation.

### Scope

Per-setup tracking for all 17 I7 plugins × active contracts. One aggregate CUSUM per symbol (`setup_plugin = '_all'`) catches system-wide degradation not visible in per-setup metrics.

---

## Feedback Loop: KS Drift → CIS Confidence Modifier

**Why this exists:** Detection without action is surveillance. When feature distributions have drifted, signals computed on those features carry less information. The aggregator must know this.

### Mechanism

After each KS check cycle, `KSDriftMonitor._publish_drift_state()` writes to DragonflyDB:

```
Key:   drift:ks:{symbol}:{tf}
Value: "none" | "warning" | "critical"
TTL:   8h  (2× check interval; stale if service dies)
```

The key encodes the worst-case severity across all 8 monitored features for that symbol/TF. If 2 features are `warning` and 1 is `critical`, the key value is `"critical"`.

`signal_generator_service` reads this key in `_build_all_ranked()` when computing `adjusted_rank`. A `drift_confidence_penalty` is applied as a multiplier on the raw CIS score before ranking:

```python
DRIFT_PENALTIES = {"none": 1.0, "warning": 0.85, "critical": 0.70}

drift_key = stream_keys.drift_ks(symbol, tf)  # "drift:ks:ES:1m"
drift_state = await redis.get(drift_key) or b"none"
penalty = DRIFT_PENALTIES[drift_state.decode()]
adjusted_cis = signal["cis_score"] * penalty
```

**Penalty values (starting values — tune empirically):**
- `warning`: 15% reduction — signal scoring is still valid, just less trustworthy
- `critical`: 30% reduction — significant distribution shift; signals should rank markedly lower

**Decision rationale:** 30% is not enough to suppress signals outright — it just ranks them lower relative to setups with healthier distributions. A suppression-based approach (cut off signals entirely during KS drift) was considered and rejected: it removes all signals for a symbol/TF during any regime transition, including transitions that create the best trading opportunities. Confidence reduction preserves signal flow while appropriately discounting it.

### Cache key registration

Add `drift_ks(symbol: str, tf: str) -> str` to `src/core/stream_keys.py` alongside existing key constructors. All Redis key construction goes through this module — no hardcoded strings elsewhere.

---

## Feedback Loop: CUSUM → Automatic `perf_multiplier` Adjustment

**Why this exists:** `setup_performance` already tracks rolling win rate and `weight_updater` already writes `perf_multiplier`. The aggregator already reads it. CUSUM state is precisely the signal that `weight_updater` is missing: "is this setup's performance degrading *right now*, beyond what the 30-day rolling average shows?"

### Mechanism

Extend `src/intelligence/weight_updater.py` (the daily job that writes `setup_performance`) to also read CUSUM state from `drift_monitor` and apply an adjustment to the computed `perf_multiplier`:

```python
# In weight_updater, after computing base perf_multiplier from win_rate/sharpe:
cusum_state = get_worst_cusum_state(symbol, setup_plugin)  # query drift_monitor

CUSUM_ADJUSTMENTS = {
    "none":     1.0,
    "info":     1.0,    # improvement — no change; don't reward drift positively
    "warning":  0.70,   # 30% reduction
    "critical": 0.40,   # 60% reduction; floor at 0.30 (never fully suppress)
}
adjustment = CUSUM_ADJUSTMENTS[cusum_state]
final_multiplier = max(0.30, base_multiplier * adjustment)
```

`get_worst_cusum_state()` queries the most recent `drift_monitor` row for (symbol, setup_plugin) where `check_type = 'cusum_performance'` and `checked_at > NOW() - INTERVAL '2 hours'`. If no row (setup hasn't accumulated 20 outcomes yet), returns `"none"`.

**Multiplier floor of 0.30:** Complete suppression via `perf_multiplier = 0` would permanently starve a setup of data, making it impossible for CUSUM to detect when performance recovers. Floor at 0.30 ensures the setup keeps generating outcomes that feed the CUSUM accumulator.

**Why extend `weight_updater` and not the drift monitor service itself:** `setup_performance` is the single source of truth for `perf_multiplier`. Having two separate writers to the same field creates race conditions and makes the system harder to reason about. `weight_updater` already owns this table — CUSUM adjustment is a natural extension of its existing responsibility.

**Decision rationale on automatic reduction:** We considered requiring human confirmation before reducing `perf_multiplier`. Rejected because: (a) the whole point is to avoid human-in-the-loop adaptation, and (b) the floor (0.30) and manual reset mechanism bound the downside of a false positive. A false CUSUM positive reduces a healthy setup's weight by 30–60% for one day until the next `weight_updater` run sees the CUSUM has reset. That's a bounded, recoverable cost. The alternative — missing a genuine degradation — is unbounded.

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
    cusum_pos       FLOAT,          -- S+ statistic; persisted for restart bootstrap
    cusum_neg       FLOAT,          -- S- statistic; persisted for restart bootstrap
    cusum_threshold FLOAT,          -- h × σ₀ (warning threshold)
    baseline_mean   FLOAT,          -- μ₀
    baseline_std    FLOAT,          -- σ₀
    total_outcomes  INTEGER,

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

Hypertable (not plain table): consistent with all other time-series tables, avoids unbounded row growth. No retention policy — every alert is a labeled event in system history.

---

## Prometheus Metrics

Port `:9118`. **Registration pattern:** All drift metrics use labels, so they must be created as module-level constants using `prometheus_client.Counter` / `Gauge` / `Histogram` directly — **not** through the `metrics.counter()` / `metrics.gauge()` helpers in `src/observability/metrics.py`, which do not accept `labelnames`. Follow the same pattern as `PLUGIN_EXECUTION_TOTAL` in `metrics.py`.

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `drift_ks_pvalue` | Gauge | `symbol, timeframe, feature` | Most recent KS p-value (lower = more drift) |
| `drift_ks_statistic` | Gauge | `symbol, timeframe, feature` | Most recent KS statistic (0–1) |
| `drift_ks_alert_total` | Counter | `symbol, timeframe, feature, severity` | Cumulative KS alerts fired |
| `drift_ks_confidence_penalty` | Gauge | `symbol, timeframe` | Active CIS confidence multiplier (1.0 / 0.85 / 0.70) |
| `drift_cusum_neg` | Gauge | `symbol, setup_plugin` | Current S- statistic |
| `drift_cusum_pos` | Gauge | `symbol, setup_plugin` | Current S+ statistic |
| `drift_cusum_threshold` | Gauge | `symbol, setup_plugin` | Warning threshold (h × σ₀) |
| `drift_cusum_alert_total` | Counter | `symbol, setup_plugin, severity` | Cumulative CUSUM alerts fired |
| `drift_cusum_perf_adjustment` | Gauge | `symbol, setup_plugin` | Active perf_multiplier adjustment factor (1.0 / 0.70 / 0.40) |
| `drift_monitor_check_duration_seconds` | Histogram | `check_type` | Time to complete one full check cycle |

Grafana alert rules:
- `drift_ks_pvalue < 0.05` (filtered by `drift_ks_statistic > 0.10`)
- `drift_cusum_neg > drift_cusum_threshold`
- `drift_ks_confidence_penalty < 1.0` (active CIS penalty in effect)
- `drift_cusum_perf_adjustment < 1.0` (active perf reduction in effect)

---

## API Endpoint

New file: `src/api/routes/drift.py`. Register in `src/api/main.py` alongside `signals.py`, `features.py`, etc.

```
GET /api/drift
```

Returns current active alerts (most recent row per symbol/feature/setup with `alert_triggered = TRUE`).

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
      "confidence_penalty_active": 0.85,
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
      "perf_adjustment_active": 0.70,
      "checked_at": "2026-03-11T13:00:00Z"
    }
  ]
}
```

---

## Service Deployment

### `services/drift_monitor_service.py`

```python
async def main():
    ks_monitor = KSDriftMonitor(db, redis, settings)
    cusum_monitor = CUSUMMonitor(db, settings)
    await asyncio.gather(
        ks_monitor.run_forever(interval_seconds=4 * 3600),
        cusum_monitor.run_forever(interval_seconds=3600),
    )
```

### `services/indicagent-drift-monitor.service`

```ini
[Unit]
Description=IndicAgent Drift Monitor — KS + CUSUM drift detection with automated pipeline feedback
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

---

## Implementation Plan Inputs

### Files to create

| File | Purpose |
|------|---------|
| `production/migrations/026_drift_monitor.sql` | `drift_monitor` hypertable + indexes |
| `services/drift_monitor_service.py` | Service entrypoint + main loop |
| `src/monitoring/__init__.py` | Module init |
| `src/monitoring/ks_drift_monitor.py` | KS monitor class + Redis publish |
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
| `src/core/stream_keys.py` | Add `drift_ks(symbol, tf) -> str` key constructor |
| `src/intelligence/weight_updater.py` | Read CUSUM state from `drift_monitor`; apply adjustment to `perf_multiplier` |
| `services/signal_generator_service.py` | Read `drift:ks:{symbol}:{tf}` in `_build_all_ranked()`; apply `drift_confidence_penalty` to CIS score |
| `src/api/main.py` | Register `drift` router |

### Dependencies

- `scipy` — already in use (GARCH/Kalman) — no new dependencies
- `asyncpg` — already used by all services
- `prometheus_client` — already used; drift metrics registered directly (not via `metrics.py` helpers)

### Migration order

026 must run before the service starts. No dependency on other pending migrations.

---

## Parameter Summary (All Starting Values — Tune Empirically)

| Parameter | Value | Notes |
|-----------|-------|-------|
| KS reference window | 29 days (NOW−37d to NOW−8d) | Sliding; self-correcting |
| KS current window | 7 days (NOW−7d to NOW) | |
| KS p-value threshold | 0.05 | Standard significance |
| KS effect size threshold | 0.10 | Minimum ks_statistic for alert |
| KS min sample | 50 bars | Guard for short-history TFs |
| KS warning penalty | 0.85 | 15% CIS score reduction |
| KS critical penalty | 0.70 | 30% CIS score reduction |
| KS cache TTL | 8h | 2× check interval |
| CUSUM k (allowance) | 0.5 σ | Min detectable shift |
| CUSUM h (threshold) | 4.0 σ | Warning trigger |
| CUSUM h\_critical | 8.0 σ | Critical trigger |
| CUSUM min outcomes | 20 | Before monitoring begins |
| CUSUM warning adjustment | 0.70 | 30% perf\_multiplier reduction |
| CUSUM critical adjustment | 0.40 | 60% perf\_multiplier reduction |
| CUSUM multiplier floor | 0.30 | Prevents complete suppression |

---

## What's Deferred

| Item | Why deferred |
|------|-------------|
| Chi-squared tests for categorical features | Continuous KS features capture the same structural shifts; add once value is empirically demonstrated |
| Feature-level CIS penalty granularity | Requires setup→feature dependency mapping; coarser symbol/TF-level penalty is safer and easier to maintain |
| Automatic CUSUM reset | Requires human investigation before re-baselining; auto-reset would mask recurring degradation |
| Dashboard drift panel UI | Depends on `GET /api/drift`; deferred to dashboard completion phase |
| Per-TF CUSUM | Most setups lack 20 resolved outcomes per TF yet; add after 3+ months of signal history |

---

## Success Criteria

1. `drift_monitor` table populated every 4h (KS) and every 1h (CUSUM) for all active contracts.
2. KS `warning` alert fires in unit tests when `reference = Normal(0,1)` and `current = Normal(1.5,1)` with N=200.
3. `drift:ks:ES:1m` Redis key is written after KS check cycle; value is `"warning"` when any feature exceeds alert threshold.
4. `signal_generator_service._build_all_ranked()` applies 0.85 multiplier to CIS scores when `drift:ks:ES:1m = "warning"`.
5. CUSUM fires `warning` in unit tests on a pnl_r series: μ₀=0.3 baseline for 20 samples, then −0.5 for 30 more.
6. `weight_updater` writes reduced `perf_multiplier` (0.70× base) for a setup with active CUSUM `warning` in `drift_monitor`.
7. CUSUM bootstraps from DB on restart: a monitor started with prior `cusum_neg=3.5` continues from 3.5, not from 0.
8. `GET /api/drift` returns correct alert data including active penalties; returns empty arrays when no alerts.
9. Prometheus metrics visible at `:9118` between check cycles.
10. Service survives DB connection failure — logs ERROR, sleeps, retries. Does not crash.
