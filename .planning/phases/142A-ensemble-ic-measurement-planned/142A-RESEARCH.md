# Phase 142A: Ensemble IC Measurement - Research

**Researched:** 2026-06-30
**Domain:** Statistical IC measurement (Spearman IC + BH-FDR + walk-forward + Fisher z CI) applied to the ensemble output (`alpha_score`), reusing the corrected Phase A feature-IC methodology
**Confidence:** HIGH (every load-bearing claim verified against live code/DB; only `[ASSUMED]` items are the unseeded numeric defaults the audit already flags)

## Summary

Phase 142A measures whether the ensemble OUTPUT (`alpha_events.alpha_score`) predicts forward returns, using the same corrected methodology the feature IC engine shipped in Phase A. It is the assumption-free signal proof that must pass before any frame/execution logic (142B) is built. The scope is LOCKED by the Musk 5-step + Renaissance audit (`docs/ideas/phase142-redesign-musk5step-audit.md`) — research covers HOW to implement EIC-01..EIC-05, not WHETHER.

The implementation is a near-mechanical port of `services/ic_engine.py` onto a single composite predictor (`alpha_score`) instead of 54 features. Because alpha_score is ONE column, the heavy per-feature numpy vectorization, collinearity clustering, and corpus-level BH-FDR representative selection collapse dramatically — there is no cluster deflation step and BH-FDR runs over the (symbol × tf × regime × lookahead) cells directly. The IC math primitives (Fisher z CI, t-approximation p-values, expanding-window walk-forward with scale-specific embargo, HAC IC Sharpe) are pure functions already imported from `ic_engine.py` and must be reused verbatim — re-deriving them is an architecture violation (silent-wrong-answer risk).

**Primary recommendation:** `EnsembleICEngine` extends `BaseBatch` (asyncpg, like `EnsembleTrainer`/`AlphaPublisher`), composes the IC math from `services/ic_engine.py` (import the private `_fisher_z_ci`, `_p_values_from_ic`, `_compute_ic_rolling_metrics` functions — do NOT subclass ICEngine, do NOT fork the math), parallelizes per-(symbol, tf) via ProcessPoolExecutor with compute-only workers and serial DB writes from main, writes to a new `alpha_ensemble_ic` hypertable, and stratifies on the 9 cross-sectional `market_regimes.regime_label` values (`{low/mid/high}_{bull/neutral/bear}`) — NOT the stale 4-label `bull/bear/sideways/volatile` namespace in the schema doc.

**The single most important deliverable (resolves OQ-1):** the regime namespace must be the 9 cross-sectional labels. Verified at `services/ic_engine.py:768-799` (mr_dict overrides `feature_vectors.regime` when `equity_model_enabled=True`, which is the live default) and at `services/ensemble_trainer.py:472-477` (the JOIN that produces `ensemble_alpha.regime` → `alpha_events.regime` uses `market_regimes.regime_label`). The `alpha.frame.hold_max_bars.<regime>.<tf>` APR keys must be seeded with these 9 labels × 4 TFs = 36 keys, and `alpha_ensemble_ic.regime` must store them.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions (EIC-01..EIC-05 — transcribed verbatim from the Musk redesign audit)

- **EIC-01 — EnsembleICEngine (KEEP):** Weekly oneshot, `BaseBatch` subclass. Reads `alpha_events` joined to `forward_returns` on (symbol, tf, bar_ts). Computes Spearman `IC(alpha_score, forward_return_fast/mid/slow/extended)` per (symbol, tf, regime). Applies same BH-FDR correction, circular-block-bootstrap 95% CI (NOTE: corrected to Fisher z-transform — see State of the Art), and 3-fold walk-forward as `ICEngine`. Writes to `alpha_ensemble_ic`. Parallelized: one `ProcessPoolExecutor` task per (symbol, tf). CPU-bound IC computation decoupled from async DB reads/writes.
- **EIC-02 — IC decay curve → hold_max_bars (KEEP):** For each (symbol, tf, regime), find the first lookahead where IC Sharpe drops below `alpha.ensemble_ic.decay_threshold` (default 0.1 `[initial_estimate]`). Update `alpha.frame.hold_max_bars.<regime>.<tf>` APR keys to match. Replaces initial estimates with data-derived values before 142B runs any frames.
- **EIC-03 — Walk-forward stability gate (KEEP):** IC Sharpe max/min fold ratio < 3× across walk-forward folds. Written to `alpha_ensemble_ic.walk_forward_stable` (boolean). Phase 144 OOS validation reads this column.
- **EIC-04 — Phase gate (KEEP, threshold is APR-seeded NOT baked in):** `ic_ci_lower > 0` at 95% CI on in-sample data in at least `alpha.ensemble_ic.min_qualifying_fraction` of (symbol, tf, regime) cells before Phase 142B begins. Renaissance correction: the 60% is arbitrary and unseeded — `alpha.ensemble_ic.min_qualifying_fraction = 0.60` seeded as `[initial_estimate]`, recalibrate after first run. Do NOT bake a magic number into the gate logic. If gate fails, run EIC-05 diagnosis before any changes.
- **EIC-05 — Gate failure diagnosis script (KEEP):** When EIC-04 fails, emit a structured markdown report: (1) N per cell — low N = data starvation, not signal absence; (2) Pooled vs per-symbol IC gap; (3) TF breakdown; (4) Regime coverage. Ships in Wave 2.

### Claude's Discretion (implementation detail, not locked)
- Exact ProcessPoolExecutor chunking strategy / worker count — follow `ICEngine` precedent (`infra.ic_engine.workers=12`) and the `BaseBatch` base class.
- Whether EnsembleICEngine subclasses `ICEngine` or composes its IC math — researcher decides based on code reuse vs. SoC. **Researcher recommendation: COMPOSE, do not subclass** (see Architecture Patterns).
- Service unit name / systemd wiring — follow naming system (`indicagent-ensemble-ic-engine`), register in `service_auditor.py` `_DAG_ORDER`.

### Deferred Ideas (OUT OF SCOPE — do not re-add)
- **Phase 142B** (AlphaFrameWriter + CounterfactualTracker + state machine + mean-pnl gate + SHADOW-REVIEW.md) — only planned after EIC-04 passes.
- **Phase 142C** — 4-variant `stop_atr_mult` calibration grid — only if Phase 142 exits with positive counterfactual P&L.
- **Cost model** (`alpha.cost.*`) — v4.0, when real fills exist.
- **4-variant calibration grid** — deferred to 142C.
- **Frame simulation / CounterfactualTracker** — that is Phase 142B, gated on EIC-04 passing.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EIC-01 | EnsembleICEngine: weekly oneshot, BaseBatch, IC(alpha_score, forward_return_*) per (symbol, tf, regime), BH-FDR + 95% CI + 3-fold walk-forward, writes alpha_ensemble_ic | Compose IC math from `services/ic_engine.py`; extend `BaseBatch` (asyncpg) like `EnsembleTrainer`; ProcessPoolExecutor per-(symbol,tf); see Standard Stack + Architecture Patterns |
| EIC-02 | IC decay curve → hold_max_bars APR calibration | For each (symbol, tf, regime) cell, find first lookahead where `ic_sharpe < alpha.ensemble_ic.decay_threshold`; UPDATE `alpha.frame.hold_max_bars.<regime>.<tf>` via ConfigService; 9 regimes × 4 TFs = 36 keys |
| EIC-03 | Walk-forward stability gate (max/min fold IC Sharpe ratio < 3×) | Compute per-fold IC Sharpe inside the walk-forward loop (ic_engine already collects `fold_ics_list`); add `walk_forward_stable` boolean column; ratio threshold = `alpha.ensemble_ic.wf_stability_ratio` APR seed |
| EIC-04 | Phase gate: ic_ci_lower > 0 in ≥ min_qualifying_fraction of cells | Wave 2 SQL gate-evaluation script (OQ-3 recommendation); reads `alpha_ensemble_ic` WHERE `lookahead='fast' AND ic_ci_lower > 0`, computes fraction over (symbol, tf, regime) cells; threshold from APR not baked in |
| EIC-05 | Gate failure diagnosis script (structured markdown report) | Wave 2 standalone script emitting N-per-cell, pooled-vs-persymbol gap, TF breakdown, regime coverage; reads `alpha_ensemble_ic` + `feature_ic_scores` for comparison |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

These bind this phase. Research recommendations do not contradict any of them.

- **Invariant 1 (executable returns):** All `forward_returns` queries in EnsembleICEngine MUST filter `WHERE return_type = 'executable_open_to_open'`. The `ln(open[T+N+1] / open[T+1])` formula. Theoretical returns capture overnight gaps that cannot be traded and overstate IC. Verified at `services/ic_engine.py:729`.
- **APR mandate:** Every threshold/weight/period/count in `src/` or `services/` lives in `config_state` under `alpha.*`. The new `alpha.ensemble_ic.*` and `alpha.frame.hold_max_bars.*` keys are seeded in the same migration that creates `alpha_ensemble_ic`. No hard-coded numerics in EnsembleICEngine.
- **ProcessPoolExecutor workers are compute-only:** Workers return serializable results (rows, dicts) to main. All DB writes go through a single serial connection in main. Never open a write connection from a worker subprocess (concurrent writers on the same hypertable cause index-page deadlocks — CLAUDE.md fixed this in regime_writer; pattern applies here).
- **Gradient naming:** `return_fast/mid/slow/extended` are the scale identifiers; `alpha.ic.lookahead.fast/mid/slow/extended` are the APR keys (verified values: 1/5/20/60 bars). These are immutable statistical definitions, NOT tunable calibration params.
- **`KafkaProducerClient.publish()` kwarg is `msg=`** — not relevant here (EnsembleICEngine is a batch oneshot, no Kafka producer), but if a future Kafka surface is added, use `msg=`.
- **Exception variable name is `error`** — `except X as error:`, not `exc`.
- **All timestamps UTC** — `datetime.now(UTC)` only.
- **Structlog `event` kwarg collision** — never pass `event=<value>`.
- **Metrics:** `src/observability/metrics.py` (direct OTel SDK). Counters → `.add(1, attrs)`. `JOB_COMPLETED_TOTAL.add(1, {"job": ..., "status": ...})` is the D-06 emit (BaseBatch handles this).
- **Service registry:** when adding the service, update `_DAG_ORDER`, `_LAG_THRESHOLDS` (N/A — oneshot), `_AGENT_ID_TO_UNIT`, and `_ONESHOT_UNITS` in `services/service_auditor.py`.
- **`BaseBatch` is Ring 0** — `src/core/agent/base_batch.py` must not import from `src/intelligence/`. EnsembleICEngine lives in `services/` (Ring 2) and CAN import IC math from `services/ic_engine.py` (also Ring 2). Verified: `ic_engine.py` is already a Ring 2 oneshot.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `alpha_score` source (the predictor being measured) | API / Backend (already produced by `AlphaPublisher` → `alpha_events`) | — | The signal already exists in `alpha_events`; EnsembleICEngine READS it, never writes it |
| Forward returns (the response variable) | Database / Storage (`forward_returns`, `return_type='executable_open_to_open'`) | — | Already produced by `forward_return_writer`; read-only here |
| Regime stratification labels | Database / Storage (`market_regimes.regime_label`, 9 cross-sectional labels) | — | Cross-sectional equity regime model; ic_engine + ensemble_trainer already JOIN on this |
| IC computation (Spearman + CI + walk-forward + BH-FDR) | API / Backend (`services/ic_engine.py` math functions, reused) | — | Pure numpy/scipy functions; compute-only |
| Per-(symbol, tf) parallelism | API / Backend (ProcessPoolExecutor in EnsembleICEngine main) | — | CPU-bound IC compute decoupled from async DB I/O; workers compute-only |
| IC result persistence | Database / Storage (`alpha_ensemble_ic` hypertable, serial writes from main) | — | Single writer connection in main process (ProcessPoolExecutor invariant) |
| hold_max_bars calibration | API / Backend (decay-curve analyzer) → `config_state` (APR) | — | EIC-02 reads IC decay, writes APR keys that 142B will read |
| Gate evaluation (EIC-04) | API / Backend (Wave 2 SQL script) | — | Reads `alpha_ensemble_ic`, computes fraction, emits markdown verdict |

## Standard Stack

### Core (NO new packages — all already installed and verified)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `asyncpg` | 0.31.0 `[VERIFIED: .venv/bin/python -c "import asyncpg"]` | DB pool for `BaseBatch` (read alpha_events/forward_returns/market_regimes, write alpha_ensemble_ic) | Phase 138+ batch services use asyncpg + BaseBatch (ensemble_trainer, alpha_publisher). CLAUDE.md: "asyncpg: JSONB → dict, Timestamps → datetime" |
| `numpy` | 2.4.6 `[VERIFIED]` | IC vector math, masking, Fisher z CI | ic_engine uses it throughout; alpha_score is a 1-column matrix |
| `scipy` | 1.17.1 `[VERIFIED]` | `scipy.stats.rankdata`, `scipy.stats.t` (p-values), `scipy.cluster.hierarchy` (NOT needed — single predictor) | ic_engine imports exactly these |
| `statsmodels` | 0.14.6 `[VERIFIED]` | `statsmodels.stats.multitest.multipletests` (BH-FDR) | ic_engine uses `method="fdr_bh"`; same corpus-level correction pattern |
| `psycopg2` | (already installed) | ONLY if EnsembleICEngine forks the ic_engine worker pattern | ic_engine uses psycopg2 for sync worker connections; BUT ensemble_trainer/alpha_publisher use asyncpg + BaseBatch. **Recommendation: use asyncpg + BaseBatch, avoid psycopg2 entirely** |

### Supporting (project infrastructure — reuse, do not modify)

| Component | Path | Purpose |
|-----------|------|---------|
| `BaseBatch` | `src/core/agent/base_batch.py` | Pool lifecycle, D-06 `job_completed_total`, `content_key()`, error handling. EnsembleICEngine MUST extend this |
| `ICEngineConfig` (pattern) | `services/ic_engine.py:240-308` | Frozen dataclass bound once from APR via `from_apr()`. Replicate as `EnsembleICConfig` with the subset of keys EnsembleICEngine needs |
| IC math primitives | `services/ic_engine.py` (`_fisher_z_ci`, `_p_values_from_ic`, `_compute_ic_rolling_metrics`, `_hac_sharpe_nd`, `_vectorized_ic`, walk-forward loop body) | Import and call; do NOT re-derive |
| `CorpusManifest` | `src/observability/corpus_manifest.py` | Provenance tracking; ensemble_trainer + alpha_publisher + ic_engine all use it |
| `ConfigService` | `src/config/config_service.py` | APR reads (compile-time binding) + writes (hold_max_bars calibration in EIC-02) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Composing ic_engine math (import private functions) | Subclassing ICEngine | **Rejected.** ICEngine is a psycopg2-based raw main() script, NOT a BaseBatch subclass — it has no `execute(pool)` method to inherit, its `__init__` shape is incompatible, and its 54-feature vectorization/clustering is dead weight for a single predictor. Composition is cleaner (SoC) and avoids dragging in collinearity clustering (meaningless for 1 feature). |
| Composing ic_engine math | Forking (copy-paste the math into EnsembleICEngine) | **Rejected.** Forking creates two sources of truth for Fisher z CI / walk-forward / BH-FDR. If Phase A ships a methodology fix (they did — A2/A5), the fork silently diverges and produces a silent wrong answer. Importing keeps them locked together. |
| asyncpg + BaseBatch | psycopg2 + raw main() (ic_engine style) | **Rejected for this phase.** CONTEXT.md mandates BaseBatch. asyncpg is the Phase 138+ standard. psycopg2 is only justified when you need the sync ProcessPoolExecutor worker pattern with per-worker connections (ic_engine's reason). EnsembleICEngine can use BaseBatch + asyncpg for reads/writes and ProcessPoolExecutor for the CPU-bound IC compute (workers receive numpy arrays, return dicts). |

**Installation:**
```bash
# NO INSTALL NEEDED. All packages already in .venv.
.venv/bin/python -c "import scipy, statsmodels, numpy, asyncpg; print('OK')"
```

**Version verification (run before writing the Standard Stack table — already done):**
```bash
.venv/bin/python -c "import scipy, statsmodels, numpy, asyncpg; print(scipy.__version__, statsmodels.__version__, numpy.__version__, asyncpg.__version__)"
# scipy 1.17.1 statsmodels 0.14.6 numpy 2.4.6 asyncpg 0.31.0
```

## Package Legitimacy Audit

> This phase installs ZERO new external packages. Every dependency is already installed in `.venv` and verified at runtime (imports resolve, versions printed above). slopcheck was unavailable (`command -v slopcheck` returned nothing), but since no packages are being installed or recommended for installation, the legitimacy gate is satisfied trivially — there is nothing to audit.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| scipy | PyPI | (already installed) | (already installed) | github.com/scipy/scipy | n/a (pre-existing) | Approved — pre-existing project dep |
| statsmodels | PyPI | (already installed) | (already installed) | github.com/statsmodels/statsmodels | n/a | Approved — pre-existing project dep |
| numpy | PyPI | (already installed) | (already installed) | github.com/numpy/numpy | n/a | Approved — pre-existing project dep |
| asyncpg | PyPI | (already installed) | (already installed) | github.com/MagicStack/asyncpg | n/a | Approved — pre-existing project dep |

**Packages removed due to slopcheck [SLOP] verdict:** none (no new packages proposed)
**Packages flagged as suspicious [SUS]:** none

*If slopcheck was unavailable at research time, all packages above are tagged `[ASSUMED]` and the planner must gate each install behind a `checkpoint:human-verify` task.* — N/A: no installs proposed. All four packages are pre-existing project dependencies verified by direct import in `.venv`.

## Architecture Patterns

### System Architecture Diagram

```
                                                    ┌─────────────────────────────────────────┐
                                                    │  EXISTING (read-only inputs)            │
                                                    │                                         │
                                                    │  alpha_events.alpha_score ──────────┐   │
                                                    │  (the predictor; produced by        │   │
                                                    │   AlphaPublisher Phase 139)         │   │
                                                    │                                     │   │
                                                    │  forward_returns.return_fast/mid/   │   │
                                                    │  slow/extended                      │   │
                                                    │  WHERE return_type =                │   │
                                                    │   'executable_open_to_open' ─────┐  │   │
                                                    │                                  │  │   │
                                                    │  market_regimes.regime_label     │  │   │
                                                    │  (9 cross-sectional labels) ──┐  │  │   │
                                                    └──────────────────────────────┼──┼──┼───┘
                                                                                   │  │  │
                                                                                    │  │  │
┌──────────────────────────────────────────────────────────────────────────────────▼──▼──▼───────┐
│  EnsembleICEngine (services/ensemble_ic_engine.py)                                              │
│  extends BaseBatch (asyncpg)                                                                    │
│                                                                                                │
│  main process:                                                                                 │
│    1. bind EnsembleICConfig.from_apr() (frozen)                                                │
│    2. startup gates: alpha_events non-empty, forward_returns non-empty, market_regimes loaded  │
│    3. discover (symbol, tf) cells from alpha_events                                             │
│    4. load existing alpha_ensemble_ic keys (idempotency)                                       │
│    5. ProcessPoolExecutor: one task per (symbol, tf) ────────────────┐                         │
│       workers (compute-only, psycopg2 or numpy-only):                │                         │
│         - load alpha_events.alpha_score + forward_returns + regime   │                         │
│           for this (symbol, tf)                                      │                         │
│         - for each regime_label in distinct regimes + pooled:        │                         │
│             for each scale in (fast, mid, slow, extended):           │                         │
│                 IC vector + p-value + Fisher z CI                    │                         │
│                 walk-forward (3 folds, scale-specific embargo)       │                         │
│                 IC Sharpe + HAC Sharpe + Sortino + win rate          │                         │
│                 per-fold IC Sharpe (for EIC-03 stability gate)       │                         │
│         - return list[dict] rows (NO DB writes from worker)          │                         │
│    6. collect all worker results in main                           ┌─┘                         │
│    7. corpus-level BH-FDR (single multipletests call across all    │                           │
│       representative cells — here every cell IS representative,     │                           │
│       no clustering step since alpha_score is 1 predictor)         │                           │
│    8. serial write to alpha_ensemble_ic (single asyncpg conn)      │                           │
│    9. _emit_completion("success") — D-06 job_completed_total      │                           │
└────────────────────────────────────────────────────────────────────┼───────────────────────────┘
                                                                       │
                                                          ┌────────────▼─────────────┐
                                                          │  alpha_ensemble_ic       │
                                                          │  (NEW hypertable)        │
                                                          │  ic_ci_lower, ic_sharpe, │
                                                          │  walk_forward_stable,    │
                                                          │  passes_fdr, ...         │
                                                          └────────────┬─────────────┘
                                                                       │
                Wave 2 (EIC-02, EIC-04, EIC-05) ────────────────────────┼───────────────────────
                                                                       │
                          ┌────────────────────────────────────────────┼──────────────────┐
                          ▼                                            ▼                  ▼
                ┌─────────────────────┐                  ┌──────────────────────┐   ┌──────────────────────┐
                │ EIC-02 decay curve  │                  │ EIC-04 gate eval     │   │ EIC-05 diagnosis     │
                │ for each (sym,tf,   │                  │ SQL script:          │   │ markdown report      │
                │  regime): first     │                  │ fraction of cells    │   │ N/cell, pooled gap,  │
                │ lookahead where     │                  │ WHERE ic_ci_lower>0  │   │ TF breakdown,        │
                │ ic_sharpe < thresh  │                  │ >= min_qual_fraction │   │ regime coverage      │
                │ → UPDATE APR        │                  │ → PASS/FAIL verdict  │   │ (only on FAIL)       │
                │   alpha.frame.      │                  └──────────────────────┘   └──────────────────────┘
                │   hold_max_bars.*   │
                └─────────────────────┘
```

A reader can trace the primary use case: `alpha_score` (top-right) flows down through the engine, gets joined to forward_returns + regime, IC is computed per cell, results land in `alpha_ensemble_ic`, and Wave 2 scripts read that table to calibrate hold_max_bars and evaluate the gate.

### Recommended Project Structure
```
services/
├── ensemble_ic_engine.py        # NEW — EnsembleICEngine(BaseBatch), main entrypoint
├── ic_engine.py                 # EXISTING — import IC math primitives from here (DO NOT modify)
└── _batch_utils.py              # EXISTING — load_config_service_sync helper
scripts/ops/alpha/
├── ops_ensemble_ic_gate.py      # NEW (Wave 2) — EIC-04 gate evaluation script
└── ops_ensemble_ic_diagnosis.py # NEW (Wave 2) — EIC-05 failure diagnosis (markdown report)
production/migrations/
└── 187_alpha_ensemble_ic.sql    # NEW — table + APR seeds + (optional) hold_max_bars seeds
tests/unit/
├── test_ensemble_ic_math.py     # NEW — parity tests vs ic_engine on synthetic data
└── test_ensemble_ic_config.py   # NEW — EnsembleICConfig.from_apr binding
```

### Pattern 1: Compose IC math from ic_engine.py (DO NOT subclass, DO NOT fork)
**What:** Import the private numpy/scipy functions from `services/ic_engine.py` and call them directly on the alpha_score vector.
**When to use:** Always — this is the locked methodology-parity requirement (CONTEXT.md "IC math parity").
**Why composition beats subclassing:** `ICEngine` is a raw-psycopg2 script with `main()` and `_compute_symbol_tf(conn, ...)` — it is NOT a `BaseBatch` subclass, has no `execute(pool)` to inherit, and its per-feature vectorization/clustering is meaningless for a single composite predictor. Subclassing would drag in 54-feature collinearity clustering and a `ProcessPoolExecutor`-per-symbol worker model that opens its own psycopg2 connections. Composition lets EnsembleICEngine use BaseBatch+asyncpg (the Phase 138+ standard) while reusing the exact math.
**Example:**
```python
# Source: services/ic_engine.py (verified lines 376-397, 456-462, 537-629)
# Import the private helpers — they are module-level pure functions, safe to import.
from services.ic_engine import (
    _fisher_z_ci,
    _p_values_from_ic,
    _compute_ic_rolling_metrics,
    _vectorized_ic,
    _nan_to_none,
    ICEngineConfig,  # for the lookahead mapping + shared keys
)
from scipy.stats import rankdata
from statsmodels.stats.multitest import multipletests
import numpy as np

# alpha_score is ONE predictor → X is shape [n_obs, 1]
ranks_X = rankdata(alpha_scores.reshape(-1, 1), axis=0)  # [n_obs, 1]
ranks_Y = rankdata(forward_returns_scale)                 # [n_obs]
ic_vector = _vectorized_ic(ranks_X, ranks_Y)              # shape [1]
ic_value = float(ic_vector[0])
p_value = float(_p_values_from_ic(ic_vector, n_valid)[0])
ci_lower_nd, ci_upper_nd = _fisher_z_ci(ic_vector, n_valid)
# ic_sharpe via the same rolling-windows helper (pass n_total_features=1)
sharpe, sharpe_hac, sortino, win_rate, n_windows = _compute_ic_rolling_metrics(
    X_sub, returns_sub, scale_idx, complete_mask, config,
    non_degenerate_mask=np.array([True]), n_total_features=1, stride=scale_stride,
)
```

### Pattern 2: BaseBatch + asyncpg entrypoint (mirror EnsembleTrainer)
**What:** `EnsembleICEngine` extends `BaseBatch`, defines `job_name`, `compute_version`, and `async def execute(self, pool)`, and is launched via `asyncio.run(EnsembleICEngine(db_dsn=db_dsn).run())`.
**When to use:** Always — CONTEXT.md mandates BaseBatch.
**Example:**
```python
# Source: services/ensemble_trainer.py (verified lines 224-236, 649) + src/core/agent/base_batch.py
from src.core.agent.base_batch import BaseBatch

class EnsembleICEngine(BaseBatch):
    job_name = "ensemble-ic-engine"      # matches systemd unit suffix; D-06 label
    compute_version = "1.0.0"            # bumped when IC methodology changes

    async def execute(self, pool: asyncpg.Pool) -> None:
        # bind APR, run startup gates, dispatch ProcessPoolExecutor, write results
        ...

if __name__ == "__main__":
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(EnsembleICEngine(db_dsn=db_dsn).run())
```
**BaseBatch contract satisfied:** `run()` handles pool setup → `execute()` → D-06 `_emit_completion(status, elapsed)` → teardown → `flush_and_shutdown_metrics()`. `content_key()` available for idempotent row keys.

### Pattern 3: ProcessPoolExecutor with compute-only workers + serial writes from main
**What:** Workers receive a (symbol, tf, dsn, config, ...) tuple, open their own READ connection (or receive numpy arrays), compute IC rows, return `list[dict]`. Main process accumulates all rows, applies corpus-level BH-FDR, then writes serially via a single asyncpg connection.
**When to use:** When per-(symbol, tf) IC compute is CPU-bound and embarrassingly parallel.
**CLAUDE.md invariant:** "ProcessPoolExecutor workers are compute-only ... Never open a write connection or call execute_batch/conn.commit() for writes from a worker subprocess."
**Verified at:** `services/ic_engine.py:1763-1872` (`_run_ic_worker` — workers return dicts, no writes) and `services/ic_engine.py:2125-2151` (main accumulates, then `_write_ic_results` serially).

### Pattern 4: Corpus-level BH-FDR (single multipletests call)
**What:** Collect ALL cell p-values across all (symbol, tf, regime, lookahead) cells into one flat list, call `multipletests(pvals, alpha=fdr_alpha, method="fdr_bh")` ONCE, then scatter the adjusted p-values / reject flags back to the rows.
**When to use:** Always — this is the Phase A "P2 fix" that replaced per-(symbol,tf) BH-FDR (which inflated the effective FDR rate 232×).
**Verified at:** `services/ic_engine.py:2213-2240`. For EnsembleICEngine this is SIMPLER than ic_engine: there is no collinearity clustering, so every cell IS a representative — no `cluster_groups` selection step.

### Anti-Patterns to Avoid
- **Subclassing `ICEngine`:** It's not a BaseBatch subclass; you'd inherit psycopg2 + 54-feature clustering you don't need. (See Alternatives Considered.)
- **Forking the IC math:** Two sources of truth for Fisher z CI / walk-forward. Phase A fixes would silently diverge. IMPORT instead.
- **Stratifying on the 4-label `bull/bear/sideways/volatile` regime namespace (OQ-1 trap):** The schema doc (`docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md`) keys `hold_max_bars.*` with these. The LIVE regime system is 9 cross-sectional `market_regimes.regime_label` values. Using the 4-label set means `alpha_ensemble_ic.regime` cannot be joined back to `alpha_events.regime` and the hold_max_bars APR keys have no population path. Use the 9 labels.
- **Baking the 60% threshold into gate logic:** CONTEXT.md EIC-04 explicitly forbids this. Read `alpha.ensemble_ic.min_qualifying_fraction` from APR.
- **Workers writing to DB:** CLAUDE.md ProcessPoolExecutor invariant — concurrent hypertable writers deadlock.
- **Using `theoretical` forward returns:** Invariant 1 violation — overstates IC via overnight gaps. Always `executable_open_to_open`.
- **Forgetting the scale-specific embargo:** Phase A "P3 fix" — fast scale (lookahead=1) uses embargo=1, not max(lookaheads)=60. The embargo is `lookahead_bars` for the current scale.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Spearman IC computation | Manual rank-correlation loop | `_vectorized_ic` + `scipy.stats.rankdata` from `services/ic_engine.py` | Already handles NaN masking, vectorization, edge cases (n<2 → zeros) |
| 95% CI on IC | Circular block bootstrap | `_fisher_z_ci` from `services/ic_engine.py` | Phase A replaced bootstrap with Fisher z (exact asymptotic, O(p), no RNG, no pre-ranking bug) |
| p-values from IC | Manual t-stat computation | `_p_values_from_ic` from `services/ic_engine.py` | t-approximation with df=n-2, handles ic=±1 edge via `max(1-ic^2, 1e-10)` |
| BH-FDR correction | Per-cell or per-symbol FDR | Single corpus-level `statsmodels.multipletests(method="fdr_bh")` call | Phase A "P2 fix": per-symbol FDR inflates the effective rate 232×; corpus-level is correct |
| Walk-forward fold construction | Custom fold loop | Replicate the expanding-window + scale-specific embargo loop from `ic_engine.py:919-940` | Phase A "P0/P3 fix": fixed-origin expanding window, `embargo_bars = lookahead_bars` per scale |
| IC Sharpe / HAC Sharpe / Sortino / win-rate | Manual rolling-window stats | `_compute_ic_rolling_metrics` from `services/ic_engine.py` | Handles the raw-vs-subsampled window conversion (`sharpe_window_size // stride`), n_windows gate, NaN semantics |
| HAC (Newey-West) Sharpe | Manual Bartlett kernel | `_hac_sharpe_nd` from `services/ic_engine.py` | Correct Bartlett-kernel inflation, floors at 1.0, handles K=0 |
| DB pool lifecycle / D-06 / content_key / error handling | Raw `asyncpg.create_pool` + manual `JOB_COMPLETED_TOTAL` | `BaseBatch.run()` template method | Standardized Phase 138+; ensemble_trainer + alpha_publisher + regime_writer all use it |
| APR binding | Per-call `cfg.get_sync()` in hot loop | Frozen dataclass `EnsembleICConfig.from_apr()` bound once at startup | ic_engine pattern (`ICEngineConfig`); picklable for workers; no mid-run drift |
| Provenance / manifest | Ad-hoc logging | `CorpusManifest` from `src/observability/corpus_manifest.py` | ic_engine + ensemble_trainer + alpha_publisher all use it; writes JSON to `.planning/corpus_manifests/` |

**Key insight:** The entire statistical methodology is already implemented, debugged, and Phase-A-corrected in `services/ic_engine.py`. EnsembleICEngine is a thin adapter that (1) reads alpha_events instead of feature_vectors, (2) treats alpha_score as a 1-column feature matrix, (3) skips collinearity clustering (no clusters for 1 feature), and (4) writes to `alpha_ensemble_ic` instead of `feature_ic_scores`. The math is identical.

## Runtime State Inventory

> This is a greenfield phase (new table, new service, new APR keys). No rename/refactor/migration of existing state. However, two existing-state facts materially affect the plan.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `alpha_events` = 0 rows (Phase B corpus re-run IN FLIGHT as of 2026-06-30); `ensemble_alpha` = 0 rows; `forward_returns` = 54.26M rows (1:1, executable_open_to_open); `market_regimes` = 819K rows (9 labels); `feature_ic_scores` = 0 rows mid-rebuild | Plan is unblocked; EXECUTION is blocked until Phase B completes and repopulates alpha_events. EnsembleICEngine's startup gate (`alpha_events` non-empty) will fail loud until then — this is correct behavior. |
| Live service config | `infra.ic_engine.workers = 2` (APR, current); schema doc seeds `hold_max_bars.*` with stale 4-label regime namespace | Seed `infra.ensemble_ic_engine.workers` (default 12, matching ic_engine precedent — but ic_engine is currently set to 2, so 12 may be aspirational; seed 12 as `[conventional]`). Seed `hold_max_bars.*` with 9-label namespace. |
| OS-registered state | None — no systemd unit exists yet for EnsembleICEngine | Wave 1 creates `indicagent-ensemble-ic-engine.service` + timer (weekly); register in `_ONESHOT_UNITS`, `_DAG_ORDER` (priority 8, matching ic-engine/ensemble-trainer/alpha-publisher) |
| Secrets/env vars | None new | — |
| Build artifacts | None — no compiled artifacts, no package install | — |

## Common Pitfalls

### Pitfall 1: Using the stale 4-label regime namespace (OQ-1)
**What goes wrong:** The schema design doc (`docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md` lines 302-317) seeds `alpha.frame.hold_max_bars.bull.5m`, `.bear.5m`, `.sideways.5m`, `.volatile.5m` — but the LIVE regime system is 9 cross-sectional labels.
**Why it happens:** The schema doc was written 2026-06-25, before Phase A confirmed `equity_model_enabled=True` as the live default and before the cross-sectional stratification was verified end-to-end.
**How to avoid:** Use the 9 `market_regimes.regime_label` values: `{low,mid,high}_{bull,neutral,bear}`. Verified at `services/ic_engine.py:768-799` (mr_dict overrides feature_vectors.regime), `services/ensemble_trainer.py:472-477` (JOIN produces ensemble_alpha.regime from market_regimes.regime_label), and the live DB query (`SELECT DISTINCT regime_label FROM market_regimes` → 9 rows). The `alpha_ensemble_ic.regime` column stores these 9 values; `hold_max_bars.<regime>.<tf>` keys use them (9 × 4 = 36 keys).
**Warning signs:** `alpha_ensemble_ic.regime` values don't match `alpha_events.regime` values; hold_max_bars APR keys have no readers.

### Pitfall 2: Subclassing ICEngine instead of composing
**What goes wrong:** Inheriting `ICEngine` drags in psycopg2 connections, 54-feature vectorization, collinearity clustering, and a worker model incompatible with BaseBatch.
**Why it happens:** "Reuse by inheritance" feels like the OOP-correct way to share methodology.
**How to avoid:** Import the pure functions (`_fisher_z_ci`, `_p_values_from_ic`, `_compute_ic_rolling_metrics`, `_vectorized_ic`). They are module-level, stateless, and already battle-tested. Extend `BaseBatch` for lifecycle.
**Warning signs:** EnsembleICEngine `__init__` requires a psycopg2 DSN; clustering code runs on a 1-column matrix.

### Pitfall 3: Forgetting scale-specific embargo (Phase A P3 fix)
**What goes wrong:** Using a fixed 60-bar embargo for all scales starves the fast scale (lookahead=1) of 59 valid observations per fold.
**Why it happens:** Copying old ic_engine code that used `max(lookaheads)` as embargo.
**How to avoid:** `embargo_bars = lookahead_bars` for the current scale. Verified at `services/ic_engine.py:917`.
**Warning signs:** Fast-scale walk-forward folds have dramatically lower N than extended-scale folds.

### Pitfall 4: Per-symbol BH-FDR instead of corpus-level (Phase A P2 fix)
**What goes wrong:** Running `multipletests` once per (symbol, tf) inflates the effective FDR rate by ~232× (one test per cell × 232 cells).
**Why it happens:** "FDR per stratum" sounds conservative.
**How to avoid:** Collect ALL cell p-values into one flat list, call `multipletests` ONCE, scatter results. Verified at `services/ic_engine.py:2213-2240`.

### Pitfall 5: Workers writing to DB (CLAUDE.md invariant)
**What goes wrong:** Concurrent writers on the same TimescaleDB hypertable cause index-page deadlocks.
**Why it happens:** It feels natural to "write as you go" inside a worker.
**How to avoid:** Workers return `list[dict]`; main process writes serially via one connection after corpus BH-FDR. Verified pattern at `services/ic_engine.py:1763-1872` + `_write_ic_results`.

### Pitfall 6: Stratifying on `feature_vectors.regime` (5 HMM labels) instead of `market_regimes.regime_label` (9 cross-sectional)
**What goes wrong:** IC is measured against the wrong regime strata; results don't match the ensemble's actual conditioning variable.
**Why it happens:** `feature_vectors.regime` exists and looks like "the regime column."
**How to avoid:** The ensemble conditions on cross-sectional `market_regimes.regime_label` (verified: ensemble_trainer JOINs market_regimes, alpha_events.regime inherits it). EnsembleICEngine must stratify on the SAME labels. Use the mr_dict pattern from ic_engine (`services/ic_engine.py:771-774`).

### Pitfall 7: Computing IC from alpha_events that span the OOS boundary
**What goes wrong:** In-sample IC is contaminated by OOS data (or vice versa), invalidating the EIC-04 gate.
**Why it happens:** `alpha_events` contains rows on both sides of `alpha.validation.oos_start = 2025-12-24T05:15:00Z`.
**How to avoid:** EnsembleICEngine queries MUST filter `WHERE bar_ts < alpha.validation.oos_start` for the in-sample gate evaluation (EIC-04). The OOS half is reserved for Phase 144. Document this in the query and the gate script.

### Pitfall 8: Empty alpha_events at first run
**What goes wrong:** Phase B corpus re-run is IN FLIGHT; alpha_events is currently 0 rows. EnsembleICEngine will compute nothing.
**Why it happens:** Data dependency on Phase B.
**How to avoid:** Startup gate that raises `RuntimeError("alpha_events is empty. Run ensemble_trainer + alpha_publisher first.")` — crash-loud, mirrors ic_engine's `_assert_prerequisites`. This is correct behavior, not a bug. Execution waits for Phase B; planning is unblocked.

## Code Examples

Verified patterns from the live codebase.

### The exact IC computation cell (adapt for single predictor)
```python
# Source: services/ic_engine.py:850-954 (adapted for alpha_score = 1 predictor)
# Replicates the Phase A corrected methodology: expanding-window WF, scale-specific
# embargo, Fisher z CI, rolling-window IC Sharpe.

for scale_idx, scale in enumerate(("fast", "mid", "slow", "extended")):
    lookahead_bars = lookaheads[scale]  # alpha.ic.lookahead.{scale}: 1/5/20/60

    # Per-scale subsampling: stride = max(min_stride, lookahead_bars)
    scale_stride = max(subsample_min_stride, lookahead_bars)
    sub_idx = np.arange(0, n_regime_raw, scale_stride)
    alpha_sub = alpha_scores_regime[sub_idx]
    returns_sub = returns_regime[sub_idx]
    complete_sub = complete_regime[sub_idx]

    # Filter to complete rows for this lookahead
    valid_mask = complete_sub[:, scale_idx] & np.isfinite(returns_sub[:, scale_idx])
    n_valid = int(valid_mask.sum())
    if n_valid < min_reliable_n:
        continue  # skip — insufficient N

    # IC point estimate + p-value (alpha_score is shape [n_valid, 1])
    ranks_X = rankdata(alpha_sub[valid_mask].reshape(-1, 1), axis=0)
    ranks_Y = rankdata(returns_sub[valid_mask, scale_idx])
    ic_vector = _vectorized_ic(ranks_X, ranks_Y)  # shape [1]
    ic_value = float(ic_vector[0])
    p_value = float(_p_values_from_ic(ic_vector, n_valid)[0])

    # Fisher z 95% CI
    ci_lower_nd, ci_upper_nd = _fisher_z_ci(ic_vector, n_valid)
    ic_ci_lower = float(ci_lower_nd[0])

    # Walk-forward: expanding window with scale-specific embargo
    embargo_bars = lookahead_bars  # P3 fix
    fold_ics = []
    fold_sharpes = []  # NEW for EIC-03 stability gate
    for k in range(walk_forward_folds):  # 3 folds
        train_end = int(n_valid * (k + 1) / (walk_forward_folds + 1))
        test_start = train_end + embargo_bars
        test_end = int(n_valid * (k + 2) / (walk_forward_folds + 1))
        if test_start >= test_end or (test_end - test_start) < min_reliable_n:
            continue
        fold_ic = _vectorized_ic(
            rankdata(ranks_X[test_start:test_end], axis=0),
            ranks_Y[test_start:test_end],
        )[0]
        fold_ics.append(fold_ic)

    # EIC-03: walk-forward stability = max/min fold IC Sharpe ratio < 3x
    # (using fold ICs as a proxy for per-fold Sharpe; or compute per-fold
    # rolling Sharpe if N permits)
    if len(fold_ics) >= 2 and min(np.abs(fold_ics)) > 1e-10:
        wf_stability_ratio = max(np.abs(fold_ics)) / min(np.abs(fold_ics))
        walk_forward_stable = bool(wf_stability_ratio < wf_stability_ratio_threshold)
    else:
        walk_forward_stable = False
```

### Corpus-level BH-FDR (simpler than ic_engine — no clustering)
```python
# Source: services/ic_engine.py:2213-2240 (adapted — every cell is a representative)
# For EnsembleICEngine there is NO collinearity clustering step (alpha_score is 1 predictor).
# Every (symbol, tf, regime, lookahead) cell p-value enters BH-FDR directly.

all_cell_pvals = [r["p_value"] for r in all_results if r["p_value"] is not None]
if all_cell_pvals:
    reject, p_corr, _, _ = multipletests(all_cell_pvals, alpha=fdr_alpha, method="fdr_bh")
    for idx, result_row in enumerate([r for r in all_results if r["p_value"] is not None]):
        result_row["bh_adjusted_p"] = float(p_corr[idx])
        result_row["passes_fdr"] = bool(reject[idx])
```

### EIC-02 decay curve → hold_max_bars calibration
```python
# For each (symbol, tf, regime), find first lookahead where ic_sharpe < decay_threshold.
# Update APR key alpha.frame.hold_max_bars.<regime>.<tf> with the lookahead_bars of the
# PRECEDING scale (the last scale with ic_sharpe >= threshold).
# If no scale crosses the threshold, use the extended lookahead (edge persists).

# Convert gradient scale → bars for the APR value
scale_to_bars = {"fast": 1, "mid": 5, "slow": 20, "extended": 60}  # from alpha.ic.lookahead.*

for (symbol, tf, regime), cells in groupby(results, key=lambda r: (r["symbol"], r["tf"], r["regime"])):
    sorted_cells = sorted(cells, key=lambda r: ["fast","mid","slow","extended"].index(r["lookahead"]))
    hold_bars = scale_to_bars["extended"]  # default: edge persists to extended
    for cell in sorted_cells:
        if cell["ic_sharpe"] is not None and cell["ic_sharpe"] < decay_threshold:
            # Edge expired at this scale — use the previous scale's lookahead
            prev_idx = ["fast","mid","slow","extended"].index(cell["lookahead"]) - 1
            if prev_idx >= 0:
                hold_bars = scale_to_bars[["fast","mid","slow","extended"][prev_idx]]
            else:
                hold_bars = 1  # even fast scale expired — minimal hold
            break
    apr_key = f"alpha.frame.hold_max_bars.{regime}.{tf}"
    await config_service.set_async(apr_key, str(hold_bars), changed_by="ensemble-ic-engine",
                                    reason=f"calibrated from IC decay curve (EIC-02)")
```

### EIC-04 gate evaluation surface (OQ-3 recommendation: SQL script in Wave 2)
```sql
-- Source: NEW — recommended evaluation surface for EIC-04.
-- Run as a script (scripts/ops/alpha/ops_ensemble_ic_gate.py) that reads this query,
-- compares the fraction to alpha.ensemble_ic.min_qualifying_fraction (APR), and emits
-- a PASS/FAIL markdown verdict. Phase 144 re-reads the same query on OOS data
-- (add WHERE bar_ts >= alpha.validation.oos_start for the OOS half).

-- Use the 'fast' lookahead as the primary gate signal (most independent observations;
-- lowest look-ahead-bias contamination). Configurable via alpha.ensemble_ic.gate_lookahead.
WITH qualifying AS (
    SELECT symbol, tf, regime
    FROM alpha_ensemble_ic
    WHERE lookahead = 'fast'              -- APR: alpha.ensemble_ic.gate_lookahead
      AND ic_ci_lower > 0                 -- 95% CI lower bound positive
      AND passes_fdr = true               -- survived corpus-level BH-FDR
      AND walk_forward_stable = true      -- EIC-03 stability gate
      AND scored_at >= NOW() - INTERVAL '7 days'  -- latest run only
    GROUP BY symbol, tf, regime
),
total AS (
    SELECT COUNT(DISTINCT (symbol, tf, regime)) AS n_total
    FROM alpha_ensemble_ic
    WHERE scored_at >= NOW() - INTERVAL '7 days'
)
SELECT
    (SELECT COUNT(*) FROM qualifying) AS n_qualifying,
    (SELECT n_total FROM total) AS n_total,
    (SELECT COUNT(*) FROM qualifying)::float / NULLIF((SELECT n_total FROM total), 0) AS fraction;
-- Gate: fraction >= (SELECT config_value::float FROM config_state WHERE config_key='alpha.ensemble_ic.min_qualifying_fraction')
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Circular block bootstrap 95% CI | Fisher z-transform CI | Phase A (2026-06-30), `services/ic_engine.py:376-397` | Bootstrap had a pre-ranking bug (resampled global ranks instead of re-ranking within sample) producing systematically too-narrow CIs. Fisher z is exact asymptotic, O(p), no RNG. **CONTEXT.md EIC-01 mentions "circular-block-bootstrap" but the live code uses Fisher z — follow the live code, not the CONTEXT.md wording.** |
| Per-symbol BH-FDR (232 tests) | Corpus-level BH-FDR (1 test) | Phase A "P2 fix", `services/ic_engine.py:2213-2240` | Per-symbol FDR inflated the effective rate 232×. Corpus-level is the correct multiple-testing correction. |
| Fixed 60-bar embargo for all scales | Scale-specific embargo (`embargo_bars = lookahead_bars`) | Phase A "P3 fix", `services/ic_engine.py:917` | Fast scale (lookahead=1) was losing 59 valid obs per fold. Now uses embargo=1. |
| Sliding-window walk-forward | Fixed-origin expanding window | Phase A "P0 fix", `services/ic_engine.py:919-940` | Expanding window uses all available history per fold; train_end grows monotonically. |
| Naive IC Sharpe (mean/std) | HAC Newey-West-corrected IC Sharpe | Phase A (migration 177), `services/ic_engine.py:495-534` | Penalizes positively-autocorrelated IC series that inflate naive Sharpe. `alpha.ic.hac_max_lag=3` (K=0 disables). |
| Binary `passes_walkforward` gate | `ic_ci_lower > 0 AND passes_fdr = true` | Phase A "A5" Renaissance redesign | Binary gate was the root cause of the 5m=0-features false negative (721 cells actually had ic_ci_lower > 0). The new gate is the EIC-04 criterion. |

**Deprecated/outdated:**
- **Circular block bootstrap for IC CI:** Replaced by Fisher z. Do NOT reintroduce it despite CONTEXT.md EIC-01 wording — the live `ic_engine.py` is authoritative.
- **4-label regime namespace (`bull/bear/sideways/volatile`):** STALE in the schema doc. Live system uses 9 cross-sectional labels.
- **`theoretical` forward returns:** Banned by Invariant 1. Only `executable_open_to_open`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `alpha.ensemble_ic.decay_threshold = 0.1` is a reasonable starting default | Standard Stack / EIC-02 | Low — explicitly tagged `[initial_estimate]` in CONTEXT.md; recalibrate after first run. If wrong, hold_max_bars calibration is off but the gate (EIC-04) is unaffected. |
| A2 | `alpha.ensemble_ic.min_qualifying_fraction = 0.60` is a reasonable starting default | EIC-04 | Low — explicitly tagged `[initial_estimate]`; the gate logic reads it from APR so recalibration is a config change, not a code change. |
| A3 | `alpha.ensemble_ic.wf_stability_ratio = 3.0` (the EIC-03 "max/min fold ratio < 3×" threshold) is reasonable | EIC-03 | Low — seeded `[initial_estimate]`. If wrong, too few/many cells pass the stability gate; recalibrate from APR. |
| A4 | Worker count `infra.ensemble_ic_engine.workers = 12` matches ic_engine precedent | Runtime State | Low — ic_engine is currently set to 2 in APR (not 12). 12 may be aspirational. Seed 12 `[conventional]`; operator tunes. |
| A5 | EIC-03 "IC Sharpe max/min fold ratio" can be computed from per-fold IC values (not full per-fold rolling Sharpe) | Code Examples | Medium — if true per-fold Sharpe is required (more stable), the walk-forward loop must compute rolling Sharpe inside each fold. The simpler proxy (fold IC ratio) is documented; planner should flag this for confirmation during implementation. If the proxy is too noisy, use per-fold Sharpe. |
| A6 | The gate lookahead for EIC-04 should be 'fast' (most independent observations) | EIC-04 SQL | Medium — `[ASSUMED]`, not in CONTEXT.md. Fast scale has stride=max(min_stride,1)=5 → ~N/5 obs, the densest coverage. If 'mid' or 'slow' is more meaningful (longer-horizon edge), the gate lookahead is configurable via `alpha.ensemble_ic.gate_lookahead` APR. |

**All other claims in this research are `[VERIFIED]` (via direct code read, DB query, or `.venv` import) or `[CITED]` (from the locked CONTEXT.md / Musk audit).**

## Open Questions

1. **EIC-03 fold-stability metric (A5)**
   - What we know: CONTEXT.md says "IC Sharpe max/min fold ratio < 3× across walk-forward folds." ic_engine collects `fold_ics_list` (per-fold IC point estimates), not per-fold IC Sharpe.
   - What's unclear: Is the ratio computed on per-fold IC values (simple, available) or per-fold IC Sharpe (requires rolling-window Sharpe inside each fold — more compute, more stable)?
   - Recommendation: Start with the simpler proxy (per-fold IC ratio). Seed `alpha.ensemble_ic.wf_stability_metric = 'ic_ratio'` so it's swappable. If the gate is too noisy in the first run, switch to `'sharpe_ratio'`.

2. **Cross-sectional alpha_score IC (pooling all 58 symbols per regime)**
   - What we know: feature IC engine has a `_compute_cross_sectional_tf` path (symbol='POOLED'). The ensemble_trainer derives weights from cross-sectional IC.
   - What's unclear: Should EnsembleICEngine ALSO emit a cross-sectional alpha_score IC row (symbol='POOLED') in addition to per-symbol rows? This would mirror feature_ic_scores and give the gate more statistical power (58× N per cell).
   - Recommendation: YES — emit both per-symbol and cross-sectional (symbol='POOLED') rows, mirroring ic_engine. The EIC-04 gate can then be evaluated on either surface. Add `is_pooled` column to `alpha_ensemble_ic`. This is a discretion-area implementation detail, not a scope change.

3. **Weekly cadence vs Phase B completion**
   - What we know: CONTEXT.md says "weekly oneshot." Phase B corpus re-run is in flight.
   - What's unclear: Should the first run be manual (after Phase B) or timer-triggered immediately?
   - Recommendation: Ship the systemd unit + timer (weekly), but the startup gate (alpha_events non-empty) prevents premature runs. First meaningful run happens the week after Phase B completes and alpha_publisher repopulates alpha_events.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL/TimescaleDB | All DB ops | ✓ | (live, `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent`) | — |
| `.venv` Python | Service execution | ✓ | (project venv) | — |
| scipy | IC math | ✓ | 1.17.1 `[VERIFIED]` | — |
| statsmodels | BH-FDR | ✓ | 0.14.6 `[VERIFIED]` | — |
| numpy | Vector math | ✓ | 2.4.6 `[VERIFIED]` | — |
| asyncpg | BaseBatch DB pool | ✓ | 0.31.0 `[VERIFIED]` | — |
| `alpha_events` data | EnsembleICEngine compute | ✗ (0 rows — Phase B in flight) | — | Crash-loud startup gate (correct); execution waits for Phase B |
| `forward_returns` data | Forward return response variable | ✓ | 54.26M rows `[VERIFIED]` | — |
| `market_regimes` data | Regime stratification | ✓ | 819K rows, 9 labels `[VERIFIED]` | — |

**Missing dependencies with no fallback:** None that block planning. `alpha_events` emptiness blocks EXECUTION only, and the crash-loud gate handles it correctly.

**Missing dependencies with fallback:** None.

## Validation Architecture

> `workflow.nyquist_validation` is not set in `.planning/config.json` (key absent) — treat as enabled. Include this section.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (project standard; `.venv/bin/pytest tests/unit/ -v`) |
| Config file | `pytest.ini` / `pyproject.toml` (project root) |
| Quick run command | `.venv/bin/pytest tests/unit/test_ensemble_ic_*.py -x -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` (per CLAUDE.md Done-Coding SOP) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EIC-01 | IC(alpha_score, forward_return) computed correctly; parity with ic_engine on synthetic data | unit | `.venv/bin/pytest tests/unit/test_ensemble_ic_math.py -x` | ❌ Wave 0 |
| EIC-01 | EnsembleICConfig.from_apr() binds all keys | unit | `.venv/bin/pytest tests/unit/test_ensemble_ic_config.py -x` | ❌ Wave 0 |
| EIC-01 | BH-FDR applied at corpus level (not per-symbol) | unit | `.venv/bin/pytest tests/unit/test_ensemble_ic_bh_fdr.py -x` | ❌ Wave 0 |
| EIC-02 | Decay curve → hold_max_bars correct lookahead selection | unit | `.venv/bin/pytest tests/unit/test_ensemble_ic_decay.py -x` | ❌ Wave 0 |
| EIC-03 | walk_forward_stable boolean correct (ratio < 3×) | unit | `.venv/bin/pytest tests/unit/test_ensemble_ic_wf_stability.py -x` | ❌ Wave 0 |
| EIC-04 | Gate fraction computed correctly; threshold from APR | unit | `.venv/bin/pytest tests/unit/test_ensemble_ic_gate.py -x` | ❌ Wave 0 |
| EIC-01 | Executable returns filter (`return_type='executable_open_to_open'`) enforced | unit | `.venv/bin/pytest tests/unit/test_ensemble_ic_executable_returns.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/test_ensemble_ic_*.py -x -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q` (full suite, CLAUDE.md SOP)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_ensemble_ic_math.py` — covers EIC-01 (parity vs ic_engine `_fisher_z_ci`, `_p_values_from_ic`, `_compute_ic_rolling_metrics` on synthetic alpha_score vector)
- [ ] `tests/unit/test_ensemble_ic_config.py` — covers EIC-01 (EnsembleICConfig.from_apr binding; frozen dataclass; picklable for workers)
- [ ] `tests/unit/test_ensemble_ic_bh_fdr.py` — covers EIC-01 (corpus-level multipletests; no clustering step)
- [ ] `tests/unit/test_ensemble_ic_decay.py` — covers EIC-02 (first-threshold lookahead selection)
- [ ] `tests/unit/test_ensemble_ic_wf_stability.py` — covers EIC-03 (max/min fold ratio gate)
- [ ] `tests/unit/test_ensemble_ic_gate.py` — covers EIC-04 (fraction query; APR threshold read)
- [ ] `tests/unit/test_ensemble_ic_executable_returns.py` — covers Invariant 1 (filter enforced)
- [ ] Framework install: none needed — pytest already in `.venv`

## Security Domain

> `security_enforcement` is not explicitly set in `.planning/config.json` — treat as enabled. This phase is a batch statistical compute service with no new attack surface (no user input, no network ingress, no auth). Minimal security domain coverage.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth surface — batch oneshot, no endpoints |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | No user-facing endpoints; DB access via service account (existing pattern) |
| V5 Input Validation | yes | Validate `--symbols` / `--tf` CLI args against known instrument/TF sets; reject unknown regimes (assert regime ∈ 9 market_regimes labels) |
| V6 Cryptography | no | No crypto operations |
| V7 Logging | yes | structlog → `logs/ensemble_ic_engine.log` (CLAUDE.md logging pattern); D-06 job_completed_total emitted |
| V9 Communications | no | No network egress (DB is local; no Kafka producer in this phase) |

### Known Threat Patterns for batch IC compute

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via CLI `--symbols` | Tampering | Use parameterized queries (`$1`, `%s`) — never f-string user input into SQL. ic_engine uses `%s` params throughout (verified). |
| Regime label injection (unknown regime string) | Tampering | Startup gate asserts regime ∈ distinct market_regimes labels; reject unknown |
| Data exfiltration via IC rows | Information Disclosure | N/A — IC rows are aggregate statistics, not raw PII/positions. No new egress path. |

## Sources

### Primary (HIGH confidence)
- `services/ic_engine.py` (live source — read in full, 2385 lines) — IC math primitives, ProcessPoolExecutor worker pattern, corpus-level BH-FDR, scale-specific embargo, expanding-window walk-forward, Fisher z CI, HAC Sharpe, startup gates, idempotency, manifest. All line numbers cited.
- `src/core/agent/base_batch.py` (live source — read in full, 171 lines) — `BaseBatch` contract: `run()` template, `execute(pool)` abstract, `content_key()`, `_emit_completion()` D-06, pool lifecycle.
- `services/ensemble_trainer.py` (live source — read key sections) — BaseBatch + asyncpg pattern, `EnsembleTrainer(BaseBatch)`, `job_name="ensemble-trainer"`, `compute_version="1.0.0"`, market_regimes JOIN (lines 472-477), APR loading via asyncpg.
- `services/alpha_publisher.py` (live source — read key sections) — `AlphaPublisher(BaseBatch)`, `event_id = BaseBatch.content_key(...)`, asyncpg entrypoint pattern.
- `services/service_auditor.py` (live source — grep) — `_DAG_ORDER` (priority 8 for ic-engine/ensemble-trainer/alpha-publisher), `_ONESHOT_UNITS`, `_AGENT_ID_TO_UNIT`.
- Live DB queries against `indicagent` (2026-06-30): `alpha_events` schema (alpha_score column confirmed), `market_regimes` (9 labels confirmed), `feature_vectors.regime` (5 HMM labels — NOT used for ensemble IC), `feature_ic_scores` schema (32 columns), `forward_returns` schema (return_type + 4 scales + complete_* flags), `config_state`/`config_schema` (columns are `config_key`/`config_value`, NOT `key`/`value`), APR keys present/absent.
- `.venv/bin/python` import verification: scipy 1.17.1, statsmodels 0.14.6, numpy 2.4.6, asyncpg 0.31.0; `multipletests`, `rankdata`, `t_dist`, `fcluster`, `linkage`, `squareform` all resolve.
- `.planning/phases/142A-ensemble-ic-measurement-planned/142A-CONTEXT.md` — locked decisions EIC-01..05, deferred ideas, open questions OQ-1/2/3.
- `docs/ideas/phase142-redesign-musk5step-audit.md` — the authority on scope (KEEP/DELETE/SIMPLIFY verdicts).
- `docs/plans/2026-06-25-v30-alpha-lifecycle-schema.md` — `alpha_ensemble_ic` DDL, APR key lists (regime namespace STALE — see OQ-1 resolution).

### Secondary (MEDIUM confidence)
- `docs/intelligence/intelligence-alphaengine.md` — AlphaEngine concept (alpha_score formula, regime conditioning, BaseBatch architecture diagram).
- `docs/analysis/ic-discovery-report.md` — IC methodology reference (4-symbol discovery; full corpus pending).
- `.planning/STATE.md` — current data state (alpha_events 12.47M pre-truncate; Phase B rebuilding), key load-bearing decisions (HMM_RANDOM_STATE, gradient naming, OOS boundary).
- `.planning/ROADMAP.md` — v3.1 phase sequence, Phase 142 gating.

### Tertiary (LOW confidence)
- None. Every load-bearing claim is backed by a Primary source.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified installed in `.venv` with exact versions; no new packages needed.
- Architecture: HIGH — BaseBatch + asyncpg pattern verified in 2 sibling services (ensemble_trainer, alpha_publisher); ic_engine math verified line-by-line; regime namespace verified via live DB query.
- Pitfalls: HIGH — all 8 pitfalls traced to specific code lines or live DB state; OQ-1 (regime namespace) resolved definitively.
- Open questions: MEDIUM — A5 (fold-stability metric) and A6 (gate lookahead) are implementation-detail assumptions requiring first-run validation, both backed by APR-key escape hatches.

**Research date:** 2026-06-30
**Valid until:** 2026-07-30 (30 days — stable domain; methodology is locked by Phase A and the Musk audit). Re-verify `alpha_events` row count (currently 0, Phase B in flight) before execution.

## RESEARCH COMPLETE

**Phase:** 142A - Ensemble IC Measurement
**Confidence:** HIGH

### Key Findings
- **OQ-1 RESOLVED (regime namespace):** The corrected ic_engine stratifies on the 9 cross-sectional `market_regimes.regime_label` values (`{low/mid/high}_{bull/neutral/bear}`), NOT the stale 4-label `bull/bear/sideways/volatile` in the schema doc. Verified at `services/ic_engine.py:768-799` (mr_dict overrides feature_vectors.regime when `equity_model_enabled=True`, the live default) and `services/ensemble_trainer.py:472-477` (the JOIN that produces `alpha_events.regime`). The `alpha_ensemble_ic.regime` column and `alpha.frame.hold_max_bars.<regime>.<tf>` APR keys MUST use these 9 labels (9 × 4 TFs = 36 hold_max keys). This changes the migration DDL and APR seed set versus the schema doc.
- **OQ-2 RESOLVED (alpha_score source):** The predictor is `alpha_events.alpha_score` (double precision, NOT NULL). Population path: `ensemble_trainer.py` (Phase 139) writes `ensemble_alpha.alpha_score` via IC-weighted matmul → `alpha_publisher.py` (Phase 139) reads `ensemble_alpha`, applies emission gates, writes `alpha_events`. IC is measured against `alpha_events.alpha_score` joined to `forward_returns` on (symbol, tf, bar_ts). NOTE: both `alpha_events` and `ensemble_alpha` are currently 0 rows (Phase B corpus re-run in flight) — planning unblocked, execution blocked until Phase B.
- **OQ-3 RESOLVED (gate evaluation surface):** Recommend a SQL gate-evaluation script in Wave 2 (`scripts/ops/alpha/ops_ensemble_ic_gate.py`) that queries `alpha_ensemble_ic` for the fraction of cells with `ic_ci_lower > 0 AND passes_fdr = true AND walk_forward_stable = true`, compares to `alpha.ensemble_ic.min_qualifying_fraction` (APR, not baked in), and emits a PASS/FAIL markdown verdict. Phase 144 re-reads the same query on OOS data (`WHERE bar_ts >= alpha.validation.oos_start`).
- **Methodology parity:** EnsembleICEngine COMPOSES (does not subclass/fork) the IC math from `services/ic_engine.py` — import `_fisher_z_ci`, `_p_values_from_ic`, `_compute_ic_rolling_metrics`, `_vectorized_ic`. The Phase A corrections (Fisher z CI replacing bootstrap, corpus-level BH-FDR, scale-specific embargo, expanding-window WF, HAC Sharpe) are all in those functions. CONTEXT.md EIC-01 mentions "circular-block-bootstrap" but the LIVE code uses Fisher z — follow the code.
- **BaseBatch mandate:** EnsembleICEngine extends `BaseBatch` + asyncpg (mirroring `EnsembleTrainer`/`AlphaPublisher`), NOT the raw-psycopg2+main() pattern of `ic_engine.py`. ProcessPoolExecutor parallelizes per-(symbol,tf) with compute-only workers; serial DB writes from main after corpus-level BH-FDR.

### File Created
`/home/bg/dev/indicagent/.planning/phases/142A-ensemble-ic-measurement-planned/142A-RESEARCH.md`

### Confidence Assessment
| Area | Level | Reason |
|------|-------|--------|
| Standard Stack | HIGH | All 4 packages verified installed in `.venv` with exact versions; imports resolve; no new packages needed |
| Architecture | HIGH | BaseBatch+asyncpg pattern verified in 2 sibling services; ic_engine math read line-by-line; composition-vs-subclass decision grounded in ICEngine's actual structure (raw psycopg2, not BaseBatch) |
| Pitfalls | HIGH | All 8 pitfalls traced to specific code lines or live DB state; OQ-1 regime namespace resolved via 3 independent verifications (ic_engine code, ensemble_trainer code, live DB query) |
| IC Methodology | HIGH | Phase A corrections verified in live ic_engine.py source; State of the Art table documents each fix with line numbers |
| Regime Namespace (OQ-1) | HIGH | Triangulated across ic_engine.py:768-799, ensemble_trainer.py:472-477, alpha_publisher.py:289, and live `SELECT DISTINCT regime_label FROM market_regimes` (9 rows) |

### Open Questions
- A5 (EIC-03 fold-stability metric: per-fold IC ratio vs per-fold Sharpe ratio) — seeded as APR-swappable; confirm on first run.
- A6 (EIC-04 gate lookahead: 'fast' recommended) — seeded as APR-swappable; confirm on first run.
- Cross-sectional alpha_score IC row (symbol='POOLED') recommended as an addition mirroring feature_ic_scores — discretion-area, planner decides.

### Ready for Planning
Research complete. All three open questions (OQ-1 regime namespace, OQ-2 alpha_score source, OQ-3 gate surface) are resolved with HIGH-confidence evidence from live code and DB state. Planner can now create PLAN.md files for the 2-wave structure (Wave 1: migration + EnsembleICEngine service; Wave 2: decay-curve calibration + EIC-04 gate script + EIC-05 diagnosis script).
