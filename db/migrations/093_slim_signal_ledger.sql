-- Phase 104 Plan 03 Task 2: drop fire-time duplicate columns from signal_ledger
-- (already in intelligence_features.trading_signals JSONB).
-- WARNING: may trigger recompression on 77 chunks (10-30 min I/O).
-- Run with: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f db/migrations/093_slim_signal_ledger.sql

BEGIN;

-- Drop fire-time duplicate columns (these live in intelligence_features.trading_signals JSONB)
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS entry_price;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS stop_loss;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS targets;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS confidence;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS confluence_score;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS regime_context;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS supporting_factors;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS num_signals_bar;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS num_agreeing;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS num_conflicting;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS resolution_method;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS composite_rank;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS market_context;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS cis_score;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS bucket_scores;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS weights_version;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS determined_at;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS ask_at_signal;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS bid_at_signal;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS market_price_at_signal;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS entry_zone_low;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS entry_zone_high;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS zone_valid_at_signal;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS cis_attribution;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS stop_basis;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS stop_structure_type;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS stop_structure_age_bars;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS structural_stop_distance_atr;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS chandelier_vol_source;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS trailing_stop_tightening_rate;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS raw_cis_score;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS filtered_cis_score;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS calibrated_confidence;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS regime_type_at_fire;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS pre_quality_confidence;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS pre_calibration_confidence;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS entry_type;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS co_fire_count;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS co_fire_partners;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS features_snapshot;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS adjusted_confidence;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS swarm_multiplier;
ALTER TABLE signal_ledger DROP COLUMN IF EXISTS swarm_agent_count;

COMMIT;
