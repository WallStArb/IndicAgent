-- Migration 306: alpha.regime.groups -- unify commodity_energy/metals/agri into one
-- `commodity` group, enable it, fix DBC's routing gap
--
-- Todo 224 step 2/3: commodity_energy (4 members), commodity_metals (5), commodity_agri (1)
-- are each too thin on their own to clear commodity_momentum_ts.py's 4-8 instrument peer-group
-- design floor (commodity_agri's DBA alone is unusable). Unifying into a single `commodity`
-- group (~11 members once DBC's routing gap is fixed: OIH/XLE/XOP/AMLP/GLD/SLV/PPLT/DBB/GDX/
-- DBA/DBC) comfortably clears that floor. Staged, not permanent -- re-split into
-- energy/metals/agri once the securities universe has grown enough for each sub-group to
-- independently clear the floor (todo 224 step 4), consistent with the project's long-term
-- universe-scaling direction, not a fixed date.
--
-- `commodity_broad` (DBC's tag) was previously matched by zero groups -- pure routing
-- oversight, fixed here by adding it to the unified group's tag_filter.
--
-- Momentum params unify cleanly: all three source groups already carried IDENTICAL values
-- (momentum_window=60, primary_threshold=0.75) under their separate namespaces -- confirmed
-- via config_state before writing this migration, not assumed. No calibrated divergence is
-- lost. Old alpha.commodity_{energy,metals,agri}_regime.* keys are removed (orphaned once
-- the groups they parameterized no longer exist); alpha.commodity_regime.* seeded from the
-- same values.
--
-- Interim collision handling (todo 224 step 5, decided here rather than waiting on todo 225):
-- AMLP/GDX/OIH/XLE/XOP carry BOTH a weight=1.0 `eq_*` tag AND a weight=1.0 `commodity_*` tag
-- -- verified via instrument_tags this is real dual-categorical membership (these are sector
-- ETFs whose earnings driver is a single commodity), not a tagging error, so tightening the
-- underlying instrument_tags data would destroy real information. Todo 225's proposed
-- alternative (gradient-conditional partial-IC measurement, no discrete bucket needed) ran
-- its own pilot 2026-08-01 and came back negative (recommended P2->P3 demotion) -- no
-- evidence justifies blocking on it. ic_engine.py's _build_symbol_regime_class gained an
-- explicit, auditable `exclude_symbols` field (this session, tests in
-- test_ic_engine_routing.py) for exactly this case: these 5 symbols keep routing to `equity`
-- for Job 2 (single-label regime-stratified IC), unchanged from today's live behavior, zero
-- regression. Job 1 (cross_sectional_regime_model.py's peer-averaging) has no single-
-- membership constraint and is NOT given this exclusion -- these 5 symbols remain full peers
-- in both the equity breadth calc and the new commodity momentum calc, no data dropped there.
--
-- dual_write_symbol_hmm=true set from the start (matching fx/rates/equity precedent,
-- migrations 247/262/280) to avoid reproducing the same per-symbol-HMM-measurement gap a
-- fourth time.
--
-- Lesson from the fx enablement gap (todo 224, closed 2026-08-06): a config flip alone does
-- nothing until cross_sectional_regime_model.py actually runs and populates market_regimes --
-- sitting unfollowed crash-loud-failed ic_engine.py's startup gate for EVERY invocation
-- project-wide for 4 days, not just fx-routed ones. This migration's operational
-- companion step (run immediately after applying, not deferred) is
-- `cross_sectional_regime_model.py` for all tfs/enabled groups.

BEGIN;

-- Orphaned once the per-group commodity_{energy,metals,agri}_regime groups above no longer
-- exist -- prefix match instead of a hand-duplicated 6-key list so the two DELETEs can't
-- drift out of sync with each other.
DELETE FROM config_schema WHERE config_key LIKE 'alpha.commodity\_energy\_regime.%' ESCAPE '\'
    OR config_key LIKE 'alpha.commodity\_metals\_regime.%' ESCAPE '\'
    OR config_key LIKE 'alpha.commodity\_agri\_regime.%' ESCAPE '\';

DELETE FROM config_state WHERE config_key LIKE 'alpha.commodity\_energy\_regime.%' ESCAPE '\'
    OR config_key LIKE 'alpha.commodity\_metals\_regime.%' ESCAPE '\'
    OR config_key LIKE 'alpha.commodity\_agri\_regime.%' ESCAPE '\';

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES
    ('alpha.commodity_regime.momentum_window', 'int', '60',
     '[conventional] Rolling window, in DAILY bars, for the unified commodity group''s '
     'momentum z-score. Scaled to the target TF via _tf_window(daily, tf) at compute time. '
     'Consolidated from the identical commodity_energy/metals/agri values by migration 306.'),
    ('alpha.commodity_regime.primary_threshold', 'float', '0.75',
     '[initial_estimate] Unified commodity group up_primary/down_primary threshold. '
     'Consolidated from the identical commodity_energy/metals/agri values by migration 306. '
     'Candidate ML target.');

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.commodity_regime.momentum_window', '60', 1),
    ('alpha.commodity_regime.primary_threshold', '0.75', 1);

UPDATE config_schema
SET description = '[initial_estimate] JSON array of regime group configs. Each entry: '
    '{"name": str, "tag_filter": [str], "signal_type": str, "params_prefix": str, '
    '"enabled": bool, "exclude_symbols": [str] (optional)}. tag_filter patterns match '
    'instrument_tags.tag values (prefix match, trailing * stripped). signal_type maps to a '
    'module in src/intelligence/regime_signals/. params_prefix is the APR namespace for that '
    'signal''s thresholds. Groups are checked in order (order is never load-bearing); '
    'symbols matching more than one enabled group raise AmbiguousRegimeGroupError (fail '
    'loud), UNLESS the symbol is named in the matched group''s exclude_symbols list -- a '
    'small, explicit, documented carve-out for genuine dual-categorical-membership symbols '
    '(migration 306), not a silent precedence rule. Symbols matching no enabled group are '
    'OMITTED from regime-stratified IC this run (pooled IC still covers them) with a loud '
    'startup warning -- never silently defaulted to "equity". exclude_symbols only affects '
    'this single-membership routing (ic_engine.py); cross_sectional_regime_model.py''s peer-'
    'averaging has no such constraint and ignores it.'
WHERE config_key = 'alpha.regime.groups';

UPDATE config_state
SET config_value = '[{"name":"equity","tag_filter":["eq_*","intl_*"],"signal_type":"breadth_vol","params_prefix":"alpha.equity_regime","enabled":true,"dual_write_symbol_hmm":true},{"name":"rates","tag_filter":["fi_*"],"signal_type":"curve_credit","params_prefix":"alpha.rates_regime","enabled":true,"dual_write_symbol_hmm":true},{"name":"commodity","tag_filter":["commodity_energy_crude","commodity_energy_natgas","commodity_energy_pipeline","commodity_metals_precious","commodity_metals_industrial","commodity_agri","commodity_broad"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_regime","enabled":true,"dual_write_symbol_hmm":true,"exclude_symbols":["AMLP","GDX","OIH","XLE","XOP"]},{"name":"fx","tag_filter":["fx_*","crypto"],"signal_type":"fx_dollar_carry","params_prefix":"alpha.fx_regime","enabled":true,"dual_write_symbol_hmm":true}]',
    version = version + 1
WHERE config_key = 'alpha.regime.groups';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.regime.groups', version, config_value, 'migration_306',
       'Unify commodity_energy/metals/agri into one commodity group (clears '
       'commodity_momentum_ts.py''s 4-8 instrument floor), fix DBC''s commodity_broad '
       'routing gap, enable the group. AMLP/GDX/OIH/XLE/XOP carved out via the new '
       'exclude_symbols field (real dual-categorical membership, not a tagging error) -- '
       'keeps routing to equity for Job 2, unchanged from today, pending todo 225''s '
       'gradient-conditional measurement (currently P3, negative pilot, not blocking). '
       'Todo 224.'
FROM config_state WHERE config_key = 'alpha.regime.groups';

COMMIT;
