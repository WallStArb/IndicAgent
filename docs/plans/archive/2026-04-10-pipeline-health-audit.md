---
title: Pipeline Health Audit — 2026-04-10
status: Active
priority: P0
scope: Full pipeline health from IBKR ingestion through signal lifecycle resolution
---

# Pipeline Health Audit — 2026-04-10

**Last Updated:** 2026-05-02

Full-stack health check from 1m bar ingestion → HTF aggregation → intelligence pipeline → signal generation → lifecycle resolution.

## Executive Summary

**26/26 services running.** All consumer groups stable. HTF aggregation, feature writing, and signal writing are healthy. Three critical blockers prevent the system from operating at full fidelity:

1. TimescaleDB decompression limit blocks signal lifecycle for 3 futures symbols
2. 515K signals sit in `pending` — crypto signals have **zero** activations/resolutions
3. Intelligence pipeline 67K bar lag delays equity ETF features by ~1 day

---

## Service Status

All services `active (running)`:
- `indicagent-ibkr-provider` — connected to TWS, publishing bars
- `indicagent-bar-aggregator-compute` — 1m→HTF aggregation, **0 lag**
- `indicagent-intelligence-pipeline` — I1-I7 unified, **67K lag on market.bars**
- `indicagent-feature-writer` — intelligence.journal → TimescaleDB, **8 lag**
- `indicagent-signal-writer` — i7.signals → signal_ledger, **6 lag**
- `indicagent-signal-tracker` — lifecycle tracking, **258K lag, BLOCKED**
- `indicant-ai-narrative` — I8 LLM analysis, running
- `indicagent-api` — FastAPI + SSE, running
- Timer-based (inactive/dead as expected): `redpanda-watchdog`, `weight-updater`

---

## Consumer Lag Summary

| Consumer Group | Topic | Lag | Status |
|---|---|---|---|
| `bar_aggregator_consumer` | `market.bars` | 0 | **Healthy** |
| `intelligence_pipeline_group` | `market.bars` | 67,657 | **Behind** |
| `intelligence_pipeline_group` | `market.bars.htf` | 0 | **Healthy** |
| `signal_lifecycle` | `market.bars` | 199,959 | **Critical** |
| `signal_lifecycle` | `market.bars.htf` | 58,134 | **Critical** |
| `feature_writer_group` | `intelligence.journal` | 8 | **Healthy** |
| `signal_writer_group` | `intelligence.i7.signals` | 6 | **Healthy** |

**Topic offsets** (`market.bars` partition 0):
- Log start: 1,900,229
- Log end: 2,914,136
- Total messages in topic: ~1,013,907

---

## Critical Issues

### CRITICAL-1: TimescaleDB Decompression Limit Blocks Signal Tracker

**Severity**: P0 — root cause of signal lifecycle failure
**Symptom**: Signal tracker throws `tuple decompression limit exceeded` on every bar for NQM6, RTYM6, ESM6
**Error count**: 1,635 and growing
**Affected symbols**: NQM6 (827 errors), RTYM6 (766), ESM6 (34)

**Root cause**:
- `signal_ledger` has 3,715,199 rows across 3 chunks
- Chunk `_hyper_13_52537_chunk` is compressed (`is_compressed = true`)
- `timescaledb.max_tuples_decompressed_per_dml_transaction = 100,000` (default)
- Each UPDATE to signal_ledger decompresses up to 268,996 tuples (exceeds limit)
- The tracker's UPDATE queries for NQM6/RTYM6/ESM6 hit the compressed chunk repeatedly

**Fix options** (ordered by speed):
1. **Immediate**: `ALTER SYSTEM SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0;` then `SELECT pg_reload_conf();`
2. **Alternative**: Decompress the affected chunk: `SELECT decompress_chunk('_timescaledb_internal._hyper_13_52537_chunk');`
3. **Long-term**: Disable compression on signal_ledger (it's write-heavy, compression is better for read-heavy hypertables), or increase chunk interval to reduce per-update decompression volume

**Verification**: After fix, `signal_tracker_agent.log` should show zero new decompression errors, and `signal_lifecycle` lag should start decreasing.

---

### CRITICAL-2: 515K Signals Stuck at Pending — Crypto Zero Resolutions

**Severity**: P0 — signals never activate or resolve
**Symptom**: BTCUSD/ETHUSD have tens of thousands of pending signals, zero active, zero resolved

**Data**:
| Symbol | Pending | Expired (TTL) | Active | Resolved |
|---|---|---|---|---|
| BTCUSD | 58,099 | 175,963 | 0 | 0 |
| ETHUSD | 63,523 | 194,449 | 0 | 0 |

**Root cause chain**:
1. Signal tracker consumes `market.bars` to evaluate signal lifecycle (TP/SL hits)
2. Tracker has 258K lag → can't process bars fast enough
3. Decompression errors (CRITICAL-1) cause it to skip bars for NQM6/RTYM6/ESM6
4. For crypto, the tracker simply hasn't consumed the bars needed to evaluate pending signals
5. Signals expire via TTL (`exit_reason: ttl_expired`, `outcome: never_activated`) instead of being properly evaluated

**Fix**: Resolving CRITICAL-1 is the prerequisite. Once the tracker can process bars without errors, the 258K lag should drain over hours. Crypto signals will begin transitioning properly.

**Pending signal age**:
- Pre-restart (before Apr 7): 135,901
- Post-restart (Apr 7+): 379,448

Old pending signals from pre-restart may be orphaned — consider a one-time UPDATE to expire them if the tracker can't catch up within topic retention (7 days).

---

### CRITICAL-3: Intelligence Pipeline 67K Bar Lag

**Severity**: P1 — equity ETF features delayed ~1 day
**Symptom**: Equity ETFs have `intelligence_features` only through Apr 8 19:59, while OHLCV has Apr 9 data

**Data** (`intelligence_features` last 1m bar):
| Category | Symbols | Latest 1m in features | Latest 1m in OHLCV | Gap |
|---|---|---|---|---|
| Futures | CLK6, ESM6, NQM6 | Apr 10 04:02 | Apr 10 04:02 | None |
| Crypto | BTCUSD, ETHUSD | Apr 09 03:59 | Apr 10 03:59 | ~24h |
| FX | EURUSD, GBPUSD | Apr 10 04:01 | Apr 10 04:01 | None |
| Equities | SPY, QQQ, IWM | Apr 08 19:59 | Apr 09 19:59 | ~24h |

**Root cause**:
- Pipeline processes ~1 bar/second sequentially (I1-I7 in-process, I2-I6 sequential)
- 50+ symbols × 1m bars = ~50 bars/minute input rate
- At ~1 bar/sec processing, the pipeline is barely keeping up during active hours
- Historical catchup from Apr 7 startup adds accumulated lag
- Pipeline IS processing (logs confirm perf_weights loading every hour, hmm warnings active)

**Fix options**:
1. **Short-term**: Let it catch up — lag should drain during low-activity periods (overnight/weekends)
2. **Medium-term**: Pipeline throughput optimization (wave parallelization, see `memory/pipeline_optimization_plan.md`)
3. **Long-term**: I2-I6 tier parallelization (currently sequential, biggest bottleneck)

---

## Non-Critical Issues

### NC-1: HMM Regime Fallback Warnings

**Severity**: P3 — graceful degradation
**Symptom**: `smc_context.hmm_regime` logs `hmm_fallback_2d` due to missing `macd_histogram_12_26_9`
**Impact**: HMM regime classification falls back to 2D mode (uses fewer features), slightly less accurate regime detection
**Fix**: Investigate why I3 MACD histogram isn't in the feature vector when I4 SMC HMM runs. Possible tier ordering issue — I4 may run before I3 MACD is computed for warmup bars.

### NC-2: IBKR Provider Log Noise

**Severity**: P4 — cosmetic
**Symptom**: IBKR provider log filled with `updatePortfolio` for ASMB stock (position held in account)
**Impact**: Log bloat, makes it hard to find actual bar publishing activity
**Fix**: Filter portfolio updates to a separate log, or suppress for non-tracked symbols

---

## Data Coverage

### System start: ~2026-04-07 11:51 UTC (live-only, no historical backfill)

### intelligence_features bar counts (last 3 days):

**Futures** (24h trading, all TFs current):
- CLK6: 3,631 1m / 243 15m / 62 1h / 17 4h / 3 1d
- ESM6: 3,631 1m / 243 15m / 62 1h / 17 4h / 3 1d
- NQM6: 3,631 1m / 243 15m / 62 1h / 17 4h / 3 1d

**Crypto** (24h, ~1 day behind in features):
- BTCUSD: 2,407 1m / 255 15m / 63 1h / 15 4h / 2 1d
- ETHUSD: 2,407 1m / 255 15m / 63 1h / 15 4h / 2 1d

**FX** (24h, current):
- EURUSD: 2,407 1m / 254 15m / 65 1h / 17 4h / 3 1d
- GBPUSD: 2,407 1m / 254 15m / 65 1h / 17 4h / 3 1d

**Equities** (RTH only, 1 day behind):
- SPY: 1,159 1m / 101 15m / 26 1h / 1 1d
- QQQ: 1,158 1m / 101 15m / 26 1h / 1 1d

### signal_ledger (last 3 days):

| Category | Symbols | Total Signals | Active | Pending | Resolved |
|---|---|---|---|---|---|
| Futures | ESM6 | 24,842 | 0 | 8,786 | 16,056 |
| Futures | NQM6 | 24,864 | 3 | 6,220 | 18,641 |
| Crypto | BTCUSD | 13,095 | 0 | 13,095 | 0 |
| Crypto | ETHUSD | 13,527 | 0 | 13,527 | 0 |
| FX | EURUSD | 14,104 | 0 | 8,835 | 5,269 |
| Equities | SPY | 7,546 | 76 | 1,807 | 5,663 |

**Total rows**: 3,715,199

---

## HTF Aggregation Verification

**Working correctly.** 1m → 5m/15m/1h/4h/1d all populated via BarAccumulator.

- Bar aggregator: **0 lag** on `market.bars`
- 1h bar emission: 24/day per symbol (futures), 6-7/day (equities RTH)
- 4h bar emission: 6/day (futures), 1-2/day (equities)
- 1d bar emission: 1/day per symbol
- Session break logic prevents cross-session contamination

**No backfill** — only live bars since Apr 7. HTF views build incrementally from live data only.

---

## Parallelism Status

| Component | Parallelism | Notes |
|---|---|---|
| I1 tier (27 plugins) | Parallel (asyncio.gather + ThreadPoolExecutor) | Working |
| I2-I6 tiers | Sequential | Bottleneck acknowledged |
| I7 tier (36 plugins) | Parallel | Working |
| Feature writer | Independent consumer | Near-zero lag |
| Signal writer | Independent consumer | Near-zero lag |
| Bar aggregator | Independent consumer | Zero lag |
| Signal tracker | Independent consumer | Blocked (decompression) |
| Cross-asset | Independent consumer | Stable |

---

## Self-Healing Assessment

| Mechanism | Status | Notes |
|---|---|---|
| Service restarts (systemd) | Working | `Restart=always`, `RestartSec=10` |
| Consumer group idempotency | Working | Safe to restart any consumer |
| Pipeline lag self-correction | Partial | Slowly draining but can't keep up during peak |
| Decompression limit | **NOT self-healing** | Persistent config issue |
| Historical backfill | **Not automatic** | Requires manual script |
| Signal TTL expiry | Working | Signals expire to `never_activated` but never properly evaluated |

---

## Fix Priority Order

### Phase 1: Unblock (immediate, ~5 minutes)

| # | Fix | Command | Impact |
|---|---|---|---|
| 1.1 | Increase TimescaleDB decompression limit | See CRITICAL-1 | Unblocks signal tracker for NQM6/RTYM6/ESM6 |
| 1.2 | Restart signal tracker after config change | `sudo systemctl restart indicagent-signal-tracker` | Clears error state, starts draining 258K lag |
| 1.3 | Verify decompression errors stop | `grep -c "tuple decompression" logs/signal_tracker_agent.log` | Confirm fix |

### Phase 2: Monitor lag drain (1-4 hours after Phase 1)

| # | Task | Verification |
|---|---|---|
| 2.1 | Monitor signal_lifecycle lag decreasing | `rpk group describe signal_lifecycle -t` |
| 2.2 | Monitor intelligence_pipeline lag | `rpk group describe intelligence_pipeline_group -t` |
| 2.3 | Watch for crypto signal activations | `SELECT COUNT(*) FROM signal_ledger WHERE symbol='BTCUSD' AND status='active'` |
| 2.4 | Confirm equity features catch up | Check SPY 1m latest in `intelligence_features` |

### Phase 3: One-time cleanup (after lag stabilizes)

| # | Task | Detail |
|---|---|---|
| 3.1 | Expire orphaned pre-restart pending signals | 135K signals from before Apr 7 that may never be evaluated |
| 3.2 | Historical backfill for equity ETFs | `python production/scripts/historical_backfill.py --fetch-only --symbols SPY,QQQ,IWM,...` |
| 3.3 | Consider backfill for pre-Apr 7 futures/crypto | To get full 1440-bar warmup for indicators |

### Phase 4: Investigate (when pipeline stable)

| # | Task |
|---|---|
| 4.1 | HMM fallback: why is `macd_histogram_12_26_9` missing at I4 runtime? |
| 4.2 | Pipeline throughput: I2-I6 sequential bottleneck analysis |
| 4.3 | Signal_ledger compression policy: should it be disabled for write-heavy workload? |
| 4.4 | IBKR provider log noise: filter portfolio updates for non-tracked symbols |

---

## Commands Reference

```bash
# Check lag
docker exec redpanda rpk group describe signal_lifecycle -t
docker exec redpanda rpk group describe intelligence_pipeline_group -t

# Fix decompression (Phase 1.1)
docker exec timescaledb psql -U postgres -d indicagent -c \
  "ALTER SYSTEM SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0;"
docker exec timescaledb psql -U postgres -d indicagent -c "SELECT pg_reload_conf();"

# Restart tracker (Phase 1.2)
sudo systemctl restart indicagent-signal-tracker

# Verify (Phase 1.3)
tail -f logs/signal_tracker_agent.log | grep -i "decompression"

# Check signal status
docker exec timescaledb psql -U postgres -d indicagent -c "
SELECT symbol, status, COUNT(*) FROM signal_ledger
WHERE feature_ts > NOW() - INTERVAL '1 day'
GROUP BY symbol, status ORDER BY symbol, status;"

# Check feature freshness
docker exec timescaledb psql -U postgres -d indicagent -c "
SELECT symbol, tf, MAX(ts) as latest FROM intelligence_features
WHERE symbol IN ('SPY','CLK6','BTCUSD','EURUSD')
GROUP BY symbol, tf ORDER BY symbol, tf;"
```

---

## Audit Data Collected

- Full service status dump
- All consumer group lag (18 groups)
- `intelligence_features` coverage: 326 rows (61 symbols × ~6 TFs)
- `signal_ledger` status distribution: 61 symbols
- `market_data_ohlcv` coverage since Apr 9
- `signal_tracker_agent.log` error analysis: 1,635 decompression errors
- `signal_ledger` chunk compression: 3 chunks, 1 compressed
- `signal_ledger` total: 3,715,199 rows, 104 KB compressed
- `market.bars` topic: 1,013,907 messages, 7-day retention
