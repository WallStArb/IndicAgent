# Data layer integrity design (archived)

Date: 2026-10-06, amended 2026-10-07, 2026-10-09, 2026-10-10 and 2026-10-12. Archived 2026-11-14.
Outcome: implemented by plans 185-31, 185-33, 185-35 to 185-45, 185-52 and 189-07 to 189-11, then
folded into phase 191's unified raw table (`docs/plans/2026-10-12-unified-raw-bar-table-design.md`).
Its 1d and 5m source choices were superseded by D-191-Q and D-191-P, Tradier was removed
(migration 589) and IBKR was removed 2026-11-13. The live rules it set (one writer per table,
`bar_source_policy` as the only home of a source choice, the write contract, lineage derived on
read, the D7 verdicts as the gate) are stated in `docs/foundation/canonical-truth-registry.md`.

Ideas kept:
- Every defect of its era had one shape: a second path or a side table that could disagree with
  the bars and did. The fix is fewer paths, each a pure function of stored raw answers, with every
  side record derived on read or verified against the data it describes.
- Gates read computed integrity verdicts, never a bookkeeping flag (`backfill_status.fetch_complete`
  held 517 names that had real data).
- Vendors disagree on adjustment basis for long runs (RJF before its 2021 split, REX in 2025,
  spin-off ratios on IBM, BDX, LEN); each vendor is wrong on different names, so a cross-vendor
  splice inside a basis run creates two false returns. Report basis runs; never splice prices
  across one; never rescale volume across a vendor seam.
- Zero-tolerance checks are definitions, not APR values.

Full text: git history, `docs/plans/2026-10-06-data-layer-integrity-design.md` as of `a1f11a86c`.
