-- Migration 120: instrument tag vocabulary, annotations, and instrument expansion
--
-- Three tables:
--   tag_vocabulary       — controlled tag taxonomy (human-curated, FK-enforced)
--   instrument_tags      — symbol/tag assignments with weight, provenance, evidence
--   instrument_annotations — free-form narrative and AI-generated insights
--
-- Instruments without tags (futures, FX) simply have no rows — no NULLs.
-- AI agents write to instrument_annotations; human review promotes to formal tags.

-- ── Schema ────────────────────────────────────────────────────────────────────

CREATE TABLE tag_vocabulary (
    tag         text PRIMARY KEY,
    category    text NOT NULL CHECK (category IN ('exposure', 'regime', 'signal_role', 'macro_driver')),
    description text NOT NULL
);

CREATE TABLE instrument_tags (
    symbol      text        NOT NULL REFERENCES instruments(symbol) ON DELETE CASCADE,
    tag         text        NOT NULL REFERENCES tag_vocabulary(tag),
    weight      float       NOT NULL DEFAULT 1.0 CHECK (weight >= 0.0 AND weight <= 1.0),
    source      text        NOT NULL DEFAULT 'human' CHECK (source IN ('human', 'empirical', 'ai')),
    evidence    jsonb,
    assigned_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, tag)
);

CREATE TABLE instrument_annotations (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol          text        NOT NULL REFERENCES instruments(symbol) ON DELETE CASCADE,
    annotation_type text        NOT NULL CHECK (annotation_type IN ('thesis', 'signal_context', 'ai_insight', 'regime_note')),
    content         text        NOT NULL,
    source          text        NOT NULL CHECK (source IN ('human', 'ai')),
    model_id        text,
    confidence      float       CHECK (confidence >= 0.0 AND confidence <= 1.0),
    valid_from      timestamptz NOT NULL DEFAULT now(),
    valid_to        timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_instrument_tags_tag           ON instrument_tags(tag);
CREATE INDEX idx_instrument_tags_symbol        ON instrument_tags(symbol);
CREATE INDEX idx_instrument_tags_source        ON instrument_tags(source);
CREATE INDEX idx_instrument_annotations_symbol ON instrument_annotations(symbol);
CREATE INDEX idx_instrument_annotations_type   ON instrument_annotations(annotation_type);
CREATE INDEX idx_instrument_annotations_active ON instrument_annotations(symbol, annotation_type) WHERE valid_to IS NULL;

-- ── Tag vocabulary ─────────────────────────────────────────────────────────────

INSERT INTO tag_vocabulary (tag, category, description) VALUES

-- exposure
('eq_broad',          'exposure', 'Broad equity market index'),
('eq_sector',         'exposure', 'Single GICS sector equity basket'),
('eq_growth',         'exposure', 'Growth-tilted equity factor'),
('eq_value',          'exposure', 'Value-tilted equity factor'),
('eq_factor',         'exposure', 'Systematic factor tilt — momentum, quality, low-vol'),
('eq_small_cap',      'exposure', 'Small-cap equity market segment'),
('eq_sub_sector',     'exposure', 'Focused equity sub-sector within a GICS sector'),
('fi_treasury',       'exposure', 'US Treasury bonds'),
('fi_credit_ig',      'exposure', 'Investment grade corporate bonds'),
('fi_credit_hy',      'exposure', 'High yield corporate bonds'),
('fi_em',             'exposure', 'Emerging market debt'),
('fi_tips',           'exposure', 'Inflation-linked Treasury bonds'),
('fi_muni',           'exposure', 'Municipal bonds'),
('fi_preferred',      'exposure', 'Preferred stock — hybrid debt/equity capital'),
('fi_short_duration', 'exposure', 'Short-duration or cash-equivalent fixed income'),
('commodity_energy',  'exposure', 'Energy commodity — oil, gas, pipeline'),
('commodity_metals',  'exposure', 'Metals commodity — gold, silver, copper'),
('real_estate',       'exposure', 'Real estate investment trust basket'),
('crypto',            'exposure', 'Cryptocurrency spot or futures exposure'),
('intl_em',           'exposure', 'Emerging market equities, broad or single-country'),
('intl_developed',    'exposure', 'Developed market equities outside the US'),
('miners',            'exposure', 'Mining equities — precious or base metals'),
('dividend',          'exposure', 'High-dividend or income-oriented equity basket'),

-- regime
('rate_sensitive',    'regime', 'Price moves meaningfully with interest rate changes'),
('credit_risk',       'regime', 'Signals credit spread widening and tightening cycles'),
('inflation',         'regime', 'Proxy for inflation expectations or real rate shifts'),
('risk_on',           'regime', 'Outperforms in risk-on and expansion regimes'),
('risk_off',          'regime', 'Outperforms in risk-off, contraction, and flight-to-quality'),
('defensive',         'regime', 'Low-beta — attracts flows in late-cycle and drawdown environments'),
('growth',            'regime', 'Outperforms when growth factor dominates'),
('value',             'regime', 'Outperforms when value factor dominates'),
('momentum',          'regime', 'Outperforms when trend-following regime is active'),
('breadth',           'regime', 'Measures participation width across the market'),
('yield_curve',       'regime', 'Sensitive to yield curve shape — steepening or flattening'),
('volatility',        'regime', 'Tracks or proxies VIX and implied volatility term structure'),
('speculative',       'regime', 'Proxy for speculative or retail sentiment extremes'),

-- signal_role
('benchmark',         'signal_role', 'Reference instrument for an asset class or market segment'),
('sector_rotation',   'signal_role', 'Captures institutional sector allocation flows'),
('factor_rotation',   'signal_role', 'Captures systematic factor tilt shifts'),
('leading_indicator', 'signal_role', 'Historically leads the broader market at inflection points'),
('regime_classifier', 'signal_role', 'Used to classify the prevailing macro or market regime'),
('stress_indicator',  'signal_role', 'Signals financial stress or liquidity deterioration'),
('spread_leg',        'signal_role', 'One leg of a monitored spread or ratio pair'),
('sentiment',         'signal_role', 'Measures risk appetite or speculative positioning'),

-- macro_driver
('fed_policy',        'macro_driver', 'Driven by Fed funds rate expectations and FOMC decisions'),
('oil_price',         'macro_driver', 'Correlated to crude oil price direction'),
('dollar_strength',   'macro_driver', 'Inversely or directly correlated to USD index'),
('china_demand',      'macro_driver', 'Sensitive to Chinese economic activity and demand'),
('yen_carry',         'macro_driver', 'Influenced by JPY carry trade positioning'),
('semi_cycle',        'macro_driver', 'Tracks semiconductor inventory and capex cycle'),
('housing_cycle',     'macro_driver', 'Sensitive to housing starts, rates, and affordability'),
('credit_cycle',      'macro_driver', 'Tracks corporate credit expansion and contraction'),
('em_flows',          'macro_driver', 'Driven by institutional capital flows into and out of emerging markets');

-- ── Instrument removals ────────────────────────────────────────────────────────
-- USO: structurally broken (contango drag); CL futures are the direct signal
-- GDXJ: GDX sufficient for miners regime; junior miners add noise not signal
-- EWZ: single-country Brazil, idiosyncratic noise
-- FXI: China large-cap replaced by KWEB for cleaner signal
-- ITB: cap-weighted homebuilders replaced by XHB (equal-weight, more liquid)
-- VLUE: ~$500M AUM, thinly traded; value factor covered by VTV and sector positioning

DELETE FROM instruments WHERE symbol IN ('USO', 'GDXJ', 'EWZ', 'FXI', 'ITB', 'VLUE');

-- ── New instruments ────────────────────────────────────────────────────────────

INSERT INTO instruments (symbol, base, contract_details) VALUES
('AGG',  'AGG',  '{"name": "iShares Core US Aggregate Bond ETF",    "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('TIP',  'TIP',  '{"name": "iShares TIPS Bond ETF",                 "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('BIL',  'BIL',  '{"name": "SPDR Bloomberg 1-3 Month T-Bill ETF",   "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('MUB',  'MUB',  '{"name": "iShares National Muni Bond ETF",        "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('PFF',  'PFF',  '{"name": "iShares Preferred Stock ETF",           "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('XBI',  'XBI',  '{"name": "SPDR S&P Biotech ETF",                  "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('EWJ',  'EWJ',  '{"name": "iShares MSCI Japan ETF",                "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('EWT',  'EWT',  '{"name": "iShares MSCI Taiwan ETF",               "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('EWY',  'EWY',  '{"name": "iShares MSCI South Korea ETF",          "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('INDA', 'INDA', '{"name": "iShares MSCI India ETF",                "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('CIBR', 'CIBR', '{"name": "First Trust NASDAQ Cybersecurity ETF",  "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('IGV',  'IGV',  '{"name": "iShares Expanded Tech-Software ETF",    "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('ARKK', 'ARKK', '{"name": "ARK Innovation ETF",                    "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('OIH',  'OIH',  '{"name": "VanEck Oil Services ETF",               "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('AMLP', 'AMLP', '{"name": "Alerian MLP ETF",                       "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('XHB',  'XHB',  '{"name": "SPDR S&P Homebuilders ETF",             "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('XRT',  'XRT',  '{"name": "SPDR S&P Retail ETF",                   "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('KRE',  'KRE',  '{"name": "SPDR S&P Regional Banking ETF",         "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('ITA',  'ITA',  '{"name": "iShares U.S. Aerospace & Defense ETF",  "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('IBIT', 'IBIT', '{"name": "iShares Bitcoin Trust ETF",             "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('KWEB', 'KWEB', '{"name": "KraneShares CSI China Internet ETF",    "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('RSP',  'RSP',  '{"name": "Invesco S&P 500 Equal Weight ETF",      "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('VNQ',  'VNQ',  '{"name": "Vanguard Real Estate ETF",              "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('VUG',  'VUG',  '{"name": "Vanguard Growth ETF",                   "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('VTV',  'VTV',  '{"name": "Vanguard Value ETF",                    "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}'),
('SCHD', 'SCHD', '{"name": "Schwab US Dividend Equity ETF",         "asset_class": "equity", "exchange": "NYSE", "currency": "USD", "session_id": "equity_rth", "provider": "ibkr"}');

-- ── instrument_tags ────────────────────────────────────────────────────────────

INSERT INTO instrument_tags (symbol, tag, weight, source) VALUES
-- Broad market
('SPY', 'eq_broad', 1.0, 'human'), ('SPY', 'benchmark', 1.0, 'human'), ('SPY', 'regime_classifier', 1.0, 'human'), ('SPY', 'spread_leg', 1.0, 'human'),
('QQQ', 'eq_broad', 1.0, 'human'), ('QQQ', 'eq_growth', 0.9, 'human'), ('QQQ', 'benchmark', 1.0, 'human'), ('QQQ', 'risk_on', 0.8, 'human'), ('QQQ', 'growth', 0.9, 'human'),
('IWM', 'eq_broad', 1.0, 'human'), ('IWM', 'eq_small_cap', 1.0, 'human'), ('IWM', 'benchmark', 1.0, 'human'), ('IWM', 'risk_on', 0.8, 'human'), ('IWM', 'leading_indicator', 0.8, 'human'), ('IWM', 'credit_cycle', 0.7, 'human'),
('DIA', 'eq_broad', 1.0, 'human'), ('DIA', 'benchmark', 1.0, 'human'),
-- Sector SPDRs
('XLK', 'eq_sector', 1.0, 'human'), ('XLK', 'sector_rotation', 1.0, 'human'), ('XLK', 'growth', 0.8, 'human'), ('XLK', 'rate_sensitive', 0.7, 'human'),
('XLF', 'eq_sector', 1.0, 'human'), ('XLF', 'sector_rotation', 1.0, 'human'), ('XLF', 'yield_curve', 0.8, 'human'), ('XLF', 'credit_cycle', 0.8, 'human'),
('XLV', 'eq_sector', 1.0, 'human'), ('XLV', 'sector_rotation', 1.0, 'human'), ('XLV', 'defensive', 0.8, 'human'),
('XLY', 'eq_sector', 1.0, 'human'), ('XLY', 'sector_rotation', 1.0, 'human'), ('XLY', 'risk_on', 0.8, 'human'), ('XLY', 'credit_cycle', 0.7, 'human'),
('XLE', 'eq_sector', 1.0, 'human'), ('XLE', 'sector_rotation', 1.0, 'human'), ('XLE', 'oil_price', 0.8, 'human'), ('XLE', 'dollar_strength', 0.6, 'human'),
('XLI', 'eq_sector', 1.0, 'human'), ('XLI', 'sector_rotation', 1.0, 'human'), ('XLI', 'leading_indicator', 0.7, 'human'),
('XLB', 'eq_sector', 1.0, 'human'), ('XLB', 'sector_rotation', 1.0, 'human'), ('XLB', 'china_demand', 0.7, 'human'), ('XLB', 'dollar_strength', 0.7, 'human'),
('XLC', 'eq_sector', 1.0, 'human'), ('XLC', 'sector_rotation', 1.0, 'human'), ('XLC', 'growth', 0.7, 'human'),
('XLP', 'eq_sector', 1.0, 'human'), ('XLP', 'sector_rotation', 1.0, 'human'), ('XLP', 'defensive', 0.9, 'human'), ('XLP', 'value', 0.6, 'human'),
('XLRE', 'eq_sector', 1.0, 'human'), ('XLRE', 'sector_rotation', 1.0, 'human'), ('XLRE', 'rate_sensitive', 0.9, 'human'), ('XLRE', 'real_estate', 1.0, 'human'),
('XLU', 'eq_sector', 1.0, 'human'), ('XLU', 'sector_rotation', 1.0, 'human'), ('XLU', 'defensive', 0.9, 'human'), ('XLU', 'rate_sensitive', 0.9, 'human'), ('XLU', 'fed_policy', 0.8, 'human'),
-- Fixed income (existing)
('TLT', 'fi_treasury', 1.0, 'human'), ('TLT', 'benchmark', 1.0, 'human'), ('TLT', 'rate_sensitive', 1.0, 'human'), ('TLT', 'risk_off', 0.9, 'human'), ('TLT', 'spread_leg', 1.0, 'human'), ('TLT', 'fed_policy', 1.0, 'human'),
('IEF', 'fi_treasury', 1.0, 'human'), ('IEF', 'rate_sensitive', 0.9, 'human'), ('IEF', 'yield_curve', 0.9, 'human'), ('IEF', 'spread_leg', 1.0, 'human'), ('IEF', 'fed_policy', 0.8, 'human'),
('SHY', 'fi_treasury', 1.0, 'human'), ('SHY', 'fi_short_duration', 1.0, 'human'), ('SHY', 'rate_sensitive', 0.7, 'human'), ('SHY', 'risk_off', 0.8, 'human'), ('SHY', 'fed_policy', 0.9, 'human'),
('HYG', 'fi_credit_hy', 1.0, 'human'), ('HYG', 'benchmark', 1.0, 'human'), ('HYG', 'credit_risk', 1.0, 'human'), ('HYG', 'risk_on', 0.7, 'human'), ('HYG', 'stress_indicator', 0.9, 'human'), ('HYG', 'spread_leg', 1.0, 'human'), ('HYG', 'credit_cycle', 0.9, 'human'),
('LQD', 'fi_credit_ig', 1.0, 'human'), ('LQD', 'benchmark', 1.0, 'human'), ('LQD', 'credit_risk', 0.8, 'human'), ('LQD', 'spread_leg', 1.0, 'human'), ('LQD', 'credit_cycle', 0.8, 'human'),
('EMB', 'fi_em', 1.0, 'human'), ('EMB', 'credit_risk', 0.8, 'human'), ('EMB', 'em_flows', 0.9, 'human'), ('EMB', 'dollar_strength', 0.8, 'human'),
-- Metals / miners
('GLD', 'commodity_metals', 1.0, 'human'), ('GLD', 'benchmark', 1.0, 'human'), ('GLD', 'inflation', 0.8, 'human'), ('GLD', 'risk_off', 0.8, 'human'), ('GLD', 'dollar_strength', 0.9, 'human'),
('SLV', 'commodity_metals', 1.0, 'human'), ('SLV', 'inflation', 0.7, 'human'), ('SLV', 'spread_leg', 1.0, 'human'), ('SLV', 'china_demand', 0.6, 'human'),
('GDX', 'miners', 1.0, 'human'), ('GDX', 'benchmark', 1.0, 'human'), ('GDX', 'leading_indicator', 0.7, 'human'), ('GDX', 'dollar_strength', 0.8, 'human'),
-- International (existing)
('EEM', 'intl_em', 1.0, 'human'), ('EEM', 'benchmark', 1.0, 'human'), ('EEM', 'em_flows', 1.0, 'human'), ('EEM', 'regime_classifier', 0.8, 'human'), ('EEM', 'dollar_strength', 0.8, 'human'), ('EEM', 'china_demand', 0.7, 'human'),
('EFA', 'intl_developed', 1.0, 'human'), ('EFA', 'benchmark', 1.0, 'human'), ('EFA', 'dollar_strength', 0.8, 'human'),
-- Factor
('MTUM', 'eq_factor', 1.0, 'human'), ('MTUM', 'factor_rotation', 1.0, 'human'), ('MTUM', 'momentum', 1.0, 'human'),
('QUAL', 'eq_factor', 1.0, 'human'), ('QUAL', 'factor_rotation', 1.0, 'human'), ('QUAL', 'defensive', 0.7, 'human'),
('USMV', 'eq_factor', 1.0, 'human'), ('USMV', 'factor_rotation', 1.0, 'human'), ('USMV', 'defensive', 0.9, 'human'), ('USMV', 'risk_off', 0.8, 'human'),
-- Sub-sector (existing)
('SMH', 'eq_sub_sector', 1.0, 'human'), ('SMH', 'benchmark', 1.0, 'human'), ('SMH', 'leading_indicator', 0.8, 'human'), ('SMH', 'semi_cycle', 1.0, 'human'), ('SMH', 'china_demand', 0.7, 'human'),
('IBB', 'eq_sub_sector', 1.0, 'human'), ('IBB', 'benchmark', 1.0, 'human'), ('IBB', 'risk_on', 0.7, 'human'),
('XOP', 'eq_sub_sector', 1.0, 'human'), ('XOP', 'oil_price', 1.0, 'human'), ('XOP', 'spread_leg', 0.9, 'human'),
-- New fixed income
('AGG', 'fi_treasury', 0.5, 'human'), ('AGG', 'fi_credit_ig', 0.4, 'human'), ('AGG', 'benchmark', 1.0, 'human'), ('AGG', 'rate_sensitive', 0.9, 'human'), ('AGG', 'spread_leg', 1.0, 'human'), ('AGG', 'regime_classifier', 0.8, 'human'),
('TIP', 'fi_tips', 1.0, 'human'), ('TIP', 'benchmark', 1.0, 'human'), ('TIP', 'inflation', 1.0, 'human'), ('TIP', 'rate_sensitive', 0.8, 'human'), ('TIP', 'spread_leg', 1.0, 'human'), ('TIP', 'fed_policy', 0.7, 'human'),
('BIL', 'fi_short_duration', 1.0, 'human'), ('BIL', 'fi_treasury', 1.0, 'human'), ('BIL', 'risk_off', 1.0, 'human'), ('BIL', 'regime_classifier', 0.9, 'human'), ('BIL', 'fed_policy', 1.0, 'human'),
('MUB', 'fi_muni', 1.0, 'human'), ('MUB', 'benchmark', 1.0, 'human'), ('MUB', 'rate_sensitive', 0.8, 'human'), ('MUB', 'stress_indicator', 0.7, 'human'), ('MUB', 'credit_risk', 0.6, 'human'),
('PFF', 'fi_preferred', 1.0, 'human'), ('PFF', 'rate_sensitive', 0.9, 'human'), ('PFF', 'stress_indicator', 0.8, 'human'), ('PFF', 'yield_curve', 0.7, 'human'), ('PFF', 'credit_cycle', 0.7, 'human'),
-- New biotech / international
('XBI', 'eq_sub_sector', 1.0, 'human'), ('XBI', 'benchmark', 1.0, 'human'), ('XBI', 'risk_on', 0.8, 'human'), ('XBI', 'speculative', 0.7, 'human'), ('XBI', 'sentiment', 0.8, 'human'),
('EWJ', 'intl_developed', 1.0, 'human'), ('EWJ', 'benchmark', 1.0, 'human'), ('EWJ', 'yen_carry', 0.9, 'human'), ('EWJ', 'dollar_strength', 0.7, 'human'), ('EWJ', 'regime_classifier', 0.7, 'human'),
('EWT', 'intl_developed', 1.0, 'human'), ('EWT', 'semi_cycle', 0.9, 'human'), ('EWT', 'china_demand', 0.8, 'human'), ('EWT', 'dollar_strength', 0.6, 'human'), ('EWT', 'leading_indicator', 0.7, 'human'),
('EWY', 'intl_developed', 1.0, 'human'), ('EWY', 'semi_cycle', 0.8, 'human'), ('EWY', 'china_demand', 0.8, 'human'), ('EWY', 'em_flows', 0.6, 'human'), ('EWY', 'spread_leg', 0.8, 'human'),
('INDA', 'intl_em', 1.0, 'human'), ('INDA', 'benchmark', 1.0, 'human'), ('INDA', 'em_flows', 0.9, 'human'), ('INDA', 'regime_classifier', 0.7, 'human'),
-- New tech sub-sectors
('CIBR', 'eq_sub_sector', 1.0, 'human'), ('CIBR', 'growth', 0.7, 'human'), ('CIBR', 'sentiment', 0.7, 'human'),
('IGV', 'eq_sub_sector', 1.0, 'human'), ('IGV', 'benchmark', 1.0, 'human'), ('IGV', 'growth', 0.8, 'human'), ('IGV', 'rate_sensitive', 0.8, 'human'), ('IGV', 'regime_classifier', 0.7, 'human'),
('ARKK', 'eq_sub_sector', 1.0, 'human'), ('ARKK', 'risk_on', 0.9, 'human'), ('ARKK', 'speculative', 1.0, 'human'), ('ARKK', 'sentiment', 1.0, 'human'), ('ARKK', 'growth', 0.8, 'human'), ('ARKK', 'regime_classifier', 0.8, 'human'),
-- New energy
('OIH', 'eq_sub_sector', 1.0, 'human'), ('OIH', 'oil_price', 0.9, 'human'), ('OIH', 'spread_leg', 0.9, 'human'), ('OIH', 'leading_indicator', 0.7, 'human'),
('AMLP', 'commodity_energy', 1.0, 'human'), ('AMLP', 'benchmark', 1.0, 'human'), ('AMLP', 'rate_sensitive', 0.7, 'human'), ('AMLP', 'dividend', 0.8, 'human'), ('AMLP', 'oil_price', 0.5, 'human'),
-- New consumer / housing
('XHB', 'eq_sub_sector', 1.0, 'human'), ('XHB', 'benchmark', 1.0, 'human'), ('XHB', 'housing_cycle', 1.0, 'human'), ('XHB', 'rate_sensitive', 0.8, 'human'), ('XHB', 'leading_indicator', 0.8, 'human'), ('XHB', 'credit_cycle', 0.7, 'human'),
('XRT', 'eq_sub_sector', 1.0, 'human'), ('XRT', 'benchmark', 1.0, 'human'), ('XRT', 'risk_on', 0.7, 'human'), ('XRT', 'leading_indicator', 0.7, 'human'), ('XRT', 'credit_cycle', 0.7, 'human'),
-- New banking / defense / crypto / China
('KRE', 'eq_sub_sector', 1.0, 'human'), ('KRE', 'benchmark', 1.0, 'human'), ('KRE', 'stress_indicator', 0.9, 'human'), ('KRE', 'yield_curve', 0.9, 'human'), ('KRE', 'credit_risk', 0.8, 'human'), ('KRE', 'spread_leg', 0.9, 'human'),
('ITA', 'eq_sub_sector', 1.0, 'human'), ('ITA', 'benchmark', 1.0, 'human'), ('ITA', 'sentiment', 0.8, 'human'),
('IBIT', 'crypto', 1.0, 'human'), ('IBIT', 'benchmark', 1.0, 'human'), ('IBIT', 'risk_on', 0.9, 'human'), ('IBIT', 'speculative', 0.9, 'human'), ('IBIT', 'sentiment', 0.9, 'human'), ('IBIT', 'regime_classifier', 0.7, 'human'),
('KWEB', 'intl_em', 1.0, 'human'), ('KWEB', 'benchmark', 1.0, 'human'), ('KWEB', 'china_demand', 1.0, 'human'), ('KWEB', 'regime_classifier', 0.8, 'human'), ('KWEB', 'sentiment', 0.7, 'human'),
-- Breadth / real estate
('RSP', 'eq_broad', 1.0, 'human'), ('RSP', 'benchmark', 1.0, 'human'), ('RSP', 'breadth', 1.0, 'human'), ('RSP', 'regime_classifier', 1.0, 'human'), ('RSP', 'spread_leg', 1.0, 'human'),
('VNQ', 'real_estate', 1.0, 'human'), ('VNQ', 'benchmark', 1.0, 'human'), ('VNQ', 'rate_sensitive', 0.9, 'human'), ('VNQ', 'fed_policy', 0.8, 'human'), ('VNQ', 'spread_leg', 0.9, 'human'),
-- Growth / value pair
('VUG', 'eq_growth', 1.0, 'human'), ('VUG', 'benchmark', 1.0, 'human'), ('VUG', 'growth', 1.0, 'human'), ('VUG', 'factor_rotation', 1.0, 'human'), ('VUG', 'spread_leg', 1.0, 'human'), ('VUG', 'regime_classifier', 0.9, 'human'),
('VTV', 'eq_value', 1.0, 'human'), ('VTV', 'benchmark', 1.0, 'human'), ('VTV', 'value', 1.0, 'human'), ('VTV', 'factor_rotation', 1.0, 'human'), ('VTV', 'spread_leg', 1.0, 'human'), ('VTV', 'regime_classifier', 0.9, 'human'), ('VTV', 'defensive', 0.6, 'human'),
-- Dividend
('SCHD', 'dividend', 1.0, 'human'), ('SCHD', 'benchmark', 1.0, 'human'), ('SCHD', 'eq_value', 0.8, 'human'), ('SCHD', 'value', 0.8, 'human'), ('SCHD', 'defensive', 0.7, 'human'), ('SCHD', 'regime_classifier', 0.8, 'human'), ('SCHD', 'spread_leg', 0.9, 'human');

-- ── instrument_annotations (thesis, source=human) ─────────────────────────────

INSERT INTO instrument_annotations (symbol, annotation_type, source, content) VALUES
('SPY',  'thesis', 'human', 'S&P 500 benchmark with the deepest options market in equities. Every institutional flow touches this. The reference for broad equity regime classification and the primary spread leg for ratio analysis.'),
('QQQ',  'thesis', 'human', 'Nasdaq-100 proxy for tech and growth sentiment. Mega-cap tech concentration makes it the cleanest risk-on/off signal in equities. Leads SPY during both rallies and selloffs.'),
('IWM',  'thesis', 'human', 'Russell 2000 small-cap benchmark. Domestically revenue-exposed and credit-dependent — IWM leads at cycle turns. Weakness here while SPY holds is a classic divergence warning.'),
('DIA',  'thesis', 'human', 'DJIA price-weighted benchmark. Industrial and financial heavy, slower-moving than SPY. Useful as a confirmation signal rather than a leading one.'),
('XLK',  'thesis', 'human', 'Tech sector blending software, hardware, and semiconductors. Rate-sensitive growth — contracts when real yields rise. The largest and most institutionally traded sector ETF.'),
('XLF',  'thesis', 'human', 'Broad financials. Earnings leverage to the yield curve — steepening benefits banks. Tracks credit expansion and contraction cycles. Watch XLF vs KRE divergence for regional bank stress.'),
('XLV',  'thesis', 'human', 'Healthcare sector. Defensive rotation target in late-cycle environments. M&A activity and drug pricing policy create event-driven moves independent of the macro cycle.'),
('XLY',  'thesis', 'human', 'Consumer discretionary. Amazon-heavy so part e-commerce proxy. Credit-dependent spending makes this a credit cycle barometer. Leads in early recovery, lags in tightening.'),
('XLE',  'thesis', 'human', 'Integrated oil majors. Lags spot crude but gives a smoother energy regime signal. Distinct from XOP (E&P leverage) and OIH (services). The institutional energy allocation vehicle.'),
('XLI',  'thesis', 'human', 'Industrials sector. Capex cycle and PMI proxy. Infrastructure spend and reshoring beneficiary. Often leads the broader market at economic inflection points.'),
('XLB',  'thesis', 'human', 'Materials sector. Commodity input prices and China demand sensitivity. Dollar strength compresses margins. Early-cycle outperformer when global growth accelerates.'),
('XLC',  'thesis', 'human', 'Communication services — Meta, Google, Netflix. Ad spend cycle and streaming subscriber growth. Hybrid of growth tech and defensive media characteristics.'),
('XLP',  'thesis', 'human', 'Consumer staples. The textbook defensive rotation destination. Inflation pass-through capability and consumer stress signal. Outperforms when the market prices recession.'),
('XLRE', 'thesis', 'human', 'Real estate sector REIT basket. Rate-sensitive — cap rate expansion compresses valuations when yields rise. Tracks institutional REIT allocation flows.'),
('XLU',  'thesis', 'human', 'Utilities sector. The cleanest rate-sensitivity signal in equities — treated as a bond proxy. Fed policy sensitivity is high. Defensive inflows precede broad risk-off moves.'),
('TLT',  'thesis', 'human', '20+ year treasury — the duration benchmark. The dominant instrument for expressing rate regime views. Deep options market makes it the institutional rate hedge vehicle and primary spread leg against equities.'),
('IEF',  'thesis', 'human', '7-10 year treasury. Intermediate duration gives cleaner yield curve mid-point signal than TLT. TLT vs IEF spread captures the long-end term premium.'),
('SHY',  'thesis', 'human', '1-3 year treasury anchored to Fed funds expectations. The short end of the curve. SHY vs TLT spread is the yield curve steepness signal.'),
('HYG',  'thesis', 'human', 'High yield corporate bond benchmark with a deep options market. Credit spread widening here leads equity drawdowns — HYG is the earliest stress signal in the credit complex. The HYG/LQD spread is a fundamental risk-on/off ratio.'),
('LQD',  'thesis', 'human', 'Investment grade corporate bond benchmark. LQD spread over treasuries signals credit quality cycle. Paired with HYG as the quality reference leg.'),
('EMB',  'thesis', 'human', 'EM USD-denominated sovereign debt. Captures EM credit conditions separately from EM equity flows. Dollar strength and carry regime drive performance independently of EEM.'),
('GLD',  'thesis', 'human', 'Gold benchmark with the largest metals options market. Real rate inverse — rallies when real yields fall. Safe haven and inflation hedge. Dollar strength suppresses; dollar weakness amplifies.'),
('SLV',  'thesis', 'human', 'Silver has an industrial demand component that gold lacks — divergence from GLD signals the industrial cycle. The GLD/SLV ratio (gold-silver ratio) is a classic risk regime indicator.'),
('GDX',  'thesis', 'human', 'Senior gold miners benchmark. Operating leverage to gold price amplifies moves — GDX leads gold on the way up and falls harder on the way down. A leading indicator for the gold regime.'),
('EEM',  'thesis', 'human', 'Emerging markets benchmark with the deepest EM options market. Institutional hedging flows make this the primary EM regime signal. Dollar strength is the dominant driver. China demand and Fed policy are secondary.'),
('EFA',  'thesis', 'human', 'Developed markets ex-US benchmark covering Europe, Japan, and Australia. Dollar strength suppresses returns for US-based holders. Tracks the global growth divergence between US and rest-of-developed.'),
('MTUM', 'thesis', 'human', 'Momentum factor ETF. Outperforms when trend-following regimes are active and mean-reversion is suppressed. Factor rotation signal — flows here indicate institutional quantitative positioning.'),
('QUAL', 'thesis', 'human', 'Quality factor — high ROE, low debt, stable earnings. Defensive factor rotation that outperforms in late-cycle and slowdown environments without the full defensiveness of staples or utilities.'),
('USMV', 'thesis', 'human', 'Minimum volatility factor. Institutional risk-off rotation into low-beta equities. Inflows here precede broader defensive positioning and often lead XLP and XLU.'),
('SMH',  'thesis', 'human', 'Semiconductor benchmark dominated by NVDA and TSMC. The chip cycle leading indicator — semiconductor capex and inventory cycles precede broader tech moves by 1-2 quarters. AI infrastructure capex proxy.'),
('IBB',  'thesis', 'human', 'Cap-weighted biotech. Large-cap concentration means a few FDA decisions move the whole ETF. Biotech risk-on signal — outperforms in early-cycle and speculative regimes. Pair with XBI for equal-weight divergence.'),
('XOP',  'thesis', 'human', 'Oil and gas E&P — highest beta to crude price among energy ETFs. Pure upstream producers with no refining buffer. XOP vs XLE divergence signals whether the energy move is oil-driven or rotation-driven.'),
('AGG',  'thesis', 'human', 'The institutional bond market benchmark at $100B+. Every fixed income portfolio is measured against this. AGG vs TLT divergence isolates credit from duration. AGG breakdowns precede equity stress by weeks.'),
('TIP',  'thesis', 'human', 'Inflation-linked treasury benchmark. The TIP/TLT ratio is the market''s real-time inflation expectation signal — rising ratio means the market is pricing inflation, not just rates. Critical for regime classification.'),
('BIL',  'thesis', 'human', 'T-bill cash equivalent at $30B+. When BIL inflows accelerate, capital is leaving all risk assets simultaneously. The zero-duration risk-off anchor. BIL yield tracks Fed funds in real time.'),
('MUB',  'thesis', 'human', 'Municipal bond benchmark at $40B. State and local fiscal health signal — muni spreads widen before federal credit stress appears in HYG. Tax policy sensitivity makes it a unique rate instrument.'),
('PFF',  'thesis', 'human', 'Preferred stock at $14B — banks are the primary issuers. PFF stress precedes XLF stress because preferred holders get hit before equity. Rate-sensitive with perpetual duration characteristics distinct from all treasury and corporate bond ETFs.'),
('XBI',  'thesis', 'human', 'Equal-weight biotech — completely different signal from cap-weighted IBB. Equal weighting surfaces the small-cap biotech cycle that IBB buries. Massive options market makes it an institutional risk tool. XBI/IBB divergence signals whether biotech moves are broad or concentrated.'),
('EWJ',  'thesis', 'human', 'Japan at $10B+. The primary vehicle for expressing BoJ policy and yen carry trade views. When the yen carry unwinds, EWJ sells off sharply. Japan''s export economy makes it a global growth and dollar proxy independent of US equity flows.'),
('EWT',  'thesis', 'human', 'Taiwan at $7B — TSMC-heavy, making this the supply-side semiconductor signal. EWT vs EWY (Korea = demand side) divergence reveals semiconductor inventory cycle direction. Taiwan geopolitical premium is a separate embedded signal.'),
('EWY',  'thesis', 'human', 'South Korea at $5B — Samsung and SK Hynix make this the demand-side semiconductor signal. EWY leads when memory demand is accelerating. China demand sensitivity is high through Korean exports. The Korea/Taiwan pair reveals chip cycle direction before US semi stocks move.'),
('INDA', 'thesis', 'human', 'India at $10B+ — the largest EM reallocation story of the decade. Institutional managers are rotating from China to India at scale; INDA captures this flow directly. Structurally different from EEM — domestic consumption driven, not export/China-dependent.'),
('CIBR', 'thesis', 'human', 'Cybersecurity at $8B. Defense spending on cyber has become a structural growth category independent of the macro cycle. CIBR outperforms when geopolitical risk rises and underperforms in deep risk-off when all growth sells.'),
('IGV',  'thesis', 'human', 'Software and SaaS benchmark at $7B. Software multiples are the most rate-sensitive in tech — IGV contracts sharply when real yields rise and expands fast when they fall. Distinct from SMH (hardware/chips) and QQQ (blended). IGV vs SMH divergence signals whether the tech move is software or silicon driven.'),
('ARKK', 'thesis', 'human', 'ARK Innovation at $7B — the institutional speculative sentiment barometer. ARKK is not a fundamental investment; it is a regime indicator. ARKK leading = speculative risk-on. ARKK lagging = growth rotation is selective, not broad. The ARKK/QQQ ratio is one of the cleanest sentiment signals available.'),
('OIH',  'thesis', 'human', 'Oil services at $3B — the third distinct energy signal after XLE (integrated majors) and XOP (E&P producers). Services companies benefit from drilling activity, not just oil prices. OIH leads when energy capex is accelerating. OIH vs XLE divergence reveals whether oil strength is price or activity driven.'),
('AMLP', 'thesis', 'human', 'Midstream pipeline infrastructure at $10B+. AMLP returns are infrastructure and contract-driven, not crude-price-driven — it is the energy income signal, not the oil price signal. Rate-sensitive due to high yield characteristics. Outperforms when energy is constructive but oil is range-bound.'),
('XHB',  'thesis', 'human', 'Equal-weight homebuilders at $3B — the housing cycle leading indicator. XHB leads economic turns because housing starts lead GDP. Rate-sensitive: mortgage rate spikes hit XHB immediately. The XHB trend is one of the earliest signals of credit tightening impact on the real economy.'),
('XRT',  'thesis', 'human', 'Equal-weight retail at $5B — unlike cap-weighted XLY, XRT gives full weight to small and mid-cap retailers, capturing the consumer stress that Amazon masks. XRT weakness while XLY holds signals that only mega-cap consumer is working.'),
('KRE',  'thesis', 'human', 'Regional banking at $3B+ — the banking stress signal that XLF obscures. Regional banks have concentrated deposit bases and commercial real estate exposure that large-cap banks hedge away. KRE stress precedes XLF stress. The KRE/XLF spread is a systemic risk early warning.'),
('ITA',  'thesis', 'human', 'Aerospace and defense at $6B. Defense budgets are countercyclical to the economic cycle — ITA outperforms during geopolitical escalation regardless of equity regime. A structurally growing allocation category as NATO spending increases.'),
('IBIT', 'thesis', 'human', 'Bitcoin spot ETF at $60B+ — the institutional crypto on-ramp. IBIT is now large enough that its flows reflect genuine institutional positioning, not just retail speculation. Bitcoin risk-on/off signal: IBIT leads QQQ on the way up in speculative regimes and sells off harder on the way down.'),
('KWEB', 'thesis', 'human', 'China internet at $5B+ — the cleanest China tech regime signal. KWEB captures Alibaba, Tencent, and JD specifically, where regulatory and geopolitical risk is concentrated. More signal-dense than broad China ETFs for expressing China tech sentiment.'),
('RSP',  'thesis', 'human', 'Equal-weight S&P 500 at $60B — the market breadth benchmark. SPY vs RSP divergence is one of the most reliable market health signals: when SPY rallies but RSP lags, a small number of mega-caps are masking broad weakness. RSP leading means the rally has participation. This spread should be monitored continuously.'),
('VNQ',  'thesis', 'human', 'Vanguard Real Estate at $30B — the REIT benchmark with a deep options market, far larger than XLRE. Tracks institutional REIT allocation flows and cap rate expectations. VNQ vs TLT correlation is the real estate / duration relationship signal.'),
('VUG',  'thesis', 'human', 'Vanguard Growth at $130B — pure large-cap growth factor, one of the largest ETFs in existence. QQQ is tech-concentrated; VUG is the clean growth factor across all sectors. VUG vs VTV is the canonical growth/value regime spread that Simons-style quants use to classify the prevailing factor regime.'),
('VTV',  'thesis', 'human', 'Vanguard Value at $130B — the pure large-cap value factor pair to VUG. Outperforms in rising rate, late-cycle, and inflation regimes. The VUG/VTV spread is the single most important factor regime classifier in the US equity market.'),
('SCHD', 'thesis', 'human', 'Schwab US Dividend Equity at $60B — one of the most-held ETFs in the US. SCHD vs QQQ is the income/growth regime signal: when SCHD leads, the market is in a yield and quality regime. When QQQ leads, growth dominates. Massive retail following means flows here reflect genuine retail positioning shifts.');
