# Phase 127 Clean Replay Execution Log

**Launched:** 2026-06-16 16:59:28 UTC
**Process ID:** 1398422
**Command:**
```bash
python production/scripts/run_historical_pipeline.py \
  --replay-only \
  --warmup \
  --clean \
  --include-rolled \
  --timeframes 1m,5m,15m,1h,4h,1d \
  --workers 1
```

## Purpose

Execute a clean historical replay on the full historical corpus with the two-pass --warmup (I1-I6 cache build, then I1-I7 signal emission) on the 3-table schema.

## Pre-Replay State (Before-Snapshot)

From `phase-127-before-snapshot.json` captured at 2026-06-16 16:58:01 UTC:

```
signal_events:     1,444,231
trade_frames:       1,444,231
trade_executions:          0
cold_start_count:   1,443,231
coverage (non-cold-start): 100.00%
setups: 61
```

## Replay Configuration Rationale

| Flag | Purpose |
|------|---------|
| `--replay-only` | Skip IBKR fetch; use existing market_data_ohlcv. REQUIRED by --warmup. |
| `--warmup` | Two-pass replay: Pass 1 I1-I6 only builds per-symbol I6 cache; Pass 2 I1-I7 emits signals against warm cache. |
| `--clean` | Delete existing signal_events/trade_frames/trade_executions before replay (fresh corpus). |
| `--include-rolled` | Replay full roll-chain history (all expired contracts), not just current is_front_month. |
| `--timeframes 1m,5m,15m,1h,4h,1d` | All 6 timeframes for complete coverage. |
| `--workers 1` | MANDATORY for --warmup; script only honors --warmup in single-worker mode. |

## Warmup Markers Verification

The replay log (`phase-127-replay-log.md.raw`) must contain these markers in sequence:

1. ✓ **Pass 1 Start:** `"Running warmup pass (I1-I6 only)..."` — confirms warmup pass ACTUALLY RAN
2. ⏳ **Pass 2 Start:** `"Warmup complete. Running signal pass..."` — confirms warmup finished and signal pass started
3. ⏳ **Completion:** `"Backfill complete."` — confirms replay exited successfully

**Critical:** If the log contains `"NOTE: --warmup is only supported with --workers 1 (parallel mode skips warmup pass)"`, the warmup was SILENTLY SKIPPED and the replay FAILS.

## Progress Monitoring

As of 2026-06-16 17:01 UTC (2 minutes post-launch):
- Process is running (PID 1398422, CPU time 00:01:27)
- Warmup pass marker found in log
- `--clean` deletion in progress (signal_events dropped from 1.44M → 484K)
- Expected duration: Several hours (full corpus × all symbols × 6 TFs × single-worker two-pass)

## Post-Replay Verification Steps

Once the replay completes, run these checks:

### 1. Exit Status
```bash
# Should contain "Backfill complete." with no ERROR/Traceback
tail -100 docs/plans/phase-127-replay-log.md.raw
```

### 2. Row Counts
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT
  (SELECT COUNT(*) FROM signal_events) AS signal_events,
  (SELECT COUNT(*) FROM trade_frames) AS trade_frames,
  (SELECT COUNT(*) FROM trade_executions) AS trade_executions;
"
```

### 3. Orphan Detection (G0 Integrity)
```bash
# Orphan signal_events (should be 0)
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tAc "
SELECT COUNT(*) FROM signal_events se
WHERE NOT EXISTS (
  SELECT 1 FROM trade_frames tf
  WHERE tf.signal_id = se.signal_id
);
"

# Orphan trade_frames (should be 0)
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -tAc "
SELECT COUNT(*) FROM trade_frames tf
WHERE NOT EXISTS (
  SELECT 1 FROM signal_events se
  WHERE se.signal_id = tf.signal_id
);
"
```

### 4. Warmup Marker Verification
```bash
# Should both return matches
grep -n "Running warmup pass (I1-I6 only)" docs/plans/phase-127-replay-log.md.raw
grep -n "Warmup complete. Running signal pass" docs/plans/phase-127-replay-log.md.raw

# Should return ZERO matches (warmup was NOT skipped)
grep -c "only supported with --workers 1 (parallel mode skips warmup pass)" docs/plans/phase-127-replay-log.md.raw
```

## Expected Outcomes

### Success Criteria
- Exit code 0 (no ERROR/Traceback in log)
- signal_events, trade_frames have non-zero row counts
- Zero orphan signal_events (G0 grouping holds)
- Zero orphan trade_frames (FK integrity holds)
- Both warmup markers present (warmup pass actually ran)
- No "parallel mode skips warmup pass" NOTE present

### Known Structural Zeros
- **trade_executions count = 0**: Replay does NOT populate trade_executions (execution layer). This is EXPECTED and STRUCTURAL, not a bug. The table is for live trading or execution-simulating replay (v2.11).
- **stopped_at_entry count = 0**: Not measurable in replay (requires execution-layer data). This is a KNOWN limitation, not evidence that Phase 126 zone mechanics are working.

### Schema Targets
All queries target 3-table schema ONLY:
- `signal_events` (detection)
- `trade_frames` (hypothesis)
- `trade_executions` (execution)
- `signal_ledger` (JOIN view for legacy compatibility)

**DO NOT reference:** signal_outcomes (dropped), signal_ledger_full (renamed), signal_type/feature_tf/bucket_scores/staleness_score (dropped columns).

## Next Steps

1. Wait for replay completion (monitor process PID 1398422)
2. Run post-replay verification steps above
3. Record final row counts in this log
4. Proceed to Plan 02 (validation report generation)
