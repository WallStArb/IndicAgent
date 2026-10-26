# Dashboard for v3.5: a pipeline cockpit, one page per DAG stage

Status: design, decided in session (owner asked 2026-10-26 to reimagine the dashboard for the new
concepts and to keep going without checkpoints; every call below is open to override)
Author: Claude (session 2026-10-26)
Informed by: `docs/plans/2026-09-26-unified-research-to-production-design.md` (the v3.5 DAG and
invariants), `.planning/ROADMAP.md` phases 185-190, todo 509 (v2.x surface deleted 2026-10-26)

## Problem

The dashboard was built for the v2.x path: a trading terminal of per-symbol cards showing I1-I7
intelligence tiers and I7 signals, fed by a Kafka-to-SSE bridge. Todo 509 deleted the signal and
AI surfaces. What is left still renders the I1-I7 tier panels (structure, context, pattern,
smart money, confluence), whose producers were removed in plan 185-45, over a streaming path that
is dormant: today's data arrives by nightly batch. None of the v3.5 concepts (vendor capture,
coverage, integrity, the feature rebuild, IC term structure, the concept registry, the research
ledger, books) has a view. The operator answers "is the pipeline healthy, where is the data, what
has research concluded" from psql and logs.

## What the dashboard is for

An operator and research cockpit for the v3.5 pipeline, read-only, organised by the DAG:

```
ingest (vendors -> ohlcv_raw -> market_data_ohlcv) -> feature (feature_vectors, market_regimes)
  -> measure (IC term structure, concept registry) -> research (research_run ledger)
  -> book (frozen books, forward runner; phase 188) -> capital
```

Success: for each stage the operator sees, without a query, whether it is fresh, complete and
passing its checks, and can drill from a summary number to the rows behind it. It is not a
trading terminal; there is no live feed and no book to trade until phase 188.

## Decisions

1. **Organise by DAG stage, not by symbol.** The old card-per-symbol layout assumed a live signal
   per instrument. The v3.5 questions are per stage (is ingest current, is the rebuild complete,
   what did the last runs conclude), with per-symbol detail one click down. Pages: Pipeline (home),
   Data, Instruments (and one page per symbol), Concepts, Research, Books, System.
2. **Retire the trading dashboard and the SSE bridge.** `trading-dashboard.tsx`, the tier panels,
   `use-market-stream.ts`, `src/api/routes/sse.py`, the API's Kafka consumer and
   `socket.io-client` go. Their data either has no producer or is a v2.x tier. When streaming
   returns with the forward runner (phase 188), it gets a purpose-built feed for positions, not
   this bridge. (Musk step 2: delete before rebuilding.)
3. **Batch reads over REST, polled.** Every page reads read-only FastAPI routes and refreshes on an
   interval (default 60 s, APR `ui.dashboard.refresh_seconds`). One small client hook
   (`useApi(path, refreshMs)`); no SWR or query library for six pages.
4. **Lineage on every number.** Each route returns `{as_of, source, rows}`: `source` names the
   table or view read and `as_of` the newest timestamp in it (or the query time for a live state).
   The page shows both beside the figure. This is the `lineage` invariant applied to the UI: no
   number without the rows it came from.
5. **The API reads, never writes, and never computes conclusions.** Routes are thin SQL over the
   tables their stage owns (`single_writer` stays intact: the dashboard is a reader). A verdict,
   an IC or a pass/fail shown in the UI is one a writer already stored; the browser does not
   recompute statistics. Thresholds the UI applies (stale after N hours, row caps) are APR
   `ui.dashboard.*` keys.
6. **Compute and measurement read the tradeable view.** Bar charts read
   `market_data_ohlcv_tradeable`, never the raw table (CLAUDE.md boundary test applies to
   `src/api/`).
7. **Honest empty states.** A stage with no writer yet (books, capital) shows what will populate it
   and which phase builds it, not a blank card or demo data. `use-demo-data.ts` is deleted.
8. **One chart dependency.** OHLC bars on the instrument page use `lightweight-charts`
   (Apache-2.0, canvas, about 45 kB); sparklines stay the existing SVG component.

## Pages

| Page | Question it answers | Reads |
|---|---|---|
| Pipeline `/` | Is each stage fresh and passing? | one summary row per stage from the routes below |
| Data `/data` | Where is the bar data, by vendor and timeframe, and is it clean? | `ohlcv_coverage`, `ohlcv_provider_head`, `ohlcv_revision` (counts), `integrity_monitor` (latest failures), `listing_end`, `dividend_event_coverage` |
| Instruments `/instruments` | What is in the universe and in what state? | `instruments`, `instrument_classification` via `current_level_name_sql()`, `listing_end`, coverage per symbol |
| Instrument `/instruments/[symbol]` | What do this name's bars, coverage and regimes look like? | `market_data_ohlcv_tradeable`, `ohlcv_coverage`, `market_regimes` |
| Concepts `/concepts` | Which concepts exist, in what lifecycle state, with what measured IC? | `concept_registry`, `concept_evaluation`, `feature_ic_scores_v2` (empty until the 186-26 rebuild; empty state says so) |
| Research `/research` | What has been tested, what did it conclude, how many looks are spent? | `research_run` (status, decision, gross Sharpe, sessions, span), `gate_evaluations` |
| Books `/books` | Which books are frozen and how are they doing forward? | empty state until phase 188 (`BookTracker`, `BookPositionWriter`) |
| System `/system` | Are the services and timers healthy? | `systemctl` state via the service auditor's registry, `job_completed_total`, `dlq_events` (recent), Grafana links |

## API

New read-only modules under `src/api/routes/`: `pipeline.py`, `data.py`, `instruments.py` (the
existing module grows a detail route), `concepts.py`, `research.py`, `system.py`. Each handler is
one query (or a small fixed set), returns the `{as_of, source, rows}` envelope, and caps rows by
an APR key. `/api/pipeline/summary` composes the stage summaries from the same query functions the
stage routes use, so the home page and the stage pages cannot disagree. `sse.py` and the Kafka
consumer in `main.py` are deleted.

## Testing

- Each route has a unit test against the repo's fake-connection pattern (`tests/unit/api/`) that
  pins the SQL's source table and the envelope shape; the route smoke test covers every GET.
- A guard test lists every `/api/...` path the dashboard fetches (scanned from
  `dashboard/src`) and asserts each is a registered GET route, so the UI cannot call a route that
  does not exist (the 509 cleanup found the old UI polling deleted routes).
- `tsc --noEmit` and `next build` pass for each slice; `market_data_ohlcv` boundary test stays
  green (the API reads the tradeable view).

## Slices

1. Shell, navigation, Pipeline home, System page; delete the trading dashboard, tier panels, SSE
   bridge, `use-market-stream.ts`, `use-demo-data.ts` and `socket.io-client`.
2. Data page.
3. Instruments list and instrument page (adds `lightweight-charts`).
4. Concepts page.
5. Research page.
6. Books page (empty state now; real content with phase 188).

Each slice lands as its own commit with its API routes, tests and pages, after /simplify and
/code-review.

Progress:

- Slice 1 DONE 2026-10-26 (`46358224c`). The shared envelope is `src/api/envelope.py`
  (extras go in `meta`); stage status is judged per ingest feed with
  `ui.dashboard.ingest_failing_fraction`; APR values are re-read per computation (the shared
  ConfigService caches forever); `/api/pipeline/config` serves the poll interval; the UI's
  reusable base is `useApi` (paused while hidden), `Panel`, `RowsTable`, `StatusChip` and
  `Lineage` in `dashboard/src/components/cockpit.tsx`. Deferred: the route smoke test still
  lists routers by hand (could derive from `app.openapi()` like the dashboard path guard).

## Out of scope

Writes of any kind from the UI (no APR edits, no promotions), authentication (the dashboard runs on
localhost), mobile layout beyond not breaking, and any live feed until phase 188.
