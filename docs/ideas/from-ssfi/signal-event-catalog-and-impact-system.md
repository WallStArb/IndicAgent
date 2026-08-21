# Event Catalog & Impact-Measurement System — Idea

> **Copied from SSFI** (`docs/research/signal-event-catalog-and-impact-system.md`,
> 2026-08-20) for cross-reference — unmodified below. indicagent relevance: §1's
> corporate-event taxonomy (earnings/FDA/lockup/8-K) doesn't transfer — indicagent's
> `equity` asset class is ETFs, not individual names. §5 (unified event-catalog
> naming convention) and §6 (generalized matched-control/bootstrap-CI event-impact
> mechanism) do transfer, directly applicable to indicagent's own scattered calendar
> signals (futures roll dates, ETF ex-div dates, FOMC/opex/quad-witching —
> `docs/ideas/signal-quarterly-seasonality-opex-risk-off.md`). §7's event-beta/
> class-pooling pattern is addressed in
> `docs/ideas/signal-sensitivity-regime-interaction-primitives.md`'s "universal
> concept" section — indicagent already has a proven, gated, more rigorous version
> of this exact pattern (`shrink_ic`/`leave_one_out_group_prior`).

**Status:** Idea — research/refinement done, not yet promoted. One narrow piece (§6) has a
concrete "fold into Phase 3 now" recommendation; everything else stays deferred pending a
decision.
**Origin:** user question, 2026-08-20, prompted by discussing `DATA-24` (trading halts):
should SSFI build a general system for event sourcing (date/date-range + impact
measurement), and what should "event" actually encompass beyond the Event theme's current
narrow scope (earnings, ex-dividend, lockup, capital-structure flags)?
**Verified live where a specific data-source claim is made** (`CLAUDE.md`'s vendor-fact
rule) — 8-K item-code structure and PDUFA-date sourcing both checked this session, not
assumed from memory.

---

## Why this needed real refinement, not just a "yes, build it"

The Event theme (`intelligence-vector-taxonomy.md` §5) and Shape 5 (event-log storage,
`data-model.md`) already exist, but three things were genuinely unresolved: whether "event"
means one thing or several structurally different things, whether news is in-scope or a
separate surface, and whether future/forthcoming events need different machinery than past
ones. Getting this wrong either forces genuinely different risk shapes (a certain earnings
date vs. a maybe-never secondary offering) into one primitive design, or blurs the boundary
`DOC-01`/Shape 7 already drew around unstructured text.

## 1. The real taxonomy — certainty of date × certainty of occurrence, not one bucket

Four structurally different cases, each needing a different primitive shape:

**Scheduled** (date certain, occurrence certain) — earnings, ex-dividend, index-rebalance
effective dates, scheduled debt maturity, annual shareholder meeting. **This is the Event
theme's actual existing scope**, already correctly bounded ("symbol-specific... knowable in
advance"). Primitive shape: days-to/-since, a clean countdown.

**Anticipated** (date known but often a guided range, occurrence fairly certain, *outcome*
uncertain) — FDA PDUFA dates, biotech trial-readout windows, M&A deal-closing windows,
litigation ruling dates. **Not the same shape as Scheduled**, for two reasons: (1) the date
itself is frequently a range ("Q3 2026"), not a point, so the primitive needs a
range-aware countdown, not a single-date one; (2) the actual driver of borrow demand here
is *binary-outcome uncertainty* (approval/rejection, win/loss), not proximity alone — a
name three days from a PDUFA date with a highly uncertain outcome plausibly has very
different borrow dynamics than one three days from a near-certain regulatory formality.
Proximity and outcome-uncertainty are two different candidate primitives, not one.

**Contingent** (no fixed date, occurrence itself uncertain, but *inferable* as elevated
risk from other signals) — a potential secondary offering/financing. **Real boundary
correction: this likely isn't an Event-theme candidate at all.** A low cash-runway
(computable from XBRL cash + burn rate, already in Phase 3's fundamentals scope) is a
continuous *level* read, not a discrete calendar event — forcing it into "Event" would blur
the theme boundary the same way capital-structure was deliberately kept out of a separate
theme (§5b already resolved this exact shape of question). Belongs as a Fundamentals/Risk
primitive (`months_of_cash_runway` or similar), not a new Event source.

**Unscheduled/reactive** (no forward date at all — CEO departure, a short-seller report, a
fraud allegation, a natural disaster) — **not "event risk" in the Event theme's sense at
all.** These are realized shocks, discovered only after the fact. They belong either to
Shock/Gate's real-time domain (v2, deferred, a different problem shape entirely) or to
genuinely unstructured news analysis (Shape 7, `DOC-01`, already deferred) — not a forward-
looking countdown primitive. Worth being explicit that this category doesn't quietly
belong in "Event" just because it's event-shaped in the English-word sense.

## 2. Is news a separate surface? Yes — but the real boundary is narrower than "all news"

Two genuinely different things travel under "news":

- **A structured fact delivered via an unstructured wrapper** — a press release announcing
  "Q3 earnings call is November 15" or "FDA has accepted our NDA, PDUFA date is set for
  March 2027" is, in substance, a date announcement. The *fact* (a date) is structured even
  though the *delivery mechanism* (prose) isn't. Extracting just the fact is a bounded,
  document-extraction problem (`DATA-17`'s raw-landing-then-extract shape), not full NLP.
- **Actual narrative/qualitative analysis** — sentiment, topic, magnitude of a qualitative
  development. This is Shape 7, stays deferred, no consumer currently proposes it
  (unchanged from the existing design).

The dividing line isn't "is it news," it's "does extracting the useful part require
understanding the prose, or just finding a date inside it." The first case is in-scope
document-extraction work; the second stays deferred.

## 3. Are future and past events different systems? No — same catalog, different query

Confirmed: this should **not** be two schemas. An event has one date (or range) regardless
of when it's queried; "days until" vs. "days since" is a point-in-time query against the
same catalog row relative to `as_of_date`, exactly matching `GOV-09`'s existing point-in-
time join discipline — no new mechanism, no separate past/future tables. Past-event rows
also serve a second real purpose beyond scoring: they're the realized sample `CALC-06/07/08`
walk-forward testing needs to validate any event-driven primitive against.

## 4. New candidate sources surfaced by this taxonomy — honest cost/provenance split

**Cheap, reuses existing Phase 3 EDGAR scope — 8-K item-code events.** Verified live: 8-K
filings carry a structured, enumerable item-code taxonomy (Item 1.01 material agreement,
2.02 results of operations, 5.02 officer departure, 7.01 Reg FD disclosure, 8.01 other
events, 9.01 financial statements/exhibits, etc.) as real metadata reachable through the
same `data.sec.gov` submissions API `DATA-23`'s ownership cluster already uses — no
narrative parsing required to know *that* and *when* an item fired, only to read what it
says. This is meaningfully cheaper than `primitive-catalog.md`'s existing capital-structure
flags (buyback/offering/conversion, currently scoped as "EDGAR (8-K), a new Gateway
source" with no extraction-mechanism detail) — item-code detection could plausibly source
those flags without any text parsing at all, worth revisiting when those primitives are
actually built.

**Not cheap, real provenance risk — FDA PDUFA / biotech catalyst dates.** Verified live:
no official government database publishes PDUFA dates programmatically. Every free source
found (MarketBeat, BiopharmaWatch, pdufa.bio, RTTNews) is a third-party aggregator —
exactly the re-aggregator risk `data-layer.md` already prefers avoiding for regulatory-
adjacent data ("a primary source eliminates a middleman's data-quality risk entirely").
The primary-source path would be extracting a company's own PDUFA-date disclosure from its
8-K narrative text (once FDA accepts the filing) — genuinely unstructured extraction, not
free the way item-code detection is. If this is ever pursued, it needs its own honest
make/buy call (subscribe to an aggregator vs. build extraction), not assumed to piggyback
on the cheap 8-K-item-code work.

**Reframed out of Event entirely — potential financing/dilution.** See §1; this is a
Fundamentals/Risk continuous primitive, not a new Gateway source at all.

**Already scoped, one real accuracy caveat — lockup expiration.** `primitive-catalog.md`
already lists this (EDGAR Form 4/prospectus lockup terms). Worth flagging: the standard
180-day lockup is a convention, not a guarantee — underwriters can waive it early, and
actual terms vary by deal. A naive `S-1 filing date + 180 days` calculation will be wrong
for some fraction of cases; the real lockup term needs sourcing from the actual prospectus
language, not assumed as a constant.

## 5. A unified event-catalog interface — cheap, worth documenting now regardless

Every Shape-5 event table (dividends, Form 4, halts, capital-structure flags, and any of
today's new candidates) should be queryable through one consistent shape —
`(symbol | NULL for market-wide, event_type, event_date_or_range, source)` — not a new
table, a naming/query convention so a future consumer (the impact-measurement mechanism in
§6, or a simple "what's coming up for this symbol" query) doesn't need per-source-shaped
logic. Costs nothing beyond consistent column naming across tables Phase 3 already
creates — worth writing into `data-model.md`'s Shape 5 section directly, not deferred, since
it's a naming discipline applied at zero marginal cost while those tables are still being
designed, not a new source or mechanism.

## 6. A shared event-impact/event-study mechanism — real, but Phase 4/5, not Phase 3

Symmetric to `intelligence-vector-taxonomy.md` §9's "reusable generic transform library"
(z-score/velocity/slope built once, reused everywhere) — the *impact-measurement* side of
event primitives has the same reuse opportunity, currently unrealized. `calendar-
primitives.md` already worked out the actual methodology (matched-control comparison
against same-day-of-week/other-weeks baselines, day/episode-clustered bootstrap CI) and
`CALC-15`'s e-process test — but scoped narrowly to `opex_flag`/`quad_witching_flag`,
never generalized. **Proposed generalization:** one shared Calc-layer function — given an
event-catalog entry (§5), a target metric (borrow-rate change, IV change, realized vol),
and a window — computes the metric's abnormal behavior vs. matched-control baseline with
`CALC-15`'s significance test, reused by every event-shaped primitive instead of each
reinventing it. This is Calc/Scoring work (Phase 4/5), not Gateway sourcing — recorded here
so the design exists before someone reinvents `opex_flag`'s bespoke test a second time for
the next event candidate.

## 7. Per-security sensitivity to a class/market-wide event — extends the factor-beta idea to events

Direct follow-on question, same session: once an event or event-class is defined, does a
security need its own sensitivity weighting to it? Splits into two cases with genuinely
different answers:

**Symbol-specific events (earnings, lockup, halts) — no new mechanism needed.** The event
already only applies to that one security; what varies is how strongly *other
characteristics* modulate its impact (a heavily-shorted, thinly-optioned small-cap
plausibly reacts differently to earnings than a mega-cap). That's the existing
interaction-primitive pattern, already established: `(days-to-earnings) × (existing
short-interest/float atomic)`, `CALC-14`-gated, same shape as `iv_dispersion_rate_
interaction`. Nothing new to build here.

**Class/market-wide events (FOMC, sector-wide regulatory shocks) — a real gap, and it's an
"event beta," not a continuous-factor beta.** `docs/research/signal-factor-sensitivity-
cross-asset.md` covers per-security sensitivity to *continuous* macro series (rolling OLS
beta against a factor proxy, verified real precedent: indicagent's `equity_beta_z`/
`rate_beta_z`). That construction doesn't directly work for a *discrete, sparse* event
class — you can't run a meaningful rolling regression against a flag that fires a handful
of times. **Proposed mechanism, reusing §6 rather than inventing a second one:** run §6's
event-impact function against every historical occurrence of an event type for a given
security, average the abnormal-metric readings across occurrences — that average *is* the
security's measured event-sensitivity. One computation (§6) serves two purposes: evaluating
a single occurrence's impact, and — aggregated across occurrences — estimating a security's
standing sensitivity to that event class.

**The real, already-anticipated problem: most individual securities won't have enough
historical occurrences to estimate this alone.** Same underpowering issue `calendar-
primitives.md` already found for `opex_flag`/`quad_witching_flag` (real events, ~80
episodes across 20 years, still underpowered by 2-5x) — an individual security's own count
of FOMC-adjacent or sector-shock episodes in SSFI's nascent panel will be far smaller.
**Fix: pool the same measurement across a security's sector/peer-class** (the "asset-class/
thematic" level from the factor-sensitivity hierarchy, here doing real statistical work,
not just conceptual grouping) and fall back to the class-level average when a security's
own history is too thin to trust individually — an explicit, stated fallback, not a
fabricated per-security number, the same `DATA-18` discipline already governs elsewhere.
Deliberately **not** proposing full hierarchical/Bayesian shrinkage (blending individual
and class estimates by confidence) at this stage — that's more machinery than "resist
overfitting"/simplicity-first currently justifies without evidence it's needed; a flat
"use class average below an n-threshold, use the individual estimate above it" rule is the
right v1 shape if this is ever built, same YAGNI discipline applied everywhere else in this
project.

## Recommendation on integration timing

**Revised after a second, adversarial rigor pass (2026-08-20) — one conclusion reversed,
one strengthened, neither left as originally stated:**

**Fold into Phase 3 now, mechanized rather than just documented.** The event-catalog
naming convention (§5) should **not** be a documentation-only note — that's the exact
"soft convention degrades to unread" failure this project already named and fixed
elsewhere (`DATA-16`, `FOUND-19`, `GOV-08`). Instead: extend `GOV-08`'s existing
classification gate (which already mechanically fires for every new table, Shape 5
included) to check a Shape-5 table's columns against the catalog convention. Free —
`GOV-08` already runs for Phase 3's new event tables regardless of this decision — and a
hard gate, not a hope.

**Do not fold 8-K item-code ingestion (§4) into Phase 3 — reversed from the first pass.**
It isn't actually free (the EDGAR *access* pattern is shared with `DATA-23`, but item-code
*extraction* is new, source-specific parsing, a genuinely new module) and, more importantly,
**no specific Phase 4/5 primitive currently consumes a bare "item X fired on date Y" fact**
— the capital-structure flags already have their own separately-scoped sourcing plan.
Building this now would be infrastructure ahead of a concrete, evidence-justified consumer,
the same unearned-complexity trap already rejected for the plugin-DAG engine, general
Redpanda, and EAV tables elsewhere in this project. Revisit only once a specific primitive
actually needs it, same standard as `DATA-19`/pgvector/ITR's deferred statistics engine.

**Stays deferred, Phase 4/5, unchanged:** the event-impact mechanism (§6), the event-beta/
class-pooling mechanism (§7), PDUFA/biotech sourcing (§4, real make/buy call needed
first — and now doubly so, since it would ride on the also-deferred item-code work), the
financing-risk primitive (§1, belongs to Fundamentals/Risk theme design, not Gateway).

## Cross-refs

- `docs/research/intelligence-vector-taxonomy.md` §5 (Event theme boundary), §9 (reusable
  transform library, the symmetric precedent for §6's proposal)
- `docs/foundation/data-model.md` — Shape 5 (event-log pattern), where §5's catalog
  convention would land
- `docs/research/calendar-primitives.md` — the matched-control/bootstrap-CI methodology
  §6 proposes generalizing
- `docs/research/primitive-catalog.md` — Event section (existing capital-structure flags,
  lockup expiration, earnings/dividend-timing candidates)
- `.planning/REQUIREMENTS.md` — `CALC-15` (e-process gate), `DATA-17` (raw-landing,
  relevant to §2's structured-fact-from-announcement case), `DATA-23` (ownership cluster,
  the EDGAR submissions-API access §4's 8-K item-code proposal would reuse)
