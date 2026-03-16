# Signal Intelligence Command Center — Design Spec

**Date:** 2026-03-16
**Status:** Approved for planning
**Scope:** Two deliverables — (1) unified signal quality tier system applied across all dashboard surfaces, (2) new `/signals` Signal Intelligence Command Center page

---

## Background & Motivation

The dashboard currently displays signals with confidence scores as low as 11% as hero-level UI elements. Root cause analysis revealed three issues:

1. **Alpha decay (QUAL-02)** on 1m timeframe: FVGFill and TrendFollowing fire every 3 bars (minimum cooldown). With half-life=10 bars, confidence decays to near-zero within 10 minutes of a repeated setup. These alpha-decayed signals are selected via the fallback path (CIS never fires — |cis_score| < 0.35) and rendered with the same visual weight as high-confidence signals.

2. **80% of selected signals are fallback-path selections**: Only 20% of `was_selected=true` rows have `|cis_score| > 0.35`. The other 80% were selected by priority/majority tiebreak when CIS was too weak to fire. The dashboard treats both identically.

3. **No unified quality threshold**: `SignalAlertStrip` gates at 0.65, `SignalBanner` at 0.75, drill panel `RecentSignals` has no gate at all, watchlist rail highlights any unresolved signal regardless of confidence.

**Outcome data verdict** (from `signal_ledger`, N=1.09M selected signals):
Confidence ≥ 0.40 is the empirically derived breakeven — the exact confidence level where avg pnl_r consistently crosses from negative to positive (+0.376 at 0.40–0.50, p < 0.05 at N=32k). Signals below 0.40 have negative or near-zero expected value and should not be presented as actionable.

**What Renaissance would build:** instrument everything (never drop signals), but weight the display by statistical evidence. A signal the pipeline wasn't confident enough to CIS-validate is a candidate for the watchlist and the ledger, not the hero panel.

---

## Deliverable 1 — Unified Signal Quality Tier System

### Three tiers

| Tier | Gate | Meaning | Display treatment |
|------|------|---------|-------------------|
| **Hero** | `confidence >= 0.40 AND cis_score IS NOT NULL AND abs(cis_score) > 0.35` | CIS fired, positive expected value backed by outcome data | Full opacity, blue left-border accent, shown in all hero surfaces |
| **Monitored** | `was_selected = true` AND not Hero | Pipeline selected it via fallback; CIS didn't fire, NULL cis_score, or confidence below breakeven | 85% opacity, no accent, shown in ledger and recent signals panel with "Monitored" badge |
| **Candidate** | `was_selected = false` | Fired but not selected by aggregator | 60% opacity, italic setup name, shown in ledger only, hidden from all hero surfaces |

**NULL cis_score handling:** Signals written before CIS was introduced have `cis_score IS NULL`. These always classify as Monitored (never Hero, never Candidate), regardless of confidence. The three-way tier classification must be evaluated in order: Hero gate first (requires non-null cis_score), then Monitored (was_selected=true), then Candidate.

### API changes — `/api/signals/recent`

Add `tier` query param: `hero` (default for drill panel) | `monitored` | `all`.

- Default (`tier=hero`): `WHERE was_selected = true AND confidence >= 0.40 AND cis_score IS NOT NULL AND abs(cis_score) > 0.35`
- `tier=monitored`: `WHERE was_selected = true`
- `tier=all`: no filter on quality

Add computed `signal_tier` field to response: `"hero"` | `"monitored"` | `"candidate"`.

### Dashboard surface changes

| Surface | Current gate | New gate | Change |
|---------|-------------|---------|--------|
| `SignalBanner` | confidence ≥ 0.75 | Hero tier (conf ≥ 0.40 + CIS fired) | Loosened — 0.75 was arbitrary; 0.40 is data-derived |
| `SignalAlertStrip` | confidence ≥ 0.65 | Hero tier | Loosened slightly; now consistent with overall system |
| Drill panel `RecentSignals` | None | Hero tier by default | **Breaking fix** — no more 11% confidence heroes |
| `WatchlistRail` highlight | Any unresolved signal | Hero tier only | Eliminates false urgency from fallback noise |
| `ConfidenceRing` | None | Show `signal_tier` badge below ring when signal present | Adds tier context without changing ring calculation |
| `SignalScorecard` (competing signals) | None | Visual weight by tier | Candidate signals at 60% opacity; winner badge only on Hero |

### Threshold rationale

`confidence >= 0.40` is derived directly from `signal_ledger` outcome data:
- Buckets 0.00–0.40: avg pnl_r negative (-0.22 to -2.31)
- Bucket 0.40–0.50: avg pnl_r +0.376 (p < 0.05, N=32,429)
- Buckets 0.50–0.70: avg pnl_r +0.14 to +0.21 (statistically significant)

`abs(cis_score) > 0.35` is the existing CIS fire threshold — this requirement eliminates the 80% fallback-path noise population.

This is not an arbitrary aesthetic choice. The threshold is the data.

---

## Deliverable 2 — Signal Intelligence Command Center (`/signals`)

### Page structure

New route: `/signals`. Accessible from main nav. Full-width, vertical scroll. Command strip is sticky.

```
┌─────────────────────────────────────────────────────────┐
│  COMMAND STRIP  (sticky — 6 stat pills)                 │
├─────────────────────────────────────────────────────────┤
│  ATTRIBUTION ROW  (setup alpha left · asset class right)│
├─────────────────────────────────────────────────────────┤
│  CLUSTER STRIP  (hidden unless ≥3 symbols, same bar)    │
├─────────────────────────────────────────────────────────┤
│  FILTER BAR                                             │
├─────────────────────────────────────────────────────────┤
│  SIGNAL LEDGER  (virtualized table)                     │
│  ┌──────────────────────────┬────────────────────────┐  │
│  │  table rows              │  detail panel          │  │
│  │  (click row to expand)   │  (drill panel sidebar) │  │
│  └──────────────────────────┴────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

Filter state is shared — clicking a setup row in the Attribution section pre-filters the Signal Ledger below.

---

### Zone 1 — Command Strip (sticky)

Six stat pills. Each: label + primary value + trend indicator subtext.

| Pill | Primary value | Subtext | Color logic |
|------|--------------|---------|-------------|
| **Signals / session** | Count for current ET session (09:30–16:00) | ↑↓ vs prior session | `--blue` |
| **Hero rate** | % of selected signals that are Hero tier | ↑↓ vs 7d avg | `--amber` if rising, `--text-muted` if falling |
| **Avg confidence** | Session avg confidence (was_selected=true) | ↑↓ vs 7d baseline | `--green` if above baseline, `--red` if below |
| **Pipeline latency** | p50 bar_close → signal_computed_at | p95 in subtext | `--green` if p50 < 10s, `--amber` if 10–30s, `--red` if > 30s |
| **Alpha composite** | Rolling 7d avg pnl_r | ↑↓ vs rolling 30d | `--green` if positive + improving, `--red` if negative or deteriorating |
| **Edge trend** | 7d avg pnl_r − 30d avg pnl_r | "compressing" / "expanding" / "stable" | `--green` if expanding, `--amber` if stable, `--red` if compressing |

**Edge trend** replaces "open signals count" — per Renaissance principle: the question is not how many signals are open, it is whether the system's alpha is growing or decaying.

Data source: single `GET /api/signals/stats` endpoint. Refreshes every 60 seconds.

---

### Zone 2 — Attribution Row

Two side-by-side panels: **Setup Alpha** (left) and **Asset Class Alpha** (right).

#### Setup Alpha table

Columns: Setup · N (resolved) · Win rate · Avg pnl_r · Sharpe proxy · p-value · [regime sparkline]

- **Sharpe proxy**: `avg_pnl_r / std_pnl_r` — penalises high-variance strategies
- **p-value**: one-sample t-test against null hypothesis mean=0. Formula: `p = 2 * (1 - t_cdf(|avg_pnl_r| / (std_pnl_r / sqrt(N))))` where `std_pnl_r = STDDEV(pnl_r)` and `N = COUNT(*)` computed directly from `signal_ledger` in the attribution query (not from `setup_performance` — that table does not expose std_pnl_r). Display as `p=0.031` with `--cyan` highlight if `p < 0.05`.
- **pnl_r distribution**: small inline histogram cell (9 buckets, canvas element, 80×20px) — shows whether edge is clean or outlier-driven
- **Regime breakdown (v2)**: deferred to v2. Requires JOIN to `intelligence_features` on `(symbol, feature_ts, feature_tf)` to access `i4->>'hmm_regime'` (integer: 0=ranging, 1=trending_up, 2=trending_down). Not in v1 scope — consistent with Asset Class table carve-out below.
- Sorted by avg pnl_r descending. Color-coded pnl_r cells (green positive, red negative)
- Clicking a row sets `setup_plugin` filter on the Signal Ledger

#### Asset Class Alpha table

Same columns (without regime breakdown in v1). Groups: Equity Futures · Energy · Metals · Rates · FX · Crypto. Clicking a row sets `asset_class` filter on the Signal Ledger.

Data source: `GET /api/signals/attribution?window=30d`. Computes entirely from `signal_ledger` using `AVG(pnl_r)`, `STDDEV(pnl_r)`, `COUNT(*)` grouped by `setup_plugin` and `asset_class`. The `setup_performance` table is not used — it does not expose `std_pnl_r` and the sharpe_ratio back-computation is algebraically unstable near zero.

---

### Zone 3 — Cluster Detector Strip

Hidden by default. Appears as a collapsible amber strip when ≥3 symbols fire within the same 1m bar on the same timeframe, within the last 5 minutes.

Each cluster card shows:
```
11:56 UTC · 1m · 7 symbols · avg conf 0.12 · 1 distinct setup (FVGFill)
[BTCUSD ETHUSD GBPUSD HGH6 RTYH6 USDJPY ZTH6]
```

**Setup diversity score** is the key Renaissance addition:
- `1 distinct setup / 7 symbols` = correlated event (one latent signal repeated) — shown in amber, labelled "Correlated"
- `5 distinct setups / 7 symbols` = independent confirmation — shown in green/cyan, labelled "Confluence"

A cluster where all signals are the same setup type is one piece of evidence, not seven. A cluster where 5 different setup types agree is genuinely significant.

Clicking a cluster pre-filters the ledger to those signals.

Data source: detected in the frontend from SSE signal stream (`signal_scorecard` events). No new API endpoint needed — already have bar-level signal data.

---

### Zone 4 — Filter Bar

Persistent above the ledger. All filters are multi-select or range:

| Filter | Type | Options |
|--------|------|---------|
| Symbol | Multi-select typeahead | All active instruments |
| Asset class | Pill toggle | All / Futures / FX / Crypto / Equity |
| Setup plugin | Multi-select | All 17 I7 setups |
| Timeframe | Pill toggle | All / 1m / 5m / 15m / 1h / 4h / 1d |
| Quality tier | Pill toggle | All / Hero / Monitored / Candidate |
| Confidence | Range slider | 0.0 – 1.0 |
| CIS fired | Toggle | All / CIS only / Fallback only |
| Status | Multi-select | Pending / Active / Resolved / Suppressed |
| Date range | Date picker | Default: last 7 days |

Filter state serialised to URL params — shareable links.

---

### Zone 5 — Signal Ledger

Virtualized table (react-window or TanStack Virtual). No pagination. Default sort: `signal_computed_at DESC`.

#### Columns

| Column | Field | Width | Notes |
|--------|-------|-------|-------|
| Time | `computed_at` | 90px | `HH:MM:SS` format, date on hover — serialised as `computed_at` in API response (maps to `signal_ledger.signal_computed_at`) |
| Symbol | `symbol` | 70px | Monospace |
| TF | `timeframe` | 40px | |
| Setup | `setup_plugin` | 140px | Strip `trad_` prefix |
| Dir | `direction` | 32px | ▲ green / ▼ red |
| Tier | `signal_tier` | 24px | Colored dot: blue=hero, amber=monitored, muted=candidate |
| Conf | `confidence` | 60px | `0.42` formatted, color by tier breakpoint |
| CIS | `cis_score` | 60px | `+0.41` with sign, green/red |
| Status | `status` | 80px | Badge: pending / active / suppressed |
| Outcome | `outcome` | 100px | Badge with 8-class taxonomy |
| PnL R | `pnl_r` | 60px | `+1.2R` formatted, green/red |

#### Row visual weight

- **Hero**: full opacity, 2px blue left border
- **Monitored**: 85% opacity, no accent
- **Candidate**: 60% opacity, italic setup name

Renaissance principle: nothing is hidden. Everything is visible. Weight communicates quality, suppression does not.

#### Detail panel

Right-side panel slides in on row click (320px, same width and layout as existing drill panel sidebar). Reuses `DrillPanel` component internals — no duplicate build. Shows full signal context: entry/stop/targets, CIS bucket breakdown, regime context, lifecycle events, I1–I6 features.

Close on Escape or click outside.

Data source: `GET /api/signals/recent?tier=all` (existing endpoint, extended). Detail fetched lazily on row click: `GET /api/signals/detail/{signal_id}`. Note: path must be `detail/{signal_id}` not `{signal_id}` — the existing route `GET /api/signals/{symbol}` uses a catch-all path param that would shadow a bare UUID.

---

## API endpoints required

| Endpoint | New / Modified | Purpose |
|----------|---------------|---------|
| `GET /api/signals/recent` | Modified | Add `tier` param, `signal_tier` field in response |
| `GET /api/signals/stats` | **New** | Command strip metrics (throughput, hero rate, latency, alpha composite, edge trend) |
| `GET /api/signals/attribution` | **New** | Setup and asset class alpha table with p-value, regime breakdown |
| `GET /api/signals/detail/{signal_id}` | **New** | Full signal detail for ledger row expansion |

---

## Design system

Inherits existing dashboard CSS variables:
- Background surfaces: `--bg-base` / `--bg-surface` / `--bg-elevated`
- Tier colors: Hero = `--blue`, Monitored = `--amber`, Candidate = `--text-muted`
- Alpha: `--green` (positive pnl_r), `--red` (negative)
- Typography: Outfit (labels/headings), JetBrains Mono (numeric values)
- p-value significance: `--cyan` highlight on cells where `p < 0.05`

No new design tokens required.

---

## What this is NOT

- Not a trading execution interface — no order buttons, no position sizing
- Not a replacement for the main trading dashboard — that stays focused on live per-symbol intelligence
- Not a backtest engine — uses live `signal_ledger` data only

---

## Success criteria

1. No signal with confidence < 0.40 or |cis_score| < 0.35 renders as a hero on any dashboard surface
2. Signal Intelligence page loads with full ledger in < 2s (virtualization, server-side filter)
3. Attribution table shows statistically significant edge (p < 0.05) for at least the top 3 setup plugins by volume
4. Cluster detector correctly identifies correlated vs confluence clusters (setup diversity score)
5. All existing functionality preserved — no signal data is hidden, only weighted
