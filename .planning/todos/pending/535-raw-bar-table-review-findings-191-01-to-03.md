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

## Acceptance

Each item is fixed in the plan that owns it, or deleted with a reason here. Findings 1 and 2 land
before plan 191-07.
