# Alpha research architecture: one research DAG, one book, breadth over sleeves

**Author:** Claude (Opus 5.5), 2026-09-25, at Brandon's request ("refine how we are finding
alpha ... design this like Renaissance would").
**Parents:** `docs/plans/2026-09-24-edge-proof-program.md` (sequence),
`docs/plans/2026-09-24-evidence-framework.md` (draft 3, evidence records, per-vintage budget).
**Status:** DRAFT 1. Proposes amendments to both parents; neither is edited until this is
accepted.

## 1. Diagnosis

The measurement machinery is sound: point-in-time snapshots, whole-panel shift nulls,
stationary bootstrap, pre-registration, a verdict ledger. The problems are in what gets
measured and how the search is organized. Five of them, in order of cost.

**1.1 The research unit contradicts the project's own principles.** `principles.md` says edge
is discovered, not designed, and that there is one model and one book: many weak signals
compete inside one combined forecast. The last month ran the opposite process: one
hand-designed construction at a time, tested standalone, each issued a PASS/FAIL token, each
spending the program's multiplicity budget. Under that process a real Renaissance-type signal
(IC 0.01 to 0.03, individually insignificant, useful only in combination) fails by
construction. 18 verdicts, zero PASS, is what that process produces whether or not edge
exists.

**1.2 Every portfolio-level test ran where statistical resolution is worst.** The two
walk-forward verdicts with real power machinery (TSMOM, phase 179) ran on 13 daily ETFs, n_eff
about 6.3. Section 2 of the evidence framework shows a Sharpe-1 book there takes 4 years of
data to reach t = 2 and a Sharpe-0.5 book 16. Meanwhile `feature_vectors` holds 233 names at
5m, 15m and 1h back to 2006. The resolving power of the project's data sits almost entirely
outside the vehicle being tested.

**1.3 The multiplicity budget is spent at the wrong level.** Charging alpha / N per
construction is correct for standalone tests on reused data, and at N = 18 the bar is already
p < 0.0028. The fix is not a looser bar. It is to spend the budget on a few tests of the
combined book, and let honest walk-forward fitting (ridge, refits on past data only) handle
signal selection inside it.

**1.4 The research code is bespoke per idea.** `scripts/analysis/` holds 71 scripts and about
24k lines. Most rebuild their own snapshot, target, null and decision logic. That has already
cost correctness: the 10x spread constant fixed in one script sat unfixed in another for 11
days (ledger, `range_pct_fast` row). The one reusable evaluator (`sleeve_walk_forward/`) is
shaped around the sleeve: `HarnessConfig` hardcodes 13 symbols and 1d, and `SignalSource`
receives only closes, so it cannot express a volume, intraday or feature-based signal.

**1.5 Two guards that should be code are review discipline.** Lookahead and null memory are
checked by people reading code. The shift-null memory for phase 179 (758 sessions) was derived
by hand from feature reach, and a leaking wrapped shift was found late (todo 424). Both can be
measured mechanically for any signal (section 3.3).

## 2. Design principles for the research layer

- **The unit of research is a signal's marginal contribution to one book,** not a standalone
  verdict. Standalone evaluation is a diagnostic.
- **Breadth before horizon, horizon before cleverness.** Independent bets per year is the
  lever (IR is about IC times the square root of breadth). Test where n_eff is largest first.
- **Every guard is a function that fails loudly,** not a checklist item. Silent wrong answers
  are worse than crashes.
- **Research is pure compute over an immutable snapshot.** One node reads the database,
  read-only. Nothing in the research DAG writes production tables. One node writes the ledger.
- **Declarative candidates.** A new idea is a pure function plus a machine-readable spec. It
  adds no new statistics, snapshot, or decision code.

## 3. The research DAG

```
S0  snapshot      (universe, tf, span) -> Panel            read-only DB, content-hashed    [generalize]
S1  target        Panel -> executable fwd return, factor-residualized, causal             [new, reuses factor_math]
S2  signal        Panel -> alpha[t, i]      pure function, declared reads                  [generalize signals.py]
S3  guards        causality probe, measured memory, integrity checks                      [new]
S4  residualize   alpha vs factors (+ book signals once a book exists), causal            [new]
S5  measure       evaluate(): arms, whole-panel shift null, bootstrap -> EvidenceRecord    [exists, generalize]
S6  ledger        sole writer: concept_registry(domain='construction'), vintage budget     [evidence framework step 2]
S7  combine       walk-forward ridge over all registered signals of admitted families      [new, reuses portfolio]
S8  book test     book's walk-forward excess over its own shift null, budget-charged       [new, same S5 code]
S9  holdout, then forward shadow                                                           [evidence framework 6-7]
```

One direction, no cycles. S0 is the only node with I/O besides S6. S1 to S5 and S7 are
compute-only and run in `ProcessPoolExecutor` workers under the existing rule (workers return
arrays, never write).

### 3.1 Where it lives

Promote `scripts/analysis/sleeve_walk_forward/` to `src/intelligence/research/` (Ring 1).
Statistics primitives stay in `src/intelligence/statistics/` (`panel_null`, `ic_math`,
`factor_math`), imported, never copied. Phase 179's frozen code path stays importable and
bit-identical under its frozen commit; the promotion is a move plus generalization, verified
by re-running TSMOM and 179 from their snapshots and matching the recorded numbers exactly.
New one-off scripts under `scripts/analysis/` that re-implement S0, S1, S3 or S5 stop.

### 3.2 S0 and S1: panel and target

`Panel` generalizes `Snapshot`: open, close, volume, selected `feature_vectors` columns, and
causal factor exposures, as `[t, i]` arrays for any `(universe, tf, span)`. The universe is a
pinned query (`compute_eligible`, or a named ITR selection), stored in the manifest with its
survivorship status stated. `end_exclusive` stays capped at `alpha.validation.oos_start`,
checked before any fetch, as now.

S1 defines one target for every candidate: the executable open-to-open forward return
(Invariant 1), residualized against market and sector or asset-class factors with loadings
estimated on data before t. A candidate that predicts the raw return mostly predicts beta;
that is the lesson of `range_pct_fast` and `alpha_score_residual`, and it should be enforced
once in S1, not relearned per construction.

### 3.3 S2 and S3: signals with mechanical guards

A signal is `compute(panel_view) -> alpha[t, i]` plus a spec (below). S3 runs three checks on
every signal before S5 sees it:

- **Causality probe.** For a sample of dates t, recompute alpha on the panel truncated after t
  and assert `alpha[t]` is bit-identical to the full-panel value. Any read past t fails the
  run. This catches every form of lookahead in the signal, including library calls nobody
  reviewed.
- **Measured memory.** Perturb the panel at row t and record the furthest row of alpha that
  changes. That reach, plus the forward span, is the null's `memory`. Hand-derived constants
  like 758 become an assertion that the measured value does not exceed them.
- **Integrity.** Coverage per date and per name, share of alpha computed from synthetic or
  zero-volume bars (must be zero: reads go through `market_data_ohlcv_tradeable`), and NaN
  handling (a missing input is no position, never a fill).

A failed guard records the failure in the ledger and produces no evidence.

### 3.4 The candidate spec is the pre-registration

Each candidate is a small frozen dataclass or YAML file: signal function, direction,
universe, tf, horizon, family, rationale and prior source (paper or mechanism). The runner
hashes the spec and refuses to run unless the spec is committed to git and no result exists
for that hash. The result records the spec hash, snapshot hash and code commit. This makes
"no real-data number before the pre-registration commit" a property of the runner instead of
a promise, and it keeps constants such as cost figures in one reviewed place.

Prose pre-registration docs stay for anything the spec cannot say (rationale, disclosed
in-sample hints), but the numbers that decide the test live in the spec.

### 3.5 S5: one evaluator, two readouts

`evaluate()` stays the single statistics path. Generalize it on two axes:

- Any `(universe, tf)`: the sleeve list and 1d session constants become Panel properties.
- A second readout beside portfolio excess Sharpe: the cross-sectional rank-IC time series of
  the residualized alpha against the residualized target, with the same shift null and
  bootstrap. On 233 names this is far better powered than a 13-name book Sharpe and is the
  natural input to the combiner.

The output is the evidence framework's record (estimate, standard error, permutation p,
per-period estimates, provenance). No tokens.

### 3.6 S7 and S8: the book is what gets tested

This is the main change to the evidence framework.

- **Families, not ideas, are admitted.** A family is a pre-declared group of signals with a
  shared mechanism (short-term reversal variants, intraday momentum, overnight/intraday
  decomposition, lead-lag). Admission is a pre-declared, lenient screen at the family level
  (for example, pooled residual IC positive with bootstrap interval excluding zero on the
  training span), plus clean S3 guards.
- **Every registered signal of an admitted family enters the combiner,** including the ones
  that look weak. The researcher does not choose members after seeing results. Ridge
  shrinkage, fitted walk-forward on past data only, decides the weights.
- **The multiplicity budget is spent on book tests.** S8 measures the book's walk-forward
  excess over its own shift null (shifting the combined alpha panel, as S5 does for one
  signal). Each book version is one test against the vintage budget. With a few book
  versions per vintage instead of one test per idea, the bar stays near 0.05 / M for small M,
  and power comes from breadth rather than from any one signal.
- **Standalone and residual evidence records are still written** for every signal, for
  diagnosis and for the ledger's "have we tried this", but they do not gate anything.

The forking-path risk moves to family admission and to how many book versions are tried per
vintage. Both are counted: the ledger records every family screened and every book version
tested, and the vintage budget M is declared before the first book test.

## 4. Where to search first

Ordered by prior times power, all on the 233-name panel at 1h or 15m unless stated:

1. **Short-term reversal, residualized** (todo 423, already queued). Documented anomaly,
   mechanism (liquidity provision), and the corpus already shows a consistent in-sample hint
   (disclosed; the 2026-09-13 screen's window is excluded from evidence). It is the first
   consumer of the generalized Panel, so the build in section 5 is on its critical path.
2. **Intraday momentum** (last half-hour return predicted by the first half-hour and the
   overnight return; Gao, Han, Li and Zhou 2018). Needs 5m or 15m bars, which exist to 2006.
3. **Overnight versus intraday return decomposition** (the two legs carry different, partly
   opposite premia; Lou, Polk and Skouras 2019). Needs only open and close.
4. **ETF-to-constituent and cross-asset lead-lag** at 5m to 1h. The universe mixes sector ETFs
   and their large constituents, which is the setup this family needs.

Each is a family of 3 to 8 pre-declared variants, not one construction. Families from the
existing feature corpus (SMC structure, volatility state) can be admitted the same way; the
corpus-wide IC table is their screen, and the combiner is where they are tested, not another
corpus-wide IC pass.

Costs: discovery stays gross (standing directive). Short-horizon families are exactly where
gross edge most often fails to survive costs, so every S5 and S8 record reports the cost band
as a diagnostic, and the capital step (evidence framework section 7) is where it binds.

## 5. Build order, shortest path to the next verdict

1. **Generalize S0/S2/S5 for todo 423** (Panel over `(universe, tf)`, signals receive the
   Panel, evaluator drops the sleeve constants). Verify by reproducing TSMOM and phase 179
   bit-identically. Then run 423 as a family. Target: first family evidence within days.
2. **S3 guards** (causality probe, measured memory). Small, pure, and run on 423 before its
   real-data run; backfilled against TSMOM and 179 as a check on the hand-derived 758.
3. **S1 residual target** shared by every candidate from here on.
4. **Spec-as-pre-registration runner** with the commit and hash check.
5. **S6 ledger writer** (evidence framework step 2, unchanged).
6. **S7 combiner and S8 book test** once two families are admitted.
7. Families 2 to 4 of section 4, in parallel with 5 and 6 (alpha-first rule: never serialize
   a verdict behind infrastructure that is not on its path).

## 6. What changes in the parent plans, if accepted

- Evidence framework: section 6's per-test budget becomes a per-book-version budget with
  family admission as a counted, pre-declared screen (section 3.6 above). Everything else in
  draft 3 stands.
- Edge-proof program: phase 181's queue is re-expressed as families on the 233-name intraday
  panel. Phase 180 (sleeve breadth expansion) drops in priority: the breadth it seeks already
  exists intraday, and the sleeve is no longer the primary vehicle. Phase 177's data floor
  gains weight, because a 233-name intraday book is more exposed to stale symbols (85 of 273
  active symbols lagged on 2026-09-24) and to survivorship (todo 376).
- `scripts/analysis/`: frozen for new S0/S1/S3/S5 logic. Existing scripts stay as the record
  of their verdicts.

## 7. What this deliberately does not do

- **No async in the compute path.** The research DAG is CPU-bound numpy over memory-mapped
  arrays; async buys nothing there and would complicate the worker model. Async stays where
  the waiting is: S0's concurrent asyncpg fetches and the production daemons.
- **No new service or table** beyond the ledger writer the evidence framework already
  specifies. The research layer is a library plus a runner, not a daemon.
- **No re-scoring of frozen verdicts.** Every ledger row stands. A re-test of a closed idea is a
  new family member under a new spec and is counted like any other.

## 8. Risks

- **Family admission becomes the new forking path.** Mitigated by pre-declaring families and
  their members before any real-data number, and counting every screened family.
- **Intraday data quality.** Synthetic and carry-forward bars are about 82% of raw intraday
  rows; any read outside `market_data_ohlcv_tradeable` is already CI-blocked, and S3's
  integrity check makes a synthetic-bar input a hard failure.
- **Survivorship on a present-day universe.** Short-horizon residual signals are less exposed
  than drift signals, but not immune. Stated in every manifest until todo 376 lands.
- **Cross-sectional dependence.** n_eff on 233 names after residualization is unmeasured.
  Measure it (the existing `effective_breadth_diagnostic.py` method, applied to residual
  returns) before quoting any power figure for the book.
