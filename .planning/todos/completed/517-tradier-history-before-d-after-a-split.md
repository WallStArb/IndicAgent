---
status: completed
closed: 2026-10-09
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

## Closed

Closed 2026-10-09 (UTC) by plan 185-52 (`185-52-SUMMARY.md`) with option 1, as rule d2-v3.

- Rule (`src/intelligence/bars/daily_rule.py`, `RULE_VERSION = "d2-v3"`). Where the policy's
  primary answered a date only on a stale scale and the policy names a fallback with a
  current-scale answer (fetched after the split's recorded_at, or the split's evidence), the
  fallback bar is served as `ibkr_fallback` when the basis over the
  `threshold.bar_integrity.fallback_basis_window_sessions` (20) common sessions nearest the date
  is within `threshold.bar_integrity.fallback_basis_tolerance_bp` (10). The basis of a stale
  Tradier date is IBKR's close over the Tradier close divided by the recorded split factors, a
  measurement only and never served. Otherwise the date keeps today's flagged stale bar
  (`pre_split_unrefetched`, quarantined). Volume: the bar keeps IBKR's raw volume, the tradeable
  view reads it NULL (migration 446's CASE on `ibkr_fallback`).
- D7: `policy_conformance` accepts `ibkr_fallback` where Tradier has no current-scale answer;
  `vendor_basis_run` measures the restated closes (`basis_closes`).
- Live: the unscoped daily dry run changed 0 rows on all 1,501 derived names (CTVA held), restated
  0 (ETHA, the only recorded split, has current-scale Tradier answers through its evidence
  request). The version bump relabelled 346,423 1d month digests at d2-v3 (content unchanged).
  D7 by hand before and after: every 1d verdict equal except report_age's elapsed hours.
- What-if (read-only, `logs/185-52/`): every name splitting at D with IBKR re-answering its stored
  SMART dates keeps 53.8% of the 6.69M Tradier bars before D tradeable, quarantines 1.8% on a basis
  refusal (294 names, 66 above 5% of their history) and leaves the rest without a stored IBKR
  answer; the fetcher's full-depth split re-fetch is what supplies those.
- Done-when: the synthetic tests (`tests/unit/bars/test_daily_rule.py`, d2-v3 section) and the
  D7 judge test (`test_a_restated_fallback_name_conforms_and_recomputes`) show a split name's
  Tradier history tradeable at the new scale with canonical_recompute and policy_conformance
  passing; the dry run over the live split (ETHA) is unchanged; the design doc's Amendment
  records option 1.
