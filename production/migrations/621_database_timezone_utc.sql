-- 621: the database's session timezone is UTC by its own setting, not by the server's postgresql.conf (todo 614 row 11).
--
-- Every `::date`, `date_trunc` and `timestamptz` cast in the repo reads the session timezone, and 129 call sites open
-- their own connection, so the setting belongs on the database where every connection inherits it. Today the server is
-- already UTC (verified 2026-11-27: SHOW timezone = UTC), so this changes no result; it keeps a rebuilt host, the
-- Debian timescaledb-ha image of todo 654 or a standby with a different postgresql.conf from shifting a date. A
-- new connection factory in 53 modules (the audit's original answer) is deleted: it would edit modules inside the
-- rebuild's code key to restate what one database setting says.
-- Idempotent; no table is rewritten, so no VACUUM clause is owed.
-- Reverse: ALTER DATABASE <db> RESET timezone;  (new connections only; the server default then applies)

DO $$
BEGIN
    EXECUTE format('ALTER DATABASE %I SET timezone = %L', current_database(), 'UTC');
END
$$;
