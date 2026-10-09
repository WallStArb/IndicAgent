---
status: pending
priority: P2
filed: 2026-10-08
source: plan 185-48 (residual risk of the 1d primary swap; 185-47 Apply results, 189-10 1D fetch record item 5)
owner: owner decision per name, then the onboarding SOP or ops_source_policy.py
---

# Four 1d names frozen at their last Tradier bar: PSKY, WBD, QRVO, MOD

## What

From D = 2026-10-07 no source answers these active compute_1d names, so each canonical 1d series
stops at its last Tradier bar and nothing after it is written (checked 2026-10-08):

| Name | Last canonical 1d bar | Open policy for D on | Why no bar since |
|---|---|---|---|
| PSKY | 2026-10-05 (tradier) | default: IBKR, no fallback | IBKR contract qualification fails ("No security definition has been found"); SMART answered through 2026-09-30 |
| WBD | 2026-10-05 (tradier) | default: IBKR, no fallback | same as PSKY; SMART answered through 2026-09-30 |
| QRVO | 2026-10-02 (tradier) | hold row: Tradier primary, IBKR fallback (185-47 class C) | IBKR has no contract definition; no IBKR request was ever made |
| MOD | 2026-10-06 (tradier) | hold row: Tradier primary, IBKR fallback (185-47 class C, few common sessions) | IBKR SMART answered 2026-10-07, but d2-v2 refuses the fallback date (basis window outside tolerance) |

Tradier's own answers for PSKY, WBD and QRVO also stop before 2026-10-06, the last bar of every
other name. That points at a listing or corporate event rather than an IBKR fault; check the company
record before any contract fix. CTVA is frozen too, by its hold (todo 516), and is not in scope here.

D7's `freshness_1d` fails PSKY (3 sessions), WBD (3) and QRVO (4) today; MOD fails once more than
`threshold.bar_integrity.freshness_max_lag_sessions_1d` (2) sessions pass. The rebuild gate refuses
a stale name, so these four block nothing else but cannot pass themselves.

## Decision per name (owner)

1. An IBKR contract fix (a symbol change or new conid, through the onboarding SOP's spelling rule),
   then a named fetch; or
2. an onboarding review (a merger or delisting: the name's history ends, it stays active and is
   handled under todo 512's rule for names whose defect is not worth fixing); or
3. a deliberate freeze recorded as a `bar_source_policy` row with the reason, so `freshness_1d`
   judges against a known end.

Never deactivate or soft-delete a name (onboarding SOP). MOD needs its own call: a symbol row that
makes IBKR primary from D with the seam recorded, or a wait for more common sessions.

## Done when

Each of the four has a recorded decision and either current 1d bars or a policy row that explains
its end; `freshness_1d` passes or names a recorded cause for each.
