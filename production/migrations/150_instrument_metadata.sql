-- Migration 150: instrument_metadata table
--
-- Stores reference data that is distinct from trading mechanics (instruments table):
--   listing_date      - when the instrument first started trading; limits backfill depth
--   underlying_index  - what index/asset the instrument tracks (ETFs)
--   issuer            - fund company or exchange (ETFs/futures)
--   description       - brief human-readable description
--
-- Applies to all instrument types: ETFs, stocks, futures, FX.
-- listing_date is the primary operational field: the backfill pipeline uses it
-- to skip IBKR requests for bars before the instrument existed.

CREATE TABLE IF NOT EXISTS instrument_metadata (
    symbol           text        PRIMARY KEY REFERENCES instruments(symbol) ON DELETE CASCADE,
    listing_date     date,
    underlying_index text,
    issuer           text,
    description      text,
    created_at       timestamptz NOT NULL DEFAULT NOW(),
    updated_at       timestamptz NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_instrument_metadata_listing_date ON instrument_metadata(listing_date);

-- ---------------------------------------------------------------------------
-- Seed data — all 58 active instruments
-- ---------------------------------------------------------------------------

INSERT INTO instrument_metadata (symbol, listing_date, underlying_index, issuer, description) VALUES

-- Broad market ETFs
('SPY',  '1993-01-22', 'S&P 500',             'State Street',  'SPDR S&P 500 ETF — oldest and most liquid US equity ETF'),
('QQQ',  '1999-03-10', 'Nasdaq-100',           'Invesco',       'Invesco QQQ Trust — top 100 non-financial Nasdaq companies'),
('IWM',  '2000-05-22', 'Russell 2000',         'BlackRock',     'iShares Russell 2000 — US small-cap equities'),
('DIA',  '1998-01-13', 'Dow Jones Industrial', 'State Street',  'SPDR Dow Jones Industrial Average ETF'),

-- Sector ETFs (all launched 1998-12-16 as original SPDR Sector suite)
('XLF',  '1998-12-16', 'S&P 500 Financials',          'State Street', 'Financial Select Sector SPDR'),
('XLE',  '1998-12-16', 'S&P 500 Energy',              'State Street', 'Energy Select Sector SPDR'),
('XLK',  '1998-12-16', 'S&P 500 Technology',          'State Street', 'Technology Select Sector SPDR'),
('XLY',  '1998-12-16', 'S&P 500 Consumer Disc',       'State Street', 'Consumer Discretionary Select Sector SPDR'),
('XLV',  '1998-12-16', 'S&P 500 Health Care',         'State Street', 'Health Care Select Sector SPDR'),
('XLI',  '1998-12-16', 'S&P 500 Industrials',         'State Street', 'Industrial Select Sector SPDR'),
('XLU',  '1998-12-16', 'S&P 500 Utilities',           'State Street', 'Utilities Select Sector SPDR'),
('XLP',  '1998-12-16', 'S&P 500 Consumer Staples',    'State Street', 'Consumer Staples Select Sector SPDR'),
('XLB',  '1998-12-16', 'S&P 500 Materials',           'State Street', 'Materials Select Sector SPDR'),
('XLC',  '2018-06-18', 'S&P 500 Communication Svcs',  'State Street', 'Communication Services Select Sector SPDR'),
('XLRE', '2015-10-07', 'S&P 500 Real Estate',         'State Street', 'Real Estate Select Sector SPDR'),

-- Fixed income ETFs
('TLT',  '2002-07-22', 'ICE US Treasury 20+ Year',    'BlackRock', 'iShares 20+ Year Treasury Bond ETF'),
('IEF',  '2002-07-22', 'ICE US Treasury 7-10 Year',   'BlackRock', 'iShares 7-10 Year Treasury Bond ETF'),
('SHY',  '2002-07-22', 'ICE US Treasury 1-3 Year',    'BlackRock', 'iShares 1-3 Year Treasury Bond ETF'),
('AGG',  '2003-09-22', 'Bloomberg US Aggregate Bond', 'BlackRock', 'iShares Core US Aggregate Bond ETF'),
('HYG',  '2007-04-04', 'Markit iBoxx USD Liquid HY',  'BlackRock', 'iShares iBoxx High Yield Corporate Bond ETF'),
('LQD',  '2002-07-22', 'Markit iBoxx USD Liquid IG',  'BlackRock', 'iShares iBoxx Investment Grade Corporate Bond ETF'),
('EMB',  '2007-12-17', 'JPM EMBI Global Core',        'BlackRock', 'iShares JP Morgan USD Emerging Markets Bond ETF'),
('MUB',  '2007-09-07', 'ICE AMT-Free US National Muni','BlackRock','iShares National Muni Bond ETF'),
('TIP',  '2003-12-04', 'Bloomberg US TIPS',            'BlackRock', 'iShares TIPS Bond ETF — inflation-protected'),
('BIL',  '2007-05-25', 'Bloomberg 1-3 Month T-Bill',  'State Street','SPDR Bloomberg 1-3 Month T-Bill ETF'),
('PFF',  '2007-03-26', 'ICE Exchange-Listed Preferred','BlackRock', 'iShares Preferred and Income Securities ETF'),

-- International ETFs
('EFA',  '2001-08-14', 'MSCI EAFE',                   'BlackRock', 'iShares MSCI EAFE — developed markets ex US/Canada'),
('EEM',  '2003-04-07', 'MSCI Emerging Markets',       'BlackRock', 'iShares MSCI Emerging Markets ETF'),
('EWJ',  '1996-03-12', 'MSCI Japan',                  'BlackRock', 'iShares MSCI Japan ETF'),
('EWT',  '1996-03-12', 'MSCI Taiwan',                 'BlackRock', 'iShares MSCI Taiwan ETF'),
('EWY',  '1996-05-09', 'MSCI South Korea',            'BlackRock', 'iShares MSCI South Korea ETF'),
('INDA', '2012-02-02', 'MSCI India',                  'BlackRock', 'iShares MSCI India ETF'),
('KWEB', '2013-07-31', 'CSI Overseas China Internet', 'KraneShares','KraneShares CSI China Internet ETF'),

-- Industry/thematic ETFs
('GDX',  '2006-05-16', 'NYSE Arca Gold Miners',       'VanEck',    'VanEck Gold Miners ETF'),
('IBB',  '2001-02-05', 'Nasdaq Biotechnology',        'BlackRock', 'iShares Biotechnology ETF'),
('XBI',  '2006-01-31', 'S&P Biotech Select Industry', 'State Street','SPDR S&P Biotech ETF'),
('XOP',  '2006-06-19', 'S&P Oil & Gas E&P Select',    'State Street','SPDR S&P Oil & Gas Exploration & Production ETF'),
('OIH',  '2011-12-20', 'MVIS US Listed Oil Services', 'VanEck',    'VanEck Oil Services ETF'),
('ITA',  '2006-05-01', 'Dow Jones US Aerospace & Def','BlackRock', 'iShares U.S. Aerospace & Defense ETF'),
('KRE',  '2006-06-19', 'S&P Regional Banks Select',   'State Street','SPDR S&P Regional Banking ETF'),
('XHB',  '2006-01-31', 'S&P Homebuilders Select',     'State Street','SPDR S&P Homebuilders ETF'),
('XRT',  '2006-06-19', 'S&P Retail Select Industry',  'State Street','SPDR S&P Retail ETF'),
('AMLP', '2010-08-25', 'Alerian MLP Infrastructure',  'Alerian',   'Alerian MLP ETF — energy infrastructure MLPs'),
('CIBR', '2015-07-06', 'Nasdaq CTA Cybersecurity',    'First Trust','First Trust NASDAQ Cybersecurity ETF'),
('IGV',  '2001-07-10', 'S&P North American Software', 'BlackRock', 'iShares Expanded Tech-Software ETF'),
('SMH',  '2011-12-20', 'MVIS US Listed Semiconductor','VanEck',    'VanEck Semiconductor ETF'),
('VNQ',  '2004-09-23', 'MSCI US Investable Mkt RE 25/50','Vanguard','Vanguard Real Estate ETF'),
('IBIT', '2024-01-11', 'Bitcoin',                     'BlackRock', 'iShares Bitcoin Trust ETF — spot Bitcoin exposure'),

-- Factor ETFs
('MTUM', '2013-04-16', 'MSCI USA Momentum',           'BlackRock', 'iShares MSCI USA Momentum Factor ETF'),
('QUAL', '2013-07-16', 'MSCI USA Quality',            'BlackRock', 'iShares MSCI USA Quality Factor ETF'),
('USMV', '2011-10-18', 'MSCI USA Minimum Volatility', 'BlackRock', 'iShares MSCI USA Min Vol Factor ETF'),
('RSP',  '2003-04-24', 'S&P 500 Equal Weight',        'Invesco',   'Invesco S&P 500 Equal Weight ETF'),
('SCHD', '2011-10-20', 'Dow Jones US Dividend 100',   'Schwab',    'Schwab US Dividend Equity ETF'),
('VTV',  '2004-01-26', 'CRSP US Large Cap Value',     'Vanguard',  'Vanguard Value ETF'),
('VUG',  '2004-01-26', 'CRSP US Large Cap Growth',    'Vanguard',  'Vanguard Growth ETF'),

-- Commodity ETFs
('GLD',  '2004-11-18', 'Gold spot price',             'State Street','SPDR Gold Shares — physical gold backing'),
('SLV',  '2006-04-28', 'Silver spot price',           'BlackRock', 'iShares Silver Trust — physical silver backing'),
('ARKK', '2014-10-31', 'Active — ARK Innovation',     'ARK Invest','ARK Innovation ETF — actively managed disruptive innovation'),

-- FX — continuous markets, listing_date is approximate interbank standardisation
('EURUSD', '1999-01-01', 'EUR/USD spot',  NULL, 'Euro / US Dollar — most liquid FX pair'),
('USDJPY', '1971-08-15', 'USD/JPY spot',  NULL, 'US Dollar / Japanese Yen'),
('USDCHF', '1971-08-15', 'USD/CHF spot',  NULL, 'US Dollar / Swiss Franc')

ON CONFLICT (symbol) DO UPDATE SET
    listing_date     = EXCLUDED.listing_date,
    underlying_index = EXCLUDED.underlying_index,
    issuer           = EXCLUDED.issuer,
    description      = EXCLUDED.description,
    updated_at       = NOW();
