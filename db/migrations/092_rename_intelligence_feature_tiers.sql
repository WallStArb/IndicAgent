-- Phase 104 Plan 03 Task 2: rename i1..i8 to concept names on intelligence_features.
-- Safe: works on compressed hypertables in TimescaleDB 2.25.1 — no decompression.
-- Run with: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f db/migrations/092_rename_intelligence_feature_tiers.sql

BEGIN;

ALTER TABLE intelligence_features RENAME COLUMN i1 TO technical_indicators;
ALTER TABLE intelligence_features RENAME COLUMN i2 TO market_context;
ALTER TABLE intelligence_features RENAME COLUMN i3 TO pattern_detections;
ALTER TABLE intelligence_features RENAME COLUMN i4 TO regime_features;
ALTER TABLE intelligence_features RENAME COLUMN i5 TO confluence_scores;
ALTER TABLE intelligence_features RENAME COLUMN i6 TO cross_timeframe_context;
ALTER TABLE intelligence_features RENAME COLUMN i7 TO trading_signals;
ALTER TABLE intelligence_features RENAME COLUMN i8 TO llm_narrative;

COMMIT;
