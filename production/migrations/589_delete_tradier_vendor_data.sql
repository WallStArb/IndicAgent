-- Migration 589: delete the Tradier vendor's stored data and retire the old-store backup key
-- (todo 574, owner 2026-11-12: Tradier history is not needed, Massive covers 2003 onward and
-- IBKR 1d reaches back to 1998; supersedes the 2026-11-01 KEEP ruling).
--
-- Tombstone (excluded-vendor rule): vendor tradier, reason owner_exclusion, 2026-11-12, todo 574,
-- deleted counts ohlcv_raw 7,140,397 (1d, 1,529 symbols, 2000-01-03 to 2026-10-06),
-- ohlcv_revision 155,350, ohlcv_coverage 1,529. The ohlcv_load and ohlcv_request rows that name
-- tradier are lineage and stay; so do the three retired bar_source_policy rows (decision history).
-- market_data_ohlcv holds no tradier row (policy never selects it), so canonical is unchanged.
-- Code recovery: git tag archive/tradier-2026-11.
--
-- infra.old_store_backup.disk_margin: its only reader, ops_old_store_backup.py, is deleted with
-- this migration (todo 574).
--
-- Rerun semantics: every statement matches nothing on a rerun. The CVR row is kept (lineage rows
-- still carry the code) and only its description changes.

BEGIN;

DELETE FROM ohlcv_revision WHERE vendor = 'tradier';
DELETE FROM ohlcv_coverage WHERE provider = 'tradier';
DELETE FROM ohlcv_raw WHERE vendor = 'tradier';

UPDATE controlled_vocabulary
   SET description = 'Tradier (deleted 2026-11-12, reason owner_exclusion, todo 574; '
                     'ohlcv_raw 7140397, ohlcv_revision 155350, ohlcv_coverage 1529 rows; '
                     'load and request lineage rows remain; code at git tag archive/tradier-2026-11)'
 WHERE namespace = 'bar_vendor' AND code = 'tradier';

DELETE FROM config_history WHERE config_key = 'infra.old_store_backup.disk_margin';
DELETE FROM config_state   WHERE config_key = 'infra.old_store_backup.disk_margin';
DELETE FROM config_schema  WHERE config_key = 'infra.old_store_backup.disk_margin';

COMMIT;
