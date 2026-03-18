# Phase 35: Calibration + TOD Multiplier + CIS Kalman Filter — Research

**Researched:** 2026-03-17
**Domain:** Signal confidence calibration (isotonic regression), time-of-day Bayesian adjustment, 1D Kalman filter for CIS scores
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Calibration Job — Architecture**
- New module `src/intelligence/ml/confidence_calibrator.py` with `run_calibration_update(db_manager)` async function
- Called from `weight_updater.py` after `run_weight_update()` — same 30-min timer tick, same DB connection, no new systemd unit
- Independent failure domain: calibration failure logs and returns; weight update still completes
- Runs every 30 min (same cadence as weight_updater) — continuous adaptation, not batch-on-demand

**Calibration — Data Storage**
- `calibrated_confidence = NULL` when N < 100 for a (plugin_name, timeframe) pair — explicit, unambiguous
- Never store raw confidence in `calibrated_confidence` — training pipeline isolates calibrated rows via `WHERE calibrated_confidence IS NOT NULL`
- `raw_cis_score`, `filtered_cis_score`, `calibrated_confidence` all land as **signal_ledger DB columns** (not log-only)
- DB migration adds 3 columns to `signal_ledger`

**Calibration — Aggregator Integration (CAL-03)**
- `calibrated_confidence` is the **sort key** in `_build_all_ranked()` when non-NULL; raw confidence fallback
- Do NOT mutate the existing `confidence` field — add `calibrated_confidence` as a new field
- Applied as the **final step** after all quality multipliers (perf_multiplier, Hurst, KS drift, GARCH)
- Calibration scope: per winning signal's `(plugin_name, timeframe)` — post-CIS/post-Kalman winner

**TOD Multiplier — Granularity + Seeding**
- Seeded by **`regime_type`** (3 groups: `trend`, `mean_reversion`, `any`) × timeframe × hour_ET — NOT per individual plugin
- **Bayesian smoothing**: `effective_multiplier = (α × prior + N × empirical_win_rate_ratio) / (α + N)` where α=20
- Session priors:
  - NY open (09:30–10:00 ET): `trend` +10%, `mean_reversion` neutral, `any` neutral
  - Lunch chop (11:30–13:00 ET): all regime_types −10%
  - London close (14:00–15:00 ET): `mean_reversion` +8%, `trend` neutral, `any` neutral
  - MOC (15:30–16:00 ET): `any` +10%, others neutral
- Multiplier clamped to [0.7, 1.3]
- Cached in-memory dict refreshed every 4h

**TOD Multiplier — Application Point**
- Applied **pre-CIS aggregation**: each I7 plugin's raw confidence × TOD_multiplier before feeding into CIS scoring
- NOT post-CIS — must affect signal *selection*, not just cosmetic ranking

**CIS Kalman Filter — Architecture**
- Per-(symbol, timeframe) 1D local-level Kalman filter wrapping the CIS score in `signal_generator_service`
- `CISScorer` remains stateless — Kalman state lives in the service layer
- Reuses `KalmanTrendPlugin` local-level recursion pattern (predict → update), NOT the plugin itself

**CIS Kalman Filter — Parameters**
- **Per-TF fixed Q/R from config** (NOT GARCH-adaptive — dimensionally incoherent)
- Parameters stored in `config/kalman_parameters.json` keyed by timeframe
- Starting values: Q=0.01, R=0.05 — tune per TF before shipping
- No hardcoding — config-driven

**CIS Kalman Filter — Fire Condition Transition**
- **Shadow mode using existing `is_shadow=TRUE` infrastructure**
- New fire condition: `filtered_cis > 0.35 AND raw_cis > 0.28 AND buckets_agreeing >= 3`
- **Shadow window: N≥30 suppressed signals per regime_type** (not calendar time)
- After threshold met: run outcome analysis; data decides hard switch
- No FIRE_CONDITION_V2 env var

**Dashboard**
- Signal card headline: `calibrated_confidence` as the single confidence number
- Drill panel: `raw_cis_score`, `filtered_cis_score`, `calibrated_confidence` side by side
- No other dashboard changes in this phase

### Claude's Discretion
- Exact Kalman Q/R values per TF (starting from Q=0.01, R=0.05 baseline; tune per TF)
- `confidence_calibration` table schema details (breakpoints/values array columns per CAL-01)
- Suppression reason field format in signal_ledger
- How the service refreshes calibration curves every 30 min (mirror existing `_cis_scorer` weight refresh pattern)

### Deferred Ideas (OUT OF SCOPE)
- GARCH-adaptive Kalman Q/R for CIS: dimensionally incoherent
- Per-plugin TOD multiplier (2,688 cells): defer until signal volume is 10×
- Learned Kalman parameters via EM: defer to future ML phase
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CAL-01 | `confidence_calibration` DB table: `(plugin_name, timeframe)` key, `breakpoints DOUBLE PRECISION[]`, `values DOUBLE PRECISION[]`, `ece DOUBLE PRECISION`, `sample_size INT`, `updated_at TIMESTAMPTZ` | Schema defined below; isotonic regression outputs breakpoints+values arrays |
| CAL-02 | Calibration batch job `src/intelligence/ml/confidence_calibrator.py`; N≥100 gate; runs alongside weight_updater; `calibrated_confidence` stored in `signal_ledger` | `run_weight_update()` call pattern confirmed in `weight_updater.py`; `signal_ledger` migration appends columns $55–$57 |
| CAL-03 | Aggregator `_build_all_ranked()` applies `calibrated_confidence` as final sort key when non-NULL; raw confidence fallback | `_build_all_ranked()` in `aggregator.py` fully read; integration point is after existing quality multipliers (step 1b/1c) |
| TOD-01 | TOD win rate computed per `(regime_type, timeframe, hour_et)`; seeded with session priors until N≥20 | Bayesian smoothing formula specified; prior table defined |
| TOD-02 | TOD multiplier ∈ [0.7, 1.3] applied pre-CIS to I7 plugin confidence; cached, refreshed 4h | Integration point in `_process_bar()` between `_run_setup_plugins()` and `aggregate()` call confirmed |
| KAL-01 | Per-(symbol, timeframe) 1D Kalman filter on CIS score in `signal_generator_service`; reuses `KalmanTrendPlugin` recursion; state persists | Exact predict/update recursion documented from `kalman_trend.py`; state structure `{symbol: {tf: {x_est, P_est}}}` confirmed |
| KAL-02 | Both `raw_cis_score` and `filtered_cis_score` logged; new fire condition enforced; shadow mode until N≥30 per regime_type | Shadow infrastructure (`is_shadow` column, `insert_signals_with_features`) confirmed in place |
</phase_requirements>

---

## Summary

Phase 35 enhances the signal confidence pipeline with three coordinated changes, all within `signal_generator_service` and `weight_updater`. No new services, no new plugins.

The calibration job adds isotonic regression curves per `(plugin_name, timeframe)` using historical outcomes from `signal_ledger`. These curves map raw plugin confidence → calibrated probability, stored in a new `confidence_calibration` table and applied as the final sort key in `_build_all_ranked()`. The N≥100 gate and NULL fallback make this safe before signal volume grows.

The TOD multiplier applies Bayesian-smoothed win-rate adjustments (grouped by `regime_type × timeframe × hour_ET`) to each I7 plugin's raw confidence before CIS aggregation. The pre-CIS placement means suppressed-lunch-chop signals never accumulate enough bucket score to clear the CIS gate — which is the causal behavior wanted.

The CIS Kalman filter is a direct copy of the `KalmanTrendPlugin` local-level recursion, applied to the raw CIS score (not price). Per-TF Q/R parameters in `config/kalman_parameters.json` give the system a noise model tuned to CIS-space rather than price-space. The existing `is_shadow=TRUE` infrastructure handles the shadow window until N≥30 suppressed signals per regime_type.

**Primary recommendation:** Implement in three plans in order: (1) migration + calibrator module, (2) TOD multiplier + service integration, (3) Kalman filter + shadow fire condition.

---

## Standard Stack

### Core (all already installed in .venv)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `scikit-learn` | installed (see weight_updater.py) | `IsotonicRegression` for calibration curves | Already used for LogisticRegression in weight_updater |
| `numpy` | installed | Array operations for Kalman recursion, TOD math | Project-wide standard |
| `asyncpg` | installed | DB pool for async writes | All other service DB writes use this |
| `structlog` | installed | Structured logging for multiplier/filter fields | Service-wide standard |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `scipy.stats` | installed | ECE (expected calibration error) metric | Optional diagnostic in calibrator |
| `pytz` / `datetime.timezone` | stdlib | ET timezone conversion for TOD hour computation | Standard for hour_et extraction |

**No new installs required.** `IsotonicRegression` is in `scikit-learn` which is already a dependency.

**Version verification:** `scikit-learn` present via `from sklearn.linear_model import LogisticRegression` in `weight_updater.py`. `IsotonicRegression` is in `sklearn.isotonic`.

---

## Architecture Patterns

### Recommended Project Structure (new files only)

```
src/
├── intelligence/
│   ├── ml/
│   │   └── confidence_calibrator.py   # CAL-01, CAL-02: new module
│   └── weight_updater.py              # add run_calibration_update() call
config/
└── kalman_parameters.json             # DOES NOT EXIST YET — must create; add CIS Kalman entries
production/
└── migrations/
    └── 038_calibration_fields.sql     # signal_ledger 3 cols + confidence_calibration table
tests/unit/intelligence/
├── test_confidence_calibrator.py      # new
└── ml/
    └── __init__.py
tests/unit/service_tests/
└── test_signal_generator_calibration.py  # new: Kalman + TOD integration tests
```

Note: `config/kalman_parameters.json` does not yet exist (confirmed — the KalmanTrendPlugin loads it via `_CONFIG_PATH = Path("config/kalman_parameters.json")` with a fallback to defaults). Wave 0 must create this file.

### Pattern 1: Isotonic Regression Calibration

**What:** `IsotonicRegression` trains a monotone mapping from raw confidence (feature) to empirical win rate (label). Breakpoints and values arrays are the piecewise-constant interpolation that `predict()` uses internally. These are stored to DB and reconstructed at runtime with `np.interp()` — no sklearn object serialization needed.

**When to use:** After N≥100 resolved signals per `(plugin_name, timeframe)` — sufficient to fit a monotone curve without overfitting.

```python
# Source: sklearn.isotonic — verified in .venv
from sklearn.isotonic import IsotonicRegression

ir = IsotonicRegression(out_of_bounds="clip")
ir.fit(confidences, win_labels)   # win_labels: 1.0=win, 0.0=loss

# Extract piecewise breakpoints for DB storage (avoid sklearn object pickling)
breakpoints = ir.X_thresholds_.tolist()   # x values at step boundaries
values = ir.y_thresholds_.tolist()         # calibrated probability at each step
```

**ECE computation:**
```python
# Expected Calibration Error — measures reliability of calibration
# Bin into 10 equal-width bins; average |fraction_wins - mean_confidence| per bin
n_bins = 10
bin_edges = np.linspace(0, 1, n_bins + 1)
ece = 0.0
for lo, hi in zip(bin_edges[:-1], bin_edges[1:]):
    mask = (confidences >= lo) & (confidences < hi)
    if mask.sum() == 0:
        continue
    frac_win = win_labels[mask].mean()
    mean_conf = confidences[mask].mean()
    ece += mask.mean() * abs(frac_win - mean_conf)
```

**Runtime apply (no sklearn at inference):**
```python
# np.interp is pure numpy, fast, no sklearn dependency at query time
calibrated = float(np.interp(raw_confidence, breakpoints, values))
```

### Pattern 2: Bayesian TOD Smoothing

**What:** Smoothly interpolates between session prior and empirical win rate as N grows. α=20 means 20 virtual observations anchoring the prior.

**When to use:** All hours for all (regime_type, timeframe) cells — even at N=0 (prior-only mode).

```python
# Source: CONTEXT.md decision
PRIOR_RATIO = {
    ("trend",           "09"):  1.10,   # NY open
    ("mean_reversion",  "09"):  1.00,
    ("any",             "09"):  1.00,
    ("trend",           "11"):  0.90,   # lunch chop 11:30-13:00
    ("mean_reversion",  "11"):  0.90,
    ("any",             "11"):  0.90,
    ("mean_reversion",  "14"):  1.08,   # London close
    ("any",             "15"):  1.10,   # MOC
    # all others: 1.0 (neutral)
}

ALPHA = 20.0  # prior weight in virtual observations

def effective_multiplier(
    regime_type: str, hour_et: int, timeframe: str,
    empirical_n: float, empirical_win_rate_ratio: float,
    prior_ratio: float,
) -> float:
    numerator = ALPHA * prior_ratio + empirical_n * empirical_win_rate_ratio
    raw = numerator / (ALPHA + empirical_n)
    return max(0.7, min(1.3, raw))  # clamp to [0.7, 1.3]
```

**hour_et computation (ET conversion):**
```python
from datetime import datetime, timezone
import zoneinfo

ET = zoneinfo.ZoneInfo("America/New_York")

def hour_et_from_utc(ts: datetime) -> int:
    return ts.astimezone(ET).hour
```

### Pattern 3: CIS Kalman Filter (local-level model)

**What:** Exact same predict/update recursion as `KalmanTrendPlugin.compute_next()`, applied to CIS scores in `[-1, 1]` space. State is `{symbol: {tf: {x_est, P_est}}}` in the service layer.

**When to use:** Every bar, wrapping the `cis_scorer.score()` return value before fire condition check.

```python
# Source: src/intelligence/context/kalman_trend.py — verified
# CIS Kalman — runs in service layer, NOT in CISScorer

def _cis_kalman_update(
    raw_cis: float,
    x_est: float,
    P_est: float,
    Q: float,
    R: float,
) -> tuple[float, float]:
    """Returns (new_x_est, new_P_est) after one predict+update step."""
    # Predict
    P_pred = P_est + Q
    # Update
    K = P_pred / (P_pred + R)
    x_new = x_est + K * (raw_cis - x_est)
    P_new = (1.0 - K) * P_pred
    return x_new, P_new
```

**State initialization (first bar per symbol/TF):**
```python
# Initialize to raw CIS with P=R (same pattern as KalmanTrendPlugin)
if (symbol, tf) not in self._cis_kalman_state:
    self._cis_kalman_state[(symbol, tf)] = {
        "x_est": raw_cis,
        "P_est": R,  # uncertainty = measurement noise
    }
```

**Per-TF Q/R config (discretionary — starting values from requirements):**
```json
{
  "cis_kalman": {
    "1m":  {"Q": 0.01, "R": 0.08},
    "5m":  {"Q": 0.01, "R": 0.06},
    "15m": {"Q": 0.01, "R": 0.04},
    "1h":  {"Q": 0.01, "R": 0.02}
  }
}
```
Rationale: 1m CIS is noisier (higher R = more weight on prior state); 1h CIS is smoother (lower R = more weight on observation). Q fixed at 0.01 across TFs as CIS process noise is similar regardless of TF.

### Pattern 4: Shadow Fire Condition

**What:** Signals that pass the old condition (`abs(cis) > 0.35 AND buckets_agreeing >= 3`) but fail the new condition (`filtered_cis > 0.35 AND raw_cis > 0.28 AND buckets_agreeing >= 3`) are written to `signal_ledger` with `is_shadow=TRUE` and a suppression reason.

**Integration with existing infrastructure:**
```python
# In _process_bar(), after Kalman filter runs:
raw_cis = result.cis_score  # from CISScorer
filtered_cis = self._cis_kalman_state[(symbol, tf)]["x_est"]

new_condition = (
    filtered_cis > 0.35
    and raw_cis > 0.28
    and result.buckets_agreeing >= 3
)
old_condition = result.direction != 0  # current gate

if old_condition and not new_condition:
    # Determine which sub-condition failed
    if filtered_cis <= 0.35:
        suppression_reason = "kalman_filtered_cis_low"
    elif raw_cis <= 0.28:
        suppression_reason = "raw_cis_low"
    else:
        suppression_reason = "buckets_agreeing_low"
    # Write as shadow to signal_ledger (is_shadow=TRUE)
    # Track per regime_type for N>=30 graduation gate
```

### Anti-Patterns to Avoid

- **Storing sklearn objects in DB:** Pickle of `IsotonicRegression` is fragile. Store `breakpoints` and `values` arrays; reconstruct with `np.interp()` at runtime.
- **Applying calibration to ALL signals, not just the winner:** CAL-03 specifies calibration applies to the **winning signal's** `(plugin_name, timeframe)` after selection. Applying it to all-ranked before selection changes selection criteria incorrectly.
- **Applying TOD multiplier post-CIS:** The architectural decision is pre-CIS. Post-CIS application is a cosmetic rank adjustment; pre-CIS changes what enters the CIS bucket contribution.
- **Re-instantiating `CISScorer()` inside `aggregate()`:** Current aggregator creates `scorer = CISScorer()` fresh per call (line 170 of aggregator.py). This is stateless by design — do not add Kalman state to `CISScorer`. Kalman wraps the result in the service layer.
- **Using `garch_vol_regime` to scale CIS Kalman R:** GARCH sigma is in price units; CIS is in [-1, 1]. Dimensionally incoherent. Use per-TF fixed R only.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Isotonic regression | Custom monotone piecewise function | `sklearn.isotonic.IsotonicRegression` | Handles ties, edge cases, out-of-bounds automatically |
| Timezone conversion | Custom UTC→ET offset math | `zoneinfo.ZoneInfo("America/New_York")` | DST transitions handled correctly |
| Array interpolation for calibration at inference | Custom bisect + lerp | `numpy.interp(x, xp, fp)` | One-liner, handles boundary correctly |
| Moving average of CIS | Rolling mean | Kalman filter | Kalman is optimal Bayesian estimate; handles non-stationary noise; converges faster |

---

## Common Pitfalls

### Pitfall 1: Migration Number Collision

**What goes wrong:** The CONTEXT.md says to use `039_calibration_fields.sql` because `038` is taken by the roll detection phase. But if Phase 38 hasn't been executed yet, there is no `038` migration file on disk. Always verify `ls production/migrations/ | tail -5` before numbering.

**How to avoid:** Confirmed: last migration on disk is `037_vwap_volume_profile_fields.sql`. Use `038_calibration_fields.sql`. Phase 38 (roll detection) would use `039` when it executes. CONTEXT.md's advice to use `039` was written anticipating Phase 38 would run first, but it has not.

**Warning sign:** Migration fails with `relation already exists` or `column already exists`.

### Pitfall 2: `to_insert_params()` Tuple Length

**What goes wrong:** `LedgerEntry.to_insert_params()` returns a 54-element tuple. Adding `raw_cis_score`, `filtered_cis_score`, `calibrated_confidence` bumps it to 57. Every caller of `insert_signals_with_features` and every test that validates the tuple shape must be updated.

**How to avoid:** Search for `54` in `signal_ledger.py` and all test files. Update `_INSERT_SQL` to include `$55, $56, $57`. Update the docstring comment. Update `LedgerEntry.to_insert_params()` in lockstep with the SQL.

**Warning sign:** `asyncpg.exceptions.PostgresException: bind message supplies 57 parameters, but prepared statement requires 54`.

### Pitfall 3: `config/kalman_parameters.json` Does Not Exist

**What goes wrong:** `KalmanTrendPlugin._load_parameters()` handles the missing file with a fallback (`Path.exists()` check). The new CIS Kalman loader must do the same. If the file doesn't exist at service startup, the CIS Kalman falls back to defaults rather than crashing.

**How to avoid:** Create `config/kalman_parameters.json` in Wave 0 with the full structure including `cis_kalman` block. Verify `Path("config/kalman_parameters.json").exists()` returns True from project root before relying on it.

**Warning sign:** `KalmanTrendPlugin` loads fine but CIS Kalman uses unexpected Q/R values in logs.

### Pitfall 4: TOD Dict Key Format for Bayesian Prior Hours

**What goes wrong:** Session priors cover hour ranges (e.g., lunch chop 11:30–13:00 ET). But the TOD dict is keyed by `hour_et: int`. A signal at 11:45 ET has `hour_et=11`; at 12:15 ET has `hour_et=12`. Both are lunch chop, but only `hour_et=11` and `hour_et=12` must have the −10% prior. The prior table must enumerate all hours in the range, not just the start.

**How to avoid:** Expand session ranges to individual hour keys during prior table construction. Session "11:30–13:00" maps to hours 11 and 12 (12:00 starts at 12, not 13).

**Warning sign:** Signals at 12:45 ET show no lunch chop suppression.

### Pitfall 5: Calibration Applied Before Selection vs After

**What goes wrong:** If `calibrated_confidence` is used to reorder signals in `_build_all_ranked()` (CAL-03), and the calibration job also writes `calibrated_confidence` to `signal_ledger` for all ranked signals (not just the winner), there are two different usages with different semantics:
- **Ranking use (CAL-03):** `calibrated_confidence` derived from the signal's own `(plugin_name, timeframe)` isotonic curve — used as sort key to pick the best signal.
- **DB storage use (CAL-02):** `calibrated_confidence` stored for the winner only — true probability estimate for downstream ML.

**How to avoid:** Keep clear separation: `_build_all_ranked()` uses calibrated curves for ranking (all signals get a calibrated score for comparison purposes), but only the winning signal's `calibrated_confidence` is stored in `signal_ledger` as the headline probability. Non-winner entries get `calibrated_confidence=NULL`.

**Warning sign:** ML training pipeline sees non-NULL `calibrated_confidence` on non-selected signals — contaminates the training set.

### Pitfall 6: `aggregate()` Creates Fresh `CISScorer()` Per Call

**What goes wrong:** `aggregator.py` line 170 does `scorer = CISScorer()` — fresh bootstrap weights every call. Phase 35 does NOT change this (CISScorer stays stateless). The TOD pre-multiplied confidences flow through this same stateless scorer. Ensure the TOD adjustment is applied to `sig["confidence"]` in the signal dict *before* `aggregate()` is called, not inside the scorer.

**How to avoid:** Apply TOD multiplier in `_process_bar()` loop over `raw_signals` after `_run_setup_plugins()` returns and before the `aggregate()` call. This matches the CONTEXT.md decision and the existing alpha decay / TTL injection pattern in lines 911–952 of `signal_generator_service.py`.

### Pitfall 7: `is_shadow` Flag Shadow Count for Graduation

**What goes wrong:** The N≥30 shadow graduation gate requires counting suppressed signals per `regime_type`, not total suppressed signals. If the service restarts, the in-memory count resets. The count must be queried from the DB (`signal_ledger WHERE is_shadow=TRUE AND suppression_reason LIKE 'kalman%' GROUP BY regime_type_at_fire`), or the service must journal it on shutdown.

**How to avoid:** Simpler approach — count from DB on each weight_updater tick using a query. The graduation check is a one-time event, not a per-bar hot path.

**Warning sign:** Premature hard switch before N≥30 per regime_type is actually achieved.

---

## Code Examples

### Calibrator Module Structure

```python
# Source: mirrors run_weight_update() pattern in weight_updater.py
async def run_calibration_update(db_manager: Any) -> None:
    """Train isotonic regression calibration curves and write to confidence_calibration.

    Called immediately after run_weight_update() on the 30-min timer tick.
    Independent failure domain: exception caught, logged, weight update already complete.

    N>=100 gate: only (plugin_name, timeframe) pairs with sufficient resolved signals
    produce a calibration curve. Pairs below threshold are deleted from (or never
    inserted into) confidence_calibration so callers see no stale curves.
    """
    try:
        rows = await db_manager.execute_query("""
            SELECT setup_plugin, timeframe, confidence, outcome
            FROM signal_ledger
            WHERE outcome IS NOT NULL
              AND is_shadow = FALSE
            ORDER BY timestamp DESC
            LIMIT 50000
        """)
        if not rows:
            return
        # Group by (plugin_name, timeframe), fit IsotonicRegression when N>=100
        ...
        # Upsert to confidence_calibration
        await db_manager.execute_command("""
            INSERT INTO confidence_calibration
                (plugin_name, timeframe, breakpoints, values, ece, sample_size, updated_at)
            VALUES ($1, $2, $3::double precision[], $4::double precision[], $5, $6, NOW())
            ON CONFLICT (plugin_name, timeframe)
            DO UPDATE SET breakpoints=$3::double precision[], values=$4::double precision[],
                          ece=$5, sample_size=$6, updated_at=NOW()
        """, plugin_name, tf, breakpoints, values, ece, n)
    except Exception:
        logger.exception("Calibration update failed — weight update not affected")
```

### Service-Layer Calibration Curve Cache (mirror CIS weights refresh)

```python
# Source: _load_cis_weights_from_db() pattern in signal_generator_service.py (line 1420)
# _calibration_curves: dict[(plugin_name, timeframe), list[tuple[float, float]]]
# where list = [(breakpoint, value), ...] for np.interp() at inference

async def _load_calibration_curves_from_db(self) -> None:
    """Load calibration curves from confidence_calibration table every 30 min."""
    if self.db_manager is None:
        return
    try:
        rows = await self.db_manager.execute_query("""
            SELECT plugin_name, timeframe, breakpoints, values
            FROM confidence_calibration
            WHERE sample_size >= 100
        """)
        new_cache = {}
        for row in rows:
            key = (row["plugin_name"], row["timeframe"])
            new_cache[key] = (row["breakpoints"], row["values"])
        self._calibration_curves = new_cache
    except Exception as exc:
        self.logger.warning("Calibration curves refresh error", error=str(exc))
```

### TOD Cache Load (mirror drift penalties pattern)

```python
# Source: _refresh_drift_penalties_from_db() pattern (line 1346 in signal_generator_service.py)
async def _load_tod_multipliers_from_db(self) -> None:
    """Load TOD win rates from signal_ledger; compute Bayesian-smoothed multipliers."""
    # Query: actual win rates per (regime_type, timeframe, hour_et)
    rows = await self.db_manager.execute_query("""
        SELECT
            regime_type_at_fire,
            timeframe,
            EXTRACT(HOUR FROM timestamp AT TIME ZONE 'America/New_York')::int AS hour_et,
            COUNT(*) AS n,
            SUM(CASE WHEN outcome IN ('target_1','target_1_2','target_full') THEN 1 ELSE 0 END)
                AS wins
        FROM signal_ledger
        WHERE outcome IS NOT NULL AND is_shadow = FALSE
        GROUP BY 1, 2, 3
    """)
    # Build in-memory dict: (regime_type, tf, hour_et) -> effective_multiplier
    # Apply Bayesian formula with session priors as alpha seed
    ...
```

### `_build_all_ranked()` Calibrated Confidence Sort Key

```python
# Source: aggregator.py _build_all_ranked() — step to add after step 1c
# Applied as FINAL step after Hurst, entropy, drift penalty

# Step 1d: Apply calibrated_confidence as sort key when curve exists
# calibration_curves passed as optional kwarg to _build_all_ranked()
if calibration_curves:
    for sig in with_ranks:
        plugin_name = sig.get("setup_plugin", "")
        tf = timeframe  # passed in from calling context
        curve = calibration_curves.get((plugin_name, tf))
        if curve is not None:
            breakpoints, values = curve
            raw_conf = float(sig.get("confidence", 0.0))
            sig["calibrated_confidence"] = round(
                float(np.interp(raw_conf, breakpoints, values)), 4
            )
        else:
            sig["calibrated_confidence"] = None

# Sorting: use calibrated_confidence as primary key when available
return sorted(
    with_ranks,
    key=lambda s: (
        # calibrated_confidence is a probability [0,1]; lower = less confidence = worse
        # Invert so higher calibrated confidence sorts first (ascending adjusted_rank)
        -s.get("calibrated_confidence") if s.get("calibrated_confidence") is not None
        else -s.get("confidence", 0.0),
        ...
    )
)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Raw confidence as probability estimate | Isotonic regression calibration (N≥100) | Phase 35 | Confidence becomes a true probability (ECE near 0); Kelly criterion position sizing enabled in v2.0 |
| Uniform confidence weight at all hours | Bayesian-smoothed TOD multiplier seeded from regime priors | Phase 35 | Lunch chop / NY open signal quality reflected in selection, not just ranking |
| Raw CIS as fire threshold | Kalman-filtered CIS (pre-TF Q/R) + shadow transition | Phase 35 | Noise-reduced fire condition; data-driven promotion via N≥30 shadow gate |
| Hard N=20 switch between prior/empirical | Continuous Bayesian blend (α=20) | Phase 35 | No discontinuity artifact; prior overridden smoothly as data accumulates |

---

## Open Questions

1. **`regime_type_at_fire` column in `signal_ledger`**
   - What we know: `setup_plugin` is stored; `regime_type` can be looked up from `TIER_I7` plugin objects.
   - What's unclear: Is `regime_type` stored per-signal in `signal_ledger` today, or does the TOD query have to JOIN to a plugin metadata table?
   - Recommendation: Store `regime_type` from `sig.get("regime_type", "any")` in the LedgerEntry at signal fire time. Add it to the migration as column 58 (after the 3 calibration columns). This avoids a fragile JOIN against plugin registry at query time.

2. **Hour boundary for session priors**
   - What we know: "NY open (09:30–10:00 ET)" starts at 09:30, not 09:00.
   - What's unclear: A signal fired at 09:15 ET (hour=9) — should it get the NY open prior (+10%) or be neutral?
   - Recommendation: Apply the NY open prior to all of hour_et=9 (09:00–09:59). The first 30 minutes (09:00–09:30) are pre-market; empirical data will self-correct the prior once N accumulates.

3. **`calibrated_confidence` in `build_ledger_entries()`**
   - What we know: `build_ledger_entries()` in `signal_generator_service.py` builds `LedgerEntry` from `result.all_ranked`. The `calibrated_confidence` field must flow from the signal dict into `LedgerEntry`.
   - What's unclear: Whether `calibrated_confidence` should be a field on `LedgerEntry` or computed at insert time from the service's `_calibration_curves` cache.
   - Recommendation: Add `calibrated_confidence: float | None = None` to `LedgerEntry`; populate it in `build_ledger_entries()` by passing the calibration curves as a parameter.

---

## Validation Architecture

`workflow.nyquist_validation` key is absent from `.planning/config.json` — treat as enabled.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (`.venv/bin/pytest`) |
| Config file | `pytest.ini` or `pyproject.toml` (project root) |
| Quick run command | `.venv/bin/pytest tests/unit/intelligence/test_confidence_calibrator.py tests/unit/intelligence/test_kalman_trend.py -x -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CAL-01 | `confidence_calibration` table schema correct | unit (migration SQL) | `.venv/bin/pytest tests/unit/intelligence/test_confidence_calibrator.py::test_calibration_table_schema -x` | ❌ Wave 0 |
| CAL-02 | Calibrator trains on N≥100, skips below; writes breakpoints/values; appends `calibrated_confidence` to `signal_ledger` | unit | `.venv/bin/pytest tests/unit/intelligence/test_confidence_calibrator.py -x -q` | ❌ Wave 0 |
| CAL-03 | `_build_all_ranked()` uses `calibrated_confidence` as sort key when curve exists; raw fallback | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -k calibrated -x` | ❌ Wave 0 |
| TOD-01 | Bayesian smoothing converges to empirical for large N; prior-only at N=0 | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_calibration.py::test_tod_bayesian_smoothing -x` | ❌ Wave 0 |
| TOD-02 | TOD multiplier clamped to [0.7, 1.3]; applied pre-CIS to signal confidence | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_calibration.py::test_tod_multiplier_clamp -x` | ❌ Wave 0 |
| KAL-01 | Kalman filter converges: repeated same value → filtered_cis converges to that value; state persists per (symbol, tf) | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_calibration.py::test_cis_kalman_convergence -x` | ❌ Wave 0 |
| KAL-02 | `raw_cis_score` and `filtered_cis_score` both appear in `signal_ledger` rows; new fire condition enforced; shadow signals written with `is_shadow=TRUE` | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_calibration.py::test_shadow_fire_condition -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `.venv/bin/pytest tests/unit/intelligence/test_confidence_calibrator.py tests/unit/service_tests/test_signal_generator_calibration.py -x -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/unit/intelligence/test_confidence_calibrator.py` — covers CAL-01, CAL-02
- [ ] `tests/unit/intelligence/ml/__init__.py` — package marker for new `ml/` subdirectory
- [ ] `tests/unit/service_tests/test_signal_generator_calibration.py` — covers TOD-01, TOD-02, KAL-01, KAL-02
- [ ] `config/kalman_parameters.json` — must be created (KalmanTrendPlugin falls back to hardcoded defaults without it; CIS Kalman needs its own section)
- [ ] `production/migrations/038_calibration_fields.sql` — `confidence_calibration` table + 3 `signal_ledger` columns (`raw_cis_score`, `filtered_cis_score`, `calibrated_confidence`)

---

## Integration Points Summary

The following is a precise map for the planner of exactly where each change hooks in:

### `signal_generator_service.py`

| Location | Change | Phase req |
|----------|--------|-----------|
| `__init__()` | Add `self._cis_kalman_state: dict = {}`, `self._calibration_curves: dict = {}`, `self._tod_multipliers: dict = {}` | KAL-01, CAL-02, TOD-02 |
| `start()` → startup loads | Add `_load_calibration_curves_from_db()`, `_load_tod_multipliers_from_db()` | CAL-02, TOD-02 |
| `start()` → tasks | Add `_calibration_curves_refresh_loop()` (30 min), `_tod_multipliers_refresh_loop()` (4h) | CAL-02, TOD-02 |
| `_process_bar()` after `_run_setup_plugins()` | Apply TOD multiplier to each `sig["confidence"]` in `raw_signals` | TOD-02 |
| `_process_bar()` after `aggregate()` returns | Run CIS Kalman update; store `raw_cis` and `filtered_cis`; check new fire condition | KAL-01, KAL-02 |
| `build_ledger_entries()` | Accept `calibration_curves` param; add `calibrated_confidence` to `LedgerEntry` for winner | CAL-02, CAL-03 |

### `aggregator.py`

| Location | Change | Phase req |
|----------|--------|-----------|
| `_build_all_ranked()` | Accept optional `calibration_curves` kwarg; after step 1c (drift penalty), compute `calibrated_confidence` per signal; use as sort key | CAL-03 |
| `aggregate()` | Pass `calibration_curves` through to `_build_all_ranked()` | CAL-03 |

### `weight_updater.py`

| Location | Change | Phase req |
|----------|--------|-----------|
| `run_weight_update()` exit | Call `await run_calibration_update(db_manager)` in try/except | CAL-02 |

### `signal_ledger.py`

| Location | Change | Phase req |
|----------|--------|-----------|
| `LedgerEntry` dataclass | Add `raw_cis_score`, `filtered_cis_score`, `calibrated_confidence` fields (all `float | None = None`) | CAL-02, KAL-02 |
| `to_insert_params()` | Extend tuple by 3 elements → 57 total; update `_INSERT_SQL` to $55, $56, $57 | CAL-02, KAL-02 |

---

## Sources

### Primary (HIGH confidence)

- `src/intelligence/context/kalman_trend.py` — exact Kalman recursion pattern confirmed
- `src/intelligence/weight_updater.py` — `run_weight_update()` async function, timer integration pattern
- `src/intelligence/trading/cis_scorer.py` — `CISScorer` stateless confirmed; `CISResult.cis_score` field
- `src/intelligence/trading/aggregator.py` — `_build_all_ranked()` step structure, `aggregate()` signature
- `services/signal_generator_service.py` (full read) — `_process_bar()` integration point, all refresh loop patterns, `_cis_weights_refresh_loop()` canonical pattern
- `src/intelligence/trading/signal_ledger.py` — `LedgerEntry` 54-field tuple, `_INSERT_SQL` exact column list
- `.planning/phases/35-calibration-tod-multiplier-cis-kalman-filter/35-CONTEXT.md` — all locked decisions

### Secondary (MEDIUM confidence)

- `sklearn.isotonic.IsotonicRegression` — `X_thresholds_` and `y_thresholds_` attributes for breakpoint extraction (confirmed present in scikit-learn; exact attribute names should be verified against installed version with `.venv/bin/python -c "from sklearn.isotonic import IsotonicRegression; help(IsotonicRegression)"`)
- `zoneinfo.ZoneInfo("America/New_York")` — standard library DST-aware ET conversion (Python 3.9+; project uses 3.10+)

### Tertiary (LOW confidence — validate before use)

- Starting Q/R values for CIS Kalman: 1m R=0.08, 5m R=0.06, 15m R=0.04, 1h R=0.02. These are reasoned from "1m is noisier than 1h" but not backtested. The system will self-correct via shadow mode, but initial values affect suppression counts during the N≥30 graduation window.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries confirmed installed; no new dependencies
- Architecture: HIGH — all integration points verified against actual code; exact line numbers cited
- Pitfalls: HIGH for structural (tuple length, migration number, config file); MEDIUM for behavioral (TOD hour boundaries, calibration timing)

**Research date:** 2026-03-17
**Valid until:** 2026-04-17 (stable domain — no external library changes expected within 30 days)
