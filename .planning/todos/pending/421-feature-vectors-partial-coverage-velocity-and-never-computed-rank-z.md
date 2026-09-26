

## Unified design note (2026-09-26)

The phase 186 `feature_vectors` rebuild recomputes every feature for every symbol, which removes the partial-coverage and never-computed classes at the source; the per-feature coverage floor in S0 (todo 435) and the rebuild's drift report keep them from returning. Close when the rebuild is validated.
