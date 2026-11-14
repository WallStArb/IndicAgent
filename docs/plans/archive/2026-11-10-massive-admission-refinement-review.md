# Massive admission design: data-layer refinement review (archived)

Date: 2026-11-10. Archived 2026-11-14.
Outcome: every finding (F1 to F14) and the pre-admission checklist were folded into
`docs/plans/2026-11-10-massive-admission-db-design.md` as dated amendment notes at `65e287edd`
(each note cites this review as d386cac3a); the captured-data corrections are in
`docs/reference/massive-plan-entitlements.md`.

Ideas kept:
- A byte-exact reproduction over spans whose raw did not change proves rebuild mechanics only;
  new code paths need their own witness (a seam-continuity check and a unit-level canary).
- Serve-time currency: a file archive is verified against its manifest, and the manifest against
  the vendor's current ETags, before the first load and again before the plan lapses.
- Future-dated corporate actions exist in vendor captures; a point-in-time join gates on the
  recorded announcement time, never on the effective date alone.
- An irreplaceable capture (the reference tree) belongs on the backup list with the bar files.

Full text: git history, `docs/plans/2026-11-10-massive-admission-refinement-review.md` as of `d386cac3a`.
