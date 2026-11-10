-- Migration 587: reference_raw holds non-HTTP answers and names its vendors in CVR (todo 600
-- admission step 3b).
--
-- The step 3b identity anchor is IBKR contract details (the ISIN of every equity instrument),
-- answered over IBKR's socket API, which has no HTTP status. Migration 586 made http_status
-- NOT NULL with a 100-599 CHECK, so an IBKR row would need an invented status. This lets
-- http_status be NULL for exactly the non-HTTP answers: an http(s) URL carries the status it
-- was served, any other URL (ibkr://reqContractDetails?...) carries none. Readers already judge
-- the body's own status, never the HTTP status alone (586's comment); an IBKR body carries
-- status OK, NOT_FOUND (Error 200) or ERROR.
--
-- Vendors: 586 says reference_raw.vendor is a CVR bar_vendor code, but the step 3b anchor
-- answers come from OpenFIGI, which serves no bars. The vendors of reference answers get their
-- own CVR namespace, reference_vendor (massive, ibkr, openfigi), and the reference_raw writer
-- refuses a root whose directory names no code in it (a mistyped root would otherwise load
-- under an invented vendor). The column CHECK stays the code format; the CVR is read at load.
--
-- No compressed hypertable is touched (no VACUUM is owed). Idempotent.

BEGIN;

ALTER TABLE reference_raw ALTER COLUMN http_status DROP NOT NULL;

ALTER TABLE reference_raw DROP CONSTRAINT IF EXISTS ck_reference_raw_http_status_iff_http;
ALTER TABLE reference_raw
    ADD CONSTRAINT ck_reference_raw_http_status_iff_http
    CHECK ((http_status IS NOT NULL) = (url ~ '^https?://'));

COMMENT ON COLUMN reference_raw.http_status IS
    'HTTP status as served for an http(s) answer; NULL for a non-HTTP answer (an IBKR socket '
    'reply, url ibkr://...), migration 587. Readers judge the body status.';

INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order)
VALUES
    ('reference_vendor', 'massive', 'Massive',
     'Massive REST reference answers (tickers, overview, events, corporate actions, ...)', 1),
    ('reference_vendor', 'ibkr', 'IBKR',
     'IBKR contract details over the socket API (the ISIN anchor, todo 600 step 3b)', 2),
    ('reference_vendor', 'openfigi', 'OpenFIGI',
     'OpenFIGI mapping of an ISIN to its US composite and share-class FIGI (todo 600 step 3b)', 3)
ON CONFLICT (namespace, code) DO NOTHING;

COMMENT ON COLUMN reference_raw.vendor IS
    'Who answered: a CVR reference_vendor code (migration 587), checked by the writer at load.';

COMMIT;
