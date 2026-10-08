---
status: pending
priority: P0
filed: 2026-10-07
source: plan 185-37 (docs/research/vendor-adjustment-basis-study.md, "Undecided runs")
owner: owner decision, then a policy plan through scripts/ops/bars/ops_source_policy.py
---

# Stale-basis Tradier heads (45 names) and 185-38 IBKR rows contradicted by continuity (5 names)

## What

The 185-37 basis study decided 100 runs where Tradier steps and IBKR is continuous. 30 got IBKR
rows bounded to the run. 45 were withheld because the run starts at IBKR's first common session
while Tradier holds earlier dates on the same stale basis (verified on ABT: Tradier 2000 to
2006-10-05 sits about 2.09x above the current scale; LEGACY_IMPORT holds 4 days). A row bounded at
the run's start would move the false return from the run's end into the head seam, where no check
judges it (vendor_basis_run looks inside runs, unexplained_seam only at a recent window). Today the
false return stays where D7 sees it: canonical 1d on these names jumps by the run's factor at the
boundary (CHD log -0.69 on 2011-05-23, EWJ +1.39 on 2016-11-07, and similar).

Blocking under D7 (28): ABT, BAX, BF.B, CAH, CF, CHD, COP, CPAY, DOV, DUK, EBAY, EQT, EWI, EWJ,
EWM, EWS, EWU, FIS, FLO, GL, IBB, KIE, MGM, NI, NSC, ROST, WELL, XRT; EWT is undecided under the
rule by a hair and has the same stale head. Not blocking (17): AAON, ADP, BDX, BNY, CVBF, DRI, IRM,
KMB, MAS, MS, OUT, PPL, SPG, TT, VTR, VZ, WMB. 67,209 Tradier head dates in total.

Separately, the 185-38 admission sweep gave PATK, KDP, FTV, IP and STE whole-history IBKR rows
because Tradier disagreed; the continuity evidence says Tradier is the continuous side on those
runs (PATK: IBKR jumps 2.5x on 2017-12-11, so canonical PATK carries that false return; FTV and
IP: runs ending 2020-10-08 and 2021-09-30 with IBKR stepping; KDP: IBKR falls by a factor of about
5.6 on 2018-07-10 while Tradier moves 10%). The corporate actions behind the FTV, IP and KDP dates
were not checked against the public record. PATK and KDP block under D7.

## Options for the heads (owner decides)

1. A row from the name's first observation through the run's end (the 185-38 precedent): the
   Tradier head becomes holes, levels absent and no false return.
2. A vendor scale correction of the Tradier head by the measured factor (exact: 2.0, 0.5, 4.0):
   keeps the head's history; a new mechanism in d2-v2, so a design change.
3. Leave it: the false return stays at the run's end, visible to D7 and blocking promotion.

Recommendation: 1 for names whose head is short or whose factor is not an exact split ratio; 2 is
worth designing only if the 2000 to 2006 history matters to a research spec (the 45 names hold
about 1,700 head dates each).

For the five 185-38 rows: close each at its first day plus one (the only change the append-only
table allows, as VMRK) and write IBKR rows only where the evidence says IBKR is continuous (STE's
2014-03-19 to 2015-07-24 run). One plan, with a dry run per name.

## Gate

Before the 186-26 rebuild: the stale heads put false returns of log 0.5 to 3.2 into every feature
whose window spans the boundary.

## Decision 2026-10-07 (orchestrator recommendation, owner may override)

Option 1 for all 45 stale heads, including exact-factor ones: a head row from the name's first observation through the run's end, so the Tradier head becomes holes (missing is NaN, no_fill) and the raw observations stay in D1. Option 2 adds a vendor rescale mechanism to d2-v2 to save pre-2006 history that no current spec reads; delete before accelerating. Revisit only if a research spec needs 2000 to 2006 on these names. The five 185-38 rows follow the todo's own plan (close at first day plus one, IBKR rows only where the evidence says IBKR is continuous). One policy plan through ops_source_policy.py with a dry run per name, before 186-26.

## Owner decision 2026-10-08 (relayed by the research-ledger session indicagent-6a; confirm in the 185 session before acting on live data)

Todo 508 decision: option 1 for all 45 stale Tradier heads (head row from first observation through the run's end; head becomes NaN holes, raw D1 observations stay). Revisit option 2 only if a pre-registered spec needs pre-2006 history. The five 185-38 rows (PATK, KDP, FTV, IP, STE): one plan with a dry run per name, close each at first day plus one, write IBKR rows only where continuity says IBKR is the continuous side.
