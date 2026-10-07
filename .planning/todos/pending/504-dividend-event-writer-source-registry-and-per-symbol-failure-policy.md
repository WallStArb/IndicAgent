---
status: pending
priority: P2
filed: 2026-10-07
source: owner request 2026-10-07 after indicagent-dividend-event-writer@yahoo failed on PSKY (Yahoo NaN close on 2026-09-15, a dividend day)
---

# dividend_event_writer: sources are a registry, one bad symbol does not fail the run

## What

The process is "get dividend events for a name"; Yahoo and the IBKR adjusted-last ratio are data vehicles. Today the vehicle is hard-coded in `services/dividend_event_writer.py`:

1. Source identity leaks into the logic: `SOURCE_IBKR`/`SOURCE_YAHOO`, `_CLI_SOURCES`, `if source == SOURCE_YAHOO` branches in the fetch path, `reconcile(ibkr, yahoo_events, ...)` with named parameters, `Reconciliation.ibkr_holes`/`yahoo_holes`, and metric outcomes named per vendor. A third source (a paid dividend feed, a corporate-action table from the broker) means editing the reconciliation, the dataclass and the metrics.
2. One unusable symbol fails the whole unit. After all symbols are processed `execute` raises `RuntimeError(... failures ...)`, so the systemd unit is red every night until the vendor fixes one name (PSKY since 2026-10-06). The loud-crash rule is right for a wrong answer; here the writer already refuses to write the bad name, so the failure carries no extra safety and hides new failures behind an old one.

## Design

- A `DividendSource` protocol (name, `fetch(symbol) -> Derivation`, examined span) and a registry keyed by name; the CLI `--sources` choices come from the registry. The vendor modules stay in `src/providers/` and know nothing of reconciliation.
- Reconciliation is pairwise over any registered sources: one primary, the others compared to it; outputs are `holes[source]` and `disagreements`, not vendor-named fields. Metric outcome labels carry the source name as a label value.
- Per-symbol failure policy: a failed (symbol, source) pair is recorded (log, a `failed` outcome counter, and the symbol's coverage stays unextended so dividends are unknown, never zero, per the CLAUDE.md dividend rule), and the run fails only when the failed share exceeds an APR threshold (`threshold.dividend.max_failed_symbol_share`, seeded small) or the same pair has failed N consecutive runs (alert, not unit failure). Needs a Grafana rule on the failed counter so a persistent failure is still loud.
- The failing-name decision needs the owner: whether any failed name should block promotion or total-return specs that touch it (the coverage gap already excludes it from `panel.total_return`; confirm).

## Done when

A new source is added by one registry entry plus its provider function with no change to `reconcile`, the dataclass or the metrics; the PSKY case produces a counted, alerting, non-fatal failure; tests cover the registry, pairwise reconciliation with 3 sources, and the threshold.
