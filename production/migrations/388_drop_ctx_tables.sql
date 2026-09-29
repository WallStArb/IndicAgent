-- Migration 388: drop ctx_events and ctx_snapshots (retire the ctx pipeline, R-01,
-- phase 186 plan 11)
--
-- services/context_writer.py consumed topic ctx.snapshot, which has no publisher
-- anywhere in src, services or scripts, and wrote only these two tables. The unit
-- indicagent-ctx-writer was uninstalled from the host earlier in the same session.
--
-- PRECONDITIONS ASSERTED BEFORE THIS MIGRATION WAS WRITTEN (audit trail):
--   1. Consumer grep (ctx_events, ctx_snapshots, context_writer, ctx-writer,
--      topic_ctx_snapshot, ctx.snapshot) found only the files this plan deletes or
--      edits, old migrations, the pinned integration baselines, and history docs.
--   2. Covering card: docs/research/summary-cards/cache-ctx-tables.md, card lint
--      (tests/unit/test_summary_cards.py) green.
--   3. Both tables held 0 rows on 2026-09-27 (planning) and 2026-09-29 (execution).
--   4. The unit was stopped, disabled and uninstalled (no file or wants-link).
--
-- Dropping the ctx_events hypertable removes its compression job (1040) and
-- retention job (1049). No decompress happens, so the VACUUM-after-decompress rule
-- does not apply.
--
-- DROP TABLE without IF EXISTS or CASCADE: a missing table or an unexpected dependent
-- object should fail loudly.

BEGIN;

DO $$
DECLARE
    v_events   BIGINT;
    v_snaps    BIGINT;
    v_reader   INT;
BEGIN
    SELECT count(*) INTO v_events FROM ctx_events;
    IF v_events <> 0 THEN
        RAISE EXCEPTION 'refusing to drop: ctx_events holds % rows', v_events;
    END IF;

    SELECT count(*) INTO v_snaps FROM ctx_snapshots;
    IF v_snaps <> 0 THEN
        RAISE EXCEPTION 'refusing to drop: ctx_snapshots holds % rows', v_snaps;
    END IF;

    SELECT pid INTO v_reader
    FROM pg_stat_activity
    WHERE pid <> pg_backend_pid()
      AND state <> 'idle'
      AND (query ILIKE '%ctx_events%' OR query ILIKE '%ctx_snapshots%')
    LIMIT 1;
    IF v_reader IS NOT NULL THEN
        RAISE EXCEPTION 'refusing to drop: another session is reading ctx tables (pid %)', v_reader;
    END IF;
END $$;

-- APR key of the retired unit. No-op where the row is absent.
INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), cs.config_key, cs.version, cs.config_value, 'migration_388',
    'Removed: indicagent-ctx-writer retired (phase 186 plan 11, R-01); topic ctx.snapshot never had a publisher.'
FROM config_state cs
WHERE cs.config_key = 'alert.lag.ctx-writer'
  AND NOT EXISTS (
      SELECT 1 FROM config_history ch
      WHERE ch.config_key = cs.config_key AND ch.changed_by = 'migration_388'
  );

DELETE FROM config_state WHERE config_key = 'alert.lag.ctx-writer';
DELETE FROM config_schema WHERE config_key = 'alert.lag.ctx-writer';

DROP TABLE ctx_events;
DROP TABLE ctx_snapshots;

COMMIT;
