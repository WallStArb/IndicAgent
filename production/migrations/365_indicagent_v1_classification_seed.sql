-- Migration: indicagent_v1 classification seed (Phase 182, todo 384). GENERATED FILE, DO NOT EDIT.
--
-- Rendered from src/config/classification_seed_data.py by src/config/classification_seed.py.
-- Regenerate: .venv/bin/python -m src.config.classification_seed --write <this file>
-- Verify:     .venv/bin/python -m src.config.classification_seed --check <this file>
--
-- D-01: node parent_code/level are immutable per code; the seed aborts on disagreement and
--       only node names update in place. instrument_classification is append-only.
-- D-07: valid_from is the apply date (the build date); no history before it.
-- D-09: the seed aborts if any active instrument lacks a current indicagent_v1 assignment.
-- D-11: numbered migration, applied and committed together.
-- This scheme is project-owned and is not GICS (D-03).

BEGIN;

INSERT INTO classification_scheme (scheme, name, authority, source_ref)
VALUES ('indicagent_v1', 'IndicAgent security classification v1', 'IndicAgent', 'phase_182_build')
ON CONFLICT (scheme) DO NOTHING;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM classification_scheme
        WHERE scheme = 'indicagent_v1' AND authority IS DISTINCT FROM 'IndicAgent'
    ) THEN
        RAISE EXCEPTION 'classification_scheme indicagent_v1 exists with a different authority';
    END IF;
END $$;

-- Node staging and immutability guard (D-01): parent_code and level never change for a code.
CREATE TEMP TABLE _seed_classification_node (
    code        TEXT PRIMARY KEY,
    parent_code TEXT,
    level       SMALLINT NOT NULL,
    name        TEXT NOT NULL
) ON COMMIT DROP;

INSERT INTO _seed_classification_node (code, parent_code, level, name) VALUES
    ('CCY', NULL, 1, 'Currency'),
    ('CMD', NULL, 1, 'Commodity'),
    ('CRY', NULL, 1, 'Crypto'),
    ('EQ', NULL, 1, 'Equity'),
    ('FI', NULL, 1, 'Fixed income'),
    ('MA', NULL, 1, 'Multi-asset'),
    ('VOL', NULL, 1, 'Volatility'),
    ('CCY.DM', 'CCY', 2, 'Developed-market currencies'),
    ('CCY.USD', 'CCY', 2, 'US dollar'),
    ('CMD.AG', 'CMD', 2, 'Agriculture'),
    ('CMD.BROAD', 'CMD', 2, 'Broad commodities'),
    ('CMD.ENERGY', 'CMD', 2, 'Energy'),
    ('CMD.INDMET', 'CMD', 2, 'Industrial metals'),
    ('CMD.PREC', 'CMD', 2, 'Precious metals'),
    ('CRY.BTC', 'CRY', 2, 'Bitcoin'),
    ('CRY.ETH', 'CRY', 2, 'Ether'),
    ('EQ.BROAD', 'EQ', 2, 'Broad market (multi-sector)'),
    ('EQ.CD', 'EQ', 2, 'Consumer Discretionary'),
    ('EQ.COM', 'EQ', 2, 'Communication Services'),
    ('EQ.CS', 'EQ', 2, 'Consumer Staples'),
    ('EQ.EN', 'EQ', 2, 'Energy'),
    ('EQ.FIN', 'EQ', 2, 'Financials'),
    ('EQ.HC', 'EQ', 2, 'Health Care'),
    ('EQ.IND', 'EQ', 2, 'Industrials'),
    ('EQ.IT', 'EQ', 2, 'Information Technology'),
    ('EQ.MAT', 'EQ', 2, 'Materials'),
    ('EQ.RE', 'EQ', 2, 'Real Estate'),
    ('EQ.UTL', 'EQ', 2, 'Utilities'),
    ('FI.BROAD', 'FI', 2, 'Broad and aggregate bonds'),
    ('FI.CONV', 'FI', 2, 'Convertible securities'),
    ('FI.CREDIT', 'FI', 2, 'Corporate credit'),
    ('FI.EM', 'FI', 2, 'Emerging-market debt'),
    ('FI.INFL', 'FI', 2, 'Inflation-linked'),
    ('FI.MUNI', 'FI', 2, 'Municipal'),
    ('FI.PREF', 'FI', 2, 'Preferred securities'),
    ('FI.RATES', 'FI', 2, 'Government rates'),
    ('MA.ALT', 'MA', 2, 'Alternatives, market-neutral and managed strategies'),
    ('VOL.EQUITY', 'VOL', 2, 'Equity index volatility'),
    ('EQ.CD.AUTO', 'EQ.CD', 3, 'Automobiles & Components'),
    ('EQ.CD.DURABLES', 'EQ.CD', 3, 'Consumer Durables & Apparel'),
    ('EQ.CD.RETAIL', 'EQ.CD', 3, 'Consumer Discretionary Distribution & Retail'),
    ('EQ.CD.SERVICES', 'EQ.CD', 3, 'Consumer Services'),
    ('EQ.COM.MEDIA', 'EQ.COM', 3, 'Media & Entertainment'),
    ('EQ.COM.TELECOM', 'EQ.COM', 3, 'Telecommunication Services'),
    ('EQ.CS.FOOD', 'EQ.CS', 3, 'Food, Beverage & Tobacco'),
    ('EQ.CS.HOUSEHOLD', 'EQ.CS', 3, 'Household & Personal Products'),
    ('EQ.CS.RETAIL', 'EQ.CS', 3, 'Consumer Staples Distribution & Retail'),
    ('EQ.EN.ENERGY', 'EQ.EN', 3, 'Energy'),
    ('EQ.FIN.BANKS', 'EQ.FIN', 3, 'Banks'),
    ('EQ.FIN.FINSVC', 'EQ.FIN', 3, 'Financial Services'),
    ('EQ.FIN.INSURANCE', 'EQ.FIN', 3, 'Insurance'),
    ('EQ.HC.EQUIPSVC', 'EQ.HC', 3, 'Health Care Equipment & Services'),
    ('EQ.HC.PHARMA', 'EQ.HC', 3, 'Pharmaceuticals, Biotechnology & Life Sciences'),
    ('EQ.IND.CAPGOODS', 'EQ.IND', 3, 'Capital Goods'),
    ('EQ.IND.COMMSVC', 'EQ.IND', 3, 'Commercial & Professional Services'),
    ('EQ.IND.TRANSPORT', 'EQ.IND', 3, 'Transportation'),
    ('EQ.IT.HARDWARE', 'EQ.IT', 3, 'Technology Hardware & Equipment'),
    ('EQ.IT.SEMI', 'EQ.IT', 3, 'Semiconductors & Semiconductor Equipment'),
    ('EQ.IT.SOFTWARE', 'EQ.IT', 3, 'Software & Services'),
    ('EQ.MAT.MATERIALS', 'EQ.MAT', 3, 'Materials'),
    ('EQ.RE.MGMT', 'EQ.RE', 3, 'Real Estate Management & Development'),
    ('EQ.RE.REITS', 'EQ.RE', 3, 'Equity Real Estate Investment Trusts (REITs)'),
    ('EQ.UTL.UTILITIES', 'EQ.UTL', 3, 'Utilities'),
    ('FI.CREDIT.HY', 'FI.CREDIT', 3, 'High yield'),
    ('FI.CREDIT.IG', 'FI.CREDIT', 3, 'Investment grade'),
    ('EQ.CD.AUTO.AUTOMOBILES', 'EQ.CD.AUTO', 4, 'Automobiles'),
    ('EQ.CD.AUTO.COMPONENTS', 'EQ.CD.AUTO', 4, 'Automobile Components'),
    ('EQ.CD.DURABLES.HOUSEHOLD', 'EQ.CD.DURABLES', 4, 'Household Durables'),
    ('EQ.CD.DURABLES.LEISURE', 'EQ.CD.DURABLES', 4, 'Leisure Products'),
    ('EQ.CD.DURABLES.TEXTILES', 'EQ.CD.DURABLES', 4, 'Textiles, Apparel & Luxury Goods'),
    ('EQ.CD.RETAIL.BROADLINE', 'EQ.CD.RETAIL', 4, 'Broadline Retail'),
    ('EQ.CD.RETAIL.SPECIALTY', 'EQ.CD.RETAIL', 4, 'Specialty Retail'),
    ('EQ.CD.SERVICES.HOTELS', 'EQ.CD.SERVICES', 4, 'Hotels, Restaurants & Leisure'),
    ('EQ.COM.MEDIA.ENTERTAIN', 'EQ.COM.MEDIA', 4, 'Entertainment'),
    ('EQ.COM.MEDIA.INTERACTIVE', 'EQ.COM.MEDIA', 4, 'Interactive Media & Services'),
    ('EQ.COM.MEDIA.MEDIA', 'EQ.COM.MEDIA', 4, 'Media'),
    ('EQ.COM.TELECOM.DIVERSIFIED', 'EQ.COM.TELECOM', 4, 'Diversified Telecommunication Services'),
    ('EQ.COM.TELECOM.WIRELESS', 'EQ.COM.TELECOM', 4, 'Wireless Telecommunication Services'),
    ('EQ.CS.FOOD.BEVERAGES', 'EQ.CS.FOOD', 4, 'Beverages'),
    ('EQ.CS.FOOD.FOOD', 'EQ.CS.FOOD', 4, 'Food Products'),
    ('EQ.CS.FOOD.TOBACCO', 'EQ.CS.FOOD', 4, 'Tobacco'),
    ('EQ.CS.HOUSEHOLD.HOUSEHOLD', 'EQ.CS.HOUSEHOLD', 4, 'Household Products'),
    ('EQ.CS.RETAIL.RETAIL', 'EQ.CS.RETAIL', 4, 'Consumer Staples Distribution & Retail'),
    ('EQ.EN.ENERGY.EQUIPSVC', 'EQ.EN.ENERGY', 4, 'Energy Equipment & Services'),
    ('EQ.EN.ENERGY.OILGAS', 'EQ.EN.ENERGY', 4, 'Oil, Gas & Consumable Fuels'),
    ('EQ.FIN.BANKS.BANKS', 'EQ.FIN.BANKS', 4, 'Banks'),
    ('EQ.FIN.FINSVC.CAPMKTS', 'EQ.FIN.FINSVC', 4, 'Capital Markets'),
    ('EQ.FIN.FINSVC.CONSUMER', 'EQ.FIN.FINSVC', 4, 'Consumer Finance'),
    ('EQ.FIN.FINSVC.FINSVC', 'EQ.FIN.FINSVC', 4, 'Financial Services'),
    ('EQ.FIN.FINSVC.MREITS', 'EQ.FIN.FINSVC', 4, 'Mortgage Real Estate Investment Trusts (REITs)'),
    ('EQ.FIN.INSURANCE.INSURANCE', 'EQ.FIN.INSURANCE', 4, 'Insurance'),
    ('EQ.HC.EQUIPSVC.EQUIPMENT', 'EQ.HC.EQUIPSVC', 4, 'Health Care Equipment & Supplies'),
    ('EQ.HC.EQUIPSVC.HCTECH', 'EQ.HC.EQUIPSVC', 4, 'Health Care Technology'),
    ('EQ.HC.EQUIPSVC.PROVIDERS', 'EQ.HC.EQUIPSVC', 4, 'Health Care Providers & Services'),
    ('EQ.HC.PHARMA.BIOTECH', 'EQ.HC.PHARMA', 4, 'Biotechnology'),
    ('EQ.HC.PHARMA.PHARMA', 'EQ.HC.PHARMA', 4, 'Pharmaceuticals'),
    ('EQ.IND.CAPGOODS.AEROSPACE', 'EQ.IND.CAPGOODS', 4, 'Aerospace & Defense'),
    ('EQ.IND.CAPGOODS.CONGLOM', 'EQ.IND.CAPGOODS', 4, 'Industrial Conglomerates'),
    ('EQ.IND.CAPGOODS.ELECTRICAL', 'EQ.IND.CAPGOODS', 4, 'Electrical Equipment'),
    ('EQ.IND.CAPGOODS.MACHINERY', 'EQ.IND.CAPGOODS', 4, 'Machinery'),
    ('EQ.IND.CAPGOODS.TRADING', 'EQ.IND.CAPGOODS', 4, 'Trading Companies & Distributors'),
    ('EQ.IND.COMMSVC.PROFESSIONAL', 'EQ.IND.COMMSVC', 4, 'Professional Services'),
    ('EQ.IND.TRANSPORT.AIRFREIGHT', 'EQ.IND.TRANSPORT', 4, 'Air Freight & Logistics'),
    ('EQ.IND.TRANSPORT.AIRLINES', 'EQ.IND.TRANSPORT', 4, 'Passenger Airlines'),
    ('EQ.IND.TRANSPORT.GROUND', 'EQ.IND.TRANSPORT', 4, 'Ground Transportation'),
    ('EQ.IND.TRANSPORT.MARINE', 'EQ.IND.TRANSPORT', 4, 'Marine Transportation'),
    ('EQ.IT.HARDWARE.TECHHW', 'EQ.IT.HARDWARE', 4, 'Technology Hardware, Storage & Peripherals'),
    ('EQ.IT.SEMI.EQUIP', 'EQ.IT.SEMI', 4, 'Semiconductors & Semiconductor Equipment'),
    ('EQ.IT.SOFTWARE.ITSVC', 'EQ.IT.SOFTWARE', 4, 'IT Services'),
    ('EQ.IT.SOFTWARE.SOFTWARE', 'EQ.IT.SOFTWARE', 4, 'Software'),
    ('EQ.MAT.MATERIALS.CHEMICALS', 'EQ.MAT.MATERIALS', 4, 'Chemicals'),
    ('EQ.MAT.MATERIALS.METALS', 'EQ.MAT.MATERIALS', 4, 'Metals & Mining'),
    ('EQ.RE.REITS.INDUSTRIAL', 'EQ.RE.REITS', 4, 'Industrial REITs'),
    ('EQ.RE.REITS.RETAIL', 'EQ.RE.REITS', 4, 'Retail REITs'),
    ('EQ.RE.REITS.SPECIALIZED', 'EQ.RE.REITS', 4, 'Specialized REITs'),
    ('EQ.UTL.UTILITIES.ELECTRIC', 'EQ.UTL.UTILITIES', 4, 'Electric Utilities'),
    ('EQ.UTL.UTILITIES.IPP', 'EQ.UTL.UTILITIES', 4, 'Independent Power and Renewable Electricity Producers'),
    ('EQ.UTL.UTILITIES.WATER', 'EQ.UTL.UTILITIES', 4, 'Water Utilities');

DO $$
DECLARE
    bad TEXT;
BEGIN
    SELECT string_agg(
        format('%s (seed parent %s level %s, existing parent %s level %s)',
               s.code, s.parent_code, s.level, n.parent_code, n.level),
        ', ' ORDER BY s.code) INTO bad
    FROM _seed_classification_node s
    JOIN classification_node n ON n.scheme = 'indicagent_v1' AND n.code = s.code
    WHERE n.parent_code IS DISTINCT FROM s.parent_code OR n.level <> s.level;
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'classification_node immutability violated in indicagent_v1 (D-01): %', bad;
    END IF;
END $$;

INSERT INTO classification_node (scheme, code, parent_code, level, name, path, valid_from)
WITH RECURSIVE tree AS (
    SELECT code, parent_code, level, name, ARRAY[code] AS path
    FROM _seed_classification_node
    WHERE parent_code IS NULL
    UNION ALL
    SELECT c.code, c.parent_code, c.level, c.name, t.path || c.code
    FROM _seed_classification_node c
    JOIN tree t ON c.parent_code = t.code
)
SELECT 'indicagent_v1', code, parent_code, level, name, path, (now() AT TIME ZONE 'UTC')::date
FROM tree
ORDER BY level, code
ON CONFLICT (scheme, code) DO UPDATE SET name = EXCLUDED.name;

-- Assignment staging. A symbol already holding a different current code aborts the seed.
CREATE TEMP TABLE _seed_instrument_classification (
    symbol     TEXT PRIMARY KEY,
    code       TEXT NOT NULL,
    source_ref TEXT NOT NULL
) ON COMMIT DROP;

INSERT INTO _seed_instrument_classification (symbol, code, source_ref) VALUES
    ('AA', 'EQ.MAT.MATERIALS.METALS', 'ibkr_contract_details+review'),
    ('AAPL', 'EQ.IT.HARDWARE.TECHHW', 'ibkr_contract_details+review'),
    ('ACTG', 'EQ.IND.COMMSVC.PROFESSIONAL', 'ibkr_contract_details+review'),
    ('ADM', 'EQ.CS.FOOD.FOOD', 'ibkr_contract_details+review'),
    ('AEP', 'EQ.UTL.UTILITIES.ELECTRIC', 'ibkr_contract_details+review'),
    ('AGG', 'FI.BROAD', 'fund_mandate'),
    ('ALMS', 'EQ.HC.PHARMA.BIOTECH', 'ibkr_contract_details+review'),
    ('AMD', 'EQ.IT.SEMI.EQUIP', 'ibkr_contract_details+review'),
    ('AMLP', 'EQ.EN.ENERGY.OILGAS', 'fund_mandate'),
    ('AMT', 'EQ.RE.REITS.SPECIALIZED', 'ibkr_contract_details+review'),
    ('AMZN', 'EQ.CD.RETAIL.BROADLINE', 'ibkr_contract_details+review'),
    ('ARKK', 'EQ.BROAD', 'fund_mandate'),
    ('ARRY', 'EQ.IND.CAPGOODS.ELECTRICAL', 'ibkr_contract_details+review'),
    ('ASML', 'EQ.IT.SEMI.EQUIP', 'ibkr_contract_details+review'),
    ('ATMU', 'EQ.IND.CAPGOODS.MACHINERY', 'ibkr_contract_details+review'),
    ('AVBP', 'EQ.HC.PHARMA.BIOTECH', 'ibkr_contract_details+review'),
    ('AVGO', 'EQ.IT.SEMI.EQUIP', 'ibkr_contract_details+review'),
    ('AWK', 'EQ.UTL.UTILITIES.WATER', 'ibkr_contract_details+review'),
    ('AXP', 'EQ.FIN.FINSVC.CONSUMER', 'ibkr_contract_details+review'),
    ('BA', 'EQ.IND.CAPGOODS.AEROSPACE', 'ibkr_contract_details+review'),
    ('BAC', 'EQ.FIN.BANKS.BANKS', 'ibkr_contract_details+review'),
    ('BEAM', 'EQ.HC.PHARMA.BIOTECH', 'ibkr_contract_details+review'),
    ('BHP', 'EQ.MAT.MATERIALS.METALS', 'ibkr_contract_details+review'),
    ('BIL', 'FI.RATES', 'fund_mandate'),
    ('BKE', 'EQ.CD.RETAIL.SPECIALTY', 'ibkr_contract_details+review'),
    ('BKNG', 'EQ.CD.SERVICES.HOTELS', 'ibkr_contract_details+review'),
    ('BLK', 'EQ.FIN.FINSVC.CAPMKTS', 'ibkr_contract_details+review'),
    ('BNTX', 'EQ.HC.PHARMA.BIOTECH', 'ibkr_contract_details+review'),
    ('BTAL', 'MA.ALT', 'fund_mandate'),
    ('CASY', 'EQ.CS.RETAIL.RETAIL', 'ibkr_contract_details+review'),
    ('CAT', 'EQ.IND.CAPGOODS.MACHINERY', 'ibkr_contract_details+review'),
    ('CCJ', 'EQ.EN.ENERGY.OILGAS', 'ibkr_contract_details+review'),
    ('CENT', 'EQ.CS.HOUSEHOLD.HOUSEHOLD', 'ibkr_contract_details+review'),
    ('CIBR', 'EQ.IT', 'fund_mandate'),
    ('CL', 'CMD.ENERGY', 'contract_spec'),
    ('CMCSA', 'EQ.COM.MEDIA.MEDIA', 'ibkr_contract_details+review'),
    ('COFS', 'EQ.FIN.BANKS.BANKS', 'ibkr_contract_details+review'),
    ('COIN', 'EQ.FIN.FINSVC.CAPMKTS', 'ibkr_contract_details+review'),
    ('COP', 'EQ.EN.ENERGY.OILGAS', 'ibkr_contract_details+review'),
    ('COST', 'EQ.CS.RETAIL.RETAIL', 'ibkr_contract_details+review'),
    ('CRI', 'EQ.CD.DURABLES.TEXTILES', 'ibkr_contract_details+review'),
    ('CRM', 'EQ.IT.SOFTWARE.SOFTWARE', 'ibkr_contract_details+review'),
    ('CRSP', 'EQ.HC.PHARMA.BIOTECH', 'ibkr_contract_details+review'),
    ('CRUS', 'EQ.IT.SEMI.EQUIP', 'ibkr_contract_details+review'),
    ('CRWD', 'EQ.IT.SOFTWARE.SOFTWARE', 'ibkr_contract_details+review'),
    ('CRWV', 'EQ.IT.SOFTWARE.ITSVC', 'ibkr_contract_details+review'),
    ('CSTM', 'EQ.MAT.MATERIALS.METALS', 'ibkr_contract_details+review'),
    ('CSX', 'EQ.IND.TRANSPORT.GROUND', 'ibkr_contract_details+review'),
    ('CTVA', 'EQ.MAT.MATERIALS.CHEMICALS', 'ibkr_contract_details+review'),
    ('CVS', 'EQ.HC.EQUIPSVC.PROVIDERS', 'ibkr_contract_details+review'),
    ('CVX', 'EQ.EN.ENERGY.OILGAS', 'ibkr_contract_details+review'),
    ('CWB', 'FI.CONV', 'fund_mandate'),
    ('DAL', 'EQ.IND.TRANSPORT.AIRLINES', 'ibkr_contract_details+review'),
    ('DAR', 'EQ.CS.FOOD.FOOD', 'ibkr_contract_details+review'),
    ('DBA', 'CMD.AG', 'fund_mandate'),
    ('DBB', 'CMD.INDMET', 'fund_mandate'),
    ('DBC', 'CMD.BROAD', 'fund_mandate'),
    ('DD', 'EQ.MAT.MATERIALS.CHEMICALS', 'ibkr_contract_details+review'),
    ('DE', 'EQ.IND.CAPGOODS.MACHINERY', 'ibkr_contract_details+review'),
    ('DHI', 'EQ.CD.DURABLES.HOUSEHOLD', 'ibkr_contract_details+review'),
    ('DIA', 'EQ.BROAD', 'fund_mandate'),
    ('DIS', 'EQ.COM.MEDIA.ENTERTAIN', 'ibkr_contract_details+review'),
    ('DOCS', 'EQ.HC.EQUIPSVC.HCTECH', 'ibkr_contract_details+review'),
    ('DOW', 'EQ.MAT.MATERIALS.CHEMICALS', 'ibkr_contract_details+review'),
    ('DUK', 'EQ.UTL.UTILITIES.ELECTRIC', 'ibkr_contract_details+review'),
    ('ECL', 'EQ.MAT.MATERIALS.CHEMICALS', 'ibkr_contract_details+review'),
    ('EDV', 'FI.RATES', 'fund_mandate'),
    ('EEM', 'EQ.BROAD', 'fund_mandate'),
    ('EFA', 'EQ.BROAD', 'fund_mandate'),
    ('ELV', 'EQ.HC.EQUIPSVC.PROVIDERS', 'ibkr_contract_details+review'),
    ('EMB', 'FI.EM', 'fund_mandate'),
    ('EMLC', 'FI.EM', 'fund_mandate'),
    ('EMR', 'EQ.IND.CAPGOODS.ELECTRICAL', 'ibkr_contract_details+review'),
    ('ENPH', 'EQ.IT.SEMI.EQUIP', 'ibkr_contract_details+review'),
    ('EPD', 'EQ.EN.ENERGY.OILGAS', 'ibkr_contract_details+review'),
    ('EQIX', 'EQ.RE.REITS.SPECIALIZED', 'ibkr_contract_details+review'),
    ('ES', 'EQ.BROAD', 'contract_spec'),
    ('ETHA', 'CRY.ETH', 'fund_mandate'),
    ('ETR', 'EQ.UTL.UTILITIES.ELECTRIC', 'ibkr_contract_details+review'),
    ('EURUSD', 'CCY.DM', 'contract_spec'),
    ('EWG', 'EQ.BROAD', 'fund_mandate'),
    ('EWJ', 'EQ.BROAD', 'fund_mandate'),
    ('EWT', 'EQ.BROAD', 'fund_mandate'),
    ('EWY', 'EQ.BROAD', 'fund_mandate'),
    ('EWZ', 'EQ.BROAD', 'fund_mandate'),
    ('EXEL', 'EQ.HC.PHARMA.BIOTECH', 'ibkr_contract_details+review'),
    ('EZU', 'EQ.BROAD', 'fund_mandate'),
    ('F', 'EQ.CD.AUTO.AUTOMOBILES', 'ibkr_contract_details+review'),
    ('FCX', 'EQ.MAT.MATERIALS.METALS', 'ibkr_contract_details+review'),
    ('FDX', 'EQ.IND.TRANSPORT.AIRFREIGHT', 'ibkr_contract_details+review'),
    ('FRHC', 'EQ.FIN.FINSVC.CAPMKTS', 'ibkr_contract_details+review'),
    ('FSLR', 'EQ.IT.SEMI.EQUIP', 'ibkr_contract_details+review'),
    ('FXA', 'CCY.DM', 'fund_mandate'),
    ('FXC', 'CCY.DM', 'fund_mandate'),
    ('FXE', 'CCY.DM', 'fund_mandate'),
    ('FXI', 'EQ.BROAD', 'fund_mandate'),
    ('FXY', 'CCY.DM', 'fund_mandate'),
    ('GBPUSD', 'CCY.DM', 'contract_spec'),
    ('GC', 'CMD.PREC', 'contract_spec'),
    ('GDX', 'EQ.MAT.MATERIALS.METALS', 'fund_mandate'),
    ('GE', 'EQ.IND.CAPGOODS.AEROSPACE', 'ibkr_contract_details+review'),
    ('GEV', 'EQ.IND.CAPGOODS.ELECTRICAL', 'ibkr_contract_details+review'),
    ('GILD', 'EQ.HC.PHARMA.BIOTECH', 'ibkr_contract_details+review'),
    ('GKOS', 'EQ.HC.EQUIPSVC.EQUIPMENT', 'ibkr_contract_details+review'),
    ('GLD', 'CMD.PREC', 'fund_mandate'),
    ('GM', 'EQ.CD.AUTO.AUTOMOBILES', 'ibkr_contract_details+review'),
    ('GOOGL', 'EQ.COM.MEDIA.INTERACTIVE', 'ibkr_contract_details+review'),
    ('GRBK', 'EQ.CD.DURABLES.HOUSEHOLD', 'ibkr_contract_details+review'),
    ('GS', 'EQ.FIN.FINSVC.CAPMKTS', 'ibkr_contract_details+review'),
    ('HCA', 'EQ.HC.EQUIPSVC.PROVIDERS', 'ibkr_contract_details+review'),
    ('HD', 'EQ.CD.RETAIL.SPECIALTY', 'ibkr_contract_details+review'),
    ('HG', 'CMD.INDMET', 'contract_spec'),
    ('HON', 'EQ.IND.CAPGOODS.CONGLOM', 'ibkr_contract_details+review'),
    ('HYD', 'FI.MUNI', 'fund_mandate'),
    ('HYG', 'FI.CREDIT.HY', 'fund_mandate'),
    ('IBB', 'EQ.HC.PHARMA.BIOTECH', 'fund_mandate'),
    ('IBIT', 'CRY.BTC', 'fund_mandate'),
    ('ICLN', 'EQ.BROAD', 'fund_mandate'),
    ('IEF', 'FI.RATES', 'fund_mandate'),
    ('IGV', 'EQ.IT.SOFTWARE.SOFTWARE', 'fund_mandate'),
    ('IHF', 'EQ.HC.EQUIPSVC.PROVIDERS', 'fund_mandate'),
    ('INDA', 'EQ.BROAD', 'fund_mandate'),
    ('INSW', 'EQ.EN.ENERGY.OILGAS', 'ibkr_contract_details+review'),
    ('IPO', 'EQ.BROAD', 'fund_mandate'),
    ('ISRG', 'EQ.HC.EQUIPSVC.EQUIPMENT', 'ibkr_contract_details+review'),
    ('ITA', 'EQ.IND.CAPGOODS.AEROSPACE', 'fund_mandate'),
    ('ITB', 'EQ.CD.DURABLES.HOUSEHOLD', 'fund_mandate'),
    ('IWM', 'EQ.BROAD', 'fund_mandate'),
    ('IYT', 'EQ.IND.TRANSPORT', 'fund_mandate'),
    ('IYZ', 'EQ.COM.TELECOM', 'fund_mandate'),
    ('JBHT', 'EQ.IND.TRANSPORT.GROUND', 'ibkr_contract_details+review'),
    ('JBS', 'EQ.CS.FOOD.FOOD', 'ibkr_contract_details+review'),
    ('JETS', 'EQ.IND.TRANSPORT.AIRLINES', 'fund_mandate'),
    ('JNJ', 'EQ.HC.PHARMA.PHARMA', 'ibkr_contract_details+review'),
    ('JPM', 'EQ.FIN.BANKS.BANKS', 'ibkr_contract_details+review'),
    ('KEX', 'EQ.IND.TRANSPORT.MARINE', 'ibkr_contract_details+review'),
    ('KMI', 'EQ.EN.ENERGY.OILGAS', 'ibkr_contract_details+review'),
    ('KO', 'EQ.CS.FOOD.BEVERAGES', 'ibkr_contract_details+review'),
    ('KRE', 'EQ.FIN.BANKS.BANKS', 'fund_mandate'),
    ('KWEB', 'EQ.BROAD', 'fund_mandate'),
    ('LEN', 'EQ.CD.DURABLES.HOUSEHOLD', 'ibkr_contract_details+review'),
    ('LIN', 'EQ.MAT.MATERIALS.CHEMICALS', 'ibkr_contract_details+review'),
    ('LLY', 'EQ.HC.PHARMA.PHARMA', 'ibkr_contract_details+review'),
    ('LMT', 'EQ.IND.CAPGOODS.AEROSPACE', 'ibkr_contract_details+review'),
    ('LQD', 'FI.CREDIT.IG', 'fund_mandate'),
    ('MAR', 'EQ.CD.SERVICES.HOTELS', 'ibkr_contract_details+review'),
    ('MARA', 'EQ.FIN.FINSVC.FINSVC', 'ibkr_contract_details+review'),
    ('MCD', 'EQ.CD.SERVICES.HOTELS', 'ibkr_contract_details+review'),
    ('MCHI', 'EQ.BROAD', 'fund_mandate'),
    ('META', 'EQ.COM.MEDIA.INTERACTIVE', 'ibkr_contract_details+review'),
    ('MGM', 'EQ.CD.SERVICES.HOTELS', 'ibkr_contract_details+review'),
    ('MMM', 'EQ.IND.CAPGOODS.CONGLOM', 'ibkr_contract_details+review'),
    ('MO', 'EQ.CS.FOOD.TOBACCO', 'ibkr_contract_details+review'),
    ('MOO', 'EQ.BROAD', 'fund_mandate'),
    ('MRK', 'EQ.HC.PHARMA.PHARMA', 'ibkr_contract_details+review'),
    ('MS', 'EQ.FIN.FINSVC.CAPMKTS', 'ibkr_contract_details+review'),
    ('MSFT', 'EQ.IT.SOFTWARE.SOFTWARE', 'ibkr_contract_details+review'),
    ('MSTR', 'EQ.FIN.FINSVC.FINSVC', 'ibkr_contract_details+review'),
    ('MTH', 'EQ.CD.DURABLES.HOUSEHOLD', 'ibkr_contract_details+review'),
    ('MTUM', 'EQ.BROAD', 'fund_mandate'),
    ('MUB', 'FI.MUNI', 'fund_mandate'),
    ('NAD', 'FI.MUNI', 'fund_mandate'),
    ('NEE', 'EQ.UTL.UTILITIES.ELECTRIC', 'ibkr_contract_details+review'),
    ('NEM', 'EQ.MAT.MATERIALS.METALS', 'ibkr_contract_details+review'),
    ('NFLX', 'EQ.COM.MEDIA.ENTERTAIN', 'ibkr_contract_details+review'),
    ('NG', 'CMD.ENERGY', 'contract_spec'),
    ('NLY', 'EQ.FIN.FINSVC.MREITS', 'ibkr_contract_details+review'),
    ('NQ', 'EQ.BROAD', 'contract_spec'),
    ('NTR', 'EQ.MAT.MATERIALS.CHEMICALS', 'ibkr_contract_details+review'),
    ('NUE', 'EQ.MAT.MATERIALS.METALS', 'ibkr_contract_details+review'),
    ('NVDA', 'EQ.IT.SEMI.EQUIP', 'ibkr_contract_details+review'),
    ('NVR', 'EQ.CD.DURABLES.HOUSEHOLD', 'ibkr_contract_details+review'),
    ('ODFL', 'EQ.IND.TRANSPORT.GROUND', 'ibkr_contract_details+review'),
    ('OIH', 'EQ.EN.ENERGY.EQUIPSVC', 'fund_mandate'),
    ('OXY', 'EQ.EN.ENERGY.OILGAS', 'ibkr_contract_details+review'),
    ('PANW', 'EQ.IT.SOFTWARE.SOFTWARE', 'ibkr_contract_details+review'),
    ('PEP', 'EQ.CS.FOOD.BEVERAGES', 'ibkr_contract_details+review'),
    ('PFE', 'EQ.HC.PHARMA.PHARMA', 'ibkr_contract_details+review'),
    ('PFF', 'FI.PREF', 'fund_mandate'),
    ('PG', 'EQ.CS.HOUSEHOLD.HOUSEHOLD', 'ibkr_contract_details+review'),
    ('PGNY', 'EQ.HC.EQUIPSVC.PROVIDERS', 'ibkr_contract_details+review'),
    ('PGR', 'EQ.FIN.INSURANCE.INSURANCE', 'ibkr_contract_details+review'),
    ('PLD', 'EQ.RE.REITS.INDUSTRIAL', 'ibkr_contract_details+review'),
    ('PM', 'EQ.CS.FOOD.TOBACCO', 'ibkr_contract_details+review'),
    ('PPLT', 'CMD.PREC', 'fund_mandate'),
    ('PURR', 'EQ.FIN.FINSVC.FINSVC', 'ibkr_contract_details+review'),
    ('QCOM', 'EQ.IT.SEMI.EQUIP', 'ibkr_contract_details+review'),
    ('QQQ', 'EQ.BROAD', 'fund_mandate'),
    ('QUAL', 'EQ.BROAD', 'fund_mandate'),
    ('R', 'EQ.IND.TRANSPORT.GROUND', 'ibkr_contract_details+review'),
    ('RCL', 'EQ.CD.SERVICES.HOTELS', 'ibkr_contract_details+review'),
    ('REGN', 'EQ.HC.PHARMA.BIOTECH', 'ibkr_contract_details+review'),
    ('RGR', 'EQ.CD.DURABLES.LEISURE', 'ibkr_contract_details+review'),
    ('RIOT', 'EQ.FIN.FINSVC.FINSVC', 'ibkr_contract_details+review'),
    ('RIVN', 'EQ.CD.AUTO.AUTOMOBILES', 'ibkr_contract_details+review'),
    ('RJF', 'EQ.FIN.FINSVC.CAPMKTS', 'ibkr_contract_details+review'),
    ('RSP', 'EQ.BROAD', 'fund_mandate'),
    ('RSPG', 'EQ.EN.ENERGY', 'fund_mandate'),
    ('RSPU', 'EQ.UTL.UTILITIES', 'fund_mandate'),
    ('RTX', 'EQ.IND.CAPGOODS.AEROSPACE', 'ibkr_contract_details+review'),
    ('RTY', 'EQ.BROAD', 'contract_spec'),
    ('RVMD', 'EQ.HC.PHARMA.BIOTECH', 'ibkr_contract_details+review'),
    ('SCHD', 'EQ.BROAD', 'fund_mandate'),
    ('SDOG', 'EQ.BROAD', 'fund_mandate'),
    ('SHW', 'EQ.MAT.MATERIALS.CHEMICALS', 'ibkr_contract_details+review'),
    ('SHY', 'FI.RATES', 'fund_mandate'),
    ('SI', 'CMD.PREC', 'contract_spec'),
    ('SLB', 'EQ.EN.ENERGY.EQUIPSVC', 'ibkr_contract_details+review'),
    ('SLM', 'EQ.FIN.FINSVC.CONSUMER', 'ibkr_contract_details+review'),
    ('SLV', 'CMD.PREC', 'fund_mandate'),
    ('SMH', 'EQ.IT.SEMI.EQUIP', 'fund_mandate'),
    ('SO', 'EQ.UTL.UTILITIES.ELECTRIC', 'ibkr_contract_details+review'),
    ('SPG', 'EQ.RE.REITS.RETAIL', 'ibkr_contract_details+review'),
    ('SPHB', 'EQ.BROAD', 'fund_mandate'),
    ('SPNT', 'EQ.FIN.INSURANCE.INSURANCE', 'ibkr_contract_details+review'),
    ('SPY', 'EQ.BROAD', 'fund_mandate'),
    ('SSP', 'EQ.COM.MEDIA.MEDIA', 'ibkr_contract_details+review'),
    ('STIP', 'FI.INFL', 'fund_mandate'),
    ('T', 'EQ.COM.TELECOM.DIVERSIFIED', 'ibkr_contract_details+review'),
    ('TDOC', 'EQ.HC.EQUIPSVC.PROVIDERS', 'ibkr_contract_details+review'),
    ('THC', 'EQ.HC.EQUIPSVC.PROVIDERS', 'ibkr_contract_details+review'),
    ('THRM', 'EQ.CD.AUTO.COMPONENTS', 'ibkr_contract_details+review'),
    ('TIP', 'FI.INFL', 'fund_mandate'),
    ('TLT', 'FI.RATES', 'fund_mandate'),
    ('TMUS', 'EQ.COM.TELECOM.WIRELESS', 'ibkr_contract_details+review'),
    ('TOL', 'EQ.CD.DURABLES.HOUSEHOLD', 'ibkr_contract_details+review'),
    ('TRV', 'EQ.FIN.INSURANCE.INSURANCE', 'ibkr_contract_details+review'),
    ('TSLA', 'EQ.CD.AUTO.AUTOMOBILES', 'ibkr_contract_details+review'),
    ('TSM', 'EQ.IT.SEMI.EQUIP', 'ibkr_contract_details+review'),
    ('TXT', 'EQ.IND.CAPGOODS.AEROSPACE', 'ibkr_contract_details+review'),
    ('UBER', 'EQ.IND.TRANSPORT.GROUND', 'ibkr_contract_details+review'),
    ('UNFI', 'EQ.CS.RETAIL.RETAIL', 'ibkr_contract_details+review'),
    ('UNH', 'EQ.HC.EQUIPSVC.PROVIDERS', 'ibkr_contract_details+review'),
    ('UNP', 'EQ.IND.TRANSPORT.GROUND', 'ibkr_contract_details+review'),
    ('UPB', 'EQ.HC.PHARMA.BIOTECH', 'ibkr_contract_details+review'),
    ('UPS', 'EQ.IND.TRANSPORT.AIRFREIGHT', 'ibkr_contract_details+review'),
    ('URA', 'EQ.EN.ENERGY', 'fund_mandate'),
    ('USB', 'EQ.FIN.BANKS.BANKS', 'ibkr_contract_details+review'),
    ('USDCHF', 'CCY.DM', 'contract_spec'),
    ('USDJPY', 'CCY.DM', 'contract_spec'),
    ('USMV', 'EQ.BROAD', 'fund_mandate'),
    ('UUP', 'CCY.USD', 'fund_mandate'),
    ('V', 'EQ.FIN.FINSVC.FINSVC', 'ibkr_contract_details+review'),
    ('VCR', 'EQ.CD', 'fund_mandate'),
    ('VDC', 'EQ.CS', 'fund_mandate'),
    ('VGT', 'EQ.IT', 'fund_mandate'),
    ('VHT', 'EQ.HC', 'fund_mandate'),
    ('VIX', 'VOL.EQUITY', 'contract_spec'),
    ('VIXY', 'VOL.EQUITY', 'fund_mandate'),
    ('VNDA', 'EQ.HC.PHARMA.PHARMA', 'ibkr_contract_details+review'),
    ('VNQ', 'EQ.RE', 'fund_mandate'),
    ('VOX', 'EQ.COM', 'fund_mandate'),
    ('VPU', 'EQ.UTL.UTILITIES', 'fund_mandate'),
    ('VRP', 'FI.PREF', 'fund_mandate'),
    ('VRTX', 'EQ.HC.PHARMA.BIOTECH', 'ibkr_contract_details+review'),
    ('VST', 'EQ.UTL.UTILITIES.IPP', 'ibkr_contract_details+review'),
    ('VTV', 'EQ.BROAD', 'fund_mandate'),
    ('VUG', 'EQ.BROAD', 'fund_mandate'),
    ('VWO', 'EQ.BROAD', 'fund_mandate'),
    ('VX', 'VOL.EQUITY', 'contract_spec'),
    ('VYM', 'EQ.BROAD', 'fund_mandate'),
    ('VZ', 'EQ.COM.TELECOM.DIVERSIFIED', 'ibkr_contract_details+review'),
    ('WCC', 'EQ.IND.CAPGOODS.TRADING', 'ibkr_contract_details+review'),
    ('WHR', 'EQ.CD.DURABLES.HOUSEHOLD', 'ibkr_contract_details+review'),
    ('WMB', 'EQ.EN.ENERGY.OILGAS', 'ibkr_contract_details+review'),
    ('WMT', 'EQ.CS.RETAIL.RETAIL', 'ibkr_contract_details+review'),
    ('WSHP', 'EQ.CD.RETAIL.BROADLINE', 'ibkr_contract_details+review'),
    ('WSM', 'EQ.CD.RETAIL.SPECIALTY', 'ibkr_contract_details+review'),
    ('WTRG', 'EQ.UTL.UTILITIES.WATER', 'ibkr_contract_details+review'),
    ('XBI', 'EQ.HC.PHARMA.BIOTECH', 'fund_mandate'),
    ('XHB', 'EQ.CD', 'fund_mandate'),
    ('XLB', 'EQ.MAT.MATERIALS', 'fund_mandate'),
    ('XLC', 'EQ.COM', 'fund_mandate'),
    ('XLE', 'EQ.EN.ENERGY', 'fund_mandate'),
    ('XLF', 'EQ.FIN', 'fund_mandate'),
    ('XLI', 'EQ.IND', 'fund_mandate'),
    ('XLK', 'EQ.IT', 'fund_mandate'),
    ('XLP', 'EQ.CS', 'fund_mandate'),
    ('XLRE', 'EQ.RE', 'fund_mandate'),
    ('XLU', 'EQ.UTL.UTILITIES', 'fund_mandate'),
    ('XLV', 'EQ.HC', 'fund_mandate'),
    ('XLY', 'EQ.CD', 'fund_mandate'),
    ('XOM', 'EQ.EN.ENERGY.OILGAS', 'ibkr_contract_details+review'),
    ('XOP', 'EQ.EN.ENERGY.OILGAS', 'fund_mandate'),
    ('XRT', 'EQ.CD.RETAIL', 'fund_mandate'),
    ('XTL', 'EQ.COM.TELECOM', 'fund_mandate'),
    ('XTN', 'EQ.IND.TRANSPORT', 'fund_mandate'),
    ('YM', 'EQ.BROAD', 'contract_spec'),
    ('ZB', 'FI.RATES', 'contract_spec'),
    ('ZC', 'CMD.AG', 'contract_spec'),
    ('ZF', 'FI.RATES', 'contract_spec'),
    ('ZN', 'FI.RATES', 'contract_spec'),
    ('ZS', 'CMD.AG', 'contract_spec'),
    ('ZT', 'FI.RATES', 'contract_spec'),
    ('ZW', 'CMD.AG', 'contract_spec');

DO $$
DECLARE
    bad TEXT;
BEGIN
    SELECT string_agg(format('%s (seed %s, current %s)', s.symbol, s.code, c.code),
                      ', ' ORDER BY s.symbol) INTO bad
    FROM _seed_instrument_classification s
    JOIN instrument_classification c
      ON c.symbol = s.symbol AND c.scheme = 'indicagent_v1' AND c.valid_to IS NULL
    WHERE c.code <> s.code;
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'seed disagrees with current indicagent_v1 assignments: %', bad;
    END IF;
END $$;

INSERT INTO instrument_classification (symbol, scheme, code, valid_from, source_ref)
SELECT s.symbol, 'indicagent_v1', s.code, (now() AT TIME ZONE 'UTC')::date, s.source_ref
FROM _seed_instrument_classification s
JOIN instruments i ON i.symbol = s.symbol
WHERE NOT EXISTS (
    SELECT 1 FROM instrument_classification c
    WHERE c.symbol = s.symbol AND c.scheme = 'indicagent_v1' AND c.valid_to IS NULL
)
ORDER BY s.symbol;

DO $$
DECLARE
    n_absent INTEGER;
    absent TEXT;
BEGIN
    SELECT count(*), string_agg(s.symbol, ', ' ORDER BY s.symbol) INTO n_absent, absent
    FROM _seed_instrument_classification s
    WHERE NOT EXISTS (SELECT 1 FROM instruments i WHERE i.symbol = s.symbol);
    RAISE NOTICE 'seed symbols absent from instruments (skipped): % %', n_absent, coalesce(absent, '');
END $$;

-- D-09 seed-time coverage guard.
DO $$
DECLARE
    bad TEXT;
BEGIN
    SELECT string_agg(i.symbol, ', ' ORDER BY i.symbol) INTO bad
    FROM instruments i
    WHERE i.is_active
      AND NOT EXISTS (
          SELECT 1 FROM instrument_classification c
          WHERE c.symbol = i.symbol AND c.scheme = 'indicagent_v1' AND c.valid_to IS NULL
      );
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'active instruments without a current indicagent_v1 assignment: %', bad;
    END IF;
END $$;

COMMIT;
