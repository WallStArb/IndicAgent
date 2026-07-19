-- Add timeframe column to calibration_curves and update PK to (setup_plugin, timeframe, symbol).
--
-- Before this migration, calibration_curves had PK (setup_plugin, symbol) with timeframe
-- embedded in the curve_data JSONB. This prevented storing multiple timeframe curves for
-- the same (setup_plugin, symbol) pair, which is required for CIS-level calibration
-- (setup_plugin='_cis_') across 1m / 5m / 15m / 1h timeframes.
--
-- The table was empty (0 rows) when this migration was written.

ALTER TABLE calibration_curves
    ADD COLUMN timeframe text NOT NULL DEFAULT '*';

ALTER TABLE calibration_curves
    DROP CONSTRAINT calibration_curves_pkey;

ALTER TABLE calibration_curves
    ADD PRIMARY KEY (setup_plugin, timeframe, symbol);
