"""Research-only kernels under the phase 186 registry contract (184 B2, design D5 revision 3).

Each kernel here is a `Kernel` with declared inputs, declared memory and a pure compute, held
to the same causality probe and memory check as the stored kernels. The package sits outside
`kernels/` on purpose: `default_registry()` never discovers it, so no stored column, schema test
or rebuild import closure changes. Only `src/intelligence/research/kernel_source.py` imports it,
and only for a (statistic, window) no stored column computes (184-REVIEWS row 10). Each family
carries a pending todo to move it into phase 186's registry once the rebuild's import closure
unfreezes, after which the research copy is deleted.
"""
