---
status: pending
priority: P2
filed: 2026-10-10
source: owner directive 2026-10-10 ("run simplify on 185, 187-190"); four-agent simplify over the load-bearing 185/189 code; findings in docs/plans/2026-10-10-simplify-findings-185-189.md
---

# Post-backfill simplify backlog: the 185/189 findings no one applied

## What

The four-agent simplify pass over the load-bearing 185/189 code found ~40 items, none urgent
during the live backfill. The full findings live in
`docs/plans/2026-10-10-simplify-findings-185-189.md` (committed); apply them after the backfill
completes, highest cost first:

1. Answered-window SQL exists in five copies (bar_derivation, bar_reconciliation_audit,
   bar_auditor, _empty_history, _d1_gaps) — the corroboration rule is the todo-462 coverage
   contract; one drift reads as silent coverage miss in the check built to catch drift.
   Consolidate to one parameterized constant in gap_plan next to AnsweredWindows.
2. The 5m load-and-shape recipe is copy-pasted between bar_derivation `_run_symbol` and the
   audit's `_FiveMinute.from_rows`, with ~10^8 redundant per-row timestamp conversions per
   night; one pure shaper serves both.
3. The month-digest recipe exists three times; `write_1d_digests` re-inlines what
   `_month_digest_rows` returns and writes the stored digests the other two verify against.
4. The check-name contract (what D7 judges vs what promotion requires) is defined in two
   independent lists (integrity_checks CHECKS_* vs verdict_gate REQUIRED_CHECKS); derive one
   from the other.
5. Timeframe-to-bucket tables restated in four modules (sources, integrity_checks, gap_plan,
   scrub_rules); derive from sources.GRID_TIMEFRAMES so the 4h promise becomes true.
6. D7 per-name round trips: _HAS_REAL_BEFORE per (symbol, tf) (~3,000 sequential queries per
   run), two fetchvals per moved name, non-gathered per-name input fetches.
7. The fetcher's nine copy-paste APR overlay loaders (~170 lines, ~10 startup connections);
   ohlcv_history_fetcher's `prepare` already reads every infra.% key in one query.
8. The retired midnight-UTC aggregator (`aggregate_bars_from_1m`) is still the FX/crypto derive
   path (dormant; decide: session-anchored rewrite or a comment pinning why the fallback keeps
   the old arithmetic).
9. Small items: writer-transaction boilerplate x4, `_bind_registry` seam, per-item empty-history
   config re-reads, `fetch_per_contract` window/parse-back, `_merge_windows` promotion,
   `real_bars_only_for` removal, dead `_logger`, APR bool parsing three ways, `_BP` x3, private
   cross-imports in scripts/ops/bars, `is_fresh`/`load_fresh_heads_per_tf` dead code.

## Done when

Each numbered item is applied or explicitly declined with a reason in the findings doc; the
before/after test suites stay green; nothing lands mid-backfill in the queue or write paths.
