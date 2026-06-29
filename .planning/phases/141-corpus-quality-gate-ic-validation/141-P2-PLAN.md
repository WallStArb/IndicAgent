---
plan: 141-P2
phase: "141"
title: "HMM Numba JIT"
wave: 1
depends_on: [141-P0]
files_modified:
  - src/intelligence/hmm_jit.py
  - services/regime_writer.py
  - requirements.txt
  - tests/unit/intelligence/test_hmm_jit.py
autonomous: true
must_haves:
  goal: "Numba JIT forward filter implemented, tests proving numerical identity to Python reference, wired into regime_writer hot path with main-process pre-compilation (no worker race)"
  truths:
    - "requirements.txt contains a non-comment numba line (numba>=0.65.0 or similar)"
    - "src/intelligence/hmm_jit.py exports alpha_pass_jit decorated with @numba.njit(cache=True)"
    - "alpha_pass_jit signature: (log_emit: np.ndarray, log_A: np.ndarray, pi0: np.ndarray) -> tuple[np.ndarray, np.ndarray] where log_A is pre-computed log(max(transmat_, 1e-300))"
    - "test_jit_states_match_reference PASS — JIT states array-equal to Python _alpha_pass_ref for same inputs"
    - "test_jit_alpha_history_matches_reference PASS — alpha_history matches within rtol=1e-10"
    - "test_alpha_rows_sum_to_one PASS — each row of alpha_history sums to 1.0 within atol=1e-10"
    - "regime_writer.py imports alpha_pass_jit from src.intelligence.hmm_jit"
    - "regime_writer._causal_decode pre-computes log_A = np.log(np.maximum(model.transmat_, 1e-300)) and passes it to alpha_pass_jit (not model.transmat_ directly)"
    - "alpha_pass_jit is pre-compiled in the main process (before ProcessPoolExecutor) using a dummy (10, K) input so all workers load from cache; no initializer= argument needed"
    - "regime_writer ProcessPoolExecutor has no initializer= argument — warmup is in main process"
    - "regime_writer --symbols SPY --tf 5m completes without error and writes regime labels to feature_vectors"
    - ".venv/bin/pytest tests/unit/ -q exits green"
---

<objective>
Implement Numba JIT compilation for the HMM forward filter (_alpha_pass) in regime_writer.
The _alpha_pass t-loop is the corpus pipeline bottleneck: 20+ hours for a 58-symbol full run.
With @numba.njit(cache=True), subsequent runs load the compiled artifact from __pycache__
and run at LLVM native speed (~30 min total).

Scope: Only _alpha_pass (the causal t-loop). _log_emit_full and _log_emit_diag are already
vectorized numpy — leave them in Python (the try/except in _log_emit_full is incompatible
with nopython mode).

Key invariant: The JIT version must be numerically identical to the Python reference.
Tests prove this by comparing against a pure-Python reimplementation of the same algorithm.

Key design: The JIT takes log_A (pre-computed), not transmat_ (raw). The call site must
compute log_A = np.log(np.maximum(model.transmat_, 1e-300)) BEFORE calling alpha_pass_jit.
The current Python _alpha_pass computes this internally; moving it outside the JIT boundary
avoids recomputing it on every element of the t-loop.

Key placement for warmup: pre-compile in the MAIN PROCESS before spawning the
ProcessPoolExecutor. With cache=True, the main-process compile writes the artifact to
__pycache__ once; every worker subprocess then loads it read-only on first use — no
compilation, no race. Do NOT use ProcessPoolExecutor(initializer=...) for warmup: N workers
starting simultaneously with a cold cache would all try to compile and write to __pycache__
at once, causing file locks, corruption, or PermissionError. Main-process pre-compile is the
single-writer pattern that eliminates the race and is start-method agnostic (works under both
fork and spawn).

Ring 1 placement: src/intelligence/hmm_jit.py. No DB imports. No Ring 2 imports.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@docs/plans/2026-06-28-validity-fixes-and-phase-141.md
@services/regime_writer.py
@src/intelligence/
</context>

<tasks>

<task id="P2-T1" type="execute">
  <title>Write failing tests for alpha_pass_jit</title>
  <wave>1</wave>
  <read_first>
    - services/regime_writer.py:247-276 — _alpha_pass Python reference (exact algorithm to replicate)
    - docs/plans/2026-06-28-validity-fixes-and-phase-141.md — Task 8 (complete test file)
    - tests/unit/intelligence/ — verify directory exists (create if not)
  </read_first>
  <action>
    Follow Task 8 in docs/plans/2026-06-28-validity-fixes-and-phase-141.md exactly.

    Step 1 — Create tests/unit/intelligence/test_hmm_jit.py with the full test file from the doc.

    The _alpha_pass_ref function in the test file MUST be a verbatim copy of regime_writer._alpha_pass
    at lines 247-276 (current state). Verify line-by-line match before running — any divergence
    makes the reference test meaningless.

    Step 2 — Run to confirm FAIL (module does not exist yet):
      .venv/bin/pytest tests/unit/intelligence/test_hmm_jit.py -v
      Expected: ImportError on 'from src.intelligence.hmm_jit import alpha_pass_jit'

    Step 3 — Run full unit suite to confirm it was green before this change:
      .venv/bin/pytest tests/unit/ -q
      Expected: same pass count as pre-P2 baseline.
  </action>
  <acceptance_criteria>
    - tests/unit/intelligence/test_hmm_jit.py exists
    - pytest on it fails with ImportError (module not yet implemented)
    - full unit suite otherwise green
  </acceptance_criteria>
  <output_gate>tests/unit/intelligence/test_hmm_jit.py exists; pytest on it fails with ImportError; full unit suite still green</output_gate>
</task>

<task id="P2-T2" type="execute">
  <title>Implement src/intelligence/hmm_jit.py</title>
  <wave>2</wave>
  <read_first>
    - services/regime_writer.py:247-276 — _alpha_pass algorithm to replicate in Numba
    - docs/plans/2026-06-28-validity-fixes-and-phase-141.md — Task 9 (complete implementation)
    - requirements.txt:55-65 — dev/test section and the existing numba comment (line 60)
    - src/intelligence/ — confirm Ring 1 module pattern (no DB imports, no Ring 2 imports)
  </read_first>
  <action>
    Follow Task 9 in docs/plans/2026-06-28-validity-fixes-and-phase-141.md exactly.

    Step 0 — Declare numba as a real dependency:
      grep -n 'numba' requirements.txt
      The only current mention (line ~60) is a COMMENT about pandas-ta pinning numba==0.61.2.
      If there is no actual package line (only the comment), add a package entry AFTER that
      comment block:
        numba>=0.65.0
      (numba 0.65.1 is installed in the venv; >=0.65.0 is compatible with numpy>=2.4.) If a
      non-comment numba line already exists, skip — do not duplicate.

    Step 1 — Create src/intelligence/hmm_jit.py with alpha_pass_jit decorated @numba.njit(cache=True).

    The function takes:
      log_emit: (n, K) float64 — precomputed log emissions
      log_A: (K, K) float64 — pre-computed log(max(transmat_, 1e-300)); caller's responsibility
      pi0: (K,) float64 — initial state distribution

    The function must NOT take raw transmat_ — only log_A. This is intentional: moving the
    log(max(...)) computation outside the JIT boundary means it runs in Python (once per symbol)
    rather than inside the Numba-compiled t-loop.

    The algorithm in the JIT must be numerically identical to _alpha_pass in regime_writer.
    Use scalar for-loops inside the JIT (not numpy broadcasting) — Numba njit requires numpy
    calls that work in nopython mode. log-sum-exp done with explicit max + log(sum(exp(x-max))).

    Step 2 — Run tests (first run compiles JIT — expect 10-20s):
      .venv/bin/pytest tests/unit/intelligence/test_hmm_jit.py -v -s
      Expected: all PASS. Second run will be faster (cache hit).

    Step 3 — Run full unit suite:
      .venv/bin/pytest tests/unit/ -q
      Expected: all green.

    Step 4 — Commit (include requirements.txt):
      git add src/intelligence/hmm_jit.py tests/unit/intelligence/test_hmm_jit.py requirements.txt
      git commit -m "feat(intelligence): Numba JIT forward filter for HMM regime inference

      alpha_pass_jit is a drop-in for _alpha_pass in regime_writer. Takes log_A
      (pre-computed) not transmat_ to keep log(max()) outside the JIT boundary.
      cache=True: compiled once, loaded from __pycache__ on all subsequent runs.
      Declare numba>=0.65.0 as a real dependency (was comment-only).
      Target: 20+ hr regime_writer run → ~30 min."
  </action>
  <acceptance_criteria>
    - requirements.txt contains a non-comment numba line (numba>=0.65.0 or similar)
    - src/intelligence/hmm_jit.py exists with alpha_pass_jit @numba.njit(cache=True)
    - all 5 tests in test_hmm_jit.py PASS
    - full unit suite green
    - commit includes requirements.txt, hmm_jit.py, test file
  </acceptance_criteria>
  <output_gate>requirements.txt has a non-comment numba line; src/intelligence/hmm_jit.py exists; all 5 tests in test_hmm_jit.py PASS; full unit suite green; commit exists</output_gate>
</task>

<task id="P2-T3" type="execute">
  <title>Wire alpha_pass_jit into regime_writer</title>
  <wave>3</wave>
  <read_first>
    - services/regime_writer.py:39,247-276,474-492,800-880 — imports, _alpha_pass, call site, n_components APR load, ProcessPoolExecutor setup
    - src/intelligence/hmm_jit.py — verify alpha_pass_jit signature matches expected call
  </read_first>
  <action>
    Follow Task 10 in docs/plans/2026-06-28-validity-fixes-and-phase-141.md with these additions.

    Step 1 — Add import at top of regime_writer.py (after existing imports, around line 39):
      from src.intelligence.hmm_jit import alpha_pass_jit as _alpha_pass_jit

    Step 2 — Pre-compile in the MAIN PROCESS before spawning the pool (NO worker initializer).
      In run(), AFTER n_components is loaded from APR (around line 808) and BEFORE the
      ProcessPoolExecutor block, add:

        # Pre-compile in main process so all workers load from cache (no race).
        # With cache=True, the main-process compile writes __pycache__ once; workers
        # then load read-only on first use — no concurrent compile, start-method agnostic.
        import numpy as np
        _precompile_emit = np.zeros((10, n_components), dtype=np.float64)
        _precompile_log_A = np.log(np.full((n_components, n_components), 1.0 / n_components))
        _precompile_pi0 = np.full(n_components, 1.0 / n_components)
        _alpha_pass_jit(_precompile_emit, _precompile_log_A, _precompile_pi0)
        logger.info("HMM JIT pre-compiled in main process; workers will load from cache")

      Do NOT add a module-level _jit_warmup_k global, a _jit_warmup() function, or an
      `import services.regime_writer as _rw_module` hack. Those are removed by this design.

    Step 3 — ProcessPoolExecutor call site (around line 871) stays as-is — NO initializer=:
      with ProcessPoolExecutor(max_workers=n_workers) as pool:
      Workers load the pre-compiled cache on first use; no per-worker compilation, no race.

    Step 4 — Replace _alpha_pass call at line 487 with the JIT version:
      BEFORE the existing call site (which calls _alpha_pass(log_emit, model.transmat_, pi0)),
      pre-compute log_A:
        log_A = np.log(np.maximum(model.transmat_, 1e-300))
      Then change the call from:
        raw_states, alpha_history = _alpha_pass(log_emit, model.transmat_, pi0)
      to:
        raw_states, alpha_history = _alpha_pass_jit(log_emit, log_A, pi0)

    Step 5 — Smoke test on single small symbol:
      .venv/bin/python services/regime_writer.py --symbols SPY --tf 5m 2>&1 | tail -30
      Expected: completes without error; final log lines show regime labels written for SPY 5m.
      If Numba cache exists from T2 test run: pre-compile is instant (<1s).
      If no cache: the main-process pre-compile takes ~10-20s once (expected, logged), then
      all workers load from cache.

    Step 6 — Run full unit suite:
      .venv/bin/pytest tests/unit/ -q
      Expected: all green.

    Step 7 — Commit:
      git add services/regime_writer.py
      git commit -m "feat(services): wire alpha_pass_jit into regime_writer hot path

      Replace Python _alpha_pass with Numba JIT version. Pre-compute log_A once
      per symbol outside the JIT call. Pre-compile the JIT in the main process
      (dummy (10,K) input) before ProcessPoolExecutor so workers load the cache
      read-only — eliminates the parallel-compile __pycache__ write race. No
      initializer= argument; start-method agnostic."
  </action>
  <acceptance_criteria>
    - regime_writer.py imports _alpha_pass_jit from src.intelligence.hmm_jit
    - the JIT is pre-compiled in the main process with a dummy (10, n_components) input before the ProcessPoolExecutor block
    - ProcessPoolExecutor has NO initializer= argument; no _jit_warmup() function or _jit_warmup_k global exists
    - _causal_decode passes log_A = np.log(np.maximum(model.transmat_, 1e-300)) (not transmat_) to _alpha_pass_jit
    - regime_writer --symbols SPY --tf 5m completes without error
    - unit suite green
  </acceptance_criteria>
  <output_gate>regime_writer.py imports _alpha_pass_jit; JIT pre-compiled in main process before pool; ProcessPoolExecutor has no initializer=; _causal_decode passes log_A (not transmat_); regime_writer --symbols SPY --tf 5m completes; unit suite green</output_gate>
</task>

</tasks>
</output>
