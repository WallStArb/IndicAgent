# 302 - IBKR pre-listing void hits full retry storm instead of fast no-data skip

**Filed:** 2026-08-12
**Source:** Observed live during the client-49 full-universe catch-up backfill (post-todo-296/298
saga). GEV (GE Vernova, spun off from GE April 2024) has an ~18-year pre-listing void
(2006-04-2024) in `market_data_ohlcv`. Requesting historical bars for that range should hit
the pipeline's existing fast no-data skip (`ibkr.hist_no_data_skip`, matches on
`_no_data_req_ids`, see `src/providers/ibkr.py` around line 826), but instead every chunk in
the void returns `Error 162: API historical data query cancelled` -- a different error shape
than the "HMDS query returned no data" pattern the fast-skip matches on. That error doesn't
populate `_no_data_req_ids`, so it falls through to the full 3-attempt exponential backoff
(`_RETRY_COUNT`/`_RETRY_BACKOFF_BASE_S` -- 65s then 130s per attempt, ~195s+ wasted) before
`ibkr.hist_chunk_failed_all_retries` finally gives up on that chunk and the outer loop moves
to the next one.

## Impact

For `GEV/15m` (`chunk_days.15m` = 730d / 2yr chunks) the void spans ~9 chunks -- confirmed live,
each one burning the full retry storm, several minutes of pure waste per chunk. `GEV/1h`
(1095d/3yr chunks) already ground through the same shape (6 chunks) and eventually succeeded
with `stored 0 bars`, just slowly. `GEV/5m` (`chunk_days.5m` = 150d) would need ~44 chunks to
cover the same 18-year void -- worst case, potentially an hour or more wasted on one symbol's
`5m` timeframe alone, and `1m` (14d chunks) would be far worse if it isn't capped by the
pipeline's shorter default depth for that timeframe.

Any other recently-listed/spun-off instrument in the 231-symbol active universe hits the same
shape (IPO/spinoff date well after the pipeline's `2006`-era global backfill start). Not
unique to GEV.

## Root cause (confirmed via live log, not theorized)

`fetch_historical_bars`'s chunked-request loop (`src/providers/ibkr.py`, ~line 790-864)
only recognizes definitive no-data via a specific error-callback pattern
(`_no_data_req_ids`, matched via `reqId`) that corresponds to IBKR's "HMDS query returned no
data" message. IBKR's `Error 162: API historical data query cancelled` message is a distinct
wire-level response for querying a pre-listing/no-such-instrument-yet date range, and isn't
recognized as equivalent -- so it goes through the generic retryable-failure path instead of
the fast skip.

## Fix direction (not yet designed)

Either: (a) widen the no-data detection to also match the "query cancelled" error text/code as
definitive-no-data (risk: could also legitimately fire on a genuine pacing cancellation
mid-retry -- needs care not to conflate "no data because pre-listing" with "cancelled because
of pacing violation, data likely does exist"); or (b) once `instrument_metadata`/contract
details expose a listing/IPO date (see `docs/foundation/instrument-data-model.md`, todos
282/283 -- expansion cohort's metadata coverage gap), have the chunking loop skip chunks
entirely before that date rather than ever requesting them. (b) is more robust (avoids the
ambiguity in (a)) but depends on todos 282/283's metadata backfill landing first.

## Where

- `src/providers/ibkr.py` -- `fetch_historical_bars`'s chunked branch, `_no_data_req_ids`
  matching logic (~line 790-864)
- Not blocking: the pipeline still completes correctly (chunk failures don't corrupt data,
  just waste wall-clock time), so this is a performance/efficiency bug, not a correctness one.
