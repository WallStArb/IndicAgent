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

## Data layer services (phase 185)

| Service | Role |
|---|---|
| `bar_derivation.py` | The one writer of canonical 1d (rule d2-v2, source from `bar_source_policy`) and the derived 15m/1h grid |
| `bar_scrub.py` | Scrub rules; flags in `bar_quality_flag`, run by the daily stage |
| `bar_reconciliation_audit.py` | D7: integrity findings and the `bar_integrity` verdicts promotion reads |
| `ohlcv_observation_writer.py` | D1 writer (`ohlcv_request`, `ohlcv_observation`) for every fetch path |
| `intraday_raw_archive.py` | Frozen archive of vendor 15m/1h answers |
| `listing_venue_writer.py` | D6 listing venue spans |
| `dividend_event_writer.py` | Dividend events (Yahoo) |

The IBKR history fetcher is a script (`scripts/infrastructure/backfill/ibkr_history_fetcher.py`)
run by `indicagent-ibkr-history-fetcher.timer`; it and the Tradier daily timer are disabled by the
owner until plan 189-10.

## Removed

The v2.x I1-I7 signal path and the I8 AI stack (signal tracker and writers, swarm, narrative, LLM
writer and the rest) were removed in plan 185-45; the pre-removal tree is the local git tag
`archive/v2x-ai-stack-2026-10`. What still depends on v2.x code (`feature_vector_pipeline.py`, the
API's signal routes, the ML batch chain) is listed in todo 509.
