-- Migration 481: the restatement detector replaces the load-level refusal (phase 191, D-191-N)
--
-- Owner decision 2026-10-14: a vendor's own re-serve always overwrites its raw value last-wins;
-- the old value is logged as an ohlcv_revision row, so every overwrite is recoverable. Nothing
-- is held pending and no load is refused. What the refusal guarded against, a vendor silently
-- changing the basis of its history, is detected and reported instead
-- (src/intelligence/bars/restatement.py, applied by services/ohlcv_ingress_contract.py):
--
-- - share: changed rows over the vendor's stored rows of the offered keys, above
--   threshold.bar_integrity.restatement_flag_share over at least restatement_flag_min_stored;
-- - price_ratio: at least restatement_signature_min_bars changed bars whose new prices are one
--   multiple of the old ones within restatement_ratio_tolerance (a split, dividend, currency or
--   precision change applied to history);
-- - time_shift: at least that many changed bars of which restatement_shift_min_share equal the
--   stored value one bar earlier or later.
--
-- A flagged load is written all the same; it gets one row here, a structlog warning and the
-- ohlcv_restatement_flags_total metric. The thresholds feed a report, never a gate on a write.
--
-- New small table, APR seeds; nothing existing is rewritten.

BEGIN;

SET LOCAL lock_timeout = '10s';

CREATE TABLE IF NOT EXISTS ohlcv_restatement_flag (
    load_id     uuid        PRIMARY KEY REFERENCES ohlcv_load(load_id) ON DELETE RESTRICT,
    symbol      text        NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
    timeframe   text        NOT NULL,
    vendor      text        NOT NULL,
    kind        text        NOT NULL,
    n_stored    integer     NOT NULL CHECK (n_stored >= 0),
    n_changed   integer     NOT NULL CHECK (n_changed >= 0),
    share       double precision NOT NULL,
    signatures  text[]      NOT NULL,
    ratio       double precision,
    shift_bars  integer,
    detail      text        NOT NULL,
    flagged_at  timestamptz NOT NULL DEFAULT now(),
    reviewed_at timestamptz,
    review_note text
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_restatement_flag_series
    ON ohlcv_restatement_flag (symbol, timeframe, flagged_at DESC);

COMMENT ON TABLE ohlcv_restatement_flag IS
    'Vendor loads the restatement detector flagged for review (D-191-N): the changed share and '
    'any basis-change signature (price_ratio, time_shift). The write itself landed last-wins; '
    'the old values are in ohlcv_revision under the same load_id. Writer: '
    'services/ohlcv_ingress_contract.py. Migration 481.';

GRANT SELECT, INSERT ON ohlcv_restatement_flag TO bar_derivation_writer;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'threshold.bar_integrity.restatement_flag_share',
        'float', '0.02', 0, 1,
        '[conventional] A vendor load whose changed rows exceed this share of its stored rows at '
        'the offered keys is flagged for review (D-191-N). Reporting only: the write lands '
        'last-wins regardless. Same level the retired refusal used. Not an ML learning target.'
    ),
    (
        'threshold.bar_integrity.restatement_flag_min_stored',
        'int', '500', 0, 1000000,
        '[conventional] Stored rows a load must overlap before its changed share is judged: a '
        'fetcher tail window holds about 78 5m bars and IBKR restates recent bars. Reporting '
        'only (D-191-N). Not an ML learning target.'
    ),
    (
        'threshold.bar_integrity.restatement_signature_min_bars',
        'int', '20', 1, 100000,
        '[initial_estimate] Changed bars a load needs before a basis-change signature '
        '(price_ratio, time_shift) is tested. Reporting only (D-191-N). Not an ML learning target.'
    ),
    (
        'threshold.bar_integrity.restatement_ratio_tolerance',
        'float', '0.0005', 0, 1,
        '[initial_estimate] price_ratio signature: every changed price is the median new/old '
        'ratio within this relative spread, and the median differs from 1 by more than it. '
        'Reporting only (D-191-N). Not an ML learning target.'
    ),
    (
        'threshold.bar_integrity.restatement_shift_min_share',
        'float', '0.5', 0, 1,
        '[initial_estimate] time_shift signature: share of changed bars whose new value equals '
        'the stored value one bar earlier or later. Reporting only (D-191-N). Not an ML '
        'learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.bar_integrity.restatement_flag_share', '0.02', 1),
    ('threshold.bar_integrity.restatement_flag_min_stored', '500', 1),
    ('threshold.bar_integrity.restatement_signature_min_bars', '20', 1),
    ('threshold.bar_integrity.restatement_ratio_tolerance', '0.0005', 1),
    ('threshold.bar_integrity.restatement_shift_min_share', '0.5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version, s.config_value, 'migration:481',
       'seed (phase 191, D-191-N restatement detector)'
  FROM config_state s
 WHERE s.config_key IN (
           'threshold.bar_integrity.restatement_flag_share',
           'threshold.bar_integrity.restatement_flag_min_stored',
           'threshold.bar_integrity.restatement_signature_min_bars',
           'threshold.bar_integrity.restatement_ratio_tolerance',
           'threshold.bar_integrity.restatement_shift_min_share'
       )
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.version = s.version
          AND h.changed_by = 'migration:481'
   );

COMMIT;
