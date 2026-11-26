# Path to the first counted test

Status: operative, condensed 2026-11-25 (the 2026-11-03 task lists, the 584 item list and the IBKR-era amendments are history: `git log -p -- docs/plans/2026-11-03-path-to-first-counted-test.md`, last full text at `ec7d5c950`). The lead keeps it current.

**Goal:** hypothesis tests on real data that the research runner counts, on a corpus that passes the data gate, under the written universe and vintage the owner approved.

## What stands

- Canonical bars: Massive from 2003-09-10 to the archive end 2026-11-16, then Alpaca SIP; no IBKR (todo 600 owner ruling, ledger E22). Targets come from `panel.forward_returns` (open to open).
- Universe: the stage 2 membership (todo 609, `docs/plans/2026-11-13-stage2-universe-preregistration.md`, frozen with dated amendments), 12,857 securities over 1,042,561 membership rows, rule and 2,950 member floor as recorded there.
- Price-derived 1d families run through S0 to S8 today, with no stored feature column (`panel.fields` admits high, low and sector_pit). The E21 lift of 2026-11-22 covers that class; a family that reads stored feature columns needs its own clean-data ruling and the horizon-5 1d feature route (`docs/plans/2026-11-24-family-order-after-1d-corpus.md`).
- Global constraints: one pin move, one rerun (every stored-value change lands before the pin moves); nothing launches on a red gate; every code landing runs /simplify, /review and the suite exit code; costs never enter a test statistic (E15 to E18); fit validity decides K, never returns.

## The live chain

1. Data gate at scope 1d: passes (todo 609 s0 to s8; the A3 sweep is gated by materiality, owner 2026-11-20).
2. Pilot at the current rebuild pin (`0f593f92f8b4`, scope 1d, 65 names; the new pilot follows the capture-delivered preflight of todo 675), then read `corpus_run.measured`.
3. `stage_1d` through `feature_complete` only, on the 1d corpus; then abandon the old pilot f9f69166 (`--release`).
4. IC measure at the scope-1d pin: width 16, `ic_tfs` 1d only (todo 471); 15m and 5m wait on todos 667 and 668. Every measured cell is a counted attempt (E21), so a sweep declares its `n_looks` first and runs behind todos 670 and 671 (landed).
5. First feature family: the order and the gates are in the family-order doc (H-B low risk first, then `corpus_family`), behind the shared horizon-5 1d feature route build and a battery block.

## Counted so far

vintage_1 holds 24 charged rows (16 completed with a series, 8 failed and exempt) of `alpha.research.budget_m` 30: the daily residual family, H-C seasonality, family 9 and family 10. The StepM read on 16 series (ledger 2026-11-25b) selects `reversal_21` (primary and core) and `volume_shock_1_50` (primary only); nothing is promoted. Open owner decisions are in `docs/operations/owner-action-sheet.md` section 6.

## Review focus kept

1. A pin move with an item still open stores the old value silently: check every row reads landed and `git log` matches before the pin is taken.
2. The universe must not drift between the rerun and the test: the family spec cites the frozen universe by hash.
3. Looks counted against the wrong vintage inflate or forgive the multiple-testing burden: the vintage ruling is recorded in the methodology-change ledger before a family runs.
4. A worker editing a file another worker owns loses hunks: assignments name file sets and the lead re-verifies `git status` on every landing report.
