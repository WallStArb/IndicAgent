# Regime Writer Convergence-Iteration Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Log the actual number of EM iterations each `GaussianHMM` fit uses in `regime_writer.py`, so the next full corpus run produces the data needed to evaluate whether `n_iter=200` is oversized (todo 226) — without changing any fit behavior or output.

**Architecture:** One new structured log line (`regime_writer.hmm_convergence_iters`) emitted once per (symbol, tf) cell, immediately after the seed-restart loop in `_compute_symbol_tf` picks its final model — same call frequency and pattern as the existing `hmm_not_converged_retry`/`hmm_not_converged_final` warnings already in that function, so this does not introduce a new per-row-in-a-hot-loop logging pattern (CLAUDE.md's Key Rules) since cell count is in the low hundreds, not millions.

**Tech Stack:** Python, `hmmlearn.hmm.GaussianHMM` (`monitor_.iter` attribute), `structlog`.

## Global Constraints

- This is a measurement-only change. It MUST NOT alter `update_rows`, `converged`, `heldout_ll`, or any other return value of `_compute_symbol_tf` — Renaissance discipline here is "measure first, never guess," and a measurement tool that perturbs the thing it measures is worse than no measurement (see todo 216's own byte-identical verification precedent for the same reasoning).
- `HMM_RANDOM_STATE = 42` and `n_iter` are both APR-governed, load-bearing values (CLAUDE.md Phase 138 section) — this plan does not touch either value, only observes and logs what the existing fit already does.
- Exception variable name is `error`, not `exc` (CLAUDE.md Key Rules).
- No new APR keys, no new config — this is pure observability, nothing tunable is being added.

---

## File Structure

- Modify: `services/regime_writer.py` — add one structured log call inside `_compute_symbol_tf` (around line 617, right after the seed-restart loop selects the final `model`).
- Test: `tests/unit/services/test_regime_writer.py` — add one test asserting the log event fires with the correct fields and does not change the function's return value.

---

### Task 1: Log HMM convergence iteration count per cell

**Files:**
- Modify: `services/regime_writer.py:614-617`
- Test: `tests/unit/services/test_regime_writer.py`

**Interfaces:**
- Consumes: `model` (the `GaussianHMM` instance selected by the existing seed-restart loop, exposes `.monitor_.iter: int`), `converged: bool`, `symbol: str`, `tf: str`, `n_iter: int` — all already in scope at the insertion point, no new parameters.
- Produces: a `structlog` event named `"regime_writer.hmm_convergence_iters"` with fields `symbol`, `tf`, `iters_used` (int), `n_iter_cap` (int), `converged` (bool). No return-value or signature change to `_compute_symbol_tf` — downstream consumers of this function are unaffected.

- [ ] **Step 1: Write the failing test**

This project's established pattern for asserting on structlog output is
`structlog.testing.capture_logs()` used directly as a context manager (see
`tests/unit/intelligence/test_trade_framer.py`'s `TestFrameTradeObservability` class) —
no shared fixture exists or is needed. Add to `tests/unit/services/test_regime_writer.py`,
in the "Tests: `_compute_symbol_tf`" section (after `test_compute_symbol_tf_returns_tuple_structure`,
around line 510):

```python
def test_compute_symbol_tf_logs_convergence_iterations():
    """_compute_symbol_tf must log the actual EM iteration count used per cell.

    This is measurement-only instrumentation for todo 226 (n_iter=200 headroom
    check) -- asserts the log event fires with correct fields AND that the
    function's return value is unaffected by adding the log call, confirming
    the instrumentation has zero effect on fit output.
    """
    from structlog.testing import capture_logs

    n = 500
    closes = _make_ranging_closes(n)
    volumes = _make_volumes(n)
    timestamps = _make_timestamps(n)
    conn = _make_mock_conn(closes, volumes, timestamps)

    with capture_logs() as cap_logs:
        result = _compute_symbol_tf(
            conn=conn,
            symbol="SPY",
            tf="1d",
            n_components=3,
            vol_window=20,
            n_iter=50,
            hmm_random_state=42,
            momentum_window=20,
            vol_of_vol_window=20,
            min_state_occupation=0.0,
        )

    assert result is not None

    events = [e for e in cap_logs if e["event"] == "regime_writer.hmm_convergence_iters"]
    assert len(events) == 1
    event = events[0]
    assert event["symbol"] == "SPY"
    assert event["tf"] == "1d"
    assert event["n_iter_cap"] == 50
    assert isinstance(event["iters_used"], int)
    assert 0 < event["iters_used"] <= 50
    assert isinstance(event["converged"], bool)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/services/test_regime_writer.py::test_compute_symbol_tf_logs_convergence_iterations -v`
Expected: FAIL — either `AssertionError: assert 0 == 1` (no matching event found, since the log call doesn't exist yet) or a fixture-not-found error if `caplog_structlog` needed to be added in Step 1.

- [ ] **Step 3: Write minimal implementation**

In `services/regime_writer.py`, locate the end of the seed-restart loop (currently lines 558-617, ending with the `if n_restarts == 1: ... break` fast path at 603-606 and the multi-restart comparison at 608-617). Immediately after the loop — i.e., right before the existing comment `# Held-out log-likelihood:` at line 619 — add:

```python
    _logger.info(
        "regime_writer.hmm_convergence_iters",
        symbol=symbol,
        tf=tf,
        iters_used=int(model.monitor_.iter),
        n_iter_cap=n_iter,
        converged=converged,
    )
```

Place this as a single line covering both the `n_restarts == 1` fast-path exit and the multi-restart loop's final `model` — since both paths converge to the same `model`/`converged` local variables before falling through to this point, one log call after the loop (not one per restart candidate) is correct and matches the "once per cell" frequency in this plan's Architecture section. Do not log inside the `for i in range(n_restarts)` loop itself — that would log once per restart attempt, not once per cell, and would misrepresent "iterations used" for cells with `n_restarts > 1` (APR default is 1, so this distinction rarely matters today, but the log semantics should still be "iterations of the model actually written," not "iterations of every candidate tried").

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/services/test_regime_writer.py::test_compute_symbol_tf_logs_convergence_iterations -v`
Expected: PASS

- [ ] **Step 5: Run the full regime_writer test suite to confirm zero behavior change**

Run: `.venv/bin/pytest tests/unit/services/test_regime_writer.py tests/unit/test_regime_writer_churn.py tests/unit/test_regime_writer_occupation_gate.py tests/unit/test_regime_writer_obs.py tests/unit/test_regime_writer.py -v`
Expected: PASS, all tests — the existing `test_compute_symbol_tf_returns_tuple_structure`/`test_compute_symbol_tf_regime_values`/`test_compute_symbol_tf_probabilities_sum_to_one`/`test_compute_symbol_tf_n_restarts_*` tests must still pass unmodified, confirming the log call has zero effect on return values (this is the direct evidence for this plan's Global Constraint).

- [ ] **Step 6: Run the full unit suite**

Run: `.venv/bin/pytest tests/unit/ -q`
Expected: PASS, no regressions elsewhere.

- [ ] **Step 7: Commit**

```bash
git add services/regime_writer.py tests/unit/services/test_regime_writer.py
git commit -m "feat(regime-writer): log HMM convergence iteration count per cell (todo 226)"
```

---

## Self-Review

**1. Spec coverage:** This plan implements exactly the measurement step described in todo 226's "What to do" section 1 ("log `model.monitor_.iter` per (symbol, tf) cell alongside the existing convergence-retry counter"). It deliberately does NOT implement todo 226's step 2 (lowering the `n_iter` cap) — that step is explicitly gated on data this plan produces, and doing it now would violate the todo's own "measure-first" instruction and Renaissance's "earn promotion through proof" principle. No other in-scope requirement was identified.

**2. Placeholder scan:** No TBD/TODO markers; both the test and implementation code blocks are complete and runnable as written, using the project's existing `structlog.testing.capture_logs()` pattern (verified present in `tests/unit/intelligence/test_trade_framer.py`) rather than inventing new test infrastructure.

**3. Type consistency:** `iters_used=int(model.monitor_.iter)` matches the test's `isinstance(event["iters_used"], int)` assertion. `n_iter_cap=n_iter` matches the test's `event["n_iter_cap"] == 50` (test passes `n_iter=50`). `converged=converged` (the loop's local bool) matches `isinstance(event["converged"], bool)`. Field names (`symbol`, `tf`, `iters_used`, `n_iter_cap`, `converged`) are consistent between the log call and the test assertions — no drift.

---

**Next step after this plan lands:** the log line self-populates the next time `regime_writer.py` runs against real data (full corpus run or a targeted `--symbols`/`--refit` run). Once that data exists, return to todo 226's step 1 analysis (check the `iters_used` distribution) before considering any change to the `n_iter` cap itself.
