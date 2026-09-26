-- Migration 373: spread_leg pairs for the commodity curve funds of the 2026-09-26 ETF expansion
--
-- USO/USL (WTI front month vs a 12-month strip) and UNG/UNL (Henry Hub, same construction)
-- measure each curve's front-to-12-month slope from daily bars, the way VIXY/VIXM does for VIX
-- futures: the carry signal the basket funds (DBC, GSG) blend away. The manifest cannot express
-- a pair, so the reciprocal spread_leg rows are written here (migration 237, D-09; enforced by
-- tests/unit/test_spread_leg_pair_validity.py). Runs after the four funds are onboarded.

BEGIN;

INSERT INTO instrument_tags (symbol, tag, weight, source, evidence)
SELECT v.symbol, 'spread_leg', 1.0, 'human', v.evidence::jsonb
FROM (VALUES
    ('USO', '{"pair": "USL", "reason": "USO/USL WTI front-month vs 12-month strip curve-slope spread"}'),
    ('USL', '{"pair": "USO", "reason": "USO/USL WTI front-month vs 12-month strip curve-slope spread (reciprocal of USO''s evidence)"}'),
    ('UNG', '{"pair": "UNL", "reason": "UNG/UNL natural gas front-month vs 12-month strip curve-slope spread"}'),
    ('UNL', '{"pair": "UNG", "reason": "UNG/UNL natural gas front-month vs 12-month strip curve-slope spread (reciprocal of UNG''s evidence)"}')
) AS v(symbol, evidence);

COMMIT;
