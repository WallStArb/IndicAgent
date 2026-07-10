-- Migration 220: instruments pg_notify trigger — todo 061
--
-- Relocates the CREATE TRIGGER/CREATE FUNCTION DDL that FeatureVectorPipeline._setup()
-- previously ran on every startup (via DatabaseManager.ensure_instruments_trigger())
-- into a migration, per DAG Invariants 2/3 (compute daemons never own schema mutation).
-- Idempotent (CREATE OR REPLACE) — safe to re-run; identical SQL to what the removed
-- runtime call executed, so this is a relocation, not new behavior.

BEGIN;

CREATE OR REPLACE FUNCTION notify_instrument_change()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('instruments', COALESCE(NEW.symbol, OLD.symbol));
    RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE OR REPLACE TRIGGER trg_instruments_notify
AFTER INSERT OR UPDATE OR DELETE ON instruments
FOR EACH ROW EXECUTE FUNCTION notify_instrument_change();

COMMIT;
