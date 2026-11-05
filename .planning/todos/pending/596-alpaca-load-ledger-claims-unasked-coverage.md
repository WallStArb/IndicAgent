---
status: pending
priority: P0
filed: 2026-11-05
source: lead (indicagent-4d), from the 186-32 data-gate executor's live findings
---

# The Alpaca 5m load ledger claims coverage nobody asked for; make it truthful, then re-ask

## What (measured 2026-11-05 by the 186-32 executor)

1. `ohlcv_load` for Alpaca 5m (50,226 rows): `requested_start`/`requested_end` equal the first and
   last bar served, not the window asked. The 2016-2026 rows are 10,000-bar chunks that span any
   hole; their request log (`logs/alpaca_depth/`) is not on disk.
2. The Alpaca fetcher writes one row per page, each claiming the whole remaining window (AAOI:
   page 1 claims 2026-10-06..10-26, ends 10-22 22:50).
3. `gap_plan.LOAD_COVERAGE_*` (`src/intelligence/bars/`, used by the backfill planner and the D7
   audit) treats an applied Alpaca load as answering every slot in its range. A hole inside a
   load is therefore never re-asked and never reported: silent.
4. Consequence for the data gate (186-32): Alpaca 2016-2026-10 thin names cannot be proven
   complete. 547,938 Alpaca sessions read partial; only ledger evidence from 2026-10-06 onward can
   clear a thin session (answer-complete basis).

5. From the 186-32 independent review: a failed Alpaca page writes no request row
   (`src/providers/alpaca.py:213` raises before `_record`), and the nightly flushes request rows
   even without `--apply`, and a load failure after a fetch leaves a "bars" row with no stored bars
   (PSKY, WBD, QRVO, 2026-10-26). The ledger therefore records answers that were never answered
   in full or never stored.

## Decision (lead)

Truth first, then evidence, then re-ask (raw-capture law 528: every answer stored, last-wins):
1. The ledger records the window asked and whether the answer completed: one row per logical
   request (all pages), `requested_*` = the asked window, completion = every page arrived (the
   last page's next-token empty), per-page detail kept. No inference from bars served. A failed
   page writes a `failed` row before the error propagates; each page records whether it was
   terminal (no next token); a dry run writes no ledger rows; a request row links to its stored
   raw rows (`ohlcv_raw.request_id`) so "answered and stored" is checkable.
2. `gap_plan` treats only completed answers as coverage, on the asked window. Rows written under
   the old semantics prove nothing and are never coverage; say so in the code and a test.
   Measure what D7 and the planner then report as holes, and report before and after.
3. Re-ask Alpaca 5m from 2016-01-04 to 2026-10-06 for every name whose sessions are not
   bar-complete in the 186-32 dry run, through the existing capture leaf (no new fetch path),
   under the truthful ledger. Then the data gate's answer-complete basis covers thin names on
   recorded evidence. Measure the request budget and time first; Alpaca SIP historical is
   rate-limited per minute, not per day.
4. Rerun the 186-32 dry run and report the table.

## Done when

The ledger is truthful, gap_plan reads only completed answers, the re-ask is recorded, and the
data gate's Alpaca era reports thin sessions as answer-complete on evidence (or as named holes).
Gates the 584 pin with 534 and 594.
