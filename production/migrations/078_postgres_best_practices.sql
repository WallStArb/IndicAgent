-- 072_postgres_best_practices.sql
-- Postgres runtime configuration hardening.
--
-- Changes:
--   1. idle_in_transaction_session_timeout = 30s
--      Transactions idle-in-transaction hold row locks. Without a timeout
--      they accumulate until restart, blocking writers and vacuum.
--   2. idle_session_timeout = 10min
--      Reclaim connection slots from clients that connect and then go
--      quiet. Effective on PG14+; this cluster is PG15.

ALTER SYSTEM SET idle_in_transaction_session_timeout = '30s';
ALTER SYSTEM SET idle_session_timeout = '10min';

SELECT pg_reload_conf();
