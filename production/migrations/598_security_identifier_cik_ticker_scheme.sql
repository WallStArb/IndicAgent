-- 598: security_identifier scheme cik_ticker (todo 609, stage 2 pit-anchor map).
--
-- docs/plans/2026-11-15-pit-anchor-map-and-stage2-instruments.md, section 3. A ticker_event row
-- needs a security_identifier row, and the scheme set (two FIGIs, ISIN, CUSIP) has no key for a
-- security the vendor serves with a CIK and no FIGI. Measured 2026-11-15: a composite FIGI is
-- served for 24 percent of the active ticker records of 2003, 40 percent of 2010 and 82 percent
-- of 2026, so a FIGI-only anchor would leave most pre-2012 names unplaced. The new scheme
-- cik_ticker holds '<10-digit CIK>:<ticker string>': the issuer and the string together, never
-- the CIK alone (one CIK covers BRK.A and BRK.B).
--
-- Only the two check constraints change. Rows already there satisfy both, no data moves and no
-- compressed table is touched, so no VACUUM clause is owed. Rerun-safe: each constraint is
-- dropped if present and added back.

BEGIN;

ALTER TABLE security_identifier DROP CONSTRAINT IF EXISTS security_identifier_scheme_check;
ALTER TABLE security_identifier ADD CONSTRAINT security_identifier_scheme_check
    CHECK (scheme IN ('share_class_figi', 'composite_figi', 'isin', 'cusip', 'cik_ticker'));

ALTER TABLE security_identifier DROP CONSTRAINT IF EXISTS ck_security_identifier_value_format;
ALTER TABLE security_identifier ADD CONSTRAINT ck_security_identifier_value_format CHECK (
    CASE scheme
        WHEN 'isin' THEN value ~ '^[A-Z]{2}[0-9A-Z]{9}[0-9]$'
        WHEN 'cusip' THEN value ~ '^[0-9A-Z*@#]{8}[0-9]$'
        WHEN 'cik_ticker' THEN value ~ '^[0-9]{10}:[^[:space:]]+$'
        ELSE value ~ '^[B-DF-HJ-NP-TV-Z]{2}G[B-DF-HJ-NP-TV-Z0-9]{8}[0-9]$'
    END
);

COMMIT;
