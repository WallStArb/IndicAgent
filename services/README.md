# IndicAgent services

Daemon and batch entry points (Ring 2). Each `services/<concept>.py` runs as
`indicagent-<concept>.service`; the unit files live in `production/systemd/`, not here.

## Where the truth is

- Registry and DAG order: `_DAG_ORDER` and `_AGENT_ID_TO_UNIT` in `services/service_auditor.py`.
  A new service is added there and seeds its `alert.lag.<unit>` APR key.
- Live state: `systemctl list-units --all 'indicagent-*'` and `systemctl list-timers | grep indicagent`.
  Batch units (D7 audit, dividend writer, ML chain, roll batch) are `inactive (dead)` between runs,
  which is correct.
- Who writes what: `docs/foundation/canonical-truth-registry.md`.
- Commands: `docs/reference/cheatsheet.md`.

## Data layer services (phases 185 and 191)

| Service | Role |
|---|---|
| `ohlcv_raw_writer.py` | The one writer of `ohlcv_raw` (every vendor answer, last-wins by serve time) and its `ohlcv_revision` log (phase 191) |
| `ohlcv_ingress_contract.py` | The raw-first ingress contract every fetch path writes through (`ohlcv_load` ledger rows) |
| `ohlcv_request_writer.py` | The fetch ledger writer (`ohlcv_request`) |
| `bar_derivation.py` | The one writer of canonical 1d (rule d2-v3 over `ohlcv_raw` in the stored canonical, d2-v4 in code; source from `bar_source_policy_current`) and the derived 15m/1h grid |
| `bar_selection.py` | The canonical writer for 5m, 1m and 4h: a per-session selection from `ohlcv_raw` by policy, called by the ingress contract after each raw write; non-trivial choices in `bar_session_choice` |
| `bar_load.py` | The load engine the Alpaca capture writes through (`ops_bar_nightly.py`, `ops_bar_load.py`) |
| `bar_scrub.py` | Scrub rules; flags in `bar_quality_flag`, run by the daily stage |
| `bar_reconciliation_audit.py` | D7: integrity findings and the `bar_integrity` verdicts promotion reads |
| `listing_venue_writer.py` | D6 listing venue spans |
| `dividend_event_writer.py` | Dividend events (Yahoo) |

The IBKR history fetcher is a script (`scripts/infrastructure/backfill/ohlcv_history_fetcher.py`)
run by `indicagent-ibkr-history-fetcher.timer`; the Alpaca capture is
`scripts/ops/bars/ops_bar_nightly.py`, run by `indicagent-alpaca-nightly.timer` (04:40 UTC), and
`indicagent-bar-derivation-grid.timer` (05:45 UTC) derives the grid after it. The retired
daily vendor's loader and units were deleted in plan 185-48 (the account is not funded) and its
bar rows in plan 191-20.

## Removed

The v2.x I1-I7 signal path and the I8 AI stack (signal tracker and writers, swarm, narrative, LLM
writer and the rest) were removed in plan 185-45; the pre-removal tree is the local git tag
`archive/v2x-ai-stack-2026-10`. What still depends on v2.x code (`feature_vector_pipeline.py`, the
API's signal routes, the ML batch chain) is listed in todo 509.
