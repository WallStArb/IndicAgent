-- Migration 436: exposure tag for the managed-futures funds in the 2026-10-03 ETF batch
--
-- config/universe/wave2_etfs_2026_10_03.csv adds DBMF, KMLM and CTA, trend-following funds
-- that hold diversified futures long and short. No existing exposure tag describes them:
-- factor_market_neutral claims near-zero equity beta by construction, which a trend fund does
-- not. Additive only: no existing tag, node or assignment changes. A re-run is a no-op.

BEGIN;

INSERT INTO tag_vocabulary (tag, category, description, measurement_type)
VALUES
    ('managed_futures', 'exposure',
     'Systematic long-short futures strategy across asset classes (trend following)',
     'definitional')
ON CONFLICT (tag) DO NOTHING;

COMMIT;
