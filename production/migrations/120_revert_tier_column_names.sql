-- Migration 120: Revert tier-code column names to functional names.
-- i1/i3/i4/i5 are internal pipeline codes, not domain concepts.
-- A quant reading the schema must understand columns without a reference.
ALTER TABLE intelligence_features RENAME COLUMN i1 TO technical_indicators;
ALTER TABLE intelligence_features RENAME COLUMN i3 TO regime_features;
ALTER TABLE intelligence_features RENAME COLUMN i4 TO confluence_scores;
ALTER TABLE intelligence_features RENAME COLUMN i5 TO pattern_detections;
