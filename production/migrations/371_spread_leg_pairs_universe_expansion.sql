-- Migration 371: spread_leg pair evidence for the 2026-09-26 universe expansion
--
-- universe_expansion_onboard_manifest.py tagged 16 new ETFs spread_leg with only a
-- {"reason": ...} evidence blob. Every spread_leg row must name its partner under
-- evidence->'pair', and the partner must name it back (migration 237, D-09; enforced by
-- tests/unit/test_spread_leg_pair_validity.py). This sets each new row's pair and adds the
-- reciprocal rows on the partners.
--
-- Pairs:
--   equal-weight vs cap-weight sector: RSPT/XLK RSPF/XLF RSPH/XLV RSPN/XLI RSPD/XLY
--     RSPS/XLP RSPM/XLB RSPR/XLRE RSPC/XLC, plus the already-held RSPG/XLE and RSPU/XLU,
--     so all 11 sectors pair (docs/ideas participation-state Part B)
--   concentration: QQEW/QQQ
--   style: IWN/IWO (Russell 2000 value vs growth)
--   vol term structure: VIXM/VIXY (front vs mid VIX futures)
--   size: IJH/SPY (mid vs large), IJR/IWM (S&P 600 profitability screen vs Russell 2000),
--     IWC/IWM (micro vs small)
--
-- instrument_tags is keyed (symbol, tag), so the 16 wrong blobs are corrected in place.
-- The partner inserts fail loudly on conflict rather than skip, since an existing partner
-- row would need its pair list merged by hand, as SPY's is below.

BEGIN;

UPDATE instrument_tags t
SET evidence = jsonb_build_object('pair', v.pair, 'reason', v.reason)
FROM (VALUES
    ('RSPT', 'XLK',  'RSPT/XLK equal- vs cap-weight technology spread'),
    ('RSPF', 'XLF',  'RSPF/XLF equal- vs cap-weight financials spread'),
    ('RSPH', 'XLV',  'RSPH/XLV equal- vs cap-weight health care spread'),
    ('RSPN', 'XLI',  'RSPN/XLI equal- vs cap-weight industrials spread'),
    ('RSPD', 'XLY',  'RSPD/XLY equal- vs cap-weight consumer discretionary spread'),
    ('RSPS', 'XLP',  'RSPS/XLP equal- vs cap-weight consumer staples spread'),
    ('RSPM', 'XLB',  'RSPM/XLB equal- vs cap-weight materials spread'),
    ('RSPR', 'XLRE', 'RSPR/XLRE equal- vs cap-weight real estate spread'),
    ('RSPC', 'XLC',  'RSPC/XLC equal- vs cap-weight communication services spread'),
    ('QQEW', 'QQQ',  'QQEW/QQQ equal- vs cap-weight Nasdaq-100 concentration spread'),
    ('IWN',  'IWO',  'IWN/IWO Russell 2000 value vs growth spread'),
    ('IWO',  'IWN',  'IWN/IWO Russell 2000 value vs growth spread'),
    ('VIXM', 'VIXY', 'VIXY/VIXM front vs mid VIX futures term-structure spread'),
    ('IJH',  'SPY',  'IJH/SPY mid vs large cap spread'),
    ('IJR',  'IWM',  'IJR/IWM S&P 600 profitability-screened vs Russell 2000 small cap spread'),
    ('IWC',  'IWM',  'IWC/IWM micro vs small cap spread')
) AS v(symbol, pair, reason)
WHERE t.symbol = v.symbol AND t.tag = 'spread_leg';

INSERT INTO instrument_tags (symbol, tag, weight, source, evidence)
SELECT v.symbol, 'spread_leg', 1.0, 'human', v.evidence::jsonb
FROM (VALUES
    ('XLK',  '{"pair": "RSPT", "reason": "RSPT/XLK equal- vs cap-weight technology spread (reciprocal of RSPT''s evidence)"}'),
    ('XLF',  '{"pair": "RSPF", "reason": "RSPF/XLF equal- vs cap-weight financials spread (reciprocal of RSPF''s evidence)"}'),
    ('XLV',  '{"pair": "RSPH", "reason": "RSPH/XLV equal- vs cap-weight health care spread (reciprocal of RSPH''s evidence)"}'),
    ('XLI',  '{"pair": "RSPN", "reason": "RSPN/XLI equal- vs cap-weight industrials spread (reciprocal of RSPN''s evidence)"}'),
    ('XLY',  '{"pair": "RSPD", "reason": "RSPD/XLY equal- vs cap-weight consumer discretionary spread (reciprocal of RSPD''s evidence)"}'),
    ('XLP',  '{"pair": "RSPS", "reason": "RSPS/XLP equal- vs cap-weight consumer staples spread (reciprocal of RSPS''s evidence)"}'),
    ('XLB',  '{"pair": "RSPM", "reason": "RSPM/XLB equal- vs cap-weight materials spread (reciprocal of RSPM''s evidence)"}'),
    ('XLRE', '{"pair": "RSPR", "reason": "RSPR/XLRE equal- vs cap-weight real estate spread (reciprocal of RSPR''s evidence)"}'),
    ('XLC',  '{"pair": "RSPC", "reason": "RSPC/XLC equal- vs cap-weight communication services spread (reciprocal of RSPC''s evidence)"}'),
    ('RSPG', '{"pair": "XLE", "reason": "RSPG/XLE equal- vs cap-weight energy spread"}'),
    ('XLE',  '{"pair": "RSPG", "reason": "RSPG/XLE equal- vs cap-weight energy spread (reciprocal of RSPG''s evidence)"}'),
    ('RSPU', '{"pair": "XLU", "reason": "RSPU/XLU equal- vs cap-weight utilities spread"}'),
    ('XLU',  '{"pair": "RSPU", "reason": "RSPU/XLU equal- vs cap-weight utilities spread (reciprocal of RSPU''s evidence)"}'),
    ('QQQ',  '{"pair": "QQEW", "reason": "QQEW/QQQ equal- vs cap-weight Nasdaq-100 concentration spread (reciprocal of QQEW''s evidence)"}'),
    ('VIXY', '{"pair": "VIXM", "reason": "VIXY/VIXM front vs mid VIX futures term-structure spread (reciprocal of VIXM''s evidence)"}'),
    ('IWM',  '{"pair": ["IJR", "IWC"], "reason": "Russell 2000 leg of the IJR/IWM and IWC/IWM size spreads (reciprocal of IJR/IWC evidence)"}')
) AS v(symbol, evidence);

UPDATE instrument_tags
SET evidence = jsonb_build_object(
    'pair', '["IPO", "EZU", "IJH"]'::jsonb,
    'reason', 'SPY is the broad-market spread leg for IPO (high-beta), EZU (US vs Europe) and IJH (mid vs large cap) pairs (reciprocal of IPO/EZU/IJH evidence)'
)
WHERE symbol = 'SPY' AND tag = 'spread_leg' AND evidence->'pair' = '["IPO", "EZU"]'::jsonb;

DO $$
BEGIN
    IF (SELECT evidence->'pair' FROM instrument_tags WHERE symbol = 'SPY' AND tag = 'spread_leg')
       <> '["IPO", "EZU", "IJH"]'::jsonb THEN
        RAISE EXCEPTION 'SPY spread_leg pair list was not ["IPO", "EZU"] before this migration; merge by hand';
    END IF;
    IF EXISTS (SELECT 1 FROM instrument_tags WHERE tag = 'spread_leg' AND NOT evidence ? 'pair') THEN
        RAISE EXCEPTION 'a spread_leg row still has no pair';
    END IF;
END $$;

COMMIT;
