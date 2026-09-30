---
status: pending
priority: P2
filed: 2026-09-30
source: plan 186-13 task 2 caveat trace (todo 451)
---

# Stored regime columns carried a label-mask lookahead; two DEAD verdicts benchmarked against them

## What

Until the phase 186 rebuild (186-26), stored `feature_vectors.regime`, `regime_volatility` and
their numeric columns hold labels whose presence and duration/churn resets were decided by bars
up to a year after the labeled bar (todo 451, fixed in the kernel by 186-13). The regime columns
are kept out of every research family (STATE.md), so no positive verdict reads them.

## Dependents found (read only, 2026-09-30)

Grep over `docs/research/construction-verdict-ledger.md`, `docs/research/summary-cards/`,
`scripts/research/` and `src/intelligence/research/families/`:

- `docs/research/summary-cards/legacy-todo304-percentile-rank-regimes.md` and ledger row "Todo 304":
  the verdict "none sharpen IC beyond the already-live `regime_volatility`" used the stored column
  as the benchmark (orthogonality on 5 sample symbols, 3 with non-empty `regime_volatility`). A
  benchmark with a lookahead mask can only make the candidates look worse, so the DEAD verdict
  is biased toward dead.
- `docs/research/summary-cards/legacy-todo303-per-symbol-trend-regime.md` and ledger row "Todo 303":
  Stage 2 orthogonality (3 of 5 sample symbols non-empty) and the `regime_volatility`-stratified
  terciles of Stage 3 read the stored column; "no candidate sharpens IC beyond
  `regime_volatility`" has the same bias as the 304 verdict. The null-arm control itself is
  independent of it.
- `scripts/research/feature_matrix.py`: `NON_FEATURE_COLS` excludes `regime` but not the numeric
  `hmm_*` columns (only `todo445_5m_incremental_ic.py` excludes the `hmm_` prefix), so a family
  built on `fetch_feature_matrix` would pick them up.
- `feature_ic_scores` rows with `regime_scope = 'symbol_hmm'` are deleted by 186-20 (R-07).

## Fix

After the 186-26 rebuild, rerun the 303/304 benchmark comparison on rebuilt columns or leave the
verdicts with the note; add `hmm_` to `NON_FEATURE_COLS` (or an explicit allow after the rebuild)
before any family reads the matrix. Handoff to 186-18: the training-slice gate changes which
segments are skipped, which bears on todos 289 (1d `regime_volatility` coverage) and 341 (BIL,
ETHA, IBIT all-NULL); re-measure there.
