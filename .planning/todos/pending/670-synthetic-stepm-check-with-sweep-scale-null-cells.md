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

Null cells (the only invented data), each of the base cells (N_cells = 1,108) on the recorded calendar, entered with its mirror:
1. Mean exactly zero, so every null cell is true under H0. Each base cell enters twice, as itself and as its negation (ledger 2026-11-24i: two attempts per cell), so the null block has 2 x 1,108 = 2,216 columns. The check measures the price of the multiplicity, never power.
2. Overlap memory by horizon. A cell at horizon h in {1, 2, 5, 10} sessions is a moving sum of h iid session shocks rescaled to unit variance (an MA(h-1) series, as E17 documents for overlapping targets). Cells are split evenly over the four horizons.
3. Scale. Per-session pooled IC of a null feature has a standard deviation near 1/sqrt(N_names) (about 0.02 to 0.03 at the 1d panel width); draw each cell's scale from that range. Scale does not move a studentized t, so state it but do not tune it.
4. Dependence, a k-factor model with loading matrix chosen so the average absolute pairwise correlation reproduces a stated effective breadth n_eff (ledger section 5: effective breadth about 8.4 of 230 raw features). Three settings: n_eff = 8 (the recorded breadth), n_eff = 50, and n_eff = N_cells (independent cells, the worst case and the bound). After the corpus exists, add a fourth setting that uses the stored-column correlation matrix; the check is valid and decisive without it.
5. Tails. Shocks are Student t with 5 degrees of freedom (unit variance), because per-session IC is not Gaussian. A Gaussian replicate set is run alongside as a comparison.
6. Missingness. Real cells have warmup NaNs: mask each null cell's first w sessions (w from 0 to 252, drawn per cell) so the per-draw studentization sees unequal spans.

Procedure: for each (n_eff setting, tail setting), R = 8 replicates. Replicate r draws the null block with seed `base + r` (seed by position, never from the clock) and runs `stepm(series=[recorded 16 | null block], block_mean, max_horizon_sessions=10, reps, fwer, seed=187)` with studentize="draw". Report, per setting: for each recorded series, the share of replicates in which it stays selected, its median and range of adjusted p, and the count of null cells selected (false selections; each should be 0 at fwer 0.05 in nearly every replicate, and the share is itself a size check of the correction at sweep scale). Also run one replicate with N_cells = 0 and confirm it reproduces the recorded adjusted p-values exactly (a regression guard on the script's wiring).

Writes: one JSON file `research/stepm_checks/sweep_scale_<date>.json` (settings, seeds, replicate table, code commit) and a methodology-ledger line that cites it. It writes no database row.

Decision rule: none. Ruling 2026-11-24i makes this check a disclosure, not a gate: `n_looks` is the cells the batch measures and the check cannot shrink a batch (E21 rule 6). The report states, per setting, how often `reversal_21` and each other recorded selection stays selected and the step-1 critical t; the lead's ledger line quotes it before the sweep. The 90 percent figure of the earlier draft is withdrawn.

Settings declaration: before the first run, a dated line appended to `docs/plans/methodology-change-ledger.md` declares the replicate count, the effective-breadth set, the tail settings and the seed base (the APR exempt-gate-constants row), mirrored as named constants in the script. Changing one afterwards is a new dated line.

Tests (`tests/unit/research/`): the null generator has mean zero and the stated MA structure per horizon (autocorrelation at lag h-1 near the moving-sum value, zero beyond); the factor model hits its n_eff within a tolerance; seeds are positional (replicate r is identical alone and inside a batch); `N_cells = 0` reproduces the recorded StepM output bit for bit; a planted effect (a null cell with a mean of 5 standard errors) is selected, so the script can fail.

Cost (estimate from the code, to be replaced by one timing step first): `stepm` in "draw" mode calls `hac_mean_test` once per (draw, series), 2,000 x about 1,124 = 4.5 million calls per run (2,216 mirrored null columns plus the recorded 16), each on about 5,000 sessions with a Newey-West lag near 9 and one `student_t.sf`: about 0.15 to 0.3 ms, so 11 to 22 minutes and about 70 MB (`t_star` 18 MB plus the 5,000 x 1,124 matrix) per run in one process. 3 n_eff settings x 2 tail settings x 8 replicates = 48 runs = 9 to 18 core-hours; at 4 workers (one process per replicate, the thermal budget key `infra.feature_factory.workers` untouched) about 2.5 to 4.5 hours wall. Cut to the Student-t sets first (24 runs, 1.2 to 2.2 hours). A mirrored column's bootstrap t is the negation of its twin's, so the script may skip recomputing it and fill by negation only if the result is bit-identical to the shipped path on a small case (a test); otherwise run the shipped path unchanged. Step 0 of the build is to time 1,000 `_draw_t` calls on a 5,000-session column and replace this estimate with the measured number in this file.

Failure modes: a null cell family that is easier or harder than real IC series (the check bounds, it does not predict: say so in the ledger line); n_eff = N_cells is pessimistic because real cells share structure, so a pass there is decisive and a fail is not; seeds drawn from the clock would make the result unrepeatable; a recorded series with a short span meets the +inf rule in `_draw_t` (conservative by design), which is correct; running beside a live heavy job (guarded launcher pattern in `docs/operations/guarded-run-runbook.md`, DIMM watchdog, one heavy job at a time); letting the output become a real-data look (it reads recorded series only and opens no run row).

Gates: unit tests by exit code, ruff, black, glossary, `/simplify` and `/review`, then the run and the ledger line. Blocks: 671 is independent, both gate the first IC pass (ledger 2026-11-24f). Order: after the corpus pilot and the family 10 counted runs (it needs the final recorded universe; the 16 series today are enough to build and test it).

## Decisions (methodology-change-ledger 2026-11-24i, `docs/plans/methodology-change-ledger.md:1800`)

1. This check is a disclosure, not a gate (E21 rule 6: `n_looks` is the cells measured, never a cap). Its settings are declared in a dated ledger line before it runs. The 90 percent rule is a placeholder and is withdrawn.
2. The null universe mirrors the sweep's two attempts per cell (long and mirrored short): 2,216 null columns. The measured critical-t figures are in that ledger line; the full table with the options is in commit 0265b878b of this file.
3. The sweep stays behind the prior-driven families (design note 2026-11-24), behind this check and 671, and behind a ledger line stating its cell list.

## Build status 2026-11-24 (indicagent-94)

Built and unit-tested on the local branch `wip/670-671-sweep-recorder` (commits 5b961344b and 6eb4540a2, base a70e73758), not pushed. Held: `repro_frozen` (needs the heavy slot) and the push (the branch edits `ledger.py`, `ic_measure.py` and `select_books.py`; it lands only while no pilot or counted run imports them, on the lead's word). The cell lookup is domain-qualified (`_FEATURE_DOMAINS`) instead of widening `_RESEARCH_DOMAINS`, because `ctf_momentum` is both a family and a feature. Migration 618 adds `alpha.ic_sweep.min_names_per_session`. No integration test of the `record_sweep_block` SQL exists (todo 656); the first real block is its test. 670 timing measured: about 81 microseconds per bootstrap draw, about 6 to 8 minutes per StepM run.
