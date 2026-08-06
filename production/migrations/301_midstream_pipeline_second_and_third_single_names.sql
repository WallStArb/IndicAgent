-- Migration 301: KMI/WMB -- second and third midstream single names, complementing EPD.
--
-- EPD (Enterprise Products Partners, migration 299) was the only midstream single-name
-- complement to AMLP's basket, leaving `commodity_energy_pipeline` at N=2 (AMLP + EPD).
-- User-requested addition (2026-08-05, after migration 299 shipped) closes the same
-- single-competitor-pair gap already applied elsewhere in this corpus (GM+F, CSX+UNP).
--
-- KMI (Kinder Morgan) and WMB (Williams Companies) are both added -- structural distinction
-- from EPD: EPD is a partnership (MLP, K-1 tax treatment, distinct unit-holder economics),
-- KMI and WMB are both C-corps (standard equity structure, 1099 treatment). KMI and WMB are
-- kept as separate additions on a real but modest asset-mix difference: KMI carries some
-- CO2/crude/refined-products terminal exposure alongside its gas pipeline network, WMB is
-- more concentrated in natural-gas gathering/processing (Transco system) with more direct
-- utility/power-generation demand exposure. Code review flagged this distinction as weaker
-- than presented -- both names are dominated by fee-based interstate gas transmission and
-- will show high realized correlation -- but no weaker than the already-accepted CSX+UNP/
-- MARA+RIOT precedent, so both are kept.
--
-- Also backfills EPD's `rate_sensitive` tag (migration 299 omitted it) -- code review caught
-- that the `commodity_energy_pipeline` peer group was inconsistently tagged: AMLP and the new
-- KMI/WMB rows all carry rate_sensitive, EPD did not.
--
-- contract_details mirrors the existing ETF/single-name shape; sector is a loose descriptive
-- string, not a formal classification (see migration 287/296/299's same convention).

BEGIN;

INSERT INTO instruments (symbol, base, contract_details, is_active) VALUES
    ('KMI', 'KMI', '{"symbol":"KMI","base":"KMI","name":"Kinder Morgan, Inc.","asset_class":"equity","exchange":"SMART","sector":"energy_midstream","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true),
    ('WMB', 'WMB', '{"symbol":"WMB","base":"WMB","name":"The Williams Companies, Inc.","asset_class":"equity","exchange":"SMART","sector":"energy_midstream","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true)
ON CONFLICT (symbol) DO NOTHING;

INSERT INTO instrument_tags (symbol, tag, weight, source, evidence) VALUES
    ('KMI', 'single_name_equity',        1.0, 'human', '{"reason": "individual company stock"}'),
    ('KMI', 'commodity_energy_pipeline', 0.9, 'human', '{"reason": "midstream pipeline C-corp -- largest CO2/natural-gas-pipeline-and-storage footprint plus crude/refined-products terminals, structurally distinct from EPD''s MLP/K-1 unit-holder economics"}'),
    ('KMI', 'defensive_yield',           0.7, 'human', '{"reason": "midstream -- stable fee-based cash flows, bond-like dividend yield, same family as EPD"}'),
    ('KMI', 'rate_sensitive',            0.5, 'human', '{"reason": "capital-intensive infrastructure with meaningful leverage -- moderate rate sensitivity"}'),

    ('WMB', 'single_name_equity',        1.0, 'human', '{"reason": "individual company stock"}'),
    ('WMB', 'commodity_energy_pipeline', 0.9, 'human', '{"reason": "midstream pipeline C-corp -- concentrated in natural-gas gathering/processing (Transco system) with larger direct utility/power-generation demand exposure, distinct asset mix from KMI and EPD"}'),
    ('WMB', 'defensive_yield',           0.7, 'human', '{"reason": "midstream -- stable fee-based cash flows, bond-like dividend yield, same family as EPD/KMI"}'),
    ('WMB', 'rate_sensitive',            0.5, 'human', '{"reason": "capital-intensive infrastructure with meaningful leverage -- moderate rate sensitivity"}'),

    ('EPD', 'rate_sensitive', 0.5, 'human', '{"reason": "backfilled -- migration 299 omitted this; code review caught the commodity_energy_pipeline peer group was inconsistently tagged (AMLP/KMI/WMB all carry it, EPD did not)"}')
ON CONFLICT (symbol, tag) DO NOTHING;

COMMIT;
