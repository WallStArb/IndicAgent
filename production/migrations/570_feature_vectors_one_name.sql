-- Migration 570: one feature table name (todo 584 decision item 3, owner 2026-11-04; plan 186-27
-- re-scoped).
--
-- The old feature_vectors (89 GB, v1 schema, stale since 2026-09-24) is dead cache: its summary
-- card is docs/research/summary-cards/cache-feature-vectors-v1.md (186-01, D-06) and
-- tests/unit/test_summary_cards.py DROP_TABLES covers it. The empty feature_vectors_v2 (rows
-- discarded by migration 569) takes the name, so the rerun writes straight into feature_vectors.
-- No view depends on either table (pg_depend checked 2026-11-04); neither has grants beyond the
-- owner. The DROP comes first and both statements are literal text so
-- tests/unit/_migration_catalog.py resolves the final names.
--
-- Provenance: the 1,647 provenance_batch rows with target_table 'feature_vectors_v2' are all
-- 'superseded' (migration 569) and stay as history, never rewritten. Every reader selects
-- status = 'completed' for target 'feature_vectors', so none of them is read again.
--
-- No compression policy. bulk_load refuses a unit whose range_start a scheduled policy's
-- compress_after already covers, and every rebuild unit starts on Jan 1 of the first bar's year,
-- so a policy would refuse the rerun. The rebuild writer compresses chunks itself, at the end of
-- every stage, once no pending unit can still write into them (todo 584 item 4).
--
-- Nothing here decompresses or alters a column type, so no VACUUM step (D-16): DROP frees the old
-- table's space at commit and the renamed table is empty.
--
-- Guarded like 526 and 559: the integration replay (baseline 433, then migration 462's
-- DROP TABLE IF EXISTS feature_vectors_v2) has no feature_vectors_v2, so there the swap is a
-- no-op. Production has it, and the swap runs.

BEGIN;

DO $$
BEGIN
    IF to_regclass('public.feature_vectors_v2') IS NOT NULL THEN
        DROP TABLE feature_vectors;

        ALTER TABLE feature_vectors_v2 RENAME TO feature_vectors;
        ALTER INDEX feature_vectors_v2_pkey RENAME TO feature_vectors_pkey;
        ALTER INDEX feature_vectors_v2_bar_ts_idx RENAME TO feature_vectors_bar_ts_idx;
        ALTER TABLE feature_vectors RENAME CONSTRAINT feature_vectors_v2_symbol_not_null
            TO feature_vectors_symbol_not_null;
        ALTER TABLE feature_vectors RENAME CONSTRAINT feature_vectors_v2_tf_not_null
            TO feature_vectors_tf_not_null;
        ALTER TABLE feature_vectors RENAME CONSTRAINT feature_vectors_v2_bar_ts_not_null
            TO feature_vectors_bar_ts_not_null;

        COMMENT ON TABLE feature_vectors IS
            'The feature table, one row per (symbol, tf, bar_ts), columns derived from the '
            'kernel registry. Sole writer: bulk_load for the rebuild writer '
            '(services/backfill_feature_factory.py). Lineage = provenance_batch records; no '
            'per-row provenance column (D-34/D-24). No compression policy (bulk_load refuses '
            'ranges a policy covers); the writer compresses chunks no pending unit can still '
            'write into.';
    END IF;
END $$;

UPDATE config_schema
   SET description = replace(description, 'feature_vectors_v2', 'feature_vectors')
 WHERE description LIKE '%feature_vectors\_v2%';

COMMIT;
