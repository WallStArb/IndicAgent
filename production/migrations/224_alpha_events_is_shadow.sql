-- Migration 224: alpha_events.is_shadow + alpha.publisher.is_shadow APR flag (todo 011)
--
-- Every alpha_events emission today is treated as live with no DB-level distinction from
-- a Phase 144 promotion decision. Adds a first-class is_shadow column (default TRUE -- all
-- existing/future rows are shadow until the operator explicitly promotes) and the APR flag
-- alpha_publisher.py reads to stamp it. Flipping alpha.publisher.is_shadow to 'false' is the
-- sole mechanism for live promotion; the promotion gate criteria are fixed in todo 011's file,
-- not renegotiated at flip time.

BEGIN;

ALTER TABLE alpha_events ADD COLUMN is_shadow BOOLEAN NOT NULL DEFAULT TRUE;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.publisher.is_shadow',
    'bool',
    'true',
    NULL, NULL,
    '[initial_value] Operator-facing promotion switch (todo 011). When true, AlphaPublisher '
    'stamps every emitted alpha_events row is_shadow=true. Flip to false only after all Phase '
    '144 promotion-gate criteria in todo 011 pass on the shadow record -- this is a one-way '
    'live-promotion switch, not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.publisher.is_shadow', 'true', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.publisher.is_shadow', 1, 'true', 'migration_231',
    'Initial value: all alpha_events emissions are shadow until Phase 144 promotion-gate '
    'criteria pass [initial_value]'
)
ON CONFLICT DO NOTHING;

COMMIT;
