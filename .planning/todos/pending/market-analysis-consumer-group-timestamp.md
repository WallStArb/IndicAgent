# Fix market_analysis_service timestamped consumer group

**File:** `services/market_analysis_service.py` line 84  
**Bug:** `self.consumer_group = f"market_analysis_{int(time.time())}"`

Creates a new consumer group on every restart, starting from the latest
stream ID. Misses any messages buffered during downtime — recovers quickly
since bars arrive continuously, but is still incorrect behavior.

**Fix:** Use stable name `"market_analysis"` (same pattern as ai_narrative_service).
Also use `"0"` for initial start position (rewind) on group creation.

**Priority:** Low — not blocking current operation.
