# Corpus first run: disclosures the report must carry

Status 2026-11-24: draft for the first 1d `feature_complete` report (pin `09708ae249f2`, scope 1d, run walked `--through feature_complete`, ledger 2026-11-24f). Every item below is a sentence to publish with the report, its number and where the number comes from. Nothing here is computed in this file; a number marked "to fill" comes from `corpus_run.measured` after the pilot. Gates are by materiality (owner 2026-11-20): these are disclosed, not chased. A reader of any feature or IC result from this corpus reads this list first.

## 1. Universe and survivorship

| # | Sentence to publish | Number | Source |
|---|---|---|---|
| 1.1 | The universe is the stage 2 point-in-time membership, which includes dead names, so the panel is survivorship-reduced, not survivorship-free. The share of early-era member-days that rests on a later list is not measured. | 1,042,561 membership rows, 12,857 securities, 278 month-ends; closed-list hash `af96da67` | ledger 2026-11-21 (stage 2 universe amendments); `.planning/STATE.md` Position |
| 1.2 | Years 2003 to 2006 and 2009 stay under the 2,950 member sizing and are disclosed, not chased. | highest month-end member count by year: 2,004 (2003), 2,302 (2004), 2,547 (2005), 2,776 (2006), 2,874 (2009); all other years above 3,000 | `docs/plans/2026-11-13-stage2-universe-preregistration.md:118`; ledger 2026-11-21 |
| 1.3 | The security type of 823 securities had conflicting list typings; they are counted and not resolved. | 823 of 29,325 securities | preregistration line 118; ledger 2026-11-21 "What it costs" |
| 1.4 | The eight names excluded in 2026-11-14 for `identity_unresolved` are computed and disclosed as the former identity_unresolved set; their 5m exclusion stays. | BWXT, EXP, HWM, PIPR, RGA, SPXC, UHAL, USAU | ledger 2026-11-24f point 2 |
| 1.5 | SCCO and CTVA are held (unclassified rescale), have no canonical 1d and no `universe_membership` row, so no compute reads them. | 0 membership rows each (2026-11-24); 1,875 (CTVA) and 5,299 (SCCO) Massive 1d slots held | `.planning/todos/completed/608-*.md` closure 2026-11-24 |
| 1.6 | Names whose ticker ended carry a recorded `listing_end` and are judged to it. BKH ends 2026-11-13 (its merger with NorthWestern closed 2026-11-16 and the survivor trades under a new ticker; reason `merged`); the new ticker is a separate instrument (reused-ticker class), not BKH's continuation. BKH and NWE were both 5 sessions behind in the 2026-11-21 dry run. | BKH last bar 2026-11-13 at both vendors; migration 616 | ledger 2026-11-24h; ledger 2026-11-21e (BKH, NWE) |
| 1.7 | Inactive members are verified to the span the compute can read, not to the last session; a tail cut before the true end is not chased. | of 11,348 inactive members, 2,767 have the last bar more than 10 days before the judged end, 211 more than 31 days (none beyond 92) | ledger 2026-11-21e |
| 1.8 | Instruments with no listing end that have stopped printing are caught only by `freshness_1d` (todo 673 adds the named list). | todo 673 | `.planning/todos/pending/673-*.md` |

## 2. Bars and prices

| # | Sentence to publish | Number | Source |
|---|---|---|---|
| 2.1 | Canonical 1d is Massive from 2003-09-10 to the archive seam 2026-11-16, then Alpaca SIP, no fallback and no IBKR (rule d2-v6). A series therefore changes vendor at the seam; post-seam splits are caught by `split_feed_auditor` (built, timer not installed, owner step). | seam 2026-11-16; todo 649 | CLAUDE.md Core Runtime; `.planning/STATE.md` Lane B |
| 2.2 | Closes for 2005 to 2007 are the official close and agree with Yahoo; there is no 2003 to 2007 seam. A residual remains in 2007: 7 of 63 sampled names agree only at 84 to 89 percent. | 99.7 percent agreement in 2005 and 2006, 97.2 percent in 2007; the residual is at most about 0.4 percent of scope C name-years; n = 63 | todo 610 closure 2026-11-24 |
| 2.3 | Holes: 143 names have no Massive bars before their first day. Canonical has no close there, so the panel reads NaN (`no_fill`). | 359,919 hole days in all (corrected from 451,735); 341,638 before the first Massive day; 7,784 days touch scope C, 0.74 percent of its observations (6,876 of them in the 143 names) | todo 632 closure 2026-11-23 |
| 2.4 | Split-shaped findings left unrepaired: six D4 reds and HON; the 2026-11-21e unexplained seams (ACIW, AGL, RCAT, SNEX, TROX, WSM) are one-bar real moves that age out. | MHH 2013, DRIP 2020, VIP 2004, ACGN 2018, CETV 2003, ETS 2005, HON 2026-06-26; at most about 1,000 cells of about 9 million finite cells, under 0.02 percent | ledger 2026-11-21e; ledger 2026-11-23d point 5 |
| 2.5 | Eleven inactive names carry vendor-side holes inside their history (session coverage 0.43 to 0.997) and are listed, not repaired. | ACQR, CEP, DKA, ENGN, GGOV, KWT, PACQ~1726293, PRE, RRF, STNL, WTRE | ledger 2026-11-21e |
| 2.6 | Twenty-four pinned holds pass `d2_landed` by named exception. | 24 holds | ledger 2026-11-23d point 5 |
| 2.7 | Extended-hours bars are raw only and never reach canonical. 5m is outside this report (1d only). | scope 1d | `.planning/STATE.md` rulings in force; todo 471 |
| 2.8 | Features and targets read the tradeable view (volume above 0) only; carry-forward and synthetic placeholders never reach compute. | n/a | CLAUDE.md Core Runtime |

## 3. Dividends and targets

| # | Sentence to publish | Number | Source |
|---|---|---|---|
| 3.1 | Total-return coverage is Yahoo first, then Massive; where a name has no covered session, total-return panels read NaN, never zero. Coverage is 59.7 percent of member cells (23.1 percent with Yahoo alone), 6,700 of 12,245 names. | 59.7 percent; 18,930,885 covered cells | ledger 2026-11-21d; `.planning/STATE.md` Dividends |
| 3.2 | 5,292 member names have no covered day, all dead; total-return families are scored mostly on live names, and dead non-payers are under-represented. | 5,192 no event at all; 96 events and coverage rows but no covered member day (under review); 4 coverage row and gap rows only | ledger 2026-11-21d correction |
| 3.3 | Massive carries cash only: a spin-off or return of capital stays in prices as a loss. | upper estimate of the missed class about 1.9 per 100,000 sessions on live names; 98 percent of overnight drops above 10 percent fall on no ex-date | ledger 2026-11-21d |
| 3.4 | The first IC run uses price-only targets (`panel.forward_returns`, `dividends=False`); a target window straddles an ex-date on about 1 percent times h of rows. Yield-linked columns (`dividend_yield`, `size_proxy` and the linked ones) are read on price-only targets. The run is counted under E21 (the sentence "not a counted look" was withdrawn by 2026-11-24f). | 194,375 ex-date events on 5,838 names over 978,350 member-months (about 0.2 per member-month); yield median 0.49 percent, p90 1.56, p99 4.5, 1,507 above 5 percent, 327 above 10 percent | ledger 2026-11-24e and 2026-11-24f |
| 3.5 | For the stage 2 member universe the dividend coverage figures are those of 2026-11-21d: 59.7 percent of member cells covered (40.3 percent uncovered), 6,162 of 11,684 member names covered, and all 5,292 uncovered member names dead. Quote these in the survivorship disclosure. The 0.819 uncovered share of the family 9 primary panel (core 0.496) is a family-specific panel, not the member universe, and belongs only under the family 9 disclosure (3.7). | 59.7 percent; 6,162 of 11,684; 5,292 | ledger 2026-11-21d; correction ledger 2026-11-24j |
| 3.6 | The families that read total return carry a finite share per panel (family 9's F1 needs 240 of 252 finite closes and is thinner); segments split at a suspect event start a new column and are NaN for 240 sessions after. | `reversal_21` averages 2,037 finite names per row on the primary panel and 866 on core | ledger 2026-11-23d points 1 and 2 |
| 3.7 | Family 9 only: its member F1 is finite on about 17.1 percent of the primary panel's names a row (2,005 of 11,757) and 39.8 percent of core (855 of 2,150), because the total-return close is NaN outside dividend coverage; the family's uncovered share is 0.819 on the primary panel and 0.496 on core. The result speaks for the dividend-covered names only. | 0.819 primary, 0.496 core; 2,005 of 11,757 and 855 of 2,150 | ledger 2026-11-23i disclosure 2 |

## 4. Features and regimes

| # | Sentence to publish | Number | Source |
|---|---|---|---|
| 4.1 | The rebuild stores rows only from bar 252; a declared warmup is judged in stored-row units. `hma_slope_z` (declared 7,560 bars) exceeds every judged history and stays "expected not judged". | first stored row bar 252; 7,308 stored rows for `hma_slope_z` | ledger 2026-11-24c |
| 4.2 | The 13 HMM numeric columns (7 trend, 6 volatility) are NaN wherever the walk-forward writes no segment; they are judged only on written rows. Per timeframe, the share of post-warmup rows with a written segment is disclosed here. | to fill from `corpus_run.measured.pilot_hmm_written_share` after the pilot. Prior measurement at K=3 on 437 names: 21.5 percent of 1d segments refused, 1.7 percent of names with no output, median written share 86.8 percent | ledger 2026-11-24d; todo 583 table (437 names) |
| 4.3 | A name-day without a written segment is NaN, never a default state. Degenerate-occupation refusal is a causal but non-random selection on each name's own path; it is stated, not corrected. | n/a | `docs/plans/2026-11-24-family-order-after-1d-corpus.md` (Regime columns) |
| 4.4 | A regime column from a pre-rebuild batch is refused; `market_regimes` ends 2026-08-11 in every group. | `refuse_regime_columns`; 2026-08-11 | the same note; todo 466 |
| 4.5 | The E21 clean-data lift covers price-derived 1d families only; every feature-vector family needs its own lift. | n/a | family-order note ("What the corpus adds") |
| 4.6 | Path-dependent columns are refused by the research reader; kernels may not recompute a stored column at its stored window. | n/a | family-order note |

## 5. Selection and counting

| # | Sentence to publish | Number | Source |
|---|---|---|---|
| 5.1 | Every measured IC cell is a counted attempt (E21), recorded as two attempts per cell (long and mirrored short) once the sweep-cell writer exists. This report runs only through `feature_complete`; no IC cell is measured or recorded by it. | about 1,108 cells x 2 per full 1d level 1 sweep | ledger 2026-11-24f, 2026-11-24i; todos 670, 671 |
| 5.2 | StepM universe on the vintage: 20 charged rows, 24 after family 10; 16 series. A sweep raises the step-1 critical t from about 2.7 to about 3.1 to 4.1 depending on cell correlation, and may drop `reversal_21` from the selection set. | critical t 3.92 to 4.12 at cell correlation 0, 3.08 to 3.34 at 0.7 | todos 670 and 671 (commit 0265b878b); ledger 2026-11-24i |
| 5.3 | The adjusted p-values of the selected `reversal_21` runs (0.0090 and 0.0025) were computed on 10 series and may rise when read on the larger universe. | 0.0090 and 0.0025 on 10 series; 0.0135 and 0.0045 on 12 | ledger 2026-11-23d point 4 |
| 5.4 | Target windows end before `alpha.validation.oos_start` (2025-12-24); the forward span is not read. | 2025-12-24 | ledger E21 rule 4; design section 11 |
| 5.5 | Sweep winners that prompt a family carry `informed_by`; admission gates are outcome free and run on the discovery span only. | n/a | ledger E21 rules 5 and admission note |

## 6. Operations

| # | Sentence to publish | Number | Source |
|---|---|---|---|
| 6.1 | The first run is walked at 4 workers under the DIMM watchdog after a host memory fault on 2026-11-23 (DIMMs 117 C, memory corruption, four family 10 runs lost as charged failed rows). Reads after the reboot were clean. | 460 chunks read clean; memtester 44 GB x 2 passed | ledger 2026-11-24b; `.planning/STATE.md` Queue |
| 6.2 | The Massive plan lapses about 2026-12-10 (owner call); after it every active-name split reaches `corporate_action` only through the Alpaca feed detector, whose timer is not yet installed. | about 3 splits a month on active names | todo 649; `docs/plans/2026-11-15-massive-plan-lapse-deadlines.md` |
| 6.3 | Pilot: the first run `a4f6ad40` failed the pilot gates G1 to G3 and G6 (todo 652, parked); the new run uses code key `09708ae249f2`, which no earlier run shares. | key `09708ae249f2` | `.planning/STATE.md` Position; ledger 2026-11-24c and 2026-11-24d |

## Maintenance

Update this file when the pilot reports (4.2), when an item changes. A disclosure is removed only with its evidence. Gates for edits: `tests/unit/test_doc_schema_numbers.py`, `tests/unit/test_no_dangling_references.py` by exit code, and `tools/check_glossary.py`.
