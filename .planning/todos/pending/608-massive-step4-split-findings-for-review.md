---
status: pending
priority: P1
filed: 2026-11-11
source: todo 600 admission step 4 (split reconciliation and level-seam detector, commit fc3e4525b); lead indicagent-32 rulings 2026-11-11: list these, do not act
---

# Massive step 4 split findings held for review

## What

The step 4 audit (`scripts/ops/bars/ops_massive_split_audit.py`, outputs under
`data/massive_split_audit/2026-11-10/`, git-ignored, rebuilt by one 60 s run) proposed 497
`massive_reference` rows (applied under the lead's ruling) and held five classes for review. Each
item below names its evidence file. Nothing here is acted on until ruled.

1. **Writer-guard collisions (5)**, `review_rows.csv` status `writer_guard`: a Massive split the
   tape confirms sits within the corporate_action writer's 7-day window of a todo 592 operator row
   that corrects one incumbent route. Since d2-v6 an operator row is never a market split
   (`corporate_actions.is_market_split`), so selection and the daily rule do not rescale Massive by
   it, and the market's split needs its own row:
   ELS 2019-10-15 x2, IJR 2017-01-18 x2, OKE 2012-06-01 x2, UHAL 2022-11-09 x10, WST 2004-09-29 x2.
   WST and OKE are pre-2016, where Massive becomes primary: **their Massive bars would carry an
   unadjusted step until these rows land, so they are a precondition of the step 5 raw load for
   those two names** (ELS, IJR, UHAL are Alpaca-era, Massive unserved by policy). Recommended fix:
   the writer's existing-row guard skips rows that are not market splits when it decides a
   `massive_reference` row (same table of meanings), then `--apply-massive` lands the five.
2. **Canonical-flat seam candidates (130)**, `seams_active.csv` rows with `seam_class`
   unexplained and `incumbent` `incumbent_flat`: Massive's unadjusted tape steps by a recognised
   ratio where adjusted canonical stays flat, and no record holds a split. Real splits (FTI
   2011-04-01 2:1, ALK 2014-07-10 2:1, the SPDR sector ETFs XHS/XSW/XHE/XTN 2015-09-11 2:1) are
   mixed with spin-offs the incumbent adjusts for (HPQ 2015-11-02, ABT 2013-01-02, BAX
   2015-07-01, MO 2008-03-31). Massive's dividends capture has no spin-off type, so a filing
   witness separates them; a real split becomes a row, a spin-off stays a price move under the
   price-only convention.
3. **Off-level canonical spans (129 names, 257 runs)**, `level_census.csv`: canonical 1d more
   than 0.1 log off Massive (adjusted by the recorded splits) for at least 10 sessions. Mostly
   IBKR's non-split adjustments (ABT 0.48 AbbVie, BAX 0.54 Baxalta, A 1.40 Keysight: the 8a
   non-split class) and Massive-missing splits (ALK exactly 0.5 until 2014-07-09). The load checks
   (design 8a) pre-classify them; Massive replaces the pre-2016 incumbent at admission.
4. **Identity-suspect steps on active names (40 on 37 names)**, `seams_active.csv` `seam_class`
   identity_suspect: string reuse inside an instrument's head span (LIN 2018, TFC 2019, MTCH 2015,
   DOC/PEAK 2019, TPR 2017, GL 2019, RTX 2020 and others; gaps of hundreds of sessions before a
   level step). Input for the ticker-entity map (step 3b), never a missing split.
5. **Canonical defects the applied rows make visible (3)**: before the apply, D7
   `split_continuity` was dry-run per name with and without the proposed rows (read-only). Three
   names turn red, each a real canonical scale error the market's split exposes, not a row
   error: CENT 2007-02-05 (canonical steps +1.05 at 2007-02-06, its earlier span at 1/3 of
   correct: adjusted twice), RJF 2015-12-31 (IBKR before 2016 at 2/3 of correct, +0.38 at the
   2016 seam), SNEX 2023-11-24 (Alpaca before 2023-11-28 adjusted twice, +0.37). The two
   pre-2016 spans are replaced by Massive at admission; SNEX is an Alpaca capture-epoch seam
   (design 8a) for the third-witness ledger.
6. **SNX 2020-12-01 x2** (`review_rows.csv` status `excluded_spin_off`): the vendor serves the
   Concentrix spin-off as a 2:1 split; the operator spin-off list names it, so it is never a row
   (the proposal gate and the writer both read the list). One of the 497 approved rows.
7. **Smaller items:** ITA, MTUM, QUAL 2026-11-04 date_offset (ours one session before Massive's
   execution; Alpaca era, Massive unserved); CCBG 2003-06-13 ratio_disagree (Massive x2.25, ours
   x1.25, before the tape); the 4 vendor-internal conflicts and 52 collapsed duplicate ids
   (`attribution_excluded.csv`); a latent pairing edge (a correction row losing its pair to a
   second split row of the same event would be applied twice in the audit's witness; not live).

## Decided, recorded here

- Detector thresholds stay script constants in `ops_massive_split_audit.py` (junction cut 0.2,
  ten sessions a side, explain window five sessions, halt gap 5, identity gap 60, thin volume
  1,000, level tolerance 0.1), the todo 592 sweep's precedent; `summary.json` records them with
  the APR values each run (lead ruling 2026-11-11).
- OKE: incumbent defective over 2003-2015 (0.72x to 1.95x off Massive); Massive replaces it by the
  normal load, no rows (lead ruling 2026-11-11).
- GSAT 2021-02-08 x0.609687 (`calendar_audit`, batch b1): voided under the lead's ruling; Massive
  shows a real squeeze (1.23 -> 2.08 on 10x volume, 2021-02-08 to 02-09), not a split.

## Before step 7 (Massive canonical 1d)

- `canonical_bar_lineage` (migration 568) divides raw by calendar_audit factors only; a Massive
  canonical 1d row (`sip_flat_adj`) needs the market-split product of d2-v6 in the view, or it
  reads lineage_missing.
- `(massive, sip_flat_agg)` at 1d is not a d2-v6 input series; add it only if the day-against-
  minute check (design 8a) rules the RTH aggregate the 1d kind.
- `ops_split_calendar_audit._RAW_SERIES_OF` has no Massive entry, so its `--sweep` reports a
  Massive-served break as not rescalable; add `(massive, sip_flat_adj) -> (massive, sip_flat)`
  with the d2-v6 market-split rescale before the post-admission sweep rerun (todo 592 ruling).

## Before the next reference recapture (future splits)

d2-v6 never stales an incumbent on a `massive_reference` row, which is right for every applied
row (each split executed before the 2026-11-10 capture, and the incumbents serve it adjusted).
A row landing BEFORE the incumbent restates (a recapture that lists a split executed days
earlier) would interact with `ops_split_detect`'s same-factor dedup (`_EXISTING_SQL`): the
nightly overlap would find the reference row, record nothing, and the incumbent's pre-split
fetches would stay current. Recommended fix before any recapture applies: the overlap detector
supersedes a same-event `massive_reference` row with its `nightly_overlap` row (one row, the
stale meaning, Massive still divided once), or the reference writer refuses rows executed after
the incumbents' last fetch. Not live: no reference capture is scheduled.
