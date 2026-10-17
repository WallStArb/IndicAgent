-- Migration 500: seed infra.selection_gate.statement_timeout_s (phase 191 plan 16).
--
-- ops_selection_gate.py sets its connection's statement timeout from an APR key. It had been
-- reading infra.raw_backfill.statement_timeout_s (migration 381, the one-shot backfill's key)
-- as a squatter; plan 191-16 deletes the backfill and migration 499 retires that key, so the
-- gate gets its own key at the same live value the old key held (7200 s, migration 381's seed;
-- the per-tool key follows the infra.canonical_swap.statement_timeout_s precedent of
-- migration 492). Reader: scripts/ops/bars/ops_selection_gate.py (_TIMEOUT_KEY).
-- Not an ML learning target.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'infra.selection_gate.statement_timeout_s',
        'int',
        '7200',
        1, NULL,
        '[initial_estimate] Statement timeout (seconds) for the selection gate connection (phase 191 plan 16): --compare and --emit-spans scan full canonical series per name, so the gate needs a long-running-statement budget of its own. Seed value carries over infra.raw_backfill.statement_timeout_s (migration 381) as plan 191-16 deleted that key with ops_raw_backfill.py. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.selection_gate.statement_timeout_s', '7200', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (now(), 'infra.selection_gate.statement_timeout_s', 1, '7200', 'migration_500',
        'seed: the selection gate statement timeout, split from infra.raw_backfill.statement_timeout_s retired by migration 499 (phase 191 plan 16)');

COMMIT;
