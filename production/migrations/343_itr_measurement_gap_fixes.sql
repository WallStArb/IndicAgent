-- Migration 343: fix 8 tag_vocabulary rows TagCalibrator has been silently skipping every run.
--
-- Discovered while investigating Phase 174's D-10 pilot gate FAIL: TagCalibrator's own run log
-- flags exactly 8 tags each run as "not measurable -- data-integrity anomaly" (measurement_type=
-- 'beta_regression' but factor_series IS NULL, which migration 238's Option A sweep was supposed
-- to make impossible). All 8 are live, human-asserted, in-use tags (single_name_equity alone
-- carries 168 rows) -- not dead vocabulary, real gaps. Root-caused into two distinct bugs:
--
-- Bug A -- wrong measurement_type (2 tags): single_name_equity and vol_proxy are IDENTITY
-- claims ("is this a single stock" / "is this a VIX-linked product"), not falsifiable exposure
-- hypotheses -- there is no sensible factor_series to regress either against. Migration 338's
-- own comment for vol_proxy proves this was the intent all along: "a definitional exposure
-- claim ... never measured or auto-expired, per this project's ITR rules." Neither migration
-- 238 (single_name_equity) nor 338 (vol_proxy) set measurement_type explicitly on INSERT, so
-- both silently took the column's DEFAULT 'beta_regression' instead of 'definitional' -- exactly
-- the kind of silent-wrong-answer footgun root CLAUDE.md warns about. Fix: correct both rows to
-- 'definitional' and null out their factor_series/loading_threshold (matching every other
-- definitional row's shape, e.g. fx_em).
--
-- Bug B -- correctly typed, never wired (6 tags): wireless_infrastructure, clean_energy,
-- commodity_uranium, eq_low_vol, eq_momentum, eq_quality are genuine falsifiable exposure
-- hypotheses (do OTHER instruments in the corpus show a measurable return-correlation to this
-- theme/factor), but nobody ever set their factor_series, so they've never been measured against
-- anything. Verified live in this session that a real, liquid, already-backfilled proxy exists
-- in `instruments` for every one of them -- zero new onboarding required:
--
--   SELECT symbol, is_active, compute_eligible FROM instruments
--   WHERE symbol IN ('IYZ','ICLN','URA','USMV','MTUM','QUAL');
--     all 6: is_active=true, compute_eligible=true
--   SELECT symbol, count(*), min(timestamp), max(timestamp)
--   FROM market_data_ohlcv_tradeable WHERE timeframe='1d'
--   AND symbol IN ('IYZ','ICLN','URA','USMV','MTUM','QUAL') GROUP BY symbol;
--     IYZ: 5023 rows (2006-08-11 to 2026-08-10)   ICLN: 4559 rows (2008-06-25 to 2026-08-10)
--     URA: 3961 rows (2010-11-05 to 2026-08-07)   USMV: 3710 rows (2011-10-21 to 2026-08-10)
--     MTUM: 3343 rows (2013-04-18 to 2026-08-10)  QUAL: 3281 rows (2013-07-18 to 2026-08-10)
--
-- Proxy choices: IYZ (iShares US Telecom) for wireless_infrastructure -- reuses the existing
-- eq_sub_sector-tagged telecom ETF rather than sourcing a niche 5G-specific fund. ICLN (iShares
-- Global Clean Energy) and URA (Global X Uranium) are the direct, unambiguous named proxies for
-- their tags. USMV/MTUM/QUAL are migration 338's own eq_low_vol/eq_momentum/eq_quality
-- definitional picks -- self-regression (F6.1) already skips each fund measuring itself, so
-- wiring them as factor_series lets every OTHER instrument in the corpus get measured for
-- loading against that specific factor, without disturbing USMV/MTUM/QUAL's own human-asserted
-- rows (never overwritten by TagCalibrator regardless).
--
-- loading_threshold=0.2 for all 6, matching every other working sensitivity/macro_driver row
-- (rate_sensitive, oil_price, semi_cycle, etc.) -- no basis in this session's evidence for a
-- different bar, so inheriting the existing convention rather than inventing a new one.
--
-- lookback_days=252 / half_life_days=180 already correct on all 8 rows (unaffected, not part of
-- either bug) -- left untouched.
--
-- Idempotent: every statement is an UPDATE keyed on tag (primary key), safe to re-run with zero
-- additional effect.

BEGIN;

-- Bug A: identity/definitional tags wrongly defaulted to 'beta_regression'.
UPDATE tag_vocabulary
SET measurement_type = 'definitional',
    factor_series = NULL,
    loading_threshold = NULL
WHERE tag IN ('single_name_equity', 'vol_proxy');

-- Bug B: correctly-typed exposure/factor tags, never wired to a proxy.
UPDATE tag_vocabulary SET factor_series = 'IYZ',  loading_threshold = 0.2 WHERE tag = 'wireless_infrastructure';
UPDATE tag_vocabulary SET factor_series = 'ICLN', loading_threshold = 0.2 WHERE tag = 'clean_energy';
UPDATE tag_vocabulary SET factor_series = 'URA',  loading_threshold = 0.2 WHERE tag = 'commodity_uranium';
UPDATE tag_vocabulary SET factor_series = 'USMV', loading_threshold = 0.2 WHERE tag = 'eq_low_vol';
UPDATE tag_vocabulary SET factor_series = 'MTUM', loading_threshold = 0.2 WHERE tag = 'eq_momentum';
UPDATE tag_vocabulary SET factor_series = 'QUAL', loading_threshold = 0.2 WHERE tag = 'eq_quality';

COMMIT;
