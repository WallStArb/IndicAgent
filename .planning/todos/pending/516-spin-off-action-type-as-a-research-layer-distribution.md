---
status: pending
priority: P2
filed: 2026-10-08
source: plan 185-51 (todo 515 option 1; 185-47 admission sweep note on ELE, IESC, MSM, TIGO)
owner: one data-layer plan (schema, d2-v2 rule, research kernel), then release CTVA's hold
---

# Spin-offs as a recorded distribution, not a split; four write names without symbol rows

## What

### 1. A spin_off action type, treated like a dividend in the research layer

CTVA is held since 185-51 (`bar_hold_current`, reason `unclassified_rescale`, factor 39/7, over
2019-05-24..2026-09-30) and frozen at its raw 2026-09-30 bar. Its wrong split row
(`90c2dc47`) is voided. The event: Corteva distributed one Vylor (VYLR) share per CTVA share,
record date 2026-09-24, distribution before the open on 2026-10-01 (Corteva release,
2026-09-14). The share count did not change, so the raw closes are the right bar series and the
-83.8 % first-day return is a distribution, not a loss.

The treatment (todo 515 option 1):
- `corporate_action` admits `action_type = 'spin_off'` (CHECK; append-only as now) with the
  distribution ratio (VYLR per CTVA share), the ex date and, when known, the distributed value
  (a when-issued or first-session price of the spun-off name). d2-v2 never applies it as a
  split.
- d2-v2 rule for a spin-off: dates before the ex date keep the observations fetched before the
  vendors restated them. Release alone is not enough: today IBKR's latest SMART answers for
  every pre-event date are its 39/7-adjusted ones (refetched 2026-10-08) and d2-v2 serves the
  latest fetch per date, so releasing the hold without this rule applies the rewrite of 1,848
  bars. Volume is never rescaled.
- Research layer: a return whose span crosses the ex date gets the distribution as a total-return
  event, the way `panel.total_return` handles dividends (todo 428). With no distributed value
  recorded, the crossing return is unknown, never zero (the dividend coverage rule).
- Then `ops_split_detect.py --release-hold 72cc2b5e-8af7-4ade-b3da-0a869dc53b41` and a daily dry run on CTVA (expected:
  changed 0 before 2026-10-01, new bars from 2026-10-01 on), apply, D7 canonical_recompute and
  freshness_1d pass on CTVA.

### 2. ELE, IESC, MSM, TIGO

185-47's admission sweep would write rows for 76 names; 72 hold a 1d symbol row, these four hold
none. They are class A on the recent median (1.0) but their whole-history agree share is 0.08,
0.04, 0.44 and 0.05 (ELE's whole-history median ratio is 10): the former class B pattern.
Checked still true 2026-10-08 (no `bar_source_policy` 1d row for any of them; all four active
and compute_1d). Decide each with the 185-37 continuity method (row or not), as 185-49 did for
the 38 head rows.

### 3. d2-v2 reads effective_date one session late

`corporate_action.effective_date` is the last day on the old scale (migration 400, the three
writers, D7's seam checks). `daily_rule._is_current` skips every observation with
`bar_date >= effective_date`, so the effective date itself is treated as new-scale: an
observation of that date fetched before the recording is served without
`pre_split_unrefetched`. Harmless while the escalation re-fetch answers that date (the latest
fetch wins); wrong when it does not. Fix with `>` and a test; no stored bar moves today (CTVA
held, ETHA's one current row has a new-scale answer for 2026-10-05).

## Gate

Before CTVA's hold is released and before the 186-26 rebuild reads CTVA (it reads a frozen series
today, which freshness_1d names).
