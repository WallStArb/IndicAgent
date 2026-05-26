---
phase: 093-mathematical-correctness-audit
reviewed: 2026-05-21T00:00:00Z
depth: standard
files_reviewed: 22
files_reviewed_list:
  - src/intelligence/features/i1_indicators/cci.py
  - src/intelligence/features/i1_indicators/mfi.py
  - src/intelligence/features/i1_indicators/stochastic.py
  - src/intelligence/features/i1_indicators/williams_r.py
  - src/intelligence/features/i5_patterns/bollinger_squeeze.py
  - src/intelligence/trading/volume_zscore.py
  - tests/unit/intelligence/correctness/conftest.py
  - tests/unit/intelligence/correctness/test_adx_reference.py
  - tests/unit/intelligence/correctness/test_atr_reference.py
  - tests/unit/intelligence/correctness/test_bollinger_reference.py
  - tests/unit/intelligence/correctness/test_cci_reference.py
  - tests/unit/intelligence/correctness/test_edge_cases.py
  - tests/unit/intelligence/correctness/test_efficiency_numeric_equivalence.py
  - tests/unit/intelligence/correctness/test_garch_invariants.py
  - tests/unit/intelligence/correctness/test_kalman_invariants.py
  - tests/unit/intelligence/correctness/test_macd_reference.py
  - tests/unit/intelligence/correctness/test_mfi_reference.py
  - tests/unit/intelligence/correctness/test_numerical_stability.py
  - tests/unit/intelligence/correctness/test_rsi_reference.py
  - tests/unit/intelligence/correctness/test_stochastic_reference.py
  - tests/unit/intelligence/correctness/test_vwap_reference.py
  - tests/unit/intelligence/correctness/test_williams_r_reference.py
findings:
  critical: 1
  warning: 4
  info: 3
  total: 8
status: issues_found
---

# Phase 093: Code Review Report

**Reviewed:** 2026-05-21
**Depth:** standard
**Files Reviewed:** 22
**Status:** issues_found

## Summary

This phase delivers a mathematical correctness audit for six indicator/pattern plugins (CCI, MFI, Stochastic, Williams %R, BollingerSqueeze, VolumeZscore) plus a comprehensive test suite. The test design is generally sound — reference comparison against pandas-ta, incremental-vs-full consistency checks, numerical stability over 10K bars, and edge-case coverage. The GARCH and Kalman invariant tests are particularly thorough.

One critical bug was found in MFIPlugin: `compute_full` returns `0.0` when all money flow is positive (neg_sum=0, pos_sum>0) instead of the correct `100.0`. This is a formula error that the test suite does not catch. Four warnings cover: a dead-code `np.partition` call that runs but discards its result, a `compute_full` state parameter that is silently shadowed, a fragile column-position index in a test, and the `inputs` field type annotation violating the plugin protocol on four files. Three info items cover incorrect type annotations and a mislabeled comment.

---

## Critical Issues

### CR-01: MFIPlugin.compute_full Returns 0.0 Instead of 100.0 When All Money Flow Is Positive

**File:** `src/intelligence/features/i1_indicators/mfi.py:40-44`

**Issue:** `compute_full` handles the zero-negative-money-flow case incorrectly. When `neg_sum == 0` and `pos_sum > 0` (all 14 consecutive bars had TP >= prev_TP, e.g. sustained uptrend), the correct MFI is `100.0`. Instead the code does:

```python
neg_sum = neg_mf.rolling(window=p, min_periods=p).sum().replace(0, pd.NA)
mfr = pos_sum / neg_sum   # NaN when neg_sum was 0
mfi = 100 - (100 / (1 + mfr))  # NaN
val = mfi.iloc[-1]        # NaN
out[f"mfi_{p}"] = float(val) if pd.notna(val) else 0.0  # emits 0.0 -- WRONG
```

`compute_next` handles the same case correctly at lines 122-123:
```python
if neg_sum == 0:
    out[key] = 100.0 if pos_sum > 0 else 0.0
```

The inconsistency between paths means MFI can read `0.0` (extreme bearish) during a strong sustained uptrend when computed via the full path. This creates a direction-inverted signal. The test suite does not catch this because `test_mfi_output_range` only checks bounds (0.0 passes the `>= 0` check) and the pandas-ta reference comparison likely produces NaN for the same edge case, which is dropped by the valid-mask filter.

**Fix:**
```python
# After computing pos_sum and before dividing:
pos_sum = pos_mf.rolling(window=p, min_periods=p).sum()
neg_sum_raw = neg_mf.rolling(window=p, min_periods=p).sum()
mfr = pos_sum / neg_sum_raw.replace(0, pd.NA)
mfi = 100 - (100 / (1 + mfr))
# Handle all-positive-flow edge case:
mfi = mfi.where(neg_sum_raw != 0, other=pos_sum.where(pos_sum > 0, 0.0).where(pos_sum == 0, 0.0))
# Simpler alternative: post-process
mfi = mfi.where(neg_sum_raw != 0, other=(pos_sum > 0).astype(float) * 100.0)
val = mfi.iloc[-1]
out[f"mfi_{p}"] = float(val) if pd.notna(val) else 0.0
```

Also add a test:
```python
def test_mfi_all_positive_flow_returns_100():
    """When neg_sum=0 and pos_sum>0, compute_full must return 100.0 not 0.0."""
    # 15 bars of strictly increasing TP ensures no negative money flow
    plugin = MFIPlugin()
    n = 16
    prices = np.linspace(100.0, 110.0, n)
    df = pd.DataFrame({"high": prices+0.1, "low": prices-0.1,
                       "close": prices, "volume": np.ones(n)*1000})
    result = plugin.compute_full({"main": df})
    assert result.get("mfi_14") == 100.0, f"Expected 100.0, got {result.get('mfi_14')}"
    # Also verify compute_next agrees
    state = result["_state"]
    ...
```

---

## Warnings

### WR-01: Dead Computation — np.partition Result Discarded in BollingerSqueeze

**File:** `src/intelligence/features/i5_patterns/bollinger_squeeze.py:78` and `:170`

**Issue:** `np.partition` is called, the kth element is retrieved, but the result is assigned to `_` and never used. The actual percentile computation on the very next line uses `np.sum(bw_arr <= current_bw)` which does not need partition at all. This runs in every bar in both `compute_full` and `compute_next`, allocating a full copy of the bandwidth array each time for zero benefit.

```python
# compute_full line 78:
_ = np.partition(bw_arr, k)[k]  # kth-element selection; confirms O(n) path

# compute_next line 170:
_ = np.partition(bw_arr, k)[k]  # kth-element selection; confirms O(n) path
```

The comments describe this as "confirming" the O(n) path, but confirmation-by-dead-call is not a valid test mechanism — it does not assert anything. If the intent was to demonstrate the approach, the code should actually use the partition result, or the call should be removed.

**Fix:** Remove both `_ = np.partition(...)` lines entirely. The rank-based percentile using `np.sum(bw_arr <= current_bw)` is correct and sufficient.

---

### WR-02: compute_full State Parameter Silently Shadowed in WilliamsRPlugin and StochasticPlugin

**File:** `src/intelligence/features/i1_indicators/williams_r.py:28` and `src/intelligence/features/i1_indicators/stochastic.py:31`

**Issue:** Both `WilliamsRPlugin.compute_full` and `StochasticPlugin.compute_full` declare a `state: dict | None = None` parameter, but the first statement of the function body creates a new local `state = {}`, completely shadowing the parameter. Any caller passing `state=some_dict` to `compute_full` has their value silently ignored.

```python
# williams_r.py line 28-46:
def compute_full(
    self, frames: dict[str, pd.DataFrame], *, state: dict | None = None  # <-- parameter
) -> dict[str, Any]:
    ...
    state = {}  # <-- shadows the parameter at line 46; incoming state is lost
    self._seed_state(frames, state)
    out["_state"] = state
```

In contrast, `CCIPlugin.compute_full` and `MFIPlugin.compute_full` correctly omit the `state` parameter. This inconsistency could cause confusing behavior if `compute_full` is ever called with an intent to pre-populate state.

**Fix:** Remove the `state: dict | None = None` parameter from both `compute_full` signatures:
```python
def compute_full(self, frames: dict[str, pd.DataFrame]) -> dict[str, Any]:
```

---

### WR-03: Fragile Column-Position Access for pandas-ta Stochastic Output

**File:** `tests/unit/intelligence/correctness/test_efficiency_numeric_equivalence.py:193-194`

**Issue:** The Stochastic numeric equivalence test accesses pandas-ta result columns by position (`iloc[:, 0]` and `iloc[:, 1]`) rather than by name. If pandas-ta ever changes its column ordering (has happened between minor versions), the test silently validates the wrong columns — `%K` compared to `%D` and vice versa — yielding a misleading green test.

```python
ref_k = ref_stoch.iloc[:, 0].iloc[warmup:].reset_index(drop=True)  # fragile
ref_d = ref_stoch.iloc[:, 1].iloc[warmup:].reset_index(drop=True)  # fragile
```

The companion test `test_stochastic_reference.py` (lines 59-60) correctly uses named column access:
```python
ref_k = pd.Series(ref["STOCHk_14_3_1"].values, index=df.index)
ref_d = pd.Series(ref["STOCHd_14_3_1"].values, index=df.index)
```

**Fix:**
```python
ref_k = ref_stoch[f"STOCHk_{k_period}_{d_period}_1"].iloc[warmup:].reset_index(drop=True)
ref_d = ref_stoch[f"STOCHd_{k_period}_{d_period}_1"].iloc[warmup:].reset_index(drop=True)
```

---

### WR-04: inputs Field Type Annotation Violates Plugin Protocol on Four Source Files

**File:** `src/intelligence/features/i1_indicators/cci.py:19`, `mfi.py:19`, `stochastic.py:20`, `williams_r.py:19`

**Issue:** The plugin protocol (documented in `src/intelligence/CLAUDE.md`) requires:
> Use `frozenset[str]` for `outputs`/`capability_tags`, `tuple[InputSpec, ...]` for `inputs` — not `set`/`list`.

All four plugins declare:
```python
inputs: list[InputSpec] = (InputSpec(symbol=".*", lookback=100),)
```

The type annotation says `list[InputSpec]` but the default value is a tuple. This is a type contradiction: the annotation will fail static analysis (mypy/pyright) and violates the documented convention. `VolumeZscorePlugin` correctly uses `inputs: tuple = (...)`.

`BollingerSqueezePlugin` (`bollinger_squeeze.py:22`) has the same issue.

**Fix:** Update all five files to use the correct annotation:
```python
inputs: tuple[InputSpec, ...] = (InputSpec(symbol=".*", lookback=100),)
```

---

## Info

### IN-01: periods and configs Type Annotations Are Optional but Not Declared as Such

**File:** `src/intelligence/features/i1_indicators/cci.py:20`, `mfi.py:20`, `stochastic.py:21`, `williams_r.py:20`

**Issue:** All four plugins declare `periods: list[int] = None` (or `configs: list[tuple[int,int]] = None`). The type annotation `list[int]` is incorrect — the actual type is `list[int] | None`. This is not a mutable default argument problem (using `None` as sentinel is correct), but the annotation misleads static analysis and documentation.

**Fix:**
```python
periods: list[int] | None = None
configs: list[tuple[int, int]] | None = None
```

---

### IN-02: conftest.py "Inner Join" Comment Is Misleading — Actual Behavior Is Outer Join

**File:** `tests/unit/intelligence/correctness/conftest.py:228-229`

**Issue:** The comment says "Inner join on index" but `dropna(how="all")` performs an outer join, retaining rows where at least one series has a value. A true inner join would use `dropna(how="any")`. The subsequent NaN filter at line 244 (`aligned_ours.notna() & aligned_ref.notna()`) recovers correct behavior, but the comment is wrong and creates confusion for anyone extending the helper.

```python
# Inner join on index   <-- WRONG: this is an outer join (dropna(how="all"))
combined = pd.DataFrame({"o": ours, "r": reference}).dropna(how="all")
```

**Fix:** Either change the comment to "Outer join; NaN rows filtered below", or change `how="all"` to `how="any"` for a true inner join (both are functionally equivalent here due to line 244, but explicit intent is clearer).

---

### IN-03: Unused Import — pandas_ta noqa Suppression in test_atr_reference.py

**File:** `tests/unit/intelligence/correctness/test_atr_reference.py:17`

**Issue:** `pandas_ta` is imported with `# noqa: F401` and the comment "used via pandas accessor below", but the file accesses `pandas_ta.atr(...)` directly by name — not via a pandas accessor (`.ta.atr()`). The `noqa` suppression is incorrect and masks an import that is actually used directly.

```python
import pandas_ta  # noqa: F401 (used via pandas accessor below)
```

**Fix:** Remove the `# noqa: F401` comment since the import is legitimately used:
```python
import pandas_ta
```

---

_Reviewed: 2026-05-21_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
