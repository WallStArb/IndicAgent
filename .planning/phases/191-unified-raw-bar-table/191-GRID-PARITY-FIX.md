# Grid parity fix (2026-10-29)

Problem: the intraday `grid_parity` verdict re-bucketed canonical 5m bars into the IBKR archive's
15m/1h buckets and demanded exact equality. Since D-191-P the 5m from 2016-01-04 is Alpaca SIP, the
reference is IBKR SMART TRADES, and they legitimately differ, so the verdict failed for 886 names
(15m) and 887 (1h) and blocked the intraday D-32 gate of the 186-26 rebuild.

Fix (`services/bar_reconciliation_audit.py`):
- The audit's 5m loader now selects `vendor`; `_FiveMinute.ibkr` is a per-bar flag
  (`vendor = 'ibkr'`, any kind). The shared `bar_derivation._SELECT_5M_SQL` is unchanged.
- `judge_name_intraday` passes only ibkr-sourced bars to `rebucket_5m`. Because `rebucket_5m`
  returns a bucket only when every constituent is present, a bucket with any non-ibkr constituent
  drops out entirely: neither compared nor counted. Exactness on the remaining buckets is unchanged.
- Metric is the mismatched count; `None` when no bucket was comparable (a pass that measured
  nothing, same as the no-archive branch). The run log gains `grid_parity_compared_nothing`,
  `grid_parity_buckets_compared` and `grid_parity_buckets_mismatched` per timeframe, and the
  mismatch log lines carry `compared=`.

Meaning of "ibkr-sourced": the 5m bar's `vendor` is `ibkr`, any kind. The live canonical 5m holds
only (ibkr, named) and (alpaca, sip_rth); the archive is (ibkr, named). A future ibkr fallback 5m
would still be IBKR's own trades aggregate.

Live read-only sample (30 names, the changed loader and judge): see the task report. Residual
failures are real IBKR 5m versus IBKR 15m differences (volume off by 1 to 2 on pre-2016 BIIB and
OIH, thin late-print differences on AAP, ASTE, ACTG), not a structural cause.
