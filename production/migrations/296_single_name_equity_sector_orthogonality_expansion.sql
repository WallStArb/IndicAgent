-- Migration 296: single-name equity sector-orthogonality expansion -- 111 -> 153 instruments.
--
-- Consolidated from three separate uncommitted migration files (296/298/299) into one -- same
-- underlying task (fill single-name-equity sector gaps for cross-sector orthogonality), done in
-- three passes during one session because each pass surfaced the next gap. User feedback
-- 2026-08-05: don't leave multiple migration files sitting around for one continuous piece of
-- work, merge into one before committing.
--
-- Three waves, each auditing "does this sector have 2+ single names with genuinely distinct
-- factor loadings, not just 2+ names":
--
-- Wave 1 (rate-sensitive + uranium): real_estate (XLRE) and utilities (XLU) had ZERO single-name
-- complements -- the two textbook negatively rate-sensitive equity sectors (rising rates ->
-- cap-rate expansion / bond-proxy discounting -> price falls). Uranium/nuclear had no exposure
-- anywhere in the corpus, ETF or single-name -- economically distinct from the industrial-metals
-- complex already covered by FCX/NUE/BHP/AA (nuclear buildout + energy-security driven, not
-- industrial demand driven). New tag_vocabulary entry `commodity_uranium` added -- no existing
-- tag captures this commodity category. Also filled communication_services (had only DIS) with
-- a telecom pure-play, same rate-sensitive/bond-proxy mechanism.
--
-- Wave 2 (broad sector-orthogonality sweep): technology (AAPL only, consumer-hardware
-- idiosyncratic, zero semis/AI-capex or software/cloud representation) and every other sector
-- with thin or redundant coverage -- healthcare, financials, staples, discretionary,
-- industrials, communication services, materials chemicals. Added names carrying a genuinely
-- distinct primary driver from what was already present in the same sector.
--
-- Wave 3 (financials depth + remaining gaps): financials still lacked wealth management,
-- super-regional banking, pure underwriting, and fee/AUM asset management as distinct business
-- models (only money-center banking, card networks, and trading were covered). Also closed the
-- remaining sector-orthogonality items: zero auto exposure, zero e-commerce/cloud-retail
-- exposure, no data-center REIT, no foundry semis (distinct manufacturing-driven profile +
-- genuinely distinct geopolitical risk factor vs. fabless design), no pure biotech, no
-- homebuilder, no parcel/logistics single name, no travel/leisure, no medtech/devices, no
-- airline. KRE (regional banking ETF, already in the corpus and well-tagged) had its
-- contract_details `sector` field backfilled -- it predates that convention.
--
-- BRK.B intentionally excluded from wave 3: instruments.symbol passes straight through to
-- ib_async's Stock(symbol=...) with no dot/space translation (src/providers/ibkr.py:942) --
-- IBKR expects class shares as "BRK B" (space), and a space in `symbol` risks breaking
-- stream_keys.py's dots-only topic convention downstream. GS/BAC/MS already cover the
-- investment-bank/money-center financials angle without the special case.
--
-- Where a wave's review listed an either/or pair, one representative was picked for liquidity/
-- clarity of the target factor: EQIX over DLR (data-center REIT), TSM as the single foundry
-- name, VRTX over AMGN (VRTX's concentrated single-franchise profile is more distinctly
-- "biotech" than AMGN's increasingly diversified-pharma-like profile), DHI over LEN (largest
-- homebuilder by volume), UPS over FDX, BKNG over MAR (BKNG's OTA model captures travel demand
-- across brands rather than one owned/managed hotel chain).
--
-- contract_details mirrors the existing ETF/single-name shape throughout; sector is a loose
-- descriptive string (not GICS); tags use existing vocabulary except commodity_uranium
-- (justified in wave 1).
--
-- Historical backfill NOT launched by this migration -- all 53 zero-data symbols (11 from
-- migration 287's incomplete backfill + the 42 registered here) are tracked as one consolidated
-- queue in todo 259, sequenced behind the in-flight client-id 41 run per this project's
-- no-concurrent-IBKR-sessions precedent.

BEGIN;

-- ---------------------------------------------------------------------------
-- Wave 1: tag vocabulary extension -- commodity_uranium is a genuinely new category, not
-- covered by commodity_metals_industrial/precious (uranium is neither an industrial base metal
-- nor a precious metal -- distinct supply/demand driver: nuclear fuel cycle, not industrial
-- production or monetary hedging).
-- ---------------------------------------------------------------------------

INSERT INTO tag_vocabulary (tag, category, description) VALUES
    ('commodity_uranium', 'exposure', 'Uranium/nuclear fuel cycle exposure -- distinct commodity complex from industrial or precious metals, driven by nuclear power buildout and fuel-supply-chain geopolitics (Russian/Kazakh production share), not the industrial-production or China-demand cycle that industrial metals share.')
ON CONFLICT (tag) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Wave 3: backfill sector on KRE (pre-dates the `sector` field convention; already well-tagged
-- in instrument_tags, this just aligns contract_details).
-- ---------------------------------------------------------------------------

UPDATE instruments
SET contract_details = jsonb_set(contract_details, '{sector}', '"financials"')
WHERE symbol = 'KRE';

-- ---------------------------------------------------------------------------
-- Register instruments -- 42 new symbols across all three waves.
-- ---------------------------------------------------------------------------

INSERT INTO instruments (symbol, base, contract_details, is_active) VALUES
    -- Wave 1: rate-sensitive sector fill + uranium complex
    ('URA', 'URA', '{"symbol":"URA","base":"URA","name":"Global X Uranium ETF","asset_class":"equity","exchange":"SMART","sector":"uranium_miners","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('CCJ', 'CCJ', '{"symbol":"CCJ","base":"CCJ","name":"Cameco Corporation","asset_class":"equity","exchange":"SMART","sector":"materials_mining_uranium","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('PLD', 'PLD', '{"symbol":"PLD","base":"PLD","name":"Prologis, Inc.","asset_class":"equity","exchange":"SMART","sector":"real_estate","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('SO',  'SO',  '{"symbol":"SO","base":"SO","name":"The Southern Company","asset_class":"equity","exchange":"SMART","sector":"utilities","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('VZ',  'VZ',  '{"symbol":"VZ","base":"VZ","name":"Verizon Communications Inc.","asset_class":"equity","exchange":"SMART","sector":"communication_services","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),

    -- Wave 2: technology, healthcare, financials, staples, discretionary, industrials,
    -- real_estate, utilities, communication_services, materials_chemicals
    ('MSFT', 'MSFT', '{"symbol":"MSFT","base":"MSFT","name":"Microsoft Corporation","asset_class":"equity","exchange":"SMART","sector":"technology","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('NVDA', 'NVDA', '{"symbol":"NVDA","base":"NVDA","name":"NVIDIA Corporation","asset_class":"equity","exchange":"SMART","sector":"technology","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('AVGO', 'AVGO', '{"symbol":"AVGO","base":"AVGO","name":"Broadcom Inc.","asset_class":"equity","exchange":"SMART","sector":"technology","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('UNH',  'UNH',  '{"symbol":"UNH","base":"UNH","name":"UnitedHealth Group Incorporated","asset_class":"equity","exchange":"SMART","sector":"healthcare","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('LLY',  'LLY',  '{"symbol":"LLY","base":"LLY","name":"Eli Lilly and Company","asset_class":"equity","exchange":"SMART","sector":"healthcare","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('PFE',  'PFE',  '{"symbol":"PFE","base":"PFE","name":"Pfizer Inc.","asset_class":"equity","exchange":"SMART","sector":"healthcare","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('GS',   'GS',   '{"symbol":"GS","base":"GS","name":"The Goldman Sachs Group, Inc.","asset_class":"equity","exchange":"SMART","sector":"financials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('BAC',  'BAC',  '{"symbol":"BAC","base":"BAC","name":"Bank of America Corporation","asset_class":"equity","exchange":"SMART","sector":"financials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('COST', 'COST', '{"symbol":"COST","base":"COST","name":"Costco Wholesale Corporation","asset_class":"equity","exchange":"SMART","sector":"consumer_staples","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('PEP',  'PEP',  '{"symbol":"PEP","base":"PEP","name":"PepsiCo, Inc.","asset_class":"equity","exchange":"SMART","sector":"consumer_staples","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('WMT',  'WMT',  '{"symbol":"WMT","base":"WMT","name":"Walmart Inc.","asset_class":"equity","exchange":"SMART","sector":"consumer_staples","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('HD',   'HD',   '{"symbol":"HD","base":"HD","name":"The Home Depot, Inc.","asset_class":"equity","exchange":"SMART","sector":"consumer_discretionary","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('RTX',  'RTX',  '{"symbol":"RTX","base":"RTX","name":"RTX Corporation","asset_class":"equity","exchange":"SMART","sector":"industrials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('AMT',  'AMT',  '{"symbol":"AMT","base":"AMT","name":"American Tower Corporation","asset_class":"equity","exchange":"SMART","sector":"real_estate","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('NEE',  'NEE',  '{"symbol":"NEE","base":"NEE","name":"NextEra Energy, Inc.","asset_class":"equity","exchange":"SMART","sector":"utilities","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('DUK',  'DUK',  '{"symbol":"DUK","base":"DUK","name":"Duke Energy Corporation","asset_class":"equity","exchange":"SMART","sector":"utilities","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('AEP',  'AEP',  '{"symbol":"AEP","base":"AEP","name":"American Electric Power Company, Inc.","asset_class":"equity","exchange":"SMART","sector":"utilities","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('CMCSA','CMCSA','{"symbol":"CMCSA","base":"CMCSA","name":"Comcast Corporation","asset_class":"equity","exchange":"SMART","sector":"communication_services","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('NFLX', 'NFLX', '{"symbol":"NFLX","base":"NFLX","name":"Netflix, Inc.","asset_class":"equity","exchange":"SMART","sector":"communication_services","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('T',    'T',    '{"symbol":"T","base":"T","name":"AT&T Inc.","asset_class":"equity","exchange":"SMART","sector":"communication_services","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('TMUS', 'TMUS', '{"symbol":"TMUS","base":"TMUS","name":"T-Mobile US, Inc.","asset_class":"equity","exchange":"SMART","sector":"communication_services","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('ECL',  'ECL',  '{"symbol":"ECL","base":"ECL","name":"Ecolab Inc.","asset_class":"equity","exchange":"SMART","sector":"materials_chemicals","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('DOW',  'DOW',  '{"symbol":"DOW","base":"DOW","name":"Dow Inc.","asset_class":"equity","exchange":"SMART","sector":"materials_chemicals","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),

    -- Wave 3: financials depth + remaining orthogonality gaps
    ('MS',   'MS',   '{"symbol":"MS","base":"MS","name":"Morgan Stanley","asset_class":"equity","exchange":"SMART","sector":"financials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('USB',  'USB',  '{"symbol":"USB","base":"USB","name":"U.S. Bancorp","asset_class":"equity","exchange":"SMART","sector":"financials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('PGR',  'PGR',  '{"symbol":"PGR","base":"PGR","name":"The Progressive Corporation","asset_class":"equity","exchange":"SMART","sector":"financials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('BLK',  'BLK',  '{"symbol":"BLK","base":"BLK","name":"BlackRock, Inc.","asset_class":"equity","exchange":"SMART","sector":"financials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('AMZN', 'AMZN', '{"symbol":"AMZN","base":"AMZN","name":"Amazon.com, Inc.","asset_class":"equity","exchange":"SMART","sector":"consumer_discretionary","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('TSLA', 'TSLA', '{"symbol":"TSLA","base":"TSLA","name":"Tesla, Inc.","asset_class":"equity","exchange":"SMART","sector":"consumer_discretionary","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('DHI',  'DHI',  '{"symbol":"DHI","base":"DHI","name":"D.R. Horton, Inc.","asset_class":"equity","exchange":"SMART","sector":"consumer_discretionary","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('BKNG', 'BKNG', '{"symbol":"BKNG","base":"BKNG","name":"Booking Holdings Inc.","asset_class":"equity","exchange":"SMART","sector":"consumer_discretionary","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('EQIX', 'EQIX', '{"symbol":"EQIX","base":"EQIX","name":"Equinix, Inc.","asset_class":"equity","exchange":"SMART","sector":"real_estate","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('TSM',  'TSM',  '{"symbol":"TSM","base":"TSM","name":"Taiwan Semiconductor Manufacturing Company Limited","asset_class":"equity","exchange":"SMART","sector":"technology","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('VRTX', 'VRTX', '{"symbol":"VRTX","base":"VRTX","name":"Vertex Pharmaceuticals Incorporated","asset_class":"equity","exchange":"SMART","sector":"healthcare","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('ISRG', 'ISRG', '{"symbol":"ISRG","base":"ISRG","name":"Intuitive Surgical, Inc.","asset_class":"equity","exchange":"SMART","sector":"healthcare","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('UPS',  'UPS',  '{"symbol":"UPS","base":"UPS","name":"United Parcel Service, Inc.","asset_class":"equity","exchange":"SMART","sector":"industrials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('DAL',  'DAL',  '{"symbol":"DAL","base":"DAL","name":"Delta Air Lines, Inc.","asset_class":"equity","exchange":"SMART","sector":"industrials","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true)
ON CONFLICT (symbol) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Tag new instruments -- single_name_equity on all non-basket names, plus sensitivity/
-- exposure/macro_driver tags only where the fit is genuine. No tags needed beyond
-- commodity_uranium (wave 1) -- semi_cycle, rate_sensitive, defensive_yield, geopolitical,
-- china_demand, real_estate, transports, oil_price, high_beta, yield_curve all pre-existed.
-- ---------------------------------------------------------------------------

INSERT INTO instrument_tags (symbol, tag, weight, source, evidence) VALUES
    -- Wave 1
    ('URA', 'commodity_uranium', 1.0, 'human', '{"reason": "uranium miners basket -- diversified uranium/nuclear fuel cycle exposure"}'),
    ('URA', 'geopolitical',      0.7, 'human', '{"reason": "nuclear fuel supply chain -- sanctions/geopolitics sensitive given Russian/Kazakh production share"}'),
    ('URA', 'benchmark',         1.0, 'human', '{"reason": "uranium miners basket, benchmark exposure -- same role GDX plays for gold miners"}'),
    ('CCJ', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('CCJ', 'commodity_uranium',  0.9, 'human', '{"reason": "largest low-cost uranium producer -- direct exposure to uranium spot/contract price"}'),
    ('CCJ', 'geopolitical',       0.7, 'human', '{"reason": "nuclear fuel supply chain -- sanctions/geopolitics sensitive given Russian/Kazakh production share, pairs with URA"}'),
    ('PLD', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('PLD', 'rate_sensitive',     0.9, 'human', '{"reason": "industrial/logistics REIT -- cap-rate/discount-rate mechanics make REITs directly and negatively sensitive to rising rates"}'),
    ('PLD', 'real_estate',        1.0, 'human', '{"reason": "largest industrial REIT, real_estate sector complement to XLRE (previously zero single names)"}'),
    ('SO',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('SO',  'rate_sensitive',     0.9, 'human', '{"reason": "regulated utility -- classic bond-proxy, negatively correlated to rate moves; picked over NEE for a purer signal (NEE mixes in renewables-growth narrative)"}'),
    ('SO',  'defensive_yield',    0.7, 'human', '{"reason": "regulated utility dividend -- defensive cash flows, same family as SDOG/VYM"}'),
    ('VZ',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('VZ',  'rate_sensitive',     0.8, 'human', '{"reason": "high-dividend-yield telecom -- bond-proxy behavior, negatively rate-sensitive similar to utilities/REITs"}'),
    ('VZ',  'defensive_yield',    0.6, 'human', '{"reason": "high dividend telecom, orthogonal to DIS media/content-earnings risk within same communication_services sector"}'),

    -- Wave 2
    ('MSFT',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('NVDA',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('NVDA',  'semi_cycle',         0.9, 'human', '{"reason": "datacenter/AI-accelerator GPU demand -- distinct from AAPL consumer hardware, high sensitivity to AI capex cycle"}'),
    ('AVGO',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('AVGO',  'semi_cycle',         0.8, 'human', '{"reason": "networking/custom-silicon semis plus enterprise software (VMware) -- diversified semis profile distinct from NVDA pure-play GPU exposure"}'),
    ('UNH',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- managed care/payer, reimbursement-driven, distinct from JNJ/MRK pharma R&D pipeline risk"}'),
    ('LLY',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- concentrated GLP-1/obesity franchise, distinct growth profile from JNJ/MRK diversified pharma"}'),
    ('PFE',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('GS',    'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- trading/investment-banking revenue mix, distinct from JPM NIM/deposit-driven model"}'),
    ('BAC',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('COST',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- membership retail, foot-traffic/margin driven, distinct from KO/PG brand pricing power"}'),
    ('PEP',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('PEP',   'defensive_yield',    0.6, 'human', '{"reason": "consistent dividend payer, same family as KO"}'),
    ('WMT',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('HD',    'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('HD',    'rate_sensitive',     0.7, 'human', '{"reason": "housing turnover/mortgage-rate demand sensitivity -- distinct mechanism from REIT/utility bond-proxy discounting (demand-side, not valuation-side)"}'),
    ('RTX',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('RTX',   'geopolitical',       0.6, 'human', '{"reason": "defense/aerospace revenue tied to government spending and geopolitical tensions, distinct from BA commercial-aviation-heavy mix"}'),
    ('AMT',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('AMT',   'rate_sensitive',     0.9, 'human', '{"reason": "cell tower REIT -- cap-rate/discount-rate mechanics, same bond-proxy family as PLD but digital-infrastructure demand driven, not e-commerce logistics"}'),
    ('AMT',   'real_estate',        1.0, 'human', '{"reason": "REIT structure, real_estate sector complement to PLD"}'),
    ('NEE',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('NEE',   'rate_sensitive',     0.9, 'human', '{"reason": "regulated utility plus renewables growth -- bond-proxy mechanics with a growth overlay, distinct from SO pure regulated-baseload model"}'),
    ('NEE',   'defensive_yield',    0.6, 'human', '{"reason": "utility dividend, defensive cash flows"}'),
    ('DUK',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('DUK',   'rate_sensitive',     0.9, 'human', '{"reason": "Mid-Atlantic regulated electric -- bond-proxy discounting, distinct rate-case/regulatory geography from SO/NEE"}'),
    ('DUK',   'defensive_yield',    0.7, 'human', '{"reason": "utility dividend, defensive cash flows"}'),
    ('AEP',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('AEP',   'rate_sensitive',     0.8, 'human', '{"reason": "transmission/distribution grid buildout -- bond-proxy discounting on rate-base growth, distinct capex profile from generation-focused SO/DUK"}'),
    ('AEP',   'defensive_yield',    0.6, 'human', '{"reason": "utility dividend, defensive cash flows"}'),
    ('CMCSA', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- broadband/cable distribution plus media, distinct from DIS content-only and VZ wireless-only models"}'),
    ('NFLX',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- subscription streaming, distinct ad-free/content-spend model from DIS diversified media"}'),
    ('T',     'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('T',     'rate_sensitive',     0.7, 'human', '{"reason": "high-dividend-yield telecom -- bond-proxy behavior, same family as VZ"}'),
    ('T',     'defensive_yield',    0.7, 'human', '{"reason": "high dividend telecom, defensive cash flows"}'),
    ('TMUS',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- wireless share-gain/growth profile, distinct from VZ/T mature-carrier defensive profile"}'),
    ('ECL',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- specialty chemicals, institutional/hygiene end-markets, distinct from LIN industrial-gas take-or-pay contracts"}'),
    ('DOW',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock"}'),
    ('DOW',   'china_demand',       0.6, 'human', '{"reason": "commodity chemicals -- ethylene/polyethylene margins tied to global industrial/manufacturing demand"}'),

    -- Wave 3
    ('MS',   'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- wealth-management-heavy revenue mix, distinct from GS trading-heavy and JPM/BAC deposit-driven models"}'),
    ('USB',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- largest pure super-regional bank, complements KRE with single-name exposure"}'),
    ('USB',  'yield_curve',        0.7, 'human', '{"reason": "regional bank NIM directly sensitive to yield curve slope, sharper than diversified money-center JPM/BAC"}'),
    ('PGR',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- direct-to-consumer auto underwriter, distinct underwriting model from TRV commercial P&C"}'),
    ('BLK',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- fee/AUM-driven asset management, distinct revenue mechanism from NIM, trading, or underwriting"}'),
    ('AMZN', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- e-commerce plus cloud infrastructure (AWS), zero prior exposure to either"}'),
    ('TSLA', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- EV/battery supply chain, zero prior auto exposure"}'),
    ('TSLA', 'high_beta',          0.8, 'human', '{"reason": "structurally elevated volatility and retail-investor-driven flow, distinct beta profile from rest of universe"}'),
    ('DHI',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- largest homebuilder by volume"}'),
    ('DHI',  'rate_sensitive',     0.8, 'human', '{"reason": "new-construction demand directly tied to mortgage rates, sharper mechanism than HD renovation-retail exposure"}'),
    ('BKNG', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- OTA model captures travel demand across hotel/loyalty brands, zero prior travel/leisure exposure"}'),
    ('EQIX', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- data-center REIT, AI/cloud-infra demand driven"}'),
    ('EQIX', 'rate_sensitive',     0.9, 'human', '{"reason": "REIT cap-rate/discount-rate mechanics, same bond-proxy family as PLD/AMT but interconnection/data-center demand driven"}'),
    ('EQIX', 'real_estate',        1.0, 'human', '{"reason": "REIT structure, third distinct real_estate single-name driver alongside PLD (logistics) and AMT (wireless towers)"}'),
    ('TSM',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- foundry manufacturing, distinct from NVDA/AVGO fabless design"}'),
    ('TSM',  'semi_cycle',         0.9, 'human', '{"reason": "leading-edge foundry capacity is the physical bottleneck of the AI-capex cycle"}'),
    ('TSM',  'geopolitical',       0.8, 'human', '{"reason": "Taiwan Strait tension is a distinct geopolitical risk factor not present in any other current holding"}'),
    ('VRTX', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- concentrated single-franchise (cystic fibrosis) biotech, binary FDA/pipeline event risk distinct from diversified pharma (JNJ/MRK/LLY/PFE)"}'),
    ('ISRG', 'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- capital-equipment plus procedure-volume driven medtech, isolates from pharma R&D-pipeline risk"}'),
    ('UPS',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- parcel/logistics, e-commerce-volume driven"}'),
    ('UPS',  'transports',         1.0, 'human', '{"reason": "distinct freight mechanism from UNP rail/bulk -- parcel/last-mile vs. bulk intermodal"}'),
    ('DAL',  'single_name_equity', 1.0, 'human', '{"reason": "individual company stock -- airline, zero prior exposure to jet-fuel-cost/travel-demand cyclicality"}'),
    ('DAL',  'transports',         1.0, 'human', '{"reason": "distinct freight/passenger mechanism from UNP rail and UPS parcel -- passenger travel demand, not freight"}'),
    ('DAL',  'oil_price',          0.7, 'human', '{"reason": "jet fuel is airlines'' largest variable cost, direct crude-oil sensitivity distinct from energy-sector exposure to oil price on the production side"}')
ON CONFLICT (symbol, tag) DO NOTHING;

COMMIT;
