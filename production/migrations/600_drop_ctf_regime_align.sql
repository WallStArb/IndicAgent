-- Migration 600: drop feature_vectors.ctf_regime_align from the empty kernel table (R2 item 4,
-- lead ruling 2026-11-15).
--
-- The column was a fixed-constant 3-state pseudo-HMM over higher-timeframe bars: transition
-- matrix, means, variances, a 20-bar window and a 0.005 fallback were literals outside APR,
-- never fitted, beside the walk-forward HMM regime kernels. The kernel, its FeatureVector field
-- and its persistence entry are deleted in the same change, so the rerun would write NULL into it
-- forever. Owner-idea check: no ideas doc, ledger row or research spec names it; its one
-- appearance in a counted look is todo 445's 5m sweep, whose recorded cells stay in the
-- selection universe (E18, E21).
--
-- Guarded as migration 577 is: the table must be empty with no chunks, or this raises instead of
-- touching data. On an empty uncompressed table DROP COLUMN is a catalog change (no decompress,
-- no type change), so the compressed-column VACUUM rule does not apply. concept_registry's
-- feature row is NOT touched here: only ConceptRegistryService flips a status (UCR), so the
-- deprecation is a service call at landing (docs/plans/2026-11-15-post-d1-landing-runbook.md).
-- Skipped where the table is absent (an integration replay without it); a second run finds no
-- column to drop.

BEGIN;

DO $$
BEGIN
    IF to_regclass('public.feature_vectors') IS NULL THEN
        RETURN;
    END IF;
    IF EXISTS (SELECT 1 FROM feature_vectors) THEN
        RAISE EXCEPTION 'migration 600: feature_vectors holds rows; drop the column by the '
            'compressed-column procedure instead';
    END IF;
    IF EXISTS (SELECT 1 FROM timescaledb_information.chunks
               WHERE hypertable_schema = 'public' AND hypertable_name = 'feature_vectors') THEN
        RAISE EXCEPTION 'migration 600: feature_vectors has chunks; refusing';
    END IF;

    ALTER TABLE feature_vectors
        DROP COLUMN IF EXISTS ctf_regime_align;
END $$;

COMMIT;
