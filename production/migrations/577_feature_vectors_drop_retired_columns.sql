-- Migration 577: drop the retired columns from the empty kernel feature_vectors (todo 591; lead
-- ruling 2026-11-05).
--
-- The registry no longer derives these 13 columns, so the rerun would write NULL into them
-- forever: the eleven universe-dead session columns todo 584 item 6 (D5) retired (migration
-- 561 kept them physically until "the rebuild's summary card", which referred to rows migration
-- 569 discarded) plus hmm_vol_prob_elevated (584 item 3, todo 583) and sweep_detected, which no
-- kernel produces either. After this the table's columns equal the registry derivation
-- (tests/unit/intelligence/test_feature_vectors_schema.py, and the integration schema test).
--
-- Guarded: the table must be empty with no chunks (migration 570 left it so; the rerun has not
-- started), or this raises instead of touching data. On an empty uncompressed table DROP COLUMN
-- is a catalog change: no decompress, no type change, so the compressed-column VACUUM rule
-- (D-16) does not apply. Skipped where the table is absent (an integration replay without it).

BEGIN;

DO $$
BEGIN
    IF to_regclass('public.feature_vectors') IS NULL THEN
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM feature_vectors) THEN
        RAISE EXCEPTION 'migration 577: feature_vectors holds rows; drop the columns by the '
            'compressed-column procedure instead';
    END IF;
    IF EXISTS (SELECT 1 FROM timescaledb_information.chunks
               WHERE hypertable_schema = 'public' AND hypertable_name = 'feature_vectors') THEN
        RAISE EXCEPTION 'migration 577: feature_vectors has chunks; refusing';
    END IF;

    ALTER TABLE feature_vectors
        DROP COLUMN amd_distribution_direction,
        DROP COLUMN amd_manipulation_detected,
        DROP COLUMN amd_phase,
        DROP COLUMN asian_session_high_dist_atr,
        DROP COLUMN asian_session_low_dist_atr,
        DROP COLUMN hmm_vol_prob_elevated,
        DROP COLUMN in_london_kz,
        DROP COLUMN manip_strength,
        DROP COLUMN overnight_high_dist_atr,
        DROP COLUMN overnight_low_dist_atr,
        DROP COLUMN overnight_range_pct,
        DROP COLUMN ret_div_1m_5m,
        DROP COLUMN sweep_detected;
END $$;

COMMIT;
