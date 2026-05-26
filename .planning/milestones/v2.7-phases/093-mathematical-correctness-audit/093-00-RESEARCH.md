# Phase 093: Renaissance Mathematical Correctness Audit

**Phase:** 093
**Milestone:** v2.7 Mathematical Correctness & AI Platform Modernization
**Status:** 🔬 Research Phase - Pre-Planning
**Priority:** P0 - Blocks further feature development until mathematical correctness is verified
**Trigger:** ATR calculation bug discovered in production intelligence pipeline

## Problem Statement

The ATR bug revealed that mathematical correctness gaps exist in the intelligence pipeline despite:
- 35 tests in Phase 06 (I1-I6 Correctness Audit)
- Extensive integration tests
- Shadow mode governance
- Institutional-grade observability

**Renaissance Mandate:** Every computation must be mathematically correct, invariant-protected, and validated against reference implementations. No exceptions.

## Scope

### In-Scope (Mathematical Computations)

**Tier 1: Financial Math (Highest Risk)**
- ATR (Average True Range) — ✅ Bug found, needs fix + validation
- Bollinger Bands calculations
- VWAP (Volume Weighted Average Price)
- Volume Profile (POC, VAH, VAL)
- MACD, RSI, Stochastic oscillators
- GARCH volatility modeling
- Kalman trend filtering

**Tier 2: Statistical Computations**
- Z-score normalization
- Percentile calculations
- Gradient scoring
- Confidence calibration
- Bootstrap confidence intervals
- Correlation matrices

**Tier 3: Transform Functions**
- Signal transforms (6 math transforms + 3 swarm transforms)
- Feature scaling
- Time decay functions
- Regime gating logic

### Out-of-Scope

- LLM prompt engineering (validated via shadow mode, not math)
- Data transport (Kafka, DB schemas)
- UI/dashboard calculations (presentation layer)
- Business logic (signal aggregation, lifecycle)

## Renaissance Validation Framework

### 1. Reference Implementation Validation

For each mathematical function:
```python
def test_atr_reference_implementation():
    """Compare against pandas-ta or TA-lib reference."""
    # Load historical OHLCV
    # Compute ATR using our implementation
    # Compute ATR using reference library
    # Assert: max absolute error < 1e-6
    # Assert: directional agreement > 99.9%
```

### 2. Invariant Tests

For stateful computations (Kalman, GARCH, rolling windows):
```python
def test_kalman_invariants():
    """Kalman filter must maintain these invariants."""
    # Covariance matrix is always positive semi-definite
    # State estimate is finite (no NaN/Inf)
    # Measurement residual is bounded
    # Time evolution is monotonic (no teleportation)
```

### 3. Edge Case Coverage

```python
def test_atr_edge_cases():
    """ATR must handle edge cases correctly."""
    # Single bar (no history)
    # Gap up/down (open != prev_close)
    # Zero volume bars
    # Price limits (e.g., circuit breakers)
    # Negative prices (impossible, but defensive)
```

### 4. Numerical Stability

```python
def test_garch_numerical_stability():
    """GARCH must not explode or converge to zero."""
    # Run on 10,000 bars of real data
    # Assert: variance is finite and positive
    # Assert: no numerical overflow/underflow
    # Assert: log-likelihood is monotonic during convergence
```

## Execution Strategy

### Wave 1: Discovery & Triaging (1-2 days)
1. **Catalog all mathematical computations** in intelligence pipeline
2. **Classify by risk** (Tier 1/2/3 based on financial impact)
3. **Identify reference implementations** (pandas-ta, TA-lib, statsmodels, scipy)
4. **Create test matrix** — what's covered vs. what's missing

**Artifacts:**
- `docs/audits/mathematical-computations-catalog.md`
- `docs/audits/reference-implementation-mapping.md`
- `docs/audits/test-coverage-gap-analysis.md`

### Wave 2: Critical Fixes (Immediate)
1. **Fix ATR bug** — patch production, validate against reference
2. **Add invariant tests** for all stateful computations (Kalman, GARCH)
3. **Add reference validation tests** for Tier 1 indicators
4. **Edge case coverage** for high-risk computations

**Artifacts:**
- PR: "Fix ATR calculation with reference validation"
- PR: "Add invariant tests for stateful computations"
- Test suite: `tests/unit/intelligence/correctness/`

### Wave 3: Systematic Validation (1 week)
1. **Reference validation** for all Tier 1 computations
2. **Numerical stability tests** for all statistical functions
3. **Regression guards** — prevent future correctness bugs
4. **Documentation** — correctness proofs for key algorithms

**Artifacts:**
- Test coverage report: 100% of Tier 1, 80% of Tier 2
- Documentation: `docs/proofs/` for key algorithms
- CI gate: correctness tests must pass before merge

## Success Criteria

### Must-Have (Non-Negotiable)
- ✅ ATR bug fixed and validated against pandas-ta
- ✅ All Tier 1 computations have reference validation tests
- ✅ All stateful computations have invariant tests
- ✅ CI gate prevents merges with failing correctness tests
- ✅ No regression in existing functionality

### Nice-to-Have
- Tier 2/3 computations validated
- Formal correctness proofs for key algorithms
- Performance benchmarks (correctness shouldn't kill latency)
- Automated reference validation (CI runs against pandas-ta weekly)

## Open Questions

1. **Reference library choice:** pandas-ta vs. TA-lib vs. manual implementation?
2. **Tolerance definition:** What's acceptable numerical error? (1e-6? 1e-8?)
3. **Test data source:** Historical backfill vs. synthetic vs. production snapshot?
4. **Priority ordering:** ATR first, then what? (Risk-based vs. dependency-based?)
5. **Scope creep:** Do we validate ML models too? (Probably separate phase)

## Dependencies

- Blocks: Phase 094 (Pydantic AI) — correctness first, then agent platform
- Blocks: Phase 100 (Composite Fitness Function) — fitness math must be correct
- Requires: Historical backfill data for reference validation
- Requires: Reference libraries (pandas-ta, TA-lib, statsmodels)

## Next Steps

1. **Approve this research phase** — Is this the right approach?
2. **Prioritize Wave 1** — Start cataloging mathematical computations
3. **Fix ATR immediately** — Unblock production intelligence pipeline
4. **Define test data strategy** — What data do we validate against?

---

**Renaissance Mandate:** "Every computation must be mathematically correct." — Jim Simons would demand nothing less.
