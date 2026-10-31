# HMM regime audit and optimization plan

Original: 2026-06-28, updated 2026-06-29 (status OPEN; P0-P3 ready to implement, P4 gated).
Archived 2026-10-31: pre-unified audit, kept for the open findings.

Findings worth keeping: the cross-sectional VIX proxy ranked each bar against the full
corpus including future observations (look-ahead; fix is expanding().rank(pct=True));
vol/VIX/breadth windows were raw bar counts whose economic meaning changes per timeframe
(define in days, derive bar counts); single GaussianHMM EM initialization risks local optima
(run N restarts with derived seeds, select by log-likelihood). What was already right: causal
forward-filter decoding without Viterbi, the 5D observation vector, K=5 BIC-validated,
diagonal covariance, APR-backed random state.

Full text in git history at docs/plans/2026-06-28-hmm-regime-audit-optimization.md as of 708f3fe09.
