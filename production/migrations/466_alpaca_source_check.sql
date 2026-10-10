-- 466: admit 'alpaca' into the source CHECK constraints (todo 521 admission build).
--
-- The 521 admission build stores 5m bars with source 'alpaca' (the row tuples' vendor,
-- derived and enforced by the ingress contract) and writes ohlcv_load rows with the same
-- label; both tables' CHECK constraints predate the second vendor. Same widening shape as
-- migrations 438 (Tradier) and 443 (derived). Idempotent.

BEGIN;

ALTER TABLE ohlcv_request DROP CONSTRAINT IF EXISTS ohlcv_request_source_check;
ALTER TABLE ohlcv_request
    ADD CONSTRAINT ohlcv_request_source_check CHECK (source IN ('ibkr', 'tradier', 'alpaca'));

ALTER TABLE ohlcv_load DROP CONSTRAINT IF EXISTS ohlcv_load_source_check;
ALTER TABLE ohlcv_load
    ADD CONSTRAINT ohlcv_load_source_check CHECK (source IN ('tradier', 'ibkr', 'derived', 'alpaca'));

COMMIT;
