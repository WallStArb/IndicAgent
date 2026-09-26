---
status: pending
priority: P0
filed: 2026-09-26
source: 2026-09-26 backlog triage, owner decision
---

# Wire feature_vectors into the research Panel at all four timeframes

## What

The research layer (`src/intelligence/research/`, phase 183) never reads `feature_vectors`:
zero references in the package. Both registered families (`intraday_periodicity.py`,
`overnight_intraday.py`) build their signals from raw 15m bar returns. So the feature corpus
that v3.0 was built around has no path into a book test.

This contradicts the adopted architecture (`docs/plans/2026-09-25-alpha-research-architecture.md`,
E15): section 3.2 says the Panel carries "selected `feature_vectors` columns", and section 4 says
families from the feature corpus are admitted the same way as any other family. The phase 183
build shipped prices only because its first two families are return anomalies.

The phase 184 draft (`docs/plans/2026-09-25-multi-timeframe-horizon-design.md`, status proposed,
never adopted) then went further: D5 and section 6 say the research layer does not read
`feature_vectors` and recomputes features from kernels instead. The owner did not approve that.

## Owner decision (2026-09-26)

- `feature_vectors` is the basis of the research layer. Features enter books as members of
  pre-registered families, at 5m, 15m, 1h and 1d.
- Staleness and coverage are fixed at the source, not worked around with a parallel feature
  implementation. Todos 411, 412, 421 and 426 are on the critical path for this reason.
- The ic_engine / feature_ic_scores chain stays as evidence and disclosure (E15 changed
  admission, not the data).

## What to do

1. Revise the 184 draft: replace D5 (recompute, no `feature_vectors` reads) with reads of
   `feature_vectors` in S0, and bring the draft to the owner for adoption before planning.
   Keep its alignment node (B3) for mixing timeframes on one book clock.
2. Close the pre-registration gaps D5 was trying to cover, without a second implementation:
   - pin the APR window values in the spec at freeze and have S0 refuse if the live values
     used to compute the rows differ;
   - mask warmup rows (filled values such as RSI 50, z 0, percentile 0.5) to NaN in S0, by
     each feature's declared memory, so they never reach a signal;
   - refuse a feature whose populated-symbol coverage over the span is below a pinned floor
     (the 421 failure class).
3. S0 extension: `feature_vectors` columns as `[t, i]` arrays, read-only pool, content-hashed
   in the snapshot like the bars. The S3 causality probe covers them.
4. First feature family pre-registration once 1-3 land (candidates the architecture already
   names: SMC structure, volatility state).

## Depends on

411 (features current at every tf), 421 (coverage), 426 (write path for the refresh), 412
(watermark, so the refresh does not invalidate the IC corpus). 390 (illiq divide by zero) before
illiq enters any family.

## Triage 2026-09-26 (backlog review with the owner)

Added in triage: (1) HMM-derived columns (regime labels, `hmm_*`) may not enter any family until todo 248's walk-forward refit is deployed; phase 179 used the same exclusion. (2) Methods plan (todo 436): besides prior-driven feature families, the whole corpus may enter as one data-driven family without per-member priors (the ledger's reopened corpus-features row); that is the first Renaissance-style use once steps 1-3 land.
