# Phase 093 CI Gate

## Summary

Phase 093 adds a `tests/unit/intelligence/correctness/` directory containing
mathematical correctness tests for all Tier 1 plugins. This document confirms
that the existing pytest configuration already picks up these tests and
specifies the slow-test CI policy.

## Discovery: No pytest.ini change required

`pytest.ini` already contains:

```ini
testpaths = tests
```

This causes `pytest tests/unit/` (and any `pytest` run with the default
testpaths) to recursively discover `tests/unit/intelligence/correctness/`.
No additional configuration is needed.

Verified by:

```bash
.venv/bin/pytest tests/unit/ --collect-only -q | grep -c "tests/unit/intelligence/correctness/"
# Returns: 96 (at least 1 is the requirement)
```

## Standard CI command

The CI command is unchanged:

```bash
.venv/bin/pytest tests/unit/ -v
```

This command runs the full correctness suite, including all tests added in
Phase 093, by default.

To run only the Phase 093 correctness tests:

```bash
.venv/bin/pytest tests/unit/intelligence/correctness/ -v
```

## Slow-test policy

### Slow tests run in CI

The `@pytest.mark.slow`-marked numerical stability tests (10K-bar runs) are
the stability gate for Phase 093 and MUST be executed on every CI run. CI
does NOT pass `-m "not slow"`.

The numerical stability tests (`test_numerical_stability.py`) drive each
plugin through 10,000 bars of synthetic data and assert all outputs remain
finite. Skipping these tests in CI would remove the primary regression guard
for numerical overflow, underflow, and filter divergence.

### Local fast-iteration opt-out

Developers may skip slow tests during local fast development by running:

```bash
.venv/bin/pytest tests/unit/ -m "not slow"
```

This opt-out is FORBIDDEN in CI. The `-m "not slow"` flag must never appear
in the CI pipeline configuration or CI scripts.

## Test files added by Phase 093

| File | Coverage |
|------|----------|
| `test_atr_reference.py` | ATR vs pandas-ta reference |
| `test_bollinger_reference.py` | Bollinger Bands vs pandas-ta reference |
| `test_macd_reference.py` | MACD vs pandas-ta reference |
| `test_rsi_reference.py` | RSI vs pandas-ta reference |
| `test_stochastic_reference.py` | Stochastic vs pandas-ta reference |
| `test_vwap_reference.py` | VWAP reference |
| `test_cci_reference.py` | CCI vs pandas-ta reference |
| `test_williams_r_reference.py` | Williams %R vs pandas-ta reference |
| `test_mfi_reference.py` | MFI vs pandas-ta reference |
| `test_adx_reference.py` | ADX vs pandas-ta reference |
| `test_kalman_invariants.py` | Kalman filter mathematical invariants |
| `test_garch_invariants.py` | GARCH(1,1) mathematical invariants |
| `test_efficiency_numeric_equivalence.py` | compute_full vs compute_next equivalence |
| `test_edge_cases.py` | Gap, zero volume, single bar, empty input |
| `test_numerical_stability.py` | 10K-bar numerical stability (slow) |

## Confirming the gate is in effect

The CI gate is already in effect via the existing `testpaths = tests`
configuration. No new configuration is required. Running:

```bash
.venv/bin/pytest tests/unit/ -v
```

will run all 96+ correctness tests, including the `@pytest.mark.slow`
numerical stability tests, blocking merges on any failure.
