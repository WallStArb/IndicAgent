-- Migration 314: APR-back a statement_timeout override for
-- compressed_hypertable_write_session / async_compressed_hypertable_write_session
--
-- Confirmed live 2026-08-14: regime_writer.py's relaunch hit a fatal_error
-- ("canceling statement due to statement timeout") on its very first decompress_chunk()
-- call, 30 minutes in, with zero rows written. compressed_hypertable_write_session opens
-- its decompress-all-chunks step on a connection that inherits the role/database default
-- statement_timeout (SHOW statement_timeout => 30min) -- fine for interactive/API
-- queries, wrong for this function's own stated purpose (bracketing a long batch write
-- against a compressed hypertable). Made materially worse by a self-reinforcing cycle
-- this session also diagnosed live: every failed 30-minute attempt leaves dead-tuple
-- bloat behind, which recruits more autovacuum workers onto the same hypertable's
-- chunks (7 concurrent, then 10, observed climbing across two consecutive failed
-- attempts), which slows the next attempt's decompress further, which fails the same
-- way. A generous, explicit override breaks the cycle by giving the legitimate one-time
-- decompress/write/recompress+VACUUM sequence enough wall-clock room to actually
-- finish under realistic contention, instead of a cap tuned for unrelated interactive
-- queries silently applying to a batch job that was never its target.

BEGIN;

INSERT INTO config_schema (config_key, value_type, description) VALUES
    ('infra.compressed_hypertable_write_session.statement_timeout_ms', 'int',
     '[rca_analysis] statement_timeout (milliseconds) applied for the duration of '
     'compressed_hypertable_write_session / async_compressed_hypertable_write_session '
     '(services/_batch_utils.py), overriding the role/database default (30min) that is '
     'tuned for interactive/API queries, not this function''s own long batch decompress/ '
     'write/recompress+VACUUM sequence. Restored to the connection''s prior value on '
     'exit. Not an ML learning target -- pure infrastructure timeout knob, output is '
     'invariant to this value (only whether the batch completes at all, or fails with '
     'more wall-clock margin, varies).')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('infra.compressed_hypertable_write_session.statement_timeout_ms', '14400000', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
