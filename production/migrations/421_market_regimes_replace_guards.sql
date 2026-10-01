-- Migration 421: guards and decision record for the market_regimes replace
-- (phase 186 follow-up to 186-18, todo 420)
--
-- 1. market_regimes_override: append-only record of every reviewed override of the replace
--    guards. cross_sectional_regime_model.py refuses a (regime_group, tf) replace whose orphaned
--    or changed rows exceed their APR fraction of the stored rows; an operator approves it with
--    `--accept-orphan-delete=N` / `--accept-changed=N` and a `--reason`, and the decision (cell,
--    counts, accepted counts, operator, reason, UTC time) is inserted in the same transaction
--    as the write, so the record exists exactly when the rows moved. Rows are never edited or
--    deleted (row trigger) and the table cannot be truncated (statement trigger). No existing
--    ledger fits: config_history records APR values, research_run is the research runner's.
--
-- 2. alpha.regime.cross_sectional.max_changed_fraction: the guard migration 419's key does not
--    cover. A broken peer set can rewrite every label without removing a timestamp. Default 0.05
--    from the 186-18 dry run (evidence/186-18-market-regimes-dry-run.json): a rerun on unchanged
--    inputs changes nothing, and the observed changed fractions today are equity 5m 0.089, 15m
--    0.179, 1h 0.167, 1d 0.675; commodity 5m 0.0006, 15m 0.727, 1h 0.719, 1d 0.960; fx 1h
--    0.012; rates and the other fx cells 0. The stored history predates the label logic it is
--    compared with, so the first reviewed run on equity and commodity needs --accept-changed.
--
-- 3. infra.regime_cross_sectional.feature_vectors_probe_timeout_ms: statement timeout of the
--    dry run's feature_vectors join (the DISTINCT bar_ts scan takes about 4 s per tf).
--
-- Guarded: CREATE ... IF NOT EXISTS, ON CONFLICT DO NOTHING, idempotent history rows.

BEGIN;

CREATE TABLE IF NOT EXISTS market_regimes_override (
    override_id       bigserial PRIMARY KEY,
    decided_at        timestamptz NOT NULL,
    regime_group      text        NOT NULL,
    tf                text        NOT NULL,
    stored            bigint      NOT NULL CHECK (stored >= 0),
    orphaned          bigint      NOT NULL CHECK (orphaned >= 0),
    changed           bigint      NOT NULL CHECK (changed >= 0),
    accepted_orphans  bigint      NOT NULL CHECK (accepted_orphans >= 0),
    accepted_changed  bigint      NOT NULL CHECK (accepted_changed >= 0),
    operator          text        NOT NULL CHECK (length(btrim(operator)) > 0),
    reason            text        NOT NULL CHECK (length(btrim(reason)) > 0)
);

COMMENT ON TABLE market_regimes_override IS
    'Append-only record of reviewed overrides of the market_regimes replace guards '
    '(migration 421, todo 420): written by cross_sectional_regime_model.py in the same '
    'transaction as the rows it approved.';

CREATE OR REPLACE FUNCTION fn_market_regimes_override_no_change()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'market_regimes_override is append-only: % is not allowed', TG_OP
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_market_regimes_override_no_update_delete ON market_regimes_override;
CREATE TRIGGER trg_market_regimes_override_no_update_delete
    BEFORE UPDATE OR DELETE ON market_regimes_override
    FOR EACH ROW EXECUTE FUNCTION fn_market_regimes_override_no_change();

DROP TRIGGER IF EXISTS trg_market_regimes_override_no_truncate ON market_regimes_override;
CREATE TRIGGER trg_market_regimes_override_no_truncate
    BEFORE TRUNCATE ON market_regimes_override
    FOR EACH STATEMENT EXECUTE FUNCTION fn_market_regimes_override_no_change();

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.regime.cross_sectional.max_changed_fraction',
    'float',
    '0.05',
    0, 1,
    '[initial_estimate] Largest fraction of a (regime_group, tf) market_regimes history that '
    'cross_sectional_regime_model.py may rewrite as changed rows (same timestamp, different '
    'label or probability vector) without a reviewed --accept-changed=N override; guards '
    'against a broken peer set relabeling a history without removing a timestamp. Not an ML '
    'learning target.'
),
(
    'infra.regime_cross_sectional.feature_vectors_probe_timeout_ms',
    'int',
    '600000',
    1000, NULL,
    '[initial_estimate] statement_timeout in milliseconds of the cross_sectional_regime_model.py '
    '--dry-run feature_vectors join probe (a DISTINCT bar_ts scan, about 4 s per tf). Not an ML '
    'learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('alpha.regime.cross_sectional.max_changed_fraction', '0.05', 1),
    ('infra.regime_cross_sectional.feature_vectors_probe_timeout_ms', '600000', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), v.config_key, 1, v.config_value, 'migration_421', v.reason
FROM (VALUES
    ('alpha.regime.cross_sectional.max_changed_fraction', '0.05',
     'Initial value [initial_estimate]: rewrite guard on the market_regimes replace (todo 420)'),
    ('infra.regime_cross_sectional.feature_vectors_probe_timeout_ms', '600000',
     'Initial value [initial_estimate]: dry-run probe timeout')
) AS v(config_key, config_value, reason)
WHERE NOT EXISTS (
    SELECT 1 FROM config_history h
    WHERE h.config_key = v.config_key AND h.changed_by = 'migration_421'
);

COMMIT;
