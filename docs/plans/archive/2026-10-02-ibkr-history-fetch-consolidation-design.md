# IBKR history fetch consolidation: one fetcher, one ledger, one queue (phase 189)

Original: 2026-10-02 (approved; landed as phase 189).
Archived 2026-10-31: landed design, kept for the incident and the consolidation rule.

Kept: four independent fetch paths arbitrating one IBKR history connection through a DB lease
produced a multi-hour stall with zero bars written when the priority holder silently hung
(reqHistoricalDataAsync had no per-request timeout, todo 488); lease arbitration worked as
designed and still starved the bulk lane. Separately, the bulk lane wrote to the archive
table while coverage was checked against the grid table, so promotion lag read as missing
data (HPQ: 0 grid rows, 35k archive rows). One fetcher, one coverage ledger, one queue is the
fix; the fetcher is timeframe-agnostic and planner data is per-provider.

Full text in git history at docs/plans/2026-10-02-ibkr-history-fetch-consolidation-design.md as of 708f3fe09.
