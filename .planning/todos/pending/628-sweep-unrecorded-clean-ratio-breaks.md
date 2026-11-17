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

## Evidence pass 2026-11-17 (indicagent-55; read-only, Yahoo calendar via `--audit`, raw closes)

Classes of the 20 rows:

- Real forward splits, Yahoo calendar lists the split, Massive served unadjusted, incumbents adjusted (11 rows,
  10 names): XHE, XHS, XSW, XTN (2:1, 2015-09-11), ALK (2:1, 2014-07-10), PENG (2:1, 2022-02-02), AAON (3:2,
  2013-07-03), MDU (3:2, 2003-10-30 and 2006-07-27), MGEE (3:2, 2014-02-10), ROL (3:2, 2018-12-11). No writer
  records these: todo 630 owns the mechanism and the rows.
- Distributions where the calendar factor is not a split ratio (ABT 2.084, DELL 1.973, HPQ 2.202, POST 1.528,
  XPO 1.718; the audit verdict is `not_a_split_ratio` and the incumbents read adjusted by the same factor): a
  spin-off or separation by size; each needs a filing witness and a disposition, never a row. Value leaves the
  holder's line at the break, so returns across it are understated by the distributed value; no table holds
  the distribution (the ATRO precedent in todo 622); promotion-grade total returns need a distribution table first.
- Not splits by the raw series: GSAT 2021-02-10 (+0.67): IBKR, Alpaca and the rescaled Massive all move
  18.45 to 31.2 (2021-02-09) to 36.0 (2021-02-10) with 17 to 300 times normal volume, the same move in every
  vendor, so a real move across two sessions; the 2021-02-08 operator row (factor 0.609687, Alpaca route, todo
  592) is then suspect and needs a review, it does not rescale canonical (Massive serves 2021). HLT 2016-12-13
  (Massive's series starts that day at 26.38 against 54.13 at the incumbents) and ENOV 2022-03-21 (Massive
  starts that day at 39.69 against Alpaca 119.07, IBKR 68.26) are Massive series that begin on the break
  date at another scale: identity or vendor-seam class, with todo 624 and the pit map, not a split row.
  SVRA 2017-01-09 (+0.42, volume 62k to 1.46M, Alpaca only) reads as a merger or listing event.

Rows and dispositions are not prepared here: the split rows wait on todo 630, the distributions on witnesses
(each is a filing read), and the not-split rows on the ruling above.

## Rulings 2026-11-17 (lead, indicagent-77, on the evidence pass)

- The eleven real splits go through todo 630 (`calendar_market`); the five distributions have dispositions
  (`sweep_dispositions.csv`, filings read from the search summaries and URLs named: ABT, DELL, HPQ, POST,
  XPO) and the returns policy in `docs/research/2026-11-17-returns-across-distributions.md`.
- GSAT 2021-02-10: no row; a real move. The 2021-02-08 operator row (factor 0.609687, Alpaca route) should be
  voided in a todo, not now: it rescales the Alpaca series before 2021-02-08 by 1/0.609687 while Alpaca, IBKR
  and Massive agree on the move (18.45 to 31.2 to 36.0), so the row manufactures a step in Alpaca's own series;
  canonical is Massive in 2021 and unaffected. Void it with the next batch of operator-row reviews.
- HLT, ENOV, SVRA: todo 624 (seam and identity cases).
