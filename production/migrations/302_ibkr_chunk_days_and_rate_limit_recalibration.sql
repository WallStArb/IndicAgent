-- Migration 302: infra.ibkr.chunk_days.* and rate_limit_max_requests recalibration
--
-- Every value below was empirically re-verified 2026-08-06 via a new, saved probe script
-- (scripts/infrastructure/backfill/ibkr_chunk_and_rate_limit_probe.py), not carried forward
-- from inherited assumption. Motivation: migration 192's own text flagged chunk_days.15m as
-- `[initial_estimate]`, never independently tested, and migration 276 tagged
-- rate_limit_max_requests `[conventional]` -- inherited developer convention, never measured
-- against this account either. Both gaps are closed by this migration; every other
-- chunk_days key was re-verified too, not just the previously-flagged ones, since the same
-- probe pass also caught and fixed a real, separate bug: fetch_historical_bars's chunked
-- (non-continuous) request path never converted "N D" to "N Y" past 365 days, unlike the
-- continuous-contract branch -- exposed by the probe widening chunk_days.1d past 365 for the
-- first time (see same-date commit to src/providers/ibkr.py + new regression test in
-- tests/unit/providers/test_ibkr_provider.py::test_chunk_over_365_days_uses_years_not_days).
--
-- Methodology: for each timeframe, temporarily widen _MAX_CHUNK_DAYS and run ONE real
-- fetch_historical_bars call (through the actual production code path, not a synthetic
-- request) against a real symbol from todo 259's zero-row backfill queue, sized so the
-- chunking loop makes exactly one chunk attempt. A successful test IS real backfill
-- progress (store_bars wrote the data); a failed test writes nothing (fetch_historical_bars
-- only returns bars on success). Every value below succeeded cleanly on this test. None of
-- these are proven true ceilings -- each is one confirmed-good tier above the old default,
-- not an exhaustive search for the maximum (1h's true ceiling sits somewhere between the
-- confirmed-good 1095d and a confirmed-BAD 7300d full-20yr single-shot, which genuinely
-- failed after 375s of retries -- not applied here).
--
-- Real, unexplained-but-benign side finding, noted for whoever revisits this: for
-- day-formatted ("N D") requests, actual returned calendar coverage ran ~1.45x the
-- requested day count across 5m/15m/4h (consistent ratio, close to the 7/5 weekday
-- fraction -- working hypothesis is IBKR counts "N D" as N trading/session days for
-- equities, not N calendar days). Year-formatted ("N Y") requests behave as clean, exact
-- calendar years instead (1095d -> ~1095 actual, 400d -> a full 2yr/730d via math.ceil
-- rounding up). Not confirmed via an isolated controlled test -- a bonus observation, not
-- load-bearing for the values chosen here (every value below was accepted based on its own
-- direct pass/fail result, not on this ratio).
--
-- Rate limit: tested clean through 62 req/10min (2 past IBKR's own documented 60 hard
-- ceiling) with zero pacing violations, across two separate probe runs same day. Recalibrated
-- to 58, not the full tested 62 -- conservative partial credit, retaining a real margin
-- rather than adopting the edge of a single day's clean test. infra.ibkr.rate_limit_max_requests
-- already has a config_schema max_value=60 constraint (migration 276); 58 fits inside it,
-- no schema change needed.
--
-- chunk_days.* keys have no config_schema min/max bounds (confirmed via live query
-- 2026-08-06) -- no schema change needed for those either.

BEGIN;

-- ---------------------------------------------------------------------------
-- chunk_days.* recalibration
-- ---------------------------------------------------------------------------

UPDATE config_state SET config_value = '14', version = version + 1, updated_at = NOW()
WHERE config_key = 'infra.ibkr.chunk_days.1m';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'infra.ibkr.chunk_days.1m', version, config_value, 'migration_302',
       '[rca_analysis] Recalibrated 6d -> 14d. Confirmed clean via real fetch_historical_bars '
       'call (KMI, 5088 bars, 0.4s), scripts/infrastructure/backfill/'
       'ibkr_chunk_and_rate_limit_probe.py run 3, 2026-08-06. Was already [rca_analysis] '
       '(~7-day IBKR limit), this widens within the same confirmed-real boundary class, not '
       'a re-derivation from scratch.'
FROM config_state WHERE config_key = 'infra.ibkr.chunk_days.1m';

UPDATE config_state SET config_value = '150', version = version + 1, updated_at = NOW()
WHERE config_key = 'infra.ibkr.chunk_days.5m';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'infra.ibkr.chunk_days.5m', version, config_value, 'migration_302',
       '[rca_analysis] Recalibrated 89d -> 150d, narrowing the known 90D-good/180D-bad gap '
       '(migration 192''s original 2026-07-02 probe). Confirmed clean (LEN, 11626 bars, '
       '36.0s), same probe run as above, 2026-08-06. True ceiling still untested between '
       '150-180d.'
FROM config_state WHERE config_key = 'infra.ibkr.chunk_days.5m';

UPDATE config_state SET config_value = '400', version = version + 1, updated_at = NOW()
WHERE config_key = 'infra.ibkr.chunk_days.15m';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'infra.ibkr.chunk_days.15m', version, config_value, 'migration_302',
       '[rca_analysis] Recalibrated 59d -> 400d. This closes the gap migration 192 itself '
       'flagged: "[initial_estimate]... has not had a re-verification probe... possibly '
       'under-tuned" -- now independently confirmed. 400d crosses the 365-day threshold, so '
       'the actual request is formatted "2 Y" (math.ceil(400/365)) and IBKR returns a full '
       '2 calendar years (~730 days) per request, not literally 400. Confirmed clean (MSFT, '
       '12944 bars, 24.7s), ibkr_chunk_and_rate_limit_probe.py run 5, 2026-08-06.'
FROM config_state WHERE config_key = 'infra.ibkr.chunk_days.15m';

UPDATE config_state SET config_value = '1095', version = version + 1, updated_at = NOW()
WHERE config_key = 'infra.ibkr.chunk_days.4h';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'infra.ibkr.chunk_days.4h', version, config_value, 'migration_302',
       '[rca_analysis] Recalibrated 29d -> 1095d (3yr), matching 1h''s confirmed-good tier -- '
       '4h bars are less dense than 1h so should tolerate at least as much. Was '
       '[initial_estimate], "not re-verified alongside 5m/1h" per migration 192 -- now '
       'independently confirmed. Requested as "3 Y" (1095/365 divides evenly), returned '
       '~1095 actual days almost exactly. Confirmed clean (MSFT, 1752 bars, 16.6s), '
       'ibkr_chunk_and_rate_limit_probe.py run 5, 2026-08-06.'
FROM config_state WHERE config_key = 'infra.ibkr.chunk_days.4h';

UPDATE config_state SET config_value = '1095', version = version + 1, updated_at = NOW()
WHERE config_key = 'infra.ibkr.chunk_days.1h';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'infra.ibkr.chunk_days.1h', version, config_value, 'migration_302',
       '[rca_analysis] Recalibrated 364d -> 1095d (3yr). Confirmed clean (GOOGL, 36841 bars, '
       '179.2s), ibkr_chunk_and_rate_limit_probe.py run 2, 2026-08-06. A more aggressive '
       'full-20yr (7300d) single-shot tier was also tested (run 3, LMT) and genuinely FAILED '
       '(0 bars, 375.3s of retries, "API historical data query cancelled") -- NOT applied. '
       'True ceiling sits somewhere between 1095d (confirmed good) and 7300d (confirmed '
       'bad), untested further.'
FROM config_state WHERE config_key = 'infra.ibkr.chunk_days.1h';

UPDATE config_state SET config_value = '7300', version = version + 1, updated_at = NOW()
WHERE config_key = 'infra.ibkr.chunk_days.1d';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'infra.ibkr.chunk_days.1d', version, config_value, 'migration_302',
       '[rca_analysis] Recalibrated 364d -> 7300d -- a full 20yr single-shot request per '
       'symbol, replacing ~20 chunked requests with 1. This tier ALSO exposed and led to '
       'fixing a real bug: fetch_historical_bars''s chunked-request branch never converted '
       '"N D" to "N Y" durations past 365 days (Error 321, "must be made in years"), unlike '
       'the continuous-contract branch -- fixed same-date in src/providers/ibkr.py, '
       'regression test added. Confirmed clean post-fix (MARA, 3025 bars, 0.9s), '
       'ibkr_chunk_and_rate_limit_probe.py run 3, 2026-08-06.'
FROM config_state WHERE config_key = 'infra.ibkr.chunk_days.1d';

-- ---------------------------------------------------------------------------
-- rate_limit_max_requests recalibration
-- ---------------------------------------------------------------------------

UPDATE config_state SET config_value = '58', version = version + 1, updated_at = NOW()
WHERE config_key = 'infra.ibkr.rate_limit_max_requests';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'infra.ibkr.rate_limit_max_requests', version, config_value, 'migration_302',
       '[rca_analysis] Recalibrated 55 -> 58. Was [conventional] (migration 276) -- inherited '
       'developer convention, never independently measured against this account. Tested '
       'clean through 62 req/10min (2 past IBKR''s own documented 60 hard ceiling) with zero '
       'pacing violations, across two separate probe runs same day '
       '(ibkr_chunk_and_rate_limit_probe.py, 2026-08-06). Recalibrated to 58, not the full '
       'tested 62 -- conservative partial credit, retaining real margin rather than adopting '
       'the edge of a single day''s clean test. A genuine pacing violation costs a 65s/130s '
       'retry backoff, so the downside of pushing too far outweighs the small additional '
       'throughput gain.'
FROM config_state WHERE config_key = 'infra.ibkr.rate_limit_max_requests';

COMMIT;
