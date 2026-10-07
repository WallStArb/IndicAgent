---
status: pending
priority: P1
filed: 2026-10-07
source: 185-41 finding 1 (SUMMARY), rechecked against the 1d primary swap plans 185-46 to 185-48
owner: phase 185 data layer
---

# D7 judges only compute_1d, so a never-judged name can never pass the promotion gate

## What

Since 185-41, promotion and the phase 186 rebuild read the computed `bar_integrity` verdicts, and a name with a missing verdict is held. D7 writes verdicts only for the universes it already loads: the 1d report covers the 1,502 `compute_1d` names and the intraday report covers the 233 `compute` names. The 27 active names with `compute_eligible_1d = false` therefore have no verdict row for any 1d check, and the dry run of 2026-10-07 holds all 27 as "missing" on every check. No run can ever produce the verdict that would promote them, so the onboarding SOP's promote stage reports "held, missing" by design for every new name. The same shape applies to `compute`: a name whose 5m the fetcher lands later is never judged on slot_coverage, grid_parity or coverage_cache, so it cannot be promoted either.

The old gate (`backfill_status.fetch_complete`) had a related flaw for a different reason; the new one is correct except that its input universe is the promoted set. D7 already loads the `backfill` dimension (all 1,529 active names) as `active` in `execute`; the verdict reports do not use it.

## Fix

Judge the promotion candidates, not only the promoted names. The 1d report takes the `backfill` dimension (every active name). The intraday report takes every active name that holds 5m rows, so a name becomes judgeable as soon as its 5m lands and stays absent (held) before. The new `freshness_1d` check (185-46) follows the 1d universe change. Measure before and after: the 1d report took 4 min 37 s at 1,502 names, so 27 more names add about 2 percent; record the intraday report's time at the larger universe. Expect the failing-name gauges to rise by the failing candidates, which is the point; the dedicated freshness alert (`bar_freshness_1d_uid`) will include them.

Do not change the gate (`gate_symbols`, `REQUIRED_CHECKS`) and do not promote or demote any name in this todo: promotion remains the promote script's decision on the verdicts.

## Gate

Before the next onboarding wave's promote step (onboarding SOP stage 8) and before the freshness alert is expected to be quiet. It does not block the 186-26 rebuild, which reads the `compute_1d` names.

## Done when

- universe_expansion_promote_compute_eligible.py dry run reports the 27 names as judged (pass or a named failing check), not "missing", for both dimensions that apply to them.
- D7 writes verdict rows for all 1,529 active names on the 1d checks; run times for both reports are recorded in the commit message.
- A unit test pins the universes (1d: backfill dimension; intraday: active names with 5m rows) with fakes (todo 494).
- The onboarding SOP's promote stage no longer says a never-judged name is held by design.

## Related

185-41 finding 1, 185-33, 185-40, 185-46 (freshness_1d), 185-47. Todo 498 keeps the fetcher's own SLA alert dead; this todo does not depend on it.
