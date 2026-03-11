# Deferred Items (Phase 25-01)

## Pre-existing issues discovered but out of scope

### 1. F821 Undefined name 'timezone' in historical_backfill.py:941
- **File:** `production/scripts/historical_backfill.py`
- **Line:** 941
- **Issue:** Uses `timezone.utc` but only `UTC` is imported from datetime
- **Current import:** `from datetime import UTC, datetime, timedelta`
- **Fix:** Add `from datetime import UTC, datetime, timedelta, timezone` OR change line 941 to use `UTC`
- **Status:** Pre-existing bug, not introduced by 25-01 changes
- **Impact:** Only affects `--days` argument in main() function (replay path)
