# Raw capture enforcement: no drops, losers archived, completeness counted (todo 528)

Original: 2026-10-10 (landed as capture law 528).
Archived 2026-10-31: landed law, kept for the rationale.

Kept: every vendor-served bar is stored in ohlcv_raw under (vendor, kind), last-wins with a
revision log; nothing a vendor serves is dropped. First-writer-stays picks the canonical
author, never destroys the loser; multiple sources exist to disagree productively (basis
audits, depth extension past vendor floors, restatement). The old raw archive could not hold
a second vendor's row (its primary key had no source dimension), which is why the unified raw
table exists.

Live successor: docs/plans/2026-10-12-unified-raw-bar-table-design.md.
Full text in git history at docs/plans/2026-10-10-raw-capture-enforcement.md as of 708f3fe09.
