# Evidence framework: book-level tests, a renewable screen, confirmation on unsearched data

**Author:** Claude (Opus 5.5), 2026-09-24 (drafts 1-3), 2026-09-25 (version 4), at Brandon's
request ("get rid of the non-Renaissance concepts/rules/gates"; "design this like Renaissance
would").
**Informed by:** AGY adversarial reviews of drafts 1 and 2 (2026-09-24), council refinement of
draft 3 and `docs/plans/2026-09-25-alpha-research-architecture.md` draft 1 (2026-09-25),
section 11. Codex review not obtained (quota exhausted until 2026-10-15).
**Status:** ADOPTED 2026-09-25, methodology-change-ledger entry E15. Governs every verdict
produced after adoption; no frozen verdict is re-scored (section 9). The build plan that
implements it is `docs/plans/2026-09-25-alpha-research-architecture.md`.

## 1. The decision

1. **The unit of test is a book version,** not an idea. Ideas enter as pre-registered signal
   families; every registered family goes into one combined book; the book is what gets tested.
   Per-signal and per-family measurements are recorded as evidence, never as tokens, and never
   remove a family from the book.
2. **Error control lives on unsearched data.** Tests on the searched vintage are a screen: they
   decide which book spends the forward span, at a fixed, pre-declared bar. The confirmation test
   on the forward span is the one that controls false discoveries, and it is spent once.
3. **The screen budget is renewable; the forward span is not.** Because validity rests on
   confirmation, the screen budget can restart when the vintage rolls. The current vintage's
   budget is M = 30, count restarted at 0 on adoption (section 6).
4. **No underpowered test runs.** A test whose null cannot resolve its bar, or whose synthetic
   power at the pre-declared effect is below 50%, is refused before any real-data number exists.
5. **Capital is sized net of costs, after confirmation,** from the low end of the evidence, and
   scales with forward results. Discovery and confirmation stay gross (standing directive).

## 2. The fact that governs everything: time to resolve an edge

The standard error of an annualized Sharpe measured over T years is about 1/sqrt(T).

| True Sharpe of the book | Years to t = 2 | Years for 80% power at one-sided 0.05 |
|---|---|---|
| 0.5 | 16 | 25 |
| 1.0 | 4 | 6.2 |
| 2.0 | 1 | 1.5 |
| 3.0 | 0.4 | 0.7 |
| 4.0 | 0.25 | 0.4 |

Power column: T = ((1.645 + 0.842) / S)^2. No verdict rule changes these numbers. A 13-name
daily sleeve with a modest edge sits in the first rows, in-sample and forward alike. The only
lever that moves a book down the table is **breadth times horizon**: many independent bets per
year, which means factor-residualized signals across the full universe at intraday horizons
(IR is about IC times the square root of independent bets per year). Independent bets are
counted after removing common factors, not by ticker; on this universe that count is still
unmeasured at intraday horizons (architecture plan, step 0).

## 3. Two stages

```
searched vintage  [2007 .. cutoff)       unsearched forward span  [cutoff .. test date]
  families -> book walk-forward            frozen book, run forward
  screen test at alpha/M, recorded         confirmation test, alpha 0.05 one-sided, once
  (decides who spends the span)            (controls false discovery; gates capital)
```

- **Why the screen is not the error control.** Every look at the vintage, including informal
  ones (a screen that "hinted" at reversal, a diagnostic run before a pre-registration), shapes
  later choices, and informal looks cannot be counted. A Bonferroni count over pre-registered
  tests is therefore a lower bound on the true search, never an exact charge. Data that nobody
  has looked at is the only place a p-value means what it says.
- **Why keep a strict screen anyway.** The forward span is the scarcest resource in the program:
  a failed confirmation costs its whole length (months to years, section 2). The screen's job is
  to keep noise books from spending it. At alpha/M with M = 30, the chance that any noise book
  clears the screen during this vintage is at most 5%.
- **Why the budget may restart when the vintage rolls.** A screen that renews does not
  compromise the confirmation, which is always on data no screen has touched.

## 4. What changes and what stays

| Current rule | Verdict | Replacement |
|---|---|---|
| "Earn promotion through proof (p < 0.05, sufficient N)" | Reword | "Earn capital through a pre-registered, powered test on unsearched data" |
| PASS / ACT / FAIL token per idea | Replace | Evidence record per measurement (section 5); tests only at the book level |
| Bar of 0.05 / N_tested, N counted at time of use | Replace | Pre-declared screen budget per vintage, same bar for every book version (section 6) |
| Excess positive in 2 of 3 sub-periods; Track 1 five-criterion gates; per-symbol BY-FDR share | Remove for new work | Per-period estimates reported, not voted on |
| Holdout as a one-shot sign veto | Replace | Confirmation test on the forward span, dated in advance by power (section 7) |
| Standalone test of each idea | Replace | Standalone and factor-residual evidence records, diagnostic only; the book is tested |
| Draft 3's residual-vs-book test per candidate | Demote to diagnostic | The book test decides; the combiner fits factor-residualized signals with walk-forward ridge, so what a signal adds is priced without order dependence |
| Draft 1 architecture's outcome-based family admission screen | Delete | Families are admitted by pre-registration and clean guards only (section 6) |
| "DEAD, do not re-litigate" | Keep | A variant is a new pre-registered family member; it enters the next book version, which is counted |
| Pre-registration, point-in-time snapshots, whole-panel shift null, synthetic V2/V3 per statistic, fidelity checks, loud failure on broken data | Keep | These protect the measurement |

## 5. The evidence record

Written for every measurement (signal, family, book), from `evaluate()`:

- **Estimate** `e = S_obs - median(S_null)`: excess annualized Sharpe over shifted copies, and
  for panels wide enough to carry it, the excess mean cross-sectional rank IC.
- **Standard error** from the stationary bootstrap of the daily excess series.
- **Permutation p** from the shift null.
- Per-period estimates, shape diagnostics, snapshot hash, spec hash, code commit, and the
  **resolution time** implied by the estimate (section 2).

Worked example, TSMOM (2026-09-24): `e = +0.19`, bootstrap 95% interval [-0.32, +0.73]
(`se` about 0.27), permutation p 0.22.

A measurement that fails an integrity check records the failure and no evidence. A shrunk
estimate may be shown as a reading aid where the family is large and homogeneous (feature ICs);
no prior is fitted to the program ledger, whose rows are too few and too heterogeneous.

## 6. The screen: book versions against a per-vintage budget

- **Families.** A family is a pre-declared set of 3 to 8 signal variants sharing one mechanism
  (short-term reversal, intraday momentum, overnight/intraday decomposition, lead-lag). Its spec
  (members, direction, universe, horizon, rationale, prior source) is committed before any
  real-data number. A family enters the book when its spec is committed and its signals pass the
  mechanical guards (causality probe, measured memory, integrity). **There is no outcome-based
  admission screen**: a screen on the full vintage followed by a walk-forward book test on the
  same vintage would leak future information into the book through the choice of families.
- **Commitment.** Every member of every registered family enters the combiner, including the
  ones whose evidence records look weak. Ridge shrinkage, fitted walk-forward on past data only,
  sets the weights. Removing a family or member after seeing its record is a new book version.
- **Book version.** A book version is the set of registered families plus the combiner spec.
  Each book version tested on the vintage is one screen test, one-sided at alpha / M on its
  permutation p.
- **Budget.** Vintage 1 is all data before `alpha.validation.oos_start` (2025-12-24). Its budget
  is **M = 30**, declared 2026-09-25, count restarted at 0; bar **p < 0.00167**. The 18 legacy
  standalone verdicts stay frozen in the ledger with their own tokens and are not charged:
  several ran on data or code later found wrong (the 10x spread constant, the Phase 179
  coverage bug, stale feature snapshots), all were standalone tests of a kind this framework no
  longer runs, and section 3 is why a restart is sound. The ledger records every book version
  and every guard failure; a run registers its ledger row before computing, so an aborted run is
  still counted.
- **Refusals, before any real-data number.** A test is refused if its null cannot resolve the
  bar (fewer than M / alpha admissible shifts, so at least 600 at M = 30), or if its synthetic
  V3 power at the pre-declared effect size is below 50%. Phase 179's V3b (0% power on slow
  signals) is the case this prevents.
- **When the budget runs out,** new book versions wait for the vintage to roll (section 7).

## 7. Confirmation on the forward span

- **The forward span** is all data from the vintage cutoff onward: the existing holdout
  (2025-12-24 to date, about 9 months) plus every day that accrues. The book that clears the
  screen is frozen (spec hash, code commit, walk-forward refit rules) and runs forward in
  shadow.
- **The test date is fixed at freeze,** never chosen by looking. It is the date at which the
  span gives 80% power for half the screen's excess Sharpe estimate (the conventional haircut
  for in-sample selection; it plans power and never enters the test). Interim views of the
  forward P&L are allowed for loss-limit monitoring only; no significance is read before the
  test date. Optional stopping is the bias this closes.
- **The test.** One-sided, alpha 0.05, on the frozen book's forward excess over its shift null.
  One spend per span; if two books are frozen on the same span, the split is declared at the
  second freeze.
- **Vintage roll.** When a confirmation is spent, pass or fail, the cutoff moves to the test
  date, the spent span joins the searched vintage, and a new screen budget is declared.
- **Data floor.** A forward span with stale or missing bars fails integrity loudly. Confirmation
  depends on the batch data being current across the book's universe (edge-proof program,
  phase 177; todos 395, 411).

## 8. Capital

- **Entry.** Only a confirmed book gets capital: a small starting risk budget sized from the low
  end of the evidence (lower bound of the combined walk-forward and forward bootstrap interval),
  with hard loss limits.
- **Scaling.** Forward daily returns update the book's Sharpe estimate; the risk budget follows
  a lower posterior quantile, growing only as unseen data supports it and shrinking as it
  decays.
- **Construction.** Positions from mean-variance optimization over the book's joint covariance,
  with a transaction-cost penalty, factor and position limits, and liquidity caps.
- **Costs enter sizing only.** A book whose expected return net of costs is not positive sizes to
  zero. That is arithmetic at the capital step, not a gate on the search; discovery and
  confirmation stay gross, with the cost band reported as a diagnostic.
- **Owner parameters,** set when the first book is frozen (none is close): the overall risk
  budget (the single fractional-Kelly choice), the loss limits, and the posterior quantile.

## 9. Transition

- Frozen verdicts stand: all 18 ledger rows, including Phase 179's E14 rerun, keep their
  pre-registered tokens. Evidence records added for them are labeled legacy.
- The first family is intraday momentum, unseen on this data (architecture plan section 4).
  Todo 423 (short-term reversal) is fourth: the 2026-09-13 screen already looked at a
  reversal-like statistic on these names in-sample. Its daily form runs on symbols added since
  that screen or on phase 180 onboarding, never on the forward span.
- `docs/foundation/principles.md` and `CLAUDE.md` are updated with adoption.

## 10. Objections considered

- **"Restarting the count forgives 18 looks at the same data."** It would, if the screen were
  the error control. It is not: section 3 puts error control on the forward span, which none of
  the 18 touched. The restart changes only how strict the screen is.
- **"Confirmation takes too long."** For a Sharpe-1 book it takes about 6 years, and no rule can
  shorten that. The response is to build books that sit lower in section 2's table, not to test
  a weak book sooner.
- **"Committing every family member dilutes the book."** Ridge shrinks weak members toward zero
  at a walk-forward cost the book test pays honestly. Dropping members after seeing their
  records would be cheaper and wrong.
- **"A book test hides which signal works."** The evidence records show it. The book test only
  decides what spends the forward span.
- **"Small capital after one confirmation is still risky."** It starts at the low end of the
  evidence with hard loss limits, and forward data decides whether it grows.

## 11. Review record

AGY, 2026-09-24, on draft 1. Adopted: removing every gate would size noise from day one; forward
proof at Sharpe 0.5 takes decades; the bootstrap, not the null spread, is the standard error; an
empirical-Bayes prior over 17 heterogeneous tests is not identifiable; per-signal Kelly ignores
covariance and estimation variance; the unit should be marginal contribution to one model.

AGY, 2026-09-24, on draft 2. Adopted: per-version multiplicity and holdouts can be gamed by
cutting versions; forward-only capital is paralyzed at realistic Sharpes; shifting only the
candidate inside the book makes a phantom diversifier; breadth is independent bets, not tickers;
sizing is mean-variance with costs and limits.

Council refinement, 2026-09-25, on draft 3 and architecture draft 1. Changed:
- Error control moved to the forward span; the vintage budget became a renewable screen. Draft 3
  said fresh data "opens a new budget" while every later in-sample test still reads the old
  data; that is only sound once confirmation, not the screen, controls false discovery.
- Test unit moved from candidate to book version; draft 3's residual-vs-book test demoted to a
  diagnostic.
- Architecture draft 1's family admission screen deleted: admitting on the full vintage, then
  testing the book walk-forward on the same vintage, leaks future information through family
  choice.
- Book null must shift the stacked signal panel and refit the combiner per shift; shifting the
  combined alpha after fitting leaves the fit out of the null.
- Confirmation date fixed at freeze by power, closing optional stopping.
- Underpowered tests and nulls that cannot resolve the bar are refused up front.
- Owner decision (2026-09-25): M = 30 on vintage 1, count restarted; legacy verdicts frozen.
