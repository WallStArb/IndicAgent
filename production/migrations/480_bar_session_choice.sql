-- Migration 480: bar_session_choice, the durable record of selection's session choices
-- (phase 191, third review of plan 07, finding 4)
--
-- Selection takes each regular-hours session whole from one vendor (D-191-M item 9). A session
-- taken from the fallback, one no ranked vendor held whole, or one whose chosen vendor holds
-- fewer slots than the NYSE calendar's regular-hours grid was recorded only as a structlog line
-- (`bar_selection.session_choice`). A feature cannot condition on a log line, and the vendors'
-- volume levels differ (IBKR to Alpaca 5m volume about 0.38 on BKNG, 0.62 to 0.95 on MSFT), so
-- a session's vendor is a property of its bars that research must be able to read.
--
-- One row per (symbol, timeframe, session_date) that is not plain: plain is taken from the
-- ranked first vendor, complete, and holding every calendar slot. services/bar_selection.py
-- (select_and_write) is the sole writer: it upserts the choices of every session it selects and
-- deletes the rows of sessions it selected that are plain now. Current state, not history; the
-- structlog line keeps each decision.
--
-- New small table, no rewrite of anything existing.

BEGIN;

SET LOCAL lock_timeout = '10s';

CREATE TABLE IF NOT EXISTS bar_session_choice (
    symbol              text        NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
    timeframe           text        NOT NULL,
    session_date        date        NOT NULL,
    vendor              text        NOT NULL,
    ranking             text[]      NOT NULL,
    complete            boolean     NOT NULL,
    n_slots             integer     NOT NULL CHECK (n_slots >= 0),
    n_vendor_slots      integer     NOT NULL CHECK (n_vendor_slots >= 0),
    n_grid_slots        integer     CHECK (n_grid_slots >= 0),
    n_vendor_grid_slots integer     CHECK (n_vendor_grid_slots >= 0),
    dropped             timestamptz[] NOT NULL DEFAULT '{}',
    decided_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, timeframe, session_date),
    CONSTRAINT bar_session_choice_timeframe_check CHECK (timeframe IN ('1m', '5m', '4h'))
);

COMMENT ON TABLE bar_session_choice IS
    'Sessions selection did not take plainly (ranked-first vendor, complete, every calendar '
    'slot): the vendor it took the session from, whether any ranked vendor held it whole, the '
    'slot counts against the NYSE regular-hours grid, and the slots left out. Sole writer: '
    'services/bar_selection.py select_and_write. Migration 480.';
COMMENT ON COLUMN bar_session_choice.complete IS
    'True when some ranked vendor held every regular-hours slot any ranked vendor held.';
COMMENT ON COLUMN bar_session_choice.n_grid_slots IS
    'The calendar''s regular-hours slots of the session; NULL for a timeframe without a grid.';
COMMENT ON COLUMN bar_session_choice.dropped IS
    'Slots another ranked vendor held that the session rule left out (canonical retracted).';

GRANT SELECT, INSERT, UPDATE, DELETE ON bar_session_choice TO bar_derivation_writer;

COMMIT;
