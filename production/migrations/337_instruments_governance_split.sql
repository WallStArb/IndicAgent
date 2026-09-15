-- Migration 337: instruments governance split -- backfill-eligible / compute-eligible /
-- live-tradeable 3-way split (Phase 174, plan 174-02, D-07; closes todo 274).
--
-- Today `instruments.is_active` conflates three distinct questions into one boolean:
-- "fetch OHLCV for this symbol" (backfill), "run feature_factory/ic_engine/regime models
-- against it" (compute), and "eligible for live IBKR streaming" (live-trading). All 37
-- existing get_active_contracts() call sites read is_active as a single flag today.
-- Marking a future Russell-3000-scale sample is_active=true under that single-flag model
-- would silently make hundreds-to-thousands of names live-trading-eligible too -- IBKR's
-- 80-simultaneous-subscription cap (reqMktData / reqHistoricalData keepUpToDate=True)
-- only binds live streaming, not backfill or compute, but a future
-- indicagent-ibkr-provider restart against an unsplit universe would nondeterministically
-- fail to honor that cap. This gap already survived the 111->231 expansion untouched
-- (todo 274); it does not survive a second, much larger one.
--
-- is_active is deliberately NOT renamed or repurposed here. 37 call sites read it today,
-- and it already means "backfill-eligible" in practice -- every one of the current 231
-- active rows is both backfilled AND compute-consumed. Renaming would force a review of
-- every one of those call sites for zero behavioral gain; adding two new columns is
-- additive and leaves every existing reader untouched.
--
-- Default mapping for the 231 existing rows, justified by a MEASURED audit (this plan's
-- Task 1, scripts/analysis/instrument_compute_eligibility_audit.py), not an assumption:
--   compute_eligible = true  -- the audit found all 231 is_active=true symbols have
--     non-zero market_data_ohlcv_tradeable rows AND a fetch_complete backfill_status row
--     in every one of the four timeframes (5m/15m/1h/1d). No symbol needs calling out as
--     a demotion candidate -- the measured aggregate was n_active=231,
--     n_with_all_four_tfs=231, n_missing_any_tf=0, n_zero_rows=0 (full output recorded in
--     174-02-SUMMARY.md). compute_eligible=true for all existing rows is therefore
--     bit-for-bit behavior-preserving, not a guess.
--   live_tradeable = false  -- honest, not a regression: nothing reads live_tradeable yet,
--     live IBKR streaming is confirmed dormant (root CLAUDE.md), and no <=80-symbol
--     whitelist has ever been chosen. Every row starts at false; a future live-trading
--     restart must explicitly promote a bounded subset, never inherit the full corpus
--     universe by default.
--
-- This migration deliberately does NOT touch contract_metadata (futures-only front-month/
-- roll bookkeeping) -- no futures are in Phase 174's scope, and contract_metadata's
-- is_front_month flag is an orthogonal concept to this 3-way split.
--
-- This migration deliberately does NOT change get_active_contracts()'s query or add the
-- dimension= parameter -- that is Plan 06's scope (D-07 continued). This plan lands only
-- the schema and the measured default; nothing in src/ reads compute_eligible or
-- live_tradeable yet, so there is no consumer-behavior risk from landing the schema alone.
--
-- Idempotent: DDL uses ADD COLUMN IF NOT EXISTS (migration 158's pattern); the UPDATE is
-- naturally idempotent (re-running it re-asserts the same values for the same WHERE
-- clause). Safe to re-run.

BEGIN;

-- ── Block 1: additive DDL, behavior-preserving defaults ─────────────────────────

ALTER TABLE instruments
    ADD COLUMN IF NOT EXISTS compute_eligible boolean NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS live_tradeable   boolean NOT NULL DEFAULT false;

-- ── Block 2: explicit backfill statement ─────────────────────────────────────────
-- Redundant with the DEFAULT above but explicit per CLAUDE.md's "silent wrong answers
-- are worse than loud crashes" -- the semantic mapping decision must be a visible,
-- reviewable SQL statement, not only an implicit column default.

UPDATE instruments SET compute_eligible = true, live_tradeable = false WHERE is_active = true;

-- ── Block 3: schema-level documentation of the 3-way split ──────────────────────
-- The semantics live in the schema itself, not only in a planning doc.

COMMENT ON COLUMN instruments.is_active IS
    'Dimension 1 of 3 (Phase 174 D-07): BACKFILL-ELIGIBLE. Retained with unchanged '
    'semantics; 37 call sites read it. Do not repurpose or rename.';

COMMENT ON COLUMN instruments.compute_eligible IS
    'Dimension 2 of 3 (Phase 174 D-07): COMPUTE-ELIGIBLE -- feature_factory / ic_engine / '
    'regime models consume this symbol. Newly onboarded symbols are set false until '
    'backfill completes across ALL FOUR timeframes, then promoted. The promotion predicate '
    'is COMPUTE_READY_PREDICATE_SQL in scripts/analysis/instrument_compute_eligibility_'
    'audit.py -- all four timeframes fetch_complete AND non-zero tradeable rows in all '
    'four, never an any-one-timeframe test.';

COMMENT ON COLUMN instruments.live_tradeable IS
    'Dimension 3 of 3 (Phase 174 D-07): LIVE-TRADEABLE -- eligible for IBKR live streaming '
    '(reqMktData / reqHistoricalData keepUpToDate=True), which is subject to the '
    '80-simultaneous-subscription cap. Defaults false for every row; no row is '
    'live-eligible until a subscription whitelist is explicitly chosen.';

COMMIT;
