-- Migration 499: drop the two old bar stores (phase 191 plan 16, design doc step 8).
--
-- ohlcv_raw is the one table of vendor answers (todo 533): plan 191-05 moved every write to it
-- and plan 191-13 proved the swapped canonical equal, so the stores it replaced are dead weight.
-- The COPY backup this drop depends on is data/backups/191/ (ops_old_store_backup.py dump and
-- verify both passed 2026-10-17, manifest old_store_backup_manifest.json, 218,252,126 rows,
-- retention until 2026-11-12).
--
-- Live object map, re-verified 2026-10-17: the archive carries the two append-only triggers
-- (trg_ohlcv_intraday_raw_archive_no_delete, trg_ohlcv_intraday_raw_archive_no_truncate) and
-- their function ohlcv_archive_no_delete, which serves nothing else; ohlcv_observation has had
-- no triggers since migration 438. The FKs (ohlcv_observation_request_id_fkey to ohlcv_request,
-- ohlcv_intraday_raw_archive_batch_id_fkey to bar_derivation_batch) and the grants go with
-- their tables. bar_derivation_append_only is NOT dropped: bar_content_digest still uses it.
-- The pg_depend guard below allows exactly the table family (the tables, their chunks, the
-- family's own constraints and triggers) and aborts on any other dependent, so a view or FK
-- somebody adds later cannot be destroyed silently. ohlcv_request and bar_derivation_batch are
-- never named as targets and must survive this migration untouched.
--
-- Order inside the transaction: guard, then the two parent triggers, then the tables (the
-- archive first, then the observation), then the function. The function drop must follow the
-- table drops because the archive's ~89 chunk-level trigger clones reference it and only
-- disappear with the table. No CASCADE anywhere: anything the explicit drops cannot take must
-- stop the migration, not cascade to it.
--
-- Also retires two orphaned APR keys, in the order history, state, schema (the retirement
-- order of migrations 349, 431, 434, 457 and 459), citing 191-16:
--   infra.backfill.ohlcv_insert_batch_size (migration 428) - its only reader was the fetcher's
--     canonical/archive insert batching, deleted by plan 191-05; the raw write batches by
--     infra.ohlcv_observation.copy_batch_rows.
--   infra.raw_backfill.statement_timeout_s (migration 381) - its subject, the one-shot
--     ops_raw_backfill.py, is deleted by this same plan 191-16 commit; ops_selection_gate.py
--     moved to infra.selection_gate.statement_timeout_s (migration 500).
-- Reader check, 2026-10-17: grep -rn "infra.backfill.ohlcv_insert_batch_size\|infra.raw_backfill.statement_timeout_s" services src scripts -> no output.
--
-- Idempotent: every DROP is IF EXISTS and the DELETEs match nothing on a rerun. Not
-- decompress/recompress: no chunk is touched, so no trailing VACUUM clause is owed here; the
-- post-apply VACUUMs run as separate statements per the plan.

BEGIN;

SET LOCAL lock_timeout = '30s';

DO $$
DECLARE
    offender text;
BEGIN
    WITH family AS (
        SELECT 'ohlcv_observation'::regclass AS tbl
        UNION ALL
        SELECT 'ohlcv_intraday_raw_archive'::regclass
        UNION ALL
        SELECT i.inhrelid
          FROM pg_inherits i
          JOIN (VALUES ('ohlcv_observation'::regclass), ('ohlcv_intraday_raw_archive'::regclass))
            AS parents(parent) ON i.inhparent = parents.parent
    )
    SELECT format('%s (a %s)', d.objid, d.classid::regclass)
      INTO offender
      FROM pg_depend d
      JOIN family f ON d.refobjid = f.tbl
     WHERE d.deptype = 'n'
       AND NOT (
            (d.classid = 'pg_class'::regclass AND d.objid IN (SELECT tbl FROM family))
         OR (d.classid = 'pg_constraint'::regclass AND d.objid IN (
                SELECT con.oid FROM pg_constraint con
                 WHERE con.conrelid IN (SELECT tbl FROM family)))
         OR (d.classid = 'pg_trigger'::regclass AND d.objid IN (
                SELECT t.oid FROM pg_trigger t
                 WHERE t.tgrelid IN (SELECT tbl FROM family)
                   AND NOT t.tgisinternal))
       )
     LIMIT 1;
    IF offender IS NOT NULL THEN
        RAISE EXCEPTION
            'unexpected dependent on ohlcv_observation or ohlcv_intraday_raw_archive: %; name it and handle it before this drop',
            offender;
    END IF;
END $$;

DROP TRIGGER IF EXISTS trg_ohlcv_intraday_raw_archive_no_delete ON ohlcv_intraday_raw_archive;
DROP TRIGGER IF EXISTS trg_ohlcv_intraday_raw_archive_no_truncate ON ohlcv_intraday_raw_archive;

DROP TABLE ohlcv_intraday_raw_archive;
DROP TABLE ohlcv_observation;

DROP FUNCTION IF EXISTS ohlcv_archive_no_delete();

DELETE FROM config_history
 WHERE config_key IN ('infra.backfill.ohlcv_insert_batch_size',
                      'infra.raw_backfill.statement_timeout_s');
DELETE FROM config_state
 WHERE config_key IN ('infra.backfill.ohlcv_insert_batch_size',
                      'infra.raw_backfill.statement_timeout_s');
DELETE FROM config_schema
 WHERE config_key IN ('infra.backfill.ohlcv_insert_batch_size',
                      'infra.raw_backfill.statement_timeout_s');

COMMIT;
