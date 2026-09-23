---
phase: 175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro
reviewed: 2026-09-23T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - CLAUDE.md
  - docs/foundation/apr-calibration-backlog.md
  - docs/foundation/instrument-tag-registry.md
  - production/migrations/346_itr_materiality_evidence_columns.sql
  - scripts/analysis/itr_materiality_shadow_diagnostic.py
  - services/tag_calibrator.py
  - src/intelligence/statistics/factor_math.py
  - tests/unit/test_factor_math.py
  - tests/unit/test_itr_materiality_shadow_diagnostic.py
  - tests/unit/test_tag_calibrator.py
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: issues_found
---

# Phase 175: Code Review Report

**Reviewed:** 2026-09-23
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Reviewed Phase 175's ITR materiality-filter addition to `TagCalibrator` (migration 346,
`factor_math.py`'s partial-loading/sign-stability/null-arm kernel, and the read-only shadow
diagnostic). The statistical kernel functions (`partial_loading`, `partial_loading_ci_low`,
`sign_stable_window_count`) are individually well-guarded and well-tested against synthetic
fixtures. However, tracing the Pass 4 null-arm BH-FDR wiring end-to-end (something the unit
tests never exercise across multiple rows in the same run) surfaced a confirmed, provable
correctness bug: a single pair with a NaN `null_arm_p_value` silently corrupts the persisted
`null_arm_bh_p` evidence column for **every** pair measured in that TagCalibrator run, not just
the offending pair. This is exactly the "silent wrong answer" class of defect this project's own
CLAUDE.md flags as worse than a crash, and it sits squarely in Pass 4's own documented F1
invariant ("BH-FDR applied exactly ONCE per run over the full p-vector"). Verified empirically
against the actual `statsmodels.stats.multitest` dependency this code calls (see CR-01 for the
reproduction). Three further design/documentation inconsistencies and two minor duplication/
dead-code items round out the findings below.

## Critical Issues

### CR-01: A single NaN `null_arm_p_value` corrupts `null_arm_bh_p` for every pair in the run

**File:** `services/tag_calibrator.py:774-805` (row construction in `measure_partial_loadings`), `services/tag_calibrator.py:1343-1349` (the Pass 4 `apply_run_level_fdr` call site)

**Issue:** `partial_loading_null_arm_p` (`src/intelligence/statistics/factor_math.py:592-675`)
documents and tests (`test_partial_loading_null_arm_p_nan_when_insufficient_finite_draws`) a real,
expected code path that returns `NaN` "when fewer than half of `n_draws` produce a finite null
statistic." `measure_partial_loadings` computes `null_p` via this function and unconditionally
appends the row to `pass4_rows` (lines 782-803) — unlike Pass 1's `_measure_pair`
(`services/tag_calibrator.py:483-487`), which explicitly filters `math.isnan(p_value)` before a
measurement is allowed into the p-vector that later feeds `apply_run_level_fdr`. Pass 4 has no
equivalent filter.

`execute()` then calls `apply_run_level_fdr(pass4_rows, materiality.null_arm_alpha,
p_key="null_arm_p_value", ...)` (line 1343) over the **entire** `pass4_rows` list in one call —
exactly the F1 "once per run, once per p-vector" invariant this module's own docstrings insist
on. `apply_run_level_fdr` passes the raw p-value list straight into `ic_math.apply_bh_fdr`, which
is a thin wrapper around `statsmodels.stats.multitest.multipletests(..., method="fdr_bh")`. That
call has no NaN handling. Verified directly against the installed dependency:

```
>>> from statsmodels.stats.multitest import multipletests
>>> multipletests([0.001, 0.002, 0.5, 0.6, 0.8], alpha=0.05, method="fdr_bh")[1]
array([0.005, 0.005, 0.75 , 0.75 , 0.8  ])
>>> multipletests([0.001, 0.002, 0.5, 0.6, 0.8, float("nan")], alpha=0.05, method="fdr_bh")[1]
array([nan, nan, nan, nan, nan, nan])
```

A single `NaN` anywhere in the input turns statsmodels' `pvals_corrected` (returned as
`null_arm_bh_p`) into an **all-NaN array**, for the whole family — not just the offending row.
(`fdrcorrection`'s internals: `pvals_corrected = np.minimum.accumulate(pvals_corrected_raw[::-1])[::-1]` — once a NaN enters that reverse-cummin chain it propagates through every earlier-ranked
entry.) `reject` (used for `null_arm_passes_fdr`, which feeds the *in-run* `decide_materiality`
call) is computed independently from `pvals_sorted <= ecdffactor*alpha` and happens to stay
NaN-free in practice, so TagCalibrator's own immediate `passes_materiality` write may look
unaffected — but the **persisted** `null_arm_bh_p` column (the value written to
`instrument_tags` via `_UPSERT_EMPIRICAL_SQL` at `services/tag_calibrator.py:1135`) is silently
`NaN` for every pair in that run.

This is not merely cosmetic: `scripts/analysis/itr_materiality_shadow_diagnostic.py:160-161`
independently re-derives `null_arm_passes` from the persisted `null_arm_bh_p` column
(`null_arm_bh_p is not None and null_arm_bh_p <= thresholds["null_arm_alpha"]`) — precisely
because, per its own docstring, it cannot trust the transient in-run reject boolean. Since
`NaN <= alpha` is always `False` and `NaN is not None` is `True`, every single row's re-derived
`null_arm_passes` becomes `False` for that entire run's data, contradicting whatever
`passes_materiality` TagCalibrator itself wrote on the same rows and corrupting the shadow
diagnostic's GATE ATTRIBUTION / NEAR MISS report (`docs/foundation/apr-calibration-backlog.md`'s
"584/2170 fail" null-arm figure would read "2170/2170 fail" for a run that happened to hit this
path). This can be triggered by ordinary corpus data (a single degenerate control/factor
alignment among hundreds of measured pairs) and is not currently covered by any test that runs
`apply_run_level_fdr`/`measure_partial_loadings` over a multi-row batch containing a NaN entry.

**Fix:** Exclude NaN p-values from the correction call itself rather than passing them through
to `apply_bh_fdr`. Minimal fix in the shared helper (also protects any future non-Pass-1 caller):

```python
def apply_run_level_fdr(
    measured: list[dict[str, Any]],
    fdr_alpha: float,
    *,
    p_key: str = "p_value",
    reject_key: str = "passes_fdr",
    adjusted_key: str = "bh_adjusted_p",
) -> None:
    if not measured:
        return
    for m in measured:
        m[reject_key] = False
        m[adjusted_key] = float("nan")
    finite_idx = [i for i, m in enumerate(measured) if not math.isnan(m[p_key])]
    if not finite_idx:
        return
    p_values = [measured[i][p_key] for i in finite_idx]
    reject, p_corrected = apply_bh_fdr(p_values, fdr_alpha)
    for i, rej, p_corr in zip(finite_idx, reject, p_corrected, strict=True):
        measured[i][reject_key] = bool(rej)
        measured[i][adjusted_key] = float(p_corr)
```

Add a regression test with >=2 pass4 rows where exactly one has `null_arm_p_value = nan`,
asserting the other rows' `null_arm_bh_p` stays a real float (not NaN).

## Warnings

### WR-01: `partial_loading()`'s incremental-R2 design matrix has no ill-conditioning gate

**File:** `src/intelligence/statistics/factor_math.py:412-433`

**Issue:** Every other linear solve in this module (`_partial_residuals`'s controls-only
regression, `partial_loading_null_arm_p`'s pinv) is gated by `check_condition_number` before the
result is trusted — this is the module's own stated design philosophy (see
`check_condition_number`'s docstring in `ic_math.py`: "shared by every linear solve against an
estimated ... matrix"). The second `lstsq` call in `partial_loading` (`full_design =
column_stack([controls_c, factor_c])`, solved to derive `r2_full`/`incremental_r2`) has no such
gate. `_partial_residuals` only guarantees `resid_factor`'s sum-of-squares exceeds `1e-10` in
absolute terms — a candidate factor that is *almost* (but not quite) a linear combination of the
controls can pass that weak absolute floor while still making `full_design` severely
ill-conditioned, producing a numerically unstable (potentially inflated) `incremental_r2` right
at the point where it matters most (the `min_incremental_r2` materiality gate).

**Fix:** Reuse `check_condition_number(full_design, condition_max)` before trusting `r2_full`,
returning NaN for `incremental_r2` (and the loading, for consistency) on gate failure, mirroring
the guard already applied to `controls_c` in `_partial_residuals`.

### WR-02: `partial_loading_ci_low`'s alpha is silently sourced from the wrong APR key

**File:** `src/intelligence/statistics/factor_math.py:455-458` (docstring) vs.
`services/tag_calibrator.py:756-763` (call site)

**Issue:** `partial_loading_ci_low`'s own docstring documents its contract: "alpha is the
caller-supplied project-standard `alpha.tag_calibrator.fdr_alpha` (0.05) rather than a new APR
key for the same two-sided alpha." The actual call site passes `materiality.null_arm_alpha`
(`alpha.tag_calibrator.materiality.null_arm_alpha`) instead — a separate, independently-tunable
APR key whose own migration comment (`production/migrations/346_itr_materiality_evidence_columns.sql:183-192`)
states its purpose is "BH-FDR alpha applied to the D-06 circular-shift null-arm p-vector," not the
CI width on `partial_loading_ci_low`. Both currently default to `0.05`, so today's behavior
matches the docstring by coincidence. The moment an operator recalibrates `null_arm_alpha`
specifically (which `docs/foundation/apr-calibration-backlog.md` explicitly earmarks for future
recalibration) they will unintentionally also widen/narrow the `min_partial_loading_ci_low` gate's
confidence interval — a coupling neither doc describes or intends.

**Fix:** Either (a) pass `config.fdr_alpha` (the actual `alpha.tag_calibrator.fdr_alpha` key) at
the `measure_partial_loadings` call site to match the documented contract, or (b) update
`partial_loading_ci_low`'s docstring to describe the actual dependency on `null_arm_alpha` and
document the intentional coupling. Given R-05's lower-CI gate is conceptually independent of the
D-06 null-arm FDR alpha, (a) is the more defensible fix.

### WR-03: `materiality_gate_failures`'s docstring undercounts the NaN-guarded field list

**File:** `services/tag_calibrator.py:845-848` (docstring) vs. `857-859` (implementation)

**Issue:** The docstring states the function returns `None` "if any of the **five** core numeric
fields is missing/NaN," but the implementation's guard loop checks **six** values:
`(sample_n, pl, pl_ci_low, inc_r2, n_stable, n_total)`. This is purely a documentation accuracy
issue (the code itself is correct and consistent with the shadow diagnostic's own comment at
`scripts/analysis/itr_materiality_shadow_diagnostic.py:146-159`, which correctly refers to "the
six core Pass 4 statistics"), but it is the single source of truth two call sites depend on and a
future maintainer trusting the docstring's count over the code risks miscounting which fields are
NaN-sensitive.

**Fix:** Change "five" to "six" in the docstring at line 846.

## Info

### IN-01: Six-gate-name tuple duplicated verbatim across two files

**File:** `services/tag_calibrator.py:808-815` (`_MATERIALITY_GATE_NAMES`) and
`scripts/analysis/itr_materiality_shadow_diagnostic.py:57-64` (`_GATE_NAMES`)

**Issue:** Both files independently declare the identical
`("sample_n", "partial_loading", "ci_low", "incremental_r2", "sign_stability", "null_arm")` tuple.
`materiality_gate_failures` itself is correctly shared (imported by the diagnostic, not
re-derived) precisely to avoid the E12-class drift this module's own comments warn about
elsewhere — but the gate-name ordering constant that iterates over that shared dict's keys is
not shared, so a future gate rename/addition in one file could silently desync iteration order
(and therefore print/report ordering) from the other without either file failing to import.

**Fix:** Export `_MATERIALITY_GATE_NAMES` from `services/tag_calibrator.py` (or move it next to
`materiality_gate_failures`) and import it in the diagnostic script instead of redeclaring.

### IN-02: Redundant `check_condition_number` call in `partial_loading_null_arm_p`

**File:** `src/intelligence/statistics/factor_math.py:637-647`

**Issue:** `observed_loading, _, _ = partial_loading(...)` (line 637) already runs
`_partial_residuals`'s `check_condition_number` gate internally and returns NaN (short-circuiting
this function at line 640-641) on ill-conditioning. The subsequent explicit
`check_condition_number(controls_c, condition_max)` call at line 645 is therefore unreachable
with a failing result whenever it would matter (any `controls_c` that fails this second check
would already have failed inside the `partial_loading()` call above and returned NaN by line 641).
Harmless (documented in the docstring as "reused for shape only" from the tsmom script), but dead
code that adds a second `np.linalg.cond` computation for no behavioral effect.

**Fix:** Optional cleanup — drop the second `check_condition_number` call and rely on the
already-computed `observed_loading` NaN-check, or leave as defensive redundancy with a comment
noting it is deliberately belt-and-suspenders.

---

_Reviewed: 2026-09-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
