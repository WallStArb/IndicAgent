# Phase 191 deferred items

Out-of-scope discoveries logged during execution (not fixed; the executor's scope boundary
applies). Newest first.

## 2026-10-17, plan 191-14 (executor)

1. **Live-data: 1d lineage gaps from raw re-serves pending canonical refresh.**
   `tests/integration/test_d2_single_writer_live.py::test_every_visible_1d_bar_has_lineage_with_request_ids`
   fails on live data: 16 bars dated 2026-10-08 (plus scattered singles back to September)
   where `ohlcv_raw` holds an ibkr smart_trades re-serve with volume differing by exactly 1
   share from the stored canonical row (ARKK example: canonical 2,570,400 vs raw 2,570,399).
   The lineage view's OHLCV equality then finds no match. Verified identical in
   `market_data_ohlcv_old` (pre-swap table), so this predates the plan 14 swap; the assertion
   has simply been unrunnable since migration 485 broke the integration harness replay
   (191-07, fixed in e15fb5108). Expected to self-resolve when the nightly canonical refresh
   lane runs again after the cutover window; re-run the test after one nightly cycle and
   investigate only if the count grows.

2. **Live-data: derived 1h volume deficit vs ibkr 1d observations for CTVA, ETHA, MDGL.**
   `tests/integration/test_derived_grid_live.py::test_1h_volume_close_and_open_agree_with_ibkr_smart_1d_observations`
   fails: median (1d obs volume - derived 1h sum)/1d obs beyond 0.005 for those three names
   (worst 2.0). Verified by running the pre-191-14 source-based query against
   `market_data_ohlcv_old`: the same three names flag, so the condition predates the vendor/kind
   swap. All three look like vendor volume-reporting disagreements (ETHA is an ETF; smart_trades
   volume can exceed the 5m-derived grid's consolidated volume by multiples). Needs a measured
   vendor-fact look, not a code change; candidate for a todo if it persists after the next
   derivation rebuild.
