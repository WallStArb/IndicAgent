# D-191-Q daily rule d2-v4 build note (todo 545 step 3)

Author: Claude (executor session, 2026-10-27). Informed by: D-191-Q and D-191-P in `docs/plans/2026-10-12-unified-raw-bar-table-design.md`, todo 545, and the fresh-context review of the first build (2026-10-27).

This step changes code and tests and runs one read-only arbitration. No bar_source_policy row was written, no daily stage or derive ran against the live database, and nothing was written to a live table.

## Commits

| Commit | What |
|--------|------|
| caab252ce | test: first build (RED) |
| 1cc7bf759 | feat: first build, with an agreement guard (GREEN) |
| 4ab0babc0 | test: rework (RED) |
| e1355c906 | feat: d2-v4 rework, so the policy decides which vendor serves |
| 4457a66ef | feat: `--plan` expresses the 1d decision |
| c171920c7 | feat: three-vendor arbitration, pure |
| e31dfd664 | test: arbitration script (RED) |
| 907c445bf | feat: arbitration script (GREEN) |
| 183d11fd1 | fix: the span minimum is the basis window |
| 61e939bea | feat: the report renders from the plan |
| d672e2bcc, 0b99c09c5 | second review M1: IBKR serves as fallback inside the Alpaca era |
| 71079481c, 07752ae7b | second review H1: holds get interim IBKR rows, three-way rule, continuity, quarantine |
| 6f369cf80, 1930730a4 | second review `--plan`: lock, pinned defaults, coverage, fingerprint, quarantine |
| 84e63f454, 4df252223 | second review script: pinned ids, fingerprint, plan sha256 |
| dc961d149, d724430d9 | third review: long pre-IBKR spans, migration 527, prune exemption, global quarantine clear |

The docs commit for this note and the report follows them. `git log --oneline --grep 545` lists them all.

## Review and rework

The first build put an agreement guard inside the rule: Alpaca served only from the first session where IBKR agreed with it. The fresh-context review found three problems:

- HIGH: the guard trusts IBKR wherever the two disagree, and Tradier shows IBKR is often the one that is wrong. OKE's IBKR/Alpaca ratio drifts from 0.76 to 1.42 over 2018 to 2023 while Alpaca equals Tradier to the cent. RJF's IBKR is exactly 2/3 before 2021-09-22.
- MEDIUM: the guard's start date depended on future data.
- MEDIUM: it dropped valid Alpaca history on names IBKR has not fetched.

The rework moves the decision to its own level, as dated policy evidence:

- Rule (`src/intelligence/bars/daily_rule.py`, d2-v4): no agreement screen. Under an Alpaca-primary row, Alpaca serves every session it answered with a trade, and IBKR falls back only where Alpaca has no tradeable bar. Two guards remain, both about tradeability:
  - a zero-volume Alpaca bar is dropped;
  - under an Alpaca primary, a zero-volume IBKR fallback bar is never served, so the session is missing (`zero_volume_fallback`).

  The session-date mapping is unchanged: Alpaca in New York time, IBKR and Tradier in UTC, one canonical row per session at 00:00 UTC. The d2-v3 golden digests (5 fixture cases × 4 policy shapes, with and without Alpaca rows) still match, so output is bit-identical wherever no policy names Alpaca.
- Arbitration (`src/intelligence/bars/vendor_arbitration.py` is the pure part; `scripts/ops/bars/ops_d191q_arbitration.py` is the read-only script):
  - Tradier decides each maximal span where Alpaca and IBKR disagree by more than 10 bp.
  - Alpaca = Tradier: IBKR is defective there; this is evidence only, and Alpaca serves.
  - IBKR = Tradier: a spin-off Alpaca leaves unadjusted, or a reused ticker. The span gets an IBKR symbol row with no fallback.
  - All three differ, or Tradier is absent: the span goes on the owner's hold list.
  - A span shorter than the basis window (APR `fallback_basis_window_sessions`, 20) is noise.
  - Alpaca history before IBKR's first bar is held only where IBKR verified its 1d head; otherwise it is reported and Alpaca serves.
  - The script refuses to run without Tradier 1d raw rows.
  - It writes the plan document and the report `191-D191Q-ARBITRATION.md`.
- `scripts/ops/bars/ops_source_policy.py --plan`:
  - `retire_defaults` retires both live 1d defaults: the closed Tradier default and the open IBKR default.
  - A 1d plan must name every live symbol row: retired with a disposition (`replaced` or `confirmed`, with evidence) or kept with a reason. An unnamed live row refuses the whole plan.
  - New symbol rows insert in the same transaction.
  - Dry run by default. Tests run on temp copies of the table and its trigger.

## Span minimum

The first full run used D7's `vendor_ratio_run_min_sessions` (5) as the span minimum and wrote 129 IBKR rows. 64 of them were 5 to 16 session close-definition episodes at 0.2 to 111 bp (thin ETFs, plus SPY and IWM in March 2020). Every genuine basis span is at least 62 sessions with at least 88 bp, except DELL (717 sessions, 19 bp). The basis window (20) separates the two groups.

## Second review (2026-10-28)

- H1, a hold must mean Alpaca does not serve. `build_plan` now gives every held span an interim IBKR row (primary ibkr, no fallback), and `--plan` refuses a hold span that no new or kept symbol row covers. No live row is kept for coverage any more: a name with new rows retires its old row as `replaced`; the rest retire as `superseded_by_default`, a rename of the old `confirmed`.
- Three-way spans get an IBKR row when IBKR and Tradier both adjusted the history. All three tests must pass:
  - the median log IBKR/Tradier is within 50 bp;
  - its median absolute deviation is under the 10 bp tolerance (the MAD is the spread measure, because single bad prints make a range or p5-p95 useless);
  - it is at most a tenth of the median log IBKR/Alpaca.

  The 50 bp and the tenth are the review's decision values, recorded in the plan's evidence; they are not APR keys. The rule admits HON, ATRO, CBSH, FTV, CNH, EU and YUM. DHC fails the third test (47 bp against 0.1 × 359 bp = 36 bp) and stays held, contrary to the review's expectation.
- Alpaca before IBKR's first bar serves only when it is continuous with that bar. Both conditions must hold:
  - the span's last session and IBKR's first bar are consecutive NYSE sessions;
  - on IBKR's first session, Alpaca's close agrees within tolerance with IBKR's close, or with Tradier's close where IBKR is the vendor that is off (MOD: IBKR off by 826 bp, Alpaca equals Tradier).

  Otherwise there is no bar until the head: an IBKR row from the span start to IBKR's first bar. Verified and unverified heads take the same test; the heads are re-read live every run. Admitted: the IPO-day names (FCFS, ARRY, IBEX, NRIX, RLAY, VOR, FERG), CRH, COO and the other names IBKR has not backfilled. No bar: AA, AKTS, BAM, BTU, CART, CR, CRC, DD, DOW, EXE, FOXA, FWONK and LION. QRVO, which IBKR never answered, is held.

  Interpretation: I read "Alpaca's last close within tolerance of IBKR's first bar" as agreement on IBKR's first session, not as the overnight gap. The gap rejects ordinary IPO-day moves (NRIX 632 bp, FCFS 422 bp). The cost is a predecessor that hands over on exactly that session. SW passes with an overnight gap of -832 bp, and the owner should look at it; the report records the gap for every pre-IBKR span.
- Quarantine. Short spans where IBKR equals Tradier and Alpaca's close is more than `threshold.bar_scrub.view_disagreement_rel` (0.02) off become a per-session list. The apply writes it to `bar_quality_flag` through `bar_scrub.write_flags`, the table's writer path, under one batch with stage `scrub`, because the batch stage CHECK has no policy stage. The rule is `vendor_disagreement`, and the apply refuses unless that rule is in `threshold.bar_scrub.quarantine_rules`. Adding it there is a live APR write, not done here.
- M1, one volume basis. The rework did this in the rule (`alpaca_era_start`, `primary_pair`): on or after the first valid_from of a 1d default naming Alpaca primary, any session IBKR serves is `(ibkr, fallback)`, and the tradeable view nulls its volume. A dedicated kind would need a CVR migration to say the same thing. Policy conformance follows. With no Alpaca default there is no era, so the d2-v3 goldens hold.
- M2, the raw fingerprint. Per 1d raw series, the plan records the row count and the last served_at through Tradier's last day. The script reads the fingerprint before and after it reads the names (exit 3 if they differ). The apply re-reads it under the table lock and refuses on any change. The 2 live default policy_ids are pinned the same way. `--plan` starts with `LOCK TABLE bar_source_policy IN SHARE ROW EXCLUSIVE MODE`, and the report carries the plan's sha256.
- M3, the D7 Alpaca-against-IBKR basis check, is recorded as todo 545 step 5a and not built this round: it changes D7's verdict set and the verdict gate.

## Third review (2026-10-28)

- H1: a long pre-IBKR span needs more than the same-session test, which cannot see a ticker handover (SW served WestRock's 2016-01-04 to 2024-07-05, 2,140 sessions). A span of more than the basis window (20 sessions) is admitted only when the same-session test passes and one of these holds:
  - Tradier answered inside the span and agrees with Alpaca on at least 90% of those sessions;
  - the close-to-close gap at IBKR's first bar is at most 4 of the name's median absolute daily log moves, measured on IBKR's own closes.

  The 4 is APR `threshold.bar_integrity.arbitration_gap_max_daily_moves`, seeded by migration 527, applied live and committed with the code. A span that fails both is held under an interim IBKR row. Spans of 20 sessions or fewer keep the same-session test alone. The rule holds SW (Tradier agreement 0.2%, gap 7.9 moves) and GRNT (no Tradier, 6.8 moves). It admits RKT (Tradier 99.7%, gap 4.5 moves) and SVRA (Tradier 99.1%, 2.1 moves).
- Spans with a gap over 300 bp, 42 in all:
  - Already no bar (discontinuous): AA, AKTS, BAM, BTU, CART, CR, CRC, DD, DOW, EXE and FOXA.
  - Newly held: SW and GRNT.
  - Admitted through Tradier agreement (condition a): APG, APO, ASPN, CORZ, CRCL, DOCN, ESTC, EVER, FIGR, GFL, GH, MOD, NCMI, PRAX, RKT, RYTM, SVRA, TAN, TROX, TXG and XENE.
  - Admitted on the gap alone (condition b), with Tradier contradicting Alpaca on that span (agreement 3.1%): CRH. CRH is the one to look at.
  - Admitted as short spans (20 sessions or fewer): ARRY, AVGO, FCFS, IBEX, RBLX, RLAY and VOR.
- M1: bar_scrub's `_DELETE_STALE_SQL` exempts `vendor_disagreement` from the stale prune (test added). The quarantine apply now replaces the rule globally: every name holding the rule's 1d flags today goes through `write_flags`, with an empty list when the plan dropped it.
- M2: todo 545 step 5a is a blocker. D7's acceptance of the re-derived canonical 1d, and the research notice, wait on it. The judge for a future spin-off is a recorded corporate action (a spin-off factor in `corporate_action`), not a third vendor. The final arbitration re-run and the policy apply must happen before plan 20 deletes Tradier.

## Results (read-only re-run, 2026-10-28 06:50Z)

The plan is `data/policy_plans/d191q_1d_plan_20261028.json` (gitignored); its sha256 is in `191-D191Q-ARBITRATION.md`. 1,529 names, window 2016-01-04 to 2026-10-06.

| Class | Action | Spans | Sessions | Names |
|-------|--------|-------|----------|-------|
| alpaca_differs | row | 46 | 72,826 | 46 |
| three_way | row (both adjusted) | 7 | 12,656 | 7 |
| pre_ibkr_history | row (no bar until IBKR's head) | 13 | 11,360 | 13 |
| three_way | hold, interim row | 19 | 18,319 | 16 |
| two_vendor | hold, interim row | 2 | 1,368 | 2 |
| pre_ibkr_history | hold, interim row (SW, GRNT, QRVO) | 3 | 5,330 | 3 |
| pre_ibkr_history | info, Alpaca serves | 122 | 177,467 | 122 |
| ibkr_defective | evidence, Alpaca serves | 1,318 | 19,344 | 194 |
| noise (all classes) | Alpaca serves | 5,484 | 7,401 | |

That is 90 IBKR symbol rows in all, 24 of them interim. 285 quarantine sessions on 215 names. All 154 live 1d symbol rows retire: 21 replaced, 133 superseded_by_default, none kept.

## Gate

- Targeted suites pass, and the full `pytest tests/unit/ -n auto` is green after the third-review fixes.
- ruff and black are clean.
- Commits go through a detached scratch worktree off origin/main: another session's untracked test file trips the duplicate-test pre-commit check in the shared checkout, and local main holds another session's unpushed commit.

## For step 4 and later

1. The plan is perishable. IBKR still re-serves old 1d sessions (last serve inside the window: 2026-10-28 01:09Z), so the apply refuses once the fingerprint moves. Re-run the arbitration immediately before the dry run and the apply, with the fetchers idle.
2. Before an apply that carries the quarantine list, add `vendor_disagreement` to `threshold.bar_scrub.quarantine_rules`, through a migration with its APR history row.
3. Owner: the 24 interim holds (the report's hold list; DHC, SW and GRNT among them) and CRH, admitted on the gap alone while Tradier contradicts Alpaca.
4. The fetcher's end stage runs d2-v4 from this checkout. Under today's policy the bars are unchanged, but the touched names' digests relabel, so D7's `digest_fresh` fails until the plan 20 Task 3 re-derive.
5. Alpaca has no 1d split re-ask; D7 has no Alpaca-against-IBKR check yet (step 5a, a blocker for D7's acceptance and the research notice); `services/bar_hold.py` `_VENDOR_RATIOS_SQL` reads SMART and TRADIER only.
