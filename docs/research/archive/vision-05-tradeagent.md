# TradeAgent — Autonomous Trading Application (Vision)

**Status:** draft
**Version:** 0.9
**Created:** 2026-03-04
**Last Updated:** 2026-06-17
**Context:** Autonomous trading application — consumes intelligence, manages full trade lifecycle, multi-tenant
**Priority:** low
**Milestone:** future (post-v2.8)
**Tags:** tradeagent, execution, autonomous-trading, broker, portfolio, risk, platform, vision

---

## Table of contents

| Section | Contents |
|---------|----------|
| [Product family](#product-family) | IndicAgent, TradeAgent, DerivAgent roles |
| [TradeAgent scope](#tradeagent-scope) | Consumes, deployment, multi-tenant, learning |
| [Internal agents](#internal-agents-within-tradeagent) | Lead, synthesis, lifecycle, risk, portfolio, parameters, learning |
| [Lead agent](#lead-agent-llm-assisted-with-user-defined-guardrails) | LLM-assisted lead, user-defined guardrails |
| [Broker-agnostic execution](#broker-agnostic-execution-layer) | Canonical orders, adapters, MCP, multi-broker per tenant, rule-based routing |
| [Portfolio monitoring](#portfolio-monitoring-and-position-visibility) | Real-time tools, segregation when comingled |
| [Trade linkage](#trade-linkage-multi-leg-pairs-groups-position-allocation) | 1:1, 1:many, many:many groups; options vs equities; managed as group |
| [Confidence → allocation](#confidence--allocation-draft) | Max cap, confidence→size curve |
| [Signal and universe filtering](#signal-and-universe-filtering) | Include/exclude by asset class, security, sector |
| [Customer problems and feature ideas](#customer-problems-and-feature-ideas) | Execution, management, lifecycle, portfolio, risk, metrics |
| [Connection to IndicAgent](#connection-to-indicagent) | API/SSE, regime + volatility data |
| [Connection to DerivAgent](#connection-to-derivagent) | TBD |
| [Observability, HITL, guardrails, security](#observability-human-in-the-loop-guardrails-and-security) | Logging, metrics, trace, audit; human modes; system guardrails; injection protection |
| [Renaissance-style](#renaissance-style-what-tradeagent-would-need) | Validation before scale, data first, self-improving, research-to-production |
| [Learning and self-improvement](#learning-and-self-improvement-key-feature) | What feeds learning, what gets updated, safety, promotion gates, versioning |
| [Agenticizing lifecycle](#agenticizing-the-full-lifecycle-pre-trade-post) | Pre-trade, in-life, post-trade agents |
| [Agent dashboards and ops](#agent-dashboards-and-ops) | Spin up/turn off, see what agents do, config, alerts |
| [Reporting agents and dashboards](#reporting-agents-and-report-dashboards) | P&L, risk, journal, learning dashboard; delivery |
| [References](#references) | Related docs |

---

## Product family

| Product       | Role |
|---------------|------|
| **IndicAgent** | Market intelligence: I1–I8 pipeline, signals, narratives. No execution. |
| **TradeAgent** | Autonomous trading application: consumes IndicAgent signals, manages trade lifecycle, portfolio, risk. Multi-tenant. |
| **DerivAgent**  | Derivatives-focused product (separate codebase). |

Naming: `*Agent` is a product label in the product family, not a code class. Underlying daemon classes/files derive from `docs/foundation/naming-system.md` when built (the `_agent` suffix is retired).

---

## TradeAgent scope

- **Consumes:** IndicAgent outputs (signals, optionally intelligence/SSE or API).
- **Deployment:** Separate application (e.g. API/SSE client). Not inside IndicAgent repo.
- **Multi-tenant:** Multiple users/tenants; each has own parameters, portfolio, risk limits, and agent behavior.
- **Learning and self-improvement** is a core feature: outcome data feeds back into sizing, setup ranking, and validation so the system improves over time without manual retuning.

---

## Internal agents (within TradeAgent)

| Agent | Responsibility |
|-------|----------------|
| **Lead (orchestrator)** | LLM-assisted: reasons over context (positions, regime, signal confidence) and suggests take/skip/size. User-defined guardrails enforced before any order. Delegates to synthesis, lifecycle, risk, portfolio. |
| **Trade synthesis** | Turns IndicAgent signals into executable trade decisions (entry/exit levels, confidence → sizing). |
| **Trade lifecycle** | Manages active trades: stop cascade (1m → 5m → 15m → 1H), “let winners run,” BE/trail logic. |
| **Risk management** | Position limits, drawdown caps, exposure checks, per-tenant risk params. Watches **market regime** and **volatility** from IndicAgent: may cut or reduce trades on regime change, extreme events, or volatility spikes. Volatility-based position sizing (e.g. scale down size when vol expands). |
| **Portfolio optimizer** | Avoids repetitive/overlapping trades; diversification; capital allocation across signals. |
| **User parameters** | Manages tenant config: risk tolerance, max % per trade, confidence→size curve, feature toggles, **signal/universe filters** (asset class, symbol, sector include/exclude). |
| **Learning / self-improvement** | Consumes outcome data (resolved trades, MAE/MFE, guardrail hits, shadow signals). Updates setup weights, confidence→sizing curves, and validation thresholds. Key feature: system gets better over time without manual retuning. |

Additional specialists (e.g. entry/exit refinement from structure) can sit under trade synthesis or lifecycle as needed.

---

## Lead agent: LLM-assisted with user-defined guardrails

- **Lead agent** uses an LLM to reason over context (positions, deployment %, signal confidence, regime, volatility) and suggests **take / skip / size** (or reduce/exit). Specialists (synthesis, lifecycle, risk, portfolio) remain deterministic.
- **User-defined guardrails** constrain what the lead can do. Examples: max position size, never trade certain symbols or sessions, minimum confidence threshold, max daily trades, allowed setup types. Guardrails are **enforced** before any order is sent: the lead’s suggestion is checked against tenant guardrails; if it violates, the action is blocked or downgraded (e.g. size capped).
- Guardrails live in **tenant parameters** (same store as risk/sizing). User Parameters agent manages them; risk/lead read them on every decision. Optional: allow guardrails to be expressed in natural language and compiled into rules (future).

---

## Broker-agnostic execution layer

- TradeAgent must support **multiple brokers**: IBKR, Tastyworks, Schwab, Tradestation, Alpaca, ToS (TDAmeritrade).
- **Canonical order model:** All internal logic speaks a single, broker-agnostic format. Example: “BUY 1000 AAPL limit @ 170 day” → `{ side: BUY, symbol: AAPL, quantity: 1000, order_type: LIMIT, limit_price: 170, time_in_force: DAY }` (plus optional stop, bracket, etc.). Lifecycle and synthesis output only canonical orders.
- **Translation layer:** A generic **broker adapter** (or adapter per broker) translates canonical orders into broker-specific API calls. One interface (e.g. `submit_order(canonical)`, `cancel_order(id)`, `get_positions()`) implemented by IBKR adapter, Tastyworks adapter, Schwab adapter, etc. TradeAgent never contains broker-specific API details; those live in adapters.
- **MCP option:** Broker-specific logic can be exposed via **MCP servers** (one per broker or one multi-broker MCP). The lead or an “execution” agent calls MCP tools like `submit_order(side, symbol, qty, ...)`; the MCP server translates to the connected broker. This keeps broker credentials and API code out of TradeAgent and allows users to “connect their broker” by configuring the appropriate MCP. Alternative: adapters as a **library layer** inside TradeAgent with broker API keys in tenant config. Both are valid; MCP favors pluggability and user-owned broker connections.

**Broker connection UX (MCP):** Many brokers (e.g. Tradestation) offer their own MCP servers. The client must be able to **enter credentials** and **connect/disconnect** easily. Flow: tenant adds broker connection (e.g. Tradestation MCP), supplies credentials (stored per-tenant, encrypted); TradeAgent connects to the broker MCP and shows status (connected / disconnected / error). Disconnect clears or revokes the session without deleting stored credentials so the user can reconnect. Optional: per-broker “test connection” and last-successful sync time for monitoring.

**Multiple brokers per tenant:** A tenant can **connect multiple brokers** at once (e.g. IBKR, Schwab, Alpaca, TastyTrade, Tradestation). Each connection has an id (e.g. `broker_connection_id`), credentials, and status. Portfolio view can aggregate positions and P&L across all connected brokers, or show per-broker. Risk and allocation limits apply at **tenant level** (across brokers), not per-broker, unless the user opts into per-broker caps.

**Rule-based broker routing:** Orders are **routed to a specific broker** by **rules** the user configures. Examples: “crypto → IBKR”; “SPX options → Schwab”; “equity futures → Alpaca”; “everything else → TastyTrade.” Rules are **evaluated in priority order**; first match wins. Each rule has:
- **Conditions:** e.g. `asset_class = crypto`; `instrument_type = option` AND `underlying` matches pattern (e.g. SPX, SPXW); `asset_class = equity index` AND `instrument_type = future`; or symbol allowlist/blocklist.
- **Target:** `broker_connection_id` (which connected broker gets the order).
- **Priority:** order of evaluation (e.g. 1 = crypto→IBKR, 2 = SPX options→Schwab, 3 = equity futures→Alpaca, 4 = default→TastyTrade).
A **default/fallback** rule (e.g. “send to TastyTrade”) catches any order that matches no higher-priority rule. If no rule matches and no default is set, the order is rejected with reason “no broker route” (and optionally require the user to add a rule).

**Routing flow:** When the execution layer receives a canonical order (symbol, instrument_type, asset_class, etc.), it runs the tenant’s routing rules, resolves `broker_connection_id`, then calls that broker’s adapter/MCP to submit. Order and fill records store `broker_connection_id` so we know which broker executed what. Lifecycle and positions: we track per broker; aggregation for portfolio/risk is across brokers for the tenant.

**Rule management:** Rules are per-tenant, stored with tenant parameters (or a dedicated `broker_routing_rules` table). UI: list rules, add/edit/delete, reorder priority, set default broker. Validation: at least one default or ensure every possible (asset_class, instrument_type) is covered so no order is dropped silently.

---

## Portfolio monitoring and position visibility

- **Real-time portfolio tools:** TradeAgent (or a dashboard/API consumed by the user) must support **real-time monitoring** of positions originating from this process. That implies: (1) **Position feed** — positions and P&L from the broker, refreshed in real time (via MCP tools like `get_positions`, `get_account`, or broker streaming). (2) **Portfolio tools** — either MCP tools the lead/agents call (e.g. “current positions”, “buying power”) or a dedicated read-only API/UI so the user sees positions, exposure, and TradeAgent-attributed P&L. Both agent use and user visibility may be needed.
- **Segregation when account is comingled:** A single broker account may hold both **TradeAgent-managed** trades and other activity (manual, another system). We need to **segregate** which positions/orders belong to TradeAgent so risk, reporting, and lifecycle only consider “our” slice. Options: (1) **Order tagging** — every order sent by TradeAgent includes a tag or comment (e.g. `source=TradeAgent`, `strategy_id=...`). Broker reports positions; we attribute by matching fills to our orders or by lot/position tags if the broker supports it. (2) **Position attribution** — for accounts that don’t support tags, maintain an internal ledger of “our” opens/closes and derive a synthetic “TradeAgent position” per symbol. (3) **Sub-accounts** — use broker sub-accounts for TradeAgent if available (cleanest). Outcome: user sees total account in broker; TradeAgent UI/API shows only **TradeAgent-attributed** positions and P&L for monitoring and guardrails.

---

## Trade linkage (multi-leg, pairs, groups, position allocation)

- **Logical grouping of positions:** Users may run **pairs trades** (e.g. long AAPL vs short MSFT), **multi-leg options** (spreads, straddles), or **market-neutral** baskets. Positions (or **fractions** of a position) must be **logically tied** to a single “trade” or strategy so P&L and risk can be per-leg, per-trade, or per-group.
- **Position fraction allocation:** A single broker position (e.g. 5000 shares AAPL long) may be split across **multiple logical trades**. Example: 3000 shares allocated to “pairs trade AAPL/MSFT” (with 2000 MSFT short) and 2000 shares to “single-name long AAPL.” We need: (1) **Trade linkage** — a logical trade (or “strategy leg”) that groups one or more legs (e.g. AAPL long + MSFT short). (2) **Allocation of quantity** — each leg has a quantity; a single broker position can have multiple allocations (e.g. 5000 AAPL → 3000 to trade_id=A, 2000 to trade_id=B). (3) **P&L and risk per logical trade** — so the user and the lead agent can see P&L by pair/spread and enforce limits per strategy type.
- **Grouping cardinality (1:1, 1:many, many:many):** (1) **1:1** — One logical trade = one leg (single-name equity or single option). (2) **1:many** — One group has many legs (e.g. pairs: AAPL long + MSFT short; spread: long call + short call); one group_id, managed together. (3) **Many:many** — Legs can belong to multiple groups (e.g. AAPL long in "Pairs AAPL/MSFT" and in "Tech basket"). **Group** = named collection of legs (id, name, type: pairs | spread | basket | custom). Use cases: P&L by group, risk limits per group, close/adjust as a group.
- **Managed as a group:** (1) Group-level P&L across all legs. (2) Group-level risk (delta/gamma for options; notional/beta for baskets). (3) Group-level lifecycle: "close group" = close all legs (order may matter for options); "move stop" may apply to equity leg(s) of covered call. (4) Group-level guardrails: max open pairs, max option premium at risk. Lead and risk reason at group level when appropriate.
- **Options vs equities:** Groups can mix equity and option legs (covered call, collar, pairs with options on one side). Each leg has **instrument_type** (equity | option) and for options: underlying, strike, expiry, right. Allocation and linkage same as above; execution uses equity vs option order types per leg. Risk/P&L per-leg and per-group; greeks when broker provides them.
- **Implementation sketch:** Entities: `position`, `position_allocation`, `trade`, `leg` (trade_id, symbol, side, quantity, instrument_type, group_ids[]), `group` (id, name, type). Supports single-name, pairs, multi-leg options, baskets, mixed equity+option strategies.

**Brainstorm — open questions**

- **Group types:** Fixed set (pairs, spread, basket, covered_call, collar, custom) vs user-defined? Fixed simplifies UI and risk templates.
- **Who creates groups?** User only? Lead when opening multi-leg? Or both (user can merge trades into a group after the fact)?
- **Close order for options:** Spread close = simultaneous OCO or sequential? Broker MCP may dictate; need group-close policy per type.
- **DerivAgent:** Groups with option legs — created in TradeAgent (DerivAgent supplies greeks) or in DerivAgent with link to TradeAgent for equity legs? Document as integration point.

---

## Confidence → allocation (draft)

- Max single-trade allocation cap (e.g. 20% of portfolio).
- Confidence score (e.g. 0.70–1.0) maps to % of that cap: e.g. 1.0 → 100%, 0.70 → 50%.
- Implemented by portfolio/sizing logic (portfolio optimizer + trade synthesis).

---

## Signal and universe filtering

Customers need to **act only on signals in certain assets or segments** — not every symbol IndicAgent covers. TradeAgent must support configurable **include/exclude** filters so the lead and execution pipeline never consider out-of-universe signals.

- **Asset class:** Include or exclude by **asset class** (e.g. equity index only; no FX; metals + energy only). IndicAgent instrument set maps to classes (equity index, energy, metals, rates, volatility, ag, FX, crypto); tenant config holds allowed_asset_classes or excluded_asset_classes. Signal ingestion or validation agent drops any signal whose symbol is not in the allowed set.
- **Securities / symbols:** **Allowlist** (only these symbols) or **blocklist** (all except these). Examples: “only ES, NQ, CL”; “no single-name equities, only indices”; “exclude VX.” Stored per-tenant; applied before sizing and lead.
- **Sectors (equity):** For equity symbols, filter by **sector** (e.g. technology only; exclude financials). Requires symbol → sector mapping (from broker, IndicAgent, or static table). Optional: “only sectors X, Y” or “exclude sectors A, B.”
- **Combined rules:** Filters can be combined (e.g. asset class = equity index AND sector in [technology, healthcare] AND symbol not in blocklist). Evaluation order: asset class → sector (if applicable) → symbol allow/block. Any fail = signal dropped with reason (e.g. “excluded_asset_class”) for audit.
- **Where it runs:** **Signal ingestion or validation agent** applies universe filters first; only in-universe signals proceed to sizing, portfolio, and lead. Filter results (dropped count, drop reasons) are observable and can feed reporting (“we ignored 50 signals today due to universe filter”).

---

## Customer problems and feature ideas

Features organized by customer problem area: execution, management, lifecycle, portfolio, risk, and **profitability/alpha metrics**. These inform prioritization and UX.

**Trade execution**

| Customer problem | Feature idea |
|------------------|--------------|
| “I get too many fills at bad prices.” | Limit/default order types; optional limit-offset from signal price; fill quality metrics (slippage vs signal price). |
| “I want to scale in/out, not all at once.” | Scale-in/scale-out templates (e.g. 50% at open, 50% on pullback); partial fills tracked per trade. |
| “Different brokers, one place to trade.” | Broker-agnostic layer + MCP; **multiple brokers per tenant**; **rule-based routing** (e.g. crypto→IBKR, SPX options→Schwab, equity futures→Alpaca, rest→TastyTrade) so the right orders go to the right broker automatically. |
| “I don’t want to trade certain times or symbols.” | Session filters (e.g. no first 15 min); symbol/asset/sector filters (see Signal and universe filtering). |

**Trade management**

| Customer problem | Feature idea |
|------------------|--------------|
| “I lose track of open positions and stops.” | Real-time position feed; TradeAgent-attributed positions only; stop/target visible per position; “managed as group” for pairs/spreads. |
| “Stops are too tight or too loose.” | Timeframe cascade (1m→5m→15m→1H) with tenant-tunable ATR multipliers; regime-adaptive stop width (existing). |
| “I want to move to BE or trail without watching.” | Lifecycle agent: BE at 2:1, trail by structure; optional “trail to 1m low” or “graduate to 5m stop” (existing). |
| “Multi-leg trades are a mess.” | Trade linkage and groups; group-level close, P&L, and risk (existing). |

**Trade lifecycle**

| Customer problem | Feature idea |
|------------------|--------------|
| “I don’t know why a trade was taken or closed.” | Audit trail per order (signal_id, lead reason, guardrail pass); decision flow view (trace_id); trade journal narrative (existing). |
| “Rolling futures is manual and error-prone.” | Roll agent: days_to_expiry logic, suggest or execute roll; optional roll calendar (existing). |
| “Reconciling with my broker is painful.” | Reconciliation agent: compare ledger to broker positions/fills; break report and alerts (existing). |

**Portfolio management**

| Customer problem | Feature idea |
|------------------|--------------|
| “I’m over-concentrated in one name or sector.” | Portfolio optimizer: max % per symbol, per sector, per asset class; diversification checks (existing). |
| “I take too many similar trades.” | Repetitive/overlap rules: max open per symbol, per group, per setup type (existing). |
| “I can’t see allocation vs buying power.” | Portfolio dashboard: exposure by symbol/sector/class; buying power; utilization %. |
| “I want different sizing for different strategies.” | Per-group or per-setup max size; confidence→allocation curve (existing); optional curve per setup. |

**Risk management and analysis**

| Customer problem | Feature idea |
|------------------|--------------|
| “I blow up when vol spikes or regime flips.” | Risk agent: regime/vol from IndicAgent; cut or reduce on regime change or vol spike; volatility-based sizing (existing). |
| “I need hard limits I can’t override by mistake.” | User and system guardrails; deterministic risk/portfolio checks; kill switch (existing). |
| “I want to see risk before it’s too late.” | Risk dashboard: current exposure, drawdown, margin, guardrail status; alerts when approaching limits. |
| “Why did risk block this trade?” | Audit: every block logged with reason (e.g. max_drawdown, symbol_limit); visible in decision flow and reports. |

**Profitability, alpha, and strategy metrics**

| Customer problem | Feature idea |
|------------------|--------------|
| “I don’t know if I’m making money or which setups work.” | **P&L and win-rate metrics:** Realized P&L, unrealized P&L; **win rate %** (by setup, symbol, sector, timeframe); **avg win vs avg loss**; trade count. Dashboard and reports (existing P&L agent; extend with win-rate and strategy breakdown). |
| “I want to know my alpha, not just raw returns.” | **Alpha / benchmark metrics:** Compare account or strategy returns to a benchmark (e.g. SPY, zero); **alpha**, **beta**, **Sharpe** (rolling). Optional: attribution (how much came from which setup or symbol). |
| “I want to track every trade from signal to outcome.” | **Trade tracking:** End-to-end trace: signal_id → lead decision → order → fill → lifecycle (BE, trail, exit) → outcome (MAE, MFE, pnl_r, outcome class). Queryable and visible in audit/decision flow; feeds learning and reporting. |
| “Which strategies actually work?” | **Strategy performance view:** Per setup (and optionally per symbol/sector): win rate %, avg pnl_r, Sharpe, sample size, recent trend (e.g. last 30 days). Learning agent already updates weights from this; surface in **Learning dashboard** and in a dedicated **Strategy performance** report. “Strategies that work” = sort/filter by win rate or Sharpe; highlight setups above threshold. |
| “I want to improve over time.” | Learning/self-improvement (existing): weights, confidence→sizing, validation thresholds updated from outcomes; promotion gates and rollback. Reporting: “what changed and why” in learning dashboard. |

---

## Connection to IndicAgent

- **Preferred:** TradeAgent subscribes via **API/SSE** (no direct Redis). Clean separation, independent deploy.
- **Alternative:** Separate app subscribing to the Redpanda hot bus for lowest latency (still no execution code inside IndicAgent).

**Data consumed (beyond signals):** Risk manager and sizing logic need live **volatility** and **regime** from IndicAgent, e.g.:
- Volatility: ATR, GARCH volatility, MTF volatility (I1/I4).
- Regime: HMM regime, regime probability, regime duration (I6 SMC).
- Enables: regime-based cut/reduce, volatility-based position sizing, and reaction to extreme vol or regime shift.

---

## Connection to DerivAgent

- DerivAgent is derivatives-focused; relationship to TradeAgent (shared execution layer, shared agents, or separate) TBD.

---

## Observability, human-in-the-loop, guardrails, and security

**Observability**

- **Agent observability:** Every agent (lead, synthesis, lifecycle, risk, portfolio, parameters) should be observable: (1) **Structured logging** — agent name, tenant_id, input summary, decision summary, latency, errors. (2) **Metrics** — counters (decisions taken/skipped/blocked), gauges (open positions, queue depth), histograms (latency per agent). (3) **Trace context** — one trace_id per “decision flow” (e.g. signal received → lead → synthesis → risk → order or skip) so we can follow a single signal end-to-end. (4) **Audit trail** — immutable log of every suggested action, guardrail check, and order (submitted, cancelled, rejected) with timestamp and tenant. Enables debugging, compliance, and tuning.
- **Dashboards and alerts:** Real-time view of agent activity, guardrail hits, order rate, and errors. Alerts on repeated guardrail violations, failed broker calls, or anomalous decision rate.

**Human in the loop (HITL)**

- **Modes:** (1) **Fully autonomous** — lead suggests, guardrails enforce, orders go out without human approval. (2) **Approve-before-send** — lead suggests; human must approve (or reject) each order or each “batch” (e.g. once per session). (3) **Advisory only** — lead suggests; no orders sent automatically; human copies or executes manually. Mode is a per-tenant (or per-symbol) parameter.
- **Surfaces:** Notifications (e.g. “Lead suggests BUY 100 AAPL limit 170 — approve?”) with one-click approve/reject; optional “reason override” (human can reduce size or cancel). Pending suggestions visible in UI with timeout (e.g. expire in 5 minutes if not approved). History of approved/rejected suggestions for review.
- **Override and emergency:** Human can **override** — cancel open orders, flatten a position, or pause the lead for a tenant. “Kill switch” to disable all automated trading for a tenant or globally. Override actions are logged and (where possible) require confirmation.

**Guardrails (beyond user-defined limits)**

- **User-defined guardrails** (already above): max size, banned symbols, min confidence, max daily trades, etc., enforced before any order.
- **System guardrails:** (1) **Output validation** — lead output (e.g. “BUY 1000 AAPL”) is parsed into canonical form and validated: symbol in allowed list, quantity and price in sane bounds, order type allowed. Reject malformed or out-of-range before sending to broker. (2) **Rate limits** — max orders per minute per tenant; max open orders per symbol. (3) **Circuit breakers** — if error rate from broker or agent exceeds threshold, pause automated trading for that tenant until acknowledged. (4) **Deterministic checks** — risk and portfolio run after lead; their “no” overrides lead “yes.” Guardrails are the single gate before execution.

**Security and injection protection**

- **Prompt injection:** The lead agent receives context (signals, positions, regime). Any external or user-supplied text (e.g. symbol names, comments, strategy names) that is embedded in prompts must be **sanitized and delimited** so it cannot be interpreted as instructions. Practices: put user content in clearly marked blocks (e.g. `<user_content>…</user_content>`); avoid passing raw user input as system prompt; limit prompt scope to structured fields (e.g. symbol, quantity) and reject free-form text in critical paths.
- **Tool/API injection:** Agent “tools” (e.g. submit_order, get_positions) must be called with **structured arguments only** (typed, validated). No passing raw LLM output as command strings. Parse LLM output into a fixed schema; validate and allowlist (e.g. symbol must match known list, side is enum BUY/SELL). Reject any call that doesn’t match schema or passes disallowed values.
- **Broker and tenant isolation:** Broker credentials and API keys per tenant; never log or expose to other tenants. MCP or adapter calls are scoped to the tenant’s connection. Inputs from IndicAgent (signals, regime) are treated as untrusted for purposes of injection: validate and type-check before use in prompts or decisions.
- **Audit and least privilege:** All order submissions and parameter changes are audited. Service accounts and MCP credentials have least privilege (e.g. trade-only, no withdraw). Optional: require 2FA or approval for sensitive parameter changes (e.g. guardrail relaxation, new broker connection).

---

## Renaissance-style: what TradeAgent would need

If Jim Simons / Renaissance were building this, the system would emphasize **data first**, **signal validation before scale**, and **self-improving feedback** — same principles as IndicAgent v1.4, applied to execution and agent behavior.

- **Validation before scale:** Don’t let every signal trade. A **signal-quality** or **validation** agent (or step) scores incoming signals against historical outcome data (e.g. this setup on this symbol/TF has win rate X, Sharpe Y). Only signals that clear a statistical bar get sized and sent to the lead. “Most signals are discarded unless statistically valid.”
- **Data first:** Every fill, every order, every guardrail hit is data. Store it. Trade ledger, order log, and agent decision log feed **research and feedback**. No “we’ll add analytics later” — the pipeline is the source of truth for what the system did and why.
- **Self-improving:** Feedback loop from outcomes into sizing, setup ranking, and (optionally) lead behavior. Reporting and **research agents** consume outcome data; **learning/feedback agent** or scheduled jobs update weights, thresholds, or flags. Managers and algorithms “monitor current conditions” via dashboards and reports, not manual one-offs.
- **Minimal discretionary overlay:** Guardrails and deterministic risk/portfolio checks are the guard. The lead can reason, but it cannot override hard limits. Human-in-the-loop is for exceptions and kill switch, not for cherry-picking trades.
- **Research-to-production path:** New strategies or setups should be validated (backtest, walk-forward) before they are allowed to trade. A **research/backtest agent** (or integration with IndicAgent’s validation script) gates “promotion” of a new setup or parameter set into live guardrails.

---

## Learning and self-improvement (key feature)

Learning and self-improvement is a **first-class capability**: the system gets better from its own outcomes, with guardrails so updates are safe and auditable.

**What feeds learning**

- **Outcome data:** Resolved trades (pnl_r, outcome class, MAE, MFE, bars_in_trade), guardrail hits (what was blocked and why), shadow signals (regime-suppressed signals and their would-be outcomes from IndicAgent/signal_ledger). Order and fill history. Attribution by setup, symbol, timeframe, group.
- **Agent decision log:** What the lead suggested, what risk/portfolio allowed or blocked, latency and error rates. Enables “would we have done better with different thresholds?”

**What gets updated (and how)**

- **Setup weights / ranking:** Which setups get more or less capital or priority (e.g. aggregator-style weights). Updated from rolling performance (win rate, Sharpe, sample size). **Promotion gate:** Only apply weight updates after minimum resolved count (e.g. 30 trades per setup) to avoid overfitting on tiny samples.
- **Confidence → sizing curve:** Map from signal confidence to % of max allocation. Learning agent can tune this from outcome data (e.g. “0.75 confidence has historically done better with 70% allocation than 50%”). Changes are parameter updates in tenant config; can require human approval for large shifts.
- **Validation thresholds:** Min confidence or min historical win rate for a setup/symbol/TF to be “accepted” by the signal-validation agent. Updated from shadow and resolved data; again with promotion gate (enough data before relaxing or tightening).
- **Lead behavior (optional):** If the lead is tuned via few-shot or prompt parameters, learning can suggest prompt or rule updates from “what worked” vs “what was rejected or lost.” Human approval before deploying prompt changes.

**Safety and audit**

- **No live trading in the loop:** Learning runs on stored data (scheduled or on-demand). It does not execute orders; it updates parameters or suggests updates. Execution path stays: signal → validation → lead → risk → portfolio → order.
- **Promotion gates:** Every learned update (weight, curve, threshold) should respect a **gate**: e.g. minimum sample size, minimum improvement vs baseline, or human approve for first deployment. Prevents one bad week from shifting the system off a cliff.
- **Versioning and rollback:** Learned parameters are versioned. If a new set underperforms (e.g. next week’s P&L drops), tenant or ops can **roll back** to a previous parameter set. Audit log: who/what updated which parameter, when, and what the previous value was.
- **Per-tenant:** Learning can be **per-tenant** (each tenant’s outcomes drive that tenant’s weights and curves) or **global** (shared research, tenant opts in). Configurable.

**Learning agent in the pipeline**

- The **Learning / self-improvement** agent (or scheduled job) runs periodically (e.g. daily post-session). It reads outcome and attribution tables, computes new weights/curves/thresholds, and either (1) writes to a “pending” store for human approval, or (2) applies within guardrails (e.g. max change per day, no change without N new resolved trades). Reporting agents can surface “what changed and why” in the learning dashboard or report.

---

## Agenticizing the full lifecycle (pre, trade, post)

**Pre-trade**

- **Signal ingestion & validation agent:** Consumes IndicAgent stream; validates schema and freshness; optionally scores signal quality vs historical outcomes (Renaissance “discard unless valid”). Output: accepted signal or drop + reason.
- **Routing agent (optional):** Decides which strategy or group a signal belongs to (e.g. equity trend vs pairs). Informs sizing and which lifecycle/group to attach to.
- **Sizing & portfolio (existing):** Confidence → allocation; portfolio checks (repetitive, overlap, limits). Already agentic; can be refined with volatility- and regime-adjusted sizing.
- **Lead (existing):** Take/skip/size after risk and portfolio context. Pre-trade “last gate” before order.

**Trade (in-life)**

- **Trade lifecycle agent (existing):** Stop cascade, BE, trail, timeframe graduation. Manages open positions.
- **Stop-management agent (specialist):** Can be part of lifecycle or separate. Focused on “when to move stop,” “when to graduate timeframe,” “when to take partial.” Uses structure and regime from IndicAgent.
- **Rebalance agent (optional):** For baskets or pairs, monitors drift (e.g. hedge ratio, beta). Suggests or executes rebalancing orders. More relevant for multi-leg and market-neutral.
- **Roll agent (futures):** As expiry approaches, suggests or executes roll (close front, open next). Consumes days_to_expiry and roll logic; can be rule-based or LLM-assisted for timing.

**Post-trade**

- **Reconciliation agent:** Compares our ledger (what we think we have) to broker positions and fills. Flags breaks; triggers alerts or pauses. Runs periodically or on demand.
- **Attribution agent:** Attributes P&L to strategy, setup, symbol, timeframe. Feeds reporting and feedback. Output: tables or streams for “PnL by setup,” “PnL by group.”
- **Reporting agents:** Produce **scheduled or on-demand reports**: daily P&L, risk summary, trade journal narrative (e.g. “today’s trades and why”), guardrail hit summary, agent activity summary. Can be LLM-generated (narrative) or deterministic (tables). Output to dashboard, email, or audit store.
- **Learning / self-improvement agent:** (See dedicated section above.) Consumes outcome data, updates setup weights, confidence→sizing curves, and validation thresholds. Closes the loop so the system improves over time; runs with promotion gates and optional human approval.

---

## Agent dashboards and ops

- **Agent control plane:** Per-tenant (or global) view of **all agents** with **on/off** and **config**.
  - **Spin up / turn off:** Enable or disable each agent (lead, synthesis, lifecycle, risk, portfolio, validation, reporting, etc.) per tenant. Disabling lead effectively pauses automated trading; disabling reporting stops report generation. Useful for testing, maintenance, or “advisory only” mode.
  - **See what they’re doing:** For each agent: **status** (running, paused, error), **last run** (time and summary: e.g. “Lead: suggested BUY AAPL 100 @ 170”), **queue depth** (if applicable), **recent errors**. Live tail of decisions or link to trace_id for full flow.
  - **Config per agent:** Link to tenant parameters that affect that agent (e.g. guardrails for lead, cascade params for lifecycle). Edit in one place; agent reads on next run or after reload.
- **Agent dashboard UX:** Dashboard (or dedicated “Agent ops” view) with:
  - **Agent cards** — one card per agent: name, on/off toggle, last activity, latency, error count, “View recent decisions” / “View config.”
  - **Decision flow view** — for a given signal or time range, show which agents ran and what they decided (trace_id → timeline of lead → risk → portfolio → order or skip).
  - **Alerts** — agent down, error spike, guardrail breach, circuit breaker tripped. Surface in same dashboard or in a global alert panel.

---

## Reporting agents and report dashboards

- **Reporting agents:** Dedicated agents (or scheduled jobs with agent-like output) that **produce reports**.
  - **Daily P&L agent:** End-of-day (or on-demand): realized P&L, unrealized P&L, by symbol, by group, by setup. Output: table + optional narrative.
  - **Risk report agent:** Current exposure, VaR-style or notional summary, margin usage, guardrail status. Output: table + alerts if near limits.
  - **Trade journal agent:** LLM or template: “Today’s trades: … Reasons and outcomes.” Consumes trade ledger and optional narrative from IndicAgent. Output: human-readable summary for compliance or review.
  - **Agent activity report:** Which agents ran, how many decisions, how many blocked, latency percentiles. For tuning and ops.
- **Report dashboards:** Dashboards that **consume** agent output (and live data):
  - **P&L dashboard** — positions, P&L by period, by strategy, by symbol. Real-time and EOD.
  - **Risk dashboard** — exposure, limits, guardrail hits, circuit breaker state.
  - **Audit / compliance dashboard** — order history, approval/reject history, overrides, parameter changes. Filter by tenant, date, agent.
  - **Agent ops dashboard** — (above) agent on/off, health, recent decisions, config.
  - **Learning / self-improvement dashboard** — what the learning agent updated (weights, curves, thresholds), when, and why (e.g. “Setup X win rate 0.62 → weight +0.1”). Pending vs applied updates; rollback control. Outcome summaries (win rate by setup, confidence vs outcome) that drive learning.
- **Delivery:** Reports can be **in-app** (dashboard), **emailed** (scheduled), or **exported** (PDF/CSV) for compliance or external use.

---

## Relationship to Existing Architecture

TradeAgent is the autonomous execution application. It is a separate application (own repo) that consumes the shared intelligence bus and executes through broker adapters/MCP:

- **Unified Data Bus compliance** — Services never call each other. TradeAgent subscribes to `signals:*`, `qual:*`, `deriv:*` streams and publishes orders and trade outcomes. No coupling beyond the bus. See `docs/data/` for bus architecture.
- **DAG invariants preserved** — TradeAgent never writes to the intelligence database directly; outcomes flow back through the Signal Ledger Architecture writers. See `docs/concepts/dag-execution.md`.
- **APR-governed** — All sizing curves, guardrails, and validation thresholds live in `config_state` under tenant-scoped namespaces. No hardcoded values. See `docs/foundation/adaptive-parameter-registry.md`.
- **Shadow Governance (SG)** — New setups and learned parameter sets run in shadow before promotion; minimum sample size and statistical gates apply before any live weight change. See `docs/foundation/glossary.md`.
- **Signal Ledger Architecture integration** — Trade outcomes close the compounding loop by writing `actual_pnl_r` to `trade_executions`; the learning loop joins against `signal_ledger` (the SLA join view). See `docs/foundation/glossary.md`.
- **Risk independence** — TradeAgent obeys AegisAgent's binding `risk:*` events (`risk:halt`, `risk:reduce`, `risk:block`); it does not enforce its own hard risk limits. See `docs/research/vision-01-aegisagent.md`.

## Foundation Concepts Referenced

- **Principles** — `docs/foundation/principles.md`: Shadow before production, segment relentlessly, ruthlessly automate manual tasks, never override the model
- **Naming System** — `docs/foundation/naming-system.md`: `TradeAgent` is a product name, not a code class; the underlying daemon classes derive from the naming system when built
- **APR** — `docs/foundation/adaptive-parameter-registry.md`: Guardrails, sizing curves, and validation thresholds governed by APR
- **Documentation System** — `docs/foundation/documentation-system.md`: Idea docs live in `ideas/`, not authoritative until verified
- **Glossary** — `docs/foundation/glossary.md`: SLA, SG, APR, alpha, edge, regime — canonical definitions
- **Renaissance Framing** — `docs/research/renaissance-02-framing.md`: validation before scale, unified model, never override

## References

- `docs/research/signal-04-timeframe-cascade-strategy.md` — stop cascade (1m → 5m → 15m → 1H).
- `docs/research/signal-03-regime-adaptive-trading.md` — regime-aware sizing and gating.
