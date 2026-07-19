-- Migration 119: Rename legacy tier columns to match canonical tier names.
-- smc and cross_timeframe_context already correct.
-- market_context (cross-asset) retains its name.
ALTER TABLE intelligence_features RENAME COLUMN technical_indicators TO i1;
ALTER TABLE intelligence_features RENAME COLUMN pattern_detections TO i5;
ALTER TABLE intelligence_features RENAME COLUMN regime_features TO i3;
ALTER TABLE intelligence_features RENAME COLUMN confluence_scores TO i4;
