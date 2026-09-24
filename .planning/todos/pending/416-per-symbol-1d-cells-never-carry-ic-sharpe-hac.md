---
status: pending
priority: P3
filed: 2026-09-24
source: Phase 179 V4b finding (other session), consistent with the 176-08 gate verdict
---

# Per-symbol 1d IC cells never carry ic_sharpe_hac

All 1,146,900 per-symbol 1d rows of window 2025-12-24 are `reliable=true`, but none has
`ic_sharpe_hac`. A per-symbol 1d cell is too short for the rolling Sharpe (window
`alpha.ic.sharpe_window_size` with `alpha.ic.sharpe_min_windows`), so per-symbol 1d rows never
enter a shrinkage bucket, and at 1d the shrinkage prior is effectively pooled-only. Decide whether
that is intended; if a per-symbol 1d risk-adjusted IC is wanted, use a window sized to daily
history. Check no consumer assumes these rows carry a Sharpe.
