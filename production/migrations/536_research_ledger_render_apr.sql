-- Migration 536: APR seed for the research ledger render job (phase 187 plan 13 Task 3,
-- scripts/research/render_research_ledger.py).
--
-- infra.research_ledger_render.git_lock_retries: how many times the nightly render retries its
-- one `git commit` when .git/index.lock is held (the shared checkout has concurrent sessions).
-- 5 = [initial_estimate] a lock is held for seconds by a peer commit or pre-commit run; with a
-- 2 s wait between tries, 5 tries span about 10 s, so a busy minute is skipped (the next night
-- renders again) rather than waited out. Not an ML learning target. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'infra.research_ledger_render.git_lock_retries',
        'int',
        '5',
        0, 30,
        '[initial_estimate] research_ledger_render: retries of its single git commit when .git/index.lock is held, 2 s apart. 5 spans about 10 s; a longer hold skips the night and the next render commits the same text. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('infra.research_ledger_render.git_lock_retries', '5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), 'infra.research_ledger_render.git_lock_retries', 1, '5', 'migration_536',
       'seed: research ledger render git lock retries (plan 187-13)'
WHERE NOT EXISTS (
    SELECT 1 FROM config_history h
    WHERE h.config_key = 'infra.research_ledger_render.git_lock_retries'
);

COMMIT;
