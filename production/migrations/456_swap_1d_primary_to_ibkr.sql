-- Migration 456: the 1d primary moves from Tradier to IBKR SMART TRADES from D = 2026-10-07
-- (phase 185 plan 47; docs/research/1d-primary-swap-evidence.md rule R1, shape F)
--
-- Owner decision 2026-10-07: the Tradier account will not be funded (its API answers HTTP 401),
-- so no new Tradier bar arrives. Tradier bars dated before D stay canonical history with full
-- standing; from D the 1d default is IBKR SMART TRADES with no fallback (d2-v2 admits a fallback
-- only under a Tradier primary, and there is no second 1d vendor; D-01 Stage V).
--
-- D is the first NYSE session after the last Tradier 1d observation (2026-10-06). The open
-- default row (primary tradier, fallback ibkr, from 1990-01-01) closes at D through the one
-- UPDATE the append-only trigger of migration 446 allows; a new default opens at D. Symbol rows
-- are not touched: a symbol row beats the default for the dates it covers, so the 74 open
-- IBKR-primary rows, the 31 closed ones and the 185-47 hold rows decide their names as before.
--
-- Volume basis (R5): from D canonical 1d volume is IBKR SMART's, about 0.53 of Tradier's
-- consolidated volume at the cross-sectional median over the last 250 common sessions (1,528
-- names, measured 2026-10-08), so a research snapshot that pins policy_as_of sees the step in
-- this row's evidence.
--
-- Rule R1's stop condition is checked inside the transaction: a Tradier observation dated on or
-- after D aborts it. Rerunnable: the UPDATE finds no open Tradier default and the INSERT finds
-- an open default, so a second run changes nothing.
--
-- Rollback (plan 185-47 objective): a later migration closes this default at D plus one day and
-- opens a Tradier default (primary tradier, fallback ibkr) from that day.

BEGIN;

SET LOCAL lock_timeout = '10s';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ohlcv_observation
        WHERE timeframe = '1d' AND route = 'TRADIER' AND bar_date >= DATE '2026-10-07'
    ) THEN
        RAISE EXCEPTION 'migration 456: a Tradier 1d observation is dated on or after D (rule R1)';
    END IF;
END $$;

UPDATE bar_source_policy SET valid_to = DATE '2026-10-07'
WHERE timeframe = '1d' AND symbol IS NULL AND valid_to IS NULL
  AND primary_source = 'tradier' AND fallback_source = 'ibkr';

INSERT INTO bar_source_policy
    (timeframe, symbol, valid_from, valid_to, ingress_mode, primary_source, fallback_source,
     reason, evidence)
SELECT '1d', NULL::text, DATE '2026-10-07', NULL::date, 'observed', 'ibkr', NULL::text,
       'Owner decision 2026-10-07: Tradier is unfunded, the 1d primary moves to IBKR SMART TRADES from D = 2026-10-07 (first NYSE session after the last Tradier bar, 2026-10-06), no fallback. Bars before D keep their policy. Volume basis changes at D (IBKR over Tradier median 0.53, recent 250 sessions). docs/research/1d-primary-swap-evidence.md rule R1, plan 185-47.',
       '{"decision": "1d primary IBKR SMART TRADES from D, no fallback (shape F)", "owner_decision_date": "2026-10-07", "basis_change_date": "2026-10-07", "tradier_last_bar_date": "2026-10-06", "volume_ratio_recent250_p10": 0.4095, "volume_ratio_recent250_p50": 0.5278, "volume_ratio_recent250_p90": 0.8068, "volume_ratio_names": 1528, "volume_ratio_measured": "2026-10-08", "volume_ratio_185_46": {"p10": 0.418, "p50": 0.541, "p90": 0.853, "names": 1032}, "source_doc": "docs/research/1d-primary-swap-evidence.md", "plan": "185-47"}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM bar_source_policy p
    WHERE p.timeframe = '1d' AND p.symbol IS NULL AND p.valid_to IS NULL
);

COMMIT;
