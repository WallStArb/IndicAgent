# Trade Construction Layer — From Forecast to Position

**Version:** 1.0
**Status:** draft — design concept; PortfolioTrack's concrete half
**Priority:** high (weakness #5 from the 2026-07-01 council review: the layer is absent, and
its absence changes what "edge" means upstream)
**Milestone:** future — scoping trigger is Phase 142A's OOS gate, same as PortfolioTrack
**Last Updated:** 2026-07-01
**Tags:** trade-construction, portfolio, cross-sectional, long-short, sizing, cost, kelly

**Companion to:** `docs/research/edge-source-thesis.md` (thesis T3 is only testable through this
layer) and `docs/research/intel-15-measurement-engine.md`'s Cross-Sectional Rank IC addendum (T3's
falsification measurement, which must clear before this construction layer is warranted).
**Note (2026-07-03):** this doc's original companion, `intel-11-dual-system-discrete-vs-portfolio.md`,
was retired — see `docs/research/archive/intel-11-dual-system-discrete-vs-portfolio.md`. Per
`.planning/research/2026-07-03-intel10-11-fable-review.md` (F9), PortfolioTrack is not a track;
this doc's construction-layer content remains a v4.0 concern, gated on the addendum's falsification
result, not on a "PortfolioTrack" scoping event.

---

## The Core Point

A forecast is not a trade. The same per-bar conviction vector can be monetized at least four
structurally different ways, and they have *different edge requirements* — the construction
choice determines how much IC is enough:

| Construction | What it needs to win | IC bar | Beta exposure |
|---|---|---|---|
| Per-symbol directional (current implicit design) | Each symbol's signal beats that symbol's full vol + market moves | Highest | Full |
| Cross-sectional long-short (dollar-neutral) | Only the *ranking* across symbols has to be right | Lowest | ~Hedged |
| Directional with index hedge | Signal beats idiosyncratic vol only | Middle | Hedged per-position |
| Overlay tilts on a passive book | Conditional tilts beat their own turnover cost | Lowest, but capped upside | Deliberate |

Everything upstream (IC engine, ensemble, frames) is currently built for row 1 — the hardest
row. Phase 142B's stop/target/hold frames are per-symbol directional execution rules. Nothing
in the roadmap tests rows 2-4.

## Why Cross-Sectional Long-Short Is the Natural Fit for This Universe

- **58 correlated ETFs is a relative-value universe, not 58 independent directional bets**
  (effective breadth ~8-15; see feature-scoring-beyond-ic §4). Ranking within a correlated
  set is exactly what a cross-sectional portfolio monetizes and a directional book wastes.
- **Beta cancellation is free risk reduction.** Long the top decile of the ranking, short the
  bottom, dollar-neutral: the market factor nets out, so the P&L stream is the *spread* —
  driven by the forecast, not by whether SPY went up. The Sharpe of a hedged spread on weak
  IC routinely beats the Sharpe of unhedged directional trades on the same IC.
- **It changes the falsification story.** If per-symbol directional fails the cost hurdle
  (todo 030 Step 0) but the spread portfolio pays, the edge is real and relative (thesis T3).
  Without this layer, that outcome is indistinguishable from "no edge."
- **Costs differ:** a rebalanced spread portfolio trades *changes in the ranking*, not every
  signal — turnover control is a portfolio property, unavailable to independent per-symbol
  frames.

## Minimal Design (deliberately small — this is a v1 spec, not an optimizer)

Renaissance principle applied: no convex optimizer, no risk-model estimation, no borrow/
margin modeling in v1. Rank, bucket, weight, net, rebalance. Each step earns complexity later
through proof.

1. **Input:** per-bar calibrated conviction vector across the universe per tf — requires
   feature-scoring-beyond-ic 0c (calibration) so the vector is in return units. Uncalibrated
   z-scores can rank (enough for v1 spread construction) but cannot size.
2. **Ranking → buckets:** top-N / bottom-N by conviction (APR: `alpha.construction.n_legs`),
   within the symbol's validated regime_scope only.
3. **Weights:** v1 equal-weight per leg, vol-scaled per symbol (divide by trailing ATR/vol so
   one high-vol leg doesn't dominate the spread). Kelly-fraction scaling of gross exposure
   deferred until calibrated E[R] exists (the `alpha.*` Kelly APR keys already reserved).
4. **Netting:** dollar-neutral across legs per tf. Cross-tf netting (5m signal vs 1d signal
   on the same symbol) resolved by simple priority rule in v1 (APR:
   `alpha.construction.tf_priority`), learned later.
5. **Rebalance rule:** trade only ranking changes that clear a per-trade cost floor
   (todo 030's spread estimates) — turnover control as a first-class constraint, not an
   afterthought.
6. **Measurement:** the unit of account is the *portfolio*, not the trade. Daily spread P&L,
   net of modeled costs, vs. two benchmarks: flat, and the same construction with shuffled
   rankings (the construction-level null — a spread portfolio can show positive P&L from
   construction artifacts alone; the shuffled-ranking null catches that).

## What This Explicitly Defers

- Convex optimization / covariance-based risk models (v1 vol-scaling is the 80/20)
- Borrow cost / hard-to-borrow modeling (ETF universe is easy-to-borrow; revisit if universe
  expands)
- Capacity/market-impact modeling (irrelevant at this account size)
- Live execution — this layer is validated entirely in counterfactual/shadow mode first,
  same discipline as Phase 142B frames

## AegisAgent / TradeAgent Reuse Assessment (todo 059, 2026-07-16)

`docs/research/archive/vision-01-aegisagent.md` (independent risk management) and
`docs/research/archive/vision-05-tradeagent.md` (autonomous trading app) were written as
long-horizon, multi-tenant commercial-product vision — out of scope now that the Core Value is
confirmed as personal live-trading capital (`.planning/PROJECT.md`). Re-reading both specifically
for "what transfers to a single-user version" against this doc's v1 design and the v4.0 Execution
Layer roadmap (Phases 156-159):

**Transfers directly (no descoping needed):**

- **AegisAgent's fail-safe default** — if the risk check is unavailable, block new positions.
  Cheap, architecturally correct regardless of scale, and should be a hard rule in Phase 157.
- **AegisAgent's hard limit table** (max daily/weekly/account drawdown, margin utilization
  tiers, single-position-% caps) maps almost line-for-line onto Phase 157's already-planned
  risk ceilings (VaR ceiling, per-symbol drawdown limits, regime-conditioned caps) — use
  AegisAgent's limit table as the starting checklist when Phase 157 is planned, not a proposal
  needing re-derivation.
- **AegisAgent's emergency halt / independent-authority principle** — a risk check that cannot
  be silently bypassed by the sizing or execution code path. Phase 157 already independently
  designed a kill switch; AegisAgent's "fails loud, fails safe, no automated override" framing
  is the correct discipline to apply to it, single-user or not.
- **AegisAgent's VaR (95%/99%) and correlation/concentration analysis** — directly reusable;
  Phase 156's `portfolio_state` (correlation-cluster exposure) and Phase 157's VaR ceiling are
  this same idea, already scoped.
- **AegisAgent's audit trail** (`risk_events`, `pretrade_checks` tables) — cheap, valuable at
  any scale, no commercial framing required.
- **TradeAgent's trade lifecycle management** (stop cascade 1m→5m→15m→1H, BE/trail logic) — pure
  position-management logic with zero multi-tenant baggage. Not yet named explicitly in Phase
  158/159's design; worth folding in when those phases are planned.
- **TradeAgent's confidence→allocation curve** — a simple signal-confidence-to-position-size%
  map. Useful as an interim/sanity-check sizing method before Phase 157's Portfolio Kelly is
  fully calibrated (Kelly with high estimation error can produce sizes worth sanity-checking
  against a simpler curve).
- **TradeAgent's reconciliation agent** (compare internal ledger to broker positions/fills,
  flag breaks) — directly reusable and currently a gap in Phase 158's design, which covers
  idempotent reconciliation on reconnect but not an ongoing scheduled reconciliation job.
- **TradeAgent's trade linkage/groups** (P&L, risk, and close managed as one unit for a set of
  legs) — maps directly onto this doc's own cross-sectional spread portfolio: a long/short
  ranked bucket is exactly a "group" whose legs should be sized, measured, and closed together.
- **TradeAgent's learning-loop promotion gates** (minimum sample size before a weight update,
  versioning/rollback) — not a new idea for this project, it's the same Shadow Governance /
  APR promotion-gate pattern already in use (`setup_performance`'s `sample_size >= 30` gate);
  AegisAgent/TradeAgent's version confirms the pattern rather than introducing one.

**Needs descoping (the underlying idea is right, the commercial machinery around it is not):**

- **AegisAgent's synchronous pre-trade-check protocol as an independent Ring 2 daemon**
  publishing binding `risk:halt`/`risk:reduce` Kafka events other daemons must obey — for one
  account and one execution path, this can likely collapse into an in-process gate call inside
  Phase 157/158's sizing→execution sequence rather than a separate pub/sub service. Keep the
  *property* (a bug in sizing math cannot silently disable a drawdown limit) by hard-sequencing
  Phase 157 before Phase 158, not by building a standalone daemon architecture to enforce it.
- **AegisAgent's stress-test scenario library** — descope from 7 scenarios (several assume an
  options book: vol spike/crush on Greeks, short gamma/vega) down to the 1-2 that apply to an
  ETF-only spot book (gap-open, vol spike on the underlying). No options are traded here.
- **AegisAgent's margin monitoring across brokers** — single IBKR account, no
  multi-broker margin aggregation needed; keep basic utilization tiers only.
- **TradeAgent's broker-agnostic canonical order model** — the *abstraction* (internal logic
  speaks one order format, translated at the boundary) is good practice and already matches
  this project's existing invariant that `src/providers/ibkr.py` is the sole `ib_insync`
  boundary. Descope everything downstream of that: no multi-broker adapters, no MCP-per-broker,
  no rule-based routing table — there is exactly one broker connection.
- **TradeAgent's signal/universe filtering** (asset-class/sector allow-blocklists) — descope
  from a per-tenant rules engine to one global static config list. The design shape (an
  include/exclude filter ahead of sizing) is still worth keeping.
- **TradeAgent's Lead agent (LLM-assisted take/skip/size with HITL approval modes)** — descope
  to a deterministic decision path for v1; this project's existing pattern keeps LLMs advisory/
  narrative (`narrative_swarm`), not in the order-decision critical path. The user is already
  the human in the loop by default for a personal account — the elaborate approve/advisory/
  autonomous mode-selection machinery isn't needed until (if ever) an LLM sits in that path.

**Commercial-only / irrelevant — ignore:**

- Multi-tenant everything: per-tenant parameters, per-tenant broker credential encryption,
  tenant isolation and least-privilege between *other users'* credentials.
- Agent dashboards/ops and reporting agents framed as a customer-facing product surface
  (spin up/turn off per tenant, emailed/PDF/CSV report delivery) — this project already has
  Grafana (`:3001`) for internal monitoring; no customer deliverable is needed.
- Prompt-injection/tool-injection hardening for LLM-driven order submission — moot once the
  decision path is kept deterministic (see descoping above); revisit only if an LLM is ever
  placed in the execution critical path.
- Institutional compliance/regulatory reporting framing, and any options-Greeks-specific
  language (vega/gamma exposure, short-vol stress) — not applicable, no options book exists.

## Validation Gates (same pattern as everything else)

1. **Shadow spread portfolio on the OOS window:** net-of-cost spread Sharpe > 0 at 95%
   bootstrap CI, and beats the shuffled-ranking null.
2. **Attribution honesty:** spread P&L must load on the forecast (rank-weighted return
   spread), not on a static factor tilt (e.g., permanently long low-vol sectors) — regress
   spread returns on static bucket membership; if a fixed membership explains most of it,
   the "forecast" is a factor exposure in disguise (edge thesis T4, cap expectations
   accordingly).
3. **Comparison to DiscreteTrack directional on the same features** — this comparison IS the
   T3 test from the edge-source thesis; record the verdict there.

## Sequencing

Blocked on Phase 142A (proven OOS ensemble IC — no point constructing portfolios from an
unproven forecast). Then this doc's v1 is deliberately buildable in 1-2 phases: construction
+ shadow measurement is queries and a batch service, not new infrastructure — it reads
`alpha_events`/`feature_vectors` and `forward_returns` like everything else.

## References

- `docs/research/archive/intel-11-dual-system-discrete-vs-portfolio.md` — retired strategic frame (historical only)
- `docs/research/intel-15-measurement-engine.md` — Cross-Sectional Rank IC addendum, T3's falsification gate
- `docs/research/edge-source-thesis.md` — thesis T3, which only this layer can test
- `.planning/todos/pending/030-cost-hurdle-apr-calibration.md` — Step 0 cost floors feed the
  rebalance rule and the net-of-cost measurement
- `docs/plans/2026-06-29-feature-scoring-beyond-ic.md` — 0c calibration (sizing prerequisite),
  §4 effective breadth (why relative-value fits this universe)
- ROADMAP.md Phase 142A (scoping trigger), Phase 142B (the per-symbol directional counterpart
  this doc complements, not replaces)
- `docs/research/archive/vision-01-aegisagent.md`, `docs/research/archive/vision-05-tradeagent.md`
  — commercial-product vision docs; see the Reuse Assessment section above for what transfers
  to a single-user version (todo 059, 2026-07-16)
- ROADMAP.md Phases 156-159 (v4.0 Execution Layer — Portfolio State, Position Sizing & Risk,
  Live Execution, Cost Calibration) — where the "transfers directly" items above should land
