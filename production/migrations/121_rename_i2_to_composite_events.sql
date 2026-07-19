-- Migration 121: Rename i2 JSONB column to composite_events.
-- i2 was added in migration 124 using the tier-code name.
-- Migration 126 reverted i1/i3/i4/i5 to functional names but missed i2.
-- composite_events matches the I2 tier description: crossovers, threshold
-- crossings, and extremes from composite indicator plugins.
ALTER TABLE intelligence_features RENAME COLUMN i2 TO composite_events;
