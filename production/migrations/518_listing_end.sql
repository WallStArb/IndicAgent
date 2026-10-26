-- Migration 518: listing_end, a name's recorded last session (todo 519, owner decision 2026-10-26).
--
-- A merger, buyout or delisting ends a name's listing. The name is never deactivated (onboarding
-- SOP rule 6): it stays active and in every panel, its bars simply stop. Without a record of the
-- end, freshness_1d fails the name every night and the plan 191-19 readiness gate needs a
-- hand-passed --frozen-names list. One append-only row per ended name carries the last session,
-- the reason and the evidence (the exchange's Form 25 or the issuer's Form 15, plus each vendor's
-- last bar); a correction is a new row that supersedes the old one. Readers:
-- services/bar_reconciliation_audit.py (freshness_1d counts no session after it) and
-- scripts/ops/bars/ops_tradier_residue.py (ended names are flagged, never gated). Written by
-- migration only.
--
-- Seed rows, checked 2026-10-26 against SEC EDGAR and ohlcv_raw:
--   CCO  taken private by Mubadala Capital, closed 2026-10-14; NYSE suspended trading 2026-10-15
--        and filed Form 25-NSE 2026-10-15 (accession 0000876661-26-000839).
--   QRVO merged into Skyworks (trades as SWKS); Nasdaq filed Form 25-NSE 2026-10-05 (accession
--        0001354457-26-000942); last alpaca and tradier bars 2026-10-02.
--   WBD  acquired by Paramount Skydance for cash, closed about 2026-10-06; issuer Form 15-12G
--        2026-10-16 (accession 0001193125-26-423513); last alpaca and tradier bars 2026-10-05.

BEGIN;

CREATE TABLE IF NOT EXISTS listing_end (
    listing_end_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol text NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
    last_session date NOT NULL,
    reason text NOT NULL CHECK (reason IN ('acquired', 'merged', 'taken_private', 'delisted')),
    evidence jsonb NOT NULL CHECK (evidence <> '{}'::jsonb),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    supersedes uuid NULL REFERENCES listing_end(listing_end_id)
);

COMMENT ON TABLE listing_end IS
    'Append-only record of a name''s last listed session (migration 518, todo 519). The name '
    'stays active and in every panel; freshness_1d judges it up to last_session. Corrections are '
    'new rows with supersedes; read through listing_end_current.';

CREATE INDEX IF NOT EXISTS idx_listing_end_symbol ON listing_end (symbol);

CREATE OR REPLACE FUNCTION listing_end_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_listing_end_append_only ON listing_end;
CREATE TRIGGER trg_listing_end_append_only
    BEFORE UPDATE OR DELETE ON listing_end
    FOR EACH ROW
    EXECUTE FUNCTION listing_end_append_only();

DROP TRIGGER IF EXISTS trg_listing_end_no_truncate ON listing_end;
CREATE TRIGGER trg_listing_end_no_truncate
    BEFORE TRUNCATE ON listing_end
    FOR EACH STATEMENT
    EXECUTE FUNCTION listing_end_append_only();

CREATE OR REPLACE VIEW listing_end_current AS
SELECT le.*
FROM listing_end le
WHERE NOT EXISTS (
    SELECT 1 FROM listing_end newer WHERE newer.supersedes = le.listing_end_id
);

COMMENT ON VIEW listing_end_current IS
    'listing_end rows that no later row supersedes (migration 518).';

REVOKE UPDATE, DELETE, TRUNCATE ON listing_end FROM PUBLIC;

INSERT INTO listing_end (symbol, last_session, reason, evidence)
SELECT v.symbol, v.last_session, v.reason, v.evidence::jsonb
FROM (VALUES
    ('CCO', DATE '2026-10-14', 'taken_private',
     '{"source": "SEC EDGAR", "form": "25-NSE", "filed": "2026-10-15", "accession": "0000876661-26-000839", "note": "NYSE suspended trading 2026-10-15; Mubadala Capital buyout closed 2026-10-14"}'),
    ('QRVO', DATE '2026-10-02', 'merged',
     '{"source": "SEC EDGAR", "form": "25-NSE", "filed": "2026-10-05", "accession": "0001354457-26-000942", "note": "merged into Skyworks (SWKS); last alpaca 5m and tradier 1d bars 2026-10-02"}'),
    ('WBD', DATE '2026-10-05', 'acquired',
     '{"source": "SEC EDGAR", "form": "15-12G", "filed": "2026-10-16", "accession": "0001193125-26-423513", "note": "Paramount Skydance cash acquisition closed about 2026-10-06; last alpaca 5m and tradier 1d bars 2026-10-05"}')
) AS v(symbol, last_session, reason, evidence)
WHERE NOT EXISTS (SELECT 1 FROM listing_end le WHERE le.symbol = v.symbol);

COMMIT;
