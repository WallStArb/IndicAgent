# 132-A2 Measurement: stopped_at_entry Rate on Fresh 2-Week Sample

**Measured:** 2026-06-18
**Status:** A2 GAP — stopped_at_entry rate is 44.7% of stop-type exits (threshold: < 5%)

---

## 1. Exit Reason Distribution (trade_executions)

Query run after lifecycle_replay on symbols QQQ, ESM6, NGN6, GBPUSD for ts >= 2026-06-03:

```
exit_reason          | cnt  | pct_of_all | stopped_pct_of_stop_exits
---------------------+------+------------+--------------------------
stop_loss            | 9356 |      48.01 |                      0.00
ttl_expired          | 3783 |      19.41 |
ttl_expired_ahead    | 3534 |      18.14 |
target_1             | 1736 |       8.91 |
ttl_expired_behind   | 1078 |       5.53 |
```

**Note:** `stopped_at_entry` does NOT appear as an exit_reason in trade_executions. The current
lifecycle_replay.py writes all zone-track stop exits with exit_reason = `"stop_loss"` (from
`z_trans.exit_reason` at lifecycle_replay.py:779). The STOPPED_AT_ENTRY classification is an
outcome enum used only in the replay log, not persisted to trade_executions.exit_reason.

The correct A2 metric is therefore the **STOPPED_AT_ENTRY outcome classification** from
lifecycle_replay logs, which measures stops hit within <= 2 bars or with MFE <= 0.05R.

---

## 2. stopped_at_entry Percentage (from lifecycle_replay outcome logs)

### Raw counts per (symbol, timeframe)

| Symbol | TF | STOPPED_AT_ENTRY | STOPPED_IN_TRADE | total_stop | pct_at_entry |
|--------|----|-----------------|-----------------|------------|-------------|
| QQQ | 1m | 269 | 405 | 674 | 39.9% |
| QQQ | 5m | 130 | 229 | 359 | 36.2% |
| QQQ | 15m | 38 | 73 | 111 | 34.2% |
| QQQ | 1h | 9 | 9 | 18 | 50.0% |
| GBPUSD | 1m | 2283 | 1649 | 3932 | 58.1% |
| GBPUSD | 5m | 374 | 277 | 651 | 57.5% |
| GBPUSD | 15m | 184 | 113 | 297 | 61.9% |
| GBPUSD | 1h | 16 | 23 | 39 | 41.0% |
| ESM6 | 1m | 1084 | 1842 | 2926 | 37.1% |
| ESM6 | 5m | 150 | 286 | 436 | 34.4% |
| ESM6 | 15m | 54 | 82 | 136 | 39.7% |
| ESM6 | 1h | 28 | 29 | 57 | 49.1% |
| NGN6 | 1m | 489 | 1138 | 1627 | 30.1% |
| NGN6 | 5m | 149 | 286 | 435 | 34.3% |
| NGN6 | 15m | 65 | 132 | 197 | 33.0% |
| NGN6 | 1h | 22 | 35 | 57 | 38.6% |

### Aggregated totals

| Symbol | STOPPED_AT_ENTRY | STOPPED_IN_TRADE | stop_exits | pct_at_entry |
|--------|-----------------|-----------------|------------|-------------|
| QQQ | 446 | 716 | 1162 | 38.4% |
| GBPUSD | 2857 | 2062 | 4919 | 58.1% |
| ESM6 | 1316 | 2239 | 3555 | 37.0% |
| NGN6 | 725 | 1591 | 2316 | 31.3% |
| **ALL** | **5344** | **6608** | **11952** | **44.7%** |

**stopped_pct_of_stop_exits: 44.7%**

**A2 threshold: < 5%**

**A2 disposition: GAP** — 44.7% >> 5% threshold

---

## 3. A2 Disposition: GAP

The Phase 126 zone width rejection gate (trade_framer.py:1052-1077) and stop distance floor
(trade_framer.py:1095-1110) are working — they rejected narrow zones and too-close stops.
However, a large fraction of stop exits still happen at or near the entry price.

**Root cause analysis:**

The `_classify_stop_outcome()` function in lifecycle_tracker.py classifies a stop as
STOPPED_AT_ENTRY when ANY of these is true:
1. `bars_in_trade_count is None` — stop before zone was activated
2. `bars_in_trade_count <= 2` — stopped within 2 bars of activation
3. `current_mfe <= 0.05` — MFE never exceeded 0.05R (trade went nowhere before stopping)

Condition 3 is a broad catch-all: any stop where the signal never showed more than 5% of risk
as favorable excursion is classified as "stopped at entry." This captures many poor-quality
entries, not just geometric bugs where stop < zone_low.

**Identified zone_source gap:**

`context_features->>'zone_source'` is NULL for all signals in the sample. The
`features["zone_source"]` assigned at trade_framer.py:1050 is not persisted to the
`context_features` JSONB column in signal_events. This prevents per-path breakdown.

**Offending paths requiring investigation (Plan 02):**

1. **GBPUSD at 58.1%** — highest rate across all symbols. FX has tight spreads and
   frequent whipsaws. The current universal `MIN_STOP_ATR_MULTIPLIER = 1.0 ATR` may be
   insufficient for FX. The A3 per-asset-class floor key
   `feature.trade_framer.stop_multiplier_floor.fx` (seed: 1.0 ATR) may need a higher
   seed value for FX.

2. **1h timeframe: 49.1% (ESM6), 50.0% (QQQ)** — higher rate at longer timeframes
   suggests the stop distance floor in ATR terms is still too close when measured at
   coarser timeframes where single-bar moves are larger.

3. **MFE <= 0.05 condition** in `_classify_stop_outcome()` — this condition classifies
   any stop where the trade never showed movement as STOPPED_AT_ENTRY. This may be too
   broad a net. Separate from geometry, this is a signal quality issue.

**Scope of remaining work (Plan 02):**

The A5 APR migration (Plan 02) raises `MIN_STOP_ATR_MULTIPLIER` from 1.0 ATR to an
APR-backed `feature.trade_framer.min_stop_atr`. This is the primary mechanism available
within Plan 02. The per-asset-class A3 keys provide a pathway to tune per-class floors.

A full resolution may require:
- Persisting `zone_source` to context_features to enable per-path measurement
- Tuning the FX stop multiplier floor upward from 1.0 ATR
- Review of the `current_mfe <= 0.05` condition in `_classify_stop_outcome()`

These are deferred to Plan 02/03 and future phases.

---

## 4. zone_engine Audit: No Frame Construction Bypass

**Audit finding:** zone_engine.py contains NO TradeFrame construction, no call to
`frame_trade()`, and no call to `make_signal_from_frame()`.

Verification command:
```bash
grep -n "TradeFrame\|frame_trade\|make_signal_from_frame" src/intelligence/trading/zone_engine.py
# Returns: (no output) -- zero results
```

**Call chain confirmed:**
- `resolve_structural_zone()` is the only public function in zone_engine.py
- It returns a `ZoneResult` object (not a TradeFrame)
- The sole caller is `trade_framer.py:448`: `result = resolve_structural_zone(...)`
- trade_framer's zone width gate at line 1059 is applied AFTER `resolve_structural_zone` returns
- ALL zone paths (supply_demand, fvg, ob, structural engine, sweep band, ATR fallback) pass
  through the same gate at line 1059

**`_expand_to_min_width()` uses different threshold (0.25 ATR vs 1.5 ATR):**

zone_engine's internal `_expand_to_min_width()` at line 398 uses `feature.zone_engine.min_width_atr`
(current APR value: 0.25 ATR). This is intentionally smaller than trade_framer's rejection
threshold `feature.zone_engine.min_zone_width_atr` (1.5 ATR). zone_engine does not know
trade_framer's threshold. A zone can be returned with width in range [0.25 ATR, 1.5 ATR);
trade_framer's gate at line 1059 rejects these. This is by design.

**Conclusion:** No bypass exists in zone_engine. The zone width gate in trade_framer.py:1059
is the sole and sufficient rejection point.

---

## 5. Reproduction Commands

### Step 1: Resolve front-month contracts
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT base_symbol, symbol FROM contract_metadata WHERE base_symbol IN ('ES','NG') AND is_front_month=true ORDER BY base_symbol;"
# Result: ES -> ESU6 (no bar data), NG -> NGN6
# Substituted ESM6 (has bar data in window) for ESU6
```

**Note on ES contract:** ESU6 is the metadata front-month but has no bar data in the 14-day
window. ESM6 has data through 2026-06-18. Used ESM6 + `--include-rolled` flag.

### Step 2: Confirm bar coverage
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c \
  "SELECT symbol, COUNT(*) FROM market_data_ohlcv WHERE symbol IN ('QQQ','ESM6','NGN6','GBPUSD') AND timestamp >= '2026-06-03T00:00:00Z' GROUP BY symbol ORDER BY symbol;"
# QQQ: 10140, ESM6: 15753, NGN6: 15611, GBPUSD: 16219
```

### Step 3: Run fresh sample replay (2-week window)
```bash
cd /home/bg/dev/indicagent && .venv/bin/python \
  production/scripts/run_historical_pipeline.py \
  --replay-only --clean --setups ALL --days 14 \
  --symbols QQQ,ESM6,NGN6,GBPUSD --include-rolled --client-id 40
# Output: 14,432 total signals inserted
```

### Step 4: Run lifecycle_replay on same symbols
```bash
cd /home/bg/dev/indicagent && .venv/bin/python -u \
  production/scripts/lifecycle_replay.py \
  --reset --reset-after 2026-06-03T00:00:00Z --confirm \
  --symbols QQQ,ESM6,NGN6,GBPUSD --workers 8 --force
# Output: 13,049 total signals processed; VERIFY all checks passed
```

### Step 5: Measure exit_reason distribution (DB query)
```sql
SELECT exit_reason, COUNT(*) AS cnt,
       ROUND(COUNT(*)*100.0/SUM(COUNT(*)) OVER (), 2) AS pct_of_all,
       ROUND(COUNT(*) FILTER (WHERE exit_reason='stopped_at_entry') * 100.0
             / NULLIF(COUNT(*) FILTER (WHERE exit_reason IN ('stop_loss','stopped_at_entry')), 0), 2)
             AS stopped_pct_of_stop_exits
FROM trade_executions te
JOIN trade_frames tf ON te.frame_id = tf.frame_id
JOIN signal_events se ON tf.signal_id = se.signal_id
WHERE se.symbol IN ('QQQ','ESM6','NGN6','GBPUSD')
  AND se.ts >= '2026-06-03T00:00:00Z'
GROUP BY 1 ORDER BY 2 DESC;
-- stopped_at_entry does not appear: all zone stops written with exit_reason='stop_loss'
-- Use lifecycle_replay log output (STOPPED_AT_ENTRY outcome classification) instead
```

---

## Auto-fixes Applied During Measurement

### Fix 1 (Rule 1 - Bug): run_historical_pipeline.py full-symbol clean path FK violation

The `--setups ALL` clean path deleted `trade_frames` before `trade_executions`, violating the
FK constraint `fk_trade_executions_frame`. Fixed deletion order:
`trade_executions -> trade_frames -> signal_events`.

File: `production/scripts/run_historical_pipeline.py`
Lines affected: ~2560-2607 (else branch of full-symbol clean)

### Fix 2 (Rule 1 - Bug): lifecycle_replay.py NoneType.isoformat crash

`_reset_corrupt_data()` log message called `before.isoformat()` when `--reset-before` was
not provided (before=None). Fixed to use conditional: `before.isoformat() if before is not None else "unbounded"`.

File: `production/scripts/lifecycle_replay.py`
Lines affected: ~351-352

---

*Measured: 2026-06-18*
*Phase: 132-stop-zone-geometry-apr-migration*
*Plan: 132-01*
