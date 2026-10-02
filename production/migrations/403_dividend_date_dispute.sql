-- Migration 403: dividend_date_dispute, ex-date disagreements kept as records (D-23)
--
-- The dividend_event_writer's reconciliation finds the same dividend reported by
-- two sources 1-5 calendar days apart (26 events on 18 names, measured
-- 2026-09-26). Rolling the symbol back (the interim behavior) blocks the IBKR
-- route entirely for those names; keeping both rows silently would count one
-- dividend twice through dividend_events_reconciled. The third way (plan 07's
-- disputed-date rule): each pair becomes one record holding both sources' dates,
-- and the research reader marks returns spanning the record's window unknown
-- (the reader change is the phase 183 hand-off, applied by its owner).
--
-- The 1..5 day span bound is schema, tied to the dispute definition (D-23) and
-- to threshold.dividend_event.ex_date_match_days = 5 at introduction: tuning
-- that APR key beyond 5 is a deliberate change that must widen this CHECK in a
-- new migration, not a silent drift.
--
-- Plain table: at most a few dozen rows per year (measured 26 on 18 names).
-- Reads are by symbol (the reader resolves disputes per name), covered by the
-- primary key's leading column. No writer-role grants: dividend_event_writer
-- runs as the postgres login and narrows itself nowhere for dividend tables
-- (same as dividend_events, migration 376); bar_derivation_writer does not
-- touch disputes.

BEGIN;

CREATE TABLE IF NOT EXISTS dividend_date_dispute (
    symbol text NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
    first_date date NOT NULL,
    last_date date NOT NULL,
    dates_by_source jsonb NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    fetch_run_id uuid,
    PRIMARY KEY (symbol, first_date, last_date),
    CONSTRAINT dividend_date_dispute_span CHECK (last_date - first_date BETWEEN 1 AND 5)
);

COMMENT ON TABLE dividend_date_dispute IS
    'One dividend reported by both sources with disagreeing ex-dates (D-23, '
    'migration 403): first_date/last_date are the ordered span (1-5 days apart), '
    'dates_by_source maps each source name to the ex-date it reported, '
    'fetch_run_id the D1 run the IBKR side was derived from when the dispute was '
    'recorded. Returns spanning [first_date - 1 session, last_date] are unknown '
    'to the research reader. First recording wins: the writer uses ON CONFLICT DO '
    'NOTHING, so recorded_at is when the dispute was first seen.';

COMMENT ON COLUMN dividend_date_dispute.dates_by_source IS
    'JSON object, one key per source (ibkr_adjusted_last_ratio, yahoo), value the '
    'ISO ex-date that source reported.';

COMMIT;
