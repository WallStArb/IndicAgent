-- 463: the Alpaca second-tape basis tolerance (phase 521 admission build).
--
-- The D7 `alpaca_basis` condition (flag-only; docs/plans/2026-10-09-alpaca-5m-admission-build.md)
-- compares stored IBKR and stored Alpaca 5m closes on dual-tape names and flags
-- when the difference exceeds max(this tolerance, half-tick/mid). The tick term is
-- derived from instrument metadata (get_tick_size, APR-exempt); mid is defined as
-- (stored IBKR close + stored Alpaca close) / 2 on the sampled slot (the first
-- stored bar of each overlap session, per the plan's deterministic sample rule).
-- Pilot-measured: sub-tick tape differences are the honest agreement floor on
-- 1-cent-tick instruments (T1 results in the plan doc). Dated before the first
-- Alpaca apply per the 189 lane's review requirement. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('threshold.bar_integrity.alpaca_basis_tolerance_bp', 'float', '1.0', 0, 1000,
 '[pilot-measured 2026-10-09] Basis tolerance in bp of mid for the D7 alpaca_basis flag on dual-tape 5m names, where mid = (stored IBKR close + stored Alpaca close) / 2 on the sampled slot. The effective tolerance is max(this value, half-tick/mid from get_tick_size). Measured by the Alpaca integration pilot: sub-tick vendor tape differences dominate below 2 bp on 1-cent-tick instruments (docs/plans/2026-10-09-alpaca-5m-admission-build.md, T1 results). Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('threshold.bar_integrity.alpaca_basis_tolerance_bp', '1.0', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_463',
       'Initial Alpaca second-tape basis tolerance [pilot-measured 2026-10-09], dated before the first Alpaca apply'
  FROM config_state
 WHERE config_key = 'threshold.bar_integrity.alpaca_basis_tolerance_bp'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_463');

COMMIT;
