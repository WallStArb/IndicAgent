---
status: pending
priority: P1
filed: 2026-09-24
source: todo 422 build (phase 181 TSMOM), synthetic diagnostics 2026-09-24
---

# Phase 179: calibrated arms lose power on slow signals; wrapped shifts can leak long-window features

Two findings from building the TSMOM signal source on the phase 179 harness. Neither can make
179 PASS falsely; both can make a real edge FAIL. Decide before the 179 freeze whether the
pre-registration addresses them or records them as residual.

1. **Calibrated arms short a planted slow trend.** On synthetic panels with a persistent latent
   drift (AR(1) phi 0.995), the signal's IC is +0.035 and a fixed-direction sign/vol book earns
   Sharpe +2.2, but `vol_normalized` earns -1.0 (seed 0, full size, 2026-09-24). Cause:
   `portfolio._calibrate` learns each symbol's IC sign and size from a trailing 504-session
   window; for a slow signal whose innovations are the returns themselves, the in-window IC is
   noisy and Stambaugh-biased. 179's V3 plants a signal proportional to the forward return,
   which does not exercise this. If the ensemble's weight rests on slow features, V3 power is
   optimistic for it.
2. **Full-range circular shifts leak into long-window features.** With
   `out[t] = alpha[(t - k) mod n]`, shifts `k >= n - (window + 1)` wrap in a copy whose window
   contains t's target return. `admissible_shifts(..., memory=)` (b766685d2) excludes them;
   179 uses `memory=0`. On the TSMOM synthetic panel the leaking copies' median Sharpe was 1.60
   vs 1.21. This inflates 179's null (conservative) in proportion to its features' windows.
3. **N_tested at time of use is now 18** for 179 (16 ledger rows + TSMOM FAIL 2026-09-24 + 179
   itself); `HarnessConfig.n_tested` pins 17.

Also: 179 pre-registration section 14 says TLT's history starts 2017; it starts 2016-02-03
(`ohlcv_empty_history` verified).
