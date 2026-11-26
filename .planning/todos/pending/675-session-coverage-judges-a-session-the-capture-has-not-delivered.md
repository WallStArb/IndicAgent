---
status: pending
priority: P3
filed: 2026-11-25
source: indicagent-04, pilot run 0e020c5a refused at the data gate (lead ruling 2026-11-25)
---

# session_coverage is judged against a session the nightly capture has not yet delivered

## What

A 1d verdict judges `session_coverage` against the last completed session, which `threshold.bar_integrity.session_close_settle_s` (1800 s) marks complete 30 minutes after the close. The Alpaca nightly capture arrives at 04:40Z and the derivations at 05:20Z and 05:45Z, so between about 21:30Z and about 05:50Z the last completed session has no canonical bar yet for any name. `threshold.bar_integrity.session_coverage_min_1d` is 0.999, so one missing session fails any name with fewer than 1,000 sessions (CRCL: 0.99731, one of about 372).

## Evidence

The member verdict refresh of 2026-11-25 (finished 23:54Z, after the 21:00Z close and before the 04:40Z capture): 103 names failed `session_coverage`, 91 of them passed in the 10:52Z audit the same day (CRCL 1.0 then). Each of the 103 also failed `proven_start_1d`, the data gate refuses a name with no proven start, and pilot run 0e020c5a stopped there with 92 refused names, no compute started. The next audit after the capture passes them again.

## Proposal

Measure session coverage up to the last session the capture has delivered (the latest canonical 1d session of the universe), not the last completed session. By the materiality rule (owner 2026-11-20) one trailing undelivered session is not a defect that can move a counted test, and `freshness_1d` already reports a name that is behind. A change to a verdict rule needs a methodology-change ledger entry before code, so this todo states the proposal and the evidence only; nothing changes until the lead rules.

Until then the launcher preflight (`verdict_preflight`) counts fresh names whose `proven_start_1d` fails and refuses with "wait for the nightly capture" when the last completed session's bar is missing (landed with the pilot work, lead ruling 2026-11-25).
