---
status: pending
priority: P1
filed: 2026-11-01
source: owner question 2026-11-01 ("why aren't batch and real-time sharing infrastructure, a bar is a bar"); coordinator code check
---

# One HTF derivation rule set before the real-time feed returns

The storage layer is already one plane: both paths land vendor answers in `ohlcv_raw` through
the same `write_raw`/`persist_chunk_atomically` ingress and flow through the same selection,
derivation and audit chain (phase 191's whole point). Transport differs by design (Redpanda
push vs vendor pull; the real-time path never touches the database directly). That separation
is SoC, not duplication.

The remaining fork is derived bars: `src/core/bar_accumulator.py` implements its own 1m->HTF
aggregation with its own session-break logic (`TradingSession`), while the batch grid (15m/1h)
is derived by `bar_derivation --stage grid` over `src/intelligence/bars/session_grid.py` rules.
Two rule sets for one derived bar means the feed's return silently diverges real-time HTF bars
from the canonical grid (the D2a scrub, complete-bar and session rules would not apply on the
streaming side).

Fix before reactivation (todo 579's note enables the units): either make `BarAccumulator`'s
completion boundary call the batch derivation rules (shared library, streaming just triggers),
or restrict the real-time path to base bars and let the grid stay batch-only. Decide by the
recovery unlock keys (todo 497) so the feed never publishes a second truth.

Done when: one rule set constructs HTF bars for both paths, or the streaming path is
documented base-bars-only in the reactivation note, with a test proving the boundary.
