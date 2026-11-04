-- Migration 566: feature.hmm.n_components 5 -> 3 from the 583 refusal-rule study (todo 584 item 3,
-- design D6). One global value: the study's answer is uniform across timeframes, so no per-tf keys.
--
-- Rule, fixed before the run: for K in {3, 4, 5}, the K with the lowest share of refused
-- walk-forward segments (degenerate occupation), ties within two percentage points going to the
-- smaller K; fit validity only, never returns. Trend refused share, K3 / K4 / K5:
--   5m   6.2% / 7.9% / 17.0%      15m  1.3% / 3.5% / 12.0%      1h  1.5% / 5.5% / 9.6%
--   1d   K=3 from the 583 rule on complete data (decided earlier)
-- Volatility is K=2 at every timeframe (1h: 0.0% against K3 56.6%), which is the existing
-- alpha.hmm_volatility.n_components, so it is unchanged.
-- BIC disclosure: BIC prefers the grid edge K=6 on every timeframe, including 1d (380 of 437
-- names), so it does not bound K under these emissions and is uninformative here. Nothing was
-- judged on returns. The value change moves every stored trend regime label (a rebuild; the
-- 186-26 pin move covers it). Idempotent: the UPDATE and the history insert are guarded on the
-- value still being the old one.

BEGIN;

UPDATE config_schema
   SET description = '[583 refusal-rule study 2026-11-04, uniform across 1d/5m/15m/1h] Number of hidden states in the trend GaussianHMM: K=3 has the lowest share of refused walk-forward segments at every timeframe (5m 6.2% vs K4 7.9%, 15m 1.3% vs 3.5%, 1h 1.5% vs 5.5%; 1d from the rule on complete data). Replaced K=5 from the 2026-06-26 BIC study (migration 172); BIC prefers the grid edge K=6 everywhere and does not bound K here. Not an ML learning target (changes model topology, requires full retraining).'
 WHERE config_key = 'feature.hmm.n_components';

WITH moved AS (
    UPDATE config_state
       SET config_value = '3', version = version + 1
     WHERE config_key = 'feature.hmm.n_components' AND config_value <> '3'
    RETURNING config_key, version, config_value
)
INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), config_key, version, config_value, '583_refusal_rule_study',
       'K=3: lowest refused-segment share among K in {3,4,5} at every timeframe (rule fixed before the run, ties within 2 points to the smaller K): 5m 6.2% (K4 7.9%, K5 17.0%), 15m 1.3% (3.5%, 12.0%), 1h 1.5% (5.5%, 9.6%), 1d K=3 on complete data. Volatility stays K=2. BIC prefers K=6 everywhere and is uninformative here. todo 584 item 3.'
  FROM moved;

COMMIT;
