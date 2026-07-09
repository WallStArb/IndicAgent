# 087 — Shared chunked-cursor-to-numpy helper

Source: `/simplify` 4-agent review of the 2026-07-09 `ic_engine.py` per-symbol OOM fix (reuse +
altitude agents independently converged on the same finding).

The "buffer rows into a Python list, convert to a typed numpy array once a chunk threshold is
hit, accumulate chunks, concatenate/vstack at the end" idiom now exists as three independent
hand-rolled implementations:

1. `services/ic_engine.py::_compute_cross_sectional_tf` (pre-existing, commit `95a57806`-era) —
   chunks by pre-fetched timestamp list, unnamed cursor re-executed per chunk.
2. `services/ic_engine.py::_compute_symbol_tf` (new, 2026-07-09) — named server-side cursor +
   `itersize`, chunks by row-count threshold during iteration.
3. `services/ensemble_ic_engine.py`'s pooled worker fetch (migration 209) — named cursor +
   `itersize`, but reduces via `_aggregate_pooled_series` instead of building a full matrix.

Each is independently the correct fix for its own OOM, and each has different enough mechanics
(named vs re-executed cursor, `RealDictCursor` vs positional tuples, reduce-as-you-go vs full
materialization) that unifying them wasn't in scope for any single bugfix. But this is the third
occurrence of the same OOM-mitigation shape in the same service-file family in about a month —
worth a real generalization pass: a shared helper in `services/_batch_utils.py` (which already
houses `connect_db_from_url`, explicitly shared by these same two files) for "declare a named
cursor with itersize, stream rows into chunked float32 arrays, vstack, free intermediates" would
mean the next symbol/tf-shaped OOM in this codebase doesn't need to be independently
rediscovered, implemented, and reviewed a fourth time.

Not urgent — no correctness issue, all three sites are currently correct and tested. Low
priority, opportunistic (e.g. bundle with the next touch to any of these three functions).
