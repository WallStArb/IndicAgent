-- Migration 379: dividend_events_reconciled exposes IBKR's prior close (todo 428 follow-up)
--
-- The two sources' yields for one ex-date can differ for two reasons: IBKR's cent rounding
-- (noise, bounded by 0.02 / prior close) or a real disagreement (a part-stock special such as
-- WY 2010: Yahoo 63%, IBKR 24%). Telling them apart needs IBKR's prior close, so the reader
-- (research/dividends.resolve_event) can apply the bound. 606 of 42,926 two-source events
-- disagree beyond rounding (2026-09-26). The view stays facts only; columns are appended.

BEGIN;

CREATE OR REPLACE VIEW dividend_events_reconciled AS
SELECT
    symbol,
    ex_date,
    max(amount / prev_close) FILTER (WHERE source = 'yahoo') AS yahoo_yield,
    max(amount / prev_close) FILTER (WHERE source = 'ibkr_adjusted_last_ratio') AS ibkr_yield,
    COALESCE(
        max(amount / prev_close) FILTER (WHERE source = 'yahoo'),
        max(amount / prev_close) FILTER (WHERE source = 'ibkr_adjusted_last_ratio')
    ) AS dividend_yield,
    max(prev_close) FILTER (WHERE source = 'ibkr_adjusted_last_ratio') AS ibkr_prev_close
FROM dividend_events
GROUP BY symbol, ex_date;

COMMENT ON VIEW dividend_events_reconciled IS
    'One row per (symbol, ex_date): each source''s yield (NULL where it lacks the event), '
    'IBKR''s prior close (for its rounding bound, 0.02 / close) and dividend_yield, a naive '
    'Yahoo-first default. Facts only: research readers resolve agreement, dispute and single-'
    'source events with research/dividends.resolve_event, not dividend_yield (todo 428).';

COMMIT;
