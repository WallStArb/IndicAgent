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
  - tests/unit/test_circular_block_bootstrap.py
  - docs/analysis/ic-discovery-report-2026-06-21.md
  - docs/analysis/ic-discovery-report-2026-06-21.json
autonomous: true

must_haves:
  truths:
    - "Circular block bootstrap CI width shrinks as N increases on AR(1) synthetic data"
    - "Circular block bootstrap CI is wider with larger block_size on correlated data (accounts for more autocorrelation)"
    - "Circular wrap verified: start index near n wraps correctly without index error"
    - "Vectorized IC matches scipy.stats.spearmanr to 1e-10"
    - "forward_return_writer forward return = ln(open[T+2]/open[T+1]) with no lookahead bias"
    - "multipletests preserves input order -- q-value at index i maps to p-value at index i"
    - "IC engine second run inserts 0 new rows (idempotent)"
    - "regime column is non-null after labeler with canonical text labels"
    - "Forward-filter decoding produces different results than full-sequence Viterbi on a known test sequence"
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
    - path: "tests/unit/test_circular_block_bootstrap.py"
      provides: "Circular block bootstrap CI statistical correctness: CI shrinks with N, wider with larger block_size on autocorrelated data, circular wrap handles edge indices"
      contains: "_circular_block_bootstrap_ic"
  key_links:
    - from: "test_ic_engine_vectorized.py"
      to: "ic_engine vectorized IC function"
      via: "import + assert abs(ic_vec - spearmanr) < 1e-10"
      pattern: "1e-10"
    - from: "test_causal_hmm_decoding.py"
      to: "regime_writer._causal_decode()"
      via: "construct deterministic 20-bar sequence; assert causal decode != Viterbi on same input"
      pattern: "_causal_decode"
---

<objective>
Lock in correctness with unit tests for every statistical gate -- including a new test for causal HMM decoding correctness -- and produce the IC discovery report in both markdown and JSON formats.

Purpose: FDR is necessary but not sufficient; tests prove the math is right and walk-forward is the real guard (Renaissance mandate #4). The causal HMM test specifically verifies that _causal_decode() and hmmlearn Viterbi produce DIFFERENT outputs on a deterministic sequence where causality matters.

ADDITIONS IN THIS REVISION (from REVIEWS.md):
- test_causal_hmm_decoding.py: new test proving forward-filter != full-sequence Viterbi (HIGH review issue #1)
- test_circular_block_bootstrap.py: statistical correctness tests for the bootstrap implementation

Note: IC discovery report (markdown + JSON) and corpus runs are deferred to P8 (require full corpus in feature_ic_scores).

Output: 6 unit tests (all GREEN).
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
  <name>Task 1: Unit tests for vectorized IC, BH-FDR mapping, outcome labeler math, causal HMM decoding, and circular block bootstrap</name>
  <files>tests/unit/test_ic_engine_vectorized.py, tests/unit/test_bh_fdr_mapping.py, tests/unit/test_forward_return_writer.py, tests/unit/test_causal_hmm_decoding.py, tests/unit/test_circular_block_bootstrap.py</files>
  <read_first>
    - services/ic_engine.py (the vectorized IC function + BH-FDR call -- import the actual functions; refactor a pure helper out if the IC math is inline so it is unit-testable)
    - services/forward_return_writer.py (forward return formula -- extract or replicate the ln(open[T+N+1]/open[T+1]) computation as a pure function if it is SQL-only)
    - services/regime_writer.py (_causal_decode() function -- this must be importable as a pure function)
    - tests/unit/ (existing test style: pytest, no DB for pure-math tests, fixtures)
    - .planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md (Validation Architecture: tests 1,2,3)
    - CLAUDE.md (Tests section; unit tests must be CI-clean, no live DB)
  </read_first>
  <action>
    BEFORE writing any test, verify these pure module-level functions exist and are importable
    from their respective service modules. If any is still inline, refactor it out FIRST:

    - services/ic_engine.py: `compute_ic_vectorized(X: np.ndarray, y: np.ndarray) -> np.ndarray`
      (the vectorized Pearson-on-ranks IC; used in the main loop and in walk-forward folds)
    - services/ic_engine.py: `_circular_block_bootstrap_ic(ranks_X, ranks_Y, block_size, n_boot, rng)`
      (already mandated as module-level in P6 action; verify it is, not nested)
    - services/forward_return_writer.py: `forward_log_return(opens: np.ndarray, n: int) -> np.ndarray`
      (pure Python/numpy; extracts the ln(open[T+N+1]/open[T+1]) formula from SQL for unit testing)
    - services/regime_writer.py: `_causal_decode(obs_matrix, means, covars, transmat, n_components)`
      (already module-level from P4; verify it remains so after P5 edits)
    - services/regime_writer.py: `_build_label_map(means: np.ndarray) -> dict[int, str]`
      (pure label assignment helper; must be module-level for Task 2 test)

    Extraction is NOT conditional. These functions MUST be importable before any test is written.
    Update the service to call the helper if extraction is needed.

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

    Create tests/unit/test_circular_block_bootstrap.py (NEW — closes FLAG 2 from council review):
    This tests the most novel statistical component directly. Import _circular_block_bootstrap_ic from services.ic_engine (refactor to module-level pure function if needed).

    Test 1 — CI shrinks with N (statistical consistency):
      - Synthesize two AR(1) sequences X (n=500, phi=0.3) and Y (n=500) with fixed rng seed.
      - Compute CI with n=100 (first 100 obs) and n=500 (all obs), block_size=10, n_boot=500.
      - Assert CI width (upper - lower) at n=500 < CI width at n=100 for all features.
      - This verifies the bootstrap is producing meaningful uncertainty estimates that improve with data.

    Test 2 — CI wider with larger block_size on correlated data:
      - Synthesize AR(1) with phi=0.7 (high autocorrelation), n=300, fixed seed.
      - Compute CI with block_size=5 and block_size=50, n_boot=500.
      - Assert mean CI width at block_size=50 > mean CI width at block_size=5.
      - This verifies the bootstrap correctly accounts for autocorrelation structure.

    Test 3 — Circular wrap correctness:
      - Call _circular_block_bootstrap_ic with n=20, block_size=7 (forces wrap: 7*3=21 > 20).
      - Assert no IndexError raised; output shape is (n_boot, n_features); all values finite.

    Test 4 — Determinism:
      - Two calls with identical rng seed produce identical ci_lower, ci_upper arrays.
      - rng = np.random.default_rng(42)

    All tests: pure numpy, no DB, no Kafka.
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
    - All pure functions importable without DB: `.venv/bin/python -c "from services.ic_engine import compute_ic_vectorized, _circular_block_bootstrap_ic; from services.regime_writer import _causal_decode, _build_label_map; print('ok')"` exits 0
    - `.venv/bin/pytest tests/unit/test_circular_block_bootstrap.py -q` exits 0
    - `grep -c "_circular_block_bootstrap_ic" tests/unit/test_circular_block_bootstrap.py` returns >= 4 (one call per test)
    - CI width shrinks test present: `grep -c "CI width\|ci_width\|upper - lower\|upper-lower" tests/unit/test_circular_block_bootstrap.py` returns >= 1
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

</tasks>

<verification>
- All 6 unit tests green: vectorized IC == scipy 1e-10; FDR order preserved; forward return causal; idempotency + regime labels verified; causal HMM forward-filter != Viterbi
- Circular block bootstrap: CI shrinks with N, wider with larger block_size, circular wrap correct, deterministic
- Full tests/unit/ suite green
- IC discovery report and corpus runs deferred to P8
</verification>

<success_criteria>
- All task acceptance criteria pass
- .venv/bin/pytest tests/unit/ -q exits 0
</success_criteria>

<output>
After completion, create `.planning/phases/138-ic-engine-forward-returns/138-07-SUMMARY.md` documenting the 6 test files written, key assertions (IC tolerance, causal HMM delta, bootstrap CI behavior), and full unit suite green count. Note that corpus runs and the IC discovery report are in P8.
</output>
