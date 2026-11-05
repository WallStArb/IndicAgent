---
status: pending
priority: P0
filed: 2026-11-04
source: entity-continuity and split audit (indicagent-ab, read-only, 2026-11-04); design by the desk lead (indicagent-16)
---

# Canonical 1d carries 404 unadjusted splits (283 names); recover them before the 584 pin

## What

The invariant "stored equity bars are split-adjusted, not dividend-adjusted"
(`services/dividend_event_writer.py:3`, the panel builds on it) is broken in canonical 1d. Against
Yahoo's split calendar (813 names, 2,837 splits, fetched read-only), canonical steps by the split
ratio on 404 split dates over 283 names: 396 in `ibkr/named` before 2016, 6 `alpaca` 2016+, 2
`ibkr/fallback`. 156 of the 404 sit below the jump threshold (3:2, 5:4), so a jump scan alone
finds 231; the list comes from the calendar. Each one reads as a fabricated one-day return of
about -41% to -67% to every 1d kernel and research spec that spans it. Of the split-shaped jumps,
325 carry a `bar_quality_flag`, 2 are quarantined, and the tradeable view filters on volume only,
so research sees all of them. `corporate_action_current` held one row.

Measured basis (share of Yahoo-dated splits that show as a price step): IBKR `smart_trades` 1d
before 2016 misses about half (379 adjusted / 428 unadjusted); IBKR 1d 2016+, `smart_adjusted`,
Alpaca `sip_rth` and IBKR 5m before 2016 are adjusted (the 5m "unadjusted" six are spin-offs or
stock dividends). The 534 intraday backfill does not carry this defect.

## Decision (lead, 2026-11-04; owner veto window on point 3)

1. **Facts.** Each CONFIRMED split is one `corporate_action` row: Yahoo's clean ratio p:q
   (p <= 50, |log f| > 0.09) on its date, the canonical step on that date within tolerance of
   log f, and Yahoo's split-adjusted close continuous across it. That is two independent checks,
   an external calendar plus our own measured step at the exact date and ratio. The IBKR
   `smart_adjusted` witness covers almost none of these dates and confirms nothing. New
   `inferred_by` value `calendar_audit` (migration); `detail` carries the Yahoo ratio and date, the
   measured step, and the (vendor, kind) span measured unadjusted. CONFLICT (40) and the
   GYRE/VISN holds get no row: lead review list.
2. **Never a split row:** Yahoo encodes spin-offs as fractional splits (IBM 2021 Kyndryl, XPO
   2021 GXO, A 2014, DOV 2014, ZBH, J, BDX). They are a total-return question for the dividend
   layer, filed separately; the clean-ratio filter must exclude them, with a test.
3. **Application (reverses plan 185-49's "never served" for this case only).** The daily rule
   rescales a served observation from (vendor, kind) dated before a split whose row records that
   (vendor, kind) unadjusted there: prices divided by the cumulative factor, volume multiplied by
   it (a share count on the new scale; this is not the vendor-volume-basis splice that stays
   banned). It is a pure function of raw, policy and `corporate_action_current`; raw is never
   edited. 185-49 rejected a scale correction because a vendor's own current-scale answer
   existed (IBKR's restated bar). Before 2016 none exists: Tradier is deleted, and
   `smart_adjusted` is dividend-adjusted and sparse. The alternatives are worse: serving the
   unadjusted bars keeps fabricated returns, and quarantining pre-split spans drops up to decades
   of history for 283 names.
4. **Lineage.** `canonical_bar_lineage` matches canonical to raw by equality; a rescaled bar
   matches `raw / factor`. The view gains the applied factor, and the lineage check stays exact.
5. **Loud check (D7, new `split_continuity`).** At every `corporate_action_current` date, the
   canonical log step must not sit within tolerance of plus or minus log f (still unadjusted)
   or of twice log f (double-adjusted, for example after a vendor restates its history and
   last-wins raw changes). Either fails D7 by name; the row is then superseded, never edited.
   Tolerance is APR.
6. **Bad bars.** The 31 jumps flat on Yahoo with no event, the RCAT 2010 pair and GEN 2002 are
   not splits: a review list for the existing quarantine path (`bar_quality_flag`), with
   evidence, approved by the lead. GEN 2002 also joins the entity list.

## Order

One atomic landing: the rows, the rule change and the re-derive land together, with no interim
state. Rows alone are NOT neutral (ab, 2026-11-04): `daily_rule._stale_for` marks every
pre-split observation stale when a split row is recorded after it was fetched, the pre-2016
default (IBKR primary, no fallback) then serves it flagged `pre_split_unrefetched`, the existing
APR quarantines it, and `--changed-only` re-derives on new `corporate_action` records, so the
05:20Z nightly would quarantine whole pre-split spans. An IBKR refetch re-serves the same
unadjusted bars. The rule therefore treats a `calendar_audit` split, over its recorded
unadjusted (vendor, kind) span, as rescale, never stale. The code, migration, audit CSV and D7
check may land first only if nothing writes a `calendar_audit` row (`--apply` stays dry-run).
Then the atomic landing after the owner's veto window, re-derive the 283 names, D7 clean, then
the 584 pin. Gates per CLAUDE.md for every code landing; `ops_selection_gate`-equivalent
recompute and the lineage check on the re-derived names.

## Done when

404 confirmed rows (or the confirmed subset, with the rest on a named review list), the rule
applies them, `split_continuity` passes on all 1,529 names, the lineage view stays exact, and the
dividend layer's amounts are confirmed on the same split-adjusted basis for the 283 names.

Evidence files (ab's scratchpad, 2026-11-04): `yahoo_splits.csv`, `canonical_vs_yahoo_splits.csv`
(the candidate list), `split_candidates.csv`, `split_basis.csv`, `jump_spotcheck.csv`. Copy the
candidate list into the landing so it outlives the scratchpad.

## Status 2026-11-04 (session ab; paused by the owner, the 14:00Z go is cancelled)

Safe set landed: d891857d2 (migration 567, `scripts/ops/bars/ops_split_calendar_audit.py`, D7
`split_continuity`) and bf5abd1d8 (`config/corporate_actions/split_calendar_audit_2026_11_04.csv`:
380 confirmed on 268 names, 545 adjusted, 291 not a split ratio, 6 conflict, 1,611 unmeasured). No
`calendar_audit` row is written.

Atomic part, built and unpushed: local branch `wip/587-atomic-d2v5` = 5e3845df2 (the lead's tag
`wip/587-atomic` 78375ea30 plus the LEGACY pinning test). It holds rule d2-v5 (prices on the recorded
unadjusted span divided by the factor product in effective-date order, volume floor(v * scale + 0.5)),
the `_stale_for` off-by-one fix (zero impact on the one current row, ETHA), and migration 568 (the
lineage view divides raw by the same product). Dry run on AMZN, ADBE, AMGN, KLAC, GIS: 1,834 of 1,834
rescaled bars lineage-exact, all 7 splits continuous, no bar added or removed.

Review fixes 2026-11-04 (worktree `wt587land`, rebased on origin/main, unpushed; lead rulings):
the audit measures every raw series before each split on its own and the row lists them
(`detail.unadjusted_routes`); D7 also judges route seams against every partial product of the
splits. No automatic veto: a volume statistic and a new-listing witness were measured and dropped
(volume alone vetoed 27 confirmed splits and was right once; a co-listing within five sessions
occurs on 69% of sessions). Spin-offs are explicit exclusions in
`config/corporate_actions/spin_off_exclusions.csv`. Corrected CSV: 378 confirmed on 266 names (all
naming ibkr/smart_trades), 1 excluded_spin_off (SNX), 1 route_conflict (JMSB), other verdicts
unchanged. Dry run (AMZN ADBE AMGN KLAC GIS SNX SLB BH): 5,536 rescaled bars lineage-exact, D7
clean, 2016-01-04 step unchanged, no bar added or removed by the rows.

Review list (no row; each split-day bar quarantined by `unconfirmed_split` unless noted):
- SNX 2020-12-01: Concentrix spin-off (operator exclusion); a total-return question for the
  dividend layer (Decision point 2).
- EXPE 2011-12-21: a confirmed 1-for-2 reverse split on the TripAdvisor spin-off day; after the
  rescale canonical carries a real -48% price-only day (log -0.656). Confirmed and rescaled, not
  quarantined; the spin-off value is a total-return question for the dividend layer, next to SNX.
- JMSB 2017-09-06 route_conflict: canonical steps at an ibkr/fallback seam, the series is flat.
- 5 conflicts: AA 2016-11-01, ELS 2019-10-16, OKE 2001-06-12 and 2012-06-04, SNEX 2023-11-27.
- CMCSA 2017-02-21 is not an unconfirmed split: the conflict is the 2017-02-17 bad bar (the series
  is adjusted), listed in `config/corporate_actions/operator_bad_bars.csv` for the planned
  operator_bad_bar quarantine. A conflict whose step bracket holds a listed bad bar is left out
  of `unconfirmed_split`.
- Open item: `unconfirmed_split` quarantines only the first new-scale bar, so no one-day
  fabricated return reaches research, but multi-day returns and rolling kernels still span each
  of these breaks. Not solved by this landing.

D7 split_continuity (review 2026-11-05) judges a calendar_audit split's own date in excess of the
calendar's adjusted step (the day's real move), and in a rescaled name also every route seam and
every request boundary inside a rescaled span on or before the last split.

Resume on the lead's go:
1. Cherry-pick the worktree's 587 commits onto main; gates (pre-commit, unit suite); push.
2. `psql -f` migrations 568 and 571.
3. `ops_split_calendar_audit.py --apply <csv>` dry: the count must be 378 and the name list must
   equal the CSV's confirmed set (266 names; diff them). Then `--commit`.
4. `ops_split_calendar_audit.py --quarantine-unconfirmed <csv>` dry: 7 first bars (SNX, JMSB, the
   5 conflicts). Then `--commit`.
5. `bar_derivation --stage daily --symbols <the 266> --apply`; then
   `bar_derivation --stage daily --rewrite-digests --apply` over all names (no `--symbols`):
   RULE_VERSION is d2-v5, so every name's month digests move.
6. D7: record the verdict counts per check for all names before step 2 and after step 5.
   split_continuity clean on the 266, lineage_missing unchanged, and 0 digest_fresh failures
   after the rewrite.

After the landing: the six bad bars (FTNT 2014-01-10, CMCSA 2017-02-17, CDE 2008-11-18, CME
2008-07-14, OKE 2005-04-13, NEXN 2025-02-18) go to quarantine under a new `operator_bad_bar` rule
(design approved). Open questions: a non-Yahoo witness for FBIZ's 2015-08 split; the OKE, PATK, RSPF
scale breaks at the 2016-01-04 seam (with the other adjusted-on-date cases, todo 592); the CME 2007-07 to 2008-07 hole.
