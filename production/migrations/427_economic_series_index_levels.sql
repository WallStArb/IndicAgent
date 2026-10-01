-- Migration 427: long-history index levels as context-only economic series (todo 480 extension)
--
-- Owner decision 2026-10-01: store long daily index history the bars cannot provide (IBKR history
-- starts at listing-era limits; tests of equity behavior before 2006 need more), as economic series
-- marked context only, never a tradeable price (the todo 428 Yahoo precedent). Adds:
--   yahoo  ^GSPC (S&P 500, from 1927), ^NDX (Nasdaq 100, from 1985): YahooSource, index tickers only
--   fred   NASDAQCOM (Nasdaq Composite, from 1971); NASDAQ100 (from 1986) and SP500 (last ten years)
--          as second sources, so the Yahoo series reconcile on their overlap
-- The Dow is left out: no free source serves it before 1992, and the S&P 500 covers US large caps.
-- Index levels are price-only (no dividends); a total-return use must say so in its spec.
--
-- Guarded: the list update runs only while ^GSPC is absent, so a rerun changes nothing and writes no
-- second history row. Migration 423 is applied and not edited.

BEGIN;

ALTER TABLE economic_series_observation
    DROP CONSTRAINT IF EXISTS economic_series_observation_source_check;
ALTER TABLE economic_series_observation
    ADD CONSTRAINT economic_series_observation_source_check
    CHECK (source IN ('fred', 'nyfed', 'yahoo'));

WITH updated AS (
    UPDATE config_state
    SET config_value = (
            config_value::jsonb
            || '[{"source": "yahoo", "series_id": "^GSPC", "revision": "none", "consumer": "long_history_equity_context"},
                 {"source": "yahoo", "series_id": "^NDX", "revision": "none", "consumer": "long_history_equity_context"},
                 {"source": "fred", "series_id": "NASDAQCOM", "revision": "none", "consumer": "long_history_equity_context"},
                 {"source": "fred", "series_id": "NASDAQ100", "revision": "none", "consumer": "index_level_reconciliation"},
                 {"source": "fred", "series_id": "SP500", "revision": "none", "consumer": "index_level_reconciliation"}]'::jsonb
        )::text,
        version = version + 1,
        updated_at = NOW()
    WHERE config_key = 'infra.economic_series.sources'
      AND NOT config_value::jsonb @> '[{"series_id": "^GSPC"}]'::jsonb
    RETURNING config_key, config_value, version
)
INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, version, config_value, 'migration_427',
       'Added long-history index levels (owner decision 2026-10-01): Yahoo ^GSPC, ^NDX; FRED NASDAQCOM, NASDAQ100, SP500'
FROM updated;

UPDATE config_schema
SET description = replace(description, 'source is fred (series_id is the FRED id) or nyfed',
                          'source is fred (series_id is the FRED id), yahoo (an index ticker, context only, never a tradeable price) or nyfed')
WHERE config_key = 'infra.economic_series.sources';

COMMIT;
