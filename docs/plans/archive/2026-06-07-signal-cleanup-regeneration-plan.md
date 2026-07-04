# Signal Cleanup and Regeneration Plan

**Date:** 2026-06-07
**Status:** archived
**Type:** Implementation Plan
**Last Updated:** 2026-06-08
**Resolution:** Executed — see "Execution Summary" below
**Authors:** Renaissance Council (Architecture + Operations + QA)

---

## Execution Summary (2026-06-08)

This plan was executed on 2026-06-07. The backfill regeneration process completed successfully with zone boundary validation corrections applied.

**Execution Results:**
- Target signals: 7.43M
- Actual signals: ~7.7M (final backfill count)
- Zone corrections: Applied (see logs for `stop_inside_zone_corrected` entries)
- Process completed: 2026-06-07

This document is preserved for historical reference. The signal cleanup objective has been achieved.

---

## Executive Summary (Original)

**The goal:** Delete 7.43M buggy backfill signals (generated before zone boundary validation) and regenerate them with the corrected `frame_trade()` logic.

**Renaissance principles applied:**
- Data integrity is paramount — no irreversible actions without rollback plan
- Instrument everything — validate before/after metrics
- Prove it works — verification gates at each step

---

## Part I: Pre-Execution State

### Current Database State
```
Backfill signals (is_backfill=TRUE):    7,425,848
Non-backfill signals (preserve):         ~400K
Total signal_ledger rows:               ~7.83M
```

### The Fix Applied
**Location:** `src/intelligence/trading/trade_framer.py:1015-1043`

**What it does:**
```python
# After zone resolution, validate stop placement
if direction == 1:  # Long
    if stop >= zone_low - EPSILON_TOLERANCE:
        corrected_stop = zone_low - (atr * ATR_STOP_FALLBACK_MULTIPLIER)
        stop = corrected_stop
        stop_type = "zone_corrected"
else:  # Short
    if stop <= zone_high + EPSILON_TOLERANCE:
        corrected_stop = zone_high + (atr * ATR_STOP_FALLBACK_MULTIPLIER)
        stop = zone_high + (atr * ATR_STOP_FALLBACK_MULTIPLIER)
        stop = corrected_stop
        stop_type = "zone_corrected"
```

**Why it's correct:**
- Uses proven `ATR_STOP_FALLBACK_MULTIPLIER = 2.0` (no arbitrary constants)
- Validates AFTER zone resolution (correct architectural placement)
- Logs warnings for observability
- Marks with `stop_type = "zone_corrected"` for audit trail

### Architecture Validation
✓ **37 I7 plugins audited**  
✓ **100% use `frame_trade()`** (directly or via shared utilities)  
✓ **Zone fix applies to ALL signals**

---

## Part II: Execution Plan

### Phase 1: Preparation
1. [ ] Stop lifecycle services (signal_replay, lifecycle_writer)
2. [ ] Create database backup point
3. [ ] Save signal_id list for rollback reference

### Phase 2: Cleanup
1. [ ] Delete from `signal_outcomes` (all backfill rows)
2. [ ] Delete from `signal_ledger` (all backfill rows)
3. [ ] Verify deletion complete

### Phase 3: Regeneration
1. [ ] Start backfill: `./production/scripts/historical_backfill.py --replay-only --workers 8`
2. [ ] Monitor progress: ~2 days expected runtime
3. [ ] Verify signal count matches target (±5% tolerance)

### Phase 4: Validation
1. [ ] Sample check: Query for `stop_type = 'zone_corrected'` signals
2. [ ] Verify zero stopped_at_entry signals in NEW data
3. [ ] Compare signal quality metrics vs old generation

### Phase 5: Lifecycle Evaluation
1. [ ] Start lifecycle services
2. [ ] Run full lifecycle evaluation
3. [ ] Verify outcome distribution makes sense

---

## Part III: Risk Assessment

### High Risks
| Risk | Impact | Mitigation |
|------|--------|------------|
| Regeneration fails mid-way | Lose all signal data | Database backup before deletion |
| New bugs discovered in fix | Delay, repeated cycle | Code review complete, compile-tested |
| Resource exhaustion | System degradation | Monitor CPU/memory during regeneration |

### Medium Risks
| Risk | Impact | Mitigation |
|------|--------|------------|
| Signal count mismatch | Incomplete historical coverage | Target range ±5%, investigate variance |
| Lifecycle timeout | 7.43M signals take weeks to evaluate | Monitor progress, tune batching |

### Low Risks
| Risk | Impact | Mitigation |
|------|--------|------------|
| Non-backfill signals accidentally deleted | Data loss | WHERE clause strict, test count first |

---

## Part IV: Rollback Plan

**If regeneration fails:**

1. **Restore from backup** (if backup taken)
2. **OR:** Re-deploy from commit before zone fix
3. **OR:** Document gap in historical coverage, proceed with live signals

**Rollback trigger conditions:**
- Regeneration crashes >3 times
- Signal count < 6M or > 8M (target: 7.43M ±5%)
- System overload (CPU >90%, memory >90% for >10min)

---

## Part V: Verification Strategy

### Before Deletion
- [ ] Confirm 7.43M backfill signal count
- [ ] Confirm ~400K non-backfill signals preserved
- [ ] Confirm lifecycle services stopped

### After Deletion
- [ ] Confirm 0 backfill signals remain
- [ ] Confirm ~400K non-backfill signals untouched
- [ ] Confirm system stable (connections, queries work)

### During Regeneration
- [ ] Monitor for zone_corrected stop types (should appear)
- [ ] Monitor for stopped_at_entry (should be ZERO)
- [ ] Track signal count every 1M signals

### After Regeneration
- [ ] Final signal count: 7.43M ±5%
- [ ] Zero stopped_at_entry signals
- [ ] Sample of zone_corrected signals logged

---

## Part VI: Success Criteria

**MUST HAVE (gate conditions):**
1. ✓ All 7.43M signals deleted
2. ✓ Regeneration completes without crash
3. ✓ Final signal count within 7.05M - 7.80M range
4. ✓ Zero stopped_at_entry outcomes in NEW signals
5. ✓ Zone_corrected stops appear in logs (proof fix is working)

**NICE TO HAVE:**
1. Database backup taken before deletion
2. Signal_id list saved for rollback
3. Regeneration runtime logged and analyzed

---

## Part VII: Timeline Estimate

- **Preparation:** 10 minutes
- **Cleanup:** 5 minutes
- **Regeneration:** ~48 hours (8 workers, full 2-year historical range)
- **Validation:** 15 minutes
- **Lifecycle evaluation:** Depends on signal count (could be days)

**Total:** ~2-3 days for complete cycle

---

## Part VIII: Council Approval Required

**Renaissance Council questions:**
1. Should we take a database backup before deletion? (HIGHLY RECOMMENDED)
2. Is the timeline acceptable?
3. What are the acceptable signal count variance bounds?
4. Any additional verification steps?

**Approval:** [ ] Council approved [ ] Rejected with feedback

---

## Appendix A: Commands

```bash
# Phase 1: Preparation
systemctl stop indicant-signal-replay indicant-lifecycle-writer

# Database backup point (if approved)
pg_dump -U postgres -h localhost -d indicagent -f /backup/indicant_before_signal_cleanup.sql

# Save signal IDs for rollback
psql -U postgres -h localhost -d indicagent -c "
COPY (SELECT signal_id FROM signal_ledger WHERE is_backfill = TRUE) 
TO '/tmp/backfill_signal_ids.csv' CSV;
"

# Phase 2: Cleanup
psql -U postgres -h localhost -d indicagent -c "
BEGIN;
DELETE FROM signal_outcomes WHERE signal_id IN (
  SELECT signal_id FROM signal_ledger WHERE is_backfill = TRUE
);
DELETE FROM signal_ledger WHERE is_backfill = TRUE;
COMMIT;
"

# Verify cleanup
psql -U postgres -h localhost -d indicagent -c "
SELECT COUNT(*) FROM signal_ledger WHERE is_backfill = TRUE;
"

# Phase 3: Regeneration
cd /home/bg/dev/indicagent
nohup .venv/bin/python production/scripts/historical_backfill.py --replay-only --workers 8 > logs/backfill_restart.log 2>&1 &

# Monitor progress
tail -f logs/backfill_restart.log
```
