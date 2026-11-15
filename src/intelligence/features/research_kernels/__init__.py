"""Research-only kernels under the phase 186 registry contract (184 B2, design D5 revision 3).

Each kernel here is a `Kernel` with declared inputs, declared memory and a pure compute, held
to the same causality probe and memory check as the stored kernels. The package sits outside
`kernels/` on purpose: `default_registry()` never discovers it, so no stored column or schema test changes. Only `src/intelligence/research/kernel_source.py` imports it,
and only for a (statistic, window) no stored column computes (184-REVIEWS row 10). The percentile family still
here carries a pending todo (550) to move it into the registry, after which the package is
deleted; the max-distance and VWAP-deviation families already live in `kernels/_windowed.py`.
"""
