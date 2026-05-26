---
phase: 093
reviewers: [gemini, codex, ollama]
reviewed_at: 2026-05-21T00:00:00Z
plans_reviewed:
  - 093-01-PLAN.md
  - 093-02-PLAN.md
  - 093-03-PLAN.md
  - 093-04-PLAN.md
  - 093-05-PLAN.md
---

# Cross-AI Plan Review — Phase 093: Renaissance Mathematical Correctness Audit

---

## Gemini Review

### Phase 093: Renaissance Mathematical Correctness Audit Review

#### Summary
The plan is highly methodical, well-aligned with the project's "Renaissance" design philosophy, and focuses appropriately on empirical proof of correctness via reference validation. By leveraging `pandas-ta` as a golden master and enforcing mathematical invariants for stateful models, it effectively bridges the gap between theoretical formula and implementation reality. The progression from infrastructure to validation to stability/efficiency is logical and provides clear guardrails against regression.

#### Strengths
- **Reference-First Validation:** Using `pandas-ta` with configurable tolerances (1e-6) is the gold standard for financial math validation, avoiding the overhead of C-based TA-lib.
- **Invariant Testing:** Defining mathematical contracts for GARCH/Kalman (e.g., P_est > 0, K in (0, 1)) rather than just regression testing outputs is robust and captures "silent" logic failures.
- **Incremental Equivalence:** The requirement that `full == incremental` for stateful models is excellent, directly testing the stability of the state-passing mechanism (which has historically been a source of bugs).
- **Logical Workflow:** The wave-based approach minimizes "big bang" integration issues and establishes the infrastructure before adding complex indicator tests.

#### Concerns
- **[MEDIUM] `np.percentile` vs `sorted()` equivalence:** The plan assumes `method="lower"` will exactly match the previous `int(len * 0.20)` logic. This needs careful verification. If the previous logic was doing simple indexing `sorted_arr[int(len * 0.20)]`, there might be subtle "off-by-one" differences depending on integer rounding versus floor operations in the legacy implementation.
- **[MEDIUM] Drift in stateful computations:** While the incremental test `compute_full[0:100] + compute_next[100:200] == compute_full[0:200]` is good, it assumes no state corruption happens *within* a compute call. Ensure the test also validates the *internal* state object returned between steps.
- **[LOW] `pandas-ta` versioning:** The plan suggests `pandas-ta>=0.3.14b0`. Pinning this dependency strictly in `requirements.txt` is vital to prevent future CI drift if `pandas-ta` updates its own internal math implementations.

#### Suggestions
- **Explicit State Validation:** For stateful computations (Kalman/GARCH), add a specific test that serializes and deserializes the state dict to ensure it can be rehydrated correctly without losing precision or structure.
- **Rounding/Truncation Audit:** For the BollingerSqueeze `sorted()` replacement, explicitly include a unit test that compares `int(len * 0.20)` versus `np.percentile(..., method="lower")` on edge case arrays (e.g., length 0, 1, 5, 20) to prove equivalence before replacing the hot-path code.
- **Numerical Stability "Clipping":** For the GARCH and Kalman tests, if numerical instability is found, suggest adding explicit `np.clip` or `np.finfo(float).eps` guards *before* the computation occurs, rather than just asserting it doesn't happen.

#### Risk Assessment
**LOW.** The plan is robust and addresses the primary sources of historical failures (state management and mathematical drift). The risks are largely implementation-specific (numerical precision details) which the proposed 1e-6 tolerance and incremental tests are well-positioned to mitigate. The phase is well-scoped to avoid over-engineering.

---

## Codex Review

### Summary

The phase is directionally strong: it separates reference correctness tests, stateful invariants, hot-path efficiency fixes, and edge-case coverage in a way that maps well to the roadmap. The biggest risks are technical precision and brittleness: pandas-ta conventions may not match every in-house convention exactly, `1e-6` absolute tolerance may be too strict for recursive indicators, incremental-vs-full tests need careful state comparison, and some proposed efficiency changes are not guaranteed to be bit-equivalent. The plans will catch many regressions, but they need sharper handling of warm-up periods, output alignment, state contracts, pandas-ta availability, and indicators whose definitions are convention-dependent.

### Plan 093-01: Test Infrastructure

#### Strengths
- Establishes a dedicated correctness test namespace, matching the phase boundary and design philosophy.
- Fixtures cover important market regimes: trend, range, gap, zero volume, single bar, flat data.
- A shared comparison helper should reduce copy/paste errors and enforce consistent thresholds.
- Keeps tests synthetic and DB-free, which aligns with project constraints.

#### Concerns
- **HIGH:** `pandas-ta>=0.3.14b0` may be difficult to install reliably depending on package availability and Python version. This should be verified before making it a hard test dependency.
- **HIGH:** A generic `assert_close_to_reference` can hide alignment mistakes. Many indicators have different warm-up lengths, column names, and seeding conventions.
- **MEDIUM:** `directional agreement` is underspecified. Direction of raw values, first differences, sign, or crossover direction are different concepts.
- **MEDIUM:** Dropping all leading NaNs may not be enough; references and in-house outputs may have non-leading NaNs around gaps or zero-volume cases.
- **LOW:** README contract is useful, but acceptance criteria should include one real smoke test using the helper, not only collection/import checks.

#### Suggestions
- Add explicit alignment utilities: index intersection, warm-up trimming by indicator, and NaN masks shared between ours/reference.
- Define directional agreement as `sign(diff(series))` agreement unless another meaning is intended.
- Add a small `test_correctness_infra.py` that validates fixture shapes, required OHLCV columns, deterministic seeds, and helper behavior.
- Pin pandas-ta only after confirming compatibility in the actual environment. If needed, use a constraints file or guarded skip with a clear failure message.

#### Risk Assessment
**MEDIUM.** The structure is good, but weak alignment semantics could let bad comparisons pass or good implementations fail.

---

### Plan 093-02: Tier 1 Reference Validation

#### Strengths
- Directly addresses the phase's main success criterion: reference validation for Tier 1 math.
- Covers the core indicators called out in the roadmap: ATR, Bollinger, MACD, RSI, Stochastic, VWAP, plus related oscillators.
- Includes incremental-vs-full testing for ATR, which is valuable for the plugin protocol.
- Recognizes convention risk for ATR and Williams %R.

#### Concerns
- **HIGH:** The ATR task says "investigate ewm(alpha=1/p) vs pandas-ta ewm(span=p) discrepancy," but the context already states pandas-ta RMA/Wilder should match `alpha=1/p`, not `span=p`. The plan wording risks chasing the wrong convention.
- **HIGH:** `max absolute error < 1e-6` may be unrealistic for recursive EMA/RMA-style indicators unless initial seeding exactly matches pandas-ta.
- **HIGH:** pandas-ta indicator defaults are not always equivalent to local implementations. MACD `asmode`, RSI drift/scalar, Stochastic smoothing, ADX mamode, Bollinger ddof, and VWAP anchoring can all differ.
- **MEDIUM:** "20+ tests collected" is too weak as a quality gate. It counts files, not correctness depth.
- **MEDIUM:** VWAP with `DatetimeIndex` needs session boundary semantics. A single-session test is fine, but the expected reset behavior must be explicit.
- **LOW:** The plan names MFI but the roadmap's Tier 1 list does not explicitly include it; likely okay, but scope should distinguish required vs opportunistic.

#### Suggestions
- For each indicator, document exact reference parameters and local convention in the test file.
- Compare after an indicator-specific warm-up, not a shared generic trim.
- Add at least one handcrafted small-series test for ATR true range, VWAP, RSI bounds, and Bollinger bands. Reference libraries are useful, but known-answer tests catch shared convention misunderstandings.
- Include `compute_next` parity for more than ATR, especially MACD, RSI, Stochastic, ADX, and rolling-window indicators.
- Treat convention differences as explicit expected behavior rather than forcing pandas-ta equality where the product intentionally differs.

#### Risk Assessment
**MEDIUM-HIGH.** This plan is essential, but convention mismatch and over-strict tolerances could create noisy failures or lead developers to "fix" correct local behavior to match the wrong reference.

---

### Plan 093-03: Stateful Invariant Tests

#### Strengths
- Correctly focuses on mathematical invariants rather than only output snapshots.
- Kalman invariants are concrete and useful: positive covariance, bounded gain, finite state.
- GARCH invariants cover positivity, overflow, underflow, shock behavior, and incremental parity.
- Incremental-vs-full tests directly validate the plugin state protocol.

#### Concerns
- **HIGH:** `K in (0, 1)` may be invalid depending on the Kalman model, measurement matrix, and noise assumptions. It is plausible for a scalar price filter, but the implementation must confirm this invariant.
- **HIGH:** GARCH convergence to `omega/(1-alpha-beta)` on flat data is suspicious. With zero returns, the conditional variance recursively approaches the unconditional variance only under particular update forms and initialization choices; many implementations converge toward a floor or toward `omega / (1 - beta)` when shocks are zero.
- **MEDIUM:** Tests refer to internal state names like `P_est`, `K`, `prev_sigma2`, `omega`, `alpha`, `beta`. If plugins do not expose these consistently, tests may become coupled to implementation details.
- **MEDIUM:** Incremental equality can fail from legitimate floating-point path differences unless state is initialized and sliced exactly the same way.
- **LOW:** Slope positive on trending data is reasonable, but it should allow a warm-up period and maybe assert majority-positive rather than every bar positive.

#### Suggestions
- First inspect actual Kalman and GARCH equations, then encode invariants that are mathematically guaranteed by that implementation.
- Use property-style checks over multiple fixtures and parameter regimes, but keep deterministic seeds.
- Separate public-output invariants from internal-state invariants. If internal state is part of the plugin contract, document it.
- For GARCH flat-data convergence, derive the expected fixed point from the actual recurrence used in code.
- Add tests for bad-but-real inputs: repeated identical closes, one large shock, NaN in one bar if the pipeline permits it, and tiny prices/returns.

#### Risk Assessment
**MEDIUM-HIGH.** The intent is excellent, but a few proposed invariants may be mathematically wrong for the actual implementations unless verified first.

---

### Plan 093-04: Efficiency Hot-Path Fixes

#### Strengths
- Scope is appropriately narrow and tied to known hot-path issues.
- Numeric equivalence tests are the right guardrail for performance edits.
- Removing `.tolist()` can reduce unnecessary allocation in rolling computations.
- Targeting `BollingerSqueeze` sorted-per-bar behavior is sensible.

#### Concerns
- **HIGH:** `np.percentile(..., method="lower")` is not guaranteed to be bit-equivalent to `sorted(history)[int(len * 0.20)]`. Percentile rank calculation may select a different element depending on NumPy's percentile definition.
- **HIGH:** Replacing `.tolist()` with `.to_numpy(copy=False)` may break code that relies on Python list methods, deque initialization semantics, truthiness, mutation behavior, or scalar Python floats.
- **MEDIUM:** `np.percentile` is not necessarily O(n). It may sort internally depending on implementation. `np.partition` is a better match for kth-element selection.
- **MEDIUM:** "sorted() gone" may be too broad if a sorted call exists outside the hot path or is clearer elsewhere.
- **LOW:** Numeric equivalence at `1e-9` is good, but only if tests compare before/after behavior from frozen fixtures. Otherwise it just compares current code to itself.

#### Suggestions
- Replace sorted-index percentile with direct kth selection: `k = int(len(history) * 0.20)` and `np.partition(array, k)[k]`, after confirming exact old behavior.
- Before editing, add characterization tests for current outputs. Then make the optimization.
- Audit each `.tolist()` call locally before replacing it; use `deque(series.to_numpy(copy=False), maxlen=...)` only where semantics match.
- Add a small benchmark or at least document expected complexity improvement for BollingerSqueeze.
- Keep equivalence tests focused on output keys and state keys affected by the optimization.

#### Risk Assessment
**MEDIUM.** The performance goal is valid, but the `np.percentile` replacement is technically risky and may not preserve exact behavior.

---

### Plan 093-05: Edge Cases, Numerical Stability, CI Gate

#### Strengths
- Directly addresses remaining success criteria: gaps, zero volume, single bar, numerical stability, CI discovery.
- Long-run 10K-bar tests are useful for recursive state and rolling calculations.
- Explicitly checks no crash and finite outputs across Tier 1 plugins.
- CI gate approach is pragmatic: rely on existing `testpaths=tests` instead of inventing new machinery.

#### Concerns
- **HIGH:** "all outputs finite" may be wrong for warm-up periods where NaN is expected. Tests need to distinguish acceptable warm-up missingness from invalid post-warm-up NaN/Inf.
- **HIGH:** `@pytest.mark.slow` can undermine the CI gate if CI skips slow tests by default. The plan must state whether slow correctness tests are required in CI.
- **MEDIUM:** Empty DataFrame behavior returning `{}` may conflict with plugins that return structured empty outputs. The expected contract should be confirmed.
- **MEDIUM:** "all 12 Tier 1 plugins" conflicts with earlier lists of 10 indicators and the roadmap list of 9 named Tier 1 items. The canonical Tier 1 set needs to be fixed.
- **MEDIUM:** Zero-volume VWAP/MFI behavior needs a clear expected result: no crash is not enough if the output silently becomes misleading.
- **LOW:** `pytest.ini (read-only if already correct)` is ambiguous. Either no modification is planned, or a precise modification is stated.

#### Suggestions
- Define post-warm-up finite checks per plugin and allow expected warm-up NaNs/missing keys.
- Make slow-test CI policy explicit: either run in normal CI or create a named scheduled/deep correctness job.
- Add edge checks for duplicated timestamps, non-monotonic index, missing OHLCV columns, and negative/zero prices if those can appear upstream.
- For zero volume, assert specific behavior: VWAP absent/NaN/previous value, MFI neutral, or documented fallback.
- Generate `TIER1_PLUGINS` from a canonical registry if one exists, or document why this static list is authoritative.

#### Risk Assessment
**MEDIUM.** Good coverage direction, but unclear contracts around warm-up, zero volume, empty frames, and slow CI could weaken the gate.

---

### Cross-Plan Issues (Codex)
- **Dependency ordering is mostly sound.** Wave 2 plans can run independently after infrastructure, and Wave 3 correctly depends on reference, invariant, and efficiency work.
- **The biggest technical risk is convention mismatch.** Reference validation must prove intended correctness, not blindly clone pandas-ta behavior.
- **Stateful tests need implementation-specific derivation.** Kalman and GARCH invariants should be derived from the actual equations in the plugins before being frozen.
- **CI gating is under-specified.** Discovery by `testpaths=tests` is not the same as ensuring the suite runs in required CI jobs.
- **Tolerance policy needs nuance.** Use `1e-6` where appropriate, but recursive indicators may need warm-up exclusion, relative tolerance, or documented looser thresholds.

### Overall Risk Assessment (Codex)
**MEDIUM.** The plans are well-structured and likely to improve mathematical confidence substantially. The main risks are not scope or ordering; they are correctness-test correctness: wrong reference conventions, brittle tolerances, invalid invariants, and edge-case assertions that do not reflect plugin contracts. Tightening those details before implementation would make this a strong phase plan.

---

## Ollama Review (gemma4:e4b)

### Summary
This is a comprehensive and well-structured initiative designed to ensure the mathematical correctness and stability of the core feature set. Starting with foundational principles (linear algebra, statistics), the plan builds toward rigorous testing of component interaction (edge cases, large volumes). The layered approach mitigates the risk of introducing regressions in complex financial modeling components. This is an **A+ Plan** overall.

#### Strengths
1. **Layered Testing Strategy:** Moving from simple unit tests (structural checks) to complex, system-wide validations (boundary conditions, volume stress) is best practice for financial software.
2. **Focus on Core Mathematics:** Explicitly testing the mathematical foundations (linear algebra for Kalman filters, statistical properties for volatility models) is critical in quantitative finance.
3. **Comprehensive Edge Case Handling:** The inclusion of plans for gaps, zero inputs, and extreme volumes addresses the most common failure points in time-series analysis.

#### Concerns
- **[MEDIUM] Scope Creep:** The sheer breadth of tests (all core indicators + multiple edge cases) risks delays if unexpected complexities arise during implementation.
- **[MEDIUM] Test Data Dependency:** Success hinges entirely on the ability to generate synthetic test data that truly represents edge cases (e.g., instantaneous regime shifts).
- **[LOW] Over-optimization of small gains:** Some tests (achieving absolute numerical parity with academic implementations) might consume disproportionate time for marginal gains in robustness.

#### Suggestions
- Ensure the linear algebra layer includes a check for matrix singularity whenever covariance inversion is required — a primary failure point for Kalman filter implementations.
- Integrate a "Known Output Dataset" comparison against industry-standard calculators for several known data points to verify byte-for-byte compatibility.
- Formalize the "Rule Set" for edge cases: document what the expected output *must* be when data is missing (e.g., "If input is NIL, model returns previous valid state and a confidence score of 0.5").
- Use benchmarking tools to establish a baseline SLO and measure memory/CPU profile under continuous streaming load.

#### Risk Assessment
**LOW.** The plan is well-structured and is likely to significantly improve mathematical confidence and stability. The phase correctly treats the test suite as the primary artifact being built.

---

## Consensus Summary

Phase 093 was reviewed by 3 AI systems (Gemini, Codex, Ollama). All three reviewers agree the phase is directionally sound with a well-structured wave progression. The plan will substantially improve mathematical confidence in the pipeline.

### Agreed Strengths
1. **Wave-based progression** (infra → validation → invariants → efficiency → edge cases) is the right architecture for a correctness phase — each wave builds on verifiable foundations.
2. **Incremental-equals-full equivalence testing** for stateful models (Kalman, GARCH) is universally praised — this directly targets the pre-phase state-corruption bugs and catches future regressions at the protocol level.
3. **pandas-ta as reference library** is the right choice (pure Python, pip-installable, deterministic) and the 1e-6 / 99.9% directional tolerance contract is explicit enough to enforce.
4. **DB-free synthetic fixtures** correctly respects the plugin protocol (plugins are computation-only).
5. **Mathematical invariant testing** (P_est > 0, K in (0,1), sigma2 > 0) is praised as superior to snapshot-only regression tests.

### Agreed Concerns
1. **[HIGH — Plan 04] `np.percentile` may not be bit-equivalent to `sorted()[int(len*0.20)]`.** Gemini and Codex both flag this. Recommendation: use `np.partition(array, k)[k]` where `k = int(len(history) * 0.20)` — this is O(n), bit-equivalent to the original truncated index lookup, and avoids percentile interpolation ambiguity.

2. **[HIGH — Plan 02] 1e-6 absolute tolerance may be too strict for recursive EMA/RMA indicators** if initial seeding doesn't match pandas-ta exactly. Codex flags that MACD, RSI, Stochastic, ADX, and VWAP all have convention/parameter differences that need per-indicator documentation. Warm-up periods need indicator-specific trimming, not a shared generic NaN drop.

3. **[MEDIUM-HIGH — Plan 03] GARCH convergence to `omega/(1-alpha-beta)` on flat data needs verification** against the actual recurrence in `garch_volatility.py`. Codex specifically flags that with zero returns, the recursion may converge to a different fixed point depending on implementation. Derive the expected value from the actual code before encoding it as a test invariant.

4. **[MEDIUM — All Plans] Convention mismatch is the primary risk.** All three reviewers note that reference validation must prove intended correctness, not blindly clone pandas-ta behavior. Where local conventions intentionally differ (e.g., Williams %R sign, VWAP session anchoring), the test should document and assert the local convention, not coerce it to match the library.

5. **[MEDIUM — Plan 05] `@pytest.mark.slow` CI policy is undefined.** If slow tests are skipped in CI by default, the 10K-bar numerical stability tests provide no gate. The CI gate doc must state whether slow tests run in CI.

### Divergent Views
- **Risk level:** Gemini rates overall risk as LOW; Codex rates it MEDIUM; Ollama rates it LOW. The divergence is on tolerance/convention brittleness — Codex is more skeptical that 1e-6 will pass cleanly without per-indicator tuning.
- **Efficiency fixes (Plan 04):** Gemini sees MEDIUM risk; Codex sees HIGH risk for the `np.percentile` replacement specifically. Codex's `np.partition` suggestion is technically stronger.
- **Ollama** provided higher-level structural feedback (treat test suite as primary artifact, matrix singularity check for Kalman) rather than per-plan technical concerns — useful framing but less actionable than Gemini/Codex.

---

*To incorporate this feedback into planning: `/gsd-plan-phase 093 --reviews`*
