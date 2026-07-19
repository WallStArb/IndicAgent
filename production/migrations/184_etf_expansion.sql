-- production/migrations/188_etf_expansion.sql
-- Migration 184: ETF universe expansion — 58 → 79 instruments.
--
-- 1. Extend tag_vocabulary with fine-grained commodity, FX, and factor sub-tags
-- 2. Re-tag existing instruments with fine-grained sub-tags
-- 3. Register 21 new instruments in instruments table
-- 4. Tag new instruments

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Tag vocabulary extension
-- ---------------------------------------------------------------------------

INSERT INTO tag_vocabulary (tag, category, description) VALUES
    ('commodity_energy_crude',    'exposure', 'Crude oil futures or equity proxy — WTI/Brent price beta'),
    ('commodity_energy_pipeline', 'exposure', 'Midstream energy infrastructure — income, not crude spot beta'),
    ('commodity_metals_precious', 'exposure', 'Precious metals — gold, silver, platinum; monetary/inflation store of value'),
    ('commodity_metals_industrial','exposure','Industrial base metals — copper, aluminum, zinc; global demand proxy'),
    ('commodity_agri',            'exposure', 'Agricultural commodities — grains, softs, livestock'),
    ('commodity_broad',           'exposure', 'Broad commodity index — diversified across energy, metals, agriculture'),
    ('fx_usd',                    'exposure', 'US dollar index — long USD vs basket of major currencies'),
    ('fx_major',                  'exposure', 'Major developed-market currency vs USD — EUR, JPY, GBP, CHF'),
    ('fx_em',                     'exposure', 'Emerging market currency basket vs USD'),
    ('fx_commodity',              'exposure', 'Commodity-linked currency vs USD — AUD, CAD, NZD; proxy for China/metals/agri demand'),
    ('transports',                'exposure', 'Transportation sector — rails, trucking, air freight, marine; leading-indicator cyclical'),
    ('defensive_yield',           'exposure', 'High-dividend-yield equity — contrarian/mean-reversion factor distinct from dividend-quality (SCHD)'),
    ('factor_market_neutral',     'exposure', 'Long-short, dollar-neutral factor exposure — near-zero equity beta by construction (e.g. anti-beta)'),
    ('high_beta',                 'exposure', 'Liquid, non-leveraged high-volatility equity factor — elevated beta without structural rebalancing decay')
ON CONFLICT (tag) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. Re-tag existing instruments with fine-grained sub-tags
--    Existing coarse tags (commodity_energy, commodity_metals) are preserved.
-- ---------------------------------------------------------------------------

INSERT INTO instrument_tags (symbol, tag, weight, source, evidence) VALUES
    -- Precious metals
    ('GLD', 'commodity_metals_precious', 1.0, 'human', '{"reason": "gold is the benchmark precious metal"}'),
    ('SLV', 'commodity_metals_precious', 0.8, 'human', '{"reason": "silver primary classification precious; 50% industrial but monetary regime driver"}'),
    ('GDX', 'commodity_metals_precious', 0.9, 'human', '{"reason": "gold miner equity; regime driven by gold price"}'),
    -- Energy sub-tags
    ('OIH', 'commodity_energy_crude',    0.9, 'human', '{"reason": "oil services — strong crude price beta"}'),
    ('XOP', 'commodity_energy_crude',    1.0, 'human', '{"reason": "oil & gas exploration — direct crude beta"}'),
    ('XLE', 'commodity_energy_crude',    0.8, 'human', '{"reason": "broad energy sector; crude-dominated"}'),
    ('AMLP','commodity_energy_pipeline', 1.0, 'human', '{"reason": "midstream MLP infrastructure; income not spot crude"}')
ON CONFLICT (symbol, tag) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. Register 21 new instruments
--    contract_details mirrors SPY pattern: symbol, base, name, asset_class,
--    exchange, sector, tick_size, session_id, point_value, provider_meta.
--    asset_class = 'equity' for ETFs (including FX and commodity ETFs —
--    these are equity-structured funds, not futures).
-- ---------------------------------------------------------------------------

INSERT INTO instruments (symbol, base, contract_details, is_active) VALUES
    ('DBC',  'DBC',  '{"symbol":"DBC","base":"DBC","name":"Invesco DB Commodity Index Tracking Fund","asset_class":"equity","exchange":"SMART","sector":"commodity","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('DBA',  'DBA',  '{"symbol":"DBA","base":"DBA","name":"Invesco DB Agriculture Fund","asset_class":"equity","exchange":"SMART","sector":"commodity","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('DBB',  'DBB',  '{"symbol":"DBB","base":"DBB","name":"Invesco DB Base Metals Fund","asset_class":"equity","exchange":"SMART","sector":"commodity","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('PPLT', 'PPLT', '{"symbol":"PPLT","base":"PPLT","name":"Aberdeen Standard Physical Platinum Shares ETF","asset_class":"equity","exchange":"SMART","sector":"commodity","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('EZU',  'EZU',  '{"symbol":"EZU","base":"EZU","name":"iShares MSCI Eurozone ETF","asset_class":"equity","exchange":"SMART","sector":"international","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('EWG',  'EWG',  '{"symbol":"EWG","base":"EWG","name":"iShares MSCI Germany ETF","asset_class":"equity","exchange":"SMART","sector":"international","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('EWZ',  'EWZ',  '{"symbol":"EWZ","base":"EWZ","name":"iShares MSCI Brazil ETF","asset_class":"equity","exchange":"SMART","sector":"international","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('VWO',  'VWO',  '{"symbol":"VWO","base":"VWO","name":"Vanguard FTSE Emerging Markets ETF","asset_class":"equity","exchange":"SMART","sector":"international","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('FXI',  'FXI',  '{"symbol":"FXI","base":"FXI","name":"iShares China Large-Cap ETF","asset_class":"equity","exchange":"SMART","sector":"international","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('MCHI', 'MCHI', '{"symbol":"MCHI","base":"MCHI","name":"iShares MSCI China ETF","asset_class":"equity","exchange":"SMART","sector":"international","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('UUP',  'UUP',  '{"symbol":"UUP","base":"UUP","name":"Invesco DB US Dollar Index Bullish Fund","asset_class":"equity","exchange":"SMART","sector":"fx","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('FXE',  'FXE',  '{"symbol":"FXE","base":"FXE","name":"Invesco CurrencyShares Euro Currency Trust","asset_class":"equity","exchange":"SMART","sector":"fx","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('FXY',  'FXY',  '{"symbol":"FXY","base":"FXY","name":"Invesco CurrencyShares Japanese Yen Trust","asset_class":"equity","exchange":"SMART","sector":"fx","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('EDV',  'EDV',  '{"symbol":"EDV","base":"EDV","name":"Vanguard Extended Duration Treasury ETF","asset_class":"equity","exchange":"SMART","sector":"fixed_income","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('IYT',  'IYT',  '{"symbol":"IYT","base":"IYT","name":"iShares Transportation Average ETF","asset_class":"equity","exchange":"SMART","sector":"transports","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('FXA',  'FXA',  '{"symbol":"FXA","base":"FXA","name":"Invesco CurrencyShares Australian Dollar Trust","asset_class":"equity","exchange":"SMART","sector":"fx","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('VYM',  'VYM',  '{"symbol":"VYM","base":"VYM","name":"Vanguard High Dividend Yield ETF","asset_class":"equity","exchange":"SMART","sector":"defensive_yield","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('SDOG', 'SDOG', '{"symbol":"SDOG","base":"SDOG","name":"ALPS Sector Dividend Dogs ETF","asset_class":"equity","exchange":"SMART","sector":"defensive_yield","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('BTAL', 'BTAL', '{"symbol":"BTAL","base":"BTAL","name":"AGF US Market Neutral Anti-Beta Fund","asset_class":"equity","exchange":"SMART","sector":"factor_market_neutral","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('IPO',  'IPO',  '{"symbol":"IPO","base":"IPO","name":"Renaissance IPO ETF","asset_class":"equity","exchange":"SMART","sector":"high_beta","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('SPHB', 'SPHB', '{"symbol":"SPHB","base":"SPHB","name":"Invesco S&P 500 High Beta ETF","asset_class":"equity","exchange":"SMART","sector":"high_beta","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true)
ON CONFLICT (symbol) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 4. Tag new instruments
-- ---------------------------------------------------------------------------

INSERT INTO instrument_tags (symbol, tag, weight, source, evidence) VALUES
    -- DBC
    ('DBC', 'commodity_broad',        1.0, 'human', '{"reason": "GSCI-weighted broad commodity index"}'),
    ('DBC', 'benchmark',              1.0, 'human', '{"reason": "benchmark broad commodity ETF"}'),
    ('DBC', 'inflation',              0.9, 'human', '{"reason": "broad commodity basket is inflation proxy"}'),
    ('DBC', 'late_cycle',             0.8, 'human', '{"reason": "commodities outperform late expansion"}'),
    ('DBC', 'regime_classifier',      0.8, 'human', '{"reason": "commodity regime signal"}'),
    -- DBA
    ('DBA', 'commodity_agri',         1.0, 'human', '{"reason": "corn, wheat, soybeans, sugar basket"}'),
    ('DBA', 'benchmark',              1.0, 'human', '{"reason": "benchmark agriculture ETF"}'),
    ('DBA', 'inflation',              0.7, 'human', '{"reason": "food prices are inflation component"}'),
    ('DBA', 'dollar_strength',        0.7, 'human', '{"reason": "USD inverse — dollar drives agri exports"}'),
    -- DBB
    ('DBB', 'commodity_metals_industrial', 1.0, 'human', '{"reason": "aluminum, copper, zinc — industrial demand"}'),
    ('DBB', 'benchmark',              1.0, 'human', '{"reason": "benchmark base metals ETF"}'),
    ('DBB', 'china_demand',           0.9, 'human', '{"reason": "industrial metals driven by China manufacturing"}'),
    ('DBB', 'leading_indicator',      0.8, 'human', '{"reason": "copper/base metals lead global PMI"}'),
    ('DBB', 'early_cycle',            0.7, 'human', '{"reason": "industrial metals recover early in expansion"}'),
    -- PPLT
    ('PPLT','commodity_metals_precious', 0.9, 'human', '{"reason": "platinum — precious metal with industrial auto-catalyst demand"}'),
    ('PPLT','commodity_metals_industrial', 0.6, 'human', '{"reason": "40% auto-catalyst industrial demand"}'),
    ('PPLT','benchmark',              1.0, 'human', '{"reason": "benchmark platinum ETF"}'),
    ('PPLT','inflation',              0.7, 'human', '{"reason": "precious metal inflation hedge"}'),
    -- EZU
    ('EZU', 'intl_developed',         1.0, 'human', '{"reason": "eurozone developed market equities"}'),
    ('EZU', 'benchmark',              1.0, 'human', '{"reason": "benchmark eurozone ETF"}'),
    ('EZU', 'dollar_strength',        0.9, 'human', '{"reason": "EUR/USD sensitivity — weak dollar boosts EZU in USD terms"}'),
    ('EZU', 'regime_classifier',      0.8, 'human', '{"reason": "eurozone regime independent of US"}'),
    ('EZU', 'spread_leg',             0.9, 'human', '{"reason": "US vs Europe spread"}'),
    -- EWG
    ('EWG', 'intl_developed',         1.0, 'human', '{"reason": "Germany equities — industrial/export bellwether"}'),
    ('EWG', 'benchmark',              1.0, 'human', '{"reason": "benchmark Germany ETF"}'),
    ('EWG', 'dollar_strength',        0.8, 'human', '{"reason": "EUR/USD sensitivity"}'),
    ('EWG', 'china_demand',           0.7, 'human', '{"reason": "German exports sensitive to China industrial demand"}'),
    ('EWG', 'leading_indicator',      0.7, 'human', '{"reason": "German manufacturing leads European cycle"}'),
    -- EWZ
    ('EWZ', 'intl_em',                1.0, 'human', '{"reason": "Brazil EM equities"}'),
    ('EWZ', 'benchmark',              1.0, 'human', '{"reason": "benchmark Brazil ETF"}'),
    ('EWZ', 'em_flows',               0.9, 'human', '{"reason": "Brazil driven by EM capital flows"}'),
    ('EWZ', 'commodity_broad',        0.7, 'human', '{"reason": "Brazil equity index commodity-exporter dominated"}'),
    ('EWZ', 'dollar_strength',        0.9, 'human', '{"reason": "BRL/USD sensitive — strong dollar hurts EWZ"}'),
    -- VWO
    ('VWO', 'intl_em',                1.0, 'human', '{"reason": "Vanguard broad EM — most liquid EM ETF"}'),
    ('VWO', 'benchmark',              1.0, 'human', '{"reason": "benchmark broad EM ETF"}'),
    ('VWO', 'em_flows',               1.0, 'human', '{"reason": "primary EM flow vehicle"}'),
    ('VWO', 'dollar_strength',        0.9, 'human', '{"reason": "strong dollar = EM outflow"}'),
    ('VWO', 'regime_classifier',      0.8, 'human', '{"reason": "EM risk-on/off regime signal"}'),
    -- FXI
    ('FXI', 'intl_em',                1.0, 'human', '{"reason": "China H-share large-cap equities"}'),
    ('FXI', 'benchmark',              1.0, 'human', '{"reason": "benchmark China H-share ETF"}'),
    ('FXI', 'china_demand',           1.0, 'human', '{"reason": "direct China equity exposure"}'),
    ('FXI', 'em_flows',               0.8, 'human', '{"reason": "China is dominant EM flow destination"}'),
    -- MCHI
    ('MCHI','intl_em',                1.0, 'human', '{"reason": "MSCI China broad — includes A-shares"}'),
    ('MCHI','benchmark',              1.0, 'human', '{"reason": "MSCI China benchmark"}'),
    ('MCHI','china_demand',           1.0, 'human', '{"reason": "broad China market exposure"}'),
    ('MCHI','spread_leg',             0.8, 'human', '{"reason": "FXI vs MCHI spread (H-share vs MSCI divergence)"}'),
    -- UUP
    ('UUP', 'fx_usd',                 1.0, 'human', '{"reason": "dollar index — long USD vs EUR/JPY/GBP/CAD/SEK/CHF basket"}'),
    ('UUP', 'benchmark',              1.0, 'human', '{"reason": "benchmark USD index ETF"}'),
    ('UUP', 'dollar_strength',        1.0, 'human', '{"reason": "IS the dollar strength signal"}'),
    ('UUP', 'regime_classifier',      0.9, 'human', '{"reason": "dollar regime drives cross-asset flows"}'),
    ('UUP', 'risk_off',               0.7, 'human', '{"reason": "dollar tends to strengthen in risk-off"}'),
    -- FXE
    ('FXE', 'fx_major',               1.0, 'human', '{"reason": "EUR/USD — largest FX pair"}'),
    ('FXE', 'benchmark',              1.0, 'human', '{"reason": "benchmark euro ETF"}'),
    ('FXE', 'dollar_strength',        0.9, 'human', '{"reason": "primary EUR/USD exposure — inverse UUP"}'),
    ('FXE', 'spread_leg',             1.0, 'human', '{"reason": "UUP/FXE spread"}'),
    -- FXY
    ('FXY', 'fx_major',               1.0, 'human', '{"reason": "JPY/USD — yen carry trade vehicle"}'),
    ('FXY', 'benchmark',              1.0, 'human', '{"reason": "benchmark yen ETF"}'),
    ('FXY', 'yen_carry',              1.0, 'human', '{"reason": "yen strengthens when carry unwinds"}'),
    ('FXY', 'risk_off',               0.8, 'human', '{"reason": "JPY is safe haven — strengthens in risk-off"}'),
    ('FXY', 'spread_leg',             0.9, 'human', '{"reason": "FXE/FXY cross"}'),
    -- EDV
    ('EDV', 'fi_treasury',            1.0, 'human', '{"reason": "25yr+ zero-coupon Treasuries"}'),
    ('EDV', 'benchmark',              1.0, 'human', '{"reason": "benchmark ultra-long duration ETF"}'),
    ('EDV', 'rate_sensitive',         1.0, 'human', '{"reason": "highest duration in universe — most rate-sensitive"}'),
    ('EDV', 'fed_policy',             0.9, 'human', '{"reason": "ultra-long end driven by long-run Fed expectations"}'),
    ('EDV', 'recession',              0.9, 'human', '{"reason": "flight to ultra-long quality in recession"}'),
    ('EDV', 'spread_leg',             1.0, 'human', '{"reason": "TLT/EDV duration spread"}'),
    ('EDV', 'yield_curve',            0.9, 'human', '{"reason": "captures long-end yield curve moves"}'),
    -- IYT
    ('IYT', 'transports',             1.0, 'human', '{"reason": "rails, trucking, air freight, marine — Dow Transports composition"}'),
    ('IYT', 'benchmark',              1.0, 'human', '{"reason": "benchmark transportation sector ETF"}'),
    ('IYT', 'leading_indicator',      0.9, 'human', '{"reason": "freight volumes lead broad economic cycle turns"}'),
    ('IYT', 'early_cycle',            0.7, 'human', '{"reason": "transports recover early in expansion"}'),
    ('IYT', 'recession',              0.7, 'human', '{"reason": "freight demand rolls over ahead of recession"}'),
    -- FXA
    ('FXA', 'fx_commodity',           1.0, 'human', '{"reason": "AUD/USD — commodity-currency proxy"}'),
    ('FXA', 'benchmark',              1.0, 'human', '{"reason": "benchmark AUD ETF"}'),
    ('FXA', 'china_demand',           0.9, 'human', '{"reason": "AUD tightly correlated to China industrial demand"}'),
    ('FXA', 'commodity_broad',        0.8, 'human', '{"reason": "AUD tracks metals/agri terms-of-trade"}'),
    ('FXA', 'spread_leg',             0.8, 'human', '{"reason": "FXA/FXY risk-on vs risk-off currency cross"}'),
    -- VYM
    ('VYM', 'defensive_yield',        1.0, 'human', '{"reason": "broad market screened purely on trailing dividend yield"}'),
    ('VYM', 'benchmark',              1.0, 'human', '{"reason": "benchmark high-dividend-yield ETF"}'),
    ('VYM', 'risk_off',               0.7, 'human', '{"reason": "high-yield equities rotate into favor in risk-off/late-cycle"}'),
    ('VYM', 'spread_leg',             0.8, 'human', '{"reason": "VYM/SCHD raw-yield vs quality-dividend spread"}'),
    -- SDOG
    ('SDOG', 'defensive_yield',       1.0, 'human', '{"reason": "literal Dogs-of-the-Dow methodology — top 5 yielders per GICS sector"}'),
    ('SDOG', 'benchmark',             1.0, 'human', '{"reason": "benchmark sector-diversified high-yield ETF"}'),
    ('SDOG', 'risk_off',              0.7, 'human', '{"reason": "contrarian/mean-reversion yield rotation, defensive tilt"}'),
    ('SDOG', 'spread_leg',            0.7, 'human', '{"reason": "VYM/SDOG broad vs sector-equal-weight yield spread"}'),
    -- BTAL
    ('BTAL', 'factor_market_neutral', 1.0, 'human', '{"reason": "long low-beta / short high-beta, dollar-neutral construction"}'),
    ('BTAL', 'benchmark',             1.0, 'human', '{"reason": "benchmark anti-beta long-short ETF"}'),
    ('BTAL', 'risk_off',              0.8, 'human', '{"reason": "low-beta outperforms high-beta in risk-off — BTAL rises"}'),
    ('BTAL', 'regime_classifier',     0.8, 'human', '{"reason": "near-zero net beta isolates factor rotation independent of market direction"}'),
    -- IPO
    ('IPO', 'high_beta',              1.0, 'human', '{"reason": "recent-listing factor — structurally higher volatility, no leverage/decay"}'),
    ('IPO', 'benchmark',              1.0, 'human', '{"reason": "benchmark recent-IPO ETF"}'),
    ('IPO', 'risk_off',               0.8, 'human', '{"reason": "speculative/high-beta names sell off hardest in risk-off"}'),
    ('IPO', 'spread_leg',             0.7, 'human', '{"reason": "IPO/SPY high-beta vs broad market spread"}'),
    -- SPHB
    ('SPHB', 'high_beta',             1.0, 'human', '{"reason": "top-100 highest-beta S&P 500 constituents"}'),
    ('SPHB', 'benchmark',             1.0, 'human', '{"reason": "benchmark high-beta S&P 500 ETF"}'),
    ('SPHB', 'risk_off',              0.8, 'human', '{"reason": "high-beta names amplify drawdowns in risk-off"}'),
    ('SPHB', 'spread_leg',            0.8, 'human', '{"reason": "SPHB/USMV high-beta vs low-vol factor spread"}')
ON CONFLICT (symbol, tag) DO NOTHING;

COMMIT;
