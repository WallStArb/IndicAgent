-- Migration 531: infra.backfill.fetch_concurrency is an int.
--
-- Migration 471 seeded the key with value_type 'integer', which ConfigService's validator does
-- not know ('int' is the integer type), so ConfigService.set refused every write to it
-- ("Unknown value_type: 'integer'"); the earlier change to 2 went in by direct SQL. The only
-- reader (scripts/infrastructure/backfill/_fetch_queue.py) casts with int(), so the corrected
-- type changes no read. Ten other keys carry the same invalid types ('integer' x7 and 'text' x3)
-- and are left alone here: other readers may depend on the uncast values (todo 556).

BEGIN;

UPDATE config_schema
   SET value_type = 'int'
 WHERE config_key = 'infra.backfill.fetch_concurrency' AND value_type = 'integer';

COMMIT;
