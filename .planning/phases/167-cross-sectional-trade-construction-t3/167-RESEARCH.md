# Phase 167: Cross-Sectional Trade Construction (T3) - Research

**Researched:** 2026-07-26
**Domain:** Internal quant-research batch measurement service (Python/asyncpg/TimescaleDB) —
no external library integration, no new third-party dependency
**Confidence:** HIGH (every claim below is verified against live code, live schema, or live DB
queries in this repo — no external ecosystem research was needed for this phase)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Rank the cross-sectional universe directly on `ctf_momentum`, NOT on
  `ensemble_alpha`/the linear IC-weighted combiner output. Hard architectural distinction —
  `ensemble_alpha` is the already-failed Gate 2 construction; this phase is a parallel
  measurement path, not a consumer of it.
- **D-02:** Ship v1 wired specifically to `ctf_momentum` — single feature, no composite
  ranking score. Do NOT generalize to multi-feature in this phase.
- **D-03:** Rebalance every bar, exactly matching T3's measured construction (mean one-way leg
  turnover ~19.5%/bar, median ~6.25%). Do NOT implement the cost-floor-gated
  rebalance-on-ranking-change optimization in this same pass — that is a deferred fast-follow.
- **D-04:** `tf=15m` only, full active equity universe (`i.is_active=true AND
  i.contract_details->>'asset_class'='equity'`, currently 80 symbols). No other tf or asset
  class in this phase.
- **D-05:** Cost-hurdle treatment is already validated and settled as a *methodology* (apply
  todo 030's blended round-trip cost-floor convention — 1/3/5/10bp — to the construction's
  *actual measured turnover*, not a flat per-trade cost). The production service must still
  **compute** this net-of-cost calculation live every run, not hardcode "it survives" as a
  static conclusion.
- **Folded todo 185** (causal per-entity demeaning primitive) — reviewed below (see Open
  Questions): not directly required by this phase's construction or gate math.
- **Folded todo 186** (cross-sectional block-bootstrap gap) — reviewed in depth below (see
  "Todo 186 Scope Assessment"). Verdict: **not required for this phase's Validation Gate 1**;
  scope as a separate follow-on, not a Phase 167 task.

### Claude's Discretion

None stated as open discretion in CONTEXT.md beyond what the phase description and research
questions ask — CONTEXT.md's `<specifics>` section states this phase's only open question is
"how do we build and monitor it in production shape," which this document answers.

### Deferred Ideas (OUT OF SCOPE)

- Multi-feature composite ranking (D-02)
- Cost-floor-gated rebalance-on-ranking-change (D-03)
- Additional timeframes/asset classes (D-04) — 5m/1h/1d, rates/commodity/fx
- Kelly-fraction sizing, risk modeling, borrow-cost modeling (trade-construction-layer.md's own
  "What This Explicitly Defers")
- Portfolio state/sizing/execution infrastructure (Phase 156-159 — explicitly gated behind this
  phase's outcome)

</user_constraints>

<phase_requirements>
## Phase Requirements

No formal `REQUIREMENTS.md` IDs exist for this phase (standing-doc-driven phase, same pattern
as Phase 163). Governance is the canonical references listed in CONTEXT.md — the design in
`docs/research/trade-construction-layer.md` (Minimal Design, six numbered steps 1-6, and the
three-item Validation Gates section) *is* this phase's requirements list. Mapping:

| Design-doc requirement | Research support |
|---|---|
| Step 1: Input (calibrated conviction vector) | D-02 narrows this to raw `ctf_momentum` z-scores — "uncalibrated z-scores can rank... but cannot size" is explicitly fine for v1 per the doc's own text |
| Step 2: Ranking → buckets | Confirmed exact mechanic in T3 script's `_decile_spread_per_bar`/`_legs_per_bar` — see Code Examples |
| Step 3: Weights | Doc's v1 calls for vol-scaled equal-weight; T3's proven script uses **flat equal-weight, no vol-scaling** — flagged as a real gap, see Common Pitfalls #1 |
| Step 4: Netting | Dollar-neutral within tf, single-tf scope makes cross-tf netting N/A this phase |
| Step 5: Rebalance rule | D-03 overrides the doc's stated cost-floor-gated rule for v1 — replicate exact per-bar rebalance |
| Step 6: Measurement | Portfolio-level, vs. flat and shuffled-ranking null — T3's script already implements the null; the shadow measurement service must persist the same and add the flat-benchmark comparison (currently absent from the script, see Open Questions) |
| Validation Gate 1 (net-of-cost spread Sharpe > 0 at 95% CI, beats null) | Directly measurable with existing `frame_gate_passes` — see "Todo 186 Scope Assessment" |
| Validation Gate 2 (attribution honesty — not a static factor tilt) | **Not yet implemented anywhere** — new work this phase must scope, see Open Questions |
| Validation Gate 3 (comparison to DiscreteTrack directional) | Already satisfied — this comparison IS T2 vs T3, already run and recorded in `data-edge-source-thesis.md` |

</phase_requirements>

## Summary

This phase turns a proven one-off analysis script
(`scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py`) into a real,
recurring, monitored measurement service, following this codebase's own established
`BaseBatch` pattern to the letter. The closest and most load-bearing analog is
`services/counterfactual_tracker.py`: a `BaseBatch` subclass that (a) computes and persists a
per-bar/per-frame outcome, and (b) exposes a separate, read-only `--evaluate-gate` CLI mode
that groups persisted rows into day-clusters and runs the identical `frame_gate_passes`
day-clustered BCa/CLT bootstrap the T3 script already reuses verbatim. `services/alpha_scorer.py`
is the second analog and answers the "should this be on a systemd timer" question directly: it
states in its own module docstring that it is a **manual/on-demand oneshot, deliberately NOT
registered on a systemd timer**, because its deliverable is a shadow-mode diagnostic still
earning its way toward production consideration — exactly this phase's posture per CLAUDE.md's
"prove edge before production infra" principle.

No new external package, library, or framework is needed anywhere in this phase — it is 100%
internal Python/asyncpg/TimescaleDB, reusing four already-proven primitives verbatim
(`frame_gate_passes`, `BaseBatch`, `_load_apr_dict_async`/`cfg`, the T3 script's own
construction math). The one genuine gap is schema: no existing table has the right shape to
persist a per-bar cross-sectional spread with leg membership and turnover, so this phase needs
exactly one new migration (a new hypertable, following migration 205's `alpha_frames` template
almost line-for-line) plus one APR-seeding block under a new `alpha.construction.*` namespace
(the doc's own stated namespace, e.g. `alpha.construction.n_legs`).

Two locked-decision follow-ups from CONTEXT.md were investigated in depth and can be closed
out here: todo 186 (cross-sectional block bootstrap) is **not required** for this phase's
Validation Gate 1 — the day-clustered bootstrap `frame_gate_passes` already uses is exactly
what a *portfolio-level* (not pooled-panel) time series needs, and is what T3's script and
`counterfactual_tracker.py`'s existing gate-evaluation both already do. Todo 186's actual target
(a pooled multi-symbol panel IC bootstrap) is a different statistical object than "one spread
return per bar" and is not on this phase's critical path. Todo 185 (causal per-entity
demeaning) is also not needed — T3 does not pool absolute per-symbol predictions the way T5's
non-linear combiner does; the construction ranks within each bar, which needs no
per-entity-mean subtraction.

**Primary recommendation:** Build `services/cross_sectional_spread_tracker.py` as a `BaseBatch`
oneshot (invoked on-demand/nightly via cron/manual run, NOT systemd-timer-scheduled at this
phase, matching `alpha_scorer.py`'s explicit precedent) that (1) incrementally computes and
persists one row per `(tf, bar_ts)` into a new `construction_spreads` hypertable — gross/net
spread at both lookahead scales, leg membership, realized turnover — and (2) exposes a
`--evaluate-gate` mode reusing `evaluate_frame_gate`/`frame_gate_passes` verbatim to compute
Validation Gate 1's day-clustered bootstrap CI over the accumulating OOS window.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|---|---|---|---|
| Cross-sectional ranking + decile bucket construction | Compute (Ring 2 batch, in-process) | — | Pure numpy/pandas transform over an in-memory DataFrame, same shape as `_decile_spread_per_bar` in the T3 script — no DB round-trip per bar |
| Cost-hurdle net-of-turnover calculation | Compute (Ring 2 batch, in-process) | APR (Ring 0 config read) | Reads `alpha.construction.*`/liquidity-tier cost floors from `config_state`, computes in-process — never a separate service |
| Per-bar spread persistence | Persistence (dedicated writer path inside the `BaseBatch.execute()`) | Database/Storage (new hypertable) | DAG invariant #3: a compute daemon never writes its own computed output inline outside a `BaseBatch`/writer pattern — but per this codebase's established convention (`ic_engine.py`, `tag_calibrator.py`, `counterfactual_tracker.py`), a `BaseBatch` oneshot's `execute()` IS the writer; no separate `BaseWriter` daemon is needed because this is not a continuous real-time stream, it's a batch/oneshot |
| Validation Gate 1 (bootstrap CI over accumulating OOS spread) | Compute (Ring 2 batch, `--evaluate-gate` read-only CLI mode) | — | Mirrors `counterfactual_tracker.py --evaluate-gate` exactly: separate read-only reporting branch, no persistence, no D-06 emission |
| Validation Gate 2 (attribution honesty regression) | Compute (Ring 2, likely a second CLI mode or a follow-on script) | — | Not yet implemented anywhere in this codebase — new statistical work, see Open Questions |
| Universe/instrument filtering (`is_active`, `asset_class='equity'`) | Database/Storage (`instruments` table, read-only) | — | Existing table, existing convention, no new work |
| Shadow-mode gating before any live-capital consideration | Governance (project-level, not code) | — | Per CLAUDE.md's "prove edge before production infra" — enforced by NOT building Phase 156-159 until this phase's gate passes, not by a runtime check in this service |

## Standard Stack

No new external library is introduced by this phase. Every primitive needed already exists in
this repo and is reused verbatim:

### Core (reused, not new)

| Component | Location | Purpose | Why reuse, not rebuild |
|---|---|---|---|
| `BaseBatch` | `src/core/agent/base_batch.py` | Pool lifecycle, D-06 `job_completed_total` emission, `content_key()` | Every Phase 138+ batch service extends this; a new bespoke lifecycle would violate this codebase's own established pattern for no reason |
| `frame_gate_passes` / `evaluate_frame_gate` | `services/counterfactual_tracker.py` | Day-clustered BCa/CLT bootstrap CI, exactly the machinery Validation Gate 1 needs | `[VERIFIED: codebase]` Already used verbatim by the T3 falsification script itself — proven correct, no reason to reimplement |
| `load_apr_dict_async` / `cfg` | `services/_batch_utils.py` | Load `alpha.*`/`infra.*` APR keys into a typed dict | Established convention across `ic_engine.py`, `ensemble_trainer.py`, `alpha_publisher.py`, `tag_calibrator.py`, `counterfactual_tracker.py` |
| `asyncpg` | already a project dependency | Async Postgres/TimescaleDB access | Already pinned; no version change needed for this phase |
| `numpy`/`pandas` | already project dependencies | Cross-sectional rank/decile math, turnover computation | Same libraries the T3 script and `alpha_scorer.py` already use |

### Supporting

| Component | Purpose | When to use |
|---|---|---|
| `services/counterfactual_tracker.py`'s `_DEFAULT_BOOTSTRAP_RANDOM_STATE` (42) constant | Reproducibility seed for BCa resampling | Reuse the identical constant (do not introduce a second seed default that can silently drift) |
| `src/config/config_service.ConfigService` (via `_batch_utils.load_config_service_sync`/`load_apr_dict_async`) | Typed APR reads | For any config value this service needs at startup |

### Alternatives Considered

| Instead of | Could use | Tradeoff |
|---|---|---|
| A new `BaseBatch` oneshot (recommended) | A recurring `BaseDaemon`-style Ring 2 service subscribing to `topic_market_bars` | Rejected: this measurement is inherently a batch/incremental-scan-over-corpus problem (rank the whole 15m equity cross-section at each bar_ts), not an event-driven per-message transform — every existing measurement service of this shape (`ic_engine`, `ensemble_trainer`, `counterfactual_tracker`, `alpha_scorer`) is a `BaseBatch` oneshot, none is a `BaseDaemon` |
| Persisting per-bar rows in a new hypertable (recommended) | Reusing `alpha_frames` | Rejected: `alpha_frames` is a per-symbol, per-direction, stop/target/hold construction (FRAME-01/02/03) — a portfolio-level dollar-neutral spread has no `direction`, `stop_price`, `target_price`, or single `symbol`; forcing this construction's shape into `alpha_frames`' columns would corrupt that table's own invariants (see Common Pitfalls #2) |
| A new hypertable (recommended) | A plain (non-hypertable) Postgres table | Rejected: every per-bar/per-time measurement table in this codebase (`alpha_frames`, `feature_vectors`, `forward_returns`, `market_data_ohlcv`) is a TimescaleDB hypertable partitioned on its timestamp column — a plain table for one more per-bar time series would be an unexplained architectural outlier with no compression/chunk-management benefit |

**Installation:** none — no new package needed.

**Version verification:** N/A — no new package, no version to verify.

## Package Legitimacy Audit

**Skipped.** This phase installs no external packages (no `pip install`, no `npm install`). Every
component used is either already a pinned project dependency (`asyncpg`, `numpy`, `pandas`,
`scipy`, `structlog`, `psycopg2`) or first-party code already in this repository. The Package
Legitimacy Gate protocol does not apply.

## Architecture Patterns

### System Architecture Diagram

```
                    feature_vectors (ctf_momentum, tf=15m)
                    forward_returns (return_fast/slow, executable_open_to_open)
                    instruments (is_active, asset_class='equity')
                              │
                              │  incremental query: bar_ts > last_processed_bar_ts
                              ▼
                  ┌───────────────────────────────┐
                  │  CrossSectionalSpreadTracker   │   BaseBatch.execute()
                  │  (services/cross_sectional_    │
                  │   spread_tracker.py)           │
                  │                                │
                  │  1. rank universe per bar_ts   │
                  │     by ctf_momentum            │
                  │  2. top/bottom decile legs      │
                  │     (alpha.construction.        │
                  │      decile_fraction)           │
                  │  3. gross spread (fast/slow)     │
                  │  4. leg-membership turnover      │
                  │     vs. prior bar's legs         │
                  │  5. net-of-cost spread           │
                  │     (todo 030 liquidity-tier      │
                  │      cost floors x turnover)      │
                  └───────────────┬────────────────┘
                                  │  INSERT (one row per bar_ts)
                                  ▼
                     construction_spreads (new hypertable)
                     PK (construction_name, tf, bar_ts)
                                  │
                                  │  read-only, day-clustered
                                  ▼
                  ┌───────────────────────────────┐
                  │  --evaluate-gate CLI mode      │   reuses evaluate_frame_gate/
                  │  (same module, read-only path) │   frame_gate_passes VERBATIM
                  └───────────────┬────────────────┘
                                  │
                                  ▼
                     Validation Gate 1 verdict (logged, not written)
                     ci_lower > 0 at 95% ⇒ candidate for Gate 2/3 evaluation
                     (Gate 2 attribution-honesty regression: separate follow-on,
                      not yet implemented anywhere in this codebase)
```

### Recommended Project Structure

```
services/
├── cross_sectional_spread_tracker.py   # new — BaseBatch oneshot, compute + persist + --evaluate-gate
production/migrations/
├── 260_construction_spreads_schema.sql  # new — hypertable + alpha.construction.*/infra.* APR seeds
tests/unit/
├── test_cross_sectional_spread_tracker.py   # new — pure-function tests (decile split, turnover,
│                                              #  cost-hurdle math) mirroring test_counterfactual_tracker.py's
│                                              #  shape (no live DB in unit tests)
```

### Pattern 1: Incremental watermark, not full-corpus rescan

**What:** Every existing recurring measurement service in this codebase scopes its per-run work
to *new* rows since the last run (`counterfactual_tracker.py` scopes to `status='open'` frames;
`ic_engine.py`/`ensemble_ic_engine.py` scope to a `weight_epoch`/watermark). The T3 falsification
script, by contrast, does a full-corpus single-shot query (`ORDER BY fv.bar_ts ASC` over the
*entire* 2006-2026 history, ~8.79M rows for 15m equity alone) — correct for a one-off research
script, wrong for a recurring production job.

**When to use:** Every run after the first backfill.

**Example:**
```sql
-- Source: pattern derived from counterfactual_tracker.py's `status = 'open'` incremental
-- scoping and ic_engine.py's watermark convention (this codebase's established idiom, no
-- single canonical helper function exists to import — each service implements its own
-- watermark column/query, matching its own table's shape).
SELECT fv.symbol, fv.bar_ts, fv.ctf_momentum, fr.return_fast, fr.return_slow
FROM feature_vectors fv
JOIN forward_returns fr ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
JOIN instruments i ON i.symbol = fv.symbol
WHERE fv.tf = '15m'
  AND fv.ctf_momentum IS NOT NULL
  AND fr.return_type = 'executable_open_to_open'
  AND fr.complete_fast = true AND fr.complete_slow = true
  AND i.is_active = true AND i.contract_details->>'asset_class' = 'equity'
  AND fv.bar_ts > $1   -- last processed bar_ts, read from MAX(bar_ts) in construction_spreads
ORDER BY fv.bar_ts ASC
```
The first run (backfill) omits the `bar_ts > $1` predicate entirely (or uses a configured
backfill start), exactly matching `counterfactual_tracker.py --backfill`'s pattern of a distinct
CLI flag rather than a magic sentinel watermark value.

### Pattern 2: Turnover requires the PRIOR bar's leg membership, not just this bar's spread

**What:** The T3 script's `_legs_per_bar()` builds `(short_leg, long_leg)` frozensets keyed by
`bar_ts`, then `_cost_hurdle_check()` walks consecutive bars comparing set membership. A
production service must persist enough to compute this **incrementally** across runs (i.e., the
first new bar processed in a given run needs the *previous* run's last-persisted leg
membership, not just data from this run's own in-memory batch).

**When to use:** Every run after the first.

**Example:**
```python
# Source: adapted from scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py's
# _legs_per_bar/_cost_hurdle_check (lines 130-189) — the production service must read the
# single most-recent construction_spreads row's persisted long_leg_symbols/short_leg_symbols
# to seed turnover computation for the first bar of an incremental run, not just rely on
# bars fetched in the current query window.
prior_row = await conn.fetchrow(
    "SELECT long_leg_symbols, short_leg_symbols FROM construction_spreads "
    "WHERE construction_name = $1 AND tf = $2 ORDER BY bar_ts DESC LIMIT 1",
    construction_name, tf,
)
prior_long = frozenset(prior_row["long_leg_symbols"]) if prior_row else frozenset()
prior_short = frozenset(prior_row["short_leg_symbols"]) if prior_row else frozenset()
```

### Pattern 3: `--evaluate-gate` as a separate read-only CLI mode

**What:** `counterfactual_tracker.py --evaluate-gate` is architecturally distinct from its
default compute-and-persist mode: no `manifest.add_output`, no persistence, explicitly commented
"No D-06 `job_completed_total` emission — this performs no persistence, unlike
`CounterfactualTracker.execute()`." This is the correct shape for Validation Gate 1 evaluation —
it should NOT be folded into the same code path as the per-bar compute-and-persist job.

**When to use:** Whenever the shadow measurement needs a gate verdict over the accumulating OOS
window (ad hoc, or on the same cadence as the compute job — read-only, cheap, safe to run more
often than the write path).

**Example:**
```python
# Source: services/counterfactual_tracker.py lines 995-1049 (_run_evaluate_gate), the exact
# shape to replicate for this phase's gate: fetch OOS-window rows, group by day-cluster,
# call frame_gate_passes, log the verdict, never write.
gate_rows = await conn.fetch(
    "SELECT tf, bar_ts::date AS cluster_id, net_spread_fast AS pnl_r "
    "FROM construction_spreads WHERE construction_name = $1 AND bar_ts >= $2",
    construction_name, oos_start,
)
passes, ci_lower, ci_upper = frame_gate_passes(
    [r["pnl_r"] for r in gate_rows],
    [r["cluster_id"] for r in gate_rows],
    min_n=cfg(apr_cfg, "alpha.scoring.min_strategy_n", 30),
    bootstrap_max_n=cfg(apr_cfg, "alpha.scoring.bootstrap_max_n", 5000),
    bootstrap_batch=cfg(apr_cfg, "alpha.scoring.bootstrap_batch", 1000),
)
```

### Anti-Patterns to Avoid

- **Storing the construction's output in `alpha_frames`:** that table's schema is built around
  a single `symbol`/`direction`/`stop_price`/`target_price` per row — a dollar-neutral,
  multi-symbol spread has none of those in a way that fits without corrupting the table's
  existing invariants (FRAME-02/03's direction-aware exit state machine has no meaning for a
  portfolio spread). Use a new table.
- **Re-scanning the full 2006-2026 history every run:** correct once for the initial backfill,
  wrong for every subsequent incremental run — see Pattern 1.
- **Hardcoding "cost survives at 1-10bp" as a static conclusion in code:** D-05 explicitly
  requires the *live* net-of-turnover computation every run, not a cached verdict from this
  session's script output.
- **Confusing `alpha.quant.cost_hurdle.<tf>`** (the existing flat, single-value, per-tf APR key,
  currently seeded at `0.0` for all tfs per migration 182 and computed via todo 030's own
  median-IC-implied-E[R] approximation) **with this phase's cost treatment.** They are
  deliberately different mechanisms — D-05 states this construction applies the blended
  liquidity-tier sweep (1/3/5/10bp) to *actually measured turnover*, which is a materially
  different (and more precise) calculation than `alpha.quant.cost_hurdle`'s flat value. Do not
  read or write that existing key from this phase's service.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Day-clustered bootstrap CI for an autocorrelated per-bar return series | A new bootstrap routine | `frame_gate_passes` (`services/counterfactual_tracker.py`) | Already proven correct (day-clustering handles overlapping-hold-horizon autocorrelation), already reused verbatim by the T3 script itself — a second implementation risks silently diverging in a way that changes the gate verdict |
| BH-FDR correction (if this construction is ever tested across multiple features/tfs in one run) | A new multiple-testing correction | `apply_bh_fdr` (`src/intelligence/statistics/ic_math.py`) | Thin, correct wrapper around `statsmodels.multipletests`, already the shared convention across `ic_engine.py`/`ensemble_ic_engine.py`/`tag_calibrator.py` |
| APR config loading/type-casting | A new config parser | `load_apr_dict_async`/`cfg` (`services/_batch_utils.py`) | Handles the bool-string gotcha (`bool("false") == True` in naive Python) and the "unset key falls back to default" contract every other batch service already relies on |
| Batch lifecycle (pool open/close, D-06 completion metric, structured logging setup) | A new base class | `BaseBatch` (`src/core/agent/base_batch.py`) | Every Phase 138+ measurement service extends this; reinventing it would fragment the D-06 `job_completed_total` contract every Grafana dashboard already depends on |

**Key insight:** This entire phase is "assemble four already-proven primitives around one new
schema and one new incremental query pattern" — there is no genuinely novel algorithm to invent
here except the turnover/cost-hurdle bookkeeping across incremental runs (Pattern 2 above),
which is itself a small, mechanical extension of what the T3 script already computes in one
shot.

## Common Pitfalls

### Pitfall 1: The proven script uses flat equal-weight legs, NOT vol-scaled legs — the design doc's own v1 spec calls for vol-scaling
**What goes wrong:** `docs/research/trade-construction-layer.md`'s Minimal Design step 3 says
"v1 equal-weight per leg, **vol-scaled per symbol** (divide by trailing ATR/vol so one high-vol
leg doesn't dominate the spread)." The T3 script that actually earned this phase (`
_decile_spread_per_bar`) computes `long_leg[return_col].mean() - short_leg[return_col].mean()`
— **flat equal-weight, no vol-scaling at all.**
**Why it happens:** The falsification script was written to test the cheapest, simplest version
of the construction first (Renaissance discipline: earn complexity through proof). It passed
without vol-scaling.
**How to avoid:** Per CONTEXT.md's own "replicate exactly what T3 proved" principle (the
consistent theme across every D-01 through D-05 decision), the planner should build the
**flat equal-weight version first** — exactly what was measured and validated — and treat
vol-scaling as a *separate, testable enhancement* with its own before/after comparison, not
silently fold it in as "the design doc said so." Silently adding vol-scaling would test an
unvalidated variant of the construction, the exact same trap D-01/D-02/D-03 were all written to
avoid for other axes.
**Warning signs:** A plan task that says "implement vol-scaled leg weighting" without a
corresponding measurement step comparing it against the flat-weight baseline.

### Pitfall 2: `alpha_frames`' schema does not fit this construction — don't force it
**What goes wrong:** `alpha_frames` has one row per `(event_id, bar_ts, frame_variant)` with a
single `symbol`, `direction ∈ {long, short}`, `stop_price`, `target_price` — a per-symbol
directional bet. A cross-sectional spread's natural unit is `(tf, bar_ts)` with an *array* of
long-leg symbols and an array of short-leg symbols, no stop/target/direction concept at all.
**Why it happens:** Reuse pressure — `alpha_frames` is the most mature, most battle-tested
per-bar measurement table in the codebase, and CONTEXT.md's canonical refs explicitly point to
`CounterfactualTracker`/`alpha_frames` as "the direct precedent" for validation discipline. That
precedent is about *process* (shadow-mode-first, day-clustered bootstrap gate), not about
*schema reuse*.
**How to avoid:** Build a new hypertable (`construction_spreads`, see Standard Stack's
"Alternatives Considered" and the migration template in Code Examples below). Reuse the
*bootstrap-gate machinery*, not the *table*.
**Warning signs:** A plan task that says "add columns to `alpha_frames` for the spread
construction."

### Pitfall 3: Full-corpus rescan will get slower, not faster, over time
**What goes wrong:** A production service that re-runs the T3 script's full-history query every
cadence (currently ~8.79M rows for 15m equity alone, growing every day) will have monotonically
increasing runtime and will eventually fail to keep pace with its own cadence.
**Why it happens:** The T3 script was correct for a one-off research pass; copy-pasting it
directly into a "production service" without adding incremental scoping is the easiest mistake
to make when turning a script into a service.
**How to avoid:** Pattern 1 above — scope every run after the first to `bar_ts >
last_processed_bar_ts`.
**Warning signs:** No `--backfill` vs. incremental-mode CLI distinction in the implementation
(the same distinction `counterfactual_tracker.py --backfill` already makes).

### Pitfall 4: Turnover computation needs the leg membership from the LAST bar of the PREVIOUS run, not just bars fetched in the current run
**What goes wrong:** If a service run boundary falls between two adjacent bars, computing "the
first new bar's turnover vs. the prior bar" requires reading back the previously *persisted*
leg membership — it cannot be computed purely from the current run's in-memory query result if
that query is scoped to `bar_ts > watermark` (the immediately preceding bar is, by definition,
not in that result set).
**Why it happens:** Direct port of the T3 script's `_legs_per_bar`, which computes turnover
across an entire in-memory DataFrame in one pass, has no concept of "run boundaries."
**How to avoid:** Pattern 2 above — read the single most recent persisted row's leg-membership
columns before computing the first new bar's turnover.
**Warning signs:** A turnover value of exactly 0 or exactly 1.0 for the first bar processed in
every incremental run (a sign the service is treating "the first bar this run" as if it had no
predecessor).

### Pitfall 5: Don't confuse `alpha.quant.cost_hurdle.<tf>` with this phase's cost mechanism
See Anti-Patterns above — this is the single most likely naming/reuse confusion given both
mechanisms are called "cost hurdle" and both are seeded from the same todo 030 source document,
but they compute genuinely different things (a flat per-tf value derived from median IC, vs. a
turnover-weighted sweep across liquidity tiers).

## Code Examples

### Migration template (new hypertable + APR seeds)

```sql
-- Source: adapted directly from production/migrations/205_alpha_frames_schema.sql's structure
-- (Section 1: hypertable DDL, Section 2: config_schema/config_state/config_history INSERT
-- triad) — the established two-section migration shape for "new measurement table + its APR
-- knobs" in this codebase.

BEGIN;

CREATE TABLE IF NOT EXISTS construction_spreads (
    construction_name     text        NOT NULL,   -- e.g. 'ctf_momentum_decile_ls' -- supports
                                                    -- future constructions without schema churn
    tf                    text        NOT NULL,
    bar_ts                timestamptz NOT NULL,
    n_universe            int         NOT NULL,   -- symbols in this bar's ranked cross-section
    n_leg                 int         NOT NULL,   -- symbols per leg (top/bottom decile)
    long_leg_symbols      text[]      NOT NULL,
    short_leg_symbols     text[]      NOT NULL,
    gross_spread_fast     double precision,        -- lookahead=1 (return_fast)
    gross_spread_slow     double precision,        -- lookahead=20 (return_slow)
    one_way_turnover      double precision,        -- mean(long_changed_frac, short_changed_frac)
                                                     -- vs the immediately prior bar's legs
    net_spread_by_cost_bps jsonb,                   -- {"1": ..., "3": ..., "5": ..., "10": ...}
                                                     -- todo 030's blended round-trip sweep,
                                                     -- applied to realized one_way_turnover
    compute_version       text        NOT NULL,
    created_at            timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (construction_name, tf, bar_ts)     -- contains partition col (review H1 precedent)
);

SELECT create_hypertable('construction_spreads', 'bar_ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS construction_spreads_name_tf_idx
    ON construction_spreads (construction_name, tf, bar_ts DESC);

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES
(
    'alpha.construction.decile_fraction',
    'float',
    '0.10',
    '[initial_estimate] Phase 167: top/bottom fraction of the ranked equity universe forming '
    'each leg -- matches T3''s validated _DECILE_FRACTION exactly. NOT an ML learning target.'
),
(
    'alpha.construction.cost_hurdle_bps_round_trip',
    'json',
    '[1, 3, 5, 10]',
    '[conventional] Phase 167: todo 030''s blended round-trip cost-floor sweep (bps), applied '
    'to this construction''s ACTUAL measured one-way turnover per bar (D-05) -- distinct from '
    'the flat, single-value alpha.quant.cost_hurdle.<tf> key (do not confuse the two).'
),
(
    'infra.cross_sectional_spread_tracker.workers',
    'int',
    '1',
    '[conventional] Phase 167: this job is a single cross-sectional pass per bar_ts, not '
    'per-symbol parallel work like counterfactual_tracker/ic_engine -- no ProcessPoolExecutor '
    'is expected to be load-bearing at this data volume (~8.8M rows/15m/equity total corpus, '
    'incremental runs process only new bars). Revisit only if measured runtime demands it.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
('alpha.construction.decile_fraction',                  '0.10',       1),
('alpha.construction.cost_hurdle_bps_round_trip',        '[1, 3, 5, 10]', 1),
('infra.cross_sectional_spread_tracker.workers',         '1',          1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
(NOW(), 'alpha.construction.decile_fraction', 1, '0.10',
 'migration_260', 'Initial estimate: matches T3''s validated decile fraction [initial_estimate]'),
(NOW(), 'alpha.construction.cost_hurdle_bps_round_trip', 1, '[1, 3, 5, 10]',
 'migration_260', 'Conventional: todo 030 blended round-trip sweep, D-05 [conventional]'),
(NOW(), 'infra.cross_sectional_spread_tracker.workers', 1, '1',
 'migration_260', 'Conventional: single-pass cross-sectional job, no per-symbol parallelism needed yet [conventional]');

COMMIT;
```

*(Migration number 260 is illustrative — verify the actual next-free number at plan/execution
time per this codebase's own documented migration-numbering collision risk, todo 095.)*

### Decile spread construction (verbatim reuse, not reinvention)

```python
# Source: scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py lines 81-99 --
# this exact function's logic (not necessarily the exact code) is what the production service's
# per-bar compute step must replicate faithfully per CONTEXT.md's canonical_refs.
def _decile_spread_per_bar(df: pd.DataFrame, feature_col: str, return_col: str) -> pd.DataFrame:
    records = []
    for bar_ts, group in df.groupby("bar_ts"):
        n = len(group)
        n_leg = max(1, int(round(n * _DECILE_FRACTION)))
        if n < 2 * n_leg:
            continue
        ranked = group.sort_values(feature_col)
        short_leg = ranked.iloc[:n_leg]
        long_leg = ranked.iloc[-n_leg:]
        spread = float(long_leg[return_col].mean() - short_leg[return_col].mean())
        records.append({"bar_ts": bar_ts, "spread": spread, "n": n})
    return pd.DataFrame.from_records(records)
```

## State of the Art

Not applicable in the usual external-ecosystem sense — this is a 100% internal construction with
no external library evolution to track. The one within-project "state of the art" evolution
worth recording:

| Old Approach | Current Approach | When Changed | Impact |
|---|---|---|---|
| Gross-only T3 measurement (2026-07-26 initial result) | Cost-hurdle-adjusted T3 measurement (this same session, same day) | 2026-07-26 | The gross-only result could not be scoped into a phase plan per ROADMAP's own stated gate; the cost-adjusted result (net spread survives at every tested round-trip cost floor 1-10bp) is what actually unblocked Phase 167 |
| Per-symbol directional construction (T2, the implicit v3.0 design) | Cross-sectional long-short (T3, this phase) | T2 falsified 2026-07-24 (todo 179), T3 passed 2026-07-26 | This phase exists because the per-symbol construction's Gate 2 (execution) failure (Phase 148) could not be fixed by frame/execution recalibration (Phase 166) — a genuinely different construction, not a parameter tweak, was needed |

**Deprecated/outdated:** None — the T3 script itself is current (written and passed the same
day this research was conducted) and is the direct basis for this phase's production build.

## Todo 186 Scope Assessment

**Question:** Should calibrating and landing a cross-sectional block-bootstrap primitive
(todo 186) be scoped as a task within this phase's plan?

**Answer: No — it is not required for this phase's Validation Gate 1, and should stay a
separate, deferred, lower-priority primitive as todo 186 itself already states.**

Reasoning, read directly from `src/intelligence/statistics/ic_math.py` and todo 186's own text:

1. Todo 186's actual target is a **pooled multi-symbol panel IC bootstrap** — resampling blocks
   of *time* across the *whole symbol universe* to bootstrap a cross-sectional **IC** value
   (correlation between a feature and forward returns, computed jointly across many symbols'
   observations in one panel). This is what T5's non-linear combiner rigor pass needed (a
   pooled OOS IC estimate with proper block structure), and what `_circular_block_bootstrap_ic`
   in `ic_math.py` does NOT natively support (it is built for one symbol's own time series).

2. **T3's construction is a different statistical object entirely.** Once the decile split is
   formed at each bar, the "spread return" is already a single scalar time series — ONE number
   per `bar_ts` (`long_leg.mean() - short_leg.mean()`), not a panel. Bootstrapping a *single time
   series*'s mean, accounting for autocorrelation from overlapping observations, is exactly what
   `frame_gate_passes`' **day-clustered bootstrap already does** — aggregate to per-calendar-day
   means, then BCa/CLT-bootstrap those cluster means. This is precisely the same shape of
   problem `counterfactual_tracker.py`'s FRAME-04 gate solves for per-symbol frames, and T3's
   own script already reuses it verbatim with a valid result (`ci_lower`/`ci_upper` computed
   successfully at both lookahead scales, per `data-edge-source-thesis.md`'s T3 result table).

3. Therefore Validation Gate 1 ("net-of-cost spread Sharpe > 0 at 95% bootstrap CI... beats the
   shuffled-ranking null") is **already fully measurable** with existing, proven machinery. No
   new statistical primitive is needed to clear this phase's own validation bar.

4. Todo 186 remains real, valuable work — but its consumer is a *future* pooled-panel IC
   estimate (e.g., if T5's non-linear combiner or a future multi-feature composite construction
   needs a rigorously calibrated cross-sectional IC bootstrap), not this phase's portfolio-level
   spread-return gate. Scoping it into Phase 167 would add unrelated statistical-infrastructure
   work to a phase whose own design doc says "this is a v1 spec, not an optimizer."

**Recommendation to planner:** Do not include a "calibrate cross-sectional block bootstrap"
task in this phase's plan. Leave todo 186 as a separately-scoped P2 follow-on exactly as its own
filing already recommends ("do this once a second consumer... actually needs it").

## Todo 185 Scope Assessment

**Question:** Is the causal per-entity demeaning primitive (todo 185) needed by this phase's
shadow-measurement/monitoring service?

**Answer: No.** Todo 185's own filing explicitly limits its concern to services that "pool
absolute per-symbol predictions" (T5's non-linear combiner leaked exactly because a
tree-based model implicitly learned each ETF's own long-run drift as a fixed-membership factor
exposure). T3's construction ranks symbols *relative to each other within the same bar* — the
whole point of a cross-sectional rank is that it is invariant to each symbol's own absolute
level/drift; a rank-based construction cannot leak a per-entity fixed-effect the way an absolute
per-symbol regression can, because ranking already differences out any within-bar-constant
per-symbol term. If a future portfolio-level *aggregate* diagnostic (e.g. "does this spread's
P&L load on some symbols' fixed factor exposure more than others") is added, it might reuse this
primitive then (this is exactly Validation Gate 2's attribution-honesty concern, see Open
Questions) — but the core construction and Gate 1 measurement need no per-entity demeaning.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | Recommending `services/cross_sectional_spread_tracker.py` as the exact filename/service name — not locked by CONTEXT.md, a naming proposal following this codebase's `snake_case concept → ClassName` convention | Architecture Patterns, Code Examples | Low — pure naming, trivially renamed at plan time; does not affect correctness |
| A2 | Migration number `260` is illustrative, not verified as next-free at write time (todo 095's documented collision risk) | Code Examples | Low — planner/executor must re-verify at execution time, exactly as migration 215's own header already documents doing |
| A3 | Recommending the new hypertable be named `construction_spreads` rather than some other name — no existing glossary term for this concept was found (`docs/foundation/glossary.md` has no "cross-sectional spread"/"decile construction" entry) | Standard Stack, Code Examples | Low-Medium — if the planner or a future phase later formalizes a different canonical term for this concept, the table name may need a rename; recommend adding a glossary entry as part of this phase's plan |
| A4 | Recommending NOT registering a systemd timer for this service at this phase, following `alpha_scorer.py`'s explicit "manual/on-demand, not on a systemd timer... prove edge before production infra" precedent | Summary, Architectural Responsibility Map | Medium — if the planner disagrees and wants continuous incremental accumulation of the OOS shadow track record on a fixed cadence (e.g. nightly), a systemd `.timer` + `.service` pair should be added (the `regime-coverage-auditor` timer is the template) rather than relying on manual invocation; this is a judgment call, not a hard architectural constraint, and CONTEXT.md does not resolve it explicitly |
| A5 | Validation Gate 2 (attribution honesty — regress spread returns on static bucket membership) has no existing implementation anywhere in this codebase found during research; scoping and building it is new statistical work this phase's plan must account for, not a "reuse verbatim" item like Gate 1 | Phase Requirements, Open Questions | Medium — if the planner assumes Gate 2 is "already handled" by Gate 1's machinery, the phase could ship a construction that looks statistically significant but is actually a disguised static factor tilt (e.g., permanently long low-vol sector ETFs), exactly the failure mode the design doc itself warns against |

**If this table is empty:** N/A — see entries above.

## Open Questions (RESOLVED — see planner's resolution per question below)

1. **Validation Gate 2 (attribution honesty) has no existing code to reuse — how should the
   planner scope it?**
   **RESOLVED by Plan 167-05:** built from scratch as `--evaluate-attribution`, a static-tilt
   regression against a residual gate (each symbol's time-averaged net leg membership collapsed
   into one benchmark series, spread returns regressed on it, the residual passed through
   `frame_gate_passes`) — not R² alone. Plan 05's unit tests include a construction deliberately
   built to FAIL, confirming the gate actually discriminates. See plan-checker's VERIFICATION
   PASSED note: "this phase's one genuinely new statistical component — correctly scoped, not
   silently assumed-covered by Gate 1."
   - What we know: the design doc's Validation Gates section states the requirement precisely
     ("regress spread returns on static bucket membership; if a fixed membership explains most
     of it, the 'forecast' is a factor exposure in disguise"). No script, service, or shared
     statistics function in this codebase currently implements this regression.
   - What's unclear: whether this belongs in the same `--evaluate-gate` CLI mode as Gate 1, or
     as a separate one-off analysis script (mirroring how the T3 falsification itself started
     as a script before this phase productionizes it) — and what "static bucket membership"
     concretely means operationally (a fixed dummy per symbol capturing "how often was this
     symbol in the long leg over the whole OOS window," regressed against daily spread return).
   - Recommendation: scope Gate 2 as its own plan task in this phase (not deferred to a future
     phase — it is one of the three explicit Validation Gates this phase's own design doc
     requires), likely as a second `--evaluate-attribution` CLI mode or a companion analysis
     script reusing the persisted `construction_spreads` rows' `long_leg_symbols`/
     `short_leg_symbols` history.

2. **Should the flat-benchmark comparison (Minimal Design step 6: "vs. two benchmarks: flat,
   and the same construction with shuffled rankings") be added to the production service, given
   the T3 script only implements the shuffled-ranking null, not the flat benchmark?**
   **RESOLVED by Plan 167-04:** implemented exactly the reasoning recommended below — "beats
   flat" is satisfied by Gate 1's `ci_lower > 0` requirement directly; no separate,
   redundant flat-benchmark computation was added.
   - What we know: the shuffled-ranking null is implemented and already proven decisive (P(null
     ≥ observed) = 0.0000 at both scales). The "flat" (do-nothing/no-position) benchmark is
     trivially "zero P&L" for a dollar-neutral construction and may not add diagnostic value
     beyond what the bootstrap CI already shows (ci_lower > 0 already implies "beats flat").
   - What's unclear: whether the design doc intends "flat" as a literal zero-benchmark (already
     implied by the CI gate) or as something more specific (e.g., a passive long-only equal-
     weight benchmark of the same universe).
   - Recommendation: treat "beats flat" as already satisfied by Gate 1's `ci_lower > 0`
     requirement (a spread portfolio with `ci_lower > 0` outperforms doing nothing by
     construction) — do not add a redundant explicit flat-benchmark computation unless the
     planner or a future review finds this reasoning insufficient.

3. **Should this phase register a systemd timer, or stay manual/on-demand?**
   **RESOLVED by Plan 167-03 (design_decisions item 1):** manual/on-demand, matching
   `alpha_scorer.py`'s precedent. The planner's stated reasoning: `--backfill` (Plan 03)
   populates the full 2006-2026 history in one pass, immediately handing Gate 1 ~130 OOS
   day-clusters — this answers the "needs an accumulating record" counterargument below without
   needing a recurring cadence. Also noted: CLAUDE.md records all indicagent timers as disabled
   anyway, so registering one here would misrepresent actual cadence.
   - See Assumption A4 above — this is a real judgment call CONTEXT.md leaves open. The
     `alpha_scorer.py` precedent argues for manual/on-demand; but unlike `alpha_scorer.py` (a
     one-shot diagnostic snapshot over already-closed frames), this service needs to
     *accumulate* an OOS shadow track record over calendar time for Gate 1's bootstrap CI to
     eventually rest on enough day-clusters — which argues for *some* recurring cadence, even if
     not a `systemd.timer`-managed one (e.g., a documented "run this weekly by hand" operational
     note, matching how `counterfactual_tracker.py` itself has no systemd unit today either).
   - Recommendation: planner should decide explicitly rather than default silently either way;
     recommend starting manual (matches the phase's explicit "shadow measurement only, no live
     capital" framing) with a clear operational runbook note, revisiting systemd registration
     if/when this construction clears Gate 1/2/3 and heads toward Phase 156-159.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---|---|---|
| PostgreSQL/TimescaleDB (`indicagent` DB, localhost) | All reads/writes this phase | ✓ (verified live via `psql`) | TimescaleDB extension confirmed via `create_hypertable` usage elsewhere in this DB | — |
| `feature_vectors.ctf_momentum` (tf=15m) | Ranking input | ✓ (verified: 8,792,411 non-null rows, 2006-07-07 through 2026-07-07, full history, no backfill gap) | — | — |
| `forward_returns` (`return_fast`/`return_slow`, `return_type='executable_open_to_open'`, `complete_fast`/`complete_slow`) | Spread return measurement | ✓ (verified live schema: columns and indexes present, including `forward_returns_return_type_idx`) | — | — |
| `instruments.is_active` / `contract_details->>'asset_class'` | Universe filter | ✓ (verified live schema and existing usage in `tag_calibrator.py`) | — | — |
| Python env (`asyncpg`, `numpy`, `pandas`, `scipy`, `structlog`) | Service implementation | ✓ (all already pinned project dependencies, used throughout `services/`) | — | — |

**Missing dependencies with no fallback:** none.

**Missing dependencies with fallback:** none.

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Framework | pytest 8.4+ (`pytest-asyncio` 1.1+, `asyncio_mode=auto`) |
| Config file | `pytest.ini` (repo root) |
| Quick run command | `.venv/bin/pytest tests/unit/test_cross_sectional_spread_tracker.py -x` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirement → Test Map

| Requirement | Behavior | Test Type | Automated Command | File Exists? |
|---|---|---|---|---|
| Decile split (Minimal Design step 2) | Correct top/bottom leg formation, degenerate-universe skip (`n < 2*n_leg`) | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_decile_split -x` | ❌ Wave 0 |
| Turnover computation across a run boundary (Pitfall 4) | First bar of an incremental run computes turnover against the last *persisted* row, not zero/undefined | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_turnover_across_run_boundary -x` | ❌ Wave 0 |
| Cost-hurdle net-of-turnover math (D-05) | Net spread at each of the 4 cost tiers computed correctly from gross spread and realized turnover | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_cost_hurdle_sweep -x` | ❌ Wave 0 |
| Validation Gate 1 evaluation (`--evaluate-gate`) | Correctly groups persisted rows by day-cluster and calls `frame_gate_passes` unmodified | unit | `pytest tests/unit/test_cross_sectional_spread_tracker.py::test_evaluate_gate -x` | ❌ Wave 0 (can adapt `tests/unit/test_counterfactual_tracker.py`'s existing gate-evaluation test shape) |
| Incremental watermark scoping (Pitfall 3) | Second run only processes bars after the last-persisted `bar_ts` | integration (requires_db) | `pytest tests/integration/ -k cross_sectional_spread -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `.venv/bin/pytest tests/unit/test_cross_sectional_spread_tracker.py -x`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`, plus a live `--evaluate-gate` run
  producing a real (not mocked) Validation Gate 1 verdict before this phase is considered
  complete (a pure unit-test pass does not itself constitute "the construction is validated" —
  that requires the actual accumulated OOS measurement).

### Wave 0 Gaps

- [ ] `tests/unit/test_cross_sectional_spread_tracker.py` — new file, covers decile split,
      turnover-across-run-boundary, cost-hurdle sweep, `--evaluate-gate` grouping
- [ ] No new framework install needed — pytest/pytest-asyncio already configured

## Security Domain

This phase builds an internal, read-mostly batch measurement service with no external-facing
API, no user input, and no authentication boundary — it reads existing corpus tables and writes
one new internal diagnostic table. Most ASVS categories do not apply.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | No | No auth boundary — internal batch job, same trust model as every other `BaseBatch` service |
| V3 Session Management | No | N/A — no session concept |
| V4 Access Control | No | N/A — runs with the same DB credentials as every other batch service in this codebase |
| V5 Input Validation | Yes (narrow) | APR config values (`alpha.construction.decile_fraction`, `alpha.construction.cost_hurdle_bps_round_trip`) should be range/type-validated at load time (e.g., `decile_fraction` in `(0, 0.5)`), matching `alpha_frame_writer.py`'s existing pattern of raising `ValueError` on an out-of-range APR value (`stop_atr_mult must be positive`) rather than silently proceeding with a nonsensical value |
| V6 Cryptography | No | N/A — no secrets, no crypto operations in this service |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---|---|---|
| SQL injection via dynamically interpolated table/column names | Tampering | N/A here — all queries use parameterized asyncpg placeholders (`$1`, `$2`); no dynamic SQL string interpolation is needed for this phase (unlike `counterfactual_tracker.py`'s chunk-routing feature, which validates table names via regex before interpolation — this phase's queries have no equivalent dynamic-table-name need) |
| Malformed/out-of-range APR config causing a silent wrong computation | Tampering (of config data) | Validate `decile_fraction`/`cost_hurdle_bps_round_trip` bounds at load time; fail loud (raise), never silently clamp or ignore — matches this codebase's "silent wrong answers are worse than loud crashes" principle |

## Project Constraints (from CLAUDE.md)

- **Ring discipline:** `services/cross_sectional_spread_tracker.py` lives in Ring 2 (`services/`)
  per the concept-name-derives-layer-names convention; it may import Ring 0 (`src/core/`) and
  Ring 1 (`src/intelligence/statistics/ic_math.py` for `apply_bh_fdr` if ever needed) but is
  itself domain-vocabulary code, correctly placed in Ring 2.
- **DAG Invariant #3** (a compute daemon never writes its own computed output inline outside a
  dedicated writer path): satisfied by following the `BaseBatch.execute()` convention every
  other batch measurement service in this codebase already uses — this is not a continuous
  real-time daemon, so the "writer is a separate class" distinction that applies to
  `FeatureVectorPipeline`/`FeatureVectorWriter` does not apply the same way here; `ic_engine.py`,
  `tag_calibrator.py`, and `counterfactual_tracker.py` all write directly inside their own
  `BaseBatch.execute()`, which is the established precedent for oneshot batch services.
- **All timestamps UTC:** `bar_ts` columns throughout are already `timestamptz`; any
  `datetime.now()` call in the new service must use `datetime.now(UTC)` per every existing
  service's convention.
- **APR mandate (migrate-as-you-go):** `_DECILE_FRACTION`, `_COST_HURDLE_BPS_ROUND_TRIP`, and
  `_N_NULL_SHUFFLES`/`_SHUFFLE_SEED` in the T3 script are all hardcoded module-level constants —
  architecture violations per CLAUDE.md if carried forward unchanged into the production
  service. `_DECILE_FRACTION` and `_COST_HURDLE_BPS_ROUND_TRIP` must become
  `alpha.construction.decile_fraction`/`alpha.construction.cost_hurdle_bps_round_trip` APR keys
  (see Code Examples migration template). `_N_NULL_SHUFFLES`/`_SHUFFLE_SEED` are arguably
  APR-exempt as a "statistical concept definition" for a diagnostic-only null check reused from
  `_DEFAULT_BOOTSTRAP_RANDOM_STATE` — but if the production service re-runs the shuffled-null
  check on a recurring cadence (not just once at initial validation), the planner should
  consider whether `_N_NULL_SHUFFLES` also deserves an APR key for consistency; recommend
  keeping it a plain reused constant (matching `_DEFAULT_BOOTSTRAP_RANDOM_STATE`'s own precedent
  of being a named Python constant, not an APR key) unless a concrete need to tune it in
  production arises.
- **Naming system:** proposed concept name `cross_sectional_spread` (or `construction_spread`)
  → `CrossSectionalSpreadTracker` class → `services/cross_sectional_spread_tracker.py` →
  `construction_spreads` table → (if ever systemd-registered)
  `indicagent-cross-sectional-spread-tracker.service`. Planner/executor should confirm this
  concept name against `docs/foundation/glossary.md` and add an entry there per CLAUDE.md's
  glossary-first convention (no existing collision was found during this research).
- **D-06 oneshot contract:** if this phase's service ever runs under systemd (see Open Question
  3), its `job` label in `job_completed_total` must match the systemd unit's `%n` suffix exactly
  (kebab-case) — inherited automatically via `BaseBatch`'s `job_name` class attribute, no manual
  wiring needed.

## Sources

### Primary (HIGH confidence — verified directly against this repo's live code/schema/DB)

- `services/counterfactual_tracker.py` — `frame_gate_passes`, `evaluate_frame_gate`, the
  `--evaluate-gate` CLI mode pattern, the day-clustered BCa/CLT bootstrap this phase's Gate 1
  reuses verbatim
- `services/tag_calibrator.py` — generic 3-pass `BaseBatch` measurement engine pattern, APR
  compile-time binding via a frozen dataclass
- `services/alpha_scorer.py` — the "manual/on-demand, not on a systemd timer, prove-edge-before-
  production-infra" precedent directly on point for this phase's own posture
- `services/regime_coverage_auditor.py` + `production/systemd/indicagent-regime-coverage-
  auditor.{service,timer}` — the contrasting "this IS on a systemd timer" precedent (operational
  canary, not a shadow-validation gate)
- `src/core/agent/base_batch.py` — `BaseBatch` lifecycle contract
- `src/intelligence/statistics/ic_math.py` — read in full; confirmed `_circular_block_bootstrap_ic`/
  `circular_block_bootstrap_ic_serial` are per-symbol time-series primitives, distinct from what
  todo 186 targets and from what this phase's Gate 1 actually needs
- `services/_batch_utils.py` — `load_apr_dict_async`, `cfg`, APR-loading conventions
- `production/migrations/205_alpha_frames_schema.sql` — the two-section (hypertable DDL +
  config_schema/config_state/config_history seed) migration template this phase's migration
  should follow
- `production/migrations/182_alpha_cost_hurdle.sql`, `238_forward_return_price_sanity_guard.sql`
  — confirmed `alpha.quant.cost_hurdle.<tf>` and `alpha.quant.max_abs_return.<tf>` conventions,
  confirmed this phase's cost mechanism is deliberately distinct
- Live DB queries (`psql`) against `feature_vectors`, `forward_returns`, `instruments` — schema,
  indexes, and row-count/date-range verification for `ctf_momentum` (2006-2026, no backfill gap)
- `scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py` — read in full, the
  exact construction/cost-hurdle/null-check logic this phase productionizes
- `.planning/todos/pending/185-ic-math-causal-entity-demeaning-primitive.md`,
  `186-ic-math-cross-sectional-block-bootstrap-gap.md` — read in full for the Todo 185/186
  Scope Assessment sections above
- `production/systemd/` directory listing — confirmed no existing systemd unit for
  `counterfactual-tracker`, `tag-calibrator`, or `alpha-scorer` (all manual/on-demand), contrasted
  with `regime-coverage-auditor`'s timer

### Secondary (MEDIUM confidence)

- None — this phase required no external-ecosystem research; every claim above was verifiable
  directly against this repo.

### Tertiary (LOW confidence)

- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new external dependency; every reused primitive verified directly
  in this repo's source
- Architecture: HIGH — direct precedent (`counterfactual_tracker.py`, `alpha_scorer.py`) verified
  by reading both in full
- Pitfalls: HIGH — each pitfall above is grounded in a specific, cited discrepancy between the
  design doc, the proven script, and this codebase's existing schema/conventions, not a generic
  best-practice guess

**Research date:** 2026-07-26
**Valid until:** 30 days (internal-only research, no external ecosystem drift risk; re-verify
`ctf_momentum` row counts/date range and migration next-free-number at plan/execution time
regardless, per this codebase's own stated collision-risk discipline)
