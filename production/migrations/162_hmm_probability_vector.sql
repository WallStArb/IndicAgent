-- Migration 162: Add raw HMM forward-filter probability columns to feature_vectors.
--
-- Ground truth alpha vector from the causal forward-filter pass:
--   hmm_prob_trending_up   = P(state=trending_up   | obs[0..t])
--   hmm_prob_ranging       = P(state=ranging        | obs[0..t])
--   hmm_prob_trending_down = P(state=trending_down  | obs[0..t])
--
-- These three columns sum to 1.0 per bar (within float precision).
-- They are stored as separate typed DOUBLE PRECISION columns (not JSONB)
-- so the IC engine can treat them as direct numeric features.
--
-- Derivatives already stored in prior schema:
--   hmm_regime_prob = max(alpha)           -- confidence in the decoded state
--   hmm_entropy     = -sum(p * log(p))     -- uncertainty in the decoded state
--   hmm_duration    = consecutive bars in same state
--
-- NOT stored: hmm_direction_score = P(up) - P(down) — trivially derivable at query time.
--
-- Populated by regime_writer.py alongside the regime text label.
-- Idempotent: IF NOT EXISTS guards make re-application safe.

ALTER TABLE feature_vectors
    ADD COLUMN IF NOT EXISTS hmm_prob_trending_up   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hmm_prob_ranging        DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS hmm_prob_trending_down  DOUBLE PRECISION;
