-- 506: alpha.validation.oos_start is write-once (todo 439 part 1; unified design sections 11
-- and 12.2, E18).
--
-- The key bounds every research read (snapshot.py refuses end_exclusive past it; ic_measure and
-- measure/targets.py stop targets before it) and so guards the forward span. As a mutable APR
-- value, one config write (ConfigService.set, an operator UPDATE, a stray seed) would silently
-- reopen the span. This trigger refuses any UPDATE or DELETE of its config_state row, including
-- the ON CONFLICT DO UPDATE that ConfigService's upsert issues, and any UPDATE that renames
-- another row to the key. Row triggers never fire on TRUNCATE, which would empty the table and
-- let a fresh INSERT set any value, so TRUNCATE config_state is refused outright (no legitimate
-- writer truncates it). The refusal aborts the writer's transaction, so the config_history
-- row ConfigService writes first is rolled back with it.
--
-- The value stays 2025-12-24T05:15:00Z (version 2, last changed 2026-06-29; checked
-- 2026-10-26). A first INSERT is still allowed, so a fresh database can seed the key; while the
-- row is absent every reader raises (snapshot.py "is not set", ic_measure's missing-key check)
-- rather than falling back to a default. A real re-vintaging is a design decision: it drops
-- these triggers in its own migration, which makes the change reviewed and visible in git,
-- never a config write.
-- Idempotent: the function is replaced and the trigger dropped and re-created.

BEGIN;

CREATE OR REPLACE FUNCTION refuse_oos_start_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.config_key = 'alpha.validation.oos_start' THEN
            RAISE EXCEPTION 'alpha.validation.oos_start is write-once (migration 506): delete refused';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.config_key = 'alpha.validation.oos_start'
       OR NEW.config_key = 'alpha.validation.oos_start' THEN
        RAISE EXCEPTION 'alpha.validation.oos_start is write-once (migration 506): update refused';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_config_state_oos_start_write_once ON config_state;
CREATE TRIGGER trg_config_state_oos_start_write_once
    BEFORE UPDATE OR DELETE ON config_state
    FOR EACH ROW EXECUTE FUNCTION refuse_oos_start_change();

CREATE OR REPLACE FUNCTION refuse_config_state_truncate() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'config_state cannot be truncated: alpha.validation.oos_start is write-once (migration 506)';
END;
$$;

DROP TRIGGER IF EXISTS trg_config_state_no_truncate ON config_state;
CREATE TRIGGER trg_config_state_no_truncate
    BEFORE TRUNCATE ON config_state
    FOR EACH STATEMENT EXECUTE FUNCTION refuse_config_state_truncate();

COMMENT ON FUNCTION refuse_oos_start_change() IS
    'Refuses UPDATE and DELETE of alpha.validation.oos_start in config_state (migration 506, todo 439).';

COMMIT;
