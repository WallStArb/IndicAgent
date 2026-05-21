# Phase 093: Mathematical Correctness Audit — Context

**Gathered:** 2026-05-21
**Status:** Ready for planning
**Source:** User discussion + code review findings + post-fix state audit

<domain>
## Phase Boundary

Systematically validate every mathematical computation in the intelligence pipeline against reference implementations. The state management crash bugs (17 fixes) were committed before this phase begins — this phase focuses on the remaining correctness and efficiency gaps.

**Already shipped (pre-phase):**
- State initialization crashes: GARCH/Kalman uninitialized `state = {}` (FIXED)
- ADX self-referential bug `state[key] = state` → `out_state[key] = p_state` (FIXED)
- MACD/CCI/MFI/Stochastic/Williams R: `_seed_state` accepted undefined name (FIXED)
- BollingerSqueeze: `self._state` typo + missing `_state` return (FIXED)
- VolumeZscore: missing `_state` return (FIXED)

**Remaining for this phase:**
1. Mathematical validation — are formulas correct vs. reference implementations?
2. Invariant tests for stateful computations (Kalman, GARCH)
3. Efficiency: `.tolist()` in hot path, `sorted()` in BollingerSqueeze per-bar
4. Edge case coverage: gap handling, zero volume, single bar, numerical stability

</domain>

<decisions>
## Implementation Decisions

### Renaissance Design Philosophy

Jim Simons would demand: every computation is mathematically provable, every invariant is enforced in code (not docs), every test is automated and runs in CI.

**Principles that govern all decisions in this phase:**

- **Prove correctness, don't assert it**: every Tier 1 indicator must have a reference comparison test (pandas-ta or TA-lib). Tolerance: max absolute error < 1e-6.
- **Invariants are invariants**: stateful computations (Kalman, GARCH) must enforce their mathematical invariants in test code, not comments.
- **Automation over manual**: CI gate on correctness tests — no human "it looks right" sign-off. Tests fail → merge blocked.
- **Separation of concerns**: tests live in `tests/unit/intelligence/correctness/` — not mixed into existing functional tests. Correctness vs. behavior vs. integration are distinct concerns.
- **Modularity and reuse**: shared test fixtures (OHLCV test data, reference lib helpers) live in `tests/unit/intelligence/conftest.py`. Each indicator test is self-contained but builds on shared scaffolding.
- **Microservices DAG**: plugins are computation-only (no DB, no Kafka). Tests should be too — use synthetic data or fixtures, not live DB.
- **Efficiency/simplicity balance**: fix efficiency issues only where they are demonstrably wasteful in the hot path (>5ms per bar impact). Don't pre-optimize. Measure first.
- **Compute costs**: reference library calls (pandas-ta) are test-only — never in production code. Production stays lean.

### Specific Design Decisions

**Reference library choice:** pandas-ta (pure Python, deterministic, pip-installable). TA-lib is C and requires manual compilation — excluded. Tolerance: 1e-6 absolute error, 99.9% directional agreement.

**Test data strategy:** Use two tiers:
1. Synthetic data (known math, deterministic assertions) — for edge cases and invariants
2. Historical snapshot (real OHLCV from `market_data_ohlcv`) — for reference validation on realistic data

**Test organization:** `tests/unit/intelligence/correctness/` with one file per indicator class. No mixing with existing `tests/unit/intelligence/` functional tests.

**Efficiency fixes — scope:** Only hot-path issues with demonstrable impact:
- `.tolist()` in MFI, Williams R, Stochastic, CCI, VolumeZscore → replace with `.to_numpy(copy=False)` or pandas vectorized ops
- `sorted()` in BollingerSqueeze bandwidth percentile (called every bar, O(n log n)) → `np.percentile()` instead
- Do NOT optimize anything else unless benchmarks show >5ms regression

**Invariant contract:** Kalman: `P_est > 0` always, `K ∈ (0, 1)` always, no NaN/Inf in state. GARCH: `sigma2 > 0` always, no overflow/underflow, convergence to long-run variance on flat data.

**CI gate:** Add `tests/unit/intelligence/correctness/` to pytest in CI. No new gate framework — just pytest. The existing `pytest tests/unit/ -v` command must include correctness tests.

**Scope boundary — VWAP, RSI, Volume Profile:**
- RSI: straightforward Wilder's smoothing — validate with pandas-ta
- VWAP: validate POC/VAH/VAL calculations
- Volume Profile: if complex, scope to session VP only (not rolling) in this phase

**Not in scope:**
- Tier 2/3 computations unless Tier 1 uncovers systemic issues
- ML model validation (separate phase)
- Performance benchmarks beyond hot-path efficiency fixes

### Claude's Discretion
- Wave structure (how many plans, parallelization)
- Test fixture design (conftest.py structure)
- Reference validation helper implementation

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Plugin implementations (what to test)
- `src/intelligence/features/i1_indicators/atr.py` — ATR plugin (EWM Wilder's smoothing)
- `src/intelligence/features/i1_indicators/macd.py` — MACD plugin
- `src/intelligence/features/i1_indicators/bollinger.py` — Bollinger Bands
- `src/intelligence/features/i1_indicators/cci.py` — CCI
- `src/intelligence/features/i1_indicators/mfi.py` — MFI
- `src/intelligence/features/i1_indicators/stochastic.py` — Stochastic
- `src/intelligence/features/i1_indicators/williams_r.py` — Williams %R
- `src/intelligence/features/i1_indicators/adx.py` — ADX
- `src/intelligence/context/garch_volatility.py` — GARCH(1,1)
- `src/intelligence/context/kalman_trend.py` — Kalman filter (local level model)
- `src/intelligence/trading/volume_zscore.py` — Volume Z-score

### Plugin infrastructure (understand before writing tests)
- `src/intelligence/plugins.py` — InputSpec, plugin protocol
- `src/intelligence/pipeline/executor.py` — how plugins are called, state passed
- `src/intelligence/CLAUDE.md` — plugin tier structure, protocol rules

### Existing tests (avoid duplication)
- `tests/unit/intelligence/` — existing functional tests; correctness tests go in `tests/unit/intelligence/correctness/` separately

### Code review findings (reference for efficiency issues)
- `.planning/phases/093-mathematical-correctness-audit/093-CODE-REVIEW.md` — CR findings, efficiency issues

</canonical_refs>

<specifics>
## Specific Ideas

- BollingerSqueeze uses `sorted(bandwidth_history)` on every bar (line 70, 157). Replace with `np.percentile(bandwidth_history, 20)` — O(n) vs O(n log n), same result.
- ATR Wilder's smoothing: our `ewm(alpha=1/p)` is equivalent to `ewm(span=2p-1)` — confirm against pandas-ta which uses `ewm(span=p)` (different convention). This may be the original ATR "bug."
- Kalman trend history: we keep only last 6 bars for slope. That's a design choice, not a bug — but test that slope calculation matches expected output.
- GARCH shock formula uses prior sigma2 (not posterior) — this is correct (unbiased). Test that this holds under incremental updates.

</specifics>

<deferred>
## Deferred Ideas

- Tier 2 computations (Z-score normalization, percentile calculations, bootstrap CI) — only if Tier 1 work uncovers systemic patterns
- Formal mathematical proofs (LaTeX/docs) — nice-to-have, not blocking
- Automated weekly reference validation in CI (beyond initial gate) — future phase
- Volume Profile rolling VP validation — out of scope for this phase (session VP only)
- ML model validation — separate phase

</deferred>

---

*Phase: 093-mathematical-correctness-audit*
*Context gathered: 2026-05-21 via user discussion + code audit*
