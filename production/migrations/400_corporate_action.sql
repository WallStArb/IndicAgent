-- Migration 400: corporate_action, the split-seam audit's append-only record (phase 185
-- plan 15, D-21, D-24)
--
-- A corpus stored incrementally across a split keeps old days on the old price scale
-- while a fresh fetch is on one scale. The seam audit (scripts/ops/bars/ops_seam_audit.py)
-- compares the two, and each constant-ratio run that snaps to a rational split factor is
-- recorded here with the request ids that evidence it. Rows are permanent: UPDATE, DELETE
-- and TRUNCATE raise for every role, superuser included; a correction is a new row whose
-- supersedes points at the row it replaces. corporate_action_current hides superseded rows.
--
-- The writer is bar_derivation_writer (NOLOGIN, reached through SET LOCAL ROLE), created in
-- migration 380. The seam thresholds and the bootstrap window are APR keys.

BEGIN;

CREATE TABLE IF NOT EXISTS corporate_action (
    action_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol text NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
    action_type text NOT NULL CHECK (action_type IN ('split', 'reverse_split')),
    effective_date date NOT NULL,
    factor double precision NOT NULL CHECK (factor > 0 AND factor <> 'Infinity' AND factor <> 'NaN'),
    inferred_by text NOT NULL CHECK (inferred_by IN ('seam_audit', 'nightly_overlap')),
    evidence_request_ids uuid[] NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}',
    recorded_at timestamptz NOT NULL DEFAULT now(),
    supersedes uuid NULL REFERENCES corporate_action(action_id),
    batch_id uuid REFERENCES bar_derivation_batch(batch_id)
);

COMMENT ON TABLE corporate_action IS
    'Append-only record of splits and reverse splits inferred from a stored-vs-fresh close '
    'ratio (migration 400, D-21/D-24). factor is stored/fresh on the old scale (2.0 = 2-for-1, '
    '0.125 = 1-for-8); effective_date is the last day on the old scale. evidence_request_ids '
    'name the ohlcv_request rows that carried the ratio. Permanent: UPDATE, DELETE and TRUNCATE '
    'raise; corrections are new rows with supersedes.';

CREATE INDEX IF NOT EXISTS idx_corporate_action_symbol_date
    ON corporate_action (symbol, effective_date);

CREATE OR REPLACE FUNCTION corporate_action_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION corporate_action_append_only() IS
    'Refuses UPDATE, DELETE (row trigger) and TRUNCATE (statement trigger) on corporate_action '
    '(migration 400): a recorded split is corrected by a superseding row, never rewritten.';

DROP TRIGGER IF EXISTS trg_corporate_action_append_only ON corporate_action;

CREATE TRIGGER trg_corporate_action_append_only
    BEFORE UPDATE OR DELETE ON corporate_action
    FOR EACH ROW
    EXECUTE FUNCTION corporate_action_append_only();

DROP TRIGGER IF EXISTS trg_corporate_action_no_truncate ON corporate_action;

CREATE TRIGGER trg_corporate_action_no_truncate
    BEFORE TRUNCATE ON corporate_action
    FOR EACH STATEMENT
    EXECUTE FUNCTION corporate_action_append_only();

CREATE OR REPLACE VIEW corporate_action_current AS
SELECT ca.*
FROM corporate_action ca
WHERE NOT EXISTS (
    SELECT 1 FROM corporate_action newer WHERE newer.supersedes = ca.action_id
);

COMMENT ON VIEW corporate_action_current IS
    'corporate_action rows that no later row supersedes (migration 400).';

GRANT INSERT, SELECT ON corporate_action TO bar_derivation_writer;
GRANT SELECT ON corporate_action_current TO bar_derivation_writer;
REVOKE UPDATE, DELETE, TRUNCATE ON corporate_action FROM PUBLIC;

-- APR seeds: seam thresholds (D-24) and the bootstrap fetch window.
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    ('threshold.seam.rel_tol', 'float', '0.002', '0.00001', '0.5', '[initial_estimate] Relative tolerance of the stored/fresh close ratio inside one seam run, and the distance from 1 below which a day is on one scale (split-seam audit, plan 15). Not an ML learning target.'),
    ('threshold.seam.min_run', 'int', '5', '1', '1000', '[initial_estimate] Fewest consecutive days a constant-ratio run needs to count as a seam (split-seam audit, plan 15). Not an ML learning target.'),
    ('threshold.seam.ratio_snap_tol', 'float', '0.01', '0.00001', '0.5', '[initial_estimate] Largest gap between a seam factor and the nearest rational p/q (p, q <= 50) for the seam to be recorded as a split; otherwise it stays unexplained (plan 15). Not an ML learning target.'),
    ('infra.bar_campaign.bootstrap_years', 'int', '20', '1', '40', '[conventional] Years of TRADES and ADJUSTED_LAST 1d history the D1 bootstrap fetch requests back from now, one request per series per name (RESEARCH, plan 15). Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.seam.rel_tol', '0.002', 1),
    ('threshold.seam.min_run', '5', 1),
    ('threshold.seam.ratio_snap_tol', '0.01', 1),
    ('infra.bar_campaign.bootstrap_years', '20', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'threshold.seam.rel_tol', 1, '0.002', 'migration_400', 'Initial value [initial_estimate]'),
    (NOW(), 'threshold.seam.min_run', 1, '5', 'migration_400', 'Initial value [initial_estimate]'),
    (NOW(), 'threshold.seam.ratio_snap_tol', 1, '0.01', 'migration_400', 'Initial value [initial_estimate]'),
    (NOW(), 'infra.bar_campaign.bootstrap_years', 1, '20', 'migration_400', 'Initial value [conventional]')
ON CONFLICT DO NOTHING;

COMMIT;
