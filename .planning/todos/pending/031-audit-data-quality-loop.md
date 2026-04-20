---
created: 2026-04-20
title: Audit data-quality loop (bar_auditor, gap detection, reconciliation)
area: data-pipeline
files:
  - services/bar_auditor_agent.py
  - services/gap_fill_service.py  # (if still active — was archived; check current location)
  - src/core/schemas/market_events.py  # BarGapRequest
---

## Scope

Audit the self-healing data-quality feedback loop: how missing bars are detected, requested, filled, and proven filled. Also: reconciliation between the 5s-RTB-aggregated 1m stream and IBKR's official keepUpToDate bars.

## Areas to review

1. **Gap detection logic** — timing (how long after an expected bar-close before a gap is declared?), false positives during market-closed windows, handling of trading breaks (TSE lunch, etc.), handling of holidays.
2. **Gap request → fulfillment feedback loop** — does bar_auditor confirm the gap was actually filled, or does it just emit the `BarGapRequest` and move on? If no confirmation, gaps can silently recur.
3. **Official-vs-RTB reconciliation** — with two streams of 1m bars (keepUpToDate "official" + aggregated RTB for crypto only), how/whether we reconcile OHLC differences. If the two disagree, which wins? Is the discrepancy logged?
4. **Backfill idempotency on restart** — when `indicagent-ibkr-provider` restarts (e.g. on a futures roll), does bar_auditor re-request already-filled gaps?
5. **Gap coverage for intelligence_features and signal_ledger** — bar-level gap filling is necessary but not sufficient; a filled 1m bar that arrived *after* the intelligence pipeline ran for that minute won't have features. Is there a "backfill features too" path? (Historical backfill scripts exist — verify they run from the same gap signal or a separate mechanism.)
6. **Continuous-contract handoff at roll** — during futures roll, the 1m bar stream switches contracts. Is there a window where bar_auditor sees "gap" in the old contract that's actually end-of-life, and false-triggers?

## Method

Use Claude Opus 4.7 for structured read-through. Produce a prioritized findings list. Pay particular attention to silent-failure patterns — gap detectors that suppress errors, fill paths that swallow exceptions, reconciliation that logs only on match.

## Related

- Ingestion-edge audit completed 2026-04-20 (session log)
- Kafka→DB writer audit: todo 030
- Signal lifecycle tracker violates compute→Kafka→writer DAG pattern — see `docs/plans/2026-04-10-pipeline-health-fixes-design.md`
