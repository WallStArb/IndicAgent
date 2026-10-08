# Stale-basis Tradier heads and the 185-38 rows contradicted by continuity (todo 508, plan 185-49)

**Author:** Claude (Sonnet 5.5), 2026-10-08, at Brandon's request
**Status:** applied 2026-10-08 (38 head rows written and re-derived; FTV, IP and STE rows closed
and, after plan 185-50 made a close visible to the revision waiver, re-derived; 14 names handed to
todo 512); paused once before any write and resumed the same day
**Informed by:** todo 508 (decision 2026-10-07 and owner decision 2026-10-08);
docs/research/vendor-adjustment-basis-study.md (185-37 rule and results); summaries of plans 185-37,
185-38, 185-46 and 185-47; docs/research/1d-primary-swap-evidence.md (IBKR 1d default from
D = 2026-10-07, pre-D Tradier history canonical under the dated rows)

## Question

The 185-37 study withheld 45 decided-IBKR runs because Tradier holds earlier dates on the same stale
basis, and listed five 185-38 whole-history IBKR rows (PATK, KDP, FTV, IP, STE) where continuity
says Tradier is the continuous side. The owner decided option 1 for all 45 heads (a row from the
name's first observation through the run's end, so the stale Tradier head becomes holes) and, for
the five, to close each row at its first day plus one and write IBKR rows only where IBKR is the
continuous side. This plan applies those decisions name by name, on data quality and continuity
only, and leaves undecided any name whose evidence is ambiguous.

## Measurements (read-only, 2026-10-08 16:25 to 17:10 UTC)

All on the live data after the swap. Tools and outputs are in `logs/185-49/` (git-ignored, as the
185-37 logs): `vendor_basis_study.{tsv,json}`, `head_probe.json`, `step_probe*.json`,
`preview_*.{tsv,json}`, and the probes in `logs/185-49/tools/`.

1. Study rerun (`scripts/research/vendor_basis_study.py`, read-only, 70 s). Same APR as 185-37
   (tolerance 10 bp, run minimum 5). 2,178 runs on 464 names; withheld_unmeasured_seam 45 runs on the
   same 45 names as 185-37; the 30 rows 185-37 wrote now read none_already_ibkr. D7-blocking runs 35,
   on the 28 todo names plus EWT, KDP, PATK and four new ones: ELE (undecided by the rule; D7 says
   IBKR; canonical Tradier; constant ratio 10.0), LION and W (undecided by the rule, both vendors out
   of range at the boundary; canonical IBKR under 185-38 rows) and NEXN (decided tradier; canonical
   IBKR under its 185-38 row).
2. Head basis (`tools/head_probe.py`, `tools/step_probe.py`). For 40 of the 45 heads, LEGACY_IMPORT
   holds 3 to 71 dates just before the run; their LEGACY/Tradier ratio equals the ratio at the run's
   start (ABT 0.4785 against 0.4785, EWJ 4.00 against 4.00, NSC 1.50 against 1.50), which measures
   the Tradier head on the run's stale basis directly. Without LEGACY dates (AAON, ADP, CPAY, IBB,
   OUT) Tradier's own move into the run's first session is compared with its 99th percentile over
   the surrounding 250 Tradier sessions: in range for AAON, ADP, CPAY and IBB; OUT moves log 9.70
   against 1.86 (its 115 Tradier dates before the 2014-03-28 listing are not the same series).
3. IBKR inside each run. At every common session where the IBKR/Tradier ratio steps by 5% or more,
   the vendor out of its ordinary range (same 99th percentile, 250 sessions). IBKR alone steps inside
   the run on BNY (6), CF (10), CPAY (8), DOV (1: 2014-03-03, IBKR -17.6% while Tradier moves 1.1%),
   MGM (34) and WELL (9); every other run has no IBKR-only step.
4. Bar-level preview (`tools/policy_preview.py`: the daily stage's own `derive_daily_v2` and
   `classify` on live inputs, live policy plus hypothetical rows, read-only). With the live policy it
   reproduces the stored bars exactly (0/0/0 on 10 names). With a head row per name: removals are
   only the head's Tradier dates plus Tradier-only dates inside the run (1 on most names, mostly
   2007-02-08 or 2007-07-02; 6 on the EW* ETFs, 2007-02-08 and 2007-12-06 to 12-12); changes are only
   the run sessions plus the LEGACY head dates (tradier to ibkr_named); nothing outside the row's
   range moves; new bars only where d2-v2 had refused an IBKR interior date (EWM, EWS, EWU, WELL one
   each). Counts per name: `logs/185-49/preview_heads.tsv`.
5. Closure preview (each 185-38 row closed at first day plus one, STE with its IBKR row):

| name | new | changed | removed | what the removal is |
|---|---|---|---|---|
| FTV | 0 | 2,579 | 14 | IBKR head 2016-06-14 to 07-01 (when-issued, before Tradier's first date), refused by the head gate at the 1.196 seam |
| IP | 0 | 2,618 | 2,414 | IBKR 2006-10-03 to 2016-05-06; Tradier starts 2016-05-09, the head gate refuses IBKR at the 1.056 seam |
| STE | 0 | 3,525 | 1,166 | IBKR 2006-10-03 to 2011-05-20; Tradier starts 2011-05-23 |
| KDP | 0 | 4,633 | 6 | IBKR head 2008-04-29 to 05-06 |
| PATK | 1,417 | 4,930 | 4 | IBKR interior refused |
| NEXN | 713 | 309 | 637 | IBKR interior refused |
| LION | 5,440 | 180 | 401 | IBKR interior refused (Tradier holds LION dates from 2000) |
| W | 2,184 | 1,249 | 1,291 | IBKR interior refused |

## Decision rule (dated 2026-10-08; fixed before any apply)

Head row (owner option 1). One 1d symbol row, primary ibkr, no fallback, valid_from the name's first
observation over the d2-v2 routes, valid_to the day after the run's last session, evidence the run,
the head-basis measurement and the preview counts, when all hold:
- H1: the run is decided ibkr by the 185-37 rule and was withheld only for the unmeasured head seam;
- H2: the head is on the run's stale basis: the median LEGACY/Tradier ratio over the head's LEGACY
  dates is within `threshold.bar_integrity.fallback_basis_tolerance_bp` of the median ratio over the
  run's first min(`fallback_basis_window_sessions`, n) sessions, or, with no LEGACY head date,
  Tradier's own move into the run is strictly below its 99th percentile (185-37 ordinary range);
- H3: no ratio step of 5% or more inside the run at which IBKR alone is out of its ordinary range;
- H4: the preview removes only head dates and Tradier-only dates inside the run, changes nothing
  outside the row's range, and no symbol row covers the range.

Closure (owner decision for the 185-38 rows). Close the open row at its first day plus one when the
185-37 rule decides every material run on the name tradier or ibkr, the continuous vendor shows no
step of its own inside the run, and the preview removes no bar other than head bars of the name.
An IBKR row is written only for a run decided ibkr whose IBKR series passes H3.

### Name sets

- Head row (38): AAON, ABT, ADP, BAX, BDX, BF.B, CAH, CHD, COP, CVBF, DRI, DUK, EBAY, EQT, EWI,
  EWJ, EWM, EWS, EWU, FIS, FLO, GL, IBB, IRM, KIE, KMB, MAS, MS, NI, NSC, PPL, ROST, SPG, TT, VTR,
  VZ, WMB, XRT. 23 of them block under D7 today.
- Closed 185-38 row (1): FTV. Known residual: the closed row keeps 2016-06-13 under IBKR, so one
  when-issued IBKR bar on the unadjusted scale stays, 14 holes before Tradier's 2016-07-05; the
  append-only table cannot shorten a row below one day (the VMRK case).
- IBKR rows: none.
- Undecided, no row:
  - BNY, CF, CPAY, MGM, WELL (H3: IBKR steps inside the run; IBKR is not a clean series there).
  - DOV (H3: IBKR steps -17.6% on 2014-03-03 inside the run while Tradier is flat, and the run's
    end rests on one bad Tradier print on 2018-05-08; neither vendor is continuous across it).
  - OUT (H2: the Tradier head is not the same series; a head row is likely right but rests on a
    different premise than the owner decision).
  - EWT (the 185-37 rule leaves it undecided: IBKR's boundary move 0.033085 against 0.032910).
  - ELE, LION, W (the rule leaves them undecided: both vendors out of range at the boundary).
  - KDP (the rule leaves it undecided: on 2018-07-10 both vendors move out of range; the date is
    the Keurig merger's special distribution, a real price move, so which series is right depends on
    how the dividend layer carries it).
  - PATK (Tradier itself steps log 0.335 on 2011-05-23 inside the run decided tradier; neither
    vendor is continuous over 2006 to 2017).
  - STE (IBKR steps on 2014-04-02 and 2014-05-08 inside the run decided ibkr; closing also removes
    1,166 IBKR bars Tradier never answered).
  - IP (continuity is clear, Tradier adjusts for the Sylvamo spin-off and IBKR does not, but closing
    removes 2,414 IBKR bars from 2006-10-03 to 2016-05-06; the owner decision did not weigh that
    loss against one 5.6% false return).
  - NEXN (closing removes 637 IBKR interior bars; the two vendors disagree by 3% to 13% day to day).

Expected D7 effect if applied: vendor_basis_run 35 to 12 (CF, CPAY, DOV, MGM, WELL, EWT, ELE, KDP,
LION, NEXN, PATK, W). session_coverage may newly fail on the EW* names (6 in-run holes each), as UNG
did in 185-37.

### Amendment 2026-10-08 (orchestrator decisions, consistent with the owner's option 1; before any apply)

Wrong-basis data becomes holes; missing is NaN; the raw observations stay in D1.

1. IP and STE: their 185-38 rows are closed at the first day plus one, like FTV. IBKR bars on the
   wrong scale inside a stepping run are the same defect as a stale head. No IBKR row is written for
   STE (its 2014-03-19 to 2015-07-24 IBKR series fails H3). Preview (`logs/185-49/preview_closures_final.tsv`,
   close only): IP removes 2,414 IBKR bars (2006-10-03 to 2016-05-06) and changes 2,618 (2,614
   values from 2016-05-09 to Tradier, 4 source labels); STE removes 1,166 IBKR bars (2006-10-03 to
   2011-05-20) and changes 3,866 (3,864 values from 2011-05-23, 2 labels); FTV removes 14 and changes
   2,579. As with FTV, each closed row keeps its first day (IP and STE 2006-10-02, a LEGACY_IMPORT bar)
   as one IBKR bar ahead of the holes.
2. OUT: head row from 2011-05-27 to 2014-11-18. Its 115 Tradier dates before the 2014-03-28 listing
   belong to a different series; the row is a data-quality exclusion of those dates, not a returns
   decision. Preview: 115 removed (all before the listing), 163 changed (the run), nothing else.
3. Undecided, no row, handed to todo 512's data-quality rule (per-name hand work): BNY, CF, CPAY, MGM,
   WELL, DOV, EWT, ELE, LION, W, KDP, PATK, NEXN.

Final sets: head rows 39 (the 38 above plus OUT); closed 185-38 rows 3 (FTV, IP, STE); IBKR rows 0;
undecided 13. Apply gates: each name's daily dry run equals its preview row; for a head row, removed
only head dates and Tradier-only dates inside the run and nothing changed outside the row's range;
for a closure, removed only the IBKR head bars listed above, changes only on dates Tradier answers
(values to Tradier) plus the source-only relabels. Any other difference stops the apply.

### H2 checked exactly (2026-10-08, before the first apply)

`logs/185-49/tools/h2_exact.py` recomputes H2 per name with the run's first min(20, n) sessions.
37 of the 38 pass; NSC's 8-session run gives 1.02 bp. EWS fails: its three LEGACY head dates give
median 2.002083 against the run's 2.000000, 10.42 bp against the 10 bp tolerance (Tradier's stale
closes are rounded to the cent, 9.46 against 18.94 / 2). By the rule EWS gets no row and joins the
todo 512 list. Final sets: head rows 38 (the 37 plus OUT), closed 185-38 rows 3, IBKR rows 0,
undecided 14.

## Applied

2026-10-08, fetcher and Tradier timers inactive, no derivation or fetch process running.

1. D7 baseline by hand, 19:58 to 20:10 UTC (`logs/185-49/d7_before.out`, per-name verdicts
   `logs/185-49/verdicts_before.tsv`): vendor_basis_run 35, unexplained_seam 6, canonical_recompute
   1 (CTVA), freshness_1d 2 (CTVA, QRVO), session_coverage 191; policy_conformance, lineage_missing,
   digest_fresh 0. Equal to 185-47's after state.
2. Policy rows, 20:14:58 to 20:15:26 UTC, through `ops_source_policy.py`, one name at a time, a dry
   run of all 41 first (`logs/185-49/policy_dryrun.log`, all exit 0), then `--apply`
   (`logs/185-49/policy_apply.log`, driver `logs/185-49/tools/apply_rows.py`, evidence per name
   `logs/185-49/evidence_185_49.json`): 38 head rows inserted, 3 rows closed (FTV at 2016-06-14, IP
   and STE at 2006-10-03), 0 refused. 1d symbol rows: open 76 to 73, closed 31 to 72.

3. Daily dry run over the 41 names (`logs/185-49/daily_dryrun.tsv`): the 38 head-row names equal
   their previews on every count. FTV, IP and STE equal their previews on every count but the
   stage refuses them: revision ratio 0.9992 to 0.9996 against `max_revision_ratio` 0.02, and the
   waiver does not fire. The waiver (`_SELECT_REVISION_WAIVER_SQL`) and the nightly `policy_since`
   probe look for a policy row whose `recorded_at` is newer than the name's last applied load; a
   close only sets `valid_to` and the table has no column recording when, so a closure is
   invisible to both. Fixing it needs a code or schema change (a close timestamp, or a close
   recorded as a row), outside this plan; the three names are stopped, not forced.
4. Daily apply of the 38 head-row names, 20:16:17 to 20:16:36 UTC (`logs/185-49/daily_apply.tsv`):
   38 `ohlcv_load` rows applied, every count equal to the preview; 2 new (EWM, EWU: one IBKR
   interior date each that d2-v2 had refused), 50,056 changed (tradier to ibkr_named), 54,565
   removed (head dates and Tradier-only run dates); a dry run afterwards shows 0 new, 0 changed,
   0 removed. Per name new/changed/removed: AAON 0/1163/1700, ABT 0/1167/1697, ADP 0/651/1981,
   BAX 0/1167/1697, BDX 0/4868/1697, BF.B 0/1167/149, CAH 0/733/1697, CHD 0/1167/1697,
   COP 0/1199/997, CVBF 0/63/1696, DRI 0/1167/1697, DUK 0/98/1661, EBAY 0/1168/1696,
   EQT 0/981/1697, EWI 0/2537/1684, EWJ 0/2605/1634, EWM 1/2536/1701, EWU 1/2536/1702,
   FIS 0/440/169, FLO 0/1167/1696, GL 0/1167/1697, IBB 0/2315/1913, IRM 0/2009/1697,
   KIE 0/2809/211, KMB 0/1167/1697, MAS 0/1167/1697, MS 0/222/144, NI 0/1167/1697, NSC 0/12/1696,
   PPL 0/1167/1697, ROST 0/1168/1696, SPG 0/1202/1662, TT 0/1166/1698, VTR 0/1167/1697,
   VZ 0/976/1538, WMB 0/1200/1664, XRT 0/1232/4, OUT 0/163/115.

5. D7 after by hand, 20:22 to 20:34 UTC, exit 0 (`logs/185-49/d7_after_full.out`, per-name
   `logs/185-49/verdicts_after.tsv`; an earlier run at 20:17 was cut by a shell timeout in its
   intraday section, its 1d table is identical).

| check (1d, failing names) | before (20:03) | after (20:32) | pass to fail | fail to pass |
|---|---|---|---|---|
| vendor_basis_run | 35 | 13 | none | 22: ABT, BAX, BF.B, CAH, CHD, COP, DUK, EBAY, EQT, EWI, EWJ, EWM, EWU, FIS, FLO, GL, IBB, KIE, NI, NSC, ROST, XRT |
| unexplained_seam | 6 | 6 | none | none |
| canonical_recompute | 1 (CTVA) | 4 | FTV, IP, STE (rows closed, bars not re-derived) | none |
| policy_conformance | 0 | 3 | FTV, IP, STE (same) | none |
| freshness_1d | 2 (CTVA, QRVO) | 4 | PSKY, WBD (calendar, below) | none |
| session_coverage | 191 | 260 | EWJ, EWM, EWU (this plan: 6 in-run holes each), 68 untouched names (calendar) | KIE, OUT |
| lineage_missing, digest_fresh, report_age | 0 | 0 | none | none |

The calendar effect: the baseline's checks ran before the 2026-10-08 close (20:00 UTC) and the
after run past it, with the fetcher off, so every name now misses one completed session
(freshness lag 0 to 1 on every name; SPY coverage 1.0 to 0.99985). That alone moves 68 short-history
names under session_coverage's 0.999 and PSKY and WBD (no bar since 2026-10-06) to 3 sessions,
over freshness's 2; the intraday coverage_cache 0 to 10 failing has the same cause. None of them is
touched by this plan. EWJ, EWM and EWU fail on their 6 holes alone (6 of about 5,100 sessions);
EWI was failing before and still fails. The holes are dates IBKR never answered on the stale span
(2007-02-08, 2007-12-06 to 12-12); the 189-10 gap-fill lane asks IBKR for them.

vendor_basis_run still fails on 13 names, all handed to todo 512: CF, CPAY, DOV, ELE, EWS, EWT, KDP,
LION, MGM, NEXN, PATK, W, WELL (BNY is the 14th undecided name and does not block).

FTV, IP and STE: their 185-38 rows are closed (permanent) and the bars still hold IBKR's whole
history, so policy_conformance and canonical_recompute fail on them, loudly. They complete with one
daily apply once the revision waiver sees a closure (todo 508 stays open for that step); the
previews in `logs/185-49/preview_closures_final.tsv` are what that apply must show.

## Completed by plan 185-50 (FTV, IP, STE)

The waiver gap is fixed: migration 460 adds `bar_source_policy.closed_at`, stamped by the
append-only trigger on the closing UPDATE (applied live 2026-10-08 20:55:29 UTC after a rollback
dry run). The three 185-49 closes are backfilled at 2026-10-08 20:15:26.826 UTC, the upper bound
of their window in `logs/185-49/policy_apply.log` (after OUT's row at 20:15:24.633). The daily
stage's waiver and `--changed-only` probe read `GREATEST(recorded_at, closed_at)` against one
per-symbol baseline, the start of the batch that wrote the symbol's last applied daily load. The
old probe compared with the newest completed daily batch of any scope, so the 38-name batch of
185-49 (finished 20:16:36) hid these closes and CTVA's 15:13 corporate action from it as well.

Live check before the apply, read-only over the 1,529 names with 1d observations: the waiver fires
on 31 names under the new SQL and 28 under the old, the difference being exactly FTV, IP and STE;
the other 28 are the 27 names with no applied daily load (first-load waiver) and CTVA (its
corporate action). No other name gained a waiver.

1. D7 before, 20:55 to 21:07 UTC (`logs/185-50/d7_before.out`, `logs/185-50/verdicts_before.tsv`):
   equal to 185-49's after state on every 1d check.
2. Daily dry run with `--changed-only` (`logs/185-50/daily_dryrun.tsv`): all three due and
   waived; every count equal to `logs/185-49/preview_closures_final.tsv`.
3. Apply, 21:08:49 to 21:08:52 UTC (`logs/185-50/daily_apply.tsv`), new/changed/removed:
   FTV 0/2,579/14, IP 0/2,618/2,414, STE 0/3,866/1,166; changed_source_only 2, 4, 2; revision
   ratio 0.9992, 0.9996, 0.9996, waived. A dry run afterwards shows 0/0/0 for each, and
   `--changed-only` reports all three unchanged.
4. D7 after, exit 0 (`logs/185-50/d7_after.out`, `logs/185-50/verdicts_after.tsv`):

| check (1d, failing names) | before | after | change |
|---|---|---|---|
| policy_conformance | 3 (FTV, IP, STE) | 0 | FTV, IP, STE pass |
| canonical_recompute | 4 (CTVA, FTV, IP, STE) | 1 (CTVA, todo 515) | FTV, IP, STE pass |
| vendor_basis_run | 13 | 13 | none |
| unexplained_seam | 6 | 6 | none |
| freshness_1d | 4 (CTVA, PSKY, QRVO, WBD) | 4 | none |
| session_coverage | 260 | 263 | FTV 0.9942, IP 0.5203, STE 0.7681 now fail |
| lineage_missing, digest_fresh, report_age | 0 | 0 | none |

No other name's verdict moved. The session_coverage failures are the decided consequence of the
closes: the removed IBKR bars were the head before Tradier's first observation (IP 2006-10-03
to 2016-05-06, STE 2006-10-03 to 2011-05-20, FTV 2016-06-14 to 2016-07-01; each keeps its first
day), and those dates are holes now, not false returns. IP keeps about half its sessions and STE about three quarters; whether either is worth
keeping at that coverage is a todo 512 question.

## Paused (resolved)

Resumed the same day with the amendment above. The state at the pause, for the record:
- No bar_source_policy row added or closed, no re-derivation, no D7 run. Live data unchanged since
  185-47. Nothing half-applied.
- Done: study rerun, head-basis and in-run step probes, bar-level previews for all 47 head candidates
  and all 8 closure candidates, the rule and name sets above.
- Not done: per-name `ops_source_policy.py` dry runs and applies (38 head rows, FTV close), the
  daily re-derivation of the 39 names, D7 before and after, the 185-49 SUMMARY.

To resume, in order:
1. D7 baseline by hand (PYTHONPATH set as the unit sets it):
   `PYTHONPATH=/home/bg/dev/indicagent .venv/bin/python services/bar_reconciliation_audit.py`
   and record vendor_basis_run, unexplained_seam, canonical_recompute, freshness_1d and
   session_coverage failing counts.
2. Per name, evidence from `logs/185-49/head_probe.json` plus the preview row:
   `.venv/bin/python scripts/ops/bars/ops_source_policy.py --add --symbol S --valid-from <first_obs>
   --valid-to <run_end + 1> --primary ibkr --reason "..." --evidence '<json>'` (dry run), then with
   `--apply`. FTV: `--close --symbol FTV --valid-to 2016-06-14 --reason "..."`, dry run then `--apply`.
3. `python -m services.bar_derivation --stage daily --symbols <39 names>` dry run; it must equal
   `logs/185-49/preview_heads.tsv` and `preview_closures.tsv` (FTV row) per name; then `--apply`.
4. D7 again; write the results here and the 185-49 SUMMARY.

Open for the owner: IP and STE (data loss on closure), and whether OUT gets a head row on its own
premise.
