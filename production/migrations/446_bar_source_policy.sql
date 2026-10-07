-- Migration 446: bar_source_policy, the d2-v2 fallback keys, and the tradeable view's fallback
-- volume (phase 185 plan 36; docs/plans/2026-10-06-data-layer-integrity-design.md section 2)
--
-- bar_source_policy is the only place a bar source choice lives. One row per decision:
-- (timeframe, symbol or NULL for the timeframe default, [valid_from, valid_to)) names the
-- ingress mode, the primary source and the fallback source. It replaces two source rules held
-- in code: the "a loaded Tradier load owns the name" predicate (ohlcv_load outcome 'loaded') and
-- the Tradier loader's inline rule tradier-v1. The daily rule d2-v2
-- (src/intelligence/bars/daily_rule.py) resolves every 1d date through it, and a date no row
-- covers raises (a missing policy row fails loud, design section 8).
--
-- Rows are decisions, not measurements. A per-name measurement (the head seam's overlap
-- ratio, a vendor basis run) is recomputed by the derivation on every run and lives in
-- bar_quality_flag (rule fallback_seam) or the integrity report; evidence holds only what a
-- decision was made on.
--
-- Append-only, the listing_venue pattern (migration 408): no two rows of one (timeframe,
-- symbol) series overlap (EXCLUDE), the only UPDATE closes an open row (valid_to from NULL to a
-- date, every other column unchanged), and DELETE and TRUNCATE raise for every role. A changed
-- decision closes the old row and inserts a new one. Single writer: this migration seeds the
-- timeframe defaults; the next writer is 185-37's exception CLI (per-name rows on evidence, for
-- example REX's Tradier seam), registered in tests/unit/test_single_writer_registry.py when it
-- lands. No role holds INSERT until then. The derivation role reads it; the D7 audit connects
-- as the database owner (Settings DSN) and needs no grant.
--
-- Seeds, the real state on 2026-10-07:
--   1d   observed, primary tradier, fallback ibkr (SMART TRADES): design section 2
--   5m   direct, ibkr; 1m direct, ibkr (kept, not fetched beyond what exists)
--   15m  derived from 5m; 1h derived from 5m (grid-v1)
--   4h   direct, ibkr: its 2,184 vendor rows are kept, not fetched and not derived. The design
--        lists 4h as derived; deriving it is in no migration step, so the row records what is
--        true, not the aim.
--
-- APR: threshold.bar_integrity.fallback_basis_window_sessions (20) and
-- threshold.bar_integrity.fallback_basis_tolerance_bp (10) parameterize d2-v2's interior
-- fallback admission (the median IBKR/Tradier close ratio over the nearest common sessions).
--
-- market_data_ohlcv_tradeable: an admitted fallback bar (source ibkr_fallback) reads NULL
-- volume, exactly as ibkr_venue does since migration 374: the IBKR SMART volume (median 0.80 of
-- Tradier's consolidated volume) is never spliced into a Tradier series and never rescaled.
-- Column list and order unchanged (migration 381's definition otherwise).
--
-- Idempotent: the table, triggers and grants are IF NOT EXISTS / DROP IF EXISTS, the seed rows
-- insert only where no open default row exists, and the APR rows are ON CONFLICT DO NOTHING.

BEGIN;

CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE IF NOT EXISTS bar_source_policy (
    policy_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    timeframe text NOT NULL CHECK (timeframe IN ('1d', '5m', '1m', '15m', '1h', '4h')),
    symbol text NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
    valid_from date NOT NULL,
    valid_to date NULL,
    ingress_mode text NOT NULL CHECK (ingress_mode IN ('observed', 'direct', 'derived')),
    primary_source text NOT NULL CHECK (primary_source IN ('tradier', 'ibkr', 'derived')),
    fallback_source text NULL
        CHECK (fallback_source IS NULL OR fallback_source IN ('tradier', 'ibkr')),
    reason text NOT NULL,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CHECK (fallback_source IS DISTINCT FROM primary_source),
    CHECK ((ingress_mode = 'derived') = (primary_source = 'derived')),
    CONSTRAINT ex_bar_source_policy_no_overlap EXCLUDE USING gist (
        timeframe WITH =,
        (coalesce(symbol, '')) WITH =,
        daterange(valid_from, valid_to, '[)') WITH &&
    )
);

COMMENT ON TABLE bar_source_policy IS
    'The only place a bar source choice lives (migration 446, plan 185-36, data layer integrity '
    'design section 2): per (timeframe, symbol or NULL default, [valid_from, valid_to)) the '
    'ingress mode, primary and fallback source. Decisions, not measurements. Append-only: the '
    'only update closes an open row; DELETE and TRUNCATE raise. Rows never overlap per series. '
    'd2-v2 raises on a date no row covers.';

CREATE OR REPLACE FUNCTION bar_source_policy_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.valid_to IS NOT NULL THEN
            RAISE EXCEPTION 'bar_source_policy: row % is closed and immutable', OLD.policy_id
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.valid_to IS NULL THEN
            RAISE EXCEPTION 'bar_source_policy: an update must close open row % with a date',
                OLD.policy_id USING ERRCODE = 'check_violation';
        END IF;
        IF (NEW.policy_id, NEW.timeframe, NEW.symbol, NEW.valid_from, NEW.ingress_mode,
            NEW.primary_source, NEW.fallback_source, NEW.reason, NEW.evidence, NEW.recorded_at)
           IS DISTINCT FROM
           (OLD.policy_id, OLD.timeframe, OLD.symbol, OLD.valid_from, OLD.ingress_mode,
            OLD.primary_source, OLD.fallback_source, OLD.reason, OLD.evidence, OLD.recorded_at) THEN
            RAISE EXCEPTION 'bar_source_policy: only valid_to may change (close the row, insert a new one)'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    ELSE
        RAISE EXCEPTION 'bar_source_policy is append-only: % is not allowed', TG_OP
            USING ERRCODE = 'check_violation';
    END IF;
END $$;

COMMENT ON FUNCTION bar_source_policy_append_only() IS
    'Allows INSERT and the one UPDATE that closes an open row (valid_to NULL to a date); '
    'refuses every other UPDATE, DELETE and TRUNCATE on bar_source_policy (migration 446).';

DROP TRIGGER IF EXISTS trg_bar_source_policy_append_only ON bar_source_policy;

CREATE TRIGGER trg_bar_source_policy_append_only
    BEFORE INSERT OR UPDATE OR DELETE ON bar_source_policy
    FOR EACH ROW EXECUTE FUNCTION bar_source_policy_append_only();

DROP TRIGGER IF EXISTS trg_bar_source_policy_no_truncate ON bar_source_policy;

CREATE TRIGGER trg_bar_source_policy_no_truncate
    BEFORE TRUNCATE ON bar_source_policy
    FOR EACH STATEMENT EXECUTE FUNCTION bar_source_policy_append_only();

REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON bar_source_policy FROM PUBLIC;
GRANT SELECT ON bar_source_policy TO bar_derivation_writer;

-- Timeframe defaults (symbol NULL), open from 1990-01-01, before any stored bar.
INSERT INTO bar_source_policy
    (timeframe, symbol, valid_from, ingress_mode, primary_source, fallback_source, reason, evidence)
SELECT s.timeframe, NULL::text, DATE '1990-01-01', s.ingress_mode, s.primary_source,
       s.fallback_source, s.reason, s.evidence::jsonb
FROM (VALUES
    ('1d', 'observed', 'tradier', 'ibkr', 'One 1d vendor for the whole cross-section (consolidated volume); IBKR SMART TRADES fills the head with a recorded seam and an interior hole only within the fallback basis tolerance; fallback volume reads NULL. docs/plans/2026-10-06-data-layer-integrity-design.md section 2.', '{"spec": "docs/plans/2026-10-06-data-layer-integrity-design.md#2-source-policy", "plan": "185-36"}'),
    ('5m', 'direct', 'ibkr', NULL, 'One vendor, no second view: the stored row is the raw IBKR SMART answer; restatements go to ohlcv_revision. docs/plans/2026-10-06-data-layer-integrity-design.md sections 2 and 3.', '{"spec": "docs/plans/2026-10-06-data-layer-integrity-design.md#3-ingress-modes", "plan": "185-36"}'),
    ('1m', 'direct', 'ibkr', NULL, 'Kept and not fetched (design section 10 non-goal); the stored rows are IBKR answers. docs/plans/2026-10-06-data-layer-integrity-design.md section 3.', '{"spec": "docs/plans/2026-10-06-data-layer-integrity-design.md#3-ingress-modes", "plan": "185-36"}'),
    ('4h', 'direct', 'ibkr', NULL, 'Real state, not the design aim: the 2,184 IBKR vendor rows are kept, not fetched and not derived (deriving 4h is in no migration step). docs/plans/2026-10-06-data-layer-integrity-design.md sections 2 and 10.', '{"spec": "docs/plans/2026-10-06-data-layer-integrity-design.md#10-deletions-and-non-goals", "plan": "185-36", "rows_2026_10_07": 2184}'),
    ('15m', 'derived', 'derived', NULL, 'Session-anchored aggregation of 5m (grid-v1); vendor 15m stays in the archive as the parity reference. docs/plans/2026-10-06-data-layer-integrity-design.md section 5.', '{"spec": "docs/plans/2026-10-06-data-layer-integrity-design.md#5-derived-timeframes-and-the-5m-fetch", "plan": "185-36"}'),
    ('1h', 'derived', 'derived', NULL, 'Session-anchored aggregation of 5m (grid-v1); vendor 1h stays in the archive as the parity reference. docs/plans/2026-10-06-data-layer-integrity-design.md section 5.', '{"spec": "docs/plans/2026-10-06-data-layer-integrity-design.md#5-derived-timeframes-and-the-5m-fetch", "plan": "185-36"}')
) AS s (timeframe, ingress_mode, primary_source, fallback_source, reason, evidence)
WHERE NOT EXISTS (
    SELECT 1 FROM bar_source_policy p
    WHERE p.timeframe = s.timeframe AND p.symbol IS NULL AND p.valid_to IS NULL
);

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('threshold.bar_integrity.fallback_basis_window_sessions', 'int', '20', 1, 1000,
 '[initial_estimate] Common sessions (both vendors answered, current scale) the d2-v2 daily rule measures the IBKR/Tradier close ratio over: the first N after Tradier''s head for the fallback_seam record, the N nearest an interior hole (both sides, ties to the earlier session) for admission. Not an ML learning target.'),
('threshold.bar_integrity.fallback_basis_tolerance_bp', 'float', '10', 0, 10000,
 '[initial_estimate] Largest |median IBKR/Tradier close ratio - 1| in basis points at which d2-v2 admits an IBKR bar into an interior Tradier hole; outside it the date has no canonical bar. 96% of interior IBKR bars sat within 10 bp on 2026-10-06 (design section 2). Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.bar_integrity.fallback_basis_window_sessions', '20', 1),
    ('threshold.bar_integrity.fallback_basis_tolerance_bp', '10', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_446',
       'Initial value for the d2-v2 fallback basis test [initial_estimate]'
  FROM config_state
 WHERE config_key IN ('threshold.bar_integrity.fallback_basis_window_sessions',
                      'threshold.bar_integrity.fallback_basis_tolerance_bp')
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_446');

CREATE OR REPLACE VIEW market_data_ohlcv_tradeable AS
SELECT "timestamp",
       symbol,
       timeframe,
       open,
       high,
       low,
       close,
       CASE WHEN source IN ('ibkr_venue', 'ibkr_fallback') THEN NULL ELSE volume END AS volume,
       source,
       base,
       price_sanity_status
FROM market_data_ohlcv
WHERE volume > 0
  AND price_sanity_status IS DISTINCT FROM 'confirmed_corrupt'
  AND NOT EXISTS (
      SELECT 1 FROM bar_quality_flag q
      WHERE q.quarantine
        AND q.symbol = market_data_ohlcv.symbol
        AND q.timeframe = market_data_ohlcv.timeframe
        AND q."timestamp" = market_data_ohlcv."timestamp"
  );
COMMENT ON VIEW market_data_ohlcv_tradeable IS 'Compute/measurement read boundary: traded bars (volume > 0), venue and admitted 1d fallback volume nulled (ibkr_venue, ibkr_fallback; migration 446), confirmed_corrupt and quarantine-flagged bars (bar_quality_flag) excluded. Raw-table access outside this needs a test_market_data_ohlcv_boundary.py allow-list entry.';

COMMIT;
