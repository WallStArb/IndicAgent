# Alpaca 5m admission build (todo 521)

Original: 2026-10-09 (green-lit; amended 2026-10-10 after the audit).
Archived 2026-10-31: executed build, kept for the audit finding and the admission gates.

Kept: the 2026-10-10 audit found the T2 loader dropped two categories of vendor-served bars
instead of persisting them (stored-held 50.4M, extended-hours 31.3M rows; 81.7M total hit the
floor), and the served bars survived only in data/scratch/alpaca-pilot/ parquets, which must
not be cleaned until the archive backfill lands. That finding produced the capture law (todo
528) and the raw-table redesign. Superseded in part 2026-10-27 by D-191-Q / D-191-P.

Full text in git history at docs/plans/2026-10-09-alpaca-5m-admission-build.md as of 708f3fe09.
