---
status: pending
priority: P0
filed: 2026-11-13
source: the placed-span load's all-time compare_pre, 2026-11-13 19:15Z (exit 3 residue class)
---

# 192 symbols carry one unrecorded session choice each; disposition before step 7's B3

## What

The all-time 5m selection compare (2026-11-13 19:15Z, 1,551 symbols, real_differences 0, 415.7M
canonical 5m rows) exits 3: 192 symbols hold exactly one unrecorded session choice each
(series_clean 1337/1529), plus a small `unreviewed_basis_flags` set (e.g. ETHA 1h ibkr/named, a
3:1 price ratio). The unrecorded choices are nightly-shaped and pre-existing: identical on both
sides of the load bracket, and the raw-only load cannot introduce them.

## Why it matters

The step 7 runbook's B3 gate requires `session_choices_unrecorded == 0` (exit 0, or 3 with only
the A7 flag count) on the step 7 day. Step 7 does not start with this residue undispositioned.

## What to do

On the step 7 day, or before: review the 192 (one choice per symbol suggests a single recurring
recording gap, likely the nightly's last session or a writer race) and the basis-flag set through
an A7-style review; record or disposition each. Tonight's bracket cleanliness condition:
compare_post must reproduce the residue set identically (same 192, same shape); a changed
residue set is a load-introduced difference even with real_differences 0.
