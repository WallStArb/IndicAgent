-- Migration 549: borrow_availability_snapshots hypertable + APR seeds (todo 438)
--
-- Borrow availability is live-only at IBKR: a day not asked is lost for the
-- forward span and the short-leg constraint (unified design 9.3). One append-only
-- row per asked symbol per daily run; a nan vendor answer is stored as NULL
-- shortable_shares (asked-but-unknown is data, unasked is absence; the capture
-- law stores what the vendor serves). `shortable` is a generated column from the
-- share count, so the derivation lives in exactly one place. Readers take each
-- symbol's latest as_of. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS borrow_availability_snapshots (
    symbol text NOT NULL,
    as_of timestamptz NOT NULL,
    vendor text NOT NULL DEFAULT 'ibkr',
    shortable_shares double precision,
    shortable boolean GENERATED ALWAYS AS (shortable_shares > 0) STORED
);

SELECT create_hypertable('borrow_availability_snapshots', 'as_of',
    chunk_time_interval => INTERVAL '90 days',
    if_not_exists => TRUE, migrate_data => TRUE);

CREATE INDEX IF NOT EXISTS borrow_snapshots_symbol_as_of_idx
    ON borrow_availability_snapshots (symbol, as_of DESC);

-- APR seeds: batch mechanics only; scope is not a parameter (the universe is
-- get_active_contracts(dimension="backfill") by design, so the capture survives
-- compute-universe changes and is never silently narrowed by a config edit).
-- All three share one unit convention (seconds), like the provider signature.

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'infra.borrow.batch_size',
        'int', '50', 1, 80,
        '[initial_estimate] Symbols per reqMktData snapshot batch in the daily borrow capture. Subscriptions are cancelled after each batch, so the 80-subscription cap (a live-streaming cap) never binds; 50 keeps each batch well under it. Not an ML learning target.'
    ),
    (
        'infra.borrow.batch_pause_s',
        'float', '2.5', 0, 60,
        '[initial_estimate] Pause between snapshot batches (seconds) to stay clear of market-data pacing. 1,529 names at batch 50 is about 31 batches and roughly 80 s of pause time per run. Not an ML learning target.'
    ),
    (
        'infra.borrow.batch_wait_s',
        'float', '8.0', 1, 60,
        '[initial_estimate] Seconds to wait after arming a batch''s subscriptions before reading the tickers; tick 236 answers within a few seconds on the gateway. Rows already store NULL for a silent answer, so a too-short wait loses nothing permanently. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.borrow.batch_size', '50', 1),
    ('infra.borrow.batch_pause_s', '2.5', 1),
    ('infra.borrow.batch_wait_s', '8.0', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version, s.config_value, 'migration:549',
       'seed (daily borrow availability capture, todo 438)'
  FROM config_state s
 WHERE s.config_key IN ('infra.borrow.batch_size', 'infra.borrow.batch_pause_s', 'infra.borrow.batch_wait_s')
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.version = s.version
          AND h.changed_by = 'migration:549'
   );

COMMIT;
