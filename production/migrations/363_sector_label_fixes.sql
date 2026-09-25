-- Migration 363: correct and complete instruments.contract_details->>'sector'.
--
-- 'equity' was never a sector: it was the original five-instrument seed's placeholder and
-- held GLD (gold), SMH (semiconductors), SPY (broad market), TLT (Treasuries) and XLF
-- (financials) in one group. 24 later ETFs were onboarded with no sector at all. Found
-- 2026-09-25 while measuring the research residual target's sector factor (todo 384 update).
--
-- Scope: the compute_eligible research universe. 40 active single names from the 1d-only
-- pilot (compute_eligible_1d) also have no sector; they are stocks, which need a real
-- industry classification rather than a fund-mandate label, and are left to todo 384.
--
-- Every row here is an ETF, labeled by its fund mandate, so the label is definitional and
-- holds for the fund's whole history (no point-in-time issue). Labels reuse existing values
-- only; the tiered hierarchy that replaces this flat field is todo 384.
BEGIN;

WITH fix(symbol, sector) AS (VALUES
    ('GLD',  'commodity'),
    ('SMH',  'technology'),
    ('SPY',  'broad_market'),
    ('TLT',  'rates'),
    ('XLF',  'financials'),
    ('AGG',  'fixed_income'),
    ('ARKK', 'high_beta'),
    ('BIL',  'rates'),
    ('CIBR', 'technology'),
    ('EWJ',  'international'),
    ('EWT',  'international'),
    ('EWY',  'international'),
    ('IBIT', 'crypto'),
    ('IGV',  'technology'),
    ('INDA', 'international'),
    ('ITA',  'industrials'),
    ('KWEB', 'international'),
    ('MUB',  'municipal_bonds'),
    ('OIH',  'energy'),
    ('PFF',  'preferred_securities'),
    ('RSP',  'broad_market'),
    ('SCHD', 'defensive_yield'),
    ('TIP',  'tips'),
    ('VNQ',  'real_estate'),
    ('VTV',  'factor'),
    ('VUG',  'factor'),
    ('XBI',  'healthcare_biotech'),
    ('XHB',  'consumer_discretionary'),
    ('XRT',  'consumer_discretionary')
)
UPDATE instruments i
SET contract_details = jsonb_set(i.contract_details, '{sector}', to_jsonb(fix.sector))
FROM fix
WHERE i.symbol = fix.symbol
  AND coalesce(i.contract_details->>'sector', '') IN ('', 'equity');

DO $$
DECLARE
    bad TEXT;
BEGIN
    SELECT string_agg(symbol, ', ' ORDER BY symbol) INTO bad
    FROM instruments
    WHERE compute_eligible AND coalesce(contract_details->>'sector', '') IN ('', 'equity');
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'compute_eligible instruments still without a real sector: %', bad;
    END IF;
END $$;

COMMIT;
