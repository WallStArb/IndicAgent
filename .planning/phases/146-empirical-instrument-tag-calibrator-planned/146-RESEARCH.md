# Phase 146: Empirical Instrument Tag Calibrator - Research

**Researched:** 2026-07-17
**Domain:** Statistical calibration batch service (OLS factor betas + HAC standard errors + BH-FDR gating) over TimescaleDB daily-bar data; schema migration; taxonomy data cleanup
**Confidence:** HIGH (live DB/code verified for nearly every claim below; the few `[ASSUMED]` items are called out explicitly and listed in the Assumptions Log)

## Summary

Phase 146 builds `TagCalibrator` (concept name; see F9 rename below), a weekly `BaseBatch` oneshot
that replaces human-asserted `instrument_tags` rows with measured OLS factor betas (standardized
loadings), reusing this codebase's existing IC measurement kernel (`ic_math.py`) rather than
reimplementing OLS/HAC/FDR machinery. The design is fully specced in two canonical docs
(`docs/research/stratification-instrument-tag-calibrator.md`, F1-F9 2026-07-06 review, and
`docs/research/fable-2026-07-16-tag-calibrator-taxonomy-review.md`, T1-T7 2026-07-16 review); this
research verifies that design against live 2026-07-17 code/DB state so the planner can write
executable tasks.

Three things this research confirms are still true as of today (one day after the CONTEXT.md
snapshot): (1) `instrument_tags` genuinely has no `valid_from`/`valid_to` columns — confirmed via
live `\d instrument_tags` — so the migration is not optional scaffolding, it is a hard blocker for
the design doc's expiry logic; (2) the credit_cycle/credit_risk duplicate on HYG/LQD is exactly as
CONTEXT.md describes; (3) three of the original 8 ROADMAP factor series (VIX, USO, DXY) are
confirmed absent or zero-bar in `instruments`/`market_data_ohlcv`, and all of CONTEXT.md's D-02
substitute proxies (UUP, FXI, HYG-IEF, TIP-IEF, IEF-SHY, breadth_vol.py SPY-realized-vol, XLE-SPY)
are live with adequate history through the `market_data_ohlcv_tradeable` boundary view — though see
Pitfall 1 below, a genuinely new finding: the **tradeable-view bar counts are materially lower than
the raw-table counts CONTEXT.md cites**, because CONTEXT.md's counts came from the raw table, not
the boundary view D-11 mandates for reads. This does not change any go/no-go decision (every
proxy still clears 252-day lookback by a wide margin) but the planner must not reuse CONTEXT.md's
cited bar-count numbers as the operative ones — use this doc's tradeable-view numbers instead.

**Primary recommendation:** Build Wave 0 (taxonomy cleanup + one schema migration) before Wave 1
(the `TagCalibrator` service). New math lives in a new `src/intelligence/statistics/factor_math.py`
module that imports `_fisher_z_ci`, `_p_values_from_ic`, `_hac_sharpe_nd`, and `apply_bh_fdr`
directly from `ic_math.py` — do not reimplement any of these. `TagCalibrator` extends `BaseBatch`
(`src/core/agent/base_batch.py`), mirroring `EnsembleICEngine`'s shape almost exactly (same
`job_name`/`compute_version` class attrs, same `ConfigService`-via-APR-dict pattern, same
`except Exception as error:` convention). No new third-party packages are needed — `statsmodels`
and `scipy` are already project dependencies and already used by `ic_math.py` for exactly this
class of computation (`multipletests`, `t_dist`).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| OLS/HAC beta computation (`factor_math.py`) | API/Backend (Ring 1 statistics module) | — | Pure functions, no DB, no config — same tier as `ic_math.py` which it extends |
| Nightly/weekly calibration orchestration (`TagCalibrator`) | API/Backend (Ring 2 batch service) | Database/Storage (writes) | `BaseBatch` oneshot, DB-writing service per DAG invariant #3 — not a pipeline stage |
| Factor-series return construction (long-short spreads: HYG-IEF, TIP-IEF, IEF-SHY, XLE-SPY) | API/Backend (`factor_math.py` helper) | Database/Storage (reads `market_data_ohlcv_tradeable`) | Shared constructor, one function, 4 call sites |
| `vol_beta` factor input | API/Backend (reuses `breadth_vol.py`'s pure `_compute_vix_pct_rank`/realized-vol logic) | — | Already-computed live signal; zero new ingestion per D-02 |
| Schema (`tag_vocabulary`, `instrument_tags` migrations) | Database/Storage | — | Postgres/TimescaleDB DDL, no compute |
| Taxonomy data cleanup (credit merge, housing_cycle delete, spread_leg backfill) | Database/Storage | — | One-time data migration, not application code |
| APR keys (`alpha.tag_auditor.*` or `alpha.tag_calibrator.*`) | Database/Storage (`config_state`) | API/Backend (`ConfigService.get_sync`) | Standard APR pattern, no new tier |
| Downstream tag queries (dashboard, AI agents, regime classifier) | Out of scope this phase | — | Consumers read `instrument_tags`/`tag_vocabulary`; none require code changes for this phase |

No browser/client or CDN/static tier involvement — this is a pure backend batch-measurement phase
with zero user-facing surface.

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Add Wave 0 (taxonomy cleanup + factor-data readiness) before the original Wave 1
  (TagAuditor/TagCalibrator service) / Wave 2 (DB migration) / Wave 3 (Phase 2 design). Also fixes
  the ROADMAP's Wave 1/2 ordering defect — the migration creating the columns the service
  reads/writes must land before or at the start of the service build, not after.
- **D-02 (concept-over-specific-proxy, applied to every factor series):**
  - `dollar_beta`: **UUP** (not DXY)
  - `china_beta`: **FXI** (not KWEB — FXI wins on history depth)
  - `credit_beta`: **HYG-IEF long-short** (not raw HYG) — purifies credit-spread signal from HYG's
    embedded equity beta
  - `inflation`: **TIP-IEF long-short** (not raw TIP beta, which re-measures `rate_beta`)
  - `yield_curve`: **IEF-SHY long-short**
  - `vol_beta`: **reuse the existing SPY-realized-vol z-score in `src/intelligence/regime_signals/
    breadth_vol.py`** as the factor input — not VIX ingestion
  - `oil_beta`: **measurable in Phase 1 via XLE-SPY long-short** — not deferred; same
    long-short-purification technique as credit/inflation
- **D-03:** Merge `credit_cycle` into `credit_risk` — HYG and LQD each carry both tags at
  near-identical weights (verified live below); migrate assignments (max weight on collision),
  retire `credit_cycle` from `tag_vocabulary`, record as banned alias in glossary.md.
- **D-04:** `gold_beta` stays a required Phase 1 input (GLD, cleanest series, 7,313+ raw bars). Do
  NOT seed a human `gold_beta`/gold-sensitivity tag — under F8 Simons-inversion, tags are derived
  read-outs, not beliefs. `commodity_metals_precious` (exposure) already covers the human query
  handle.
- **D-05:** `yield_curve`, `inflation`, `em_flows`, `semi_cycle`, `yen_carry` are all measurable
  under the full-matrix OLS loop (F8) at near-zero marginal cost — treat as in-scope Phase 1
  primitives, not deferred/bespoke work.
- **D-06:** `fed_policy` and `geopolitical` stay `measurement_type='definitional'` with an owner
  annotation (TAG-03) — kept, not deleted, despite overlap with rate_beta+curve_beta.
- **D-07:** `housing_cycle` is **deleted** (not just low-population) — its own factor series IS its
  sole holder (XHB), a self-regression tautology, mathematically meaningless regardless of count.
- **D-08:** `volatility` (zero holders today) is **kept, not deleted** — a vocabulary row costs
  nothing; contrast directly with D-07's broken-concept deletion. Becomes the natural home once
  `vol_beta` measures via the breadth_vol.py proxy.
- **D-09:** Fix `spread_leg` (28/410 rows, 17 NULL evidence) via one Wave 0 data migration +
  boundary-style unit test — NOT a new pairs table (zero code consumers exist). Backfill
  mechanically recoverable pairs (LQD←CWB, TLT←EDV, SPY←IPO/EZU, SCHD←VYM), add missing reciprocal
  rows (UUP, USMV, FXI), defer the 13 non-mechanical pairs to Wave 0 execution time (human pass),
  delete unrecoverable rows rather than fabricate evidence.
- **D-10:** `instrument_tags` has no `valid_from`/`valid_to` today (confirmed live) — add these
  columns in the Wave 0/1 migration (T6) before the calibration loop's expiry write can work.
- **D-11:** Daily-return reads for factor-series construction go through
  `market_data_ohlcv_tradeable`, not raw `market_data_ohlcv` — this project's tradeable-boundary
  rule, which postdates the design doc.
- **D-12:** The engine (`TagCalibrator`/`factor_math.py`) must be generic —
  `(symbol, factor_series, measurement_type)` driven from `tag_vocabulary`, no hard-coded
  assumptions specific to the ~10 initial primitives. Does NOT license proactively seeding new
  stratifications (tech/GICS sectors/factor styles) beyond what's already live — `tech_beta`
  (XLK-SPY) is explicitly NOT added this phase despite being data-viable.

### Claude's Discretion

- Exact migration numbers, `TagCalibrator`/`factor_math.py` method signatures, APR key names
  (`alpha.tag_auditor.*` or renamed to `alpha.tag_calibrator.*` per F9) — follow the design doc's
  already-revised schema/loop plus this session's Wave 0 additions.
- `factor_math.py` reuses `ic_math.py`'s measurement kernel (`_fisher_z_ci`, `_p_values_from_ic`,
  the HAC pattern from `_hac_sharpe_nd`) per F4 — new math (OLS loading with Newey-West HAC SEs,
  lagged cross-correlation, mutual information vs. a discrete state series) goes in the new module.

### Deferred Ideas (OUT OF SCOPE)

- `spread_leg`'s 13 non-mechanically-recoverable pairs — needs a human pass by whoever seeded
  migration 227 (or the project owner's own recollection) at Wave 0 execution time.
- Phase 2 regime-conditioning (Wave 3) — unchanged in scope, gated on Phase 1 shipping first.
- The design doc's open-question section (lines 694-728) — closed against the 2026-07-16 review,
  no further discussion needed.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TAG-01 | Measured betas (nightly/weekly batch, `TagCalibrator`): core factor betas via OLS regression of instrument daily returns vs. factor series, gated on bootstrap-CI/HAC p-value + `loading_threshold`, with exponential half-life decay | Revised schema + revised calibration loop (design doc, verbatim below); `ic_math.py` reuse table; live factor-series bar-count verification; `factor_math.py` module contents spec |
| TAG-02 | Regime conditioning (Phase 2 extension): PK extends `(symbol, tag)` → `(symbol, tag, regime)`, gated on IC stratification showing regime-dependent divergence | Explicitly OUT OF SCOPE for Wave 1-2 of this phase (Wave 3 is design-only); F6.3's per-stratum sample-size gate documented for forward reference |
| TAG-03 | Discovery gate: tags fully computable from the factor vector must not exist as permanent human assertions; human-only tags stay `measurement_type='definitional'` with owner | Revised schema's `measurement_type` CHECK constraint; D-06/D-07/D-08 taxonomy resolutions; glossary.md category definitions (verified live below) |

## Live Schema State (verified 2026-07-17)

### `instrument_tags` (current columns — confirms D-10)

```
symbol      | text                     | not null
tag         | text                     | not null
weight      | double precision         | not null default 1.0
source      | text                     | not null default 'human'
evidence    | jsonb                    |
assigned_at | timestamp with time zone | not null default now()
PRIMARY KEY (symbol, tag)
CHECK (source IN ('human','empirical','ai'))
CHECK (weight >= 0.0 AND weight <= 1.0)
FK symbol -> instruments(symbol) ON DELETE CASCADE
FK tag -> tag_vocabulary(tag)
```

**No `valid_from`/`valid_to`, no `loading`/`p_value`/`bh_adjusted_p`/`passes_fdr`/
`consecutive_fails`/`sample_n`/`estimated_at`** — all of these are Wave 1 migration additions per
the design doc's revised schema. `[VERIFIED: live psql \d instrument_tags]`

### `tag_vocabulary` (current columns)

```
tag         | text | not null (PK)
category    | text | not null
description | text | not null
CHECK (category IN ('exposure','sensitivity','factor_regime','cycle_position','signal_role','macro_driver'))
```

**No `factor_series`, `measurement_type`, `lookback_days`, `loading_threshold`, `half_life_days`**
— all Wave 1 migration additions. Note the category CHECK already reflects the 6-category
taxonomy (migration 228 did this split from 4→6 categories in 2026-07's earlier ETF expansion
work — see "Migration history" below); T7's finding that this taxonomy is sound (only the
credit pair is a real duplicate) does not require touching this CHECK constraint.
`[VERIFIED: live psql \d tag_vocabulary]`

### `instrument_annotations` (unchanged, no Wave 1 additions needed)

Already has `valid_from`/`valid_to` (added in the original migration 227) — this table's temporal
validity was always correct; only `instrument_tags` was missing it. `[VERIFIED: live psql \d
instrument_annotations]`

### Live data snapshot (re-verified 2026-07-17, one day after CONTEXT.md's 2026-07-16 snapshot — all numbers unchanged)

| Fact | Value | Matches CONTEXT.md? |
|------|-------|---------------------|
| `tag_vocabulary` rows by category | exposure 37, macro_driver 10, signal_role 9, factor_regime 6, sensitivity 5, cycle_position 4 (71 total) | Yes, exact match |
| `instrument_tags` total rows | 410 | Yes |
| `spread_leg` rows / NULL-evidence | 28 / 17 | Yes |
| HYG `credit_cycle`/`credit_risk` weights | 0.9 / 1.0 | Yes |
| LQD `credit_cycle`/`credit_risk` weights | 0.8 / 0.8 | Yes |
| `housing_cycle` holders | XHB only, weight 1.0 | Yes |
| `volatility` tag holders | 0 | Yes |

No re-verification surprises — CONTEXT.md's snapshot is current. `[VERIFIED: live psql queries,
2026-07-17]`

## Standard Stack

### Core

| Library | Version (installed) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `statsmodels` | >=0.14.6 (pyproject.toml) / >=0.14.4 (requirements.txt) | `multipletests` (BH-FDR), OLS-adjacent statistical machinery | Already a project dependency; `ic_math.py` already imports `statsmodels.stats.multitest.multipletests` for the exact same BH-FDR pattern this phase needs (`apply_bh_fdr`, reusable directly) `[VERIFIED: grep of requirements.txt/pyproject.toml]` |
| `scipy` | >=1.15.0 | `scipy.stats.norm`, `scipy.stats.t`, `scipy.stats.rankdata` for CI/p-value math | Already imported by `ic_math.py` for `_fisher_z_ci`/`_p_values_from_ic` `[VERIFIED]` |
| `numpy` | (already a dependency, unpinned version check not needed — used pervasively) | Vectorized OLS loading computation, HAC inflation factor | Same as every other statistics module in this codebase |

**No new packages needed.** `factor_math.py`'s new math (OLS loading via covariance ratio —
`loading = beta * sigma_factor / sigma_instrument`, per F3 — and Newey-West HAC standard errors)
is expressible with `numpy`+`scipy` primitives already in the codebase; there is no need for
`statsmodels.regression.linear_model.OLS` or `statsmodels.stats.sandwich_covariance` — the design
doc's F3 resolution defines `loading` as a standardized correlation-equivalent (bounded [-1,1]),
which for univariate OLS is computable directly as `cov(x,y)/(std(x)*std(y))` (i.e., the Pearson
correlation), avoiding a full OLS solve for the single-regressor case. The HAC correction on top of
that follows `_hac_sharpe_nd`'s Newey-West Bartlett-kernel pattern (Section "Code Examples" below).

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `asyncpg` | (existing dependency) | DB pool access inside `BaseBatch.execute()` | Every `BaseBatch` subclass uses this; `TagCalibrator` is no exception |
| `structlog` | (existing dependency) | `BaseBatch.__init__` auto-configures `self.logger` | No per-service setup needed |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Correlation-equivalent loading (Pearson on raw returns) | Full `statsmodels.OLS` with `HC`/`HAC` covariance estimator | OLS gives an unstandardized beta requiring a separate normalization step (F3); the correlation-equivalent IS the standardized loading directly for univariate regression — simpler, matches `ic_math.py`'s existing `_vectorized_ic` machinery, no new dependency surface |
| Reusing `_hac_sharpe_nd`'s exact Bartlett-kernel inflation-factor formula for the loading's HAC-adjusted standard error | A fresh Newey-West SE implementation from `statsmodels.stats.sandwich_covariance.cov_hac` | The in-house formula is already tested, already understood by this codebase's reviewers, and produces the same asymptotic correction; introducing a second (library) HAC implementation risks two subtly different conventions living side by side for no real benefit |

**Installation:** No new packages required — `pip install` is a no-op for this phase.

## Package Legitimacy Audit

**Not applicable — this phase installs zero new external packages.** All required statistical
machinery (`statsmodels`, `scipy`, `numpy`) is already present in `requirements.txt`/
`pyproject.toml` and already in active use by `src/intelligence/statistics/ic_math.py`. No
`slopcheck`/registry verification needed.

## Architecture Patterns

### System Architecture Diagram

```
                     tag_vocabulary                    market_data_ohlcv_tradeable
                (factor_series, measurement_type,        (daily bars, volume>0
                 lookback_days, loading_threshold,          filter, D-11)
                 half_life_days)                                  |
                        |                                          |
                        v                                          v
              +-------------------------------------------------------+
              |         TagCalibrator.execute() (BaseBatch)            |
              |                                                       |
              |  Pass 1 - measure full matrix (F8 Simons inversion):  |
              |    for each (symbol, tag) where measurement_type !=   |
              |    'definitional' and symbol != factor_series (F6.1): |
              |      fetch instrument + factor daily returns          |
              |      (factor_math.py: long-short construction for     |
              |       HYG-IEF/TIP-IEF/IEF-SHY/XLE-SPY; breadth_vol.py |
              |       reuse for vol_beta)                             |
              |      compute standardized loading + raw HAC p-value   |
              |      (factor_math.py, reusing ic_math._hac_sharpe_nd  |
              |       pattern + _p_values_from_ic)                    |
              |      collect (pair, p) into run-level p-vector        |
              |                                                       |
              |  Pass 2 - correct once (F1):                          |
              |    apply_bh_fdr(p_vector, alpha.tag_calibrator.       |
              |    fdr_alpha) -> bh_adjusted_p, passes_fdr             |
              |                                                       |
              |  Pass 3 - decide per pair (F2, with hysteresis):       |
              |    keep = passes_fdr AND |loading| >= loading_threshold|
              |    UPSERT instrument_tags (loading, weight=|loading|, |
              |    p_value, bh_adjusted_p, passes_fdr, sample_n,      |
              |    estimated_at, consecutive_fails, valid_to)          |
              |    or INSERT instrument_annotations (ai_insight,       |
              |    expiry/discovery notices)                          |
              +-------------------------------------------------------+
                        |                            |
                        v                            v
              instrument_tags (empirical rows)  instrument_annotations
              (source='empirical', loading,      (ai_insight: expired /
               weight=|loading|, valid_to)        gap-discovered / pending-OOS)
                        |
                        v
         Downstream consumers (dashboard, AI agents, regime
         classifier) query instrument_tags WHERE passes_fdr AND
         valid_to IS NULL -- unchanged by this phase, no code
         changes required on the consumer side
```

### Recommended Project Structure

```
src/intelligence/statistics/
├── ic_math.py            # existing — DO NOT MODIFY except to export if needed
└── factor_math.py         # NEW — OLS loading + HAC SE, long-short constructors,
                            #        cross-correlation, mutual information;
                            #        pure functions, no DB, no config imports
                            #        (duck-typed config protocol, matches
                            #        SharpeWindowConfig precedent)

services/
└── tag_calibrator.py       # NEW — TagCalibrator(BaseBatch); job_name="tag-calibrator"
                            #        (F9 rename from "tag_auditor" — "auditor" is
                            #        reserved for health-check daemons in this codebase)

production/migrations/
├── 237_tag_vocabulary_taxonomy_cleanup.sql   # Wave 0: credit merge, housing_cycle
│                                              # delete, spread_leg backfill + reciprocal
│                                              # rows, glossary-adjacent banned-alias note
└── 238_tag_calibrator_measurement_contract.sql  # Wave 1 (or end of Wave 0): revised
                                              # schema columns + valid_from/valid_to +
                                              # APR key seeding

tests/unit/
├── test_factor_math.py                       # NEW — OLS loading, HAC SE, long-short
│                                              #        constructor correctness
├── test_spread_leg_pair_validity.py           # NEW — D-09's boundary-style test
│                                              #        (house pattern, see below)
└── test_tag_calibrator.py                     # NEW — full-matrix loop decision logic
                                              #        (keep/expire/discover), FDR
                                              #        correction wiring, F6.1 skip
```

### Pattern 1: Extend `BaseBatch`, mirror `EnsembleICEngine`'s shape exactly

**What:** `TagCalibrator(BaseBatch)` with `job_name`/`compute_version` class attrs, `__init__`
taking `db_dsn`, `async def execute(self, pool)` doing the real work, `if __name__ == "__main__":`
block calling `asyncio.run(TagCalibrator(db_dsn=...).run())`.

**When to use:** Always, for any new Phase 138+ batch compute service in this codebase — this is
the house pattern, not a suggestion.

**Example (from `services/ensemble_ic_engine.py`, the closest live sibling — a nightly/weekly
statistical-measurement batch service that reads market data and writes gated statistical
results):**

```python
# Source: services/ensemble_ic_engine.py:877-891 (live code, read in full 2026-07-17)
class EnsembleICEngine(BaseBatch):
    """Batch compute service: ensemble_alpha + forward_returns + market_regimes -> alpha_ensemble_ic."""

    job_name = "ensemble-ic-engine"
    compute_version = "1.0.0"

    def __init__(self, db_dsn: str, weight_version_override: str | None = None) -> None:
        super().__init__(db_dsn)
        self._weight_version_override = weight_version_override

    async def execute(self, pool: asyncpg.Pool) -> None:
        manifest = CorpusManifest("ensemble_ic_engine", CorpusManifest.DEFAULT_MANIFEST_DIR)
        try:
            await self._execute_inner(pool, manifest)
        except Exception as error:  # CLAUDE.md: exception variable name is `error`
            manifest.add_error(str(error))
            try:
                manifest.write()
            except Exception:
                pass
            raise

# Entrypoint (services/ensemble_ic_engine.py:1115-1137):
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="EnsembleICEngine oneshot")
    args = parser.parse_args()
    try:
        init_otel_providers("indicagent-ensemble-ic-engine")
    except OTelInitError as error:
        _logger.warning("ensemble_ic_engine.otel_init_failed", error=str(error))
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    asyncio.run(EnsembleICEngine(db_dsn=db_dsn, ...).run())
```

`TagCalibrator` should follow this exact shape: `job_name = "tag-calibrator"`,
`compute_version = "1.0.0"`, `execute()` loads the APR dict via `ConfigService`/direct
`config_state` query (see `EnsembleICEngine._execute_inner`'s `_load_apr_dict` pattern), runs the
3-pass loop, and its `if __name__ == "__main__":` block follows the identical
`init_otel_providers` + `Settings()` + `asyncio.run(...)` template. `CorpusManifest` is likely
unnecessary for this service (no multi-stage corpus rebuild) — plain `try/except` logging is
sufficient; the planner should confirm this simplification is safe (no downstream consumer expects
a manifest file from this service) rather than copying that piece by rote.

### Pattern 2: Long-short factor series construction (shared constructor)

**What:** A single function in `factor_math.py` builds a long-short daily return series from two
symbols (`long_symbol`, `short_symbol`) — used by `credit_beta` (HYG-IEF), `inflation` (TIP-IEF),
`yield_curve` (IEF-SHY), and `oil_beta` (XLE-SPY). Per the design doc's own Prior Art note: "The
long-short constructor is required anyway for `yield_curve` and `inflation` (T4), so this costs one
shared helper in `factor_math.py`, not new machinery."

**When to use:** Any tag whose factor series needs purification from a confound (equity beta for
credit/oil, duration for inflation, level for curve).

**Example (pattern, not live code — this function does not exist yet, construct per this shape):**

```python
def long_short_daily_returns(
    long_close: np.ndarray, short_close: np.ndarray
) -> np.ndarray:
    """Long-short daily log-return spread: log(long[t]/long[t-1]) - log(short[t]/short[t-1]).

    Shared constructor for credit_beta (HYG-IEF), inflation (TIP-IEF), yield_curve (IEF-SHY),
    and oil_beta (XLE-SPY) -- one function, four call sites, per the design doc's Prior Art note.
    """
    long_ret = np.diff(np.log(long_close))
    short_ret = np.diff(np.log(short_close))
    return long_ret - short_ret
```

### Pattern 3: Reuse `breadth_vol.py`'s pure functions for `vol_beta`'s factor input

**What:** `vol_beta`'s factor series is not a symbol at all — it's the SPY-realized-vol z-score
already computed by `_compute_vix_pct_rank` in `src/intelligence/regime_signals/breadth_vol.py`
(lines 91-135, read in full 2026-07-17). This function is DB-free (pure `pandas`/`numpy`/`bisect`),
taking a `pd.Series` of SPY close prices and returning a causal expanding-rank z-score series — it
can be imported and called directly from `factor_math.py` or `TagCalibrator` without any
regime-signals-module coupling beyond the import itself.

**Confirmed exact interface** `[VERIFIED: read breadth_vol.py in full]`:

```python
# src/intelligence/regime_signals/breadth_vol.py:91-93
def _compute_vix_pct_rank(
    spy_close: pd.Series, realized_vol_window: int, vix_z_window: int
) -> pd.Series:
    """SPY realized-vol z-score causal expanding percentile rank."""
```

Note this is a **private** function (underscore prefix) — same situation `ic_math.py` itself
solved by extraction (todo 048). The planner should decide whether to (a) import the private
function directly (acceptable within-repo, not a public API boundary issue since both are Ring 1),
or (b) have `breadth_vol.py` export a public wrapper. Given this project's precedent of importing
underscore-prefixed functions across module boundaries when they're the canonical source (e.g.
`ic_math.py`'s own `_fisher_z_ci`, `_p_values_from_ic` being imported by 3 other Ring 2 consumers),
option (a) is consistent with house style — no new public API surface is strictly required, though
a one-line public re-export (`compute_vix_pct_rank = _compute_vix_pct_rank`) would be cleaner for a
health check that this is being called correctly.

**Also confirmed:** `breadth_vol.py`'s causal-rank code explicitly documents the exact look-ahead
bias trap this codebase already fixed once (Phase 141 P0-T2) — the docstring for `compute()`
(line 15-20) states: "the vix_pct rank MUST use a causal bisect-based expanding rank, never a
whole-series percentile rank (pandas' `Series.rank` with `pct=True`)". `factor_math.py` must not
re-derive a whole-series version of this by accident when adapting it for the 252-day OLS lookback
window — reuse the causal version verbatim, do not "simplify" it.

### Pattern 4: APR key seeding migration pattern

**What:** New APR keys are seeded via a 3-table INSERT pattern: `config_schema` (key/type/default/
min/max/description), `config_state` (key/value/version), `config_history` (key/version/value/
changed_by/reason), all `ON CONFLICT DO NOTHING`, wrapped in `BEGIN`/`COMMIT`.

**Example (from `production/migrations/235_ibkr_apr_migration.sql`, the most recent APR-seeding
migration, read in full 2026-07-17):**

```sql
BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.ibkr.retry_count',
    'int',
    '3',
    1, 10,
    '[conventional] Number of retry attempts ... Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.ibkr.retry_count', '3', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (NOW(), 'infra.ibkr.retry_count', 1, '3', 'migration_235', 'Initial value: ... [conventional]')
ON CONFLICT DO NOTHING;

COMMIT;
```

The design doc's F1/F2/F4 review already specifies the exact 7 APR keys needed for this phase
(table reproduced in "APR Key Requirements" below) — apply this identical 3-table pattern for each.

### Anti-Patterns to Avoid

- **Reimplementing OLS/HAC/BH-FDR inside `factor_math.py` or `tag_calibrator.py`:** every one of
  these primitives already exists in `ic_math.py`. F4's finding is explicit: this repo already paid
  the extraction cost once (todo 048) specifically because three consumers were duplicating this
  math independently — a fourth reimplementation repeats the mistake this extraction fixed.
- **Regressing a symbol against itself (self-regression tautology):** `TLT` vs `rate_beta`'s factor
  series `TLT` produces `loading=1.0, p≈0` forever — a mathematically meaningless "confirmation."
  F6.1's guard (`symbol == factor_series` skip) is mandatory, not optional polish.
  `housing_cycle` (XHB vs XHB) is the live example of exactly this bug pre-committed in seed data —
  D-07's deletion, not a code fix, is the correct remedy for that specific row.
- **Using raw (unpurified) HYG/TIP/IEF betas for credit/inflation/curve tags:** T2's finding is that
  a univariate HYG regression "confirms" credit sensitivity for essentially the whole equity book
  because HYG carries substantial embedded equity beta — the long-short purification (Pattern 2)
  is not a refinement, it is the difference between a real measurement and a false positive.
- **Reading `tag_vocabulary.category` inside the measurement loop:** T7 confirms the calibrator
  never needs `category` for measurement logic — the measurement contract lives entirely in
  `factor_series`/`measurement_type` columns. Category is a display/organizational label only.
- **Single-run expiry (no hysteresis):** F2's fix requires `consecutive_fails >=
  expiry_consecutive_fails` (default 3) before `valid_to = now()` — a single failing run must not
  expire a tag (sequential-test flicker under weekly re-runs with ~97% window overlap).
- **Per-symbol metric labels:** F6.4 — `tag_calibration_total{symbol, tag, outcome}` is ~1,600
  label combinations today, ~16,000 at 10x universe growth, failing the metrics-backend 10x gate.
  Use `{tag, outcome}` only; per-symbol detail belongs in the DB rows.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Fisher z-transform CIs for correlation-type measurements | A new CI formula | `ic_math._fisher_z_ci` | Already handles the arctanh clip, the `_clamp_ci_to_ic` boundary-noise guard, and NaN-for-n<4 edge case — a second implementation would need to re-derive all three |
| BH-FDR multiple-testing correction | A `for` loop calling `scipy.stats` p-value adjustment manually | `ic_math.apply_bh_fdr` | Thin wrapper already extracted specifically because 3 consumers were duplicating this "collect p-values → one multipletests call → scatter back" shape (todo 069) |
| HAC (Newey-West) standard error inflation for autocorrelated series | A fresh Bartlett-kernel implementation | The pattern in `ic_math._hac_sharpe_nd` (reuse the inflation-factor math, not necessarily the function signature verbatim since it's Sharpe-specific, not loading-specific — but do not derive the Bartlett-kernel formula from scratch) | Newey-West with Bartlett kernel is a standard, easy-to-get-subtly-wrong formula (lag truncation, kernel weight sign); this codebase already has a reviewed, tested implementation |
| t-approximation p-values from a correlation/loading | `scipy.stats.pearsonr`'s built-in p-value (different df conventions) | `ic_math._p_values_from_ic` | Already supports an explicit `df` override for OLS-adjusted degrees of freedom, matching this phase's need to account for the long-short construction's implicit parameter |
| SPY-realized-vol / VIX-proxy computation | A new "ingest VIX or compute realized vol" module | `breadth_vol.py`'s existing `_compute_vix_pct_rank` | Zero new ingestion, already causal-correct (fixed for look-ahead bias in Phase 141), already tested |
| Ill-conditioned regression guard | A custom condition-number check | `ic_math.check_condition_number` | Shared gate already used by `mean_variance_weights()` and `partial_spearman_ic()` for exactly this class of numerical-trust decision |

**Key insight:** This phase's entire statistical surface (CI, p-value, FDR, HAC, condition-number
guard) is already built and tested in `ic_math.py`. The only genuinely new math is (1) the
standardized-loading transform (`beta * sigma_factor / sigma_instrument`, which for univariate OLS
reduces to a Pearson correlation — already computable via `ic_math._vectorized_ic`'s underlying
math pattern, though that function is Spearman-rank-based and this phase needs Pearson-on-raw-
returns, a genuinely new but trivial function) and (2) the long-short factor-series constructor.
Everything else is import, not derive.

## Common Pitfalls

### Pitfall 1: Raw-table bar counts overstate what's actually usable through the tradeable boundary

**What goes wrong:** CONTEXT.md cites factor-series bar counts (e.g., "UUP has 7,075 live daily
bars", "IEF-SHY... 3,261 bars") that were pulled from the **raw** `market_data_ohlcv` table, not
the `market_data_ohlcv_tradeable` view D-11 mandates for actual reads. Live 2026-07-17 verification
shows the tradeable view's counts are materially lower for several symbols:

| Symbol | Raw table bars | Tradeable view bars | Gap |
|--------|---------------|---------------------|-----|
| IEF | 3,261 | 2,240 | -31% |
| SHY | 3,261 | 2,240 | -31% |
| TLT | 3,808 | 2,618 | -31% |
| TIP | 7,316 | 5,034 | -31% |
| UUP | (not re-checked raw) | 4,867 | — |
| FXI | (not re-checked raw) | 5,024 | — |
| XLE | (not re-checked raw) | 5,034 | — |
| SPY | (not re-checked raw) | 5,033 | — |
| GLD | (not re-checked raw) | 5,034 | — |
| HYG | (not re-checked raw) | 4,838 | — |
| SMH | (not re-checked raw) | 3,652 | — |
| KRE | (not re-checked raw) | 5,035 | — |
| FXY | (not re-checked raw) | 4,876 | — |

`[VERIFIED: live psql, market_data_ohlcv vs market_data_ohlcv_tradeable, 2026-07-17]` — the ~31%
gap is consistent with `market_data_ohlcv_tradeable`'s own migration comment (236): bond ETFs
appear to have a meaningfully higher rate of zero-volume "flat carry-forward" days than equity
ETFs, consistent with lower daily trading activity on some fixed-income products.

**Why it happens:** `market_data_ohlcv` is a continuous calendar grid (weekends/holidays filled
with synthetic zero-volume bars); `market_data_ohlcv_tradeable` filters to `volume > 0`. The gap
size (~31% for the bond-ETF family) is larger than a naive "just weekends" estimate would predict.

**How to avoid:** The planner must use this doc's tradeable-view counts (table above), not
CONTEXT.md's raw-table counts, when writing any task/verification-step language that cites specific
bar counts. **This does not change any go/no-go decision** — every proxy series still clears the
252-day lookback by 8-20x margin even on the tradeable-view count — but a plan or test that asserts
"UUP has 7,075 bars" would fail if `market_data_ohlcv_tradeable` (the correct read target) is what
gets queried at execution/verification time.

**Warning signs:** Any generated verification SQL that queries the raw table instead of the
tradeable view for a bar-count assertion.

### Pitfall 2: Self-regression tautologies beyond the obvious `symbol == factor_series` case

**What goes wrong:** F6.1's `symbol != factor_series` guard catches the exact-match case (TLT vs
TLT, XHB vs XHB), but T4 identifies a second, subtler class: same-index pseudo-tautologies where
two different symbols track the same underlying index so closely that "measuring" one against the
other as a factor produces a real but uninformative loading. Documented live examples: VWO vs EEM
(same MSCI EM index, different providers) and MCHI vs FXI (same China large-cap universe).

**Why it happens:** F6.1's guard is a literal string-equality check on the symbol name — it cannot
detect "these are economically the same index under different tickers."

**How to avoid:** This is explicitly NOT something this phase needs a code fix for (T4/T7 flag it
as an F6-inventory addition, not a blocking issue) — but the planner should ensure the design doc's
F6 inventory gets this addition (per the review's Doc Edits item 1e) and that any discovery-mode
gap-annotation output is read with this caveat in mind. Not a schema/code gate; a documentation and
downstream-interpretation caveat.

**Warning signs:** A `china_beta`/`em_flows` discovery run flagging near-1.0 loadings for
MCHI-vs-FXI or VWO-vs-EEM pairs as if they were a novel finding.

### Pitfall 3: Futures-based factor series need roll adjustment (not applicable to this phase's Phase 1 scope, but a live trap if CL/VIX futures are ever revisited)

**What goes wrong (F6.2):** CL front-month futures returns carry a roll-date discontinuity if used
unadjusted — any calibration window spanning a roll date gets a spurious jump. This does not affect
Phase 1's actual factor-series list (CL/VIX are both excluded per D-02's proxy substitutions — no
futures series is used anywhere in the Phase 1 primitive set), but the design doc's F6.2 finding
should stay documented for whenever/if a futures-based factor series is added.

**Why it happens:** Futures contract-metadata roll-adjustment logic (`contract_metadata`/
`roll_batch.py`) already exists in this codebase but is not automatically applied to arbitrary daily
return series constructed ad hoc inside a new module.

**How to avoid:** N/A for this phase's actual scope (confirmed: zero futures symbols in the Phase 1
factor-series list). Included here only so the planner does not need to re-derive this finding if a
future phase revisits VIX/oil futures ingestion.

### Pitfall 4: `tag_vocabulary`'s `category` CHECK constraint already reflects the 6-category split — do not attempt to re-migrate it

**What goes wrong:** A plan that assumes `tag_vocabulary.category`'s CHECK constraint still has the
original 4 categories (`exposure`, `regime`, `signal_role`, `macro_driver`) from migration 227
would attempt a redundant/conflicting ALTER.

**Why it happens:** The design doc (v1.4, last updated 2026-07-06) and even parts of CONTEXT.md's
framing discuss the category taxonomy as if it needs active correction — but the live schema
already has the 6-category CHECK (`exposure`, `sensitivity`, `factor_regime`, `cycle_position`,
`signal_role`, `macro_driver`), applied by migration 228 (`228_instrument_tag_vocabulary_v2.sql`,
"Migration 121" per its internal header) well before this phase's context-gathering session.

**How to avoid:** Wave 0's migration only needs (a) the credit_cycle→credit_risk merge, (b) the
housing_cycle deletion, (c) the spread_leg evidence backfill — it does NOT need to touch the
category CHECK constraint at all. `[VERIFIED: read migration 228 in full, confirms 6-category CHECK
already live]`

## Code Examples

### `ic_math.py`'s exact reusable function signatures (verified live, `src/intelligence/statistics/ic_math.py`)

```python
# Source: src/intelligence/statistics/ic_math.py:121-149
def _fisher_z_ci(ic_vector: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """95% CI for Spearman IC via Fisher z-transform. Returns (ci_lower, ci_upper)."""

# Source: src/intelligence/statistics/ic_math.py:353-366
def _p_values_from_ic(ic_vector: np.ndarray, n: int, df: int | None = None) -> np.ndarray:
    """Two-tailed p-values from IC via t-approximation. df defaults to n-2; pass
    explicit df for additional fitted parameters (e.g. long-short construction)."""

# Source: src/intelligence/statistics/ic_math.py:412-431
def apply_bh_fdr(p_values: list[float], alpha: float) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg FDR correction over one family of p-values.
    Returns (reject, p_corrected) as parallel arrays in input order."""

# Source: src/intelligence/statistics/ic_math.py:724-763
def _hac_sharpe_nd(
    window_ics: np.ndarray, max_lag: int,
    mean_ic: np.ndarray | None = None, var0: np.ndarray | None = None,
) -> np.ndarray:
    """Newey-West Bartlett-kernel HAC-corrected IC Sharpe. Reuse the inflation-factor
    loop (lines 754-760: gamma_k/rho_k/Bartlett-weight accumulation) as the pattern
    for factor_math.py's HAC standard-error correction on the OLS loading -- not this
    exact function (it's Sharpe-ratio-specific), but the same kernel math."""

# Source: src/intelligence/statistics/ic_math.py:439-452
def check_condition_number(matrix: np.ndarray, condition_max: float) -> tuple[bool, float]:
    """Ill-conditioning gate for any Sigma^-1/lstsq solve on estimated data."""
```

### `breadth_vol.py`'s reusable vol-proxy function (verified live)

```python
# Source: src/intelligence/regime_signals/breadth_vol.py:91-135
def _compute_vix_pct_rank(
    spy_close: pd.Series, realized_vol_window: int, vix_z_window: int
) -> pd.Series:
    """SPY realized-vol z-score causal expanding percentile rank.
    Causal bisect-based expanding rank (no look-ahead bias) -- ported verbatim from
    equity_regime_model.py's Phase 141 P0-T2 fix. DB-free pure function."""
```

### `BaseBatch` contract (verified live, `src/core/agent/base_batch.py`)

```python
# Source: src/core/agent/base_batch.py:31-46
class BaseBatch(abc.ABC):
    """Subclasses define: job_name (str), compute_version (str),
    execute(pool) -> None (async). run() handles pool lifecycle + D-06
    job_completed_total emission + teardown, always (even on failure)."""

    job_name: str
    compute_version: str

    @abc.abstractmethod
    async def execute(self, pool: asyncpg.Pool) -> None: ...
```

### APR migration pattern (verified live, `production/migrations/235_ibkr_apr_migration.sql`)

See "Architecture Patterns" → Pattern 4 above for the full reproduced example.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Human-asserted `instrument_tags` rows with no measurement procedure | Empirically measured OLS loadings with HAC p-values, BH-FDR gating, exponential decay | This phase (146) | Tags become falsifiable hypotheses, not permanent beliefs |
| Per-hypothesis `p < 0.05` gating (design doc v1.3) | Run-level BH-FDR correction across the full measured matrix | 2026-07-06 Fable review, F1 | Prevents ~80 expected false positives per run under the global null at the 80-symbol/~20-tag scale |
| `weight = |beta|` (unstandardized, violates live `[0,1]` CHECK) | `loading = beta * sigma_factor / sigma_instrument` (standardized, `[-1,1]`), `weight = |loading|` | 2026-07-06 Fable review, F3 | Fixes a CHECK-constraint-violating crash on the first strongly-loaded instrument; makes betas comparable across leveraged/unleveraged instruments |
| Raw HYG beta for `credit_risk`/`credit_beta` | HYG-IEF long-short (purified spread) | 2026-07-16 taxonomy review, T2 | Removes HYG's embedded equity beta, which would otherwise "confirm" credit sensitivity for the whole equity book |
| VIX ingestion (planned, never built) for `vol_beta` | Reuse of existing `breadth_vol.py` SPY-realized-vol z-score | 2026-07-16 discussion (D-02) | Zero new data-pipeline work for a concept the platform already computes |
| "Defer `oil_beta`, no non-circular substitute" | XLE-SPY long-short (same purification technique as credit/inflation) | 2026-07-16 discussion (D-02) | Un-defers a Phase 1 primitive that was incorrectly judged unmeasurable |

**Deprecated/outdated:**
- The design doc's original (v1.3) "nightly" cadence language — corrected to weekly (Sunday night)
  per the doc's own § Architecture fit section; 252-day betas re-estimated nightly would be ~97%
  window overlap run-over-run, wasted compute for no new information.
- The ROADMAP's original TAG-01 factor-series list (VIX, USO, DXY, KWEB for china) — all four
  superseded by CONTEXT.md's D-02 resolutions; see Doc Edits item 2 in the taxonomy review's Punch
  List for the exact rewrite needed in `.planning/ROADMAP.md`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `TagCalibrator` does not need a `CorpusManifest`-style multi-file audit trail the way `EnsembleICEngine` does — plain exception logging is sufficient since this is a single-pass measurement loop, not a multi-stage corpus rebuild | Architecture Patterns, Pattern 1 | Low — if a downstream consumer (e.g. an ops dashboard) expects a manifest file for this job, its absence would only be a missing observability nicety, not a correctness bug. Confirm at planning time whether any script/dashboard already expects a `tag_calibrator` manifest. |
| A2 | `factor_math.py`'s standardized-loading computation can use a direct Pearson-correlation-equivalent formula rather than a full `statsmodels.OLS` solve, since univariate OLS beta standardized by `sigma_factor/sigma_instrument` is mathematically identical to the Pearson correlation coefficient | Standard Stack, Alternatives Considered | Low-Medium — this is a standard statistics identity (true for simple linear regression with one regressor), but the planner/implementer should double check the HAC-adjusted-SE math is applied consistently whichever formulation is chosen, since the design doc phrases this as "OLS loading with HAC SEs" and a correlation-based implementation must still produce the same standard error under autocorrelation |
| A3 | `TagCalibrator`'s `job_name` should be `"tag-calibrator"` (not `"tag-auditor"`) per F9's naming rationale, and the systemd unit should be `indicagent-tag-calibrator.timer`/`.service` | Recommended Project Structure | Low — this is Claude's Discretion per CONTEXT.md, not a locked decision; if the project owner prefers to keep "TagAuditor" as the concept name despite F9's argument, this is a one-line rename with no structural impact |
| A4 | The 13 non-mechanically-recoverable `spread_leg` pairs' human-pass resolution (deferred per CONTEXT.md) will happen synchronously during Wave 0 execution rather than blocking Wave 0's merge | Live Schema State / D-09 | Medium — if the project owner is unavailable to make this call during Wave 0 execution, the plan needs a fallback (e.g., delete all 13 unrecoverable rows now, re-add with real evidence later) rather than blocking indefinitely |

## Open Questions

1. **Should `TagCalibrator`'s systemd cadence be weekly (Sunday night) as the design doc specifies, or does the project's existing systemd-timer landscape (CLAUDE.md notes all timers are currently disabled as of 2026-07-02) mean this phase should not wire up a live timer at all, only the oneshot script?**
   - What we know: CLAUDE.md states "all systemd timers are confirmed disabled as of 2026-07-02" —
     this is a project-wide fact, not specific to this phase.
   - What's unclear: Whether Wave 1/2 should include enabling a new timer (going against the current
     disabled-timer status quo) or whether the calibrator ships as a manually-invoked oneshot for now,
     matching the rest of the currently-disabled timer landscape.
   - Recommendation: Build the oneshot script regardless (needed either way); defer the
     "enable a live systemd timer" decision to the planner/project-owner, since it's an operational
     choice independent of the calibration engine's correctness.

2. **Does `factor_math.py` need its own duck-typed config Protocol (mirroring `ic_math.py`'s
   `SharpeWindowConfig`), and if so what fields does it need beyond `hac_max_lag`?**
   - What we know: The design doc's APR key table specifies `fdr_alpha`, `expiry_consecutive_fails`,
     `discovery_oos_days`, `min_sample_n`, `hac_max_lag`, `half_life_min_days`, `half_life_max_days` —
     7 keys total, none of which map 1:1 onto `SharpeWindowConfig`'s 3 fields.
   - What's unclear: Whether these 7 keys live on one config dataclass (`TagCalibratorConfig`,
     mirroring `EnsembleICConfig`) loaded once per run, or are read ad hoc via `ConfigService.get_sync`
     scattered through the loop.
   - Recommendation: Follow `EnsembleICConfig`'s precedent (a single frozen dataclass with a
     `.from_apr(apr_cfg)` classmethod) — this is the established pattern for exactly this shape of
     "load N tunables once per batch run" need; the planner should design this class explicitly as
     part of Wave 1's task breakdown.

## Environment Availability

Skipped — this phase has no new external tool/service dependencies. `statsmodels`/`scipy`/`numpy`
are already installed and in active use (confirmed via `ic_math.py` imports); PostgreSQL/
TimescaleDB is the existing project database with no version change required.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (`.venv/bin/pytest`) |
| Config file | none dedicated — project-wide `tests/unit/` convention |
| Quick run command | `.venv/bin/pytest tests/unit/test_factor_math.py tests/unit/test_spread_leg_pair_validity.py tests/unit/test_tag_calibrator.py -v` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements → Test Map

No formal `REQ-XX` IDs exist for this phase (no REQUIREMENTS.md in this repo) — mapping to TAG-01/
02/03 (ROADMAP-defined, revised by CONTEXT.md's 12 decisions) as the actual acceptance surface.

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TAG-01 | OLS loading computation matches expected value on synthetic fixture data (known beta/correlation) | unit | `.venv/bin/pytest tests/unit/test_factor_math.py::test_ols_loading_synthetic -x` | ❌ Wave 1 |
| TAG-01 | HAC-adjusted standard error inflates correctly under autocorrelated synthetic data | unit | `.venv/bin/pytest tests/unit/test_factor_math.py::test_hac_se_inflation -x` | ❌ Wave 1 |
| TAG-01 | Long-short constructor (HYG-IEF/TIP-IEF/IEF-SHY/XLE-SPY) produces correct spread return series | unit | `.venv/bin/pytest tests/unit/test_factor_math.py::test_long_short_constructor -x` | ❌ Wave 1 |
| TAG-01 | F6.1 self-regression skip (`symbol == factor_series`) | unit | `.venv/bin/pytest tests/unit/test_tag_calibrator.py::test_skips_self_regression -x` | ❌ Wave 1 |
| TAG-01 | BH-FDR correction applied at run level, not per-hypothesis | unit | `.venv/bin/pytest tests/unit/test_tag_calibrator.py::test_run_level_fdr -x` | ❌ Wave 1 |
| TAG-01 | Expiry hysteresis: single failing run does not expire (`consecutive_fails` gate) | unit | `.venv/bin/pytest tests/unit/test_tag_calibrator.py::test_expiry_hysteresis -x` | ❌ Wave 1 |
| TAG-01 | `vol_beta` reuses `breadth_vol._compute_vix_pct_rank` (import/call correctness, not a re-derivation) | unit | `.venv/bin/pytest tests/unit/test_tag_calibrator.py::test_vol_beta_uses_breadth_vol_proxy -x` | ❌ Wave 1 |
| TAG-01 (data boundary) | Daily-return reads use `market_data_ohlcv_tradeable`, not raw table | CI guard | `.venv/bin/pytest tests/unit/test_market_data_ohlcv_boundary.py -v` (add `services/tag_calibrator.py` and `src/intelligence/statistics/factor_math.py` to the allow-list ONLY if they have a genuine documented reason to read the raw table — expected: they should NOT need an entry, since D-11 mandates the tradeable view) | ✅ exists — must stay green with zero new allow-list entries for this phase's new files |
| TAG-02 | (Phase 2, out of scope for Wave 1-2) | N/A | N/A | N/A — Wave 3 is design-only |
| TAG-03 | `spread_leg` evidence contract: every row's `evidence->>'pair'` resolves to a valid `instruments.symbol`, pair references are symmetric | unit | `.venv/bin/pytest tests/unit/test_spread_leg_pair_validity.py -v` | ❌ Wave 0 |
| TAG-03 | Definitional tags (`fed_policy`, `geopolitical`, `benchmark`, etc.) are never written by the calibration loop | unit | `.venv/bin/pytest tests/unit/test_tag_calibrator.py::test_skips_definitional_tags -x` | ❌ Wave 1 |
| Schema (D-10) | `instrument_tags` migration adds `valid_from`/`valid_to` without breaking existing rows | manual SQL verification | `psql ... -c "\d instrument_tags"` post-migration | N/A (SQL, not pytest) |
| Data cleanup (D-03/D-07) | credit_cycle merged into credit_risk (max-weight collision), housing_cycle deleted | manual SQL verification | `psql ... -c "SELECT * FROM instrument_tags WHERE tag IN ('credit_cycle','housing_cycle')"` (expect 0 rows) | N/A (SQL, not pytest) |

### Sampling Rate

- **Per task commit:** run that task's own new test file (`tests/unit/test_factor_math.py`,
  `tests/unit/test_spread_leg_pair_validity.py`, `tests/unit/test_tag_calibrator.py`).
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -q` (full suite — must stay green).
- **Phase gate:** full suite green + `tests/unit/test_market_data_ohlcv_boundary.py` shows zero new
  allow-list entries for this phase's files + manual SQL spot-checks for the Wave 0 data cleanup
  (credit merge, housing_cycle deletion, spread_leg evidence backfill) + a live dry-run of
  `TagCalibrator` against a small symbol subset before enabling any systemd timer (see Open
  Question 1).

### Wave 0 Gaps

- [ ] `tests/unit/test_spread_leg_pair_validity.py` — does not exist yet; D-09's boundary-style
      test (asserts every `spread_leg` row's `evidence->>'pair'` resolves to a valid
      `instruments.symbol` and that pair references are symmetric). Model directly on
      `tests/unit/test_market_data_ohlcv_boundary.py`'s allow-list-and-assert pattern, adapted for
      a data-contract check rather than a call-site grep.
- [ ] `tests/unit/test_factor_math.py` — new module, no existing test file.
- [ ] `tests/unit/test_tag_calibrator.py` — new service, no existing test file.
- [ ] No test framework install needed — pytest already configured and green project-wide
      (`statsmodels`/`scipy` already present for the statistical assertions these new tests need).

## Security Domain

Not applicable — `security_enforcement` config key not checked in `.planning/config.json`, but this
phase has zero authentication/authorization/network-input surface: an internal batch measurement
service reading/writing its own DB tables over a locally-trusted connection, no user input, no
external API, no new API routes. Omitting per the section's own scope (ASVS categories target
request-handling/auth surfaces this phase does not have). Consistent with the precedent set in
Phase 144's RESEARCH.md for the structurally similar `cross_sectional_regime_model.py` batch
service.

## Sources

### Primary (HIGH confidence — direct file reads/live DB queries, 2026-07-17)

- `.planning/phases/146-empirical-instrument-tag-calibrator-planned/146-CONTEXT.md` (read in full)
  — 12 locked decisions (D-01 through D-12), canonical refs, deferred ideas.
- `docs/research/stratification-instrument-tag-calibrator.md` (read in full, 745 lines) — full
  design doc: problem statement, Simons critique, primitives tables, schema, F1-F9 review
  (2026-07-06), revised schema/loop, T1-T7 resolution appendix (2026-07-16).
- `docs/research/fable-2026-07-16-tag-calibrator-taxonomy-review.md` (read in full, 147 lines) —
  T1-T7 findings, live-state verification, punch list.
- `src/intelligence/statistics/ic_math.py` (read in full, 859 lines) — exact signatures of
  `_fisher_z_ci`, `_p_values_from_ic`, `apply_bh_fdr`, `_hac_sharpe_nd`, `check_condition_number`.
- `src/intelligence/regime_signals/breadth_vol.py` (read in full, 156 lines) — exact interface of
  `_compute_vix_pct_rank`, causal-rank correctness invariant.
- `src/core/agent/base_batch.py` (read, ~150 lines) — `BaseBatch` contract.
- `services/ensemble_ic_engine.py` (targeted reads: class def, `execute()`, entrypoint) — closest
  live sibling batch-measurement service pattern.
- `tests/unit/test_market_data_ohlcv_boundary.py` (read in full, 162 lines) — house boundary-test
  pattern precedent for D-09's `spread_leg` test.
- `production/migrations/227_instrument_tag_vocabulary.sql`, `228_instrument_tag_vocabulary_v2.sql`,
  `188_etf_expansion.sql`, `190_etf_expansion_cwb.sql` (all read in full/targeted) — seed provenance
  for `spread_leg` rows, category-taxonomy migration history, live schema origin.
- `production/migrations/235_ibkr_apr_migration.sql`, `222_reactivate_bootstrap_ci_apr_keys.sql`
  (read in full/targeted) — APR-seeding migration pattern precedent.
- `docs/foundation/glossary.md` lines 330-408 (read) — six category definitions, confirmed live
  and matching the T7-cited line range.
- Live `psql` queries against `indicagent` DB (2026-07-17): `\d instrument_tags`, `\d
  tag_vocabulary`, `\d instrument_annotations`; `tag_vocabulary` category counts; `instrument_tags`
  totals and `spread_leg` NULL-evidence count; HYG/LQD credit-tag weights; `housing_cycle`/
  `volatility` holder counts; factor-series daily-bar counts via both raw `market_data_ohlcv` and
  `market_data_ohlcv_tradeable` for 13 symbols; `instruments.is_active`/`asset_class` for
  VIX/USO/DXY/CL.
- `requirements.txt`, `pyproject.toml` (grepped) — confirms `statsmodels`/`scipy` already present,
  no new packages needed.
- `.planning/config.json` (read) — confirms `nyquist_validation: true`, no `security_enforcement`
  key present.
- `.planning/STATE.md` (read in full) — project-wide phase status; confirms Phase 146 has no
  upstream code dependency on the in-progress 143.1 corpus re-run.

### Secondary (MEDIUM confidence)

- None — every claim in this document traces to a direct file read or live DB/psql query performed
  in this research session.

### Tertiary (LOW confidence)

- None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages, all reuse targets verified live in `ic_math.py`.
- Architecture: HIGH — `BaseBatch` contract and `EnsembleICEngine` sibling pattern both read in
  full/targeted from live code; schema state independently re-verified against CONTEXT.md's claims.
- Pitfalls: HIGH for the raw-vs-tradeable bar-count discrepancy (directly measured this session);
  MEDIUM for the F6/F7-derived pitfalls (inherited from the design doc's own review, not
  independently re-derived here, but the underlying schema/data facts they depend on were
  re-verified).

**Research date:** 2026-07-17
**Valid until:** 30 days (stable domain — internal batch service design, no external API drift risk;
re-verify live bar counts if execution is delayed more than a few weeks, since daily bar counts grow
monotonically and will only improve the lookback margin, not threaten it).
