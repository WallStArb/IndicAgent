# 190 downstream: the Alpaca lanes and their prerequisites

Status: current (updated 2026-10-10, T4 landing)
Author: Brandon with Claude Code (session indicagent-49)

The canonical Alpaca deep-history work runs as queue lanes in the unified fetcher (design
step 3) and is downstream of todo 521's admission build. This note names the exact entry
points so no later session builds a second fetch path.

## What already exists (as of 2026-10-10)

- **The leaf**: `src/providers/alpaca.py` satisfies `HistoryProvider` (SIP feed, loud
  adjustment mapping, budget-stopped pagination, authoritative-empty verdicts,
  RequestRecord capture) and is reachable through `history_leaf("alpaca", ...)`. It passed
  the conformance bar (`tests/unit/test_alpaca_provider.py`, the behavioral cases from
  190-01's suite shape).
- **The nightly capture runner**: `scripts/ops/bars/ops_bar_nightly.py` (todo 521 T4) pulls
  the recent tail natively through the engine: 5m authors via `load_series`, 1d is
  raw-capture only, request rows via the D1 sink. Unscheduled by the owner's 2026-10-10
  pull freeze; the reopen is a systemctl line.

**Deliberate deviation, recorded:** design rev 2 banned an interim separate Alpaca oneshot
(second hypertable writer, second fetch path) for the deep-history campaign. The nightly
capture runner is not that: it is 521's T4 tail-capture shell on the shared engine, with no
campaign depth and no second writer path. The ban stands for campaign lanes; the end state
remains those lanes running inside the unified fetcher's loop.

## Prerequisites for the alpaca ProviderEntry (the unified-loop lane)

1. A ProviderEntry in the fetcher's registry: `leaf_factory` (exists, via `history_leaf`)
   plus a `fetch` hook wrapping the fetch-loop mechanics — the leaf's `fetch_ohlcv` is not
   by itself the whole item path.
2. The 5m multi-source policy doc + `bar_source_policy` rows (521 dependency 1).
3. D7 vendor-agreement extension to the second tape (521 dependency 2).
4. `answers_1d=False` in its ProviderPlan: never Alpaca 1d bars (the writer fence enforces
   it in the engine; the plan asserts it at planning).
5. `_REBUILD_FILTERS` entry in `services/ohlcv_coverage_writer.py` (deliberately absent
   until then).
6. APR seeds exist (469: pacing + nightly window); campaign depth knobs would seed at
   lane-build time with [measured] provenance.

A vendor-blind ItemRunner that would collapse the per-vendor fetch hook to one file is a
candidate refactor when this lane is built, not before (YAGNI, adjudication item 7).
