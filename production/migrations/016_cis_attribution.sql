-- 016_cis_attribution.sql
-- Add per-constituent CIS attribution to signal_ledger for alpha discovery.

ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS cis_attribution JSONB;

COMMENT ON COLUMN signal_ledger.cis_attribution IS
  'Per-constituent CIS contributions at signal fire time. Structure: {bucket: {signal_name: contribution_to_final_cis_score}}. Immutable after write.';
