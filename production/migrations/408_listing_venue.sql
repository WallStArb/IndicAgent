-- Migration 408: listing_venue, the point-in-time listing venue per symbol (phase 185 plan 24,
-- D6, D-25)
--
-- IBKR serves SMART-routed history only from a stock's last listing-venue move; the same
-- contract routed to the former venue serves the earlier years (D1 venue observations, read
-- through the ohlcv_venue_head view). services/listing_venue_writer.py infers, per symbol,
-- the venue each date range was listed on: the max-volume former venue for each range before
-- the SMART head, then SMART's latest primary_exchange from the head on. The venue code is the
-- IBKR primary-exchange vocabulary (route ISLAND is NASDAQ).
--
-- Point-in-time and append-only, the classification pattern (migration 367) with one
-- difference: this history is reconstructed, not recorded forward. A move found today
-- happened years ago, so an INSERT may carry a past valid_from and a close may carry a past
-- valid_to. What stays forbidden is rewriting: no two spans of a symbol overlap (EXCLUDE),
-- the only UPDATE closes an open span (valid_to from NULL to a date, every other column
-- unchanged), and DELETE and TRUNCATE raise for every role. An inference that later changes
-- is a conflict the writer reports, never an edit.
--
-- The writer is bar_derivation_writer (NOLOGIN, reached through SET LOCAL ROLE, migration
-- 380); each run is one bar_derivation_batch row with stage listing_venue (already allowed by
-- that table's stage check).

BEGIN;

CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE IF NOT EXISTS listing_venue (
    symbol text NOT NULL REFERENCES instruments(symbol) ON DELETE RESTRICT,
    venue text NOT NULL CHECK (venue ~ '^[A-Z]{2,16}$'),
    valid_from date NOT NULL,
    valid_to date NULL,
    evidence jsonb NOT NULL,
    batch_id uuid REFERENCES bar_derivation_batch(batch_id),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, valid_from),
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT ex_listing_venue_no_overlap EXCLUDE USING gist (
        symbol WITH =,
        daterange(valid_from, valid_to, '[)') WITH &&
    )
);

COMMENT ON TABLE listing_venue IS
    'Point-in-time listing venue per symbol (migration 408, D6, D-25): [valid_from, valid_to) '
    'spans that never overlap, valid_to NULL for the current listing. Inferred from D1 venue '
    'observations (max-volume former venue per range before the SMART head) and the latest '
    'SMART primary_exchange. Reconstructed history: past valid_from and valid_to are allowed; '
    'the only update closes an open span; DELETE and TRUNCATE raise. evidence names the '
    'ohlcv_request rows behind each span.';

CREATE OR REPLACE FUNCTION listing_venue_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.valid_to IS NOT NULL THEN
            RAISE EXCEPTION 'listing_venue: span (%, %) is closed and immutable',
                OLD.symbol, OLD.valid_from USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.valid_to IS NULL THEN
            RAISE EXCEPTION 'listing_venue: an update must close the open span of % with a date',
                OLD.symbol USING ERRCODE = 'check_violation';
        END IF;
        IF (NEW.symbol, NEW.venue, NEW.valid_from, NEW.evidence, NEW.batch_id, NEW.recorded_at)
           IS DISTINCT FROM
           (OLD.symbol, OLD.venue, OLD.valid_from, OLD.evidence, OLD.batch_id, OLD.recorded_at) THEN
            RAISE EXCEPTION 'listing_venue: only valid_to may change (close the span, insert a new one)'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    ELSE
        RAISE EXCEPTION 'listing_venue is append-only: % is not allowed', TG_OP
            USING ERRCODE = 'check_violation';
    END IF;
END $$;

COMMENT ON FUNCTION listing_venue_append_only() IS
    'Allows INSERT and the one UPDATE that closes an open span (valid_to NULL to a date); '
    'refuses every other UPDATE, DELETE and TRUNCATE on listing_venue (migration 408).';

DROP TRIGGER IF EXISTS trg_listing_venue_append_only ON listing_venue;

CREATE TRIGGER trg_listing_venue_append_only
    BEFORE INSERT OR UPDATE OR DELETE ON listing_venue
    FOR EACH ROW EXECUTE FUNCTION listing_venue_append_only();

DROP TRIGGER IF EXISTS trg_listing_venue_no_truncate ON listing_venue;

CREATE TRIGGER trg_listing_venue_no_truncate
    BEFORE TRUNCATE ON listing_venue
    FOR EACH STATEMENT EXECUTE FUNCTION listing_venue_append_only();

GRANT INSERT, SELECT ON listing_venue TO bar_derivation_writer;
GRANT UPDATE (valid_to) ON listing_venue TO bar_derivation_writer;
REVOKE UPDATE, DELETE, TRUNCATE ON listing_venue FROM PUBLIC;

COMMIT;
