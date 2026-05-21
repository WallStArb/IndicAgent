# ATR Bug Postmortem — Renaissance Correctness Wake-Up Call

**Date:** 2026-05-21
**Severity:** P0 — Mathematical incorrectness in financial computation
**Status:** Root cause analysis in progress

## Bug Summary

**What happened:** ATR (Average True Range) calculation was discovered to be incorrect in the intelligence pipeline.

**Impact:** Any signal or feature depending on ATR (volatility estimation, position sizing, stop losses) was computed on wrong data.

**Discovery:** User noticed incorrect ATR values during manual inspection.

**Root cause:** TBD (investigation in progress)

## Why This Matters

ATR is a foundational volatility measure. If ATR is wrong:
- Volatility-based features are wrong
- Risk calculations are wrong
- Position sizing is wrong
- Stop loss placement is wrong
- Any downstream signal depending on volatility is compromised

**Renaissance principle:** "Data quality over model complexity." — If the foundation is wrong, nothing built on it can be trusted.

## Immediate Actions

1. ✅ **Bug reported** — User identified the issue
2. ⏳ **Root cause analysis** — Investigation needed
3. ⏳ **Fix implementation** — Patch production
4. ⏳ **Reference validation** — Compare against pandas-ta/TA-lib
5. ⏳ **Regression guard** — Add test to prevent recurrence

## Systemic Issues

### 1. Gap in Correctness Testing
**Problem:** Phase 06 (I1-I6 Correctness Audit) had 35 tests, but ATR bug still slipped through.

**Why:**
- Tests may have covered execution flow, not mathematical correctness
- No reference implementation validation
- No invariant tests for edge cases

**Fix:** Reference validation tests for all financial math

### 2. Missing Reference Implementations
**Problem:** No systematic validation against established libraries (pandas-ta, TA-lib).

**Why:**
- Assumed custom implementation was correct
- No formal correctness requirements
- No "trust but verify" culture

**Fix:** Every mathematical computation must have reference validation

### 3. Insufficient Edge Case Coverage
**Problem:** Edge cases (gaps, limits, zero volume) not tested.

**Why:**
- Focused on "happy path" testing
- No adversarial testing mindset
- No financial domain expert review

**Fix:** Comprehensive edge case suite for all computations

## Prevention Mechanisms

### 1. Reference Validation Tests
```python
def test_atr_against_pandas_ta():
    """Our ATR must match pandas-ta reference implementation."""
    # Load test data
    # Compute our ATR
    # Compute pandas-ta ATR
    # Assert: max error < 1e-6
```

### 2. Invariant Tests
```python
def test_atr_invariants():
    """ATR must maintain these mathematical properties."""
    # ATR is always non-negative
    # ATR is bounded by max price range
    # ATR is monotonic during low volatility
```

### 3. Edge Case Tests
```python
def test_atr_edge_cases():
    """ATR must handle edge cases correctly."""
    # Single bar (no history)
    # Gap up/down (open != prev_close)
    # Zero volatility (all bars same price)
```

### 4. CI Gate
- Correctness tests must pass before any merge
- No exceptions, no "fix later"
- Mathematical correctness is non-negotiable

## Cultural Changes Needed

### From: "Move fast and break things"
**To:** "First, do no harm."

### From: "Tests cover execution flow"
**To:** "Tests prove mathematical correctness."

### From: "Custom implementation is fine"
**To:** "Validate against reference implementations."

### From: "Edge cases are rare"
**To:** "Edge cases happen in production. Plan for them."

## Next Steps

1. **Root cause analysis** — What exactly was wrong with ATR?
2. **Fix implementation** — Patch production code
3. **Add reference validation** — Prevent this class of bug
4. **Audit other computations** — ATR is the canary in the coal mine
5. **Define correctness standards** — What does "correct" mean?

---

**Lesson:** Mathematical correctness is not a nice-to-have. It's the foundation of everything we build.
