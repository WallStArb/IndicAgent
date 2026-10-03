---
status: pending
priority: P1
filed: 2026-10-03
source: interactive session (185 Tradier decision)
---

# Reconcile Tradier and IBKR daily bars; replace the sandbox token

## What

Tradier became the primary 1d source on 2026-10-03 (migration 438). Raw answers from both vendors sit in D1
beside each other. Measured over 3.9M overlapping bars and 989 names: 6.5% of closes differ beyond tolerance
(18.6% in 2006 falling to 1.0% in 2026), the median IBKR/Tradier volume ratio is 0.80 (0.96 in 2006, 0.55 in
2026), and HON's Tradier closes sit a constant 0.33% above IBKR's in every year, before and after its spin-offs.
Which vendor's closes are right is open. The dividend-adjustment hypothesis is refuted (median ex-date close
difference 0 bp, a dividend-adjusted close would show about -49 bp).

## Work

1. Arbitrate the differing closes against what neither vendor owns: corporate-action dates, the known-corrupt
   prints D2a already uses, and the daily range implied by the stored 5m bars. Per-name and per-year result, the
   share each vendor wins.
2. Explain the 42 names whose closes differ on most bars (a whole-history scale offset like HON's).
3. Decide the volume basis: IBKR SMART volume falls from 0.96 to 0.55 of Tradier's across 2006 to 2026, so a
   volume feature differs by vendor and year. Rescale, flag or keep per name, and say which.
4. Replace the ssfi sandbox token (`TRADIER_API_TOKEN`, `TRADIER_BASE_URL`) with a production token; confirm the
   history endpoint's rate limit and that sandbox and production return the same bars.

Plan 185-23's vendor-agreement check measures the drift nightly; this todo decides what the measurement means.
