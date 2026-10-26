-- 511: alpaca's nightly capture moves its recent tail to feed=iex (todo 521 reopen, 2026-10-26).
-- The free plan now 403s recent SIP data. Measured live 2026-10-26: a bars request whose end
-- reaches within about 15 minutes of now on feed=sip answers
-- 403 {"message":"subscription does not permit querying recent SIP data"}
-- while feed=iex answers the same tail (thin: SPY 5m n=1 vs SIP n=2428, volume basis differs).
-- Two seeds: the APR key the nightly reads to pick its feed, and the bar_kind code the iex
-- rows must carry so raw never labels an IEX answer as sip_rth. Not an ML learning target.
-- Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('infra.alpaca.data_feed', 'string', 'iex', NULL, NULL,
 '[rca_analysis] The market data feed the alpaca capture leaves ask (scripts/ops/bars/ops_bar_nightly.py via AlpacaProvider). Free-plan Alpaca rejects recent SIP data (measured live 2026-10-26: a bars window reaching within ~15 minutes of now on feed=sip answers 403 "subscription does not permit querying recent SIP data"), so the nightly''s recent tail is asked on iex. IEX volume is a thin, differently-based answer (SPY 5m tail n=1 vs sip n=2428); rows written from it carry bar_kind iex_rth, never sip_rth. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.alpaca.data_feed', 'iex', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_511',
       'todo 521 reopen: free plan 403s recent SIP data; nightly tail moves to feed=iex'
  FROM config_state
 WHERE config_key = 'infra.alpaca.data_feed'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_511');

-- The raw kind an iex-feed answer carries (mirrors src/intelligence/bars/vendor_kind.py
-- BAR_KINDS; sort_order follows sip_rth so a slot holding both keeps sip_rth the winner).
INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order)
VALUES
    ('bar_kind', 'iex_rth', 'iex_rth',
     'Alpaca IEX aggregate over the regular trading hours window', 12)
ON CONFLICT (namespace, code) DO NOTHING;

COMMIT;
