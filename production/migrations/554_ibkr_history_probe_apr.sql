-- Migration 554: APR seeds for the IBKR history-farm liveness probe (todo 538).
--
-- IBKRProvider.history_alive (src/providers/ibkr.py) asks for one 1d bar of a liquid name after a
-- history request fails without a definitive no-data answer. reqCurrentTime cannot serve: the
-- gateway session answers it while the history farm is dead (2026-11-01 evening, hours of 0-bar
-- answers with a healthy session). A failed probe raises ProviderSessionLost, which the fetcher
-- records as gateway_lost instead of retrying into a dead farm for the whole run. Read by
-- scripts/infrastructure/backfill/_history_fetch.py (_load_ibkr_rate_limit_config) onto
-- ibkr._HIST_PROBE_TIMEOUT_S / _HIST_PROBE_SYMBOL at fetcher startup. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'infra.ibkr.history_probe_timeout_s',
        'float',
        '60',
        5, 600,
        '[initial_estimate] Seconds the history-farm liveness probe (one 1d bar of infra.ibkr.history_probe_symbol) waits before the farm counts as dead and the run ends as gateway_lost (todo 538). Sits below the 90 s per-request timeout: a probe is one bar, but at fetch_concurrency 8 its answer queues behind large 5m payloads on the same socket, so a short value risks a false loss that ends a healthy run. Not an ML learning target.'
    ),
    (
        'infra.ibkr.history_probe_symbol',
        'str',
        'SPY',
        NULL, NULL,
        '[conventional] Liquid, always-trading name whose latest 1d bar the history-farm liveness probe requests (todo 538); SPY always has a daily bar and qualifies in one contract-details call. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('infra.ibkr.history_probe_timeout_s', '60', 1),
    ('infra.ibkr.history_probe_symbol', 'SPY', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), v.config_key, 1, v.config_value, 'migration_554', v.reason
  FROM (VALUES
        ('infra.ibkr.history_probe_timeout_s', '60',
         'seed: history-farm liveness probe timeout (todo 538)'),
        ('infra.ibkr.history_probe_symbol', 'SPY',
         'seed: history-farm liveness probe name (todo 538)')
       ) AS v(config_key, config_value, reason)
 WHERE NOT EXISTS (
        SELECT 1 FROM config_history h
         WHERE h.config_key = v.config_key AND h.changed_by = 'migration_554'
       );

COMMIT;
