# BIC K-Selection Study: HMM State Count

**Date:** 2026-06-26
**Symbols:** ['SPY', 'TLT', 'GLD', 'EWT']
**Timeframe:** 5m
**K range:** [2, 3, 4, 5, 6]

## BIC Table

| symbol | K | log_lik | n_obs | n_params | BIC | converged |
|--------|---|---------|-------|----------|-----|-----------|
| SPY | 2 | 11894860.96 | 469833 | 23 | -23789421.54 | True |
| SPY | 3 | 12138190.71 | 469833 | 38 | -24275885.14 | True |
| SPY | 4 | 12558377.64 | 469833 | 55 | -25116036.96 | True |
| SPY | 5 | 13052676.11 | 469833 | 74 | -26104385.77 | True |
| SPY | 6 | 12651655.84 | 469833 | 95 | -25302070.97 | True |
| TLT | 2 | 10225543.58 | 469635 | 23 | -20450786.78 | True |
| TLT | 3 | 10469903.16 | 469635 | 38 | -20939310.05 | True |
| TLT | 4 | 12596576.50 | 469635 | 55 | -25192434.71 | True |
| TLT | 5 | 12655961.90 | 469635 | 74 | -25310957.38 | True |
| TLT | 6 | 12066810.33 | 469635 | 95 | -24132380.00 | True |
| GLD | 2 | 10375799.16 | 469259 | 23 | -20751297.97 | True |
| GLD | 3 | 12558912.11 | 469259 | 38 | -25117327.97 | True |
| GLD | 4 | 12609710.86 | 469259 | 55 | -25218703.49 | True |
| GLD | 5 | 13079997.78 | 469259 | 74 | -26159029.19 | True |
| GLD | 6 | 12713539.38 | 469259 | 95 | -25425838.16 | True |
| EWT | 2 | 10359863.25 | 469259 | 23 | -20719426.15 | True |
| EWT | 3 | 12555097.32 | 469259 | 38 | -25109698.40 | True |
| EWT | 4 | 10784404.36 | 469259 | 55 | -21568090.49 | True |
| EWT | 5 | 13113389.72 | 469259 | 74 | -26225813.08 | True |
| EWT | 6 | 12121461.31 | 469259 | 95 | -24241682.02 | True |

## Winner per Symbol

- **SPY:** K=5 (BIC=-26104385.77)
- **TLT:** K=5 (BIC=-25310957.38)
- **GLD:** K=5 (BIC=-26159029.19)
- **EWT:** K=5 (BIC=-26225813.08)

## Final Decision

Winner distribution: {5: 4}

**DECISION: update K to 5**

Rationale: K=5 minimizes BIC across the majority of study symbols.
APR key `feature.hmm.n_components` updated to 5 via migration 176.
regime_writer re-run required to propagate new labels to feature_vectors.
