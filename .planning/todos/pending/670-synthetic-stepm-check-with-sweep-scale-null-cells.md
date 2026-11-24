---
status: pending
priority: P1
filed: 2026-11-24
source: indicagent-3d family-order note, lead ruling 2026-11-24
---

# A synthetic StepM check with sweep-scale correlated null cells before any IC sweep

## What

E21 counts every measured IC cell as an attempt in the StepM universe. A full 1d level 1 sweep is about 277 columns x 4 horizons = 1,108 cells (ledger 2026-11-22d: 277 judgeable) added to the recorded series of vintage_1 (20 charged rows, 24 after family 10; StepM universe 16 series). The step-down correction tightens with every added series, so the sweep could drop `reversal_21` (adjusted p 0.0135 and 0.0045 on 12 series) from the selection set. This check measures that cost before the sweep exists. It is a script that reads recorded series and draws synthetic ones: no real-data compute, no `research_run` row, no counted look.

## Spec (design 2026-11-24, indicagent-94; implementer follows this)

Where it lives: `scripts/research/stepm_sweep_scale_check.py`, calling the shipped `src.intelligence.statistics.stepm.stepm` unchanged and reusing `scripts/research/select_books.py` (`universe_matrix`, the vintage and APR loading). It edits nothing under `src/intelligence/research/` or `statistics/`, so `repro_frozen` is not a gate and no statistic changes. If the timing step below shows the per-draw Python loop is unworkable, a vectorized draw path in `stepm.py` is a separate change under `statistics/` (bit-identical to the shipped result, `repro_frozen` and the 187-05 battery as gates, a methodology-ledger line): file it as its own todo, do not fold it in here.

Inputs, all read-only: the completed vintage_1 attempt series through `universe_matrix` (the recorded universe, one calendar, NaN where an attempt did not test a session); APR `alpha.selection.stepm.fwer` (0.05), `.block_mean_sessions` (20), `.reps` (2,000) and `.seed` (187); the declared cell count N_cells (about 1,108); the target series name `reversal_21` plus every other series the recorded StepM selects (report each).

Null cells (the only invented data), each of N_cells columns on the recorded calendar:
1. Mean exactly zero, so every null cell is true under H0. The check measures the price of the multiplicity, never power.
2. Overlap memory by horizon. A cell at horizon h in {1, 2, 5, 10} sessions is a moving sum of h iid session shocks rescaled to unit variance (an MA(h-1) series, as E17 documents for overlapping targets). Cells are split evenly over the four horizons.
3. Scale. Per-session pooled IC of a null feature has a standard deviation near 1/sqrt(N_names) (about 0.02 to 0.03 at the 1d panel width); draw each cell's scale from that range. Scale does not move a studentized t, so state it but do not tune it.
4. Dependence, a k-factor model with loading matrix chosen so the average absolute pairwise correlation reproduces a stated effective breadth n_eff (ledger section 5: effective breadth about 8.4 of 230 raw features). Three settings: n_eff = 8 (the recorded breadth), n_eff = 50, and n_eff = N_cells (independent cells, the worst case and the bound). After the corpus exists, add a fourth setting that uses the stored-column correlation matrix; the check is valid and decisive without it.
5. Tails. Shocks are Student t with 5 degrees of freedom (unit variance), because per-session IC is not Gaussian. A Gaussian replicate set is run alongside as a comparison.
6. Missingness. Real cells have warmup NaNs: mask each null cell's first w sessions (w from 0 to 252, drawn per cell) so the per-draw studentization sees unequal spans.

Procedure: for each (n_eff setting, tail setting), R = 8 replicates. Replicate r draws the null block with seed `base + r` (seed by position, never from the clock) and runs `stepm(series=[recorded 16 | null block], block_mean, max_horizon_sessions=10, reps, fwer, seed=187)` with studentize="draw". Report, per setting: for each recorded series, the share of replicates in which it stays selected, its median and range of adjusted p, and the count of null cells selected (false selections; each should be 0 at fwer 0.05 in nearly every replicate, and the share is itself a size check of the correction at sweep scale). Also run one replicate with N_cells = 0 and confirm it reproduces the recorded adjusted p-values exactly (a regression guard on the script's wiring).

Writes: one JSON file `research/stepm_checks/sweep_scale_<date>.json` (settings, seeds, replicate table, code commit) and a methodology-ledger line that cites it. It writes no database row.

Decision rule (a proposal; the lead sets it in the ledger line before the run, because it is a pre-registered gate constant): the sweep is declared at the full N_cells if `reversal_21` stays selected in at least 90 percent of replicates at n_eff = N_cells and Student t tails; if it does not, the ledger line names the largest N_cells at which it does (rerun the same script on a grid of N_cells) and the sweep is restricted to that many cells (for example horizons 1 and 5 only, or a feature subset chosen by admission gates that never read returns). Either way `n_looks` for the sweep declaration is the number of cells the batch measures (E21 rule 6); the check decides whether the batch is allowed to be that large.

Tests (`tests/unit/research/`): the null generator has mean zero and the stated MA structure per horizon (autocorrelation at lag h-1 near the moving-sum value, zero beyond); the factor model hits its n_eff within a tolerance; seeds are positional (replicate r is identical alone and inside a batch); `N_cells = 0` reproduces the recorded StepM output bit for bit; a planted effect (a null cell with a mean of 5 standard errors) is selected, so the script can fail.

Cost (estimate from the code, to be replaced by one timing step first): `stepm` in "draw" mode calls `hac_mean_test` once per (draw, series), 2,000 x about 1,124 = 2.2 million calls per run, each on about 5,000 sessions with a Newey-West lag near 9 and one `student_t.sf`: about 0.15 to 0.3 ms, so 6 to 11 minutes and about 70 MB (`t_star` 18 MB plus the 5,000 x 1,124 matrix) per run in one process. 3 n_eff settings x 2 tail settings x 8 replicates = 48 runs = 5 to 9 core-hours; at 4 workers (one process per replicate, the thermal budget key `infra.feature_factory.workers` untouched) about 1.3 to 2.3 hours wall. Cut to the Student-t sets first (24 runs, 0.7 to 1.2 hours). Step 0 of the build is to time 1,000 `_draw_t` calls on a 5,000-session column and replace this estimate with the measured number in this file.

Failure modes: a null cell family that is easier or harder than real IC series (the check bounds, it does not predict: say so in the ledger line); n_eff = N_cells is pessimistic because real cells share structure, so a pass there is decisive and a fail is not; seeds drawn from the clock would make the result unrepeatable; a recorded series with a short span meets the +inf rule in `_draw_t` (conservative by design), which is correct; running beside a live heavy job (guarded launcher pattern in `docs/operations/guarded-run-runbook.md`, DIMM watchdog, one heavy job at a time); letting the output become a real-data look (it reads recorded series only and opens no run row).

Gates: unit tests by exit code, ruff, black, glossary, `/simplify` and `/review`, then the run and the ledger line. Blocks: 671 is independent, both gate the first IC pass (ledger 2026-11-24f). Order: after the corpus pilot and the family 10 counted runs (it needs the final recorded universe; the 16 series today are enough to build and test it).

## Questions the lead must settle before the build

1. E21 rule 6 says `n_looks` equals the cells the batch measures, while this todo's old text said the check "sets n_looks". The spec above reads it as a go or no-go on the batch size. Confirm.
2. The decision rule constants (90 percent, the replicate count, the tail setting) are proposals.
