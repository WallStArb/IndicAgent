-- Migration 303: fix infra.ibkr.chunk_days.15m mismatch with IBKR's year-rounding
--
-- _days_to_duration_str() (src/providers/ibkr.py) converts any duration over 365 days to
-- whole years via math.ceil(total_days / 365). 400 is not a multiple of 365, so a
-- chunk_days.15m=400 request is formatted "2 Y" and IBKR returns a full 730 days per
-- request -- not 400. Migration 302 confirmed this exact behavior in its own commentary
-- but left the config value at 400 instead of the equivalent-cost, already-tested 730.
--
-- Consequence: the chunking loop in fetch_historical_bars() walks the request window back
-- by chunk_days (400) per iteration while each request actually returns a 730-day span, so
-- every chunk after the first re-requests ~330 days already covered by the prior chunk --
-- close to double the necessary IBKR requests for a multi-year 15m backfill, against the
-- tightest constraint in the pipeline (infra.ibkr.rate_limit_max_requests = 58 req/10min).
--
-- Fix: set chunk_days.15m = 730 (2 * 365, exact multiple -- no rounding gap). This is NOT a
-- new value requiring re-verification: 730 and 400 both format to "2 Y" and hit the
-- identical IBKR wire request already confirmed clean in migration 302
-- (ibkr_chunk_and_rate_limit_probe.py run 5, 2026-08-06, MSFT, 12944 bars, 24.7s). Zero
-- incremental risk, aligns the loop stride with the actual returned window.
--
-- Checked all other chunk_days.* keys for the same class of bug: 1m (14d) and 5m (150d)
-- stay under the 365-day threshold entirely (no year-rounding applies). 4h/1h (1095d) and
-- 1d (7300d) are exact multiples of 365 (3yr, 20yr) -- ceil(1095/365)=3, ceil(7300/365)=20,
-- no rounding gap. 15m (400d) was the only non-multiple value in the table.

BEGIN;

UPDATE config_state SET config_value = '730', version = version + 1, updated_at = NOW()
WHERE config_key = 'infra.ibkr.chunk_days.15m';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'infra.ibkr.chunk_days.15m', version, config_value, 'migration_303',
       '[rca_analysis] Recalibrated 400d -> 730d. 400 is not a multiple of 365, so '
       '_days_to_duration_str() rounded it up to "2 Y" (730d actual) while the chunking '
       'loop still only advanced its walk-back window by 400d/iteration -- causing ~330 '
       'days of redundant re-requested coverage per chunk on multi-year 15m backfills. '
       '730 = 2*365 exactly, formats to the identical "2 Y" wire request already confirmed '
       'clean in migration 302 (MSFT, 12944 bars, 24.7s) -- same tested request, corrected '
       'loop stride, zero new IBKR-side risk.'
FROM config_state WHERE config_key = 'infra.ibkr.chunk_days.15m';

COMMIT;
