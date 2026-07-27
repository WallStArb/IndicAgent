-- Migration 262: alpha.regime.groups -- add dual_write_symbol_hmm to the equity group
--
-- Sibling of migration 247 (rates), closing the equity half of the same gap. Todo 167:
-- ic_engine.py's regime-group routing (cross_sectional = mr_dict is not None) has
-- permanently replaced every equity-routed symbol's per-symbol HMM IC measurement with
-- cross-sectional measurement since equity's regime group was first enabled -- verified
-- live 2026-07-21, SPY has zero symbol_hmm-scope feature_ic_scores rows. Unlike rates,
-- no falsifier gate was ever built to test whether cross-sectional labels actually
-- separate IC better than per-symbol HMM for the ~50 equity symbols -- an unproven
-- default masquerading as settled (CLAUDE.md: "earn promotion through proof").
--
-- dual_write_symbol_hmm is already fully generic per-group (services/ic_engine.py
-- _resolve_symbol_routing / line ~1152 reads group_by_name.get(routed_group_name, {})
-- .get("dual_write_symbol_hmm", False)) -- this migration is a one-line config change,
-- zero code, exactly as migration 247's comment anticipated.
--
-- Deliberately NOT triggering a standalone recompute for this: todo 183's ic_engine
-- corpus recompute is already mid-flight against equity (config loads once at process
-- startup, so this change has zero effect on that run -- confirmed via
-- services/ic_engine.py's startup-time config load). This flag takes effect on the
-- NEXT ic_engine process start (a future scheduled corpus rebuild), batching equity's
-- symbol_hmm backfill into that run rather than launching a second, resource-contending
-- pass alongside the one already in progress -- same batching discipline already
-- applied to todos 092/146/155/171.
--
-- Once fresh symbol_hmm rows exist for equity symbols, the falsifier gate itself
-- (an equity-scoped generalization of scripts/analysis/phase144_regime_separation_gate.py)
-- is a cheap read-only query, not a recompute -- ready to run the moment that data lands.

BEGIN;

UPDATE config_state
SET config_value = '[{"name":"equity","tag_filter":["eq_*","intl_*"],"signal_type":"breadth_vol","params_prefix":"alpha.equity_regime","enabled":true,"dual_write_symbol_hmm":true},{"name":"rates","tag_filter":["fi_*"],"signal_type":"curve_credit","params_prefix":"alpha.rates_regime","enabled":true,"dual_write_symbol_hmm":true},{"name":"commodity_energy","tag_filter":["commodity_energy_crude","commodity_energy_natgas","commodity_energy_pipeline"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_energy_regime","enabled":false},{"name":"commodity_metals","tag_filter":["commodity_metals_precious","commodity_metals_industrial"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_metals_regime","enabled":false},{"name":"commodity_agri","tag_filter":["commodity_agri"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_agri_regime","enabled":false},{"name":"fx","tag_filter":["fx_*","crypto"],"signal_type":"fx_dollar_carry","params_prefix":"alpha.fx_regime","enabled":false}]',
    version = version + 1
WHERE config_key = 'alpha.regime.groups';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.regime.groups', version, config_value, 'migration_262',
       'Add dual_write_symbol_hmm=true to equity group (sibling of migration 247''s rates '
       'fix), restoring symbol_hmm IC measurement for ~50 equity-routed symbols on the '
       'NEXT ic_engine run -- unblocks todo 167''s falsifier gate. Deliberately not '
       'triggering a standalone recompute; batched into the next scheduled corpus rebuild '
       'to avoid resource contention with todo 183''s in-flight recompute.'
FROM config_state WHERE config_key = 'alpha.regime.groups';

COMMIT;
