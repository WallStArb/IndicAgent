---
status: pending
priority: P3
filed: 2026-10-01
due: 2027-05-04
source: interactive session, midterm look on S&P 500 history (looks 2 and 3)
---

# Record the 2026 midterm forward window result after 2027-05-03

## What

The pre-registered midterm spec in `docs/ideas/signal-political-policy-regime.md` (committed
2026-10-01, before the election) fixes one unsearched forward window: last `YAHOO_GSPC_CLOSE` at or
before 2026-11-03 to last close at or before 2027-05-03. Its 6-month log return is the only
out-of-sample observation this hypothesis will get for four years.

## Do

After 2027-05-03, once the close is stored:

1. Compute the window's 6-month log return with the committed rule, unchanged.
2. Compare it to the other-years mean (+1.9%) and the midterm mean (+10.0%) from look 2. Report
   it as one observation, not a test (one draw cannot confirm or reject the effect).
3. Add it under "Forward observation" in the idea doc and to the ledger row in
   `docs/research/construction-verdict-ledger.md`.

Do not use the look 3 best cell (1 month before, 9 months); the committed window is the definition.
