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
8. **No chart dependency.** The instrument page's chart is a small SVG component
   (`history-chart.tsx`): the 1d close and the per-lane bar counts share one time axis and one
   crosshair, which a candlestick library does not give. Revised in slice 3 (owner asked for the
   best concept, 2026-10-26): the page is a data passport, not a price chart, so
   `lightweight-charts` was never added.

## Pages

| Page | Question it answers | Reads |
|---|---|---|
| Pipeline `/` | Is each stage fresh and passing? | one summary row per stage from the routes below |
| Data `/data` | Where is the bar data, by vendor and timeframe, and is it clean? | `ohlcv_coverage`, `ohlcv_provider_head`, `ohlcv_revision` (counts), `integrity_monitor` (latest failures), `listing_end`, `dividend_event_coverage` |
| Instruments `/instruments` | Where in the universe are the problem names? A map of every name, grouped by asset class and sector, coloured by state | `instruments`, `instrument_classification` via `current_level_name_sql()`, `listing_end_current`, `ohlcv_coverage` |
| Instrument `/instruments/[symbol]` | Is this name's history complete, which vendor holds which span, where are the holes? | `market_data_ohlcv_tradeable` (bars per session per timeframe and vendor, the 1d close), `ohlcv_coverage`, `ohlcv_restatement_flag`, `instrument_tags` |
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
3. Instruments map and the per-name data passport.
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

- Slice 2 (Data page) landed 2026-10-26 with one cached `/api/data/summary` (six sections, feed
  rows carry the Pipeline's status) and the shared TTL cache `src/api/cache.py`. Its /code-review
  findings, after the 2026-10-26 cleanup pass:
  1. OPEN. Integrity counts only rows sharing the exact max(evaluated_at); writers that commit per
     row spread a run over many timestamps, so it undercounts. The correct per-subject latest query
     (DISTINCT ON monitor, metric, subject) takes 10 s on 900k rows, 1.5 s bounded to 7 days: add
     an APR window key (next migration number from the coordinating sessions) or an index.
  2. FIXED. A header count or headline tile whose section errored shows "?", never 0; `Panel`
     takes the section's `error` and shows it in place of the table, so no page can render an
     empty-state message over a failed query.
  3. FIXED. `cached(key, ttl, compute, keep)` resolves the TTL (an APR read) on a miss only.
  4. RESOLVED differently. Sharing the pipeline snapshot would save one 10 ms query and couple
     two TTLs; instead `judged_ingest` (pipeline.py) is the one ingest judgement both pages call,
     with its query and APR reads run concurrently.
  5. FIXED. The cache keeps lock and value in one slot, evicts both, `clear()` drops both, and a
     result with a failed section is returned but not stored (the next poll retries). Unit tests
     in `tests/unit/api/test_cache.py`. `/system/units` uses it too.
  6. FIXED in slice 3 (`gather_sections`).
  7. Sticky table headers in scroll panels FIXED; asserting the failing and restatements filters
     in tests is OPEN.
  Also open from the cleanup review: a name's map state takes the newest bar across all its
  feeds, so a dead 5m feed hides behind a current 1d one (judge per feed, as `ingest_status`
  does); the history chart's partial-session shading counts weekdays as sessions (the trading
  calendar belongs in the `_lanes` query); the pipeline features stage spends 2.3 s planning
  `max(bar_ts)` over every chunk; the shared ConfigService has no TTL, so `src/api/apr.py`
  invalidates per read.
- Slice 3 (Instruments) landed 2026-10-26 as a concept change from the plan: a universe map
  and a data passport instead of a table and a candlestick chart. `/api/universe/summary` judges
  each name's one state (inactive, ended, no_data, failing, stale, current; `name_state` in
  `src/api/routes/universe.py`), `/api/universe/{symbol}` returns the passport (identity and
  eligibility, coverage ledger, bars per UTC session per lane over the full history, the 1d
  close, restatements, current tags; about 2 s and 650 kB for a 26-year name, cached per name
  and polled at `ui.dashboard.passport_refresh_seconds`). The map's legend is its filter; the table under it lists the names needing
  attention. The passport's history lanes show vendor handoffs and holes the coverage ledger
  cannot (AAPL: 1d Tradier to IBKR on 2026-10-07, derived 15m/1h stopping 2026-10-16).
- Slice 4 (Concepts) landed 2026-10-27. `/api/concepts/summary` (`src/api/routes/concepts.py`)
  returns every registry concept with the evaluation for its newest window (the window the
  lifecycle judges on), the stored pass/fail and IC guard, and its latest transition; plus the
  fresh IC store per (timeframe, regime scope, horizon) at each group's newest training window,
  with an empty state naming 186-26. The page's lifecycle matrix (domain by state) is its filter.
  Shared UI added: `SearchInput`, `pressable`, `Panel` `count`, `spaced` in `lib/utils.ts`.
  Deferred from the review: `Panel` taking a whole section envelope (`section={env}`) instead of
  source, as_of, error and empty text one by one, which touches every page.
- Slice 5 (Research) landed 2026-10-27. `/api/research/summary` (`src/api/routes/research.py`):
  looks per (vintage, kind, mode) with the charged count from the ledger's own
  `UNCHARGED_STATUSES`; every attempt with its stored headline (pre-515 rows fall back to
  `evidence.decision`; the append-only ledger cannot backfill them) and why it was refused or
  failed; the legacy `gate_evaluations` verdicts. OPEN: the attempts list has no row cap (21 rows
  today); it needs a `ui.dashboard.*` cap key in a migration numbered with the coordinating
  sessions. An attempt left `started` by a dead runner shows as unfinished with its age, not
  flagged stale.

## Out of scope

Writes of any kind from the UI (no APR edits, no promotions), authentication (the dashboard runs on
localhost), mobile layout beyond not breaking, and any live feed until phase 188.
