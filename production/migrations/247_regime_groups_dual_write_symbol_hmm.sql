-- Migration 247: alpha.regime.groups -- add dual_write_symbol_hmm to the rates group only
--
-- ic_engine.py:965 (`cross_sectional = mr_dict is not None`) permanently replaces a
-- routed symbol's per-symbol HMM IC measurement with cross-sectional measurement --
-- verified live 2026-07-21: TLT (routed to `rates`) has zero symbol_hmm-scope
-- feature_ic_scores rows since 2026-07-17, before the most recent corpus rebuild, and
-- will never get another one under the pre-fix code. This breaks Phase 144's D-05
-- acceptance gate, whose F1 falsifier requires comparing TLT's per-symbol HMM against
-- the new rates cross-sectional label -- data that cannot exist without this fix.
--
-- dual_write_symbol_hmm is a per-group field (not a new APR key) governing whether
-- ic_engine.py's new dual-write pass (see services/ic_engine.py's
-- _compute_one_regime_cell / _compute_symbol_tf) ALSO computes a symbol_hmm-scoped
-- measurement pass for that group's routed symbols, alongside the primary
-- cross-sectional pass.
--
-- Set true for `rates` ONLY. `rates` has an open Stage-1 conditioning question (D-05
-- exists specifically to answer it: does per-symbol HMM or the new cross-sectional
-- label better separate IC for this group's members?) -- dual-write while that
-- question is open, per this project's "shadow mode first" principle. `equity`'s
-- analogous question was never asked (silently defaulted to cross-sectional-only the
-- moment routing shipped, no falsifier gate ever built) -- a separate, real gap, filed
-- as its own follow-up todo, NOT solved here by accelerating equity's measurement cost
-- before any gate exists to consume that data. Flipping equity's flag later, if that
-- gate gets built, is a one-line APR change, zero code, thanks to this migration's
-- mechanism being general per-group rather than hardcoded to `rates`.

BEGIN;

UPDATE config_state
SET config_value = '[{"name":"equity","tag_filter":["eq_*","intl_*"],"signal_type":"breadth_vol","params_prefix":"alpha.equity_regime","enabled":true},{"name":"rates","tag_filter":["fi_*"],"signal_type":"curve_credit","params_prefix":"alpha.rates_regime","enabled":true,"dual_write_symbol_hmm":true},{"name":"commodity_energy","tag_filter":["commodity_energy_crude","commodity_energy_natgas","commodity_energy_pipeline"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_energy_regime","enabled":false},{"name":"commodity_metals","tag_filter":["commodity_metals_precious","commodity_metals_industrial"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_metals_regime","enabled":false},{"name":"commodity_agri","tag_filter":["commodity_agri"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_agri_regime","enabled":false},{"name":"fx","tag_filter":["fx_*","crypto"],"signal_type":"fx_dollar_carry","params_prefix":"alpha.fx_regime","enabled":false}]',
    version = version + 1
WHERE config_key = 'alpha.regime.groups';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.regime.groups', version, config_value, 'migration_247',
       'Add dual_write_symbol_hmm=true to rates group only, restoring symbol_hmm IC '
       'measurement for its routed symbols -- unblocks Phase 144 D-05 F1 falsifier. '
       'equity left unchanged (its analogous question was never falsifier-tested; '
       'filed as a separate follow-up todo, not solved here).'
FROM config_state WHERE config_key = 'alpha.regime.groups';

COMMIT;
