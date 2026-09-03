---
name: 2026-09-03-agy-review-prereg2-script
description: AGY review of the pre-registration-2 diagnostic SCRIPT as run (post-run), plus adjudication
provenance: Review by AGY (backend live), run 2026-09-03, prompt /tmp/agy_prompt_prereg2_script.txt pointing at the script by path. Adjudication by Claude (this session) follows the verbatim review.
---

A review of `/home/bg/dev/indicagent/scripts/analysis/alpha_score_residual_single_security_15m.py` focused strictly on statistical and algorithmic correctness bugs yields the following findings:

---

### 1. Raw Comparison Arm Evaluated Against Residual Null Distribution
* **Severity:** **HIGH**
* **Location:** Lines 185, 199, and 318 ([alpha_score_residual_single_security_15m.py:185-201](file:///home/bg/dev/indicagent/scripts/analysis/alpha_score_residual_single_security_15m.py#L185-L201), [alpha_score_residual_single_security_15m.py:314-318](file:///home/bg/dev/indicagent/scripts/analysis/alpha_score_residual_single_security_15m.py#L314-L318))
* **Description:** 
  In the raw score arm, `family_stat` and `bootstrap_ci` take `score_override=A["raw"]`:
  ```python
  raw_stat = panel.family_stat(score_override=A["raw"])
  raw_lo, raw_hi = panel.bootstrap_ci(rng_boot_raw, n_boot, score_override=A["raw"])
  raw_p = panel.sync_shift_null_p(raw_stat, rng_null_raw, _N_NULL)
  ```
  However, `sync_shift_null_p` does **not** accept a `score_override` parameter. Inside `sync_shift_null_p` (line 199), it evaluates:
  ```python
  vals.append(_spearman(self.scores[idx], self.returns[sl]))
  ```
  Since `panel` was initialized with `self.scores = A["resid"]`, the null distribution generated in line 318 is built entirely from circular shifts of the **residual** scores, not raw scores. The observed `raw_stat` is tested against permutations of residuals, making `raw_p` statistically invalid.

---

### 2. Identity Permutation (Zero Shift) in `sync_shift_null_p` When `k % m == 0`
* **Severity:** **HIGH**
* **Location:** Lines 189–194 ([alpha_score_residual_single_security_15m.py#L189-L194](file:///home/bg/dev/indicagent/scripts/analysis/alpha_score_residual_single_security_15m.py#L189-L194))
* **Description:**
  The family shift draw is:
  ```python
  k = int(rng.integers(1, n_cal))
  ...
  m = len(starts)
  perm = (np.arange(m) + k % m) % m
  ```
  Symbols in the panel have varying histories and date counts $m$ (e.g., symbols like `VRP` have 100 dates, `ETHA` has 205, `COIN` has 903, whereas $n_{\text{cal}} \approx 3469$).
  
  Whenever a replicate draw $k$ is an integer multiple of a symbol's date count $m$, `k % m == 0`. When this occurs:
  - `perm` becomes `np.arange(m)` (shift = 0).
  - `idx` equals the unpermuted indices.
  - The calculated correlation is the **true, unshifted observed correlation** of that symbol.
  
  For a symbol with $m = 100$, exactly 34 values of $k \in [1, 3468]$ yield $k \pmod{100} = 0$ (~1.0% of replicates). In those replicates, the residual is paired directly with its own forward return at the identical bar. This injects the true alternative signal into the null distribution, artificially inflating null replicates toward the observed statistic and deflating statistical power. *(Note: `_per_symbol_table` avoids this by drawing `rng.integers(1, m)`).*

---

### 3. False-Positive Significance ($p \approx 0.001$) on NaN Inputs
* **Severity:** **MEDIUM-HIGH**
* **Location:** Lines 205–206 and Lines 228–231 ([alpha_score_residual_single_security_15m.py#L205-L206](file:///home/bg/dev/indicagent/scripts/analysis/alpha_score_residual_single_security_15m.py#L205-L206), [alpha_score_residual_single_security_15m.py#L228-L231](file:///home/bg/dev/indicagent/scripts/analysis/alpha_score_residual_single_security_15m.py#L228-L231))
* **Description:**
  In `_per_symbol_table`:
  ```python
  null_ic = _spearman(panel.scores[idx], y)
  if not np.isnan(null_ic) and null_ic >= ic:
      beat += 1
  null_p = (1 + beat) / (_N_SHIFT + 1)
  ```
  If a symbol has a degenerate series (e.g., constant score or return, $\sigma < 10^{-12}$), `_spearman` returns `NaN`. In Python/NumPy, any comparison `null_ic >= float("nan")` evaluates to `False`.
  
  Consequently, `beat` stays `0`, and the function outputs:
  $$\text{null\_p} = \frac{1 + 0}{1000 + 1} \approx 0.000999$$
  An entirely uninformative, degenerate series is assigned near-maximum statistical significance ($p \approx 0.001$). This false p-value enters `multipletests(..., method="fdr_by")`, distorting the BY-FDR critical values and rank thresholds across all symbols.
  
  The identical bug exists in `sync_shift_null_p` (line 205): if `observed` is NaN, `r >= observed` is always False, returning $p \approx 0.001$ and causing gate condition (2) (`resid_p < 0.05`) to spuriously pass.

---

### 4. Non-Deterministic Concurrency & Race Conditions on `np.random.Generator`
* **Severity:** **MEDIUM**
* **Location:** Lines 168–181 (`bootstrap_ci`) and Lines 188–204 (`sync_shift_null_p`) ([alpha_score_residual_single_security_15m.py#L168-L181](file:///home/bg/dev/indicagent/scripts/analysis/alpha_score_residual_single_security_15m.py#L168-L181), [alpha_score_residual_single_security_15m.py#L188-L204](file:///home/bg/dev/indicagent/scripts/analysis/alpha_score_residual_single_security_15m.py#L188-L204))
* **Description:**
  `rng` is passed as a single `np.random.Generator` instance into `bootstrap_ci` and `sync_shift_null_p`. The worker closures `_one_rep` are executed via `ThreadPoolExecutor(max_workers=8)` and call `rng.integers(...)` concurrently across 8 threads without locking.
  - Per NumPy's specification, `BitGenerator` instances are **not thread-safe**; concurrent access causes data races on internal generator state.
  - Unsynchronized thread scheduling makes the sequence of random numbers consumed per replicate non-deterministic. Even with deterministic seeds (`hash_key_to_int(...)`), runs will produce differing CI boundaries and p-values.
  - *(Note: as documented in [`ic_math.py:248-251`](file:///home/bg/dev/indicagent/src/intelligence/statistics/ic_math.py#L248-L251), RNG index generation must be executed strictly serially before dispatching compute-heavy blocks to worker threads).*

---

### 5. Shift Modulo Symbol Length Destroys Cross-Sectional Synchrony and Induces Same-Date Intra-Day Overlap
* **Severity:** **MEDIUM**
* **Location:** Lines 191–199 ([alpha_score_residual_single_security_15m.py#L191-L199](file:///home/bg/dev/indicagent/scripts/analysis/alpha_score_residual_single_security_15m.py#L191-L199))
* **Description:**
  The docstring specifies that the null "preserves within-date cross-sectional structure and time-of-day alignment".
  1. **Loss of Cross-Sectional Synchrony:** Because symbols have different numbers of dates $m_s$, applying $k \pmod{m_s}$ shifts each symbol by an idiosyncratic calendar distance along its active history. At any given replicate index, Symbol A's residuals originate from one calendar date while Symbol B's originate from a completely different calendar date (often years apart). Cross-sectional alignment across symbols is not preserved.
  2. **Intra-Day Same-Date Contamination:** Marginal distributions are strictly preserved because all rows are permuted without omission or duplication. However, date bar lengths (`counts`) vary due to early closes (e.g., 13 bars) or missing bars. Because output block $j$ takes source length `counts[perm[j]]` while returns remain unshifted with length `counts[j]`, cumulative block boundaries drift. When a prior date has fewer bars, subsequent dates in `scores[idx]` shift earlier into the flattened array and can overlap with the **same date** in `returns[sl]`, causing residuals from date $D$ to be paired with returns from date $D$ at different intra-day offsets (e.g. bar $b$ paired with bar $b - 10$).

---

### 6. Loaded APR Config Silently Ignored in `_per_symbol_table`
* **Severity:** **LOW**
* **Location:** Lines 218 and 251–253 ([alpha_score_residual_single_security_15m.py#L218](file:///home/bg/dev/indicagent/scripts/analysis/alpha_score_residual_single_security_15m.py#L218), [alpha_score_residual_single_security_15m.py#L251-L253](file:///home/bg/dev/indicagent/scripts/analysis/alpha_score_residual_single_security_15m.py#L251-L253))
* **Description:**
  In `main()`, `block_size` and `n_boot` are read from the database config (`apr_dict`) and printed to stdout. However, `_per_symbol_table(panel)` does not accept these parameters and hardcodes:
  ```python
  ci_lo, ci_hi = _circular_block_bootstrap_ic(x, y, 26, 2000, rng_ci)
  ```
  Any change to `alpha.ic.bootstrap_block_size.15m` or `alpha.ic.bootstrap_resamples` in the database configuration will be silently ignored for all per-symbol bootstrap CIs.

---

### Verification of Components with No Errors
* **`_concat_ranges` Indexing:** Vectorized offset construction `offsets = np.cumsum(counts) - counts` and `np.repeat(src_starts, counts) + np.arange(tot) - np.repeat(offsets, counts)` is mathematically exact. It correctly handles arbitrary starts, irregular lengths, zero-length dates, and empty arrays without off-by-one errors.
* **`Panel` Index Structures (`cal_start`, `cal_len`, `sym_blocks`):** Because the query specifies `ORDER BY ev.symbol, ev.bar_ts`, every symbol forms a contiguous block of rows, and dates within each symbol are monotonically non-decreasing. `searchsorted` and `np.diff` correctly construct contiguous date partitions.
* **Bootstrap Calendar Resampling Synchrony:** Synchronous across symbols. Each replicate draws a single common calendar index `cal_idx`, and all symbols sample their bars matching those exact calendar dates.
* **Silent Data Loss / Double Counting:** None in the query streaming or panel construction; row counts match the SQL stream.
* **Verdict Conditions:** Conditions `c1` (CI lower > 0), `c2` (null p < 0.05), `c3` (point >= 0.0027), and `c4` (qualifying fraction >= 10%) correctly match the Amendment 1 pre-registered rules.
