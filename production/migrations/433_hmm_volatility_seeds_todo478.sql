-- Migration 433: volatility family HMM seeds 250/250/3 -> 60/60/2 (todo 478)
--
-- The 186-18 sweep measured the volatility family's pooled 1d skip fraction at 0.982 under the
-- phase 172 seeds: on 250-day windows both observation columns ([realized_vol, vol_of_vol]) are
-- nearly constant inside a segment and the K=3 fit strands a state at zero occupation in 560 of
-- 742 unlabeled names. Todo 478's preregistered six-arm stage-1 sweep (rule committed b1e4463a5,
-- verdict ddfd631db) picked arm E (60/60, K=2): 1d labeled 0.0177 -> 0.9970, degenerate segments
-- 11799 -> 39; every K=3 arm plateaued at 0.39 regardless of windows. Stage 2, the preregistered
-- intraday non-regression gate (+/-0.02 per tf), PASSED on 2026-10-02 with labeled fraction
-- 0.977-0.9998 vs control 0.308-0.431 and skip under 0.024 vs control 0.569-0.690.
-- Evidence: evidence/478-{A..F}-*.json, evidence/478-verify-{A,E}-intraday.json (untracked by
-- design, the 186-18 convention). Decision record:
-- .planning/todos/done/478-regime-volatility-1d-three-state-fit-collapses-on-250-day-windows.md
--
-- Changing these seeds relabels the volatility family everywhere; the first consumer is the
-- 186-26 feature_vectors rebuild (stored regime columns stay gated until then, todo 248/451).
-- Golden regenerated in this change's own commit (tests/fixtures/regime_kernel).

BEGIN;

UPDATE config_state
   SET config_value = '60', version = version + 1, updated_at = NOW()
 WHERE config_key = 'alpha.hmm_volatility.vol_window';

UPDATE config_state
   SET config_value = '60', version = version + 1, updated_at = NOW()
 WHERE config_key = 'alpha.hmm_volatility.vol_of_vol_window';

UPDATE config_state
   SET config_value = '2', version = version + 1, updated_at = NOW()
 WHERE config_key = 'alpha.hmm_volatility.n_components';

UPDATE config_schema
   SET description = '[rca_analysis] Phase 172: realized-vol rolling-std window for the volatility-only regime HMM, the axis''s ORDERING column (column 0 of the 2-column observation). Todo 478 (2026-10-02): at 1d the 250-day window leaves the column nearly constant inside a segment (98.2% skip); preregistered stage-1 sweep picked 60, stage-2 intraday non-regression PASS. Changing relabels the family; first consumer is the 186-26 rebuild. Not an ML learning target.'
 WHERE config_key = 'alpha.hmm_volatility.vol_window';

UPDATE config_schema
   SET description = '[rca_analysis] Phase 172: vol-of-vol rolling-std window for the volatility-only regime HMM; 171-FINAL-VERDICT section 6 found this column''s margin thin at wide windows. Todo 478 (2026-10-02): shortened 250 -> 60 with the vol_window change after the preregistered stage-1 verdict E and the stage-2 intraday non-regression PASS. Changing relabels the family; first consumer is the 186-26 rebuild. Not an ML learning target.'
 WHERE config_key = 'alpha.hmm_volatility.vol_of_vol_window';

UPDATE config_schema
   SET description = '[rca_analysis] Phase 172: both K=2 and K=3 cleared the null-arm block-reliability control per 171-FINAL-VERDICT section 3; K=3 preserved the calm/elevated/turbulent framing per section 5. Todo 478 (2026-10-02): at 1d every K=3 arm plateaus at 0.39 labeled (a state strands at zero occupation); K=2 labels 0.997 and passed the stage-2 intraday non-regression gate, so the seed moves to 2. Changing relabels the family; first consumer is the 186-26 rebuild. Not an ML learning target.'
 WHERE config_key = 'alpha.hmm_volatility.n_components';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, version, config_value, 'migration_433',
       'todo 478: 1d three-state fit collapse on 250-day windows; stage-1 arm E (60/60/K2) + stage-2 intraday non-regression PASS [rca_analysis]'
  FROM config_state
 WHERE config_key IN ('alpha.hmm_volatility.vol_window',
                      'alpha.hmm_volatility.vol_of_vol_window',
                      'alpha.hmm_volatility.n_components');

COMMIT;
