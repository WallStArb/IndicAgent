---
phase: 138-ic-engine-forward-returns
plan: 05
type: execute
wave: 4
depends_on: ["138-04"]
files_modified:
  - tests/unit/test_ic_engine_vectorized.py
  - tests/unit/test_forward_return_writer.py
  - tests/unit/test_bh_fdr_mapping.py
  - tests/unit/test_ic_engine_idempotency.py
  - tests/unit/test_regime_writer.py
  - docs/analysis/ic-discovery-report-2026-06-21.md
autonomous: true

must_haves:
  truths:
    - "Vectorized IC matches scipy.stats.spearmanr to 1e-10"
    - "forward_return_writer forward return = ln(open[T+2]/open[T+1]) with no lookahead bias"
    - "multipletests preserves input order — q-value at index i maps to p-value at index i"
    - "IC engine second run inserts 0 new rows (idempotent)"
    - "regime column is non-null after labeler with canonical text labels"
    - "IC discovery report exists with passing-features table by regime and TF"
    - "tests/unit/ is fully GREEN"
  artifacts:
    - path: "tests/unit/test_ic_engine_vectorized.py"
      provides: "Vectorized IC == scipy.spearmanr assertion"
      contains: "spearmanr"
    - path: "tests/unit/test_forward_return_writer.py"
      provides: "No-lookahead-bias forward return assertion"
      contains: "open"
    - path: "tests/unit/test_bh_fdr_mapping.py"
      provides: "BH-FDR order-preservation assertion"
      contains: "multipletests"
    - path: "tests/unit/test_ic_engine_idempotency.py"
      provides: "Idempotency assertion"
      contains: "DO NOTHING"
    - path: "tests/unit/test_regime_writer.py"
      provides: "Canonical regime label assertion"
      contains: "regime"
    - path: "docs/analysis/ic-discovery-report-2026-06-21.md"
      provides: "IC discovery report"
      contains: "IC Sharpe"
  key_links:
    - from: "test_ic_engine_vectorized.py"
      to: "ic_engine vectorized IC function"
      via: "import + assert abs(ic_vec - spearmanr) < 1e-10"
      pattern: "1e-10"
    - from: "ic_engine run output"
      to: "docs/analysis/ic-discovery-report-{date}.md"
      via: "feature_ic_scores query -> markdown table"
      pattern: "ic-discovery-report"
---

<objective>
Lock in correctness with unit tests for every statistical gate, and produce the IC discovery report — the human-readable output that tells us which features carry real edge by regime and TF.

Purpose: FDR is necessary but not sufficient; tests prove the math is right and walk-forward is the real guard (Renaissance mandate #4). The report is the deliverable a quant reads.
Output: 5 unit tests (all GREEN) + docs/analysis/ic-discovery-report-{date}.md.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md
@CLAUDE.md
@docs/plans/2026-06-20-alphaengine-ic-spec.md
@services/ic_engine.py
@services/forward_return_writer.py
@services/regime_writer.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Unit tests for vectorized IC, BH-FDR mapping, and outcome labeler math</name>
  <files>tests/unit/test_ic_engine_vectorized.py, tests/unit/test_bh_fdr_mapping.py, tests/unit/test_forward_return_writer.py</files>
  <read_first>
    - services/ic_engine.py (the vectorized IC function + BH-FDR call — import the actual functions; refactor a pure helper out if the IC math is inline so it is unit-testable)
    - services/forward_return_writer.py (forward return formula — extract or replicate the ln(open[T+N+1]/open[T+1]) computation as a pure function if it is SQL-only)
    - tests/unit/ (existing test style: pytest, no DB for pure-math tests, fixtures)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Validation Architecture: tests 1,2,3)
    - CLAUDE.md (Tests section; unit tests must be CI-clean, no live DB)
  </read_first>
  <action>
    If the IC math, bootstrap, FDR, or forward-return logic is buried inline in the service files, FIRST refactor a pure function out (e.g. `compute_ic_vectorized(X, y)`, `forward_log_return(opens, n)`) so it is importable and DB-free. Update the service to call the helper. This is required for unit testability.

    Create tests/unit/test_ic_engine_vectorized.py:
      - Build a deterministic numpy matrix X (n=100, 5 features) and 2 lookahead return vectors y with a fixed seed.
      - Assert: for each feature j, abs(compute_ic_vectorized(X, y)[j] - scipy.stats.spearmanr(X[:,j], y).correlation) < 1e-10.

    Create tests/unit/test_bh_fdr_mapping.py:
      - Build a known p-value array with a shuffled order (e.g. [0.9, 0.001, 0.5, 0.02, 0.8]).
      - reject, q, _, _ = multipletests(pvals, alpha=0.05, method='fdr_bh')
      - Assert q is returned in INPUT order: the q-value at index of the smallest p (0.001) is the smallest q; assert len(q)==len(pvals) and that sorting indices of pvals and q correspond (q[argmin(pvals)] == min(q)). Explicitly assert multipletests does NOT sort the output.

    Create tests/unit/test_forward_return_writer.py:
      - Synthesize an open-price array for ~100 bars.
      - Assert forward_log_return(opens, n=1)[T] == ln(opens[T+2]/opens[T+1]) for an interior T (NOT ln(opens[T+1]/opens[T])).
      - Assert the last n rows are NaN/None (complete_Nbar would be false).
      - Assert no lookahead: forward return at T uses only opens at indices > T.
  </action>
  <acceptance_criteria>
    - `.venv/bin/pytest tests/unit/test_ic_engine_vectorized.py -q` exits 0
    - `.venv/bin/pytest tests/unit/test_bh_fdr_mapping.py -q` exits 0
    - `.venv/bin/pytest tests/unit/test_forward_return_writer.py -q` exits 0
    - test_ic_engine_vectorized asserts tolerance `1e-10`: `grep -c "1e-10" tests/unit/test_ic_engine_vectorized.py` returns >= 1
    - test_forward_return_writer asserts the T+2/T+1 form: `grep -c "T+2\|opens\[.*2\|+ 2\]" tests/unit/test_forward_return_writer.py` returns >= 1
    - tests use NO live DB connection (pure numpy)
  </acceptance_criteria>
  <verify>.venv/bin/pytest tests/unit/test_ic_engine_vectorized.py tests/unit/test_bh_fdr_mapping.py tests/unit/test_forward_return_writer.py -q</verify>
  <done>Three pure-math unit tests green; IC matches scipy 1e-10; FDR order preserved; forward return causal.</done>
</task>

<task type="auto">
  <name>Task 2: Idempotency + regime labeler unit tests</name>
  <files>tests/unit/test_ic_engine_idempotency.py, tests/unit/test_regime_writer.py</files>
  <read_first>
    - services/ic_engine.py (idempotency skip-set logic + ON CONFLICT)
    - services/regime_writer.py (canonical label mapping _REGIME_LABELS + state-ordering logic — extract a pure label-assignment helper if needed)
    - tests/unit/ (existing patterns for tests that need a fixture or mock conn)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Validation Architecture: tests 4 idempotency; regime canonical-label test)
  </read_first>
  <action>
    Create tests/unit/test_ic_engine_idempotency.py:
      - Unit-level: assert the dedup logic — given an existing-tuples set, the engine's "should_skip(cell)" returns True for present tuples and False for new ones. If a pure skip function does not exist, refactor one out (e.g. `cell_already_present(existing_set, feature, symbol, tf, regime, lookahead)`). Assert ON CONFLICT DO NOTHING is present in the INSERT SQL string (read the SQL constant from the module and assert "DO NOTHING" in it).

    Create tests/unit/test_regime_writer.py:
      - Refactor (if needed) a pure helper in regime_writer.py that takes fitted HMM state means and returns the integer-state -> canonical-text mapping (ordering by mean return).
      - Assert: given 3 states with means [0.0, +0.5, -0.5], the mapping yields exactly {ranging, trending_up, trending_down} and assigns trending_up to the +0.5 state, trending_down to the -0.5 state, ranging to the 0.0 state.
      - Assert all output labels are in the canonical text set and NONE is an integer string like '0'/'1'/'2'.
  </action>
  <acceptance_criteria>
    - `.venv/bin/pytest tests/unit/test_ic_engine_idempotency.py -q` exits 0
    - `.venv/bin/pytest tests/unit/test_regime_writer.py -q` exits 0
    - test_ic_engine_idempotency asserts "DO NOTHING" present: `grep -c "DO NOTHING" tests/unit/test_ic_engine_idempotency.py` returns >= 1
    - test_regime_writer asserts no integer-string labels: `grep -c "trending_up\|trending_down\|ranging" tests/unit/test_regime_writer.py` returns >= 1
  </acceptance_criteria>
  <verify>.venv/bin/pytest tests/unit/test_ic_engine_idempotency.py tests/unit/test_regime_writer.py -q</verify>
  <done>Idempotency skip logic + ON CONFLICT verified; regime canonical-label mapping verified.</done>
</task>

<task type="auto">
  <name>Task 3: Generate IC discovery report + full unit-suite green</name>
  <files>docs/analysis/ic-discovery-report-2026-06-21.md</files>
  <read_first>
    - services/ic_engine.py (report-writing function if present; if the engine already writes the report, just run it — else add a --report flag or a standalone query)
    - docs/plans/2026-06-20-alphaengine-ic-spec.md (§XVIII report path + sections)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (IC Discovery Report Format; Finding 11; Risk 6 mkdir docs/analysis/)
    - CLAUDE.md (Done-Coding SOP)
  </read_first>
  <action>
    Ensure docs/analysis/ exists (Path("docs/analysis/").mkdir(parents=True, exist_ok=True) — Risk 6). The ic_engine.py from P4 should write the report at the end of its run; if it does not yet, add a report-generation function to ic_engine.py that queries feature_ic_scores and writes docs/analysis/ic-discovery-report-{date}.md, and either run the engine again (idempotent) or add a `--report-only` mode that regenerates the report from existing feature_ic_scores without recomputing.

    Report file: docs/analysis/ic-discovery-report-2026-06-21.md with sections (IC spec §XVIII / RESEARCH.md format):
      1. Summary statistics — total tests, N passing FDR, N passing walk-forward, N with non-null IC Sharpe
      2. Per-feature table — columns: feature_name, symbol, tf, regime, lookahead_bars, ic_value, ic_ci_lower, passes_fdr, passes_walkforward, ic_sharpe (sorted, top features first)
      3. Top features by IC Sharpe
      4. Features failing both gates (count summary)
    Console output mirrors the report at INFO via structlog.

    Then run the FULL unit suite and confirm green.
  </action>
  <acceptance_criteria>
    - `ls docs/analysis/ic-discovery-report-2026-06-21.md` succeeds (file exists)
    - Report contains a passing-features table: `grep -c "passes_walkforward\|passes_fdr\|ic_sharpe\|IC Sharpe" docs/analysis/ic-discovery-report-2026-06-21.md` returns >= 1
    - Report references real symbols: `grep -c "SPY" docs/analysis/ic-discovery-report-2026-06-21.md` returns >= 1
    - `.venv/bin/pytest tests/unit/ -q` exits 0 (FULL suite green — no regression)
    - `.venv/bin/ruff check tests/unit/test_ic_engine_vectorized.py tests/unit/test_forward_return_writer.py tests/unit/test_bh_fdr_mapping.py tests/unit/test_ic_engine_idempotency.py tests/unit/test_regime_writer.py` passes
  </acceptance_criteria>
  <verify>.venv/bin/pytest tests/unit/ -q && ls -la docs/analysis/ic-discovery-report-2026-06-21.md</verify>
  <done>IC discovery report written with passing-features table; full tests/unit/ suite green.</done>
</task>

</tasks>

<verification>
- All 5 unit tests green; vectorized IC == scipy 1e-10; FDR order preserved; forward return causal; idempotency + regime labels verified
- IC discovery report exists with passing-features table by regime and TF
- Full tests/unit/ suite green
</verification>

<success_criteria>
- All task acceptance criteria pass
- .venv/bin/pytest tests/unit/ -q exits 0
- docs/analysis/ic-discovery-report-2026-06-21.md exists with all four sections
</success_criteria>

<output>
After completion, create `.planning/phases/138-ic-engine-forward-returns/138-05-SUMMARY.md` documenting the test results, the report path, and a short summary of which features carried the strongest edge (top by IC Sharpe, passing walk-forward).
</output>
