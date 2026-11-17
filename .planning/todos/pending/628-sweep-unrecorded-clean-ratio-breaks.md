---
status: pending
priority: P1
filed: 2026-11-17
source: A3 sweep run 2026-11-17 (ops_split_calendar_audit --sweep --strict --witness yahoo, exit 3: 1,529 active names, 634 lone breaks, 72 unresolved, 0 recorded_unapplied, 0 double adjusted, 0 witness errors; the unresolved list is the run's _unresolved.csv)
---

# Sweep: unresolved breaks that read as clean split ratios

## What

20 unresolved breaks whose size is a simple ratio (2:1, 3:2, 3:1, 1:2, 2:3, within 3 percent) and which the
Yahoo witness could not decide (`reported`): no recorded split within 30 days of the break, no disposition. By
size alone these are unrecorded splits, but a spin-off or a distribution can land on the same size, so each
needs a non-price witness (a filing or an exchange notice) before a row or a disposition.

- AAON 2013-07-03 (-0.41, reported) x3/2
- ABT 2013-01-02 (-0.71, reported) x2/1
- ALK 2014-07-10 (-0.68, reported) x2/1
- DELL 2021-11-02 (-0.71, reported) x2/1
- ENOV 2022-03-21 (-1.11, reported) x3/1
- GSAT 2021-02-10 (+0.67, reported) x1/2
- HLT 2016-12-13 (-0.70, reported) x2/1
- HPQ 2015-11-02 (-0.67, reported) x2/1
- MDU 2003-10-30 (-0.40, reported) x3/2
- MDU 2006-07-27 (-0.41, reported) x3/2
- MGEE 2014-02-10 (-0.41, reported) x3/2
- PENG 2022-02-02 (-0.72, reported) x2/1
- POST 2022-03-11 (-0.41, reported) x3/2
- ROL 2018-12-11 (-0.41, reported) x3/2
- SVRA 2017-01-09 (+0.42, reported) x2/3
- XHE 2015-09-11 (-0.69, reported) x2/1
- XHS 2015-09-11 (-0.69, reported) x2/1
- XSW 2015-09-11 (-0.69, reported) x2/1
- XTN 2015-09-11 (-0.69, reported) x2/1
- ZWS 2021-10-05 (-0.68, reported) x2/1

## Requirement first (Musk step 1)

Is a per-name filing witness the right unit? The four 2015-09-11 sector ETFs (XHE, XHS, XSW, XTN) move
together by 2:1 on one date, so one issuer notice settles all four. Group the rest by event type (split,
spin-off, reverse split) before reading filings.

## Scope

1. A witness per group (event type, ratio, effective date, URL), as todo 622 did for CLBK and ATRO.
2. Rows through `--apply-rows` where the ratio is not a recognised ratio (the split ratio rule's denominator
   bound is 4) and `--apply-massive` where it is; spin-offs and distributions get a disposition, never a row.
3. Rerun the sweep once.

## Gates

The sweep lists none of these rows unresolved; recorded rows carry the witness in `detail`; unit suite exit code.
