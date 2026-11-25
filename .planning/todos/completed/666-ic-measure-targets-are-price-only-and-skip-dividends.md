---
status: completed
priority: P2
filed: 2026-11-24
source: indicagent-3d, readiness check of ic_measure against the rebuilt tables (lead item C)
---

# ic_measure targets are price-only: dividends are not in the open-to-open return

## What

`build_target_panels` (`src/intelligence/measure/targets.py`) builds the S0 panels without the dividend grid (`dividends=False`) and the measure's panel digest leaves dividends out on purpose (`services/ic_measure.py`, `panels_digest`: a dividend revision cannot change an IC). The targets are therefore `panel.forward_returns` on price-only opens. CLAUDE.md says a spec that holds across a session boundary declares `panel.total_return`; every 1d horizon in `alpha.ic_measure.horizons` (1, 2, 5, 10) does. An ex-dividend drop enters the target as a negative return, which biases a feature correlated with the yield (`dividend_yield`, `size_proxy` and the like) on the ex-date rows and adds noise to the rest.

## Deadline

Decided before the first IC run after the corpus rerun: CLAUDE.md says a spec that holds across a session boundary declares `panel.total_return`, and every 1d horizon in `alpha.ic_measure.horizons` does. The measurement plan: on the 1d pilot rows, the IC of `dividend_yield`-linked columns (`dividend_yield`, `size_proxy`) and the rank correlation of the full per-column IC vector between the price-only and the total-return target at each horizon, plus the share of target rows that straddle an ex-date.

## Return-free facts (measured 2026-11-24, light read-only counts, no return or IC read)

On Massive ex-dates inside stage 2 member months (2003-09-10 to 2025-12-23): 194,375 events on 5,838 names over 978,350 member-months, about 0.2 events per member-month, so a 1d target window of h sessions straddles an ex-date on about 0.95 percent x h of rows (an upper estimate across all member-months, uncovered names included): about 1 percent at h 1, 2 at h 2, 5 at h 5, 10 at h 10. Yield on those events: median 0.49 percent, 90th percentile 1.56, 99th 4.5; 1,507 events above 5 percent and 327 above 10 percent (specials). The lead's ruling (2026-11-24): decide on these facts, with no with-and-without IC comparison (that would be a counted look), and record the decision in the ledger before the first IC run.

## Done when

The materiality is read on return-free facts first (Musk step 1; owner ruling 2026-11-20): on the 1d pilot rows, the IC of `dividend_yield` and two unrelated columns with and without a total-return target at each horizon, and the share of target rows that straddle an ex-date inside `dividend_event_coverage`. If the difference is below the noise of the IC, record the price-only choice in the ledger as a disclosed property and close; if not, the target moves to total return for covered names (outside coverage dividends are unknown, never zero) under a methodology-change entry before the first IC run that is counted.

## Closure 2026-11-24 (lead ruling, ledger 2026-11-24e)

Decided on the return-free facts above and no IC comparison (that would be a counted look): the first IC run uses price-only targets as a screening measure; counted families declare `panel.total_return`. The first IC run's report spec carries the straddle table (share of 1d target rows whose window straddles an ex-date, by horizon: about 1, 2, 5 and 10 percent at h 1, 2, 5 and 10, from the 2026-11-24 counts) and the flag list (`dividend_yield` and its linked columns, `size_proxy`), and the yield distribution (median 0.49 percent, p90 1.56, p99 4.5; 327 events above 10 percent).

## Decision memo for the first IC run, 2026-11-24 (indicagent-94; the lead decides; read-only, no IC or return read)

Question. Every 1d horizon in `alpha.ic_measure.horizons` (1, 2, 5, 10) crosses a session boundary, and CLAUDE.md says such a spec declares `panel.total_return`. Ledger 2026-11-24e chose price-only targets for the first IC run; 2026-11-24f withdrew its sentence that the run is not a counted look (every IC cell is a counted attempt under E21, so the target definition is now the definition of each counted cell); 2026-11-24j corrected the coverage figure. This memo restates the options with their measured cost so the decision is final before the first cell is recorded.

Facts (all return-free). Straddle: a window of h sessions contains an ex-date on about 0.95 percent x h of rows (1, 2, 5 and 10 percent at h 1, 2, 5 and 10; 194,375 events on 5,838 names over 978,350 member-months, ledger 2026-11-24e). Yield of an event: median 0.49 percent, p90 1.56, p99 4.5, 327 above 10 percent. Dividend coverage of the member universe: 59.7 percent of member cells, 6,162 of 11,684 member names, all 5,292 uncovered names dead (ledger 2026-11-21d, 2026-11-24j); outside coverage dividends are unknown, never zero.

Options.
- A. Price-only targets for every cell (ruled in 2026-11-24e). Cost: an ex-dividend drop enters about 1 x h percent of target rows as a negative return. The bias is mostly noise for a feature unrelated to yield; it is a systematic bias for yield-linked columns (`dividend_yield`, `size_proxy` and their linked columns), whose cells read a mechanical ex-date effect as signal. Cells: unchanged (2 x measured x 4 horizons). Keeps every name, including the 5,292 dead uncovered ones, so the proposer is not survivor-tilted.
- B. Total-return targets (`panel.total_return`) wherever dividends are known, NaN elsewhere. Cost: about 40.3 percent of member cells have no known dividends and their targets become NaN, which removes the 5,292 uncovered names (all dead) and the uncovered sessions of partly covered names, so the measured panel tilts toward live and covered names (the survivorship the stage 2 universe was built to reduce). Cells unchanged, but each cell reads about 60 percent of its observations. This is what a counted family must do anyway, so B is the definition of the counted tests; for the proposer it is the more expensive reading.
- C. Price-only targets with the rows whose window straddles a known ex-date set to NaN (the same dividend facts, used as a row mask, not a return adjustment). Cost: removes at most about 1 x h percent of rows on covered names and none on uncovered ones (their ex-dates are unknown), so the residual bias on uncovered names is the same as A and on covered names is near zero. Needs a mask in the target path (`measure/targets.py` and the research kernel's dividend grid), a code change under `src/intelligence/research/` territory, with `repro_frozen` and a methodology line, and a rebind of nothing recorded.
- D. Run both A and B (two targets). Doubles the counted cells (2 x 2,216 attempts) and tightens StepM by the 0.2 in t measured in todo 671, to compare two definitions on the same features. Not recommended: the comparison is itself the look that 2026-11-24e declined to take.

Cost in series and StepM. A, B and C each record 2 x measured cells x 4 horizons attempts; only D doubles them. The correction of todos 670 and 671 applies equally to A, B and C. The choice changes what each series means, not how many there are.

Recommendation: A, as ruled, with three binding disclosures in every report of an IC cell (and in `docs/operations/corpus-first-run-disclosures.md` item 3.4): the straddle table above, the flag list (yield-linked columns are read on price-only targets and their cells are not evidence about the feature), and the statement that any family a cell prompts declares `panel.total_return` (B) at registration, so the counted test never inherits the price-only definition. Reasons: the sweep is a proposer whose cells are priced by StepM either way; B drops 40 percent of cells and tilts to survivors exactly where the universe was widened to avoid that; C is the right long-run definition but costs a code change in the research target path before the first pass, which only moves a bias of 1 x h percent of rows on names the proposer ranks by cross-section anyway. Revisit to C only if a yield-linked cell is the one that survives StepM (then the family built on it declares total return, which removes the effect from the counted test). The ruling needs no new ledger line unless the lead prefers C.


## Decision memo 2026-11-25 (indicagent-3c, read-only, no IC or return read; for the lead to decide)

Requirement after Musk step 1. The IC measure is a proposer: its cells rank columns for counted families, and every counted family declares `panel.total_return` itself (runner and `spec.py`). So the measure does not need dollar-exact returns; it needs its ranking not to carry a dividend-calendar artifact. Only columns correlated with the yield (`dividend_yield`, `size_proxy` and their links) can carry one, on about 1 x h percent of rows (0.2 ex-dates per member-month, 21 sessions, so about 0.95 percent of rows per session in the window; entry at open[T+1], exit at open[T+N+1], so an ex-date session s counts when T+1 < s <= T+N+1). For any other column the drop is noise on a rare row. The rule in CLAUDE.md governs a counted spec; a measure cell is a counted attempt (ledger 2026-11-24f) but not a test of a book.

Candidates, by what they do to the target.
- A, price-only (ruled 2026-11-24e): every window that holds an ex-date carries the drop as a loss; nothing is NaN; all 12,857 names keep their targets, uncovered dead names included. No code.
- B, `panel.total_return` in the measure: ex-date windows become exact on covered sessions, but outside coverage prices are NaN (about 40 percent of member cells, all 5,292 uncovered names), and a suspect or reentry event splits a name into `SYM~k`. The measure joins features to target columns by symbol (`map_slots`, `scatter_features`), so a segment column has no feature; the runner refuses the same case (`runner.py` `columns`). B needs a segment-to-feature mapping plus a new S0 with dividends, so it is the dearest, and it tilts the panel to live names.
- C, price-only with ex-date-straddling rows set to NaN on covered sessions: removes the artifact where the dividend is known, changes nothing on uncovered names (their ex-dates are unknown, never zero), keeps the rest. It asks S0 for `dividends=True` (the grid is in the snapshot hash, so `panels_digest` must hash the mask) and a mask in `measure/targets.py`.

Invariants. A keeps determinism, temporal_integrity (the target is realised by construction) and no_fill. C does too: the mask is NaN, never a fill, and a Massive event declared after its ex-date is unknown, so it does not mask. B keeps them but breaks the by-symbol join. Cost: A none. C is a code change in `measure/` and `services/ic_measure.py`, which moves `ic_measure`'s fingerprint, and it needs no edit under `research/` if it reads `dividends.dividend_grid` unchanged, so `repro_frozen` is not owed; the `/simplify`, `/review`, unit suite gate and a ledger line are. B edits S0 consumers and the measure and would expose `repro_frozen` if the join is solved in `research/`.

Recommendation: A, as ruled, with the three disclosures of the 2026-11-24 memo, and no code now. By the materiality rule of 2026-11-20 the benefit is confined to a few columns whose counted use declares total return anyway, while C costs a measure change and a new look-order dependency before the first pass. Reopen to C by a mechanical trigger: a yield-linked column is the one that survives StepM, or the first report shows a straddle share above the 2026-11-24e table. B is not recommended for the measure at any point.
