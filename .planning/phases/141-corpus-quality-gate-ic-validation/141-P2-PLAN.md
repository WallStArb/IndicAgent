---
plan: 141-P2
phase: "141"
title: "HMM Numba JIT"
wave: 1
depends_on: [141-P0]
files_modified:
  - src/intelligence/hmm_jit.py
  - services/regime_writer.py
  - tests/unit/intelligence/test_hmm_jit.py
autonomous: true
must_haves:
  goal: "Numba JIT forward filter implemented, tests proving numerical identity to Python reference, wired into regime_writer hot path with worker-level warmup"
  truths:
    - "src/intelligence/hmm_jit.py exports alpha_pass_jit decorated with @numba.njit(cache=True)"
    - "alpha_pass_jit signature: (log_emit: np.ndarray, log_A: np.ndarray, pi0: np.ndarray) -> tuple[np.ndarray, np.ndarray] where log_A is pre-computed log(max(transmat_, 1e-300))"
    - "test_jit_states_match_reference PASS — JIT states array-equal to Python _alpha_pass_ref for same inputs"
    - "test_jit_alpha_history_matches_reference PASS — alpha_history matches within rtol=1e-10"
    - "test_alpha_rows_sum_to_one PASS — each row of alpha_history sums to 1.0 within atol=1e-10"
    - "regime_writer.py imports alpha_pass_jit from src.intelligence.hmm_jit"
    - "regime_writer._causal_decode pre-computes log_A = np.log(np.maximum(model.transmat_, 1e-300)) and passes it to alpha_pass_jit (not model.transmat_ directly)"
    - "regime_writer has a _jit_warmup() function called as initializer= argument to ProcessPoolExecutor — warmup runs in WORKER subprocess, not main process"
    - "_jit_warmup() reads K from module-level _jit_warmup_k (set by main process from APR n_components before pool creation) — no hardcoded integer"
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

Key placement for warmup: ProcessPoolExecutor(initializer=_jit_warmup). This ensures each
worker subprocess warms up BEFORE the first symbol is dispatched. Putting warmup at module
level (main process) does NOT warm worker subprocesses — each worker starts a fresh Python
interpreter that must compile on its first call.

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
  <output_gate>tests/unit/intelligence/test_hmm_jit.py exists; pytest on it fails with ImportError; full unit suite still green</output_gate>
</task>

<task id="P2-T2" type="execute">
  <title>Implement src/intelligence/hmm_jit.py</title>
  <wave>2</wave>
  <read_first>
    - services/regime_writer.py:247-276 — _alpha_pass algorithm to replicate in Numba
    - docs/plans/2026-06-28-validity-fixes-and-phase-141.md — Task 9 (complete implementation)
    - src/intelligence/ — confirm Ring 1 module pattern (no DB imports, no Ring 2 imports)
  </read_first>
  <action>
    Follow Task 9 in docs/plans/2026-06-28-validity-fixes-and-phase-141.md exactly.

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

    Step 4 — Commit:
      git add src/intelligence/hmm_jit.py tests/unit/intelligence/test_hmm_jit.py
      git commit -m "feat(intelligence): Numba JIT forward filter for HMM regime inference

      alpha_pass_jit is a drop-in for _alpha_pass in regime_writer. Takes log_A
      (pre-computed) not transmat_ to keep log(max()) outside the JIT boundary.
      cache=True: compiled once, loaded from __pycache__ on all subsequent runs.
      Target: 20+ hr regime_writer run → ~30 min."
  </action>
  <output_gate>src/intelligence/hmm_jit.py exists; all 5 tests in test_hmm_jit.py PASS; full unit suite green; commit exists</output_gate>
</task>

<task id="P2-T3" type="execute">
  <title>Wire alpha_pass_jit into regime_writer</title>
  <wave>3</wave>
  <read_first>
    - services/regime_writer.py:39,247-276,474-492,860-880 — imports, _alpha_pass, call site, ProcessPoolExecutor setup
    - src/intelligence/hmm_jit.py — verify alpha_pass_jit signature matches expected call
  </read_first>
  <action>
    Follow Task 10 in docs/plans/2026-06-28-validity-fixes-and-phase-141.md with these additions.

    Step 1 — Add import at top of regime_writer.py (after existing imports, around line 39):
      from src.intelligence.hmm_jit import alpha_pass_jit as _alpha_pass_jit

    Step 2 — Add module-level variable and _jit_warmup() function (BEFORE _run_symbol_worker, around line 625).
      The warmup must use the same K as production; read from APR rather than hardcoding.
      n_components is passed from the main process to the initializer via a module-level:

      _jit_warmup_k: int = 5  # set by main process before pool creation; APR default

      def _jit_warmup() -> None:
          """Trigger Numba JIT compile in the worker subprocess before any symbol is processed.
          With cache=True, compile happens once and is loaded from disk on subsequent runs."""
          import numpy as np
          k = _jit_warmup_k
          _warmup_log_emit = np.zeros((10, k), dtype=np.float64)
          _warmup_log_A = np.log(np.full((k, k), 1.0 / k))
          _warmup_pi0 = np.full(k, 1.0 / k)
          _alpha_pass_jit(_warmup_log_emit, _warmup_log_A, _warmup_pi0)

      In run() BEFORE the ProcessPoolExecutor block (after cfg.get_sync loads n_components around line 808):
        import services.regime_writer as _rw_module  # same module; set the global
        _rw_module._jit_warmup_k = n_components

    Step 3 — Update the ProcessPoolExecutor call site (around line 871). Add initializer=:
      with ProcessPoolExecutor(max_workers=n_workers, initializer=_jit_warmup) as pool:
      This runs _jit_warmup() once in each worker subprocess before any tasks are dispatched.
      The main process is NOT warmed up — workers get their own JIT state.

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
      If Numba cache exists from T2 test run: warmup is instant (<1s).
      If no cache: warmup takes ~10-20s on first worker subprocess start (expected, log it).

    Step 6 — Run full unit suite:
      .venv/bin/pytest tests/unit/ -q
      Expected: all green.

    Step 7 — Commit:
      git add services/regime_writer.py
      git commit -m "feat(services): wire alpha_pass_jit into regime_writer hot path

      Replace Python _alpha_pass with Numba JIT version. Pre-compute log_A once
      per symbol outside the JIT call. Add _jit_warmup() as ProcessPoolExecutor
      initializer so all worker subprocesses compile before first symbol dispatch."
  </action>
  <output_gate>regime_writer.py imports _alpha_pass_jit from src.intelligence.hmm_jit; _causal_decode passes log_A (not transmat_) to _alpha_pass_jit; ProcessPoolExecutor has initializer=_jit_warmup; regime_writer --symbols SPY --tf 5m completes without error; unit suite green</output_gate>
</task>

</tasks>
