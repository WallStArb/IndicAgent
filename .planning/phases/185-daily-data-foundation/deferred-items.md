# Phase 185 deferred items

Out-of-scope discoveries logged during execution (executor scope boundary). Not fixed
in the plan that found them; each needs its own change with its own review.

| Found | Item | Why deferred | Follow-up |
|---|---|---|---|
| 185-09 (2026-09-28) | `services/backfill_feature_factory.py` calls `fetch_historical_bars` without the `ibkr_history_stream` lease (allow-listed in `tests/unit/test_ibkr_history_lease_boundary.py`) | Corpus feature backfill is an ic_engine-adjacent service; wiring the lease through it changes a live batch path and needs its own runbook, not a rider on plan 09 | Hold the lease (bulk tier) around its fetch loop before its next corpus run; until then it contends lease-free |
| 185-09 (2026-09-28) | `scripts/infrastructure/backfill/infrastructure_ibkr_chunk_and_rate_limit_probe.py` fetches lease-free (allow-listed) | One-off diagnostic; no scheduled runs | Take the lease at bulk tier or delete the script when its measurements are superseded by D1 data |
| 185-09 (2026-09-28) | `services/dividend_event_writer.py` fetched TRADES/ADJUSTED_LAST lease-free (allow-listed) | RESOLVED 185-21 (2026-10-02): the IBKR branch reads D1, the fetch and its allow-list entry are gone | Done |
| 185-21 (2026-10-02) | 8 names (DE, VUG, BEN, MDLZ, STLD, VTR, ZBH, SAFE) carry interim-era `dividend_events` ibkr rows the D1 series does not reproduce; 16 of 18 sampled dates have no Yahoo corroboration either (`vanished_ex_dates` guard rolled them back loudly) | Deleting stored rows and re-deriving is a data-mutation change with its own review, outside plan 21's I/O-swap scope | Delete the uncorroborated interim rows for the 8 names, rerun the writer for them from the plan 15 run; report in `docs/research/ibkr-dividend-route-validation.md` |
| 185-21 (2026-10-02) | CBC's D1 capture holds negative ADJUSTED_LAST closes (2009-07-06, 2020-08-17..19; provider defect, kept as observations); CLBK has no TRADES observations in the plan 15 run | Raw observations are permanent (D-09); the writer correctly refuses; refetching needs the lease and plan 14's late-name resolution | Re-fetch both windows when the 42 late names are worked; CBC and CLBK stay without IBKR-derived dividends until then |
