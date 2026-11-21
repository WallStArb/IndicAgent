-- 608: Massive as a third dividend source (todo 428 follow-up, Phase A: the writer side).
--
-- Yahoo covers only the names live when it was asked (1,529), so total-return panels are NaN for
-- every dead member of the stage 2 universe. The Massive dividend capture (reference_raw,
-- endpoint dividends, 2026-11-10: 733,810 records) reaches the dead names. The loader is
-- services/dividend_event_writer.py --sources massive (the tables' single writer); the coverage
-- rule and its measurement are docs/plans/2026-11-21-massive-dividend-coverage-rule.md and
-- src/intelligence/bars/massive_dividends.py.
--
-- What changes:
-- 1. dividend_events and dividend_event_coverage accept source 'massive'.
-- 2. dividend_events gains declared_on (the vendor's declaration date where it has one, so a
--    reader at t can refuse an event declared after t) and the capture lineage of a Massive row
--    (vendor_record_ids: the Massive record ids summed into the event; reference_raw_ids: the
--    captured pages they came from). Required for 'massive', NULL for the other sources.
-- 3. dividend_event_coverage gains reference_capture (the manifest the claim was computed from;
--    required for 'massive') and rule_id (the coverage rule; required for 'massive').
-- 4. dividend_event_coverage_gap: holes inside a source's coverage span. Massive's claim is not
--    contiguous (a lost stretch, a gap between ticker spans, a dropped ex-date), and the
--    coverage primary key (symbol, source) is the Yahoo writer's ON CONFLICT target, so the
--    holes live in their own table instead of multiple coverage rows. A date is covered by a
--    source iff it lies in the source's span and in none of its gaps. Yahoo and IBKR have none.
-- 5. dividend_events_reconciled is pinned to the two existing sources, so loading Massive rows
--    leaves the research reader's surface row-for-row unchanged until Phase B (the reader)
--    decides how Massive enters it.
--
-- Plain tables, no hypertable, no compressed column change, so no VACUUM clause.
--
-- Rollback (before any 'massive' row exists; with rows, delete them first:
--   DELETE FROM dividend_event_coverage_gap WHERE source = 'massive';
--   DELETE FROM dividend_event_coverage WHERE source = 'massive';
--   DELETE FROM dividend_events WHERE source = 'massive';):
--   BEGIN;
--   DROP TABLE dividend_event_coverage_gap;
--   ALTER TABLE dividend_event_coverage DROP CONSTRAINT dividend_event_coverage_massive_lineage,
--       DROP COLUMN reference_capture, DROP COLUMN rule_id,
--       DROP CONSTRAINT dividend_event_coverage_source_check,
--       ADD CONSTRAINT dividend_event_coverage_source_check
--           CHECK (source IN ('yahoo', 'ibkr_adjusted_last_ratio'));
--   ALTER TABLE dividend_events DROP CONSTRAINT dividend_events_massive_lineage,
--       DROP COLUMN declared_on, DROP COLUMN vendor_record_ids, DROP COLUMN reference_raw_ids,
--       DROP CONSTRAINT dividend_events_source_check,
--       ADD CONSTRAINT dividend_events_source_check
--           CHECK (source IN ('yahoo', 'ibkr_adjusted_last_ratio'));
--   (re-create dividend_events_reconciled as in migration 379, without the WHERE clause)
--   DELETE FROM config_history WHERE config_key = 'threshold.dividend_event.prev_close_max_age_days';
--   DELETE FROM config_state WHERE config_key = 'threshold.dividend_event.prev_close_max_age_days';
--   DELETE FROM config_schema WHERE config_key = 'threshold.dividend_event.prev_close_max_age_days';
--   COMMIT;

BEGIN;

ALTER TABLE dividend_events
    DROP CONSTRAINT dividend_events_source_check,
    ADD CONSTRAINT dividend_events_source_check
        CHECK (source IN ('yahoo', 'ibkr_adjusted_last_ratio', 'massive')),
    ADD COLUMN IF NOT EXISTS declared_on date NULL,
    ADD COLUMN IF NOT EXISTS vendor_record_ids text[] NULL,
    ADD COLUMN IF NOT EXISTS reference_raw_ids uuid[] NULL,
    ADD CONSTRAINT dividend_events_massive_lineage CHECK (
        (source = 'massive') = (
            vendor_record_ids IS NOT NULL AND cardinality(vendor_record_ids) > 0
            AND reference_raw_ids IS NOT NULL AND cardinality(reference_raw_ids) > 0
        )
    );

COMMENT ON COLUMN dividend_events.declared_on IS
    'Declaration date as the vendor reports it (massive: the earliest among the event''s records; '
    'NULL where the vendor gives none, and for yahoo and ibkr_adjusted_last_ratio). An event '
    'declared after a reader''s as-of date was not knowable then (migration 608).';
COMMENT ON COLUMN dividend_events.vendor_record_ids IS
    'massive only: the Massive dividend record ids summed into this event (sorted); NULL otherwise.';
COMMENT ON COLUMN dividend_events.reference_raw_ids IS
    'massive only: the reference_raw pages (endpoint dividends) the records came from; NULL otherwise.';

ALTER TABLE dividend_event_coverage
    DROP CONSTRAINT dividend_event_coverage_source_check,
    ADD CONSTRAINT dividend_event_coverage_source_check
        CHECK (source IN ('yahoo', 'ibkr_adjusted_last_ratio', 'massive')),
    ADD COLUMN IF NOT EXISTS reference_capture text NULL,
    ADD COLUMN IF NOT EXISTS rule_id text NULL,
    ADD CONSTRAINT dividend_event_coverage_massive_lineage CHECK (
        (source = 'massive') = (
            reference_capture IS NOT NULL AND reference_capture <> ''
            AND rule_id IS NOT NULL AND rule_id <> ''
        )
    );

COMMENT ON COLUMN dividend_event_coverage.reference_capture IS
    'massive only: the reference_raw manifest_path of the capture the claim was computed from.';
COMMENT ON COLUMN dividend_event_coverage.rule_id IS
    'massive only: the coverage rule (massive_dividends.RULE_ID) that built the claim.';

-- LEDGER-EXCEPTION: corporate-action reference data coverage, not a counterfactual trade claim.
CREATE TABLE IF NOT EXISTS dividend_event_coverage_gap (
    symbol text NOT NULL,
    source text NOT NULL,
    gap_from date NOT NULL,
    gap_to date NOT NULL,
    reasons text[] NOT NULL CHECK (
        cardinality(reasons) > 0
        AND reasons <@ ARRAY['cadence_gap', 'span_gap', 'dropped_ex_date']::text[]
    ),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, source, gap_from),
    FOREIGN KEY (symbol, source) REFERENCES dividend_event_coverage (symbol, source)
        ON DELETE CASCADE,
    CHECK (gap_to >= gap_from)
);

COMMENT ON TABLE dividend_event_coverage_gap IS
    'Holes inside a source''s dividend_event_coverage span (migration 608): a date in '
    '[gap_from, gap_to] is unknown for that source even though it lies inside the span. Holes '
    'are disjoint; overlapping causes merge into one row listing every reason. cadence_gap: two consecutive ex-dates further apart than the coverage rule allows (the '
    'vendor lost the name for a while); span_gap: days between two ticker spans of the name, '
    'where no record could map; dropped_ex_date: an ex-date the writer could not store (non-USD, '
    'no positive amount, no prior close). Only massive writes gaps today. Single writer: '
    'services/dividend_event_writer.py, which replaces a symbol''s gaps with its coverage row.';

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
WHERE source IN ('yahoo', 'ibkr_adjusted_last_ratio')
GROUP BY symbol, ex_date;

COMMENT ON VIEW dividend_events_reconciled IS
    'One row per (symbol, ex_date) over the yahoo and ibkr_adjusted_last_ratio sources: each '
    'source''s yield (NULL where it lacks the event), IBKR''s prior close (for its rounding '
    'bound, 0.02 / close) and dividend_yield, a naive Yahoo-first default. Facts only: research '
    'readers resolve agreement, dispute and single-source events with '
    'research/dividends.resolve_event, not dividend_yield (todo 428). massive rows are excluded '
    'until the reader admits them (migration 608).';

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'threshold.dividend_event.prev_close_max_age_days',
    'int',
    '7',
    '1', '30',
    '[initial_estimate] Calendar days a Massive dividend''s prior close may lie before its ex-date: '
    'the yield divides the raw cash amount by the last raw Massive 1d close before the ex-date, '
    'and a close older than this (a halted or untraded name) leaves the ex-date unstored and a '
    'hole in the coverage. 7 admits a long weekend plus a one-day halt. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('threshold.dividend_event.prev_close_max_age_days', '7', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (NOW(), 'threshold.dividend_event.prev_close_max_age_days', 1, '7', 'migration_608',
        'Initial value [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
