# Phase 181 pre-registration: time-series momentum on the cross-asset sleeve

Original: 2026-09-24 (frozen before any real-data number; run and verdict 2026-09-24).
Archived 2026-10-31: voided-era prereg, results voided by the owner's 2026-10-30 data reset.

Hypothesis: sign-and-volatility-weighted 12-month time-series momentum on the 13-symbol
cross-asset sleeve carries trend-timing information beyond a time-shifted copy of itself.

Verdict: FAIL (excess Sharpe +0.19, permutation p 0.22); most of the book's return is drift a
shifted copy also earns, so the timing component is below detection at 13 years and 13 names.
Closes classic TSMOM and variants (unsigned, 12-1, other lookbacks) on this sleeve. Ledger
row: docs/research/construction-verdict-ledger.md section 4; summary card
docs/research/summary-cards/legacy-tsmom-sleeve.md.

Full text in git history at docs/plans/2026-09-24-phase181-tsmom-sleeve-prereg.md as of 708f3fe09.
