---
phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf
plan: 07
subsystem: database
tags: [postgresql, instrument-tag-registry, tag-vocabulary, etf-gap-fill, factor-etfs]

# Dependency graph
requires: [174-02, 174-03]
provides:
  - "eq_momentum/eq_quality/eq_low_vol/vol_proxy exposure-category tag_vocabulary rows"
  - "MTUM/QUAL/USMV retagged with factor-specific tags alongside their retained eq_factor row"
  - "docs/research/phase174-etf-gap-fill-ticker-selection.md -- EMLC (EM-FX) and VIXY (vol-proxy) ticker decisions with full contract_details/instrument_metadata field values for Plan 10"
affects: [174-10]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Tag-taxonomy split (specific tag added alongside a retained coarse parent tag, never replacing it) for a widely-shared human-sourced exposure label"

key-files:
  created:
    - production/migrations/338_factor_and_vol_exposure_tag_taxonomy.sql
    - docs/research/phase174-etf-gap-fill-ticker-selection.md
  modified: []

key-decisions:
  - "Momentum/quality/low-vol factor exposure closed via tag-taxonomy retag, not new instrument sourcing -- CONTEXT.md D-06's 'zero representation' premise was false, live-reverified (MTUM/QUAL/USMV already is_active=true with 2.15-2.42M OHLCV rows each, matching 174-RESEARCH.md's numbers exactly)"
  - "USMV tagged eq_low_vol despite D-06 dropping new low-vol sourcing from scope -- USMV is already in the universe under the coarse eq_factor tag; leaving it untagged while splitting MTUM/QUAL would silently redefine eq_factor to mean 'low-vol plus market-neutral plus high-beta'"
  - "EMLC selected over CEW for EM-FX exposure -- CEW trades at roughly 1/400th of EMLC's volume on every window measured (20/65/50-day averages), live-verified via Nasdaq's quote-summary API 2026-09-15; EMLC's EM sovereign credit/duration contamination is real but flagged explicitly in the tag evidence for later residualization"
  - "VIXY selected over VXX for vol-proxy exposure despite VXX's deeper live-measured volume (roughly 2-3x VIXY's) -- VXX is an ETN whose issuer halted new-share creation in March 2022, a structural discontinuity inside the corpus measurement window that a real ETF (VIXY) does not carry"

patterns-established:
  - "Specific-tag-alongside-coarse-tag pattern for splitting a shared human-sourced exposure label without deleting or redefining the parent -- reusable whenever a coarse tag turns out to span structurally distinct strategies"

requirements-completed: [D-05, D-06]

# Metrics
duration: ~50min
completed: 2026-09-15
---

# Phase 174 Plan 07: ETF Exposure Gap-Fill -- Tag Taxonomy + EM-FX/Vol Ticker Decision Summary

**Migration 338 splits the coarse `eq_factor` tag into `eq_momentum`/`eq_quality`/`eq_low_vol` and adds a `vol_proxy` exposure category, correcting CONTEXT.md D-06's false "zero factor-ETF representation" premise with live-reverified evidence; a companion decision document names EMLC and VIXY as the two tickers Plan 10 onboards for the genuinely-empty EM-FX and volatility exposures.**

## Performance

- **Duration:** ~50 min
- **Completed:** 2026-09-15
- **Tasks:** 2/2 completed
- **Files modified:** 2 created (1 migration, 1 research doc)

## Accomplishments

- Re-verified CONTEXT.md D-06's premise live against the database before writing any SQL: MTUM/QUAL/USMV are `is_active=true` since 2026-05-15 with 2,194,069 / 2,156,803 / 2,417,375 `market_data_ohlcv` rows respectively -- figures matched 174-RESEARCH.md's own live-verified numbers exactly, no discrepancy to record.
- Shipped migration 338: 4 new `tag_vocabulary` rows (`eq_momentum`, `eq_quality`, `eq_low_vol`, `vol_proxy`, all category `exposure`), and retagged MTUM/QUAL/USMV with their specific factor tag while leaving all 5 existing `eq_factor` rows (including BTAL/SPHB) completely untouched. Applied live, re-run confirmed idempotent (zero new inserts on re-run, all counts unchanged).
- Deliberately did NOT insert `fx_em` into `tag_vocabulary` -- confirmed live it already exists (0 member symbols today); the migration header states this explicitly so a future reader doesn't mistake the absence for an oversight.
- Ran `tests/unit/test_tag_calibrator.py` (11 passed) and the full `tests/unit/` suite (0 failures, 2 pre-existing unrelated skips) after the migration landed.
- Researched and recorded the two real ETF gaps (EM-FX, vol-proxy) in `docs/research/phase174-etf-gap-fill-ticker-selection.md`, live-verifying liquidity/expense-ratio/AUM figures via Nasdaq's quote-summary API and, for VIXY, cross-checking directly against ProShares' own fund page (authoritative where it disagreed with the aggregator). Selected EMLC over CEW and VIXY over VXX, with the rejected candidates' figures recorded alongside the picks for auditability.
- Recorded the full `contract_details` (ten-key) and `instrument_metadata` (four-key) field values for both EMLC and VIXY so Plan 10 does no re-research.

## Task Commits

Each task was committed atomically:

1. **Task 1: Migration 338 -- factor and vol exposure vocabulary, retag ETFs already owned** - `74d02bd1d` (feat)
2. **Task 2: Record the EM-FX and vol-proxy ticker decision with live evidence** - `0e35b5111` (docs)

**Plan metadata:** this SUMMARY's own commit (docs: complete plan) -- committed separately per worktree convention, not part of the task commit sequence above.

## Files Created/Modified

- `production/migrations/338_factor_and_vol_exposure_tag_taxonomy.sql` - 4 new `exposure`-category `tag_vocabulary` rows, 3 new `instrument_tags` rows (MTUM/QUAL/USMV), both blocks `ON CONFLICT ... DO NOTHING`, applied live and verified idempotent.
- `docs/research/phase174-etf-gap-fill-ticker-selection.md` - EM-FX (EMLC vs. CEW) and vol-proxy (VIXY vs. VXX) screening tables with live-verified figures, both decisions stated, full field values for Plan 10, restated Correction to CONTEXT.md D-06.

## Verification Results

- `SELECT count(*) FROM tag_vocabulary WHERE tag IN ('eq_momentum','eq_quality','eq_low_vol','vol_proxy') AND category='exposure'` -> 4
- `SELECT symbol || '|' || tag FROM instrument_tags WHERE tag IN ('eq_momentum','eq_quality','eq_low_vol') ORDER BY symbol` -> `MTUM|eq_momentum`, `QUAL|eq_quality`, `USMV|eq_low_vol`
- `SELECT count(*) FROM instrument_tags WHERE tag='eq_factor'` -> 5 (unchanged)
- `SELECT count(*) FROM instrument_tags WHERE tag IN ('eq_momentum','eq_quality','eq_low_vol') AND source <> 'human'` -> 0
- `grep -c "INSERT INTO instruments" production/migrations/338_factor_and_vol_exposure_tag_taxonomy.sql` -> 0 (no instrument sourcing in this plan)
- Migration re-run: `INSERT 0 0` / `INSERT 0 0`, all counts unchanged -- confirmed idempotent
- `.venv/bin/pytest tests/unit/test_tag_calibrator.py -q` -> 11 passed
- `.venv/bin/pytest tests/unit/ -q` -> full suite green (0 failures, 2 pre-existing unrelated skips)
- `SELECT tag, count(*) FROM instrument_tags WHERE tag LIKE 'eq\_%' GROUP BY tag ORDER BY tag` -> `eq_low_vol|1`, `eq_momentum|1`, `eq_quality|1`, `eq_factor|5` alongside the pre-existing `eq_broad`/`eq_growth`/`eq_income`/`eq_sector`/`eq_small_cap`/`eq_sub_sector`/`eq_value` rows, unchanged
- Decision-document acceptance criteria: names exactly one EM-FX ticker (EMLC) and one vol-proxy ticker (VIXY) as decisions; all four candidates (EMLC, CEW, VIXY, VXX) present with screened figures; complete `contract_details`/`instrument_metadata` value sets recorded for both picks; `## Correction to CONTEXT.md D-06` section present citing live MTUM/QUAL/USMV evidence; opens with an `Author:` line; `grep -riE "momentum ETF|quality ETF"` returns no line proposing a new momentum/quality ticker; cross-referenced by 174-10-PLAN.md and 174-VALIDATION.md (pre-existing references, confirmed present)

## Decisions Made

- **Momentum/quality/low-vol closed by retag, not sourcing.** The single most consequential decision this plan made: confirming (not just trusting 174-RESEARCH.md's prior finding, but re-running the live queries independently) that MTUM/QUAL/USMV already satisfy D-06's intent. This avoided spending any of Phase 174's newly-freed compute headroom on redundant instruments.
- **USMV gets `eq_low_vol` even though D-06 dropped adding a NEW low-vol ETF from scope.** D-06's scope cut was about not sourcing a new ticker, not about leaving an already-owned instrument under a taxonomically worse coarse label. Zero sourcing/backfill cost either way.
- **EMLC over CEW.** CEW's ~5,000 shares/day average volume (vs. EMLC's ~2M) makes it functionally too thin for reliable microstructure features, even though it would have offered a purer currency-only read. The credit/duration contamination EMLC carries instead is recorded explicitly in the field values Plan 10 will use, so the tradeoff is visible in the data model, not silently absorbed.
- **VIXY over VXX**, despite VXX's measurably deeper live volume (confirmed live, not just trusted from research). VXX's March 2022 issuer-halted share creation is a structural discontinuity landing inside this corpus's measurement window -- deeper options liquidity on the underlying doesn't compensate for a contaminated price history in a measurement corpus.
- **Live re-verification methodology:** used Nasdaq's public quote-summary API for AUM/expense-ratio/volume figures on all four candidates, and ProShares' own fund page directly for VIXY (which disagreed with the aggregator on net assets by a meaningful margin -- $215.7M official vs. $161.6M aggregator-reported; the issuer's own figure was used). Several issuer sites (WisdomTree, iPath/Barclays, etf.com, stockanalysis.com) returned HTTP 403/Cloudflare-blocked responses to automated fetches this session; inception dates for CEW and VXX are cited from the well-established historical record rather than freshly re-scraped, consistent with 174-RESEARCH.md's own confidence framing that these structural facts are stable and low-churn.

## Deviations from Plan

None -- plan executed exactly as written. One environment fix, matching the pattern documented in 174-02-SUMMARY.md and 174-03-SUMMARY.md (not a deviation from this plan's scope): the worktree spawned without its own `.venv`, symlinked to the main checkout's `.venv` (`ln -s /home/bg/dev/indicagent/.venv .venv`) so the pre-commit hook's ruff/black checks and `pytest` could run. `.venv` is gitignored, no untracked-file residue.

One methodology note, not a deviation: the plan's Task 2 action instructs re-verifying financial specifics "live." This session's live re-verification used the Nasdaq quote-summary API and ProShares' official fund page (both genuinely fetched and parsed this session, 2026-09-15) rather than a general web search, since several candidate sources (WisdomTree, iPath/Barclays official pages, etf.com, stockanalysis.com) actively blocked automated fetches (HTTP 403, Cloudflare bot-mitigation challenge). This is documented transparently in the decision document itself rather than silently substituting stale figures.

## Issues Encountered

None beyond the `.venv` symlink and the issuer-site blocking noted above, both handled and documented.

## User Setup Required

None -- no external service configuration required.

## Next Phase Readiness

- Migration 338 is live, committed, and idempotent. `eq_momentum`/`eq_quality`/`eq_low_vol`/`vol_proxy` are registered vocabulary ready for any future IC-stratification consumer to key off.
- `docs/research/phase174-etf-gap-fill-ticker-selection.md` gives Plan 10 the complete `contract_details`/`instrument_metadata`/exposure-tag field values for EMLC and VIXY -- Plan 10 can call `onboard_instrument()` (from Plan 03) directly without re-researching ticker specifics.
- No blockers. Zero new instrument rows were written by this plan, matching the plan's explicit success criterion.

---
*Phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf*
*Completed: 2026-09-15*

## Self-Check: PASSED

- FOUND: production/migrations/338_factor_and_vol_exposure_tag_taxonomy.sql
- FOUND: docs/research/phase174-etf-gap-fill-ticker-selection.md
- FOUND: commit 74d02bd1d
- FOUND: commit 0e35b5111
