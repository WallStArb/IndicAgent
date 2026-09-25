# Evidence framework: estimates not tokens, residual evidence, one test budget per data vintage

**Author:** Claude (Opus 5.5), 2026-09-24, at Brandon's request ("get rid of the non-Renaissance
concepts/rules/gates"). Parent plan: `docs/plans/2026-09-24-edge-proof-program.md`.
**Informed by:** AGY adversarial reviews of drafts 1 and 2 (2026-09-24, section 11). Codex review not
obtained (its configured model is unavailable on this account).
**Status:** DRAFT 3, awaiting owner decision on adoption. Adopted by methodology-change-ledger entry E15 once reviewed.
Applies to verdicts produced after adoption; no frozen verdict is re-scored (section 8).

## 1. The decision

Every measurement is recorded as an **estimate with its uncertainty**, never collapsed to a
per-idea token. A candidate is measured on its **residual**: the part of its signal not already
explained by the current book's signals and common factors, run through the existing evaluator
and shift null unchanged. Multiplicity is charged against a **data vintage**: every test run on
the same data draws from one pre-declared budget, each at the same known bar, and only fresh
data opens a new budget. Capital is **small after a clean holdout** and scales with forward
evidence, sized jointly with costs and risk limits.

The binding constraint is not the verdict rule; it is statistical resolution (section 2).

## 2. The fact that governs everything: time to resolve an edge

The standard error of an annualized Sharpe measured over T years is about 1/sqrt(T). To show a
true Sharpe S is above zero at t = 2 takes about (2/S)^2 years:

| True Sharpe of the book | Years to t = 2 | Years to t = 3 |
|---|---|---|
| 0.5 | 16 | 36 |
| 1.0 | 4 | 9 |
| 2.0 | 1 | 2.3 |
| 3.0 | 0.4 | 1 |

A 13-instrument daily sleeve with a modest edge sits in the first row: no verdict rule, however
clever, proves it quickly, in-sample or forward. Renaissance's answer was never a better test; it
was **breadth and horizon**: thousands of instruments, short holding periods, many weak signals
combined, so the book's Sharpe is high and resolves in months (fundamental law: IR is about IC
times the square root of the number of independent bets per year). The framework below is built
for that, and the edge-proof program's priorities should follow it (section 9).

## 3. What changes and what stays

| Current rule | Verdict | Replacement |
|---|---|---|
| "Earn promotion through proof (p < 0.05, sufficient N)" | Keep the intent, reword | "Earn capital through pre-registered, multiplicity-controlled evidence on unsearched data, then forward confirmation" |
| PASS / ACT / FAIL token per idea | **Replace** | Evidence record (section 4) plus one pre-declared test per candidate at its vintage's bar (section 6) |
| ACT at p < 0.05 / N_tested, N counted at time of use | **Replace the counting, keep the principle** | Pre-declared budget per data vintage: every test on that data gets the same bar, set before the first one runs (section 6). The count was right to accumulate, because the in-sample data is being reused; it was wrong to let a test's bar depend on its queue position |
| Excess positive in 2 of 3 sub-periods | **Remove as gate** | Per-period estimates reported |
| Holdout as a one-shot sign veto | **Replace** | Holdout is the final test of a production candidate, spent once, result recorded whatever it is (section 6) |
| Track 1 five-criterion gates, per-symbol BY-FDR "share qualifying" | **Remove for new work** | One pre-registered pooled estimate through the evaluator |
| Standalone evaluation of each idea | **Replace when a book exists** | Residual evaluation against the current book's signals and factors (section 5) |
| "DEAD, do not re-litigate" | **Keep, reworded** | A variant is a new pre-registered test and spends the same vintage budget |
| Pre-registration, point-in-time snapshots, shift null, synthetic V2/V3 per statistic, fidelity checks, loud failure on broken data, holdout discipline | **Keep** | These protect the measurement |

Draft 1 proposed removing every gate and draft 2 proposed resetting the count per model version;
both were wrong (section 11). A capital gate is necessary, and multiplicity has to be charged
against the data that was searched.

## 4. The evidence record (per pre-registered measurement)

From `evaluate()` on the pre-registered arm:

- **Estimate** `e = S_obs - median(S_null)`: excess annualized Sharpe over shifted copies.
- **Standard error** from the stationary bootstrap of the daily excess series (already computed
  in `evaluate()`; `se = (hi - lo) / 3.92` from its 95% interval, or its bootstrap sd). This
  measures variation across plausible return histories, not only across shifts of one history.
- **Permutation p** from the shift null: the significance reference, recorded, not a token.
- Per-period estimates, shape diagnostics, snapshot hash, code commit, pre-registration path.

Worked example, TSMOM (2026-09-24): `e = +0.19`, bootstrap 95% interval [-0.32, +0.73]
(`se` about 0.27), permutation p 0.22.

A measurement that fails an integrity check records no evidence, only the failure.

Shrunk readouts: each record may also show an empirical-Bayes shrunk estimate, as a reading aid
only. A two-groups prior is not fitted to the program ledger (17 heterogeneous tests cannot
identify it); it is used where the family is large and homogeneous, as it already is for
feature ICs (`ic_shrunk`, hundreds of features in one family).

## 5. Residual evidence: what does the candidate add?

- **Residualize, then test.** At each date, regress the candidate's alpha cross-section on the
  current book's signals and common factor exposures (market beta plus the factor set, causal:
  loadings from data before the date) and keep the residual. Run the residual through the
  evaluator exactly as a standalone signal: same arms, same shift null (which shifts the
  residual panel, which is uncorrelated with the book at each date by construction), same
  bootstrap.
- **Why not "book with minus book without".** Shifting only the candidate inside a combined book
  makes the null copy artificially orthogonal to the book, a phantom diversifier (AGY round 2).
  Residualizing first removes what the book already has, so the test asks only whether the new
  part predicts returns.
- **Order dependence.** The first of two correlated candidates takes the shared part. The
  combined book is refit from all admitted signals at each model version, so the order affects
  what is admitted, not the final weights; the ledger records the order.
- Until a book exists, candidates are measured standalone against factors only.

## 6. Multiplicity: one budget per data vintage

- **Vintage.** A vintage is a fixed span of data: now, everything before
  `alpha.validation.oos_start` (2025-12-24). Every test that looks at a vintage draws from its
  budget, whatever model or idea it belongs to.
- **Pre-declared budget.** Before the first test on a vintage, declare its size M (the number of
  pre-registered tests you intend to run on it). Every test is judged at alpha / M, one-sided,
  on its permutation p. The bar is known in advance, the same for every test, and independent of
  queue position. For the current vintage, the tests already run count against it (18 so far);
  M is declared once, at adoption, with room for the planned queue.
- **When the budget runs out,** new tests wait for fresh data. Fresh data is the forward span
  since the last vintage closed, which becomes the next vintage.
- **Holdout.** Data after the vintage is the holdout. It is spent once per production candidate:
  one pre-registered test of the final combined book. A candidate that fails it is recorded and
  the holdout is not reused for its successor; the successor waits for the next vintage.
- **Inside the fit,** ridge shrinkage and walk-forward refits keep weights honest across many
  weak signals.

## 7. Capital: small after the holdout, scaled by forward evidence

- **Entry.** A combined book that passes its holdout test gets a small starting risk budget,
  sized from the lower end of its evidence (for example the lower bound of the walk-forward plus
  holdout bootstrap interval), with hard loss limits.
- **Scaling.** The risk budget moves with the forward record: forward daily returns update the
  book's Sharpe estimate, and the budget follows a lower posterior quantile, so it grows only as
  unseen data supports it and shrinks as it decays.
- **Construction.** Positions come from mean-variance optimization over the admitted signals'
  joint covariance, with a transaction-cost penalty, factor and position limits, and liquidity
  caps. The overall risk budget is the only fractional-Kelly-style choice, and it is yours to
  set.
- **Costs** enter the capital step; discovery stays gross per the standing directive. Confirm or
  strike this narrow departure.
- **Resolution time is stated with every result** (section 2).

## 8. Transition

- Frozen verdicts stand. Phase 179 (E14 rerun) and every earlier ledger row keep their
  pre-registered tokens; any evidence record added for them is labeled legacy and cites the
  frozen token.
- Phase 181 onward (starting with short-term reversal, todo 423) pre-registers under this
  framework: evidence record, standalone until the combined book exists.
- `docs/foundation/principles.md` and `CLAUDE.md` wording updated with adoption.

## 9. Architecture and build order

```
S0 snapshot -> signal sources / ensemble refit -> alpha panels            [exists]
  -> evaluate(): arms, shift null, bootstrap                               [exists]
  -> evidence.from_evaluation(): (e, se, p, provenance)                    [new, pure]
  -> evidence recorder -> concept_registry(domain='construction')
                        + concept_evaluation (passed nullable for it)      [new, sole writer]
  -> residualizer: candidate vs book signals + factors (causal)           [new, pure]
  -> combiner: walk-forward ridge over admitted signals                    [new, reuses portfolio]
  -> shadow book (forward, daily) -> capital sizing                        [later]
```

1. Review this draft; record E15.
2. `evidence.py` (pure) and the recorder with its migration; S4 for signal sources emits the
   record (179's frozen path untouched, coordinated with that session).
3. The residualizer and combiner, reusing `portfolio`'s covariance and mean-variance code and
   the shift null.
4. Strategic re-plan of the edge-proof program toward independent bets: breadth counts bets
   after factor residualization, not tickers (273 names may carry only 5-15 independent daily
   bets), so the lever is residualized signals at shorter horizons (intraday bars exist),
   where bets per year multiply, not a wider daily panel alone.
5. Shadow book, then capital sizing once you set its parameters.

## 10. Objections considered

- **"A per-vintage budget is still Bonferroni."** Yes, deliberately: the in-sample data is being
  reused, and every test on it spends the same finite chance of fooling ourselves. What changes
  is that the bar is fixed in advance and equal for every test, and fresh data restores it.
- **"The budget will run out."** Then the next test waits for fresh data. That is the correct
  consequence of having searched the old data, and a reason to prioritize by prior.
- **"Residualizing depends on order."** It does for admission; the ledger records the order and
  the book is refit from all admitted signals.
- **"Small capital after one holdout is still risky."** The starting budget uses the lower end of
  the evidence and hard loss limits; forward data decides whether it grows.

## 11. Review record

AGY, 2026-09-24, on draft 1. Adopted: removing every gate would size noise from day one; forward
proof at Sharpe 0.5 takes decades, not months; the bootstrap, not the null spread, is the
standard error; an empirical-Bayes prior over 17 heterogeneous tests is not identifiable;
per-signal Kelly ignores covariance and estimation variance; the unit should be marginal,
orthogonalized contribution to one model with multiplicity controlled inside it. Not adopted:
"the two-groups model cannot correct forking paths": when every variant is recorded, empirical
Bayes is the standard winner's-curse correction; it is dropped here for identifiability, not
for that reason.

AGY, 2026-09-24, on draft 2. Adopted: per-version multiplicity and per-version holdouts can be
gamed by cutting versions (fixed by the per-vintage budget and one holdout per production
candidate); forward-only capital is paralyzed at realistic Sharpes (fixed by small capital after
the holdout); shifting only the candidate inside the book makes a phantom diversifier (fixed by
residualizing first); breadth is independent bets, not tickers; practical sizing is
mean-variance with costs and limits. Kept despite critique: a single risk-budget scalar, which
is the only place a Kelly-style choice remains.
