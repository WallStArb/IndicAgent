---
status: pending
priority: P1
filed: 2026-09-24
source: council review 2026-09-24, docs/plans/2026-09-24-edge-proof-program.md "Phase 181 queue"
---

# Phase 181 candidate 2: short-term reversal on single names, market-neutral

## What

Short-term reversal (Jegadeesh 1990, Lehmann 1990) is a documented anomaly. The 2026-09-13
screen (`scripts/analysis/tsmom_per_symbol_ic_screen.py`) found a consistent negative IC of a
14-period daily RSI against the 2-session forward return: -0.0261 pooled, -0.0280 single names,
-0.0239 ETFs. That is a hint seen in-sample, not evidence.

## Requirements for the pre-registration

- Disclose the hint. The screen's symbols and in-sample window cannot count as evidence; test on
  what the screen did not use (the holdout, symbols added since, or phase 180 onboarding).
- Market-neutral construction, so the verdict is not a beta tilt (the range_pct_fast lesson).
- Executable open-to-open returns (Invariant 1) remove most bid-ask bounce; state the residual.
- A synthetic V2 at low signal persistence before the real run: V2 was calibrated at AR(1)
  phi 0.98, and a reversal signal turns over in days.
- Survivorship stated as a residual bias (todo 376); it inflates reversal on losers most.

Runs after todo 422's verdict (TSMOM, FAIL 2026-09-24); reuses the same signal-source stage and evaluator.

## Update 2026-09-25 (evidence framework adopted, methodology-change-ledger E15)

Reversal is now fourth in the family queue (`docs/plans/2026-09-25-alpha-research-architecture.md`
section 4), behind intraday momentum, overnight/intraday decomposition and lead-lag. The
2026-09-13 screen already looked at it on 231 of these names in-sample. The holdout option above
is withdrawn: the forward span is reserved for one confirmation test of a frozen book, so a
standalone reversal look would spend it. Daily form: symbols added since the 09-13 screen, or
phase 180 onboarding. Intraday form: a disclosed re-specification on seen data, pre-declaring a
one-bar skip variant. Either is a family member entering the book, not a standalone verdict.
