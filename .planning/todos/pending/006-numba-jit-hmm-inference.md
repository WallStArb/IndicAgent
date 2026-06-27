# 006 — Numba JIT HMM Forward-Filter (regime_writer speedup)

**Priority: Medium — regime_writer currently takes 20+ hours; this reduces to ~30 min**
**Gate: After v3.1 corpus pipeline stabilizes and K=5 regime labels are validated**
**Source:** `docs/plans/2026-06-26-renaissance-optimization-roadmap.md` (ARCH-003)

---

## Problem

`regime_writer.py` runs GaussianHMM inference (forward-filter) once per bar during backfill.
For 58 symbols × 4 TFs × 500K+ bars each = ~116M forward-filter passes. The forward-filter
is O(K^2 × T) where K=5 states. With Python/scikit-hmmlearn doing this, backfill takes 20+
hours with 12 workers.

Numba JIT compilation of the forward-filter inner loop can achieve 20-50x speedup, reducing
full corpus regime labeling from 20 hours to ~30 minutes.

---

## Fix

Add a numba-JIT forward-filter to `src/intelligence/hmm_utils.py` (or equivalent):

```python
from numba import jit, prange

@jit(nopython=True, parallel=True, cache=True)
def forward_filter_jit(
    obs: np.ndarray,        # [T, D] observations
    startprob: np.ndarray,  # [K]
    transmat: np.ndarray,   # [K, K]
    emitmeans: np.ndarray,  # [K, D]
    emitcovars: np.ndarray  # [K, D] diagonal covariance
) -> np.ndarray:            # [T, K] filtered state probabilities (log space)
```

Extract trained HMM parameters from scikit-hmmlearn's GaussianHMM after fitting (keep
fitting via hmmlearn — only replace inference). Feed parameters into JIT filter for
all backfill decoding.

Key implementation notes:
- Use log-space arithmetic to prevent underflow (standard for HMM)
- `parallel=True` with `prange` over K states in inner loop
- `cache=True` to avoid recompilation on each run
- Keep `hmmlearn.GaussianHMM` for fitting — replacing the fitter is a separate problem

---

## Scope

- `src/intelligence/hmm_utils.py` or new `src/intelligence/hmm_jit.py`
- `services/regime_writer.py` — swap `model.decode()` call for JIT filter
- Add `numba` to `pyproject.toml` dependencies
- Unit test: JIT output matches hmmlearn decode on same parameters (tolerance 1e-6)

Note: Numba adds a one-time JIT compilation cost (~2s) on first call per session. Negligible
for a service that runs for hours.
