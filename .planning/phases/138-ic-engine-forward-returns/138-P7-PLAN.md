---
phase: 138-ic-engine-forward-returns
plan: 07
type: execute
wave: 6
depends_on: ["138-06"]
files_modified:
  - tests/unit/test_ic_engine_vectorized.py
  - tests/unit/test_forward_return_writer.py
  - tests/unit/test_bh_fdr_mapping.py
  - tests/unit/test_ic_engine_idempotency.py
  - tests/unit/test_regime_writer.py
  - tests/unit/test_causal_hmm_decoding.py
  - docs/analysis/ic-discovery-report-2026-06-21.md
  - docs/analysis/ic-discovery-report-2026-06-21.json
autonomous: true

must_haves:
  truths:
    - "Vectorized IC matches scipy.stats.spearmanr to 1e-10"
    - "forward_return_writer forward return = ln(open[T+2]/open[T+1]) with no lookahead bias"
    - "multipletests preserves input order -- q-value at index i maps to p-value at index i"
    - "IC engine second run inserts 0 new rows (idempotent)"
    - "regime column is non-null after labeler with canonical text labels"
    - "Forward-filter decoding produces different results than full-sequence Viterbi on a known test sequence"
    - "IC discovery report (markdown) exists with passing-features table by regime and TF"
    - "IC discovery report (JSON) exists with machine-readable passing-features list for Phase 139"
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
    - path: "tests/unit/test_causal_hmm_decoding.py"
      provides: "Forward-filter vs full-Viterbi causal correctness assertion"
      contains: "_causal_decode"
    - path: "docs/analysis/ic-discovery-report-2026-06-21.md"
      provides: "IC discovery report (markdown)"
      contains: "IC Sharpe"
    - path: "docs/analysis/ic-discovery-report-2026-06-21.json"
      provides: "IC discovery report (JSON sidecar for Phase 139 automation)"
      contains: "passing_features"
  key_links:
    - from: "test_ic_engine_vectorized.py"
      to: "ic_engine vectorized IC function"
      via: "import + assert abs(ic_vec - spearmanr) < 1e-10"
      pattern: "1e-10"
    - from: "test_causal_hmm_decoding.py"
      to: "regime_writer._causal_decode()"
      via: "construct deterministic 20-bar sequence; assert causal decode != Viterbi on same input"
      pattern: "_causal_decode"
    - from: "ic_engine run output"
      to: "docs/analysis/ic-discovery-report-{date}.md and .json"
      via: "feature_ic_scores query -> markdown table + JSON artifact"
      pattern: "ic-discovery-report"
---

<objective>
Lock in correctness with unit tests for every statistical gate -- including a new test for causal HMM decoding correctness -- and produce the IC discovery report in both markdown and JSON formats.

Purpose: FDR is necessary but not sufficient; tests prove the math is right and walk-forward is the real guard (Renaissance mandate #4). The causal HMM test specifically verifies that _causal_decode() and hmmlearn Viterbi produce DIFFERENT outputs on a deterministic sequence where causality matters. The JSON sidecar enables Phase 139 ensemble construction to automate feature selection without parsing markdown.

ADDITIONS IN THIS REVISION (from REVIEWS.md):
- test_causal_hmm_decoding.py: new test proving forward-filter != full-sequence Viterbi (HIGH review issue #1)
- docs/analysis/ic-discovery-report-2026-06-21.json: machine-readable sidecar (LOW review issue #9)

Output: 6 unit tests (all GREEN) + docs/analysis/ic-discovery-report-{date}.md + docs/analysis/ic-discovery-report-{date}.json.
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
  <name>Task 1: Unit tests for vectorized IC, BH-FDR mapping, outcome labeler math, and causal HMM decoding</name>
  <files>tests/unit/test_ic_engine_vectorized.py, tests/unit/test_bh_fdr_mapping.py, tests/unit/test_forward_return_writer.py, tests/unit/test_causal_hmm_decoding.py</files>
  <read_first>
    - services/ic_engine.py (the vectorized IC function + BH-FDR call -- import the actual functions; refactor a pure helper out if the IC math is inline so it is unit-testable)
    - services/forward_return_writer.py (forward return formula -- extract or replicate the ln(open[T+N+1]/open[T+1]) computation as a pure function if it is SQL-only)
    - services/regime_writer.py (_causal_decode() function -- this must be importable as a pure function)
    - tests/unit/ (existing test style: pytest, no DB for pure-math tests, fixtures)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Validation Architecture: tests 1,2,3)
    - CLAUDE.md (Tests section; unit tests must be CI-clean, no live DB)
  </read_first>
  <action>
    If the IC math, bootstrap, FDR, or forward-return logic is buried inline in the service files, FIRST refactor a pure function out (e.g. compute_ic_vectorized(X, y), forward_log_return(opens, n)) so it is importable and DB-free. Update the service to call the helper. Required for unit testability.

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

    Create tests/unit/test_causal_hmm_decoding.py (NEW -- fixes REVIEWS.md HIGH issue #1):
    This test verifies that the causal forward-filter decoder in regime_writer._causal_decode() produces DIFFERENT results than hmmlearn GaussianHMM.predict() on a sequence designed to expose the causal difference.

    Test construction:
      - Build a deterministic 30-bar obs matrix with a sharp regime switch at bar 20: first 20 bars have positive returns, last 10 bars have strongly negative returns. With fixed random seed.
      - Fit a GaussianHMM(n_components=2) on this 30-bar sequence.
      - Decode with hmmlearn: viterbi_states = model.predict(obs_matrix)  # full-sequence Viterbi
      - Decode with causal filter: causal_states = _causal_decode(obs_matrix, model.means_, model.covars_[:,np.arange(obs_matrix.shape[1]),np.arange(obs_matrix.shape[1])], model.transmat_, 2)
        (For diag covariance, covars_ is shape [K, n_features]; extract variance vector correctly.)
      - Assert: NOT np.array_equal(viterbi_states, causal_states)
        This is the core assertion -- if they are EQUAL, the causal decoder is not actually causal (it's replicating Viterbi behavior). On a 30-bar sequence with a late regime switch, Viterbi can look backward from bar 30 to bar 1 and "know" the switch happened; the causal filter at bar 1-15 does not yet see bars 16-30 at all.
      - Assert: for bars t < 10 (before the switch), causal_states[t] must be the "pre-switch" regime (since the causal filter has only seen positive returns). Viterbi may or may not agree here depending on the sequence strength.
      - Assert: causal_states dtype is int or np.integer (not float), all values in {0, 1}.
      - Add a docstring explaining WHY this test exists: "GaussianHMM.predict() is full-sequence Viterbi. It is NOT causal. _causal_decode() is the causal forward-filter. This test verifies they differ on a sequence where future information matters -- if they agree, the causal decoder is likely implemented incorrectly."

    Ensure _causal_decode is importable from services.regime_writer (or from a shared helper module if it was extracted). If it is a nested function, refactor it to module-level before writing this test.
  </action>
  <acceptance_criteria>
    - `.venv/bin/pytest tests/unit/test_ic_engine_vectorized.py -q` exits 0
    - `.venv/bin/pytest tests/unit/test_bh_fdr_mapping.py -q` exits 0
    - `.venv/bin/pytest tests/unit/test_forward_return_writer.py -q` exits 0
    - `.venv/bin/pytest tests/unit/test_causal_hmm_decoding.py -q` exits 0
    - test_ic_engine_vectorized asserts tolerance 1e-10: `grep -c "1e-10" tests/unit/test_ic_engine_vectorized.py` returns >= 1
    - test_forward_return_writer asserts the T+2/T+1 form: `grep -c "T+2\|opens\[.*2\|+ 2\]" tests/unit/test_forward_return_writer.py` returns >= 1
    - test_causal_hmm_decoding imports _causal_decode: `grep -c "_causal_decode" tests/unit/test_causal_hmm_decoding.py` returns >= 2
    - test_causal_hmm_decoding asserts NOT array_equal: `grep -c "NOT\|not.*equal\|array_equal\|allclose" tests/unit/test_causal_hmm_decoding.py` returns >= 1
    - test_causal_hmm_decoding has docstring explaining causal vs Viterbi: `grep -c "Viterbi\|causal\|predict" tests/unit/test_causal_hmm_decoding.py` returns >= 3
    - tests use NO live DB connection (pure numpy / hmmlearn only)
  </acceptance_criteria>
  <verify>.venv/bin/pytest tests/unit/test_ic_engine_vectorized.py tests/unit/test_bh_fdr_mapping.py tests/unit/test_forward_return_writer.py tests/unit/test_causal_hmm_decoding.py -q</verify>
  <done>Four pure-math unit tests green; IC matches scipy 1e-10; FDR order preserved; forward return causal; forward-filter != Viterbi confirmed.</done>
</task>

<task type="auto">
  <name>Task 2: Idempotency + regime labeler unit tests</name>
  <files>tests/unit/test_ic_engine_idempotency.py, tests/unit/test_regime_writer.py</files>
  <read_first>
    - services/ic_engine.py (idempotency skip-set logic + ON CONFLICT; is_pooled handling in INSERT)
    - services/regime_writer.py (canonical label mapping _build_label_map() + _REGIME_LABELS + state-ordering logic -- must be a module-level pure helper)
    - tests/unit/ (existing patterns for tests that need a fixture or mock conn)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Validation Architecture: tests 4 idempotency; regime canonical-label test)
  </read_first>
  <action>
    Create tests/unit/test_ic_engine_idempotency.py:
      - Unit-level: assert the dedup logic -- given an existing-tuples set, the engine's "should_skip(cell)" returns True for present tuples and False for new ones. If a pure skip function does not exist, refactor one out (e.g. cell_already_present(existing_set, feature, symbol, tf, regime, lookahead, is_pooled)). Assert ON CONFLICT DO NOTHING is present in the INSERT SQL string (read the SQL constants from the module and assert "DO NOTHING" in them). Assert both INSERT statements (for pooled and regime rows) contain DO NOTHING.

    Create tests/unit/test_regime_writer.py:
      - Refactor (if needed) a pure helper _build_label_map() in regime_writer.py that takes fitted HMM state means (as np.ndarray shape [K, n_dims]) and returns the integer-state -> canonical-text mapping.
      - Assert: given 3 states with means[0] (log-return dim) = [-0.5, +0.5, 0.0], the mapping yields exactly {trending_down, trending_up, ranging} and assigns trending_up to the +0.5 state, trending_down to the -0.5 state, ranging to the 0.0 state.
      - Assert all output labels are in the canonical text set {"ranging", "trending_up", "trending_down"} and NONE is an integer string like '0'/'1'/'2'.
  </action>
  <acceptance_criteria>
    - `.venv/bin/pytest tests/unit/test_ic_engine_idempotency.py -q` exits 0
    - `.venv/bin/pytest tests/unit/test_regime_writer.py -q` exits 0
    - test_ic_engine_idempotency asserts "DO NOTHING" present in both INSERTs: `grep -c "DO NOTHING" tests/unit/test_ic_engine_idempotency.py` returns >= 2
    - test_regime_writer asserts no integer-string labels: `grep -c "trending_up\|trending_down\|ranging" tests/unit/test_regime_writer.py` returns >= 3
    - test_regime_writer tests is_pooled handling if relevant: `grep -c "is_pooled" tests/unit/test_ic_engine_idempotency.py` returns >= 1
  </acceptance_criteria>
  <verify>.venv/bin/pytest tests/unit/test_ic_engine_idempotency.py tests/unit/test_regime_writer.py -q</verify>
  <done>Idempotency skip logic + both ON CONFLICT statements verified; regime canonical-label mapping verified including no integer-string labels.</done>
</task>

<task type="auto">
  <name>Task 3: Generate IC discovery report (markdown + JSON sidecar) + full unit-suite green</name>
  <files>docs/analysis/ic-discovery-report-2026-06-21.md, docs/analysis/ic-discovery-report-2026-06-21.json</files>
  <read_first>
    - services/ic_engine.py (report-writing function if present; if the engine already writes the report, just run it -- else add a --report-only flag)
    - docs/plans/2026-06-20-alphaengine-ic-spec.md (§XVIII report path + sections)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (IC Discovery Report Format; Finding 11; Risk 6 mkdir docs/analysis/)
    - CLAUDE.md (Done-Coding SOP)
  </read_first>
  <action>
    Ensure docs/analysis/ exists (Path("docs/analysis/").mkdir(parents=True, exist_ok=True) -- Risk 6). The ic_engine.py from P4 should write the report at the end of its run; if it does not yet, add a report-generation function to ic_engine.py that queries feature_ic_scores and writes both output files, and add a --report-only mode that regenerates them from existing feature_ic_scores without recomputing IC.

    MARKDOWN REPORT: docs/analysis/ic-discovery-report-2026-06-21.md with sections (IC spec §XVIII / RESEARCH.md format):
      1. Summary statistics -- total tests, N passing FDR, N passing walk-forward, N with non-null IC Sharpe
      2. Per-feature table -- columns: feature_name, symbol, tf, regime, is_pooled, lookahead_bars, ic_value, ic_ci_lower, passes_fdr, passes_walkforward, ic_sharpe (sorted, top features first)
      3. Top features by IC Sharpe
      4. Features failing both gates (count summary)

    JSON SIDECAR (NEW -- fixes REVIEWS.md LOW issue #9): docs/analysis/ic-discovery-report-2026-06-21.json
    This is the machine-readable artifact for Phase 139 ensemble construction. Format:
      {
        "generated_at": "<ISO-8601 timestamp>",
        "training_window_end": "<ISO-8601 timestamp>",
        "total_cells": N,
        "cells_passing_fdr": N,
        "cells_passing_walkforward": N,
        "passing_features": [
          {
            "feature_name": "momentum_z_5",
            "symbol": "SPY",
            "tf": "5m",
            "regime": "trending_up",
            "is_pooled": false,
            "lookahead_bars": 5,
            "ic_value": 0.042,
            "ic_ci_lower": 0.011,
            "ic_sharpe": 1.23,
            "passes_fdr": true,
            "passes_walkforward": true
          },
          ...
        ]
      }
    The "passing_features" array contains ONLY rows where passes_walkforward=true. Include all columns shown above. This file enables Phase 139 to `json.load()` the passing features without parsing markdown.

    Write both files atomically (write to .tmp then rename) to avoid partial writes. Log paths at INFO after writing.

    Then run the FULL unit suite and confirm green.
  </action>
  <acceptance_criteria>
    - `ls docs/analysis/ic-discovery-report-2026-06-21.md` succeeds
    - `ls docs/analysis/ic-discovery-report-2026-06-21.json` succeeds
    - Markdown report contains a passing-features table: `grep -c "passes_walkforward\|passes_fdr\|ic_sharpe\|IC Sharpe" docs/analysis/ic-discovery-report-2026-06-21.md` returns >= 1
    - Markdown report references is_pooled column: `grep -c "is_pooled\|pooled" docs/analysis/ic-discovery-report-2026-06-21.md` returns >= 1
    - Markdown report references real symbols: `grep -c "SPY" docs/analysis/ic-discovery-report-2026-06-21.md` returns >= 1
    - JSON sidecar is valid JSON: `.venv/bin/python -c "import json; data=json.load(open('docs/analysis/ic-discovery-report-2026-06-21.json')); assert 'passing_features' in data; assert 'training_window_end' in data; print(f'passing_features: {len(data[\"passing_features\"])}')"` exits 0
    - JSON sidecar contains passing_features with expected fields: `.venv/bin/python -c "import json; d=json.load(open('docs/analysis/ic-discovery-report-2026-06-21.json')); f=d['passing_features'][0] if d['passing_features'] else {}; required={'feature_name','symbol','tf','regime','is_pooled','lookahead_bars','ic_value','ic_sharpe','passes_walkforward'}; missing=required-set(f.keys()); assert not missing, missing; print('ok')"` exits 0
    - `.venv/bin/pytest tests/unit/ -q` exits 0 (FULL suite green -- no regression)
    - `.venv/bin/ruff check tests/unit/test_ic_engine_vectorized.py tests/unit/test_forward_return_writer.py tests/unit/test_bh_fdr_mapping.py tests/unit/test_ic_engine_idempotency.py tests/unit/test_regime_writer.py tests/unit/test_causal_hmm_decoding.py` passes
  </acceptance_criteria>
  <verify>.venv/bin/pytest tests/unit/ -q && ls -la docs/analysis/ic-discovery-report-2026-06-21.md docs/analysis/ic-discovery-report-2026-06-21.json</verify>
  <done>IC discovery report (markdown + JSON) written; JSON passing_features array valid; full tests/unit/ suite green including causal HMM test.</done>
</task>

</tasks>

<verification>
- All 6 unit tests green: vectorized IC == scipy 1e-10; FDR order preserved; forward return causal; idempotency + regime labels verified; causal HMM forward-filter != Viterbi
- IC discovery report (markdown) exists with passing-features table including is_pooled column
- IC discovery report (JSON sidecar) exists with passing_features array for Phase 139 automation
- Full tests/unit/ suite green
</verification>

<success_criteria>
- All task acceptance criteria pass
- .venv/bin/pytest tests/unit/ -q exits 0
- docs/analysis/ic-discovery-report-2026-06-21.md and .json both exist
- JSON sidecar is valid and parseable by Phase 139 ensemble construction scripts
</success_criteria>

<output>
After completion, create `.planning/phases/138-ic-engine-forward-returns/138-07-SUMMARY.md` documenting the test results, the report paths, and a short summary of which features carried the strongest edge (top by IC Sharpe, passing walk-forward), plus the count in the JSON passing_features array.
</output>
