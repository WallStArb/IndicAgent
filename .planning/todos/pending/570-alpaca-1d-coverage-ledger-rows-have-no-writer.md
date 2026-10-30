---
status: pending
priority: P1
filed: 2026-10-30
source: data lane, coverage_cache diagnosis (fails all 1,529 names in the 2026-10-30 full sweep)
---

# No writer creates the alpaca 1d ohlcv_coverage rows

The ledger holds `alpaca|5m` for 1,529 names (the intraday persist path writes it) but no
`alpaca|1d` row. The audit's `coverage_cache` check rebuilds the ledger from `ohlcv_raw` and finds
the 1d rows missing for every name, so it fails all 1,529. A diagnostic over 60 names (rolled back)
showed the same and a few real drifts: AAPL alpaca 5m row_count 474,919 stored vs 474,661 rebuilt,
KRE ibkr 5m off by one, CCO alpaca 5m status `ok` vs `no_data`.

A one-off `rebuild_from_stored_state` (fetcher lock, role `bar_derivation_writer`) clears it for
the moment (run 2026-10-30, queued behind the fetcher lock). It does not keep it cleared: the
Alpaca 1d load and the daily derivation timer must write the ledger row through
`upsert_coverage`, or the next night's audit fails every name again. Find the Alpaca 1d writer,
route it through the ledger writer, and test that a 1d load leaves a row the audit's rebuild
reproduces.
