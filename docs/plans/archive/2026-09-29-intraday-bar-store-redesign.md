# Intraday bar store redesign

Original: 2026-09-29 (proposed delta on phase 185; superseded by the unified raw bar table design).
Archived 2026-10-31: superseded design, kept for the measured defect and the principles.

Measured defect worth remembering: the old backfill padded the grid with flat placeholder
bars (81 to 83% of intraday rows), never replaced them, and gap detection counted them as
present; 155,022 15m slots held real 5m volume behind a placeholder.
Principles that carried into todo 462 and the raw-bar design: a stored bar is an assertion
about the market, so store only what the provider observed; absence is typed (not asked,
asked and empty, market closed, provider hole) and lives outside the bar table; redundancy is
error detection and first-write-wins is never the resolver; canonical bars are a pure
function of raw observations under a versioned rule.

Live successor: docs/plans/2026-10-12-unified-raw-bar-table-design.md.
Full text in git history at docs/plans/2026-09-29-intraday-bar-store-redesign.md as of 708f3fe09.
