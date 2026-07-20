# Re-test 15m chunk size — likely too conservative relative to 5m/1h

**Found:** 2026-07-02, during the ETF-universe backfill speedup investigation.

`_MAX_CHUNK_DAYS["15m"] = 59` was never re-tested when `1h` (29→364d) and `5m` (29→89d)
were re-verified against live IBKR today. If the real per-request constraint is closer
to a max-bars-per-response ceiling than a flat calendar-day cap, the numbers don't add
up: `5m` at 89 days returns ~25,600 bars/request (89d × ~288 bars/day), while `15m` at
59 days only returns ~5,700 bars/request (59d × ~96 bars/day) — under a quarter of the
volume. If bar-count is the real ceiling, `15m` should support well over 200 days per
request, not 59.

**Action:** Probe `15m` chunk size the same way `1h`/`5m` were verified today (see commit
`f9ab3005` and session history) — direct `reqHistoricalDataAsync` calls at increasing
`durationStr` (e.g. 90D, 150D, 200D, 250D) against a few new-universe symbols (DBC, PPLT,
SDOG), watching for timeout or empty-result failure the way 180D/5m timed out. Use a
client-id within `_MAX_CLIENT_ID=50` and away from any concurrently-running backfill job
to avoid disrupting it (a stray client-id >50 during this same investigation triggered an
unplanned IB Gateway restart).

**Blocked on:** nothing — safe to do anytime IBKR/TWS is up and no other backfill is mid-run.

**Status check 2026-07-19:** gate reconfirmed clear — `ib-gateway` container up 2 days,
`indicagent-ibkr-provider` inactive, no `historical_pipeline`/backfill process running. Did not
execute the live probe in this session: the existing `fetch_historical_bars()` auto-chunks
through `_MAX_CHUNK_DAYS` internally, so testing a specific `durationStr` requires either a new
public probe method on `IBKRProvider` or reaching into its private `_ib` handle — a real,
live-broker-connectivity action worth a deliberate go-ahead rather than folding into a backlog
triage pass, especially given this same todo's own note about a prior stray-client-id gateway
restart. Still fully unblocked and quick (one session) whenever picked up.
