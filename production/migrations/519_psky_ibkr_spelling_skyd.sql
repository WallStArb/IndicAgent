-- Migration 519: PSKY is asked at IBKR as SKYD (todo 519, owner decision 2026-10-26).
--
-- Paramount Skydance's Class B shares were renamed Skydance Corporation and moved from Nasdaq to
-- NYSE as SKYD around 2026-10-06. IBKR no longer resolves PSKY ("No security definition"); SKYD
-- resolves to conid 804144296 (NYSE, SKYDANCE CORP) with TRADES head 2025-08-07, PSKY's own SMART
-- head, so it is the same security under a new spelling. Measured 2026-10-26 (read-only probe):
-- every SKYD close over the 17 common sessions 2026-09-08..09-30 is the stored PSKY ibkr
-- smart_trades close times 0.9787..0.9796 (volume about 1.02x): IBKR re-served the series on a
-- new scale at the rename. The first fetch re-serves PSKY's IBKR history last-wins on that scale
-- (the old values go to ohlcv_revision); the owner holds the name as an unclassified rescale, to
-- be decided with CTVA (todo 516).
--
-- The spelling uses the existing provider_meta.ibkr.symbol mechanism (BRK.B -> "BRK B");
-- instruments.symbol stays PSKY, the concept identity. Alpaca has no spelling override yet
-- (follow-up in todo 519). Idempotent.

BEGIN;

UPDATE instruments
   SET contract_details = jsonb_set(
           contract_details,
           '{provider_meta}',
           COALESCE(contract_details -> 'provider_meta', '{}'::jsonb)
             || jsonb_build_object(
                    'ibkr',
                    COALESCE(contract_details #> '{provider_meta,ibkr}', '{}'::jsonb)
                      || '{"symbol": "SKYD"}'::jsonb
                )
       )
 WHERE symbol = 'PSKY'
   AND (contract_details #>> '{provider_meta,ibkr,symbol}') IS DISTINCT FROM 'SKYD';

COMMIT;
