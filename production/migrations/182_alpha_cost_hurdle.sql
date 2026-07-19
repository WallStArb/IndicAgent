-- Migration 182: Cost-aware CI gate for alpha_publisher (todo 004)
-- Adds per-TF cost hurdle APR keys and cost_hurdle audit column to alpha_events.
--
-- Design: alpha_publisher replaces the hardcoded `ci_lower > 0` directional gate
-- with `ci_lower > cost_hurdle(tf)`. Initial values are 0.0 (no behavior change)
-- and will be calibrated from corpus data once live. See todo 004.

-- APR keys -------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, description) VALUES
  ('alpha.quant.cost_hurdle.5m',  'float',
   'Min CI lower bound (alpha_score units) for 5m emissions. Cost-aware directional gate: '
   'ci_lower must exceed this to pass. Initial 0.0 = no-op; raise after calibration from '
   'corpus data. [initial_estimate]'),
  ('alpha.quant.cost_hurdle.15m', 'float',
   'Min CI lower bound (alpha_score units) for 15m emissions. [initial_estimate]'),
  ('alpha.quant.cost_hurdle.1h',  'float',
   'Min CI lower bound (alpha_score units) for 1h emissions. Costs negligible at hourly '
   'horizon; set to 0.0. [user_preference]'),
  ('alpha.quant.cost_hurdle.1d',  'float',
   'Min CI lower bound (alpha_score units) for 1d emissions. Costs negligible at daily '
   'horizon; set to 0.0. [user_preference]')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
  ('alpha.quant.cost_hurdle.5m',  '0.0', 1),
  ('alpha.quant.cost_hurdle.15m', '0.0', 1),
  ('alpha.quant.cost_hurdle.1h',  '0.0', 1),
  ('alpha.quant.cost_hurdle.1d',  '0.0', 1)
ON CONFLICT (config_key) DO NOTHING;

-- Audit column ----------------------------------------------------------------

ALTER TABLE alpha_events
  ADD COLUMN IF NOT EXISTS cost_hurdle DOUBLE PRECISION NOT NULL DEFAULT 0.0;

COMMENT ON COLUMN alpha_events.cost_hurdle IS
  'Cost hurdle value (alpha_score units) that was in effect when this event was emitted. '
  'Records the APR value at publish time for audit trail. Zero = no cost gate applied.';
