-- Migration 376: dividend events from two independent sources, reconciled (todo 428)
--
-- Equity bars are IBKR TRADES: split-adjusted, not dividend-adjusted. Every return that spans
-- an ex-dividend date carries the dividend as a loss, which biases overnight and daily targets
-- and price-level features on high-yield names. services/dividend_event_writer.py fills these
-- tables from two sources and checks them against each other:
--
--   yahoo                     declared cash dividends by ex-date, full history
--   ibkr_adjusted_last_ratio  the ex-date step in IBKR's ADJUSTED_LAST / TRADES daily ratio
--
-- Two sources because each has holes the other fills, invisible from its own data (measured
-- 2026-09-26: IBKR lacks SPY's 2001-2005 dividends and five HYG months; Yahoo lacks HYG's
-- November 2012 distribution).
--
-- dividend_events holds facts (ex-date, amount, the close before it), never an adjusted price
-- series. Ex-date and amount are announced before the ex-date, so no reader looks ahead by
-- using them. Readers use amount / prev_close: both are in the split units of the day the row
-- was derived, and only their ratio survives a later split.
--
-- dividend_event_coverage records the span each source examined per symbol: the difference
-- between "paid no dividend" and "never checked". A reader treats a span outside Yahoo's
-- coverage as unknown, never as zero. IBKR's span records what was examined, not completeness.
--
-- dividend_events_reconciled is the reader surface for events: one row per (symbol, ex_date),
-- each source's yield, and a default dividend_yield (Yahoo's declared amount where present;
-- IBKR's is implied through a rounded factor). The writer rolls a symbol back if the two
-- sources report one dividend on different dates, the case this view would double count.
-- Policy stays with the reader: a large yield only one source reports (2026-09-26: 113 of
-- 73,940 Yahoo events above 10%, mostly spin-offs, at least one vendor error) is for the
-- consumer's pinned spec to treat, typically by marking the spanning return unknown.

BEGIN;

-- LEDGER-EXCEPTION: corporate-action reference data (ex-date, cash amount) from market data
-- vendors, not a counterfactual trade claim; nothing here is a frame or a hypothesis.
CREATE TABLE IF NOT EXISTS dividend_events (
    symbol TEXT NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
    ex_date DATE NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('yahoo', 'ibkr_adjusted_last_ratio')),
    amount DOUBLE PRECISION NOT NULL CHECK (amount > 0),
    prev_close DOUBLE PRECISION NOT NULL CHECK (prev_close > 0),
    compute_version TEXT NOT NULL,
    derived_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, ex_date, source),
    -- NaN > 0 is true in Postgres, so the positivity checks alone admit it.
    CONSTRAINT dividend_events_finite CHECK (
        amount <> 'NaN' AND amount <> 'Infinity' AND prev_close <> 'NaN' AND prev_close <> 'Infinity'
    )
);

COMMENT ON TABLE dividend_events IS
    'Per-share cash distributions by ex-date and source (todo 428). Read amount / prev_close '
    '(the yield on the ex-date): both are in the split units of the day the row was derived. '
    'First derivation wins; re-derivations never overwrite. Readers use '
    'dividend_events_reconciled, not this table.';

CREATE TABLE IF NOT EXISTS dividend_event_coverage (
    symbol TEXT NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
    source TEXT NOT NULL CHECK (source IN ('yahoo', 'ibkr_adjusted_last_ratio')),
    covered_from DATE NOT NULL,
    covered_to DATE NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (symbol, source),
    CHECK (covered_to >= covered_from)
);

COMMENT ON TABLE dividend_event_coverage IS
    'Contiguous span of ex-dates each source examined per symbol. Outside the yahoo span the '
    'dividend history is unknown, not zero.';

CREATE OR REPLACE VIEW dividend_events_reconciled AS
SELECT
    symbol,
    ex_date,
    max(amount / prev_close) FILTER (WHERE source = 'yahoo') AS yahoo_yield,
    max(amount / prev_close) FILTER (WHERE source = 'ibkr_adjusted_last_ratio') AS ibkr_yield,
    COALESCE(
        max(amount / prev_close) FILTER (WHERE source = 'yahoo'),
        max(amount / prev_close) FILTER (WHERE source = 'ibkr_adjusted_last_ratio')
    ) AS dividend_yield
FROM dividend_events
GROUP BY symbol, ex_date;

COMMENT ON VIEW dividend_events_reconciled IS
    'One row per (symbol, ex_date): each source''s yield (NULL where it lacks the event) and '
    'dividend_yield, the Yahoo yield where present, else IBKR''s. Facts only: how to treat a '
    'large yield only one source reports (a spin-off, a vendor error) is the reader''s policy, '
    'pinned in its own spec. The reader surface for dividend adjustment (todo 428).';

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'threshold.dividend_event.noise_margin',
        'float',
        '1.25',
        '1.0', NULL,
        '[initial_estimate] Multiple of the worst-case rounding bound (0.005/close on each of two days; ADJUSTED_LAST is quoted to the cent) that a TRADES/ADJUSTED_LAST ratio step must exceed to count as a dividend. 1.0 is the exact bound; the margin absorbs closing-print differences between the two series. Changing it changes which events are derived. Not an ML learning target.'
    ),
    (
        'threshold.dividend_event.ex_date_match_days',
        'int',
        '5',
        '1', '30',
        '[initial_estimate] Two sources reporting unmatched ex-dates this many calendar days apart or fewer are treated as one dividend on disagreeing dates, which fails the dividend_event_writer run (the reconciled view would count it twice). Shorter than the shortest regular distribution interval (weekly payers aside). Not an ML learning target.'
    ),
    (
        'threshold.dividend_event.source_yield_rel_tolerance',
        'float',
        '0.10',
        '0.0', '1.0',
        '[initial_estimate] Relative difference between the two sources'' yields on the same ex-date above which the event is logged as a disagreement. 2026-09-26 measurement: medians 0.3% to 1.2%, maximum 5.3% on SPY, HYG and TLT. Diagnostic only. Not an ML learning target.'
    ),
    (
        'infra.dividend_event.lookback_years',
        'int',
        '1',
        '1', '30',
        '[initial_estimate] Years of IBKR daily history a dividend_event_writer run requests per symbol (Yahoo always returns full history). A full IBKR history is a one-off --years run; the coverage check refuses to extend a symbol whose new window does not reach its stored coverage. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.dividend_event.noise_margin', '1.25', 1),
    ('threshold.dividend_event.ex_date_match_days', '5', 1),
    ('threshold.dividend_event.source_yield_rel_tolerance', '0.10', 1),
    ('infra.dividend_event.lookback_years', '1', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'threshold.dividend_event.noise_margin', 1, '1.25', 'migration_376', 'Initial value [initial_estimate]'),
    (NOW(), 'threshold.dividend_event.ex_date_match_days', 1, '5', 'migration_376', 'Initial value [initial_estimate]'),
    (NOW(), 'threshold.dividend_event.source_yield_rel_tolerance', 1, '0.10', 'migration_376', 'Initial value [initial_estimate]'),
    (NOW(), 'infra.dividend_event.lookback_years', 1, '1', 'migration_376', 'Initial value [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
