# v3.0 Alpha Lifecycle Schema Design

**Date:** 2026-06-25
**Status:** APPROVED — referenced by Phases 142A, 142B, and 144 roadmap entries
**Scope:** New DB tables, APR keys, naming derivation, and architectural boundary for the v3.0
measurement and hypothesis layers. Migration must land before Phase 142A planning begins.

---

## Design Principle: Two Independent Measurement Instruments

The intelligence engine must never conflate two separate questions:

1. **Does the signal have IC?** Does `alpha_score` predict forward returns? (assumption-free)
2. **Do our execution rules capture that IC as P&L?** Given our stop/target/hold rules, how
   much of the signal's IC survives to the P&L line? (frame-dependent)

These require independent measurement systems. If you answer both with a single counterfactual
P&L number, you cannot distinguish a bad signal from a good signal with bad frame parameters.
That is a silent wrong answer — the worst kind.

**Phase 142A** measures the signal. **Phase 142B** measures the frame. Phase 144 requires
both to pass independently before v2.x is retired.

---

## Why New Tables

`trade_frames` cannot be reused for v3.0:

1. **Hard FK:** `trade_frames.signal_id uuid NOT NULL` references `signal_events`. No
   `signal_events` row exists for an `alpha_event` — writing v3.0 rows here is a FK violation.
2. **I7-coupled schema:** `entry_type` is a DB enum with I7-only values (`at_close`,
   `at_pullback`, `at_limit`, `at_reclaim`, `zone_proximal`). `was_selected` reflects plugin
   selection logic. `regime_at_activation` is integer (HMM state index), not text regime label.
3. **Cardinality mismatch:** `trade_frames` holds N rows per signal (one per entry_type).
   `alpha_frames` holds one row per alpha_event.

The v3.0 layered schema mirrors v2.x with clean concepts:

```
v2.x:  signal_events  →  trade_frames   →  trade_executions
v3.0:  alpha_events   →  alpha_frames   →  alpha_executions  (v4.0 only)
                ↓
         alpha_ensemble_ic  (Phase 142A — assumption-free signal measurement)
```

`alpha_events` exists (Phase 139). `alpha_executions` does not exist until v4.0 — enforced
by schema, not convention.

---

## Table: `alpha_ensemble_ic` (Phase 142A — primary signal proof)

**Concept:** `alpha_ensemble_ic` — IC measurement of the ensemble's OUTPUT (`alpha_score`)
against forward returns. The same BH-FDR + bootstrap CI + walk-forward machinery used for
feature IC, applied one level up. Assumption-free: no stops, no targets, no hold rules.

This is the primary OOS gate. If `alpha_score` does not predict forward returns, no frame
definition will save it.

The IC decay curve across `return_fast → mid → slow → extended` is also the empirical
calibration source for `hold_max_bars` — don't assume a hold horizon, read it from the data.

```sql
CREATE TABLE alpha_ensemble_ic (
    ic_id               bigserial,
    scored_at           timestamptz NOT NULL DEFAULT now(),
    symbol              text        NOT NULL,
    tf                  text        NOT NULL,
    regime              text        NOT NULL,
    lookahead           text        NOT NULL,  -- 'fast' | 'mid' | 'slow' | 'extended'
    ic_mean             float,
    ic_sharpe           float,
    ic_ci_lower         float,
    ic_ci_upper         float,
    n_obs               int,
    fdr_passed          boolean,
    walk_forward_stable boolean,    -- ic_sharpe max/min fold ratio < 3x

    PRIMARY KEY (ic_id, scored_at)
);

SELECT create_hypertable('alpha_ensemble_ic', 'scored_at');

-- Primary lookup: latest IC for a given (symbol, tf, regime, lookahead) cell
CREATE UNIQUE INDEX alpha_ensemble_ic_cell_idx
    ON alpha_ensemble_ic (symbol, tf, regime, lookahead, scored_at DESC);
```

### IC Decay Curve → hold_max calibration

For each (symbol, tf, regime), plot IC Sharpe across lookaheads:

```
fast (1-bar)  → ic_sharpe = X
mid  (3-bar)  → ic_sharpe = Y
slow (5-bar)  → ic_sharpe = Z
extended      → ic_sharpe = W
```

The hold horizon is the first lookahead where IC Sharpe drops below
`alpha.ensemble_ic.decay_threshold` (default 0.1). Update
`alpha.frame.hold_max_bars.<regime>.<tf>` APR keys to match before Phase 142B begins.
This replaces the initial estimates with empirically-derived values.

---

## Table: `alpha_frames` (Phase 142B — frame simulation)

**Concept:** `alpha_frame` — one hypothetical position per alpha_event. Tests whether a
specific set of execution rules (stop at X×ATR, target at resistance, hold max N bars) can
capture the signal's IC as P&L. The frame is a hypothesis about execution; the ensemble IC
is the proof of signal.

`CounterfactualTracker` (nightly oneshot, `BaseBatch`) scans the price path bar-by-bar and
writes the lifecycle outcome. Multiple frame variants are tested simultaneously — one row
per (alpha_event, stop_atr_mult variant). The winning variant (max
`corr(alpha_score_decile, mean_pnl_r)` on in-sample data) is validated on OOS.

```sql
CREATE TABLE alpha_frames (
    frame_id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id            text        NOT NULL,
    bar_ts              timestamptz NOT NULL,
    symbol              text        NOT NULL,
    tf                  text        NOT NULL,
    regime              text,
    direction           text        NOT NULL CHECK (direction IN ('long', 'short')),

    -- Frame variant identifier — one row per (alpha_event, stop_atr_mult variant)
    frame_variant       text        NOT NULL DEFAULT 'primary',
    -- 'primary' = current APR stop_atr_mult; 'grid_0.8', 'grid_1.0', 'grid_1.5', 'grid_2.0'
    -- during calibration runs. Production uses 'primary' only after winning variant selected.

    -- Snapshot of alpha signal at frame creation (avoid re-joining alpha_events)
    alpha_score         float       NOT NULL,
    alpha_ci_lower      float,
    alpha_ci_upper      float,
    gross_expected_r    float,
    net_expected_r      float,       -- NULL for 1h/1d (cost not applied at those horizons)
    cost_r              float,       -- cost estimate snapshot; NULL for 1h/1d

    -- Frame geometry (populated by CounterfactualTracker on T+1 bar open)
    entry_price         float,
    stop_price          float,
    target_price        float,
    r_multiple          float,       -- (target_price - entry_price) / (entry_price - stop_price)
    max_hold_bars       int,         -- APR snapshot at creation: alpha.frame.hold_max_bars.<regime>.<tf>
    stop_atr_mult       float,       -- APR snapshot at creation: alpha.frame.stop_atr_mult

    -- Lifecycle state machine
    -- open → closed_stop | closed_target | closed_reversal | closed_max_hold
    status              text        NOT NULL DEFAULT 'open'
                            CHECK (status IN (
                                'open',
                                'closed_stop',
                                'closed_target',
                                'closed_reversal',
                                'closed_max_hold'
                            )),

    -- Counterfactual outcome (written by CounterfactualTracker)
    counterfactual_pnl_r    float,
    counterfactual_mfe      float,
    counterfactual_mae      float,
    counterfactual_bars     int,
    exit_reason             text,
    closed_at               timestamptz,
    measured_at             timestamptz,    -- last CounterfactualTracker scan

    created_at          timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT fk_alpha_frames_event
        FOREIGN KEY (event_id, bar_ts)
        REFERENCES alpha_events (event_id, bar_ts),

    CONSTRAINT uq_alpha_frames_variant
        UNIQUE (event_id, bar_ts, frame_variant)
);

SELECT create_hypertable('alpha_frames', 'bar_ts');

CREATE INDEX alpha_frames_status_open_idx
    ON alpha_frames (symbol, tf, bar_ts DESC)
    WHERE status = 'open';

CREATE INDEX alpha_frames_symbol_tf_idx
    ON alpha_frames (symbol, tf, bar_ts DESC);

CREATE INDEX alpha_frames_labeled_idx
    ON alpha_frames (bar_ts DESC, counterfactual_pnl_r)
    WHERE counterfactual_pnl_r IS NOT NULL AND frame_variant = 'primary';
```

### Lifecycle State Machine

```
open
  → closed_stop       stop_price hit before target; counterfactual_pnl_r = -1.0 R
  → closed_target     target_price hit; counterfactual_pnl_r = +r_multiple R
  → closed_reversal   alpha_score sign reversal before target or stop
  → closed_max_hold   max_hold_bars elapsed; counterfactual_pnl_r = R at close price
```

All transitions: single UPDATE setting `status`, `counterfactual_pnl_r`,
`counterfactual_bars`, `exit_reason`, `closed_at`, `measured_at`. Immutable once closed.

### Frame Geometry Logic

```
entry_price   = open of T+1 bar  (same convention as IC forward return measurement)
stop_price    = min(
                  entry_price - stop_atr_mult × ATR_from_feature_vectors,
                  sr_support_dist level from feature_vectors at bar_ts   [if not NULL]
                )
target_price  = sr_resist_dist level from feature_vectors at bar_ts     [if not NULL]
                else entry_price + target_r_fallback × (entry_price - stop_price)
r_multiple    = (target_price - entry_price) / (entry_price - stop_price)
max_hold_bars = alpha.frame.hold_max_bars.<regime>.<tf>
               calibrated from IC decay curve (Phase 142A) before this runs
```

Note: `sr_support_dist` / `sr_resist_dist` are NULL in the current corpus (todo 001 Group 3).
The ATR fallback path is the primary path until those features are fixed.

### Frame Calibration Protocol (in-sample only)

During the calibration run, `CounterfactualTracker` creates 4 rows per alpha_event
(one per grid variant: 0.8, 1.0, 1.5, 2.0). After calibration:

1. For each (tf, regime), compute `corr(alpha_score_decile, mean_pnl_r)` per variant
2. Select winning `stop_atr_mult` = argmax of that correlation
3. Write winning value to APR `alpha.frame.stop_atr_mult`
4. Validate winning variant on OOS data (must hold — if OOS correlation degrades > 0.2
   vs in-sample, the winning variant is overfit; use conservative fallback 1.5)
5. Production frames use `frame_variant = 'primary'` only

---

## Table: `alpha_strategy_scores` (Phase 144 — scoring aggregation)

**Concept:** `alpha_strategy_score` — weekly aggregation of closed `primary` `alpha_frames`
into scored performance cells. Answers "which (regime, TF, alpha_score band) is producing
real edge under the winning frame variant?"

This is the secondary OOS gate (execution proof). The primary gate is ensemble IC.

```sql
CREATE TABLE alpha_strategy_scores (
    score_id            bigserial,
    scored_at           timestamptz NOT NULL DEFAULT now(),
    symbol              text,        -- NULL = cross-symbol aggregate
    tf                  text        NOT NULL,
    regime              text        NOT NULL,
    alpha_score_decile  int         NOT NULL CHECK (alpha_score_decile BETWEEN 1 AND 10),
    frame_variant       text        NOT NULL DEFAULT 'primary',
    sample_n            int         NOT NULL,
    mean_pnl_r          float,
    win_rate            float,       -- closed_target / total closed
    sharpe_annualized   float,
    max_drawdown        float,
    ci_lower            float,       -- bootstrap CI on mean_pnl_r
    ci_upper            float,
    ic_alpha_score_corr float,       -- corr(alpha_score_decile rank, mean_pnl_r) — key diagnostic

    PRIMARY KEY (score_id, scored_at)
);

SELECT create_hypertable('alpha_strategy_scores', 'scored_at');

CREATE UNIQUE INDEX alpha_strategy_scores_cell_idx
    ON alpha_strategy_scores (symbol, tf, regime, alpha_score_decile, frame_variant, scored_at);
```

`ic_alpha_score_corr` is the key diagnostic: if higher `alpha_score` deciles produce higher
`mean_pnl_r`, the ensemble output is monotonically predictive of P&L. A flat or inverted
correlation means the frame is destroying signal — the problem is execution rules, not IC.

---

## APR Keys

All keys inserted in the same migration as the schema. Hard-coded numerics in application
code are an architecture violation — `ConfigService.get_sync()` everywhere.

### `alpha.ensemble_ic.*` — Phase 142A signal measurement

| Key | Default | Provenance | Notes |
|-----|---------|------------|-------|
| `alpha.ensemble_ic.min_n_obs` | 1000 | `[conventional]` | Min independent observations for IC measurement |
| `alpha.ensemble_ic.decay_threshold` | 0.1 | `[initial_estimate]` | IC Sharpe below this = edge expired at that lookahead; calibrates hold_max |
| `alpha.ensemble_ic.fdr_alpha` | 0.05 | `[conventional]` | BH-FDR threshold; matches feature IC engine |

### `alpha.frame.*` — Phase 142B frame geometry

| Key | Default | Provenance | Notes |
|-----|---------|------------|-------|
| `alpha.frame.stop_atr_mult` | 1.5 | `[initial_estimate]` | Updated after calibration; ML learning target |
| `alpha.frame.grid_stop_atr_mults` | `[0.8,1.0,1.5,2.0]` | `[conventional]` | Calibration grid; JSON array |
| `alpha.frame.target_r_fallback` | 2.0 | `[initial_estimate]` | R-multiple target when sr_resist_dist is NULL |
| `alpha.frame.hold_max_bars.bull.5m` | 20 | `[initial_estimate]` | Calibrated from IC decay curve in Phase 142A |
| `alpha.frame.hold_max_bars.bear.5m` | 15 | `[initial_estimate]` | |
| `alpha.frame.hold_max_bars.sideways.5m` | 10 | `[initial_estimate]` | |
| `alpha.frame.hold_max_bars.volatile.5m` | 8 | `[initial_estimate]` | |
| `alpha.frame.hold_max_bars.bull.15m` | 12 | `[initial_estimate]` | |
| `alpha.frame.hold_max_bars.bear.15m` | 8 | `[initial_estimate]` | |
| `alpha.frame.hold_max_bars.sideways.15m` | 6 | `[initial_estimate]` | |
| `alpha.frame.hold_max_bars.volatile.15m` | 5 | `[initial_estimate]` | |
| `alpha.frame.hold_max_bars.bull.1h` | 6 | `[initial_estimate]` | |
| `alpha.frame.hold_max_bars.bear.1h` | 4 | `[initial_estimate]` | |
| `alpha.frame.hold_max_bars.sideways.1h` | 3 | `[initial_estimate]` | |
| `alpha.frame.hold_max_bars.volatile.1h` | 3 | `[initial_estimate]` | |
| `alpha.frame.hold_max_bars.bull.1d` | 3 | `[initial_estimate]` | |
| `alpha.frame.hold_max_bars.bear.1d` | 2 | `[initial_estimate]` | |
| `alpha.frame.hold_max_bars.sideways.1d` | 2 | `[initial_estimate]` | |
| `alpha.frame.hold_max_bars.volatile.1d` | 1 | `[initial_estimate]` | |

### `alpha.cost.*` — static cost model

| Key | Default | Provenance | Notes |
|-----|---------|------------|-------|
| `alpha.cost.equity_spread_r` | 0.10 | `[initial_estimate]` | Half-spread in R units; calibrated from fills in v4.0 |
| `alpha.cost.futures_spread_r` | 0.15 | `[initial_estimate]` | |
| `alpha.cost.fx_spread_r` | 0.05 | `[initial_estimate]` | |
| `alpha.cost.slippage_r` | 0.05 | `[initial_estimate]` | ML learning target in v4.0 |
| `alpha.cost.net_cost_tfs` | `["5m","15m"]` | `[user_preference]` | TFs where cost applied; 1h/1d excluded |

### `alpha.scoring.*` — Phase 144 scoring gates

| Key | Default | Provenance | Notes |
|-----|---------|------------|-------|
| `alpha.scoring.min_strategy_n` | 30 | `[conventional]` | Min closed frames before scoring a cell |
| `alpha.scoring.oos_ic_ci_threshold` | 0.95 | `[conventional]` | Bootstrap CI for ensemble IC OOS gate (primary) |
| `alpha.scoring.oos_pnl_ci_threshold` | 0.95 | `[conventional]` | Bootstrap CI for mean_pnl_r OOS gate (secondary) |
| `alpha.scoring.v2x_comparison_ci` | 0.80 | `[conventional]` | CI for v3.0 > v2.x (comparison, not zero-test) |
| `alpha.scoring.min_sharpe` | 0.5 | `[initial_estimate]` | Annualized Sharpe floor for retirement gate |
| `alpha.scoring.max_drawdown` | 0.25 | `[initial_estimate]` | Max drawdown ceiling for retirement gate |
| `alpha.scoring.min_ic_alpha_score_corr` | 0.3 | `[initial_estimate]` | Min corr(decile, pnl_r) — frame is not destroying signal |

---

## Naming Derivation

Per `docs/foundation/naming-system.md`:

| Concept | Table | Class | Systemd unit |
|---------|-------|-------|--------------|
| `alpha_ensemble_ic` | `alpha_ensemble_ic` | `EnsembleICEngine` | `indicagent-ensemble-ic-engine` |
| `alpha_frame` | `alpha_frames` | `AlphaFrameWriter` | `indicagent-alpha-frame-writer` |
| `counterfactual_tracker` | — | `CounterfactualTracker` | `indicagent-counterfactual-tracker` |
| `alpha_strategy_score` | `alpha_strategy_scores` | `AlphaScorer` | `indicagent-alpha-scorer` |
| `alpha_execution` | `alpha_executions` | `AlphaExecutionWriter` | `indicagent-alpha-execution-writer` |

`alpha_executions` and `AlphaExecutionWriter` are v4.0 scope — not defined here.

---

## Phase Sequencing (load-bearing)

```
Phase 142A: EnsembleICEngine
  - Measures IC(alpha_score, forward_return_*) per (symbol, tf, regime, lookahead)
  - Produces IC decay curve → updates hold_max APR keys
  - GATE: ic_ci_lower > 0 at 95% CI on in-sample data before 142B begins
  - If gate fails: diagnose ensemble, do not proceed to frame simulation

Phase 142B: AlphaFrameWriter + CounterfactualTracker
  - Calibration run: 4 frame variants per alpha_event
  - Selects winning stop_atr_mult per (tf, regime) via corr(decile, pnl_r)
  - Production run: 'primary' variant only
  - GATE: corr(alpha_score_decile, mean_pnl_r) > alpha.scoring.min_ic_alpha_score_corr
          Must hold on OOS data before Phase 144 begins

Phase 144: AlphaScorer
  - TWO INDEPENDENT GATES — both must pass:
    Gate 1 (signal):    ensemble IC > 0 at 95% CI on OOS (from 142A)
    Gate 2 (execution): mean_pnl_r > 0 at 95% CI on OOS (from 142B primary variant)
  - Gate 1 failure = signal problem. Gate 2 failure = frame problem.
    Never conflate. Diagnose independently.
```

---

## Migration Checklist

Single migration (`migration_NNN`) before Phase 142A planning:

- [ ] `CREATE TABLE alpha_ensemble_ic` (hypertable + unique cell index)
- [ ] `CREATE TABLE alpha_frames` (hypertable + indexes + unique variant constraint)
- [ ] `CREATE TABLE alpha_strategy_scores` (hypertable + unique cell index)
- [ ] `INSERT` all APR keys into `config_schema` + `config_state`
- [ ] Add `EnsembleICEngine`, `AlphaFrameWriter`, `CounterfactualTracker`, `AlphaScorer`
      to `_DAG_ORDER` and `_AGENT_ID_TO_UNIT` in `service_auditor.py`
- [ ] Add `topic_alpha_frames` to `stream_keys.py`

---

## Explicitly Deferred to v4.0

- `alpha_executions` table and `AlphaExecutionWriter` service
- Emission threshold (alpha_score floor where E[R]_net > cost) — execution-layer decision
- Kelly sizing, VaR constraints, correlation constraints
- IBKR market order routing
- Slippage calibration from actual fills

`alpha_frames.cost_r` and `net_expected_r` exist in v3.0 as diagnostic flags only.
Signals that are gross-positive but net-negative are visible in scoring; they are not
blocked. Blocking is a v4.0 execution-layer decision.
