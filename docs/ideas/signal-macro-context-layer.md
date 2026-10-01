# Macro context layer: market-wide measurements and events in one place — Idea

**Status:** Idea, not planned. Needs a rigor pass before promotion to `docs/research/`.
**Author:** Claude (Sonnet 5.5), interactive session, 2026-10-01.
**Informed by:** the owner's question of 2026-10-01; `economic_series_observation` (migration 423,
todo 480, built the same day); `docs/ideas/from-ssfi/signal-event-catalog-and-impact-system.md`
(sections 3, 5, 6); `docs/ideas/signal-political-policy-regime.md`; `docs/research/signal-temporal-atomic-primitives.md`;
todos 475 and 481. FRED release counts and dates below were read live from the FRED API on
2026-10-01.

## The idea

Things that are true of the market or economy as a whole, not of one security, are scattered today:
`macro_features` (dormant, bars-derived, keyed by a fake symbol), `kernels/macro.py` (names SPY and
TLT in code, todo 475), calendar flags (opex, quad witching), roll events, a hand-kept midterm table,
and the `rates` regime built from ETF returns (todo 481). The proposal is one layer for all of it, with
three kinds of object that each have one home:

| Kind | Example | Home | Status |
|---|---|---|---|
| Measurement series | 10-year yield, HY spread, SOFR percentile | `economic_series_observation` | built 2026-10-01 |
| Event | FOMC decision, CPI release, jobs report, auction, election | `economic_event` (not built) | idea |
| Derived measure | real-yield shock, spread percentile, funding stress, days to the next FOMC | kernels, broadcast panel columns; never stored as truth | idea |

One table for all three is the wrong shape: a series is dense numeric history, an event is a sparse
row with a schedule and an outcome, and a derived measure is cache. What unifies them is one
vocabulary (a CVR namespace for event types), one registry (UCR concepts with a market scope, no
symbol), one rule (reads are as-of), and one read surface that returns the market-wide block for a
date. The panel (S0) joins that block to every symbol, the `vix_z` pattern, never through
`market_regimes` group routing.

## Events: the shape that earns its keep

- Same catalog for past and future (event-catalog doc section 3): one row, the question is as-of.
- Convention from that doc's section 5: market-wide events carry no symbol; per-symbol events
  (dividends, halts) keep their own tables with the same column names.
- Two timestamps, not one. `occurs_at` is when it happens; `known_at` is when anyone could know the
  date. FOMC and the BLS and BEA calendars are published a year ahead, so a countdown feature is
  point in time; a backfilled date from a history feed is not, unless the lead time is declared. The
  schema records the basis (`scheduled_in_advance` or `learned_at_occurrence`), the same honesty as
  `availability_basis` on the series table.
- An outcome, when the event has one, is a measurement: a release is an event whose outcome is an
  observation in the series table. The event row points at the series; it does not copy the value.

## A cheap, free source for most of it

The FRED API (the key we already hold) lists 333 releases, including `FOMC Press Release` (101),
`Consumer Price Index` (10), `Employment Situation` (50), `Gross Domestic Product` (53), `Personal
Income and Outlays` (54), `Job Openings and Labor Turnover Survey` (192), `Unemployment Insurance
Weekly Claims Report` (180) and `H.15 Selected Interest Rates` (18). Release dates run back to 1949
(CPI, 953 dates) and 1955 (Employment Situation, 867 dates) and include scheduled future dates (next
jobs report 2026-10-02, CPI 2026-10-14). The same API serves first-release (vintage) values through
its real-time parameters, so a surprise can be measured against a rule-based expectation (the prior
print or a trailing median) without paid consensus data. Treasury auction and refunding calendars,
the election calendar and exchange holidays come from other free sources and would be additions.

## What to build, in order

1. Nothing urgent is lost by waiting: release dates and vintages can be pulled later, unlike the ICE
   spreads. Build `economic_event` with its first consumer, not ahead of one.
2. Concrete consumers already exist: the presidential-cycle spec (election dates), the quarterly and
   opex seasonality idea, a rate-direction and funding-stress macro state to replace the `rates`
   regime's ETF proxies (todo 481), and FOMC and release-day behavior as a pre-registered event study.
3. The generalized event-impact mechanism (event-catalog doc section 6) is the research tool: matched
   controls, clustered bootstrap, run through the research runner so every look is counted. Each
   event candidate is a hypothesis and gets its own pre-registered spec; the temporal-primitives
   rule applies (a coordinate spans a cycle, a flag selects a point and needs a test).
4. Derived macro measures wait for the 186 kernel work; the macro kernels move from symbol names to a
   series registry when todo 475 lands.

## Family map: who owns what

No doc is archived by this pass; each stays where it is and states its owner here.

| Topic | Owner doc | State after the 2026-10-01 refresh |
|---|---|---|
| Stored measurement series | `economic_series_observation`, todo 480 | built, backfilled, timer file not installed |
| Market-wide events and the event study | this doc; basis in `from-ssfi/signal-event-catalog-and-impact-system.md` sections 3, 5, 6 | idea; corporate-event material in the SSFI copy is SSFI-only |
| Calendar coordinates and the point-selection rule | `docs/research/signal-temporal-atomic-primitives.md` | canonical, unchanged |
| Quarterly and opex seasonality | `signal-quarterly-seasonality-opex-risk-off.md` | idea, cross-linked here |
| Policy uncertainty, divided government, presidential cycle | `signal-political-policy-regime.md` | refreshed: FRED plumbing exists, cycle section added |
| Rate and credit regime axes (the `rates` group) | todo 481 | filed: curve tier tracks the 10-year change and has the wrong sign |
| Sensitivity to a market-wide factor or event | `signal-sensitivity-regime-interaction-primitives.md`, `from-ssfi/signal-factor-sensitivity-cross-asset.md` | unchanged; consumers of this layer |
| Per-symbol external data (short volume, fails-to-deliver, dividends, halts) | separate family | not part of this layer |

## Reusable from SSFI (read 2026-10-01 at `/home/bg/dev/ssfi`)

SSFI has designed its data sources and written its methodology but collected no data (no ssfi database
exists on this host). Its `indicagent-*` research docs were written from indicagent's own code, so most
of their methods are already here (block bootstrap, embargo, BH-FDR, StepM, null-arm and e-value tests
each appear in several indicagent docs). What is worth taking:

| Item | Where in SSFI | Use here | State |
|---|---|---|---|
| Vintage keying: a revision is a new row, UPDATE and DELETE blocked | migration 040, `data-model.md` | `economic_series_observation` | applied (append-only trigger, `available_at` and basis) |
| Canonical-unit contract: a unit is a per-field declaration, never inferred from a value | `docs/foundation/data-layer.md` | the `unit` column in `economic_series_observation_coverage` (FRED's declared units, a fixed NY Fed field map, a run fails if a unit changes) | applied 2026-10-01 |
| NY Fed Markets Data API (rates, primary dealer, SOMA lending) | migrations 027 to 029, `data-sources-candidates.md` | reference rates loaded; Primary Dealer and SOMA remain | partly applied |
| Data due-diligence gate and vendor adapter boundary | `data-layer.md` (DATA-16 section) | a checklist for each new source in this layer | adopt when the next source lands |
| Sparse-flag event test: per-episode matched-control comparison with an episode-clustered bootstrap, plus the power finding (quad witching underpowered by 2 to 5 times at about 80 episodes) | `calendar-primitives.md` | the event-study mechanism; FOMC gives about 8 events a year, so set expectations before any spec | method in this doc, spec later |
| Holiday-adjacent thin trading as one curated hypothesis | `calendar-primitives.md` | a tier-1 candidate needing a stated hypothesis | idea only |
| FINRA short-sale volume, SEC fails-to-deliver, trading halts | `data-sources-candidates.md` | per-symbol and free, ETFs included; a separate table family | not started |

Not reusable for this universe: Form 4, 13F, 13D/G and XBRL (single-stock), the securities-lending
methodology notes, and the Astec lending API material.

## Cautions

- A long list of possible consumers is a reason to design the layer, not to build all of it: most
  ideas in this family have died on their first honest test (ledger), and every event feature
  multiplies the looks counted against the vintage.
- A countdown feature needs the lead-time assumption written down per event type.
- First-print values are only point in time if the vintage keying is real: use the real-time
  parameters, not the current revised history.
- Per-symbol event tables (dividends, halts, short volume) are a separate family and stay separate.
