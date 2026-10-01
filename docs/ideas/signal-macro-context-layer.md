# Macro context layer: market-wide series and events, point in time by measurement - Idea

**Status:** Idea, design refined 2026-10-01 by a council pass (below). The series store exists
(`economic_series_observation`, todo 480); the point-in-time corrections it needs are todo 482, deferred
to the start of phase 184 B8.
Needs a rigor pass before promotion to `docs/research/`.
**Author:** Claude (Opus 5.5), interactive session, 2026-10-01; first draft by Claude (Sonnet 5.5)
the same day.
**Informed by:** FRED and ALFRED queries and checks against the stored table on 2026-10-01 (every
number below was measured then); `docs/ideas/from-ssfi/signal-event-catalog-and-impact-system.md`
(sections 3, 5, 6); `/home/bg/dev/ssfi` (migration 040, `docs/foundation/data-layer.md`,
`docs/research/calendar-primitives.md`); `docs/research/signal-temporal-atomic-primitives.md`;
`src/intelligence/research/snapshot.py`; todos 475, 480, 481.

## The problem

Facts about the market or the economy as a whole (rates, spreads, funding, releases, policy dates)
are useful only as conditioning inputs, and only if every value is used no earlier than it could have
been known. The dominant risk in this layer is not a missing feature; it is a value that arrives in a
backtest days or weeks before it existed. Everything below is organized around that.

## What the measurements showed

| Check (2026-10-01) | Result | Consequence |
|---|---|---|
| CPI January 2024 first release (ALFRED) | 2024-02-13 | a "1 business day after the observation date" rule puts it 2024-01-03: six weeks of lookahead. An assumed lag must never touch a non-daily series |
| `THREEFYTP10` first release and revisions | 2024-01-02 value first published 2024-01-09 (weekly release); history revised 2024-08-12 | the stored rows are about a week early and hold revised values: a lookahead present in our table today |
| Daily H.15 and Moody's series, first-release lag over Q1 2024 (61 days each) | `DGS10`, `DFII10`: 1 day (49), 3 (10), 4 (2). `BAA10Y`: 1 (47), 2 (1), 3 (10), 4 (3) | the assumed rule is right on most days and early on holiday weekends and on `BAA10Y`'s two-day days; measurement removes the guess |
| ICE spread first release | same calendar day as the observation | conservative under the current rule |
| SOFR, FRED against the NY Fed | 2,122 common days, 0 value mismatches; the NY Fed has 2018-04-02 (first day) only | two sources reconcile exactly: usable as a standing check |
| Identity `T10Y2Y = DGS10 - DGS2` | 3 days off, worst 2 bp; 1 day with the slope but a missing leg | small, real defects: audit them, never patch values |

## Requirements

Each one exists because one of the failures above would otherwise pass silently.

1. **Availability is measured, not assumed.** A row's `available_at` comes from the publisher's own
   record where one exists: ALFRED's release records (first-release dates and revision dates). ALFRED
   calls these vintages; in this project `vintage` means a research data span (glossary), so this doc
   says release record. An assumed rule
   is allowed only where no record exists (the NY Fed today), is labeled as such, and is never applied
   to a series whose observation date is a reference period (monthly, weekly, quarterly).
2. **Revisions are rows.** The first published value is the first row; every later revision is a new
   row with its own `available_at`. The current value is never written backwards over history.
3. **One store, one writer, append-only.** UPDATE and DELETE are blocked in the database. A research
   snapshot is the table filtered on `available_at <= K` for a knowledge cutoff K, so a snapshot is
   reproducible bit for bit by construction (the `determinism` invariant at no extra cost).
4. **Declared units and declared publication rules.** Units come from the provider (FRED metadata,
   a fixed NY Fed field map) and a run fails if one changes (in place since 2026-10-01). A source with
   no release record declares its publication time (the NY Fed: 08:00 New York time on the next
   business day) and forward fetches verify it.
5. **Staleness is explicit.** An as-of read returns the value and its age. Beyond a declared maximum
   age per series the value is missing, never carried (`no_fill`). An outage at the source must show
   up as missing data, not as a flat line.
6. **Every series has a role and a consumer, stated before its predictive value is looked at.** A
   series picked because it is in the news is a look at the vintage and is counted.
7. **Checks are standing, not one-off.** Cross-source agreement (SOFR, EFFR), identities (10s2s), and
   gaps against the expected publication calendar run on every load and are reported, never repaired.

## Deleted from the first draft

- **The `economic_event` table.** An event needs no second store:
  - A release is the availability of its observation: CPI for August is a row with observation date
    2026-08-01 and `available_at` at its release. The release time is already in the table.
  - A scheduled date known in advance is a schedule series in the same table: observation date = the
    scheduled day, `available_at` = when the schedule was published, value 1. A cancellation or a
    move is a new row (value 0 for the old date, 1 for the new one). Append-only covers it.
  - So the event layer is a set of series, read with the same as-of rule. One mechanism instead of
    two.
- **The `revision` field in the APR source list.** It is an assertion; release records measure it.
- **The assumed lag for FRED series.** Replaced by first-release dates. It stays only for sources
  without release records, labeled, and becomes a measured rule as forward fetches accumulate.
- **Stored derived measures.** Real-yield shock, spread percentile, funding stress and days-to-FOMC are
  pure kernels over as-of reads, computed in the panel and never persisted as truth.

## The model, after deletion

One table, three times per row, nothing else:

| Column | Meaning |
|---|---|
| `observation_date` | what the value is about: a day for rates, a reference period for releases, the scheduled day for a schedule |
| `available_at` | the earliest moment anyone could have known this value |
| `fetched_at` | when we recorded it |

Per-series facts are stored once, in the series row (today `economic_series_observation_coverage`; it is the
series registry in all but name): unit, kind (`daily_level`, `reference_period`, `schedule`),
availability basis (`release_record` or `declared_rule`), covered span. The APR list says what to collect; the
registry says what each series is.

## Architecture: components, one direction, reuse first

### The DAG

```
            (one job, one direction, no cycles; Kafka is not involved: this is batch data)

 APR infra.economic_series.sources ──┐
                                     v
 EconomicSource adapters ──> plan_rows ──> EconomicSeriesWriter ──> economic_series_observation
 (FredSource, NyFedSource:    (pure:        (the only writer;         (append-only, trigger)
  fetch + normalize, I/O)     what to       serial transactions)      + _coverage (series registry)
                              append)                                        │
                                                                             v
                       S0 economic block (phase 184 B8): read-only, decision-time join, age,
                       knowledge cutoff, hashed into the panel manifest
                                                                             │
                                                                             v
                       kernels (pure): derived macro measures as broadcast columns
                                                                             │
                                                                             v
                       families, combiner, book test (conditioning inputs only)
```

Each node does one thing:

| Node | Does | Does not | Where |
|---|---|---|---|
| `EconomicSource` adapter | fetch one entry, parse, declare units | decide availability, write, know other sources | `src/providers/fred.py`, `nyfed.py`, contract in `economic_source.py` |
| `get_json` | one JSON GET with retries and secret redaction | know any source | `src/core/http_json.py` (Ring 0, reusable by any future source) |
| `plan_rows` | decide which rows to append and with what availability time (pure) | I/O | `services/economic_series_writer.py` |
| `EconomicSeriesWriter` | persist, coverage, unit guard; later the standing audits | fetch logic, source branching | same |
| S0 economic block | the as-of join on decision time | write anything | phase 184 B8 |
| kernels | derived measures over aligned arrays (pure) | read Postgres | the 186 kernel registry |

### Reuse, not reinvention

| Need | Reused component |
|---|---|
| Batch lifecycle, pool, tracing, `job_completed_total` | `BaseBatch` (`src/core/agent/base_batch.py`) |
| Retries with backoff and jitter | `retry_with_backoff` (`src/core/retry_utils.py`) through `get_json` |
| Tunable values | APR (`infra.economic_series.*`) via `load_apr_dict_async` |
| Session and holiday calendars (todo 482's declared rule) | `src/core/market_calendar.py` (`pandas_market_calendars`; a bond-market calendar, not the exchange one) |
| As-of alignment to the panel clock | phase 184's causal `align` node; no second join |
| Derived measures | the 186 kernel registry; no bespoke builder |
| Snapshot hashing | S0's content-hashed panel manifest, as dividends already do |

A new source is a module implementing `EconomicSource` (`validate`, `fetch`) plus one line in the
writer's registry. Nothing in the writer, the table or the reader branches on a source name, which is
the `asset_agnostic` rule applied to sources.

### Async model

- **Fetches overlap, writes do not.** One `httpx.AsyncClient` (one connection pool) serves the run;
  an `asyncio.Semaphore` caps concurrent fetches at `infra.economic_series.fetch_concurrency` (FRED
  allows about 120 requests a minute); independent requests for one entry (FRED's data and its unit)
  run together.
- **One writer, one transaction at a time.** Completed fetches are taken with `asyncio.as_completed`
  and written serially, so the table never sees two writers and a slow source never blocks a fast
  one's write. Same rule as the batch services' "workers compute, main writes" pattern.
- **Failures are per entry or per series, collected, and the run fails at the end.** A 4xx is never
  retried; transport errors and 5xx are, up to `infra.economic_series.http_max_attempts`.
- Measured 2026-10-01: a full run of 49 series (complete history refetched and diffed) takes 2.7 s
  end to end.

### Ring placement

`src/core/http_json.py` is Ring 0 (portable, no domain words). Sources live in `src/providers/`. The
writer is a Ring 2 service. The S0 block and kernels are Ring 1 research code. No arrow points back.

## Alignment to the panel clock

The join is on decision time, never on the observation date. A panel row for session t is decided at
the open of t+1 (Invariant 1: features at t, entry at the next open), so it may use an economic series
row only if `available_at` is at or before that open. Worked example: the 10-year yield for Monday is
first released on Tuesday (FRED records the date, not the time), so its availability time is
Wednesday 00:00 UTC and the first row that may use it is Tuesday's, decided at Wednesday's open. A
join on observation date would use it at Monday's row, decided at Tuesday's open: a day early.

- **Age.** Each joined value carries its age in sessions. A declared maximum age per series kind (APR;
  initial values to be set with todo 482) turns an older value into missing.
- **Calendars differ.** Rates follow the bond-market calendar: on Columbus Day and Veterans Day
  equities trade and no rate is published, so the age grows by one, which is correct and not a gap.
  The NY Fed's declared rule uses the bond-market calendar, not the exchange calendar.
- **One mechanism.** This is the same causal alignment phase 184 builds for off-clock bar inputs
  (B3, the `align` node). Economic series are one more off-clock input, not a second join.

## Hidden biases and edge cases, each with its guard

| Risk | How it fails silently | Guard |
|---|---|---|
| Release lag | a monthly value is used weeks before release | requirement 1; never an assumed lag on a reference-period series |
| Revisions | today's revised value is used for an old date | requirement 2 |
| Time of day | a release record carries a date, not a time, and the value may post late that day; a daily bar decided at the close cannot see it | `available_at` is the end (next 00:00 UTC) of the first-release date; the NY Fed uses its declared 08:00 rule |
| Holidays | an assumed business-day rule is a day early around holidays | release records for FRED; for the NY Fed, a declared calendar checked by forward fetches |
| Stale carry | a source outage reads as an unchanged value | requirement 5 |
| Truncated history | the ICE spreads are served for 3 years only; earlier days are filled from a proxy | days outside coverage are unknown; never back-filled from another series |
| Series selection | series chosen because they are topical | requirement 6; every chosen series counts as a look |
| Too few episodes | crash-like and event conditioning rests on about five independent episodes since 2006; FOMC gives about 8 events a year | every spec states its power before running; the sparse-flag test (matched controls, episode-clustered bootstrap) from `calendar-primitives.md` |
| Unit or scale error | percent read as a fraction | declared units, a run fails on change |
| Source disagreement | one source drifts or restates | requirement 7 |
| Schedule hindsight | a historical countdown uses a schedule nobody had yet | schedule rows need a publication date; where history lacks one, the lead time is declared per event type and the spec must survive the shift test below |

**Shift test.** Every result that uses this layer is re-run with every `available_at` moved one
session later. A result that changes materially was depending on timing at the edge of knowability and
is not trusted. It is cheap, mechanical, and catches every residual timing error the table above
missed.

## The four design questions

1. **10x volume:** 49 series to 500 is a few hundred requests a day and tens of megabytes; full
   history is refetched and diffed per series. ALFRED caps a request at 2,000 release dates, so long
   daily series are fetched in windows.
2. **Silent failure:** the table above; the shift test is the backstop.
3. **DAG:** one direction, one writer, compute separate from persistence (diagram above).
4. **Manual step eliminated:** none of the macro context is hand-maintained except declared
   publication rules and lead times, which forward fetches verify.

## Build order and where each piece lands

No new phase. Each piece has a natural owner:

| Piece | Lands in | Gate |
|---|---|---|
| Release-record reload, audits, CVR namespaces | todo 482 (deferred) | the start of phase 184 B8; nothing reads the table before then, so it costs the same then as now. Until then no monthly or weekly FRED series is added |
| Daily timer installed and enabled | operator step (sudo), any time | not urgent: FRED serves the ICE spreads for a trailing three years and everything since 2023-10 is stored; daily collection adds measured `fetch` availability times |
| S0 economic block: decision-time join, age, maximum age, knowledge cutoff, hashed into the manifest; the shift test | phase 184 (scope item B8, beside the `align` node) | 482 done |
| Derived macro measures as kernels | phase 184 B2 (`kernel_source` on the 186 registry); todo 475 moves the macro kernels to the series registry | 186 kernel registry |
| Rates regime curve from the measured slope | todo 481, with the 186 regime rebuild | null-arm control |
| Schedule series (FOMC, CPI, jobs report from FRED's release calendar: 333 releases, CPI dates since 1949, jobs report since 1955, future dates included) and the event study | the first pre-registered spec that needs them, through the phase 187 runner | a written spec with its power stated |
| NY Fed Primary Dealer and SOMA lending, Tier 2 FRED series | todo 480 (deferred) | a named consumer; monthly and weekly series only after 482 |

If the 184 work grows past one scope item, split it then; it does not justify a phase on its own today.

## Family map: who owns what

No doc is archived; each states its owner here.

| Topic | Owner | State |
|---|---|---|
| Stored series and their point-in-time rules | `economic_series_observation`, todos 480 and 482 | built; corrections pending |
| Market-wide events and the event study | this doc; basis in the SSFI event-catalog copy, sections 3, 5, 6 | idea; events are schedule series |
| Calendar coordinates and the point-selection rule | `docs/research/signal-temporal-atomic-primitives.md` | canonical |
| Quarterly and opex seasonality | `signal-quarterly-seasonality-opex-risk-off.md` | idea |
| Policy uncertainty, divided government, presidential cycle | `signal-political-policy-regime.md` | idea, refreshed 2026-10-01 |
| Rate and credit regime axes | todo 481 | curve tier tracks the 10-year change with an inverted sign |
| Sensitivity to market-wide factors or events | `signal-sensitivity-regime-interaction-primitives.md`, `from-ssfi/signal-factor-sensitivity-cross-asset.md` | consumers of this layer |
| `macro_features` / `macro_analyzer` | the dormant streaming path | no reader; if streaming returns, it computes from the same kernels rather than keep a second macro home |
| Per-symbol external data (short volume, fails-to-deliver, dividends, halts) | separate family | not this layer |

## Reused from SSFI

SSFI has designed its sources and written its methods but collected no data. Its `indicagent-*`
methodology docs were written from indicagent's own code, so their methods are already here.

| Item | Use here | State |
|---|---|---|
| Revision keying, append-only enforced in the database (migration 040) | requirements 2 and 3 | applied; vintages themselves are todo 482 |
| Canonical-unit contract (`data-layer.md`) | requirement 4 | applied 2026-10-01 |
| NY Fed Markets Data API | reference rates loaded; Primary Dealer and SOMA lending remain | partly applied |
| Data due-diligence gate, vendor adapter boundary (`data-layer.md`) | checklist for the next source | adopt then |
| Sparse-flag event test and its power warning (`calendar-primitives.md`) | the event study | adopt with the first event spec |
| FINRA short volume, fails-to-deliver, halts | per-symbol family | not started |

Not reusable here: single-stock filings (Form 4, 13F, 13D/G, XBRL) and the securities-lending material.

## Cautions

- This layer supplies conditioning inputs. It is not evidence of an edge, and the questions that
  prompted it (a crash after an all-time high, the midterm effect) are narratives until a
  pre-registered spec says otherwise.
- Most ideas in this family have died on their first honest test (ledger). Each new series or event
  is a look counted against the vintage.
