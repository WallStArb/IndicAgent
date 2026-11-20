---
status: pending
priority: P0
filed: 2026-11-20
source: lane B3 and B3b of the 584 pin readiness (indicagent-47), owner request through the lead
---

# Resolve the security type once per security (stage 2 membership shortfall)

## What

The stage 2 membership drops names whose pit snapshot row carries no `type` (`decide()` treats a missing type as ineligible). Missing labels are 62 percent of 2008 list rows, 50 percent of 2012, 47 percent of June 2016, and a step at 2016-10 (members 2,188 to 3,640) follows the label coverage, not the market. Measured 2026-11-20: over-floor non-members 1,567 (2008-06-30; type missing 1,352, ineligible 182), 1,608 (2012-06-29; missing 1,042, ineligible 532), 2016-09-30 4,058 over the floor against 2,188 members. INDEX-labelled names with volume are mislabelled ETFs (1,121 of 1,132 over-floor ones resolve to an ETF class across the three dates).

## Decision (lead 2026-11-20, owner framing: a security master normalization)

One type per security in a table `security_type` (symbol, rule_id, security_type, class_conflict, evidence jsonb, source), append-only by trigger, one writer, deterministic from `reference_raw_current` pit snapshots, so the ticker's presence on a list no longer gates membership (1,289 symbols have gaps inside their span that reset hysteresis). Class mapping (reviewer, adopted): ETF class {ETF, INDEX, ETS, ETV}; excluding labels win in the order ETN, WARRANT, RIGHT, PFD, ADRP; then ETF class, then FUND, then CS or ADRC by row count, CS over UNIT, then any other label. The pure resolver is on branch `wip/security-type-648` (`src/intelligence/security_type.py`, commit cdfe2d75f). The amendment states that Massive rebuilt its lists in 2025 (the labels are not point in time) instead of a temporal-integrity caveat.

## Measured

- Resolver over every security's own typed snapshot rows: 29,204 typed securities, 21,292 eligible (CS 12,615, ETF 8,145, ADRC 532), 823 with class conflict. 6,026 placed securities have no typed row in any list; their untyped residual at Dec 31 is 2,230 (2004), 1,581 (2008), 706 (2012), 24 (2016), 46 (2020), 0 (2024), all of them inactive names. Survivors are fully typed.
- Estimated members with typing alone: 2008 about 2,900 (from 2,138), 2012 about 2,760 (from 2,023); still under the preregistered 2,950 at 2012.
- Name fallback, frozen before looking, bar precision 0.99 on typed securities: A (not excluded by a warrant, unit, right, preferred or note pattern) precision 0.925, fails. B (A plus a common-stock word: COM, COMMON, ORD, SHS, ADS, ADR, ETF) precision 0.9944, recall 0.575, passes in sample, but 0.9721 on 501 typed names whose last list is before 2013, and the untyped residual is earlier-era and dead, so B is not adopted without a decision: it would type 1,357 of the 6,026 untyped.
- Reach of a capture: of the 6,026 untyped, 259 have a composite FIGI (OpenFIGI approved by the lead, about 260 requests, report hit rate), 0 have an ISIN, 5,971 have a cik, 4,870 have an overview with no type (the vendor's answer, no Massive sample).

## Remaining (nothing applied; build only)

1. Amendment to `docs/plans/2026-11-13-stage2-universe-preregistration.md` (class mapping, once per security, 2025 rebuild fact, carry disagreement counts 11 to 16 per date, per-year untyped remainder, ticker-only overview and name patterns ineligible unless B is adopted).
2. Migration 606 `security_type` (check the number against main; no compressed table, no VACUUM clause) with CI-enforced contract test; `services/security_type_writer.py` (BaseBatch, one transaction, advisory lock, rehearsal rolls back); wire `UniverseMembershipWriter._types` to read the table for placed symbols and remove the alphabetical two-rows-one-date tie-break; new `RULE_ID` and test update (`tests/unit/test_universe_membership.py` pins the old id); keep the snapshot completeness guard.
3. Re-pin `CLOSED_LIST_CANDIDATES_SHA256` (todo 645) with the new digest and its test; the pin moves again after the placement install in `docs/operations/stage2-membership-rebuild-runbook.md` step 5.
4. Gates: /simplify, /review, tests by exit code, independent review. Re-derive member counts for 2008-06-30, 2012-06-29 and 2016-09-30 from the built table with hysteresis and compare with the estimates.
5. OpenFIGI capture for the 259 securities through the existing capture path into `reference_raw` (send the lead the PID and log first); a second ranked source in the table.
6. Sequencing: the apply precedes the 584 pin; f3 runs a non-strict `--sweep --symbols` delta over the new members once the table exists.

Scripts: `scratch/b3/b3.py` (analysis, one session, temp tables) and `scratch/b3/st.py` (resolver and fallback measurement) on the wip branch. Not blocking: nothing in the table is written until the owner adopts the amendment.
