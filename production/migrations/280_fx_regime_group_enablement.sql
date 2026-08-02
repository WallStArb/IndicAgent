-- Migration 280: alpha.regime.groups -- enable the fx regime group
--
-- Todo 224 (commodity/fx regime-group re-enablement): fx (`fx_dollar_carry.py`) is fully
-- implemented, has shipped enabled=false since migration 222's original seed, and is
-- confirmed collision-free -- UUP/FXA/FXE/IBIT carry zero tag overlap with any other
-- enabled group on either cross_sectional_regime_model.py's peer-averaging or
-- ic_engine.py's _build_symbol_regime_class single-membership routing (verified
-- 2026-08-01). Unlike the commodity sub-groups (owned separately by todo 224 step 2 /
-- todo 225's equity-collision axis), there is no blocker left for fx -- flip is safe today.
--
-- Also sets dual_write_symbol_hmm=true, matching migration 247 (rates) and migration 262
-- (equity): ic_engine.py's routing (cross_sectional = mr_dict is not None) permanently
-- replaces a routed symbol's per-symbol HMM IC measurement with cross-sectional measurement
-- unless this flag is set for the group. Both prior groups had to be fixed after the fact
-- once this gap was noticed (migration 247's own comment: "equity left unchanged... filed
-- as a separate follow-up" -> closed one migration later as 262). Setting it here for fx
-- from the start avoids reproducing the identical gap a third time for UUP/FXA/FXE/IBIT.
--
-- Deliberately NOT triggering a standalone recompute: ic_engine (step 5/8 of the corpus
-- pipeline) is currently mid-flight and loads alpha.regime.groups once at process startup
-- (2026-07-30 17:08:55 EDT) -- this change has zero effect on that run. Same batching
-- discipline as migrations 247/262/todos 092/146/155/171: takes effect on the NEXT
-- cross_sectional_regime_model.py + ic_engine.py invocation (a future scheduled corpus
-- rebuild), not a disruptive standalone pass alongside the one already in progress.

BEGIN;

UPDATE config_state
SET config_value = '[{"name":"equity","tag_filter":["eq_*","intl_*"],"signal_type":"breadth_vol","params_prefix":"alpha.equity_regime","enabled":true,"dual_write_symbol_hmm":true},{"name":"rates","tag_filter":["fi_*"],"signal_type":"curve_credit","params_prefix":"alpha.rates_regime","enabled":true,"dual_write_symbol_hmm":true},{"name":"commodity_energy","tag_filter":["commodity_energy_crude","commodity_energy_natgas","commodity_energy_pipeline"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_energy_regime","enabled":false},{"name":"commodity_metals","tag_filter":["commodity_metals_precious","commodity_metals_industrial"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_metals_regime","enabled":false},{"name":"commodity_agri","tag_filter":["commodity_agri"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_agri_regime","enabled":false},{"name":"fx","tag_filter":["fx_*","crypto"],"signal_type":"fx_dollar_carry","params_prefix":"alpha.fx_regime","enabled":true,"dual_write_symbol_hmm":true}]',
    version = version + 1
WHERE config_key = 'alpha.regime.groups';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.regime.groups', version, config_value, 'migration_280',
       'Enable fx regime group (confirmed zero tag collisions with any other enabled '
       'group) and set dual_write_symbol_hmm=true to avoid reproducing the same '
       'per-symbol-HMM-measurement gap already fixed for rates (migration 247) and '
       'equity (migration 262). Takes effect on the NEXT ic_engine run -- todo 224.'
FROM config_state WHERE config_key = 'alpha.regime.groups';

COMMIT;
