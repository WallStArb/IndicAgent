-- Migration 121: instrument tag vocabulary v2
--
-- Restructures tag_vocabulary from 4 categories to 6:
--   exposure      — what the instrument IS (unchanged)
--   sensitivity   — how it responds to factor moves (split from regime)
--   factor_regime — conditional performance in factor regimes (split from regime)
--   cycle_position — economic cycle phase priors (new; definitional human seeds)
--   signal_role   — how it functions in the portfolio (unchanged + breadth moved here)
--   macro_driver  — primary macro force driving it (unchanged + geopolitical added)
--
-- Vocabulary cleanups:
--   miners   → dropped (covered by eq_sub_sector); GDX gets eq_sub_sector
--   dividend → renamed eq_income (income strategy, not asset class)
--   breadth  → moved regime → signal_role
--   speculative → dropped (all instruments already carry sentiment)
--   geopolitical → added to macro_driver
--   early_cycle / mid_cycle / late_cycle / recession → added as cycle_position

-- ── 1. Drop existing CHECK constraint, update categories, re-add ───────────────

ALTER TABLE tag_vocabulary DROP CONSTRAINT tag_vocabulary_category_check;

-- ── 2. Split regime → sensitivity + factor_regime ──────────────────────────────

UPDATE tag_vocabulary
SET    category = 'sensitivity'
WHERE  tag IN ('rate_sensitive', 'credit_risk', 'inflation', 'yield_curve', 'volatility');

UPDATE tag_vocabulary
SET    category = 'factor_regime'
WHERE  tag IN ('risk_on', 'risk_off', 'defensive', 'growth', 'value', 'momentum');

-- ── 3. Move breadth → signal_role ─────────────────────────────────────────────

UPDATE tag_vocabulary SET category = 'signal_role' WHERE tag = 'breadth';

-- ── 1b. Add new CHECK constraint (after all existing rows updated) ─────────────

ALTER TABLE tag_vocabulary ADD CONSTRAINT tag_vocabulary_category_check
    CHECK (category IN (
        'exposure',
        'sensitivity',
        'factor_regime',
        'cycle_position',
        'signal_role',
        'macro_driver'
    ));

-- ── 4. Drop speculative (instruments already carry sentiment) ──────────────────

DELETE FROM instrument_tags  WHERE tag = 'speculative';
DELETE FROM tag_vocabulary   WHERE tag = 'speculative';

-- ── 5. Drop miners — GDX → eq_sub_sector ──────────────────────────────────────

DELETE FROM instrument_tags  WHERE tag = 'miners';
DELETE FROM tag_vocabulary   WHERE tag = 'miners';

INSERT INTO instrument_tags (symbol, tag, weight, source)
VALUES ('GDX', 'eq_sub_sector', 1.0, 'human')
ON CONFLICT (symbol, tag) DO NOTHING;

-- ── 6. Rename dividend → eq_income ────────────────────────────────────────────

-- FK: instrument_tags.tag → tag_vocabulary.tag
-- Must update child rows first (or defer; simpler to update together via NO ACTION deferral)
-- tag_vocabulary PK, instrument_tags FK — update vocabulary first then referencing rows
-- PostgreSQL: FK is IMMEDIATE by default; rename via temp then swap

ALTER TABLE instrument_tags  DROP CONSTRAINT instrument_tags_tag_fkey;

UPDATE tag_vocabulary   SET tag = 'eq_income',  description = 'Income-oriented equity strategy — high dividend yield, quality screen'
WHERE tag = 'dividend';

UPDATE instrument_tags  SET tag = 'eq_income'   WHERE tag = 'dividend';

ALTER TABLE instrument_tags
    ADD CONSTRAINT instrument_tags_tag_fkey
    FOREIGN KEY (tag) REFERENCES tag_vocabulary(tag);

-- ── 7. Add geopolitical macro_driver ──────────────────────────────────────────

INSERT INTO tag_vocabulary (tag, category, description) VALUES
('geopolitical', 'macro_driver', 'Driven by geopolitical risk — defense budgets, conflict escalation, sanctions');

INSERT INTO instrument_tags (symbol, tag, weight, source) VALUES
('ITA',  'geopolitical', 1.0, 'human'),   -- defense is the primary driver
('IBIT', 'geopolitical', 0.6, 'human'),   -- sanctions avoidance / geopolitical hedge narrative
('GLD',  'geopolitical', 0.7, 'human'),   -- safe haven on escalation
('CIBR', 'geopolitical', 0.8, 'human');   -- cyber threat budgets are geopolitically driven

-- ── 8. Add cycle_position tags ─────────────────────────────────────────────────

INSERT INTO tag_vocabulary (tag, category, description) VALUES
('early_cycle',  'cycle_position', 'Outperforms in early economic expansion — credit-driven, domestically exposed'),
('mid_cycle',    'cycle_position', 'Outperforms in mid-cycle growth — earnings-driven, capex and tech spending'),
('late_cycle',   'cycle_position', 'Outperforms in late expansion — commodity prices elevated, margins peak'),
('recession',    'cycle_position', 'Outperforms in contraction — defensive cash flows, flight to quality');

-- Early cycle: small cap, consumer discretionary, industrials, materials, financials, housing, retail
INSERT INTO instrument_tags (symbol, tag, weight, source) VALUES
('IWM',  'early_cycle', 0.9, 'human'),
('XLY',  'early_cycle', 0.8, 'human'),
('XLF',  'early_cycle', 0.7, 'human'),
('XLI',  'early_cycle', 0.8, 'human'),
('XLB',  'early_cycle', 0.7, 'human'),
('XRT',  'early_cycle', 0.7, 'human'),
('XHB',  'early_cycle', 0.8, 'human'),
('KRE',  'early_cycle', 0.7, 'human');

-- Mid cycle: tech, comms, semiconductors, software
INSERT INTO instrument_tags (symbol, tag, weight, source) VALUES
('XLK',  'mid_cycle', 0.8, 'human'),
('XLC',  'mid_cycle', 0.7, 'human'),
('SMH',  'mid_cycle', 0.8, 'human'),
('IGV',  'mid_cycle', 0.8, 'human'),
('QQQ',  'mid_cycle', 0.7, 'human');

-- Late cycle: energy, healthcare, gold, oil services, pipelines
INSERT INTO instrument_tags (symbol, tag, weight, source) VALUES
('XLE',  'late_cycle', 0.8, 'human'),
('XLV',  'late_cycle', 0.7, 'human'),
('GLD',  'late_cycle', 0.7, 'human'),
('XOP',  'late_cycle', 0.7, 'human'),
('OIH',  'late_cycle', 0.7, 'human'),
('AMLP', 'late_cycle', 0.7, 'human'),
('SLV',  'late_cycle', 0.6, 'human');

-- Recession: staples, utilities, treasuries, gold, cash, min-vol, quality
INSERT INTO instrument_tags (symbol, tag, weight, source) VALUES
('XLP',  'recession', 0.9, 'human'),
('XLU',  'recession', 0.9, 'human'),
('XLV',  'recession', 0.7, 'human'),
('TLT',  'recession', 0.9, 'human'),
('IEF',  'recession', 0.8, 'human'),
('SHY',  'recession', 0.8, 'human'),
('BIL',  'recession', 0.9, 'human'),
('GLD',  'recession', 0.8, 'human'),
('USMV', 'recession', 0.8, 'human'),
('QUAL', 'recession', 0.7, 'human'),
('AGG',  'recession', 0.7, 'human');
