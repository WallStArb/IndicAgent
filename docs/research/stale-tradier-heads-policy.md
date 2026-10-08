# Stale-basis Tradier heads and the 185-38 rows contradicted by continuity (todo 508, plan 185-49)

**Author:** Claude (Sonnet 5.5), 2026-10-08, at Brandon's request
**Status:** in progress; paused by the owner 2026-10-08 before any policy row was written (see "Paused")
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

## Paused

2026-10-08, by the owner, before any write. State:
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
