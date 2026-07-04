# Backfill Regeneration Monitoring Guide

**Status:** archived
**Run Date:** 2026-06-07
**Completed:** 2026-06-07
**Purpose:** Operational monitoring guide for a specific backfill run

---

## Historical Summary

This document was operational monitoring for a backfill regeneration run. The run
has completed. This document is preserved for historical reference only.

**Run Details:**
- Started: 2026-06-07 16:29 EDT
- Process ID: 2483538
- Expected runtime: ~48 hours
- Target signals: 7.43M ±5%
- Actual signals: ~7.7M (final count)

---

---

## Quick Status Check

```bash
# Process health
ps aux | grep 2483538 | grep -v grep

# Recent logs
tail -f logs/backfill_restart.log

# Zone correction count (should increase over time)
grep "stop_inside_zone_corrected" logs/backfill_restart.log | wc -l

# Current signal count in DB
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "
SELECT COUNT(*) FROM signal_ledger WHERE is_backfill = TRUE;
"
```

---

## Progress Tracking

### Every 1 hour, check:

1. **Process still running?**
   ```bash
   ps aux | grep 2483538 | grep -v grep
   ```

2. **Signal count progress**
   ```bash
   PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -t -c "
   SELECT COUNT(*) FROM signal_ledger WHERE is_backfill = TRUE;
   "
   ```
   Expected: Should increase by ~150K per hour (7.43M / 48h)

3. **Zone corrections active?**
   ```bash
   grep "stop_inside_zone_corrected" logs/backfill_restart.log | wc -l
   ```
   Expected: Should be > 0 and increasing

4. **No errors?**
   ```bash
   grep -E "error|exception|fail" logs/backfill_restart.log | tail -10
   ```
   Expected: Should be empty

---

## Completion Verification

When signal count reaches 7.0M - 7.8M range:

### 1. Final counts
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT 
  COUNT(*) FILTER (WHERE is_backfill = TRUE) as backfill_count,
  COUNT(*) FILTER (WHERE is_backfill = FALSE) as live_count,
  COUNT(*) as total_count
FROM signal_ledger;
"
```

Target: backfill_count between 7.05M - 7.80M

### 2. Verify zero stopped_at_entry
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT outcome, COUNT(*) as count
FROM signal_outcomes
WHERE signal_id IN (
  SELECT signal_id FROM signal_ledger WHERE is_backfill = TRUE
)
GROUP BY outcome
ORDER BY count DESC;
"
```

Expected: No "stopped_at_entry" outcomes in NEW signals

### 3. Sample zone-corrected signals
```bash
grep "stop_inside_zone_corrected" logs/backfill_restart.log | head -5
```

Expected: Multiple examples of stops being corrected

---

## Troubleshooting

### Process died
```bash
# Check exit status
tail -20 logs/backfill_restart.log

# Restart
nohup .venv/bin/python production/scripts/historical_backfill.py --replay-only --workers 8 > logs/backfill_restart.log 2>&1 &
```

### Signal count stalled
```bash
# Check for errors
grep -E "error|exception" logs/backfill_restart.log | tail -20

# Check database connections
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT count(*) FROM signal_ledger;"
```

### High memory/CPU
```bash
# Check process stats
ps aux | grep backfill

# If needed, restart with fewer workers
# (kills current process first)
kill 2483538
nohup .venv/bin/python production/scripts/historical_backfill.py --replay-only --workers 4 > logs/backfill_restart.log 2>&1 &
```

---

## Post-Regeneration Steps

After backfill completes:

1. **Verify lifecycle services are still stopped**
   ```bash
   systemctl status indicagent-lifecycle-writer indicagent-signal-replay
   ```
   Should show "inactive (dead)"

2. **Start lifecycle services**
   ```bash
   echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S systemctl start indicagent-signal-replay indicagent-lifecycle-writer
   ```

3. **Run lifecycle evaluation** (automatic once services start)

4. **Monitor outcomes**
   ```bash
   # Watch for lifecycle completion
   tail -f logs/signal_replay.log logs/lifecycle_writer.log
   ```

---

## Expected Timeline

| Milestone | Target | Time |
|-----------|--------|------|
| 1M signals | 7 days of data | ~6 hours |
| 3M signals | 21 days of data | ~18 hours |
| 5M signals | 35 days of data | ~30 hours |
| 7.43M signals | 2 years of data | ~48 hours |

**Current progress:** Check signal count every few hours against this table.

---

## Success Criteria

- ✓ Backfill completes without crash
- ✓ Final signal count: 7.05M - 7.80M
- ✓ Zero stopped_at_entry outcomes in NEW data
- ✓ Zone corrections logged throughout (count > 0)
- ✓ Lifecycle services restart successfully
- ✓ Lifecycle evaluation completes

