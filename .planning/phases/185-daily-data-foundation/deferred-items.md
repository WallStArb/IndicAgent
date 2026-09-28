# Phase 185 deferred items

Out-of-scope discoveries logged during execution (executor scope boundary). Not fixed
in the plan that found them; each needs its own change with its own review.

| Found | Item | Why deferred | Follow-up |
|---|---|---|---|
| 185-09 (2026-09-28) | `services/backfill_feature_factory.py` calls `fetch_historical_bars` without the `ibkr_history_stream` lease (allow-listed in `tests/unit/test_ibkr_history_lease_boundary.py`) | Corpus feature backfill is an ic_engine-adjacent service; wiring the lease through it changes a live batch path and needs its own runbook, not a rider on plan 09 | Hold the lease (bulk tier) around its fetch loop before its next corpus run; until then it contends lease-free |
| 185-09 (2026-09-28) | `scripts/infrastructure/backfill/infrastructure_ibkr_chunk_and_rate_limit_probe.py` fetches lease-free (allow-listed) | One-off diagnostic; no scheduled runs | Take the lease at bulk tier or delete the script when its measurements are superseded by D1 data |
| 185-09 (2026-09-28) | `services/dividend_event_writer.py` fetches TRADES/ADJUSTED_LAST lease-free (allow-listed) | Plan 185-15 (D5) already swaps its IBKR branch to D1 reads, which removes the fetch entirely | Allow-list entry self-expires when 185-15 lands |
