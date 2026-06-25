---
phase: 140-ic-engine-correctness
plan: P3
type: execute
wave: 2
depends_on: [P1]
files_modified:
  - services/ensemble_trainer.py
  - tests/unit/test_ensemble_meta_fdr.py
autonomous: true

must_haves:
  truths:
    - "EnsembleTrainer computes each feature's FDR pass-rate over the ENSEMBLE-ELIGIBLE universe (is_pooled=false, reliable=true, ic_sharpe IS NOT NULL, passes_walkforward=true) once, before the per-stratum loop"
    - "A feature is excluded from all strata unless its FDR pass-rate >= alpha.ensemble.meta_fdr_min_fraction"
    - "The meta-gate logs the number of eligible features, total features, and total cells evaluated"
    - "_process_stratum filters ic_rows to meta-eligible features only"
  artifacts:
    - path: "services/ensemble_trainer.py"
      provides: "Meta-level FDR gate precompute + per-stratum filter"
      contains: "meta_fdr_min_fraction"
  key_links:
    - from: "EnsembleTrainer.execute meta-FDR precompute"
      to: "_process_stratum ic_rows filter"
      via: "meta_eligible_features set passed into stratum processing"
      pattern: "meta_eligible_features"
    - from: "feature_ic_scores.passes_fdr (ensemble-eligible rows only)"
      to: "fdr_pass_rate aggregation"
      via: "GROUP BY feature_name over the ensemble eligibility universe"
      pattern: "fdr_pass_rate"
---

<objective>
Add a meta-level false-discovery gate to the ensemble trainer: a feature must pass BH-FDR in at least `alpha.ensemble.meta_fdr_min_fraction` (default 50%) of the ensemble-eligible (symbol, tf) cells before it can receive ensemble weight.

Purpose: BH-FDR is currently applied per (symbol, tf) cell — 232 separate corrections at α=0.05. A feature passing FDR in only a handful of cells could be a pure chance discovery, yet the ensemble trainer's query never filters on `passes_fdr` at all. The meta-gate requires cross-universe evidence before a feature is trusted.

Output: A one-time precompute step in `EnsembleTrainer.execute()` that builds the eligibility set, plus a filter inside `_process_stratum`.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/140-ic-engine-correctness/140-RESEARCH.md
@CLAUDE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Meta-FDR precompute + per-stratum filter in ensemble_trainer.py</name>
  <read_first>
    - services/ensemble_trainer.py (lines 77-88 _cfg_* helpers; lines 168-232 execute(); lines 234-268 _process_stratum and the ic_rows query — note its exact WHERE clause)
    - .planning/phases/140-ic-engine-correctness/140-RESEARCH.md (Issue 3, "Meta-FDR Gate", Pitfall 5, the Issue 3 fix-pattern code block — and the actual per-stratum ic_rows query at lines 138-144 which defines the ensemble eligibility universe)
    - CLAUDE.md (asyncpg: pass dicts not json; structlog no event= kwarg; exception var name is error)
  </read_first>
  <action>
    NOTE: `alpha.ensemble.meta_fdr_min_fraction` (default 0.50) was seeded by migration 171 (plan P1).

    CRITICAL — DENOMINATOR MUST MATCH WHAT THE ENSEMBLE ACTUALLY CONSUMES. The per-stratum ic_rows query
    (research lines 138-144) selects features under
    `is_pooled = false AND passes_walkforward = true AND reliable = true AND ic_sharpe IS NOT NULL`.
    The meta-FDR pass-rate denominator MUST use the same eligibility universe, otherwise cells the ensemble
    never consumes (rows that fail walk-forward or have NULL ic_sharpe) artificially deflate every feature's
    pass-rate and silently suppress valid features. Before writing the query, confirm the exact column names in
    services/ensemble_trainer.py's ic_rows WHERE clause (the research cites `passes_walkforward`; verify it has
    not been renamed) and mirror them precisely.

    1. In `EnsembleTrainer.execute()` (services/ensemble_trainer.py), after the existing
       `cfg = await _load_apr(conn)` block and the other `_cfg_*` reads (~line 178), add:
       ```
       meta_fdr_min_fraction = _cfg_float(cfg, "alpha.ensemble.meta_fdr_min_fraction", 0.50)
       ```
       Include it in the existing `ensemble_trainer.config_loaded` log line.
       Add a short comment that 0.50 is a conservative starting value: it favors broad, stable factors and may
       suppress niche features that are genuinely strong in only a subset of symbols/TFs — revisit the APR value
       after measuring the empirical pass-rate distribution from the first clean corpus run. (No code branch for
       this; the gate value is APR-tunable.)

    2. After `_assert_prerequisites(conn)` and BEFORE the strata loop, compute the eligibility set ONCE over the
       ensemble-eligible universe (mirror the per-stratum WHERE clause exactly):
       ```
       fdr_pass_rows = await conn.fetch(
           """
           SELECT feature_name,
                  SUM(CASE WHEN passes_fdr THEN 1 ELSE 0 END)::float / COUNT(*) AS fdr_pass_rate,
                  COUNT(*) AS n_cells
           FROM feature_ic_scores
           WHERE is_pooled = false
             AND reliable = true
             AND ic_sharpe IS NOT NULL
             AND passes_walkforward = true
           GROUP BY feature_name
           """
       )
       meta_eligible_features = _meta_eligible(fdr_pass_rows, meta_fdr_min_fraction)
       n_total_cells = sum(r["n_cells"] for r in fdr_pass_rows)
       self.logger.info(
           "ensemble_trainer.meta_fdr_gate",
           n_eligible=len(meta_eligible_features),
           n_total_features=len(fdr_pass_rows),
           min_fraction=meta_fdr_min_fraction,
           n_total_cells_evaluated=n_total_cells,
       )
       ```
       (`_meta_eligible` is the pure helper added in Task 2.)
       Per Pitfall 5: if coverage looks materially incomplete, emit a
       `self.logger.warning("ensemble_trainer.meta_fdr_low_coverage", ...)`. Use the relative-coverage heuristic:
       `max_cells = max((r["n_cells"] for r in fdr_pass_rows), default=0)`; warn when
       `fdr_pass_rows and min(r["n_cells"] for r in fdr_pass_rows) < 0.10 * max_cells`. This needs no new APR key
       (it is a relative-coverage heuristic, not a tunable threshold). Note the denominator is now the
       ensemble-eligible universe, so this heuristic compares features against the best-covered feature within
       that same universe.

    3. Pass `meta_eligible_features` into `_process_stratum`: add a parameter
       `meta_eligible_features: set[str]` to the `_process_stratum` signature and to the call site in the
       strata loop.

    4. Inside `_process_stratum`, immediately after `ic_rows = await conn.fetch(...)` (and before the
       `if not ic_rows:` guard, or right after fetching), filter:
       ```
       ic_rows = [r for r in ic_rows if r["feature_name"] in meta_eligible_features]
       ```
       Keep the existing `if not ic_rows: ... return` guard so an empty post-filter stratum is skipped cleanly.

    Do NOT modify select_features_per_stratum, weight derivation, or the cluster-deflation logic.
  </action>
  <verify>
    - `.venv/bin/ruff check services/ensemble_trainer.py` — clean
    - `grep -n "meta_fdr_min_fraction\|meta_eligible_features\|meta_fdr_gate" services/ensemble_trainer.py` shows the config read, the set, the log, and the filter
    - `grep -n "passes_walkforward" services/ensemble_trainer.py` confirms the meta-FDR query mirrors the ensemble eligibility universe (also verify `ic_sharpe IS NOT NULL` and `reliable = true` in the same query)
    - `grep -n "feature_name.*meta_eligible_features" services/ensemble_trainer.py` confirms the ic_rows filter
    - `python -c "import ast; ast.parse(open('services/ensemble_trainer.py').read())"` — parses
  </verify>
  <acceptance_criteria>
    - Source: `meta_fdr_min_fraction = _cfg_float(cfg, "alpha.ensemble.meta_fdr_min_fraction", 0.50)` present in execute(), with a comment noting 0.50 is conservative and the APR value should be revisited after the first clean corpus run.
    - Source: a single aggregation query computes `fdr_pass_rate` GROUP BY feature_name over the ENSEMBLE-ELIGIBLE universe — `is_pooled=false AND reliable=true AND ic_sharpe IS NOT NULL AND passes_walkforward=true` (matching the per-stratum ic_rows WHERE clause) — before the strata loop.
    - Source: `meta_eligible_features` set built via `_meta_eligible(...)` and passed into `_process_stratum`.
    - Source: `_process_stratum` filters `ic_rows` to `r["feature_name"] in meta_eligible_features`.
    - Source: `ensemble_trainer.meta_fdr_gate` info log emits n_eligible, n_total_features, min_fraction, n_total_cells_evaluated; a relative-coverage low-coverage warning exists.
    - Behavior: file parses and lints clean.
  </acceptance_criteria>
  <done>Features that pass FDR in fewer than 50% of ENSEMBLE-ELIGIBLE (symbol, tf) cells are excluded from every ensemble stratum; the denominator matches what the ensemble actually consumes.</done>
</task>

<task type="auto">
  <name>Task 2: Unit test for meta-FDR eligibility logic</name>
  <read_first>
    - services/ensemble_trainer.py (the meta-FDR precompute added in Task 1)
    - tests/unit/ (an existing ensemble or trainer test for fixture/style conventions, e.g. any test importing from services.ensemble_trainer)
  </read_first>
  <action>
    To keep the eligibility logic unit-testable without a live DB, extract the pure decision into a small
    module-level helper in services/ensemble_trainer.py:
    ```
    def _meta_eligible(fdr_pass_rows: list[dict], min_fraction: float) -> set[str]:
        return {r["feature_name"] for r in fdr_pass_rows if r["fdr_pass_rate"] >= min_fraction}
    ```
    and call it from `execute()` instead of an inline set comprehension.

    Create `tests/unit/test_ensemble_meta_fdr.py` that:
    - Builds `fdr_pass_rows` like `[{"feature_name":"momentum_z_fast","fdr_pass_rate":0.60,"n_cells":200},
      {"feature_name":"noise_feat","fdr_pass_rate":0.10,"n_cells":200},
      {"feature_name":"edge_feat","fdr_pass_rate":0.50,"n_cells":150}]`.
    - Asserts `_meta_eligible(rows, 0.50) == {"momentum_z_fast", "edge_feat"}` (>= is inclusive at the boundary).
    - Asserts `_meta_eligible(rows, 0.50)` excludes `"noise_feat"`.
    - Asserts a stricter `_meta_eligible(rows, 0.70)` returns the empty set.
  </action>
  <verify>
    - `.venv/bin/pytest tests/unit/test_ensemble_meta_fdr.py -q` — pass
    - `grep -n "_meta_eligible" services/ensemble_trainer.py` shows helper defined and called
  </verify>
  <acceptance_criteria>
    - Source: `_meta_eligible(fdr_pass_rows, min_fraction)` helper exists and is used inside `execute()`.
    - Test: `tests/unit/test_ensemble_meta_fdr.py` asserts boundary-inclusive selection at 0.50 and empty set at 0.70.
    - Test: `.venv/bin/pytest tests/unit/test_ensemble_meta_fdr.py -q` passes.
  </acceptance_criteria>
  <done>The meta-FDR eligibility rule is covered by a deterministic unit test independent of the database.</done>
</task>

</tasks>

<verification>
- `.venv/bin/ruff check services/ensemble_trainer.py` — clean
- `.venv/bin/pytest tests/unit/test_ensemble_meta_fdr.py -q` — pass
- `.venv/bin/pytest tests/unit/ -q` — no new failures
</verification>

<success_criteria>
- Meta-FDR pass-rate computed once per run across the ensemble-eligible (symbol, tf) universe
- Features below alpha.ensemble.meta_fdr_min_fraction excluded from all strata
- Eligibility rule unit-tested
</success_criteria>

<output>
After completion, create `.planning/phases/140-ic-engine-correctness/140-P3-SUMMARY.md`
</output>
</content>
