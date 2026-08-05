-- Migration 287: single-name equity expansion -- 80 -> 111 instruments.
--
-- First individual stocks in the corpus (everything prior is an ETF/basket).
-- 1. New tag_vocabulary row: single_name_equity -- a soft behavioral flag
--    (idiosyncratic earnings/M&A/litigation risk that basket-level exposure
--    tags don't capture), NOT a GICS classification-scheme fact. See
--    docs/foundation/glossary.md's `classification scheme` vs `taxonomy`
--    distinction -- this migration deliberately does not model GICS
--    membership; that's unscheduled (docs/research/platform-09-security-
--    classification-hierarchy.md).
-- 2. Register 31 new instruments (contract_details mirrors the existing
--    ETF pattern -- asset_class stays 'equity', which already covers both
--    ETFs and single names).
-- 3. Tag each with single_name_equity plus existing cycle_position/
--    macro_driver tags where the fit is genuine (not forced).
--
-- NOTE for whoever re-enables live ingestion: get_active_contracts() will
-- now return 111 is_active rows, 31 over the documented 80-line IBKR live
-- market-data-subscription cap (src/providers/CLAUDE.md). Not a backfill
-- problem (reqHistoricalDataAsync without keepUpToDate is pacing-limited,
-- not subscription-count-limited) and not live-ingestion problem today
-- (indicagent-ibkr-provider is confirmed stopped) -- but resolve
-- retire-vs-upgrade BEFORE restarting indicagent-ibkr-provider.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Tag vocabulary extension
-- ---------------------------------------------------------------------------

INSERT INTO tag_vocabulary (tag, category, description) VALUES
    ('single_name_equity', 'exposure', 'Individual company stock, not a diversified basket -- carries idiosyncratic earnings/M&A/litigation risk that basket-level exposure tags do not capture. Soft behavioral flag, not GICS scheme membership.')
ON CONFLICT (tag) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 2. Register 11 new instruments
--    contract_details mirrors the ETF pattern: symbol, base, name,
--    asset_class, exchange, sector, tick_size, session_id, point_value,
--    provider_meta. asset_class = 'equity' (unchanged -- covers ETFs and
--    single names alike). `sector` is the same loose descriptive string
--    convention already used for ETFs, not a formal classification.
-- ---------------------------------------------------------------------------

INSERT INTO instruments (symbol, base, contract_details, is_active) VALUES
    ('AAPL', 'AAPL', '{"symbol":"AAPL","base":"AAPL","name":"Apple Inc.","asset_class":"equity","exchange":"SMART","sector":"technology","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('JPM',  'JPM',  '{"symbol":"JPM","base":"JPM","name":"JPMorgan Chase & Co.","asset_class":"equity","exchange":"SMART","sector":"financials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('MCD',  'MCD',  '{"symbol":"MCD","base":"MCD","name":"McDonald''s Corporation","asset_class":"equity","exchange":"SMART","sector":"consumer_discretionary","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('PG',   'PG',   '{"symbol":"PG","base":"PG","name":"Procter & Gamble Company","asset_class":"equity","exchange":"SMART","sector":"consumer_staples","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('CAT',  'CAT',  '{"symbol":"CAT","base":"CAT","name":"Caterpillar Inc.","asset_class":"equity","exchange":"SMART","sector":"industrials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('MMM',  'MMM',  '{"symbol":"MMM","base":"MMM","name":"3M Company","asset_class":"equity","exchange":"SMART","sector":"industrials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('BA',   'BA',   '{"symbol":"BA","base":"BA","name":"Boeing Company","asset_class":"equity","exchange":"SMART","sector":"industrials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('FCX',  'FCX',  '{"symbol":"FCX","base":"FCX","name":"Freeport-McMoRan Inc.","asset_class":"equity","exchange":"SMART","sector":"materials_mining","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('NEM',  'NEM',  '{"symbol":"NEM","base":"NEM","name":"Newmont Corporation","asset_class":"equity","exchange":"SMART","sector":"materials_mining","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('NUE',  'NUE',  '{"symbol":"NUE","base":"NUE","name":"Nucor Corporation","asset_class":"equity","exchange":"SMART","sector":"materials_mining","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('DE',   'DE',   '{"symbol":"DE","base":"DE","name":"Deere & Company","asset_class":"equity","exchange":"SMART","sector":"industrials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('CVX',  'CVX',  '{"symbol":"CVX","base":"CVX","name":"Chevron Corporation","asset_class":"equity","exchange":"SMART","sector":"energy","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('KO',   'KO',   '{"symbol":"KO","base":"KO","name":"Coca-Cola Company","asset_class":"equity","exchange":"SMART","sector":"consumer_staples","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('DIS',  'DIS',  '{"symbol":"DIS","base":"DIS","name":"Walt Disney Company","asset_class":"equity","exchange":"SMART","sector":"communication_services","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('MRK',  'MRK',  '{"symbol":"MRK","base":"MRK","name":"Merck & Co., Inc.","asset_class":"equity","exchange":"SMART","sector":"healthcare","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('JNJ',  'JNJ',  '{"symbol":"JNJ","base":"JNJ","name":"Johnson & Johnson","asset_class":"equity","exchange":"SMART","sector":"healthcare","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('AXP',  'AXP',  '{"symbol":"AXP","base":"AXP","name":"American Express Company","asset_class":"equity","exchange":"SMART","sector":"financials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('HON',  'HON',  '{"symbol":"HON","base":"HON","name":"Honeywell International Inc.","asset_class":"equity","exchange":"SMART","sector":"industrials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('V',    'V',    '{"symbol":"V","base":"V","name":"Visa Inc.","asset_class":"equity","exchange":"SMART","sector":"financials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('TRV',  'TRV',  '{"symbol":"TRV","base":"TRV","name":"Travelers Companies, Inc.","asset_class":"equity","exchange":"SMART","sector":"financials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('XOM',  'XOM',  '{"symbol":"XOM","base":"XOM","name":"Exxon Mobil Corporation","asset_class":"equity","exchange":"SMART","sector":"energy","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('SLB',  'SLB',  '{"symbol":"SLB","base":"SLB","name":"Schlumberger Limited","asset_class":"equity","exchange":"SMART","sector":"energy","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('COP',  'COP',  '{"symbol":"COP","base":"COP","name":"ConocoPhillips","asset_class":"equity","exchange":"SMART","sector":"energy","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('AA',   'AA',   '{"symbol":"AA","base":"AA","name":"Alcoa Corporation","asset_class":"equity","exchange":"SMART","sector":"materials_mining","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('BHP',  'BHP',  '{"symbol":"BHP","base":"BHP","name":"BHP Group Limited","asset_class":"equity","exchange":"SMART","sector":"materials_mining","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('GE',   'GE',   '{"symbol":"GE","base":"GE","name":"General Electric Company","asset_class":"equity","exchange":"SMART","sector":"industrials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('UNP',  'UNP',  '{"symbol":"UNP","base":"UNP","name":"Union Pacific Corporation","asset_class":"equity","exchange":"SMART","sector":"industrials_rail","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('EMR',  'EMR',  '{"symbol":"EMR","base":"EMR","name":"Emerson Electric Co.","asset_class":"equity","exchange":"SMART","sector":"industrials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('DD',   'DD',   '{"symbol":"DD","base":"DD","name":"DuPont de Nemours, Inc.","asset_class":"equity","exchange":"SMART","sector":"materials_chemicals","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('LIN',  'LIN',  '{"symbol":"LIN","base":"LIN","name":"Linde plc","asset_class":"equity","exchange":"SMART","sector":"materials_chemicals","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('OXY',  'OXY',  '{"symbol":"OXY","base":"OXY","name":"Occidental Petroleum Corporation","asset_class":"equity","exchange":"SMART","sector":"energy","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true)
ON CONFLICT (symbol) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. Tag new instruments -- single_name_equity always, plus existing
--    cycle_position/macro_driver tags only where the fit is genuine.
-- ---------------------------------------------------------------------------

INSERT INTO instrument_tags (symbol, tag, weight, source, evidence) VALUES
    ('AAPL', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('AAPL', 'mid_cycle',          0.6, 'human', '{"reason": "earnings/capex-driven growth tech"}'),

    ('JPM',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('JPM',  'early_cycle',        0.8, 'human', '{"reason": "money-center bank -- credit-driven, domestically exposed"}'),

    ('MCD',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('MCD',  'recession',          0.7, 'human', '{"reason": "defensive cash flows -- historically recession-resistant QSR"}'),

    ('PG',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('PG',   'recession',          0.8, 'human', '{"reason": "consumer staples -- classic defensive cash flows"}'),

    ('CAT',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('CAT',  'late_cycle',         0.8, 'human', '{"reason": "heavy machinery capex, commodity price sensitive margins"}'),
    ('CAT',  'china_demand',       0.7, 'human', '{"reason": "construction/mining equipment tied to China infrastructure demand"}'),

    ('MMM',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('MMM',  'mid_cycle',          0.6, 'human', '{"reason": "diversified industrial conglomerate, capex-driven"}'),

    ('BA',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('BA',   'mid_cycle',          0.6, 'human', '{"reason": "aerospace capex/order-cycle driven"}'),

    ('FCX',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('FCX',  'late_cycle',         0.8, 'human', '{"reason": "copper miner -- commodity price elevated late expansion"}'),
    ('FCX',  'china_demand',       0.9, 'human', '{"reason": "copper is the primary China industrial-demand proxy commodity"}'),

    ('NEM',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('NEM',  'inflation',          0.8, 'human', '{"reason": "gold miner -- inflation/monetary hedge, not economic-cycle-tied like industrial miners"}'),

    ('NUE',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('NUE',  'late_cycle',         0.7, 'human', '{"reason": "steel producer -- construction/infrastructure demand, margins peak late expansion"}'),

    ('DE',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('DE',   'late_cycle',         0.7, 'human', '{"reason": "agricultural/construction equipment capex-driven"}'),

    ('CVX',  'single_name_equity',    1.0, 'human', '{"reason": "individual company stock"}'),
    ('CVX',  'commodity_energy_crude',0.9, 'human', '{"reason": "integrated oil major -- direct WTI/Brent price beta"}'),
    ('CVX',  'late_cycle',            0.7, 'human', '{"reason": "energy major -- margins peak on elevated commodity prices late expansion"}'),

    ('KO',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('KO',   'recession',          0.8, 'human', '{"reason": "consumer staples -- classic defensive cash flows"}'),

    ('DIS',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('DIS',  'mid_cycle',          0.6, 'human', '{"reason": "media/entertainment/parks -- discretionary spend, earnings-driven"}'),

    ('MRK',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('MRK',  'recession',          0.7, 'human', '{"reason": "pharma -- inelastic demand, defensive cash flows"}'),

    ('JNJ',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('JNJ',  'recession',          0.8, 'human', '{"reason": "diversified healthcare/pharma/consumer -- classic defensive"}'),

    ('AXP',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('AXP',  'early_cycle',        0.7, 'human', '{"reason": "payments/credit network -- consumer spend and credit-driven"}'),

    ('HON',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('HON',  'mid_cycle',          0.6, 'human', '{"reason": "diversified industrial conglomerate, capex-driven"}'),

    ('V',    'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('V',    'early_cycle',        0.7, 'human', '{"reason": "payments network -- consumer spend and credit-driven, same family as AXP"}'),

    ('TRV',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('TRV',  'mid_cycle',          0.5, 'human', '{"reason": "P&C insurer -- underwriting/rate-cycle driven, softer economic-cycle fit than banks"}'),

    ('XOM',  'single_name_equity',    1.0, 'human', '{"reason": "individual company stock"}'),
    ('XOM',  'commodity_energy_crude',0.9, 'human', '{"reason": "integrated oil supermajor -- direct WTI/Brent price beta, pairs with CVX"}'),
    ('XOM',  'late_cycle',            0.7, 'human', '{"reason": "energy major -- margins peak on elevated commodity prices late expansion"}'),

    ('SLB',  'single_name_equity',    1.0, 'human', '{"reason": "individual company stock"}'),
    ('SLB',  'commodity_energy_crude',0.7, 'human', '{"reason": "oilfield services -- crude capex beta, distinct sub-sector from integrated majors"}'),
    ('SLB',  'late_cycle',            0.6, 'human', '{"reason": "E&P capex spend peaks late expansion on elevated commodity prices"}'),

    ('COP',  'single_name_equity',    1.0, 'human', '{"reason": "individual company stock"}'),
    ('COP',  'commodity_energy_crude',0.9, 'human', '{"reason": "pure-play E&P, no downstream/refining -- cleaner crude price beta than integrated majors"}'),
    ('COP',  'late_cycle',            0.7, 'human', '{"reason": "margins peak on elevated commodity prices late expansion"}'),

    ('AA',   'single_name_equity',        1.0, 'human', '{"reason": "individual company stock"}'),
    ('AA',   'commodity_metals_industrial',0.9, 'human', '{"reason": "aluminum producer -- industrial base metal demand proxy"}'),
    ('AA',   'china_demand',              0.7, 'human', '{"reason": "aluminum demand driven by global (especially China) industrial/construction activity"}'),
    ('AA',   'late_cycle',                0.7, 'human', '{"reason": "margins peak on elevated commodity prices late expansion"}'),

    ('BHP',  'single_name_equity',        1.0, 'human', '{"reason": "individual company stock"}'),
    ('BHP',  'commodity_metals_industrial',0.8, 'human', '{"reason": "diversified major miner -- iron ore, copper, coal; broader commodity basket than single-metal peers"}'),
    ('BHP',  'china_demand',              0.9, 'human', '{"reason": "iron ore/copper demand dominated by China steel and infrastructure demand"}'),
    ('BHP',  'late_cycle',                0.7, 'human', '{"reason": "margins peak on elevated commodity prices late expansion"}'),

    ('GE',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('GE',   'mid_cycle',          0.6, 'human', '{"reason": "diversified industrial conglomerate (aerospace/power), capex-driven"}'),

    ('UNP',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('UNP',  'transports',         1.0, 'human', '{"reason": "class I railroad -- same transports tag family as IYT"}'),
    ('UNP',  'leading_indicator',  0.9, 'human', '{"reason": "rail carload volume is a textbook leading economic indicator"}'),
    ('UNP',  'early_cycle',        0.6, 'human', '{"reason": "freight volume recovers early in expansion"}'),

    ('EMR',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('EMR',  'mid_cycle',          0.6, 'human', '{"reason": "industrial automation -- capex/tech-spend driven"}'),

    ('DD',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('DD',   'mid_cycle',          0.5, 'human', '{"reason": "specialty chemicals -- diversified end markets, earnings-driven"}'),

    ('LIN',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('LIN',  'mid_cycle',          0.5, 'human', '{"reason": "industrial gases -- ubiquitous industrial input, broad economic-activity proxy"}'),

    ('OXY',  'single_name_equity',    1.0, 'human', '{"reason": "individual company stock"}'),
    ('OXY',  'commodity_energy_crude',0.9, 'human', '{"reason": "pure-play E&P -- direct WTI price beta"}'),
    ('OXY',  'late_cycle',            0.7, 'human', '{"reason": "margins peak on elevated commodity prices late expansion"}')
ON CONFLICT (symbol, tag) DO NOTHING;

COMMIT;
