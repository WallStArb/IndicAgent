-- Migration 338: factor and vol-proxy exposure tag taxonomy (Phase 174, plan 07, D-06).
--
-- Correction to CONTEXT.md D-06: D-06 states momentum and quality factor-tilt ETFs currently
-- have "zero representation" in the corpus. That premise is FALSE -- verified live in this
-- session:
--
--   SELECT symbol, is_active FROM instruments WHERE symbol IN ('MTUM','QUAL','USMV');
--     MTUM | t     QUAL | t     USMV | t
--   SELECT symbol, count(*) FROM market_data_ohlcv WHERE symbol IN ('MTUM','QUAL','USMV')
--   GROUP BY symbol;
--     MTUM: 2,194,069 rows     QUAL: 2,156,803 rows     USMV: 2,417,375 rows
--
-- MTUM (iShares MSCI USA Momentum Factor ETF), QUAL (iShares MSCI USA Quality Factor ETF), and
-- USMV (iShares MSCI USA Min Volatility Factor ETF) were all added 2026-05-15, are
-- is_active=true, and are already fully backfilled across all four timeframes. These figures
-- match 174-RESEARCH.md's own live-verified numbers exactly -- no discrepancy to record. D-06's
-- intent (momentum and quality exposure present and individually identifiable) is therefore
-- satisfied here by a tag-taxonomy change, not by sourcing new instruments. Plan 10 handles the
-- two exposures that genuinely have no instrument at all (EM currency, volatility).
--
-- Why USMV gets eq_low_vol even though D-06 dropped low-vol from scope: D-06 dropped adding a
-- NEW low-vol ETF; USMV is already in the universe carrying the coarse eq_factor tag. Splitting
-- eq_momentum/eq_quality out for MTUM/QUAL while leaving USMV under the coarse label would
-- silently redefine eq_factor to mean "low-vol plus market-neutral plus high-beta" -- a worse
-- taxonomy than either the fully-split or fully-coarse endpoint. Zero sourcing or backfill cost
-- either way, so there is no reason not to tag it.
--
-- Do NOT insert fx_em -- it already exists in tag_vocabulary (category=exposure, 0 member
-- symbols today). Its absence from this migration is intentional, not an oversight: Plan 10
-- tags the EM-FX pick it onboards against this pre-existing vocabulary row.
--
-- What is deliberately NOT done here:
--   - No new instrument rows (Plan 10 owns onboarding EMLC/CEW-or-VIXY/VXX candidates).
--   - No eq_factor deletion or modification -- BTAL (market-neutral) and SPHB (high-beta) keep
--     the coarse tag and get no new specific tag; their structures are not factor tilts in the
--     momentum/quality/low-vol sense and inventing tags for them is outside D-06's scope.
--   - No fx_em tag_vocabulary insert (already present).
--   - vol_proxy is created here as vocabulary only -- it has zero member symbols until Plan 10
--     onboards and tags its vol-proxy pick.
--
-- Both blocks use ON CONFLICT ... DO NOTHING; safe to re-run, idempotent.

BEGIN;

-- ---------------------------------------------------------------------------
-- Block 1: new tag_vocabulary rows, category=exposure. eq_momentum/eq_quality/eq_low_vol split
-- the coarse eq_factor label so factor-specific IC stratification becomes possible; eq_factor
-- itself is retained unchanged as the parent-level label. vol_proxy is a NEW exposure category
-- distinct from the existing sensitivity-category `volatility` tag: `volatility` is an
-- empirically-measured OLS beta against a factor_series proxy (TagCalibrator-owned, can be
-- contradicted/expired); `vol_proxy` is a definitional claim ("this instrument's primary
-- exposure IS equity-index implied volatility") that is a permanent human seed prior, never
-- measured or auto-expired, per this project's ITR rules.
-- ---------------------------------------------------------------------------

INSERT INTO tag_vocabulary (tag, category, description) VALUES
    ('eq_momentum', 'exposure', 'Equity momentum factor tilt -- split out of the coarse eq_factor tag (Phase 174 D-06) so momentum exposure is individually identifiable for factor-specific IC stratification. eq_factor is retained as the parent-level label; this tag refines, not replaces, it.'),
    ('eq_quality',  'exposure', 'Equity quality factor tilt -- split out of the coarse eq_factor tag (Phase 174 D-06) so quality exposure is individually identifiable for factor-specific IC stratification. eq_factor is retained as the parent-level label; this tag refines, not replaces, it.'),
    ('eq_low_vol',  'exposure', 'Equity minimum/low-volatility factor tilt -- split out of the coarse eq_factor tag (Phase 174 D-06) so low-vol exposure is individually identifiable for factor-specific IC stratification. eq_factor is retained as the parent-level label; this tag refines, not replaces, it.'),
    ('vol_proxy',   'exposure', 'Instrument whose primary exposure IS equity-index implied volatility (a VIX-futures-linked ETF/ETN). Distinct from the sensitivity-category `volatility` tag, which is an empirically-measured beta against a volatility factor_series and can be contradicted/expired by TagCalibrator -- this is a definitional exposure claim, a permanent human seed prior, never measured or auto-expired.')
ON CONFLICT (tag) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Block 2: retag MTUM/QUAL/USMV with their specific factor tag, alongside (not replacing) their
-- existing eq_factor row. All rows source='human', weight=1.0.
-- ---------------------------------------------------------------------------

INSERT INTO instrument_tags (symbol, tag, weight, source, evidence) VALUES
    ('MTUM', 'eq_momentum', 1.0, 'human', '{"reason": "iShares MSCI USA Momentum Factor ETF -- refines, does not replace, the existing eq_factor row. is_active=true since 2026-05-15, 2,194,069 market_data_ohlcv rows verified live 2026-09-15."}'),
    ('QUAL', 'eq_quality',  1.0, 'human', '{"reason": "iShares MSCI USA Quality Factor ETF -- refines, does not replace, the existing eq_factor row. is_active=true since 2026-05-15, 2,156,803 market_data_ohlcv rows verified live 2026-09-15."}'),
    ('USMV', 'eq_low_vol',  1.0, 'human', '{"reason": "iShares MSCI USA Min Volatility Factor ETF -- refines, does not replace, the existing eq_factor row. is_active=true since 2026-05-15, 2,417,375 market_data_ohlcv rows verified live 2026-09-15."}')
ON CONFLICT (symbol, tag) DO NOTHING;

COMMIT;
