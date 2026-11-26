# Pre-declaration: the `reversal_21` replication (adopted, ledger 2026-11-23b)

Status: ADOPTED 2026-11-23 as ledger 2026-11-23b (lead ruling, owner veto reserved): R-1 as a non-gating disclosure charging 0 looks, R-2 as the forward confirmation at book freeze, R-3 rejected for now. The text below is the draft as submitted; the ledger entry governs. Author: indicagent-d4, for the lead. The author read no sub-period statistic and no run output beyond what the ledger already records (the per-member t and p of ledger 2026-11-22c and the selection of 2026-11-23a), and every rule below is set from the preregistration and from power arithmetic, not from those numbers.

## 1. What the existing documents say

- `.planning/STATE.md` (Evidence line, Lane A item 3, Owner only): "The `reversal_21` pooled replication is pre-declared (run after the pin; owner veto reserved)."
- Ledger 2026-11-22 (the E21 lift), "What it permits": the two daily residual runs, "then the `reversal_21` pooled replication". Ledger 2026-11-23a: "the pre-declared pooled replication, a positive net expectation and the single confirmation on the book's own unsearched forward span all still stand".
- `docs/plans/archive/2026-11-22-next-counted-family-after-daily-residual.md`, "Not ranked here": "pre-declared inside the daily residual sequence, not a new family".
- The daily residual preregistration (`docs/plans/2026-10-27-daily-residual-momentum-reversal-prereg.md`) has no replication section. Its amendments A1 to A4 do not mention one.

"Pooled replication" does have a defined meaning elsewhere: the E17 null battery run in two independent blocks of synthetic simulations whose rejection counts are summed (ledger 2026-11-20, 2026-11-21c; seed bases 7,000,000 and 8,000,000 for the reduced family, already passed and bound in `research/battery_passes/daily_residual_2026-11-21.json`). That is a test of the statistic, not of `reversal_21`.

So no document states which spec or panel is replicated, on what span, with what pass rule, at what look charge, or by what command. The label "pre-declared" is not yet true. This draft is the first declaration.

## 2. What can and cannot replicate

1. The same spec cannot run again. Spec-once (D-02, migration 611) refuses a second real run of a spec hash, and the E17 statistic is analytic and deterministic, so a rerun would return the same numbers.
2. Both panels read the same vintage. `daily_residual_h5` (spec hash 096abd79) and `daily_residual_h5_core` (7308dafd) score the same sessions, 2008-02-29 to 2025-12-23 for `reversal_21`, with the same `seen_names` exclusion. The core names are a subset of the primary names and the days are identical, so the two runs are one dependent pair, already counted as two looks.
3. The only data no look has touched is the forward span from `alpha.validation.oos_start` (2025-12-24). The evidence framework (section 7) spends it once, on a frozen book, and refuses any other read: a replication that reads it is a look at unsearched data and voids that spend. The runners refuse an `end_exclusive` past the cutoff.
4. `reversal_21` is a member, not a book. The forward confirmation needs a frozen book (combiner, construction rule, S8 book test); none exists.
5. The 2026-09-13 screen read a reversal hint on 231 names (preregistration section 6), so those names are not independent either, and A1 already excludes them from both panels.

Consequence: before the forward span, no run replicates `reversal_21` on independent data. Anything run on vintage_1 is a consistency check and must be disclosed as non-independent.

## 3. The declaration proposed for ruling

### 3.1 R-1, the vintage-internal consistency read (recommended)

- What: the `reversal_21` series of the two recorded runs (run groups c249e9bb and d5a95034, spec hashes 096abd79 and 7308dafd, vintage_1, 2008-02-29 to 2025-12-23, read from `research_run_series`). No new spec, no new series, no new data.
- Independence: none. It reuses vintage_1 and the two counted runs, so it adds no error control. It is disclosed as a stability check on the same evidence.
- Rule, fixed here: for each panel, the mean per-session P&L of the series is positive in each of the three sub-periods the two specs already declare (`scoring.sub_periods`: 2007-03-01 to 2011-12-31, 2012-01-01 to 2018-12-31, 2019-01-01 to 2025-12-23; the first covers sessions from 2008-02-29, the first scored session). Pass: positive in all six panel by sub-period cells. Fail: any cell is zero or negative. No threshold, no p value and no transformation is added, so the rule cannot be tuned to the known p of 0.0090 and 0.0025.
- Power note, so the rule is read correctly: if the full-span t is about 3.3 and the effect is stable, each sub-period t is expected near 1.9, so a true stable effect is positive in a given sub-period with probability near 0.97; a null series passes one panel's three cells with probability near one in eight. R-1 can embarrass a fragile result and cannot confirm a real one.
- Looks charged: 0. It creates no spec and no series, joins no StepM universe, and reads series of looks already charged (vintage_1 stands at 13 charged looks, ledger 2026-11-22f). If the lead rules that a decision-bearing read of a recorded series is itself a look, the charge is 1 (14 of the vintage), declared before the read; it must not be charged both ways.
- Command: none exists. The read needs a short read-only script, proposed as `scripts/research/replication_subperiods.py --run-groups c249e9bb d5a95034 --member reversal_21`, with a unit test on a synthetic series, built in a detached worktree and reviewed before any read. Until it is ruled and written, no number is produced.
- Pass means: disclosed as consistent, nothing promoted, no look added, no change to the selection or to the book path. Fail means: disclosed as a sub-period instability on the same evidence; it does not remove `reversal_21` from the selection or the book (removing a member after seeing its record is a new book version, framework section 6) and it is not a verdict, but it is a real result on a counted look and is carried into the forward confirmation's power plan as a haircut.

### 3.2 R-2, the independent replication is the forward confirmation (declared, not run)

The only replication with error control is the single confirmation of the frozen book that contains `reversal_21`, on the forward span, one-sided alpha 0.05, HAC timing t, one spend (framework section 7). Its date is fixed at freeze by power. This draft does not spend it, does not pre-declare its date, and does not read the span. A book containing `reversal_21` is a separate attempt (preregistration section 5) and is declared at its own freeze.

### 3.3 R-3, rejected for now: a disjoint-name panel

Run `reversal_21` on the names in the primary panel that are not in the core panel (the churn names). It is independent in names, not in days. It needs a new universe identifier in `snapshot.py` and `spec.py` (a research edit with `repro_frozen` bit-identical or a methodology entry), a new spec hash, one new counted look (14 of the vintage) and a new member series in the vintage_1 StepM universe, which tightens the correction on all eleven series including the two selected, and its own E17 battery pass at that panel's static sizes. The cost is a heavy battery plus a re-read of the selection, for evidence that shares every date with the existing runs. Not recommended before the forward confirmation; recorded so the option is not lost.

## 4. Items the existing text leaves undefined, with recommended answers

| Item | Recommended answer |
| --- | --- |
| What "pooled replication" means for `reversal_21` | Not the battery sense. Replace it by R-1 (disclosed consistency read, not independent) and R-2 (the forward confirmation); retire the phrase "pooled replication" for evidence. |
| Member, spec hash, panel | `member.daily_residual.reversal_21`; 096abd79 (primary) and 7308dafd (core), both recorded. |
| Span | vintage_1, 2008-02-29 to 2025-12-23. Not unseen; no unseen span exists before the forward span. |
| Independence | None for R-1, stated in the ledger entry. Independent only through R-2. |
| Blocks and seed bases | None. The evidence statistic is analytic; seed bases 7,000,000 and 8,000,000 belong to the battery and are not reused. |
| Pass rule | R-1: positive mean P&L in all six panel by sub-period cells. R-2: set at the book's freeze. |
| Looks charged | R-1: 0 (alternative 1, declared before the read, never both). R-2: the one forward spend. |
| Run command | R-1: the script above, to be built and reviewed. R-2: none yet. |
| Heavy slot | None for R-1 (a read of stored series). The slot is free for the next family. |
| Pass and fail meaning | As in 3.1. A fail is a real result on a counted look, not a verdict, and does not change the selection. |
| Whether the owner veto stays | Yes, on the ledger entry; the lead rules the items and writes it. |

## 5. Failure modes guarded

- Writing the rule after the p values: the rule has no threshold and was set before any sub-period read; the author did not read the sub-period statistics.
- Double charging or omission: one stated charge for R-1 and a declared alternative that replaces it; the 13 existing looks are not recounted.
- An undeclared panel choice: both recorded panels, by hash and run group, all six cells, none picked.
- Reading the forward span: R-1 reads recorded series that end 2025-12-23; R-2 is not run here.
