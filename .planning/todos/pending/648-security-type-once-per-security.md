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

One type per security in a table `security_type` (symbol, rule_id, security_type, class_conflict, evidence jsonb, source), append-only by trigger, one writer, deterministic from `reference_raw_current` pit snapshots, so the ticker's presence on a list no longer gates membership (1,289 symbols have gaps inside their span that reset hysteresis). Class mapping (reviewer, adopted): ETF class {ETF, INDEX, ETS, ETV}; excluding labels win in the order ETN, WARRANT, RIGHT, PFD, ADRP; then ETF class, then FUND, then CS or ADRC by row count, CS over UNIT, then any other label. The pure resolver is on branch `wip/security-type-648` (`src/intelligence/security_type.py`, commit cdfe2d75f). The amendment states that Massive rebuilt its lists in 2025 (the labels are not point in time) and the temporal-integrity and survivorship-direction disclosures.

## Measured

- Resolver over every security's own typed snapshot rows: 29,204 typed securities, 21,292 eligible (CS 12,615, ETF 8,145, ADRC 532), 823 with class conflict. 6,026 placed securities have no typed row in any list; their untyped residual at Dec 31 is 2,230 (2004), 1,581 (2008), 706 (2012), 24 (2016), 46 (2020), 0 (2024), all of them inactive names. Survivors are fully typed.
- Estimated members with typing alone: 2008 about 2,900 (from 2,138), 2012 about 2,760 (from 2,023); still under the preregistered 2,950 at 2012.
- Name fallback, frozen before looking, bar precision 0.99 on typed securities: A (not excluded by a warrant, unit, right, preferred or note pattern) precision 0.925, fails. B (A plus a common-stock word: COM, COMMON, ORD, SHS, ADS, ADR, ETF) precision 0.9944, recall 0.575, passes in sample, but 0.9721 on 501 typed names whose last list is before 2013, and the untyped residual is earlier-era and dead, so B is not adopted without a decision: it would type 1,357 of the 6,026 untyped.
- Reach of a capture: of the 6,026 untyped, 259 have a composite FIGI (OpenFIGI approved by the lead, about 260 requests, report hit rate), 0 have an ISIN, 5,971 have a cik, 4,870 have an overview with no type (the vendor's answer, no Massive sample).

## Built 2026-11-21 (nothing applied)

1. Amendment 2026-11-21 appended to `docs/plans/2026-11-13-stage2-universe-preregistration.md`, adopted 2026-11-21 (e93b62f15; class mapping, once per security, the 2025 rebuild fact, carry disagreements, per-year untyped remainder disclosed, B not adopted, re-pin).
2. Migration 606 `security_type` with `tests/unit/test_security_type_migration_contract.py`; `services/security_type_writer.py` (BaseBatch, one transaction, advisory lock, rehearsal rolls back, labels read one list date at a time); `UniverseMembershipWriter` reads the table (one read for every month-end, refuses an empty table, snapshot completeness check kept, tie-break removed); `RULE_ID` is `stage2-2026-11-21`. Runbook step 6b added.
3. `CLOSED_LIST_CANDIDATES_SHA256` re-pinned to `730622aeeafca7eb60329980a979df1cfda8d334428aab0cde9a4913f1c2586b` (13,103 lines: the securities the list at L places with their resolved type; the full table is 29,204 securities, rehearsal). It moves again after the placement install (runbook step 7).
4. Rehearsal in a rolled-back transaction (typed 29,204, CS 12,615, ETF 8,145, ADRC 532, 823 class conflicts, all as measured). Members with hysteresis from 2003-09 on the current spans: 3,007 (2008-06-30), 3,129 (2012-06-29), 3,824 (2016-09-30), against the estimates of about 2,900 and 2,760 (the 2012 estimate was low: carrying a name's type through its gaps keeps hysteresis that a per-date estimate reset). Highest count by year 1,988 (2003) to 3,913 (2015); 2003 to 2006 and 2009 stay under 2,950 and are disclosed, not chased.

## Dropped

Item 5, the OpenFIGI capture (lead ruling 2026-11-21): it reaches 259 of the 6,026 untyped securities, all inactive and early-era, so by the materiality cost-benefit rule (owner 2026-11-20) the effort does not match the outcome. Name fallback B stays not adopted; the 2004 to 2015 shortfall against the 2,950 floor is disclosed, not gated.

## Remaining

- Amendment adopted 2026-11-21 (e93b62f15) and the placement install applied (install id 6195ae11abff-20261121T094558Z); now runbook step 6b (apply migration 606, run the writer, after the placement install) and the repin after step 7; f3 runs a non-strict `--sweep --symbols` delta over the new members once the table exists; the apply precedes the 584 pin.
