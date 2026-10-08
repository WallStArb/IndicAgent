---
status: pending
priority: P0
filed: 2026-10-08
source: plan 185-47 (orchestrator decisions 3 and 4; 189-10-1D-FETCH-RECORD.md "For 185-47" item 1)
owner: owner decision on the spin-off treatment, then one corporate-action correction plan
---

# corporate_action: CTVA spin-off recorded as a split, ETHA reverse split recorded twice at wrong dates

## What

The 189-10 Task 1b refresh ran the in-process overlap judge (todo 507), which records every
rescaled overlap as a `split` or `reverse_split` in `corporate_action`. Two names show that the
table and its writer cannot represent what happened, and that no sanctioned tool corrects a row
(`scripts/ops/bars/ops_split_detect.record_split` only supersedes a different factor on the same
date; the table's CHECK admits `action_type` in (`split`, `reverse_split`) only).

### CTVA (held since Task 1b; the single named exception to 185-47's C3 and C8)

Row `90c2dc47-d184-48b6-8e50-932fc2f60109`: `split`, factor 5.571428571428571 (39/7), effective
2026-09-30, inferred_by `nightly_overlap`, recorded 2026-10-08 15:13:07 UTC.

Company record (Corteva press release "Corteva Board of Directors Approves Vylor Distribution",
2026-09-14, https://www.corteva.com/news/corteva-board-approves-vylor-distribution.html, fetched
with curl 2026-10-08): a pro rata dividend of all Vylor Inc. shares, one VYLR share for every CTVA
share, record date 2026-09-24, distribution before the open on 2026-10-01; CTVA WI (ex-distribution)
and VYLR WI traded 2026-09-25 to 2026-09-30. It is a spin-off: CTVA's share count did not change.

Vendors (D1, 2026-10-08):

| | 2026-09-30 close | factor | implied 2026-10-01 return (close 12.57) | pre-event volume |
|---|---|---|---|---|
| raw (IBKR fetched 2026-10-01) | 77.65 | 1 | -83.8% (false: holders received VYLR) | 1,852,362 |
| IBKR refetch 2026-10-08 | 13.94 | 5.5714 | -9.8% | scaled up by the factor (10,319,565) |
| Tradier (fetched 2026-10-03) | 11.65 | 6.665 | +7.9% | 4,035,252 |

Which factor is continuous needs the CTVA WI close of 2026-09-30 (or VYLR WI's), which D1 does not
hold; the release states the ratio but no price. So neither vendor is shown continuous and the 185-37
method cannot decide it. Applying d2-v2 for CTVA as recorded would rewrite 1,848 canonical
ibkr_named bars (2019-05-24 onward) to IBKR's spin-adjusted prices with split-scaled volumes; volume
scaling is wrong for a spin-off under any factor. Today canonical CTVA ends at the raw 2026-09-30 bar
(no bar from 2026-10-01), D7 canonical_recompute fails on CTVA and freshness_1d fails.

### ETHA (two rows for one 1:3 reverse split, both dates wrong)

| action_id | effective_date | factor | inferred_by | recorded_at |
|---|---|---|---|---|
| ed939e61-6fcb-4ac7-a5a3-00594cc7a005 | 2026-10-02 | 0.3333 | tradier_refetch | 2026-10-06 12:38:02 UTC |
| 276f406f-5a03-473c-95eb-c8dff378abb2 | 2026-09-30 | 0.3333 | nightly_overlap | 2026-10-08 15:13:07 UTC |

Tradier's 2026-10-03 fetch holds raw pre-split closes for 2026-10-01 (20.37) and 2026-10-02 (20.11),
so the first post-split session is 2026-10-05 or 2026-10-06, not either recorded date. Canonical ETHA
values are correct today only because d2-v2 serves the latest fetch per date; the second row marks
Tradier's already adjusted 2026-10-06 refetch stale for dates before 2026-09-30 (it is not that row's
evidence), so a later re-derivation can raise pre_split_unrefetched flags on bars that are right.

## Options

CTVA (owner decides):
1. Raw series plus a recorded distribution: keep IBKR's raw closes (the pre-refetch SMART answers
   in D1), add a `spin_off` action type that d2-v2 does not apply as a split, and let the
   research kernel handle the distribution as a total-return event (as dividends are, todo 428). Needs
   a schema change (CHECK) and a d2-v2 rule.
2. Accept IBKR's adjusted prices but keep raw volume: a new mechanism (rescale volume back), so a
   design change.
3. Leave CTVA held and frozen at 2026-09-30 until 1 or 2 lands; it fails freshness_1d loudly.

Recommendation: 3 now, then 1 (price adjustment for spin-offs is a research-layer total-return
question, like dividends, not a bar-layer split).

ETHA: one correction plan that supersedes both rows with one row at the true first post-split session
(read it from the vendors' answers around 2026-10-05), through a sanctioned writer (extend
`ops_split_detect.py` with a dry-run `--supersede` that inserts a correcting row; the table stays
append-only), then a daily dry run on ETHA (expect changed 0).

## Gate

Before 189-10 Task 3 (the fetcher timer launch: the nightly overlap judge will keep recording such
events) and before the 186-26 rebuild.
