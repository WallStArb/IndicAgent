# IndicAgent — Business Requirements

**Version:** 1.0.0
**Status:** current
**Last Updated:** 2026-07-10
**Milestone:** standing (not tied to a phase)
**Purpose:** the top-down, business/quant-concept view of the whole system — what it is, why it
exists, what each part promises to deliver, how it can grow, and what's genuinely undecided.
Deliberately excludes implementation detail (table schemas, formulas, parameter values) — those
live in the companion docs linked from each section. Sits as a peer to `PROJECT.md` (which
states the one-paragraph vision and current requirement status) — this doc is the missing middle
layer: everything else in the tree sits either above it (`PROJECT.md`) or below it (specific
architecture docs, specific plans), and nothing else organizes the space between. Today, nearly
everything built lives in the Intelligence tiers (§4) — that's a statement about what's been
built so far, not a scope limit on this doc.

**Companion docs:**
- `.planning/PROJECT.md` — the one-paragraph vision, confirmed endgame, and current
  validated/pending requirement status this doc expands on
- `docs/intelligence/intelligence-layer-architecture.md` — the intelligence tier stack (§4) at
  mechanism altitude (what HMM/IC/Ledoit-Wolf actually compute)
- `docs/intelligence/intelligence-alphaengine.md` — today's concrete implementation manual
- `docs/research/roadmap-scope-map.md` — impact-ranked scan of what's weak/proposed per area,
  kept current; this doc explains *why the areas are shaped the way they are*, that one tracks
  *what's currently missing in each*
- `docs/research/idea-catalog.md` — full navigation index across every idea doc
- `.planning/research/2026-07-02-v3-topdown-architecture.md` and
  `2026-07-02-v3-bottomup-audit.md` — the Fable-assisted analyses this doc synthesizes

---

## 1. Vision & Core Value

**What this is:** a quantitative research platform that discovers trading edge empirically
rather than assuming it. Renaissance Technologies' methodology is the explicit model: measure
everything, trust statistics over narrative, promote nothing until it has earned its place
through evidence.

**Core value:** no feature, model, or combination is trusted until it has demonstrated real,
out-of-sample predictive power against actual forward returns — measured on the complete
unbiased dataset, never on a hand-picked subset that already looks good.

**The inversion this replaced:** the prior approach (v2.x, archived) had researchers write rules
for what counts as a tradeable pattern, then check whether it worked — the same bias every
discretionary trader has, wrapped in code. The current approach reverses the order: produce
many simple, independent measurements of the market; let statistical evidence, not human
judgment, decide which measurements combine into a signal and how much weight each gets.

**Endgame (the actual tie-breaker):** this system exists to eventually trade the owner's
personal capital — not to become a product sold to others, not as a pure research exercise.
Every decision below — which data source is worth adding, which tier is worth building next,
which extension is premature — gets judged against "would I trust this with real money," not
against technical interest or completeness (`PROJECT.md`, confirmed 2026-07-05).

---

## 2. System Scope: Three Kinds of Modules

Everything the platform does, or could do, falls into one of three module kinds. They are
architecturally distinct — not three sizes of the same thing — and are connected only through
the data bus (Kafka topics), never by direct calls (`CLAUDE.md` DAG Invariant 5). This is the
same rule already governing today's single-vector pipeline, applied forward to a system that
may eventually run several.

1. **Intelligence modules** — produce a statistically-validated view of expected forward return
   for one instrument, from one data source. This is the entire system today (V1 Quant /
   AlphaEngine). Every future intelligence module (§3) is the same pattern — the tier stack in
   §4 — pointed at a different data source. Nothing about adding a new intelligence module
   should require touching an existing one.
2. **Decision/Action modules** — take one instrument's intelligence output and decide whether
   and when to act on it: size, enter, exit. Scope is deliberately singular — one instrument at
   a time. This is what `docs/research/vision-05-tradeagent.md` (execution vehicle) and part of
   `vision-01-aegisagent.md` (risk overlay: sizing, drawdown limits) describe, and it's the same
   thing already gated on ROADMAP as the v4.0 Execution Layer ("consumes `alpha_events`, never
   modifies signal weights").
3. **Portfolio modules** — a genuinely different scope: many instruments considered together,
   where correlation, capital allocation, and risk budgeting produce a different right answer
   than any single instrument's view would suggest in isolation. `docs/research/vision-03-primeagent.md`
   (portfolio management) is the existing doc for this. Does not exist yet, and isn't a bigger
   version of a Decision module — it's a different consumer of the same upstream intelligence.

**On the "parked" vision docs:** `PROJECT.md`'s Endgame note parks the seven `vision-0N-*` docs
because their *commercial-product framing* (building this for other people) is out of scope.
That framing is parked — the underlying module concepts are not. Read through the personal-
live-trading lens instead of the product lens: AegisAgent and TradeAgent map to Decision/Action
(§2.2 above), PrimeAgent maps to Portfolio (§2.3), and DerivAgent/QualAgent/FlowAgent/FundAgent
map to future Intelligence modules (§3) rather than to standalone products. **Known
inconsistency, not resolved here — and one level deeper than it first looks:** whether V8
Fundamental exists as its own vector is itself unsettled (§3, §7 item 1 — the glossary only
canonically recognizes V1/V3/V5/V7). Layered on top of that, `signal-08` maps V7 Qualitative →
QualAgent and V8 Fundamental → FundAgent as separate vectors, while `roadmap-scope-map.md`
describes QualAgent itself as covering "fundamental/qualitative intelligence" (combined) and
lists FundAgent as "scope unclear, titles only." Which vision doc owns which vector is unresolved
at two levels, not one — flagged in §7, not guessed at here.

Building Decision or Portfolio modules now would be premature — §6 states the bar V1 Quant has
to clear first, and nothing downstream should be designed in detail before that bar is cleared.

---

## 3. Data Foundation

**Today:** one data source — OHLCV bars via IBKR — feeding one intelligence module (V1 Quant).

**Exchange-aware filtering already exists and is real, not a gap.** `src/core/market_calendar.py`
is a proper `MarketCalendar` backed by `pandas_market_calendars` (real NYSE/CME session
boundaries, holidays, early closes); `backfill_feature_factory.py` calls
`calendar.is_trading_bar(...)` and skips non-trading bars *before computing any feature*.
Separately, the real-time path emits deliberate flat bars (`BarMessage.is_flat_bar`, propagated
through `BarAggregator`) specifically to keep a gap-free time series without pushing gap-fill
logic into every downstream consumer (`docs/data/data-provider.md`). Feature computation today is
correctly exchange-aware.

**The narrower, real gap: no column-level guarantee on the canonical table itself.**
`market_data_ohlcv` — the table every feature and vector ultimately reads from — physically
stores the flat-filled padding rows (~81% of rows, per the 2026-07-02 bottom-up audit) with no
stored flag distinguishing them from real trading bars. The one consumer that matters today
(`backfill_feature_factory.py`) correctly excludes them via `MarketCalendar`, but that's a
per-consumer discipline, not a schema-enforced contract — any future consumer has to remember to
call it too. Given "data integrity is paramount" is a house principle, closing that contract gap
(a stored session-mask column, or the already-proposed active-bars view) belongs in the
requirements picture before a new data source multiplies the number of consumers that have to
get this right independently.

**Canon vs. draft — the vector count itself is not settled.** `docs/foundation/glossary.md` (the
authoritative term source, per house rule "glossary wins on collision") formally recognizes only
**V1 Quant, V3 Macro, V5 Flow, V7 Qual** as vectors, and is explicit that a vector is "not a
synonym for tier" — I1-I4 are measurement tiers *within* V1, not vectors in their own right.
`signal-08-intelligence-refactor.md`, dated the same day as the glossary's last update and marked
**"Status: working draft — for discussion and refinement,"** proposes splitting V1's internal
tiers into four additional standalone vectors (V2 Microstructure, V4 Calendar, V6
Derivatives/Gamma, V8 Fundamental) — a draft that was never reconciled back into the glossary.
The table below presents `signal-08`'s eight-vector version because it's the only place a full
cadence taxonomy exists, but **do not treat V2/V4/V6/V8 as canonical** until that reconciliation
happens (§7):

| Vector | Domain | Cadence kind | Status |
|---|---|---|---|
| V1 Quant | Price/volume | Bar-aligned | Built |
| V2 Microstructure | Order flow (OFI/CVD) | Bar-aligned | Folded into V1's features today; tick-data upgrade later |
| V3 Macro | Cross-asset (VIX, yield curve, breadth) | Bar-aligned | Folded into V1's features today |
| V4 Calendar | Time structure | Bar-aligned | Folded into V1's features today; needs no new data |
| V5 Flow/Positioning | COT, dark pools, short interest | Ambient | Not built — new data required |
| V6 Derivatives/Gamma | GEX, vol surface, VRP | Ambient | Not built — new data required |
| V7 Qualitative | News, sentiment, narrative | Ambient | Not built — new data required |
| V8 Fundamental | Earnings, macro releases | Ambient | Not built — new data required |

**Bar-aligned vectors (V1-V4)** produce a score every bar and feed the emission decision
directly. **Ambient vectors (V5-V8)** update at their own cadence — weekly, quarterly,
event-driven — and, per `signal-08`, are meant to act as a *conviction modifier* on the
bar-aligned decision (tilting the emission threshold up or down) rather than firing a signal
directly, with a `valid_until` timestamp that decays an unrefreshed score to neutral rather than
holding a stale value.

**Open reconciliation (see §7):** `docs/research/alphaengine-alt-data-extension.md` proposes a
*different* answer to the same cadence problem for its four candidate sources (Flows,
Fundamentals, Qualitative, Kalshi prediction markets) — fill-forward the slow-cadence value into
`feature_vectors` as an ordinary column, measured by IC exactly like any bar-aligned feature,
with a per-source IC gate calibrated to that source's own available sample size. These two
patterns — ambient conviction-modifier vs. fill-forward-into-IC-measurement — are not obviously
compatible, and nothing in the tree states which applies when. This is a real open question, not
a documentation gap to smooth over.

**Recommended build order, if new sources are ever pursued** (per `alt-data-extension.md`):
Flows first (same cadence as price, lowest infrastructure delta, likely measurable IC on
rate-sensitive ETFs) → Kalshi as regime conditioning (stratifies existing price IC by macro
event probability, doesn't need its own return-prediction proof) → Fundamentals (needs
fill-forward infrastructure and corpus depth) → Qualitative (infrastructure is straightforward;
news-timestamp look-ahead discipline is the real risk, isolated last on purpose).

---

## 4. The Tiers as Capabilities

Every intelligence module (§2.1), regardless of which vector or data source feeds it, runs the
same tier stack. Full mechanism detail lives in `intelligence-layer-architecture.md`; this is
the business-capability view — what question each tier answers, and what other ways exist to
answer it.

| Tier | Business question it answers | Current approach | Real alternatives on the table |
|---|---|---|---|
| **Primitive Measurement** (Stage 0) | What can we measure about this instrument, right now, with no theory attached? | 89 Renaissance primitives (150 `FeatureVector` columns total, as of 2026-07-09) computing a fixed vector per bar | Not a mechanism-swap question (unlikely to need a different measurement paradigm) but a genuine scale question: Renaissance's own reference point is ~499 raw signals into Medallion's ensemble, vs. our 89 today. `renaissance-primitives-ohlcv.md` catalogs true stateless primitives not yet computed; a proposed atomic/interaction/theory sub-classification is designed but informal. The next tier up — second-order (pairwise) interaction primitives — had its evidence gate run 2026-07-10 (todo 037): 22.2% of a hand-picked cohort showed genuine incremental IC, confirming the atomics are NOT saturated. Phase 150 already commits to a curated ≤50-feature theory-motivated layer on the strength of that result, not the full combinatorial "Interaction Factory" generator (`docs/research/intel-feature-interaction-factory.md`), which Phase 150 separately rejected on BH-FDR power grounds at ~30K-candidate scale |
| **Stratification** (Stage 1) | Which observations belong together, so we don't average across regimes as if they behaved the same? | Two coexisting systems: per-symbol HMM (5 states) and cross-sectional VIX×breadth (9 states) | Volume/skew/factor regimes, IOHMM, factor-augmented HMM — a formal `StratificationDimension` contract with a promotion gate (orthogonality + substitution test) is proposed but not built (`intel-12`) |
| **Edge Measurement** (Stage 2) | Does this measurement actually predict forward returns, and how confident are we? | Spearman rank correlation (IC), bootstrap CI, IC Sharpe | Mutual information as a secondary, non-monotonic-aware measure — a real open question, not yet a scoped plan |
| **Combination** (Stage 3) | Given many individually-scored measurements, which matter and how much? | IC-weighted linear combination, Ledoit-Wolf covariance shrinkage for redundancy | Already multi-mechanism by design today (`ic_proportional`, `v1_shrunk`, `mean_variance`, being A/B judged) — the model for how the other tiers should eventually work |
| **Emission** (Stage 4) | When is the combined view strong and confident enough to act on? | Threshold + CI crossing | Not currently questioned — but see the conflation noted below |
| **Simulation/Validation** (not yet a numbered Stage in `intelligence-layer-architecture.md`, which stops at Stage 4 — a real cross-doc naming gap, not resolved here) | Did acting on this actually make money, under rules committed to in advance? | Frame-based counterfactual P&L tracking (Phase 142B), pre-committed criteria before data collection | Not currently questioned — this discipline (commit criteria before seeing data) is considered load-bearing, not up for revision |

**Two acknowledged gaps with no tier and no mechanism yet:** proving that separate intelligence
vectors are actually statistically independent (asserted, never measured), and any
orthogonalization/whitening step that would clean correlated features before combination rather
than just re-weighting around the correlation. Both are real gaps, not naming gaps — flagged so
they don't get assumed solved because the tier language exists.

**A third gap, inside a tier that looks finished:** Emission's output today conflates two
different claims — "statistically qualifies" and "worth acting on after real trading costs."
The 2026-07-02 bottom-up audit found ~98% of current emissions sit in a timeframe band already
shown cost-negative once realistic costs are applied, because the cost-hurdle gate is presently
a no-op. This matters at the business level, not just the implementation level: it means
Emission's output is a *research* artifact today, not yet a *tradeable* one, and the Extension
model below (§5) has to account for that distinction rather than assume a Decision module can
safely consume it as-is.

---

## 5. Extension & Reuse Model

For a new intelligence module (§2.1) to plug into the tier stack (§4) without modifying an
existing one, three things have to hold:

1. **The data source must resolve to the same shape** the tiers already consume — a numeric
   value at time T with a causally-known forward return at T+N. Per `alt-data-extension.md`,
   this is a genuine "IC methodology has one requirement" property — the measurement apparatus
   doesn't care where the number came from, only that alignment and look-ahead discipline are
   correct at ingestion.
2. **Stratification must be reusable, not vector-specific.** Today two unrelated services do
   this for one vector; the proposed `StratificationDimension` contract (§4, Stratification row)
   is what makes a second vector's conditioning free instead of a second bespoke regime system.
3. **Combination and governance stay vector-agnostic.** The ensemble weighting mechanism and the
   proposed Concept Registry (evidence-gated lifecycle for features, ensemble strategies, and
   stratification dimensions alike) are designed to treat "a predictor" generically — a V1
   feature, a V5 flow score, and an analog-engine output are the same kind of thing to the
   combination tier, differing only in provenance.

**Decision and Portfolio modules (§2.2, §2.3) are downstream consumers of `alpha_events`, not
new tiers bolted into the intelligence stack.** They read the same emitted output every
intelligence module produces; they do not participate in feature computation, stratification,
measurement, or combination. This keeps the tier stack's job (produce a validated forward-return
view) cleanly separated from the action-taking job (decide what to do about it). **Given §4's
Emission conflation, "consume `alpha_events`" has to mean the cost-hurdle-qualified subset, not
the raw emission stream** — a Decision module built against today's raw output would be acting on
a ~98%-cost-negative population without knowing it.

---

## 6. What "Solid" Means for V1 Quant

Before any new intelligence module, Decision module, or Portfolio module is worth designing in
detail, the one vector that exists today has to clear its own bar. Stated as acceptance
criteria, not implementation steps:

- **Out-of-sample proof, not in-sample fit.** The ensemble's predictive power must hold on data
  it did not see during weighting, at a pre-committed p-value threshold — not just on the corpus
  used to train it.
- **Statistically defensible per stratum.** A result has to survive multiple-testing correction
  and have enough independent observations per (instrument, timeframe, regime) cell to mean
  something — not be a single lucky cell in a large search.
- **Counterfactual, not theoretical, profitability, net of real costs.** A frame-based
  simulation must show the strategy would have made money under rules (stops, targets, holding
  period) committed to *before* the data was collected, not tuned to fit afterward — and against
  a real cost hurdle, not the currently-inert 0.0 placeholder (§4).
- **Survives across market regimes**, not just the ones most represented in the training window.
- **Rests on a data foundation whose guarantees are schema-enforced, not per-consumer
  discipline** — §3's exchange-aware filtering is correctly implemented today, but only because
  the one consumer that matters remembers to call it; that's the kind of implicit assumption this
  bar exists to eventually convert into a contract.

Until this bar is cleared, the honest posture on §2's Decision and Portfolio modules and on new
data sources (§3) is: name them, understand roughly where they'd fit, and do not build them.

---

## 7. Open Strategic Questions

Genuinely undecided calls that shape how much of the above ever gets built, in rough priority
order:

1. **Does V2/V4/V6/V8 exist at all, canonically (§3)?** `glossary.md` recognizes only V1/V3/V5/V7
   and calls a vector "not a synonym for tier"; `signal-08`'s eight-vector split is a same-day,
   never-merged working draft. This sits upstream of nearly every other item below — the vision-
   doc mapping in §2, the build order in this list, and the cadence-handling question all assume
   an eight-vector world that may not be canonical. Resolve this first: either ratify `signal-08`
   into the glossary, or fold V2/V4/V6/V8 back into their parent vectors as tiers.
2. **Ambient-modifier vs. fill-forward-IC-measurement (§3).** Two source docs propose
   incompatible answers to how a slow-cadence source enters the system. Only reachable once #1
   is settled — if V2/V4/V6/V8 aren't real vectors, this question may only apply to V5/V7 (and a
   hypothetical V8-as-part-of-V7 or similar), not eight independent cases.
3. **Which vision doc owns which future vector (§2).** `signal-08` and `roadmap-scope-map.md`
   disagree on whether QualAgent is Qualitative-only or Qualitative+Fundamental combined, and
   FundAgent's scope is described as "titles only" in one place. Also downstream of #1.
4. **Is a Portfolio module in scope at all before Decision modules exist?** §2.3 is real but has
   zero designed infrastructure; worth deciding whether it's a v4.x-adjacent concern or genuinely
   later, given the endgame is personal capital (likely a small number of concurrent positions,
   which changes how much portfolio machinery is actually needed).
5. **Does cross-vector orthogonality need its own tier**, or is it adequately handled by the
   combination tier's existing covariance-shrinkage step once a second vector actually exists?
   Currently unmeasurable because only one vector exists — see §4's acknowledged gap.
6. **Build order for V5-V8**, if pursued: `alt-data-extension.md`'s recommendation (Flows →
   Kalshi-as-conditioning → Fundamentals → Qualitative) is the only sequencing proposal on
   record and hasn't been cross-checked against `signal-08`'s ambient/bar-aligned split or
   against which of the parked vision docs are actually ready to inform a build.
7. **Mutual information as a second edge-measurement statistic (§4)** — real question, no
   scoping done yet, would need a schema note (does `feature_ic_scores`/`predictor_ic_scores`
   reserve room for a second statistic type per cell?) before it's actionable.
8. **Research-qualifying vs. cost-hurdle-actionable (§4, §5).** `alpha_events` needs an explicit
   second gate (a real cost hurdle, not the current no-op) or an explicit second column/tier
   before any Decision module design starts — otherwise "consume alpha_events" quietly means
   "consume a ~98%-cost-negative population."

---

## Related Documents

- Business/vision altitude (this doc) → tier mechanism detail: `intelligence-layer-architecture.md`
- Tier mechanism detail → current concrete implementation: `intelligence-alphaengine.md`
- What's weak/proposed per area, kept current: `docs/research/roadmap-scope-map.md`
- Full idea-doc navigation index: `docs/research/idea-catalog.md`
- Clean-sheet structural proposal this doc draws on heavily:
  `.planning/research/2026-07-02-v3-topdown-architecture.md`
- What the running system actually does today, verified against code/DB:
  `.planning/research/2026-07-02-v3-bottomup-audit.md`
- New data source candidates in depth: `docs/research/alphaengine-alt-data-extension.md`
- Full intelligence-vector taxonomy: `docs/research/signal-08-intelligence-refactor.md`
- Exchange-aware bar filtering and the deliberate flat-bar design: `docs/data/data-provider.md`
- Parked-but-relevant module concepts: `docs/research/vision-01-aegisagent.md` (risk overlay),
  `vision-03-primeagent.md` (portfolio), `vision-05-tradeagent.md` (execution vehicle),
  `vision-02-derivagent.md`, `vision-04-qualagent.md`, `vision-06-flowagent.md`,
  `vision-07-fundagent.md`
