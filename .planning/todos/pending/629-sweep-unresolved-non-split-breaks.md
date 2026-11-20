---
status: in_progress
priority: P1
filed: 2026-11-17
source: A3 sweep (ops_split_calendar_audit --sweep --strict --witness yahoo); the 2026-11-20 run over all 12,561 universe members read 25,189 breaks, 19,342 with no Yahoo history, 4,086 unresolved
---

# Sweep: unresolved breaks, gated by materiality

## What

The A3 strict sweep over the universe members leaves breaks no automatic verdict decides. History: the 2026-11-17 active-name run (72 unresolved) was cleared by dispositions (spin-offs, distributions, real moves, reused-ticker identity lines in `config/corporate_actions/sweep_dispositions.csv`), six Massive-route split rows (todo 633), CLBK, UNIT, SNEX and RTX rows, leaving only SW 2016-05-16. The 2026-11-20 members run (`logs/sweep_strict_members_20261120b`, per-row classes in its `triage.csv`) widened the scope to dead names.

## Gate scope (owner 2026-11-20, CLAUDE.md)

The gate covers witnessed breaks that are split-shaped or wrong-scale in the name-years the compute reads: scope C (any `universe_membership` year of the name) for 1d, scope B (a year with `tier_5m` true) for 5m. Scope sizes of the 529 witnessed undecided breaks: A (tier names over their member years) 157, B 81, C 318, 211 outside every scope. A second witness counts only as tape plus a vendor agreeing; the Yahoo-only rule is unchanged. Everything else is disclosed with class counts, never counted as confirmed.

## Landed (lane A2, 2026-11-20)

- Four `massive_reference` rows redated one session (BMI, BRBS, HCSG, USNA; `--correct-massive`, reviewed).
- 31 Yahoo-calendar market split rows (`split_rescale_rows_2026_11_20_a2_b.csv`: CNI, DDD, TBCH, TQQQ; `..._a2_c1.csv`: 27 rows), tape step plus Yahoo adjusted continuity, independently reviewed; derived (5m reselect, daily, grid); member history audit rerun exit 0, 0 findings.
- 17 dispositions (16 one-day real moves, OIS Civeo distribution) and two bad bars (IMVP, SUNE); quarantine tool fix 185f9fd2d (a listed bar in neither canonical nor raw is moot, listed per line); 40 bars quarantined, 109 listed lines moot.

## Disclosure (not gated, not confirmed)

- No Yahoo history (witness_no_data): 3,551 rows, 1,516 names, mostly dead names.
- Yahoo cannot bracket the break (not_bracketable): 262 rows. Route not rescalable with no calendar event: 42 in scope. Calendar ratio does not match the scale: BINI 2025-08-04, JBIO, NWTG, SMX 2025-11-18, TVRD.
- Held for a source or an anomaly: QBTX 2025-10-21 (aggregator sources only), HMNY 2018-07-25 (1:250, outside the recognised ratios), SDEV, PLRZ, TDIC.
- Twelve breaks whose calendar ratio is not a split ratio (distributions or combined events): AHT, BSAC, FWONA, JTAI, NC x2, SMX 2025-10-23, TDW, TKC, TLSA, UL, VHI; MTW, NTGR and OPLN likewise.
- Eleven ETFs whose calendar split lies inside a gap of 12 to 20 sessions in canonical bars (SPEM, SPGM, SPIP, SPLB, SPMD, SPSM, SPTI, SPTL, SPTM, SPYM, USIG) plus IGIB and IGSB: the tool refuses a row across a gap, and each is one contaminated gap return per ETF (lead ruling: no tool change).
- One-bar wrong scale, refused corrections (Yahoo has no split for a dead name): VIP, ACGN, ETS, and CETV 2003-11 (two sessions late, out of scope); ZSL 2015-10 is a coverage hole (no bars 2013-03-15 to 2015-10-30) needing a disposition. NCT and SIX have no Yahoo data. SW 2016-05-16: an identity line cannot rule an `unrecorded_split` verdict; waits on the pit map (todo 624).
- Evidence files: `logs/f3_a2/pin_gating_candidates.csv`, `logs/sweep_strict_members_20261120b/in_scope_C.csv`.

## Scoped rerun result (2026-11-20, `logs/sweep_strict_members_20261120c`)

Strict exits 3 by design (25,149 breaks read, 19,342 with no Yahoo history, 4,084 unresolved). I launched it without `--dispositions`, so the tool did not apply `sweep_dispositions.csv`; the unresolved list was filtered by the dispositions file and the bad-bar list offline (the same rule the tool applies), leaving 4,033 (`sweep_unresolved_with_dispositions.csv`). In scope (C 1d, B 5m) 266 witnessed breaks remain (72 in B), all disclosed classes: not_bracketable 180, route rows with no calendar event 41, five calendar-ratio mismatches, and 34 split-shaped route rows with a matching calendar ratio. Those 34 are exactly the disclosed lists above plus SNX, whose Concentrix spin-off disposition moved from 2020-12-02 to 2020-12-01 after the rederivation (the stale identity line SN 2023-07-31 was removed; the tool counts an unused identity line as a strict failure). Nothing in scope is undecided and split-shaped outside the disclosure. Per-row: `scoped_remainder.csv` in the run directory. The members added by the type fix (missing security types drop about 700 members in 2008 and 2012, 47) are not in this sweep: a non-strict delta sweep over them follows the membership rebuild.

## Done when

The delta sweep over the names the rebuilt universe adds is reported; then the 584 pin readiness row for the strict sweep closes.
