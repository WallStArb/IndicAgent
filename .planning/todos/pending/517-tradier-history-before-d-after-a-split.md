---
status: pending
priority: P1
filed: 2026-10-08
source: plan 185-48 (residual risk of the 1d primary swap; design doc Amendment 2026-10-07)
owner: one data-layer plan (d2-v2 rule or the split path), before the first split of a name with Tradier bars before D
---

# Tradier history before D after a split: d2-v2 quarantines it and never uses the restated IBKR answer

## What

Every name with Tradier bars before D = 2026-10-07 (about 1,500 names; their canonical 1d before D
is source `tradier`) reads those bars from Tradier observations that will never be fetched again:
the account is unfunded and plan 185-48 deleted the loader. d2-v2 (`src/intelligence/bars/daily_rule.py`)
treats an observation as stale for a date when a recorded split takes effect after that date and
the observation was fetched before the split's `recorded_at`. A primary with only stale-scale
observations is served with the `pre_split_unrefetched` flag (quarantined per APR) and the rule
never falls back to the other vendor for it.

So the first split of such a name after 2026-10-06 makes every Tradier observation before the split
stale. The closed default row still names Tradier primary for those dates, so d2-v2 serves the whole
pre-D history at the old scale, flagged and quarantined: the name loses its history before D in the
tradeable view, although IBKR's in-process split re-fetch (todo 507) holds current-scale SMART answers
for every date IBKR covers (from its SMART head on).

## Options

1. In d2-v2: when the primary has only stale-scale answers for a date and the fallback vendor has a
   current-scale answer fetched after the split's `recorded_at`, serve the fallback bar (source
   `ibkr_fallback`, volume NULL in the tradeable view) instead of the flagged stale bar. A rule change:
   new `RULE_VERSION`, golden fixture cases, a C1-style dry run over the names it would touch.
2. In the split path: when `ops_split_detect.py` records a split for a name with Tradier history
   before D, write a per-name `bar_source_policy` row (primary IBKR, no fallback) over the affected
   span, with the split as evidence. No rule change; the IBKR head and basis seams then need the
   185-37 and 185-49 judgments on that name.
3. A vendor scale correction of the frozen Tradier bars by the recorded factor (a design change, the
   same mechanism 185-49 rejected for stale heads).

Recommendation: option 1. It keeps one rule, uses only answers fetched after the event, and needs no
operator step per split.

## Gate

Before the first split of a name with Tradier bars before D is recorded (the fetcher timer launch,
189-10 Task 3, makes that likely within weeks) and before the 186-26 rebuild is relied on.

## Done when

- A recorded split on a name with Tradier history before D leaves that history tradeable at the new
  scale (a test over a synthetic name, and a dry run over the live names with recorded splits).
- D7's `canonical_recompute` and `policy_conformance` pass on such a name after the split.
- The chosen option is recorded in `docs/plans/2026-10-06-data-layer-integrity-design.md`.
