# Phase 179 sleeve walk-forward diagnostics (stub)

**Archived 2026-10-31** under the doc-disposition hierarchy (root CLAUDE.md). Full text in git
history at `docs/plans/2026-09-24-phase179-diagnostics-plan.md`, commit 708f3fe09.

**The ideas worth keeping** (reusable for any future walk-forward or book evaluation):
- Diagnostics never feed the verdict token: one script outside the harness package, reading the
  S1-S3 artifacts, so a diagnostics fix never moves the frozen code key.
- The ten-diagnostic catalog: one-way L1 turnover (annual mean + per-year series); net-of-cost
  Sharpe at cost bands 1/3/5/10 bps round-trip subtracted per day; Sortino, max drawdown, skew,
  excess kurtosis, hit rate per arm; excess per year and per pre-registered sub-period;
  per-symbol contribution (weight x forward return); per-stratum excess by equity regime;
  reference arms (equal-weight long-only, static tilt); deviation sizing (uniform-weight vs
  production-pool variants as separate suffixed runs); feature decay (each selected feature's
  next-year pooled IC vs its training IC); no-weight days per year.
- Payload-first pattern: persist the per-arm daily weight matrix in the S3 payload BEFORE the
  freeze, tested for identical decide output, so post-freeze diagnostics never touch verdicts.

Parent prereg stub: `2026-09-24-phase179-sleeve-walk-forward-prereg.md` (same directory).
