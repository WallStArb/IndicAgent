-- Migration 315: APR-back an idle_session_timeout/idle_in_transaction_session_timeout
-- override for compressed_hypertable_write_session / async_compressed_hypertable_write_session
--
-- Confirmed live 2026-08-15: regime_writer.py's session connection (bracketing a compute
-- run for 80 previously-missing feature_vectors symbols) decompressed all 85 chunks
-- cleanly, then sat completely idle for ~55 minutes while its ProcessPoolExecutor workers
-- computed HMM walk-forward fits in separate processes -- real, necessary work, but not
-- work this connection itself was doing. Postgres's role/database default
-- idle_session_timeout (1h, tuned for interactive/API connections that should never sit
-- idle that long) killed the connection outright. Every subsequent write failed
-- ("the connection is closed"), and because the same dead connection was supposed to run
-- this function's own recompress+VACUUM cleanup at exit, feature_vectors was left fully
-- decompressed across all 85 chunks -- same failure shape as migration 314's
-- statement_timeout incident, just triggered by idle time between statements instead of
-- one statement's runtime. Migration 314 already overrides statement_timeout for this
-- exact reason; idle_session_timeout is a distinct GUC with no relationship to it and was
-- never covered.
--
-- This one APR key also covers idle_in_transaction_session_timeout (same value applied to
-- both GUCs) as defense-in-depth -- NOT because the incident hit it (the session's own
-- conn.commit() right before yielding to the caller means there's no open transaction
-- during the idle gap, so only the bare idle_session_timeout was actually observed live).
-- regime_writer.py/forward_return_writer.py already disable idle_in_transaction_session_
-- timeout at connect time (`options="-c idle_in_transaction_session_timeout=0"`), making
-- this override redundant for them specifically; kept because compressed_hypertable_
-- write_session is shared infrastructure and cannot assume every caller follows that
-- connect-time convention (a bare `psycopg.connect()` does not).
--
-- Default is disabled (0, Postgres's convention for "no timeout" on this GUC) rather than
-- a generous-but-bounded value like migration 314's 4h statement_timeout: unlike a single
-- statement's runtime (which this function's own decompress/recompress/VACUUM calls
-- roughly bound), the idle gap between those calls is caller-determined -- an arbitrary
-- amount of external compute (worker pool HMM fits, feature-factory computation, etc.)
-- can happen between them, and there is no value this function could pick that is
-- guaranteed large enough for every future caller.
--
-- Do NOT "fix" this by picking a bounded-but-generous number instead (8h, 24h, etc.) --
-- that just defers the identical bug to a longer fuse. The role default (1h) already WAS
-- someone's reasonable-sounding generous guess, and it broke a legitimate, non-buggy run;
-- any other guessed bound is exposed to the same risk the moment a future caller's
-- legitimate work runs long enough. And the one thing idle_session_timeout could catch
-- that disabling it loses -- a truly abandoned connection (caller crashed/hung, no query
-- in flight, nothing ever coming) -- is not actually protected by a bounded value either
-- in any way that matters here: a connection blocked or executing is caught by
-- statement_timeout already (separately overridden, migration 314); idle_session_timeout
-- only fires when NO query is in flight at all, which for this function's callers is the
-- legitimate "doing external work" case, not the leaked-connection case. A genuinely
-- abandoned connection belongs to operational monitoring (pg_stat_activity idle-connection
-- alerting), not a per-call GUC that has already been proven to guess wrong once.

BEGIN;

INSERT INTO config_schema (config_key, value_type, description) VALUES
    ('infra.compressed_hypertable_write_session.idle_session_timeout_ms', 'int',
     '[rca_analysis] idle_session_timeout AND idle_in_transaction_session_timeout '
     '(milliseconds, same value applied to both) applied for the duration of '
     'compressed_hypertable_write_session / async_compressed_hypertable_write_session '
     '(services/_batch_utils.py), overriding the role/database default (1h) that is '
     'tuned for interactive/API connections, not this function''s own long batch '
     'decompress/[caller work]/recompress+VACUUM sequence where the middle step''s '
     'duration is caller-determined and can leave this connection idle for an arbitrary '
     'time. Restored to the connection''s prior value on exit. Not an ML learning target '
     '-- pure infrastructure timeout knob, output is invariant to this value (only '
     'whether the batch completes at all, or is killed for sitting idle, varies).')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('infra.compressed_hypertable_write_session.idle_session_timeout_ms', '0', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
