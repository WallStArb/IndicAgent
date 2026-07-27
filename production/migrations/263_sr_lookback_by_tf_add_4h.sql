-- Migration 263: feature.sr.lookback_by_tf -- add missing "4h" entry
--
-- Todo 178 IN-02 (Phase 163 review): FeatureVectorPipeline._STANDARD_TFS includes "4h", but
-- the seeded/default lookback dict (migration 255) has no "4h" key, so _compute_sr_dist_atr()
-- silently falls back to the generic 120-bar default via .get(tf, 120) -- not incorrect
-- (matches the pre-existing _CTF_HIGHER_TF mapping's same 4h gap, likely intentional), just
-- an unconfigured tunable. Migration 255 is already applied and can't be retroactively
-- changed, hence a new migration rather than editing 255.
--
-- Value: 90, interpolating 1h's 120 and 1d's 60 (todo 178's own suggestion) -- a reasonable
-- starting point between the two neighboring timeframes' lookback windows, not empirically
-- tuned (no live 4h S/R usage to calibrate against yet).

BEGIN;

UPDATE config_state
SET config_value = '{"1m":60,"5m":60,"15m":80,"1h":120,"4h":90,"1d":60}',
    version = version + 1
WHERE config_key = 'feature.sr.lookback_by_tf';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'feature.sr.lookback_by_tf', version, config_value, 'migration_263',
       'Add missing "4h" entry (90, interpolating 1h=120/1d=60) -- todo 178 IN-02, closing a '
       'Phase 163 review finding. Previously silently fell back to the generic 120-bar default.'
FROM config_state WHERE config_key = 'feature.sr.lookback_by_tf';

COMMIT;
