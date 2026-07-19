-- Migration 233: Controlled Vocabulary - seed 6 live namespaces + vocabulary groups
-- (phase 161, plan 161-01)
--
-- NUMBERING NOTE: plan 161-01 originally specified migration number 238 for this seed
-- migration (paired with schema migration 237). Both were already taken by the time this
-- plan executed (Phase 146 shipped two migrations at those numbers on 2026-07-17). This
-- migration uses the next free integer after its schema companion (239), per the plan's own
-- fallback instruction ("if taken, use the next free integer and note it in the SUMMARY").
--
-- Seeds exactly the six live namespaces per CONTEXT.md D-01 (revised 2026-07-16 per
-- docs/research/fable-2026-07-16-controlled-vocabulary-open-questions-review.md finding V1):
-- the live `market_regimes.regime_label` column carries two independent taxonomies
-- (regime_group='equity': 9 labels, regime_group='rates': 6 labels, a different curve-shape x
-- width shape) sharing one column. One namespace mixing both would violate the Label Identity
-- Invariant and recreate the pre-141.1 feature_ic_scores.regime mixing bug inside the registry
-- meant to prevent it - so this migration seeds regime_cross_sectional_equity and
-- regime_cross_sectional_rates as two sibling namespaces, not one.
--
--   regime_hmm                       - 5 codes (feature_vectors.regime, per-symbol HMM)
--   regime_cross_sectional_equity    - 9 codes (market_regimes, regime_group='equity')
--   regime_cross_sectional_rates     - 6 codes (market_regimes, regime_group='rates')
--   timeframe                        - 5 codes (market_data_ohlcv.timeframe)
--   asset_class                      - 3 codes (instruments.contract_details->>'asset_class')
--   tier                             - 3 codes (feature_registry.tier) - CONTEXT.md's
--     code_context section notes "2 live values" but that snapshot is stale; RESEARCH.md
--     Critical Finding 2 and 161-PATTERNS.md both confirm 3 live values
--     (0_atomic=135, 1_interaction=8, 2_theory=12), re-verified live during this migration's
--     authoring. Seed all 3.
--
-- Archived-SLA namespaces (signal_outcome, entry_type, signal_status, session_type) are
-- explicitly deferred per the design doc's "on demand later" staging - not seeded here.
--
-- Vocabulary groups per CONTEXT.md D-03/D-04/D-04b:
--   regime_hmm: two independent overlapping groupings (trending/transition,
--     bullish_bias/bearish_bias) - not a single ordered scale. `ranging` stays ungrouped.
--   regime_cross_sectional_equity: two crossed facets - vol-tier (low/mid/high_vol) and
--     direction (bull/neutral/bear) - every code belongs to exactly one of each.
--   regime_cross_sectional_rates: two crossed facets - curve-shape (flat/steep/inverted) and
--     width (tight/wide) - every code belongs to exactly one of each.
--
-- All statements idempotent: every INSERT uses ON CONFLICT DO NOTHING on the natural composite
-- key. Safe to re-run.

BEGIN;

-- ── regime_hmm (5 codes, ordered by emission mean) ─────────────────────────────

INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order) VALUES
('regime_hmm', 'trending_down',   'Trending Down',   'Strong sustained downward price movement (lowest emission-mean HMM state)', 1),
('regime_hmm', 'transition_down', 'Transition Down',  'Weakening or early-stage downward movement between ranging and trending_down', 2),
('regime_hmm', 'ranging',         'Ranging',           'No sustained directional movement; mean-reverting price action', 3),
('regime_hmm', 'transition_up',   'Transition Up',     'Weakening or early-stage upward movement between ranging and trending_up', 4),
('regime_hmm', 'trending_up',     'Trending Up',       'Strong sustained upward price movement (highest emission-mean HMM state)', 5)
ON CONFLICT (namespace, code) DO NOTHING;

-- ── regime_cross_sectional_equity (9 codes) ────────────────────────────────────

INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order) VALUES
('regime_cross_sectional_equity', 'low_bull',     'Low Vol / Bull',     'Low cross-sectional volatility, bullish breadth', 1),
('regime_cross_sectional_equity', 'low_neutral',  'Low Vol / Neutral',  'Low cross-sectional volatility, neutral breadth', 2),
('regime_cross_sectional_equity', 'low_bear',     'Low Vol / Bear',     'Low cross-sectional volatility, bearish breadth', 3),
('regime_cross_sectional_equity', 'mid_bull',     'Mid Vol / Bull',     'Mid cross-sectional volatility, bullish breadth', 4),
('regime_cross_sectional_equity', 'mid_neutral',  'Mid Vol / Neutral',  'Mid cross-sectional volatility, neutral breadth', 5),
('regime_cross_sectional_equity', 'mid_bear',     'Mid Vol / Bear',     'Mid cross-sectional volatility, bearish breadth', 6),
('regime_cross_sectional_equity', 'high_bull',    'High Vol / Bull',    'High cross-sectional volatility, bullish breadth', 7),
('regime_cross_sectional_equity', 'high_neutral', 'High Vol / Neutral', 'High cross-sectional volatility, neutral breadth', 8),
('regime_cross_sectional_equity', 'high_bear',    'High Vol / Bear',    'High cross-sectional volatility, bearish breadth', 9)
ON CONFLICT (namespace, code) DO NOTHING;

-- ── regime_cross_sectional_rates (6 codes) ─────────────────────────────────────

INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order) VALUES
('regime_cross_sectional_rates', 'flat_tight',     'Flat / Tight',     'Flat yield curve, tight credit spreads', 1),
('regime_cross_sectional_rates', 'flat_wide',      'Flat / Wide',      'Flat yield curve, wide credit spreads', 2),
('regime_cross_sectional_rates', 'steep_tight',    'Steep / Tight',    'Steep yield curve, tight credit spreads', 3),
('regime_cross_sectional_rates', 'steep_wide',     'Steep / Wide',     'Steep yield curve, wide credit spreads', 4),
('regime_cross_sectional_rates', 'inverted_tight', 'Inverted / Tight', 'Inverted yield curve, tight credit spreads', 5),
('regime_cross_sectional_rates', 'inverted_wide',  'Inverted / Wide',  'Inverted yield curve, wide credit spreads', 6)
ON CONFLICT (namespace, code) DO NOTHING;

-- ── timeframe (5 codes) ─────────────────────────────────────────────────────────

INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order) VALUES
('timeframe', '1m',  '1 Minute',   'One-minute bar timeframe', 1),
('timeframe', '5m',  '5 Minute',   'Five-minute bar timeframe', 2),
('timeframe', '15m', '15 Minute',  'Fifteen-minute bar timeframe', 3),
('timeframe', '1h',  '1 Hour',     'One-hour bar timeframe', 4),
('timeframe', '1d',  '1 Day',      'One-day bar timeframe', 5)
ON CONFLICT (namespace, code) DO NOTHING;

-- ── asset_class (3 codes) ───────────────────────────────────────────────────────

INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order) VALUES
('asset_class', 'equity',  'Equity',  'Exchange-traded equity/ETF instrument', 1),
('asset_class', 'futures', 'Futures', 'Exchange-traded futures contract', 2),
('asset_class', 'fx',      'FX',      'Foreign exchange spot/forward instrument', 3)
ON CONFLICT (namespace, code) DO NOTHING;

-- ── tier (3 codes) ────────────────────────────────────────────────────────────
-- Seed all 3 live feature_registry.tier values - the "2 live values" note in CONTEXT.md's
-- code_context section is a stale snapshot; re-verified live as 0_atomic=135,
-- 1_interaction=8, 2_theory=12 during this migration's authoring.

INSERT INTO controlled_vocabulary (namespace, code, label, description, sort_order) VALUES
('tier', '0_atomic',      'Atomic',      'Base-level computed feature with no dependency on other features', 1),
('tier', '1_interaction', 'Interaction', 'Feature derived from an interaction between two or more atomic features', 2),
('tier', '2_theory',      'Theory',      'Feature encoding a higher-level theoretical construct', 3)
ON CONFLICT (namespace, code) DO NOTHING;

-- ── vocabulary_group: regime_hmm (D-03) ─────────────────────────────────────────
-- Two independent overlapping groupings, not a single ordered scale. `ranging` stays
-- ungrouped (a group of one adds no query value).

INSERT INTO vocabulary_group (namespace, group_name, label, description, sort_order) VALUES
('regime_hmm', 'trending',     'Trending',      'Either trending direction (excludes transition and ranging states)', 1),
('regime_hmm', 'transition',   'Transition',    'Either transition direction (excludes trending and ranging states)', 2),
('regime_hmm', 'bullish_bias', 'Bullish Bias',  'States with upward directional bias (transition_up or trending_up)', 3),
('regime_hmm', 'bearish_bias', 'Bearish Bias',  'States with downward directional bias (transition_down or trending_down)', 4)
ON CONFLICT (namespace, group_name) DO NOTHING;

INSERT INTO vocabulary_group_member (namespace, group_name, code) VALUES
('regime_hmm', 'trending',     'trending_down'),
('regime_hmm', 'trending',     'trending_up'),
('regime_hmm', 'transition',   'transition_down'),
('regime_hmm', 'transition',   'transition_up'),
('regime_hmm', 'bullish_bias', 'transition_up'),
('regime_hmm', 'bullish_bias', 'trending_up'),
('regime_hmm', 'bearish_bias', 'transition_down'),
('regime_hmm', 'bearish_bias', 'trending_down')
ON CONFLICT (namespace, group_name, code) DO NOTHING;

-- ── vocabulary_group: regime_cross_sectional_equity (D-04) ─────────────────────
-- Two crossed facets - vol-tier and direction. Every code belongs to exactly one of each.

INSERT INTO vocabulary_group (namespace, group_name, label, description, sort_order) VALUES
('regime_cross_sectional_equity', 'low_vol',  'Low Volatility',  'Low cross-sectional volatility tier (all directions)', 1),
('regime_cross_sectional_equity', 'mid_vol',  'Mid Volatility',  'Mid cross-sectional volatility tier (all directions)', 2),
('regime_cross_sectional_equity', 'high_vol', 'High Volatility', 'High cross-sectional volatility tier (all directions)', 3),
('regime_cross_sectional_equity', 'bull',     'Bull',            'Bullish breadth direction (all volatility tiers)', 4),
('regime_cross_sectional_equity', 'neutral',  'Neutral',         'Neutral breadth direction (all volatility tiers)', 5),
('regime_cross_sectional_equity', 'bear',     'Bear',            'Bearish breadth direction (all volatility tiers)', 6)
ON CONFLICT (namespace, group_name) DO NOTHING;

INSERT INTO vocabulary_group_member (namespace, group_name, code) VALUES
('regime_cross_sectional_equity', 'low_vol',  'low_bull'),
('regime_cross_sectional_equity', 'low_vol',  'low_neutral'),
('regime_cross_sectional_equity', 'low_vol',  'low_bear'),
('regime_cross_sectional_equity', 'mid_vol',  'mid_bull'),
('regime_cross_sectional_equity', 'mid_vol',  'mid_neutral'),
('regime_cross_sectional_equity', 'mid_vol',  'mid_bear'),
('regime_cross_sectional_equity', 'high_vol', 'high_bull'),
('regime_cross_sectional_equity', 'high_vol', 'high_neutral'),
('regime_cross_sectional_equity', 'high_vol', 'high_bear'),
('regime_cross_sectional_equity', 'bull',     'low_bull'),
('regime_cross_sectional_equity', 'bull',     'mid_bull'),
('regime_cross_sectional_equity', 'bull',     'high_bull'),
('regime_cross_sectional_equity', 'neutral',  'low_neutral'),
('regime_cross_sectional_equity', 'neutral',  'mid_neutral'),
('regime_cross_sectional_equity', 'neutral',  'high_neutral'),
('regime_cross_sectional_equity', 'bear',     'low_bear'),
('regime_cross_sectional_equity', 'bear',     'mid_bear'),
('regime_cross_sectional_equity', 'bear',     'high_bear')
ON CONFLICT (namespace, group_name, code) DO NOTHING;

-- ── vocabulary_group: regime_cross_sectional_rates (D-04b) ─────────────────────
-- Two crossed facets - curve-shape and width. Every code belongs to exactly one of each.

INSERT INTO vocabulary_group (namespace, group_name, label, description, sort_order) VALUES
('regime_cross_sectional_rates', 'flat',     'Flat',     'Flat yield curve shape (both spread widths)', 1),
('regime_cross_sectional_rates', 'steep',    'Steep',    'Steep yield curve shape (both spread widths)', 2),
('regime_cross_sectional_rates', 'inverted', 'Inverted', 'Inverted yield curve shape (both spread widths)', 3),
('regime_cross_sectional_rates', 'tight',    'Tight',    'Tight credit spread width (all curve shapes)', 4),
('regime_cross_sectional_rates', 'wide',     'Wide',     'Wide credit spread width (all curve shapes)', 5)
ON CONFLICT (namespace, group_name) DO NOTHING;

INSERT INTO vocabulary_group_member (namespace, group_name, code) VALUES
('regime_cross_sectional_rates', 'flat',     'flat_tight'),
('regime_cross_sectional_rates', 'flat',     'flat_wide'),
('regime_cross_sectional_rates', 'steep',    'steep_tight'),
('regime_cross_sectional_rates', 'steep',    'steep_wide'),
('regime_cross_sectional_rates', 'inverted', 'inverted_tight'),
('regime_cross_sectional_rates', 'inverted', 'inverted_wide'),
('regime_cross_sectional_rates', 'tight',    'flat_tight'),
('regime_cross_sectional_rates', 'tight',    'steep_tight'),
('regime_cross_sectional_rates', 'tight',    'inverted_tight'),
('regime_cross_sectional_rates', 'wide',     'flat_wide'),
('regime_cross_sectional_rates', 'wide',     'steep_wide'),
('regime_cross_sectional_rates', 'wide',     'inverted_wide')
ON CONFLICT (namespace, group_name, code) DO NOTHING;

COMMIT;
