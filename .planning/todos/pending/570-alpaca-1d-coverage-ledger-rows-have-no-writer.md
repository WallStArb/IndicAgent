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

Landed 2026-10-30: the writers now match the rebuild. `load_frame` refreshes a 1d series' bounds with
`refresh_1d_bounds` (the nightly no longer passes `coverage=False`); `count_new_slots` makes the incremental
row_count count distinct slots (AAPL: 258 iex_rth rows at stamps sip_rth already held); the nightly sink
records each series' newest request outcome as the ledger status, from one outcome mapping the rebuild's SQL is
generated from. Review findings not acted on, by design: status follows request rows even on a dry run (the
rebuild derives it from them); the 1d refresh is a separate idempotent transaction after the raw write.
Remaining: the one-off rebuild (queued behind the fetcher lock) repairs the existing drift; close this todo
after the next full audit reads coverage_cache clean.

Applied 2026-10-30 15:04 to 15:08 EDT (fetcher lock, role bar_derivation_writer): the full rebuild wrote 6,975
rows; the ledger now holds alpaca|1d for all 1,529 names. A rolled-back rebuild probe (REPEATABLE READ, 60 names,
309 series) shows 0 drifting names, against all 60 missing a 1d row and 5 names with other drift before. Close
this todo when the 02:00 ET full audit reads coverage_cache clean for all names.
