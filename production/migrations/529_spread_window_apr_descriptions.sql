-- Migration 529: correct the two spread-window APR descriptions migration 526 seeded (todo 553
-- review). 526 justified 21 and 252 by 1d calendars, but each key serves every timeframe the
-- feature rebuild computes (5m, 15m, 1h, 1d). Decision: one key per estimator, the window counted
-- in bars at every timeframe, with the 1d-only rationale and the intraday caveats stated.
--
-- Description text only: no value changes, so no config_state write. config_history records
-- values (config_value, reason), not descriptions, so it gets no row. Idempotent: a rerun
-- rewrites the same text.

BEGIN;

UPDATE config_schema SET description =
    '[conventional] Corwin-Schultz high_low_spread: two-bar spread estimates (negatives set to 0) averaged over this many pairs. Counted in bars at every timeframe (one key for 5m, 15m, 1h and 1d). 21 = the paper''s monthly average of daily estimates, a rationale that holds only on 1d; intraday levels are not comparable to 1d levels, and flat bars (high == low, about 1.7% of 15m bars since 2024) floor their pairs toward 0. Declared memory = window. Not an ML learning target.'
WHERE config_key = 'feature.high_low_spread.window';

UPDATE config_schema SET description =
    '[conventional] Roll implied spread roll_spread: serial covariance of log close changes over this many return pairs, NaN when the covariance is >= 0 (about 40% of 1d rows after warmup; the missingness is informative, never missing at random). Counted in bars at every timeframe (one key for 5m, 15m, 1h and 1d). 252 = one trading year, Roll (1984) estimated per year, a rationale that holds only on 1d; intraday levels are not comparable to 1d levels and an intraday window spans overnight returns. Declared memory = window + 1. Not an ML learning target.'
WHERE config_key = 'feature.roll_spread.window';

COMMIT;
