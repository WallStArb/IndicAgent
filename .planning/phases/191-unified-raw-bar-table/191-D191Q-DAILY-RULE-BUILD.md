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

## Results

Read-only full run, 2026-10-27 21:24Z, 1,529 names, window 2016-01-04 to 2026-10-06. The class table, rows, hold list and dispositions are in `191-D191Q-ARBITRATION.md`. The plan is `data/policy_plans/d191q_1d_plan_20261027.json` (gitignored).

| Class | Action | Spans | Sessions | Names |
|-------|--------|-------|----------|-------|
| alpaca_differs | row | 46 | 72,826 | 46 |
| ibkr_defective | evidence | 1,318 | 19,344 | 194 |
| three_way | hold | 26 | 30,975 | 23 |
| two_vendor | hold | 2 | 1,368 | 2 |
| pre_ibkr_history | hold | 27 | 18,934 | 27 |
| pre_ibkr_history | info | 116 | 186,015 | 116 |
| noise (all classes) | none | 5,479 | 7,396 | |

Of the 154 live 1d symbol rows, 136 retire (132 confirmed, 4 replaced) and 18 are kept: 17 on hold names, plus QRVO, which has no common sessions to arbitrate.

## Gate

- Targeted suites pass.
- `pytest tests/unit/ -n auto` shows 4 failures in `tests/unit/research/test_runner_book.py`. They come from another session's uncommitted WIP in `src/intelligence/research/` (missing E17 certificate) and touch nothing here.
- ruff and black are clean.
- The fresh-context review of the first build came from the coordinator. The rework has had no second review.

## For step 4 and later

1. Owner decisions in the hold list:
   - The three_way spans whose IBKR/Tradier column is near 1 (HON, ATRO, CBSH, FTV, CNH and others) are spin-off adjustments that IBKR and Tradier applied with factors a few bp apart. Each could become an IBKR row, but per the spec none is written automatically.
   - The pre_ibkr_history holds (SW, AKTS, COO, CRH, CR and others) are Alpaca history before an IBKR head that IBKR verified. Each is either a predecessor under a reused ticker or the limit of IBKR's coverage.
2. Step 4 runs `ops_source_policy.py --plan data/policy_plans/d191q_1d_plan_20261027.json`, a dry run first. Names whose live row is kept stay as they are today until the owner decides.
3. The rule version moved. The IBKR fetcher's end stage (`--stage daily --apply`) runs d2-v4 from this checkout. Under the current policy its bars are identical (read-only check, 1,523 names, 0 mismatches), but it relabels the touched names' 1d digests. D7's `digest_fresh` fails for the other names until plan 20 Task 3 re-derives, or until a `--rewrite-digests` run.
4. Splits: Alpaca has no 1d split re-ask. After a recorded split, older Alpaca sessions take the restated IBKR fallback until Alpaca's history is asked again.
5. D7: `vendor_basis_run` compares Tradier against IBKR only. `services/bar_hold.py` `_VENDOR_RATIOS_SQL` reads SMART and TRADIER only.
6. The arbitration is evidence frozen at Tradier's last day, 2026-10-06. A name's spin-off after that date has no third vendor to decide it; the D7 extension in item 5 is where later events surface.
