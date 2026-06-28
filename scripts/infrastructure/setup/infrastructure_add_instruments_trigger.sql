-- Idempotent trigger: fires pg_notify('instruments', symbol) on any instruments row change.
-- Safe to re-run: both statements use CREATE OR REPLACE.
-- Applied to production DB as part of Phase 091-01 (instrument-registry).

CREATE OR REPLACE FUNCTION notify_instrument_change()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    -- COALESCE handles DELETE (NEW is NULL) and INSERT (OLD is NULL).
    PERFORM pg_notify('instruments', COALESCE(NEW.symbol, OLD.symbol));
    RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE OR REPLACE TRIGGER trg_instruments_notify
AFTER INSERT OR UPDATE OR DELETE ON instruments
FOR EACH ROW EXECUTE FUNCTION notify_instrument_change();
