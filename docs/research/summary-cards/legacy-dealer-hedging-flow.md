---
card_id: legacy-dealer-hedging-flow
kind: legacy_verdict
title: Dealer hedging flow, options-expiry calendar screen
idea: "Monthly option expiry resets dealer gamma, so intraday mean-reversion strength fades after expiry, concentrated in heavily optioned ETFs."
verdict: DEAD
verdict_date: 2026-08-07
recipe:
  spec: docs/research/data-edge-source-thesis.md
  script: scripts/analysis/dealer_hedging_flow_expiry_calendar_pilot.py
  recipe_commit: 0a8a0a16a8962b7be7e3948289bf5558b3472a88
results:
  - name: first_window_heavy_ci_lower
    value: -0.0133
    source: docs/research/data-edge-source-thesis.md
  - name: corrected_window_heavy_ci_lower
    value: "-0.00490, n_obs=1234, n_expiry_months=236"
    source: docs/research/data-edge-source-thesis.md
  - name: corrected_window_control_ci_lower
    value: "-0.00728, n_obs=567, n_expiry_months=158"
    source: docs/research/data-edge-source-thesis.md
known_defects:
  - "The first attempt (2026-08-07 to 2026-08-08) put expiry Friday in the PRE bucket. Index options on SPX, NDX and RUT settle AM off the opening print, so much of the gamma unwind lands at Friday's open; the window mislabeled a transition day. The DEAD verdict from that run was retracted and not trusted."
  - "The doc gives the first-window ci_lower for the heavy group only (-0.0133); the control group's first-window figure is not recorded."
  - "This is a calendar-proxy screen on OHLCV. The real test needs options-chain open interest and skew, which the project does not have and did not buy on spec."
  - "The 5m full-history window ends 2026-07-28, so the run read data at or after alpha.validation.oos_start."
spans_looked_at:
  - {start: 2006-09-01, end: 2026-07-28, role: full_history}
forward_span_looks: 2
tables: [market_data_ohlcv_tradeable]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - docs/research/data-edge-source-thesis.md
  - docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
related_cards: []
---

# Dealer hedging flow, options-expiry calendar screen

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row `dealer_hedging_flow`; `docs/research/data-edge-source-thesis.md` (Dealer Hedging Flow section)

## What was tried

Statistic pinned 2026-08-08 before running: per (symbol, expiry month), the change in a
mean-reversion proxy (minus the lag-1 autocorrelation of that session's 5m RTH bar returns,
at least 30 bars) from the sessions before monthly expiry (third Friday) to the sessions after.
Each group went through `gate_math.frame_gate_passes` clustered by expiry month. Heavily
optioned group: SPY, QQQ, IWM, TLT, GLD, SMH. Control group: SDOG, SPHB, CIBR, IPO, QUAL.
Verdict rule: the heavy group must pass (`ci_lower > 0`) and the control group must not. The
first window included expiry Friday in PRE. The corrected window excludes expiry Friday from
both buckets: PRE is the three sessions before expiry week's Friday, POST the three sessions
after.

## What was found

The heavy group fails under both windows. First window: `ci_lower` -0.0133. Corrected window:
heavy group `ci_lower` -0.00490 (1,234 observations over 236 expiry months), control group
-0.00728 (567 observations over 158 expiry months). Removing the ambiguous transition day moved
the heavy group closer to zero, consistent with dilution, but not across it.

## Known defects

See front matter. The doc trusts the corrected run because the window flaw was fixed and the
result confirmed the first rather than overturning it.

## Why closed

The ledger froze it DEAD, confirmed across two window specs. The doc states a negative cheap
screen closes the thesis, and a positive one was the only thing that would have justified buying
options-chain data. It cannot be rerun as-is: the recipe script is deleted by 186-16 and E15
changed the gates.

## Where the numbers came from

Every number is copied from the pinned-statistic and corrected-result paragraphs of the Dealer
Hedging Flow section in `docs/research/data-edge-source-thesis.md`. No query was run and no
script was rerun. The ledger row dates the verdict 2026-08-07/08; `verdict_date` takes the first
date.

`recipe_commit` is `git log -1 --format=%H --before="2026-08-08 23:59:59" -- scripts/analysis/dealer_hedging_flow_expiry_calendar_pilot.py`
(the corrected run's date). `tables` come from the shared `_fetch_bars_from_db` helper, which
reads `market_data_ohlcv_tradeable`.

The span start follows the 186-01 corpus start convention; the doc gives only expiry-month
counts. The end (2026-07-28) is the data freshness the 2026-08-07 research docs state, which
applies to the 2026-08-08 run. `forward_span_looks` is 2, one per run (the retracted first window
and the corrected one), since each read data at or after 2025-12-24; no other card counts them.
