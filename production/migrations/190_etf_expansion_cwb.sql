-- production/migrations/190_etf_expansion_cwb.sql
-- Migration 190: add CWB (convertible bond ETF) — 79 → 80 instruments.
-- Follow-up to migration 188; CWB was identified after that migration ran.

BEGIN;

INSERT INTO tag_vocabulary (tag, category, description) VALUES
    ('convertible', 'exposure', 'Convertible bonds — hybrid equity-optionality/credit/duration exposure')
ON CONFLICT (tag) DO NOTHING;

INSERT INTO instruments (symbol, base, contract_details, is_active) VALUES
    ('CWB', 'CWB', '{"symbol":"CWB","base":"CWB","name":"SPDR Bloomberg Convertible Securities ETF","asset_class":"equity","exchange":"SMART","sector":"convertible","tick_size":0.01,"session_id":"nyse","point_value":1.0,"provider_meta":{}}', true)
ON CONFLICT (symbol) DO NOTHING;

INSERT INTO instrument_tags (symbol, tag, weight, source, evidence) VALUES
    ('CWB', 'convertible',        1.0, 'human', '{"reason": "diversified US convertible bond basket — equity optionality + credit + duration in one security"}'),
    ('CWB', 'benchmark',          1.0, 'human', '{"reason": "benchmark convertible bond ETF"}'),
    ('CWB', 'risk_on',            0.7, 'human', '{"reason": "convertibles participate in equity upside — risk-on tilt vs straight credit"}'),
    ('CWB', 'credit_risk',        0.6, 'human', '{"reason": "issuer credit quality affects convertible pricing alongside equity optionality"}'),
    ('CWB', 'spread_leg',         0.7, 'human', '{"reason": "CWB/LQD convertible vs straight-credit spread"}')
ON CONFLICT (symbol, tag) DO NOTHING;

COMMIT;
