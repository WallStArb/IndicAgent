-- 331: todos 280+283 (program workstream 1, coverage fix). Route ALL 231 active
-- instruments into regime groups for measurement while freezing every regime
-- SIGNAL input (and therefore every existing label) byte-identically:
-- - equity measurement gains single_name_equity carriers + 9 previously
--   untagged ETFs; its peer set stays the 63 eq_*/intl_* ETFs via
--   signal_tag_filter (new key, cross_sectional_regime_model prefers it for
--   peer resolution; routing always uses tag_filter).
-- - 18 dual-category single names (XOM/COIN/NLY/...) stay measured under their
--   commodity/fx/rates groups via equity exclude_symbols (the sanctioned
--   routing carve-out; peer-averaging never saw them for equity anyway).
-- - URA routes to commodity via commodity_uranium added to commodity's
--   tag_filter; commodity's signal_tag_filter freezes its peer list without
--   uranium; CCJ (uranium single name) routes to equity via commodity
--   exclude_symbols.
-- - infra.ic.max_unrouted_symbols: APR-gated hard ceiling on unrouted active
--   instruments (ic_engine raises when exceeded; default 0). The old
--   warning-only path fired on 120 symbols unnoticed for a month (todo 280
--   step 3).
-- Not a compressed hypertable; no VACUUM step applies.

-- 9 equity ETFs missing exposure tags (todo 283 part 1; definitional human seeds)
INSERT INTO instrument_tags (symbol, tag, weight, source, evidence)
VALUES
  ('BTAL', 'eq_factor', 1.0, 'human', '{"reason": "todo 283 coverage fix 2026-09-03: anti-beta factor strategy ETF", "provenance": "[user_preference]"}'::jsonb),
  ('CWB', 'eq_broad', 1.0, 'human', '{"reason": "todo 283 coverage fix 2026-09-03: broad convertible basket ETF", "provenance": "[user_preference]"}'::jsonb),
  ('ICLN', 'eq_sub_sector', 1.0, 'human', '{"reason": "todo 283 coverage fix 2026-09-03: clean energy theme basket", "provenance": "[user_preference]"}'::jsonb),
  ('IPO', 'eq_sub_sector', 1.0, 'human', '{"reason": "todo 283 coverage fix 2026-09-03: IPO theme basket", "provenance": "[user_preference]"}'::jsonb),
  ('IYT', 'eq_sector', 1.0, 'human', '{"reason": "todo 283 coverage fix 2026-09-03: transportation sector ETF", "provenance": "[user_preference]"}'::jsonb),
  ('SDOG', 'eq_income', 1.0, 'human', '{"reason": "todo 283 coverage fix 2026-09-03: dividend screen ETF", "provenance": "[user_preference]"}'::jsonb),
  ('SPHB', 'eq_factor', 1.0, 'human', '{"reason": "todo 283 coverage fix 2026-09-03: high-beta factor ETF", "provenance": "[user_preference]"}'::jsonb),
  ('VNQ', 'eq_sector', 1.0, 'human', '{"reason": "todo 283 coverage fix 2026-09-03: real estate sector ETF", "provenance": "[user_preference]"}'::jsonb),
  ('VYM', 'eq_income', 1.0, 'human', '{"reason": "todo 283 coverage fix 2026-09-03: high-dividend ETF", "provenance": "[user_preference]"}'::jsonb)
ON CONFLICT DO NOTHING;

UPDATE config_state SET config_value = '[{"name":"equity","tag_filter":["eq_*","intl_*","single_name_equity"],"signal_type":"breadth_vol","params_prefix":"alpha.equity_regime","enabled":true,"dual_write_symbol_hmm":true,"signal_tag_filter":["eq_*","intl_*"],"exclude_symbols":["AA","ADM","BHP","COIN","COP","CTVA","CVX","EPD","KMI","MARA","MSTR","NLY","NTR","OXY","RIOT","SLB","WMB","XOM"]},{"name":"rates","tag_filter":["fi_*"],"signal_type":"curve_credit","params_prefix":"alpha.rates_regime","enabled":true,"dual_write_symbol_hmm":true,"signal_tag_filter":["fi_*"]},{"name":"commodity","tag_filter":["commodity_energy_crude","commodity_energy_natgas","commodity_energy_pipeline","commodity_metals_precious","commodity_metals_industrial","commodity_agri","commodity_broad","commodity_uranium"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_regime","enabled":true,"dual_write_symbol_hmm":true,"exclude_symbols":["AMLP","CCJ","EWZ","FXA","GDX","OIH","XLE","XOP"],"signal_tag_filter":["commodity_energy_crude","commodity_energy_natgas","commodity_energy_pipeline","commodity_metals_precious","commodity_metals_industrial","commodity_agri","commodity_broad"]},{"name":"fx","tag_filter":["fx_*","crypto"],"signal_type":"fx_dollar_carry","params_prefix":"alpha.fx_regime","enabled":true,"dual_write_symbol_hmm":true,"signal_tag_filter":["fx_*","crypto"]}]'::jsonb, updated_at = now()
WHERE config_key = 'alpha.regime.groups';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), 'alpha.regime.groups', 12, '[{"name":"equity","tag_filter":["eq_*","intl_*","single_name_equity"],"signal_type":"breadth_vol","params_prefix":"alpha.equity_regime","enabled":true,"dual_write_symbol_hmm":true,"signal_tag_filter":["eq_*","intl_*"],"exclude_symbols":["AA","ADM","BHP","COIN","COP","CTVA","CVX","EPD","KMI","MARA","MSTR","NLY","NTR","OXY","RIOT","SLB","WMB","XOM"]},{"name":"rates","tag_filter":["fi_*"],"signal_type":"curve_credit","params_prefix":"alpha.rates_regime","enabled":true,"dual_write_symbol_hmm":true,"signal_tag_filter":["fi_*"]},{"name":"commodity","tag_filter":["commodity_energy_crude","commodity_energy_natgas","commodity_energy_pipeline","commodity_metals_precious","commodity_metals_industrial","commodity_agri","commodity_broad","commodity_uranium"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_regime","enabled":true,"dual_write_symbol_hmm":true,"exclude_symbols":["AMLP","CCJ","EWZ","FXA","GDX","OIH","XLE","XOP"],"signal_tag_filter":["commodity_energy_crude","commodity_energy_natgas","commodity_energy_pipeline","commodity_metals_precious","commodity_metals_industrial","commodity_agri","commodity_broad"]},{"name":"fx","tag_filter":["fx_*","crypto"],"signal_type":"fx_dollar_carry","params_prefix":"alpha.fx_regime","enabled":true,"dual_write_symbol_hmm":true,"signal_tag_filter":["fx_*","crypto"]}]'::jsonb, 'migration_331',
  'todos 280+283: full-universe regime routing (workstream 1). Measurement tag_filter widened; signal inputs frozen via signal_tag_filter so all existing regime labels are unchanged.'
FROM config_state WHERE config_key = 'alpha.regime.groups'
  AND NOT EXISTS (SELECT 1 FROM config_history WHERE changed_by='migration_331' AND config_key='alpha.regime.groups');

INSERT INTO config_state (config_key, config_value, version, updated_at)
VALUES ('infra.ic.max_unrouted_symbols', '0', 13, now())
ON CONFLICT (config_key) DO UPDATE SET config_value = '0', version = 13, updated_at = now();

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), 'infra.ic.max_unrouted_symbols', 13, '0', 'migration_331',
  'Hard ceiling on unrouted active instruments at ic_engine startup (todo 280 step 3). Default 0: any unrouted instrument fails the run.'
WHERE NOT EXISTS (SELECT 1 FROM config_history WHERE changed_by='migration_331' AND config_key='infra.ic.max_unrouted_symbols');

INSERT INTO config_schema (config_key, value_type, description)
VALUES
  ('infra.ic.max_unrouted_symbols', 'int',
   'Hard ceiling on active instruments unmatched by any enabled regime group tag_filter; ic_engine raises at startup when exceeded (default 0 = any unrouted instrument fails the run). Added todo 280 step 3 after the unrouted-symbols warning fired on 120 symbols unnoticed for a month. [user_preference]'),
  ('alpha.regime.groups.signal_tag_filter', 'json',
   'Optional per-group list resolving PEER (signal-input) symbols, preferred over tag_filter by cross_sectional_regime_model; routing to measurement always uses tag_filter. Lets a group measure a wider symbol set than feeds its regime signal. [user_preference]')
ON CONFLICT (config_key) DO UPDATE SET description = EXCLUDED.description;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), 'alpha.regime.groups', 12, '[{"name":"equity","tag_filter":["eq_*","intl_*","single_name_equity"],"signal_type":"breadth_vol","params_prefix":"alpha.equity_regime","enabled":true,"dual_write_symbol_hmm":true,"signal_tag_filter":["eq_*","intl_*"],"exclude_symbols":["AA","ADM","BHP","COIN","COP","CTVA","CVX","EPD","KMI","MARA","MSTR","NLY","NTR","OXY","RIOT","SLB","WMB","XOM"],"signal_exclude_symbols":["BTAL","CWB","ICLN","IPO","IYT","SDOG","SPHB","VNQ","VYM"]},{"name":"rates","tag_filter":["fi_*"],"signal_type":"curve_credit","params_prefix":"alpha.rates_regime","enabled":true,"dual_write_symbol_hmm":true,"signal_tag_filter":["fi_*"]},{"name":"commodity","tag_filter":["commodity_energy_crude","commodity_energy_natgas","commodity_energy_pipeline","commodity_metals_precious","commodity_metals_industrial","commodity_agri","commodity_broad","commodity_uranium"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_regime","enabled":true,"dual_write_symbol_hmm":true,"exclude_symbols":["AMLP","CCJ","EWZ","FXA","GDX","OIH","XLE","XOP"],"signal_tag_filter":["commodity_energy_crude","commodity_energy_natgas","commodity_energy_pipeline","commodity_metals_precious","commodity_metals_industrial","commodity_agri","commodity_broad"]},{"name":"fx","tag_filter":["fx_*","crypto"],"signal_type":"fx_dollar_carry","params_prefix":"alpha.fx_regime","enabled":true,"dual_write_symbol_hmm":true,"signal_tag_filter":["fx_*","crypto"]}]', 'migration_331',
  'Amendment: equity signal_exclude_symbols freezes the peer set at the pre-migration 63 (the 9 newly-tagged ETFs match eq_* and would otherwise widen the signal input).'
WHERE NOT EXISTS (SELECT 1 FROM config_history WHERE changed_by='migration_331' AND config_key='alpha.regime.groups' AND config_value LIKE '%signal_exclude_symbols%');
