---
card_id: legacy-retail-immediacy-provision
kind: legacy_verdict
title: Retail immediacy provision, levered-ETF close-rebalance sharpening
idea: "Leveraged and inverse ETF issuers' mandatory close rebalance moves the underlying's last 5m bar in the direction of the day's return, more so for levered-sleeve names than for a control group."
verdict: DEAD
verdict_date: 2026-08-07
recipe:
  spec: docs/research/data-edge-source-thesis.md
  script: scripts/analysis/retail_immediacy_provision_levered_sleeve_pilot.py
  recipe_commit: 0a8a0a16a8962b7be7e3948289bf5558b3472a88
results:
  - name: levered_group_ci_lower
    value: "0.0000014, n_obs=41747, n_days=5069, gate pass (analytic CLT bound, n_days above bootstrap_max_n=5000)"
    source: docs/research/data-edge-source-thesis.md
  - name: control_group_ci_lower
    value: "0.00000001, n_obs=26129, n_days=4919, gate pass"
    source: docs/research/data-edge-source-thesis.md
  - name: trading_days_in_range
    value: 5434
    source: docs/research/data-edge-source-thesis.md
  - name: point_estimate_ratio
    value: "levered group point estimate about 140x the control group's (not load-bearing for the verdict)"
    source: docs/research/data-edge-source-thesis.md
known_defects:
  - "The verdict rule was binary and pinned before the run: the levered group must pass and the control group must not. The control group passing falsifies the mechanism; the 140x point-estimate gap is suggestive of a smaller distinct effect but was explicitly not a test."
  - "Both ci_lower values sit at the numerical floor (1.4e-6 and 1e-8); the gate is a pass only in the strict sense ci_lower > 0."
  - "The full-history 5m window ends 2026-07-28, so the run read data at or after alpha.validation.oos_start."
spans_looked_at:
  - {start: 2006-09-01, end: 2026-07-28, role: full_history}
forward_span_looks: 1
tables: [market_data_ohlcv_tradeable]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - docs/research/data-edge-source-thesis.md
  - docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
related_cards: []
---

# Retail immediacy provision, levered-ETF close-rebalance sharpening

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row `retail_immediacy_provision`; `docs/research/data-edge-source-thesis.md` (Retail Immediacy Provision section)

## What was tried

The thesis was sharpened on 2026-08-03 to one mandatory, price-insensitive flow: 3x and inverse
ETF issuers rebalance into the close in proportion to the day's move, and that flow lands on the
underlying. Statistic pinned 2026-08-07 before running, at tf=5m per (symbol, RTH session day):
`co_movement = prior_return * last_bar_return`, with `prior_return` the day's move up to the
second-to-last bar. Each group was passed once through `gate_math.frame_gate_passes` with
day-clustered CIs. Levered group: XLF, XLE, SMH, XBI, GDX, TLT, IWM, QQQ, SPY. Control group:
SCHD, SDOG, USMV, QUAL, MUB, PFF, DBA. Verdict rule: the levered group must pass
(`ci_lower > 0`) and the control group must not.

## What was found

Both groups pass. The levered group has `ci_lower` 0.0000014 over 41,747 observations on 5,069
days; the control group has `ci_lower` 0.00000001 over 26,129 observations on 4,919 days. The
effect is present in both, so it is ordinary intraday momentum, not a levered-issuer rebalance
flow. The levered point estimate is about 140x the control's, which the doc records as
suggestive of a real, smaller, distinct effect but not as part of the verdict.

## Known defects

See front matter. The near-zero `ci_lower` values mean "pass" carries little margin, and the
pre-registered rule deliberately kept the 140x gap from substituting for the binary test.

## Why closed

The ledger froze it DEAD (falsified by its own pre-registered rule). It cannot be rerun as-is:
the recipe script is deleted by 186-16, `feature_vectors` is rebuilt (this run read only
`market_data_ohlcv_tradeable`), and E15 changed the gates.

## Where the numbers came from

Every number is copied from the "Result" paragraph of the Retail Immediacy Provision section in
`docs/research/data-edge-source-thesis.md`. No query was run and no script was rerun.

`recipe_commit` deviates from the date rule: `git log -1 --format=%H --before="2026-08-07
23:59:59" -- scripts/analysis/retail_immediacy_provision_levered_sleeve_pilot.py` returns
nothing, because the script was first committed the next day (2026-08-08 09:21 -0400) in
`0a8a0a16a8962b7be7e3948289bf5558b3472a88`, together with the dealer hedging flow pilot. That is
the only commit touching the path, so it is the recipe. `tables` come from the script's
`_fetch_bars_from_db` helper, which reads `market_data_ohlcv_tradeable`.

The span start follows the 186-01 corpus start convention; the doc gives only the day counts.
The end (2026-07-28) is the data freshness the 2026-08-07 research docs state. `forward_span_looks`
is 1: the single run read data at or after 2025-12-24 and no other card counts it.
