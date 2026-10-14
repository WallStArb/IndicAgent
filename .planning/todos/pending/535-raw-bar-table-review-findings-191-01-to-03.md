---
status: pending
priority: P1
filed: 2026-10-13
source: independent review of phase 191 plans 01-03 (fresh-context Claude reviewer; AGY and Codex out of quota)
owner: phase 191
---

# Raw bar table review findings that plan 191-04 does not close

Full report: scratchpad `review_claude_01-03.md` of the 2026-10-13 session (the findings below are
self-contained). Findings 1 to 3 of the review (per-route venue kinds, delta update-on-difference,
archive value kept with the canonical value as a revision) went to the 191-04 executor.

## Open

1. A refusal does not last. `write_raw` replaces raw current with the refused values, and selection
   reads current raw plus policy, so the next unchanged overlapping fetch or the plan 07 rebuild
   writes them into canonical. Design (owner direction pending objection): raw stays faithful; a
   refusal is a held span (vendor, kind, series, span) that selection skips until explicitly
   accepted. Plan 07 already names a `refused_self_restatement` class (slots of a series whose raw write was refused are excluded from selection, via the ohlcv_load outcome), so this is probably built there: verify plan 07 makes the exclusion durable across reruns before adding a table.
2. A slot with no winner, or a winner with NULL volume, leaves the old canonical row
   (`bar_selection.py:124-134`), so canonical depends on history. Use `removal_scope`, fall to the
   next candidate on NULL volume. Do not wire `apply_raw_contract` before plan 07 seeds the Alpaca
   spans (live 5m policy is IBKR-only; 220M canonical 5m rows are Alpaca).
3. Reconstructed revision loads carry today's `loaded_at` for restatements back to 2005;
   `ops_data_bar_check.py` uses `MAX(loaded_at)`, so known-answer keys can flip from replaced to
   open (inferred, not run). `old_source='ibkr'` on `smart_trades`/`venue` rows reads as `generic`
   in migrations 472/475.
4. Policy spans match by UTC calendar date, not session date (`selection.py:107`); Alpaca AAPL 5m
   has 8,331 post-market bars after 00:00 UTC. Harmless until dated spans are seeded. Kind
   `sip_rth` holds post-market bars, contradicting its description.
5. Low: `--check` subtracts canonical diffs by count, not by row (`ops_raw_backfill.py:781`);
   no advisory lock between read and upsert in `write_raw`; canonical-only kind `fallback` would
   enter raw; a chunk with the same key twice drops the earlier value; request-writer buffer is
   handed over by reference; `ohlcv_revision.load_id` ON DELETE CASCADE removes revision evidence
   when Tradier loads are deleted (plan 20); a deferrable `ohlcv_revision` FK would let
   `preview_series` go; `bar_derivation_writer` holds INSERT and UPDATE on `ohlcv_raw`.

## Status after plan 191-05 (2026-10-13)

- Item 1 (refusal does not last): done in 191-05, no new table. A refused series writes no raw row;
  its offered values that differ from the stored rows are `ohlcv_revision` rows of origin `pending`
  (migration 477, applied live at the window resume step); the stored rows stay current. Tests: unit
  (refuse, unchanged re-offer, raw and selection untouched) and integration under the real role.
  Plan 07's `refused_self_restatement` class should now count zero (amendment appended to plan 07);
  a release command is not built (a waived write releases).
- Item 5, advisory lock per series: done (`write_raw`, `preview_series`). Same key twice with different
  values in one chunk: raises. Request-writer buffer: swapped, restored on failure. `fallback` into
  raw: closed in 191-04.
- Item 5, deferrable FK: decided against. A refused series must be classified before any write, so
  `preview_series` stays whatever the FK does; the advisory lock now makes preview and write agree
  by construction.
- Still open: items 2, 3, 4 and the `bar_derivation_writer` grant on `ohlcv_raw`; the CASCADE on
  `ohlcv_revision.load_id` (plan 25 Tradier retire).

## Status after plan 191-07 code (2026-10-14)

- Item 4 (spans by UTC date): done. Selection matches `bar_source_policy` spans by the NYSE session date;
  kind `sip_rth` is a candidate only on the regular-hours grid (Alpaca's extended-hours bars stay in raw
  and never reach canonical; D-191-L).
- Item 2, no-winner half: the selection writer counts slots no ranked vendor holds (`unselected`); the
  loader and nightly report them and fail on them. The NULL-volume half needs no change today (no raw row
  of 1m, 5m or 4h has a NULL volume). Canonical rows selection no longer produces are not removed; the
  selection gate reports them as `only_canonical` differences instead.
- Advisory lock per (symbol, timeframe) before `select_and_write`, upsert tail on new rows: done.

## Open items from the plan 191-06 review (2026-10-14), not fixed in the 06 fixes

6. Medium: any single route's `no_data` covers a 1d session. `_d1_gaps.py` (`_ANSWERED_WINDOWS_SQL`
   with `_DAILY_ROUTES`) treats a `no_data` window on SMART or on any one listing-venue route as
   covering the session; the empty-history rule (`confirmed_empty_spans`) requires every required
   route to agree. Live mechanism: SCHW SMART `no_data` 2006-10-05..2010-03-04 over 651 venue
   bars; DAL ISLAND `failed` while SMART/ARCA/AMEX/BATS answered `no_data` in the same run. No
   hole found today (DAL and VRP are genuinely pre-listing), but a failed listing-venue walk under
   a SMART `no_data` window would never be asked again. Fix: for 1d, the confirmed spans (every
   required route `no_data` in one run) become the `no_data` coverage, not per-route windows.
   Recommended placement: plan 191-08 (the daily rule), before the fetcher resumes, with a
   fake-conn test of a SMART `no_data` over a span a venue route failed.
10. Low: a forming 15m or 1h bar is asked, stored and counted as covered. `plan_gaps` caps the
    forming slot at `run_end`; IBKR returns the partial bar; it is stored and counts as a slot.
    5m is re-asked by the update overlap (last-wins), 15m and 1h have no overlap lane, so a
    partial bar stays until a gap-fill restates it. Reach is limited (15m and 1h are parity and
    derived series). Fix: drop intraday slots whose end is after `now` from the horizon, as the 1d
    planner now does for unfinished sessions (`session_complete_at`). Recommended placement: plan
    191-08 with item 6, one planner pass, so the intraday rule and the 1d rule are decided together.

## Acceptance

Each item is fixed in the plan that owns it, or deleted with a reason here. Findings 1 and 2 land
before plan 191-07.
