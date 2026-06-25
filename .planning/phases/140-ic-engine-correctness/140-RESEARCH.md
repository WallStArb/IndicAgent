# Phase 140: IC Engine Correctness - Research

**Researched:** 2026-06-25
**Domain:** IC engine correctness, forward return labeling, statistical methodology
**Confidence:** HIGH

---

## Summary

Seven issues were identified by first-principles review of `ic_engine.py` and
`forward_return_writer.py`. Two are P0 correctness blockers that must be fixed
before the next corpus run (forward_returns and feature_ic_scores are currently
empty - the corpus pipeline is mid-run at step 1 and has not yet reached these
steps). Two are P1 statistical methodology gaps that corrupt BH-FDR results. Two
are P2 quick cleanups with no correctness impact. One P1 item (sharpe_min_windows)
is a single APR database update.

The code has been read at the exact lines cited in the todo. All findings below are
verified against the actual implementation.

**Primary recommendation:** Fix P0 issues before the corpus pipeline reaches
forward_return_writer (step 2). P1 BH-FDR meta-gate goes into ensemble_trainer.py.
P1 collinearity fix goes into ic_engine.py. All changes require exactly one migration
(171) for new APR keys and one schema column.

---

## Issue-by-Issue Findings

### Issue 1: Stride Bug (P0) - ic_engine.py:617-619

**Exact code (lines 617-622):**
```python
max_lookahead = max(lookaheads.values())  # = 60
stride = max(subsample_min_stride, max_lookahead)  # always 60
sub_idx = np.arange(0, n_regime_raw, stride)
X_sub = X_regime[sub_idx]
returns_sub = returns_regime[sub_idx]
complete_sub = complete_regime[sub_idx]
```

This block is at the **regime level**, BEFORE the per-scale loop at line 655
(`for scale_idx, scale in enumerate(_SCALES):`). All four scales (fast=1, mid=5,
slow=20, extended=60) use the same `sub_idx` with stride=60.

**Structural dependency chain** inside the per-scale loop that uses subsampled data:
- Line 636: `feature_stds = np.std(X_sub, axis=0)` - degenerate detection uses X_sub
- Line 649: `X_sub_nd = X_sub[:, non_degenerate_mask]`
- Line 653: `ranks_X_full = rankdata(X_sub_nd, axis=0)` - pre-ranks subsampled data
- Lines 659-662: `complete_sub[:, scale_idx]` and `returns_sub[:, scale_idx]`
- Lines 750-759: `_compute_ic_rolling_metrics(X_sub, returns_sub, scale_idx, ..., stride)`

**Fix approach:**
1. Remove the shared subsampling block (lines 617-623) from the regime level
2. Move degenerate detection to operate on `X_regime` (full un-subsampled regime data) -
   this is strictly better: detects constant features before any subsampling discards variance
3. Inside the per-scale loop, compute per-scale subsampling:
   ```python
   scale_stride = max(subsample_min_stride, lookahead_bars)
   sub_idx = np.arange(0, n_regime_raw, scale_stride)
   X_sub_scale = X_regime[sub_idx][:, non_degenerate_mask]
   returns_sub_scale = returns_regime[sub_idx]
   complete_sub_scale = complete_regime[sub_idx]
   ```
4. `ranks_X_full` becomes `ranks_X_scale = rankdata(X_sub_scale, axis=0)` inside each scale
5. `_compute_ic_rolling_metrics` receives `X_sub_scale`, `returns_sub_scale`, `scale_stride`
   (not the old `stride`)

**Naming clarification:** rename local `stride` → `scale_stride` inside the loop to
avoid confusion with the old single-stride variable.

**Impact on n_independent:** With per-scale stride, each scale reports a different
`n_independent` in `feature_ic_scores`. The fast scale will have ~60x more independent
observations than the extended scale. This is correct behavior.

---

### Issue 2: Overnight Gap Contamination (P0) - forward_return_writer.py

**Root cause in `_build_forward_return_sql` (lines 172-232):**
```python
complete_col_list = [
    f"(open_{scale} IS NOT NULL) AS complete_{scale}" for scale in lookaheads
]
```
`complete_{scale}` is TRUE whenever `LEAD(open, N+1)` is non-NULL. It does not
check whether that forward bar is in the same trading session as the current bar.
The LEAD() window is ordered purely by timestamp with no session partition.

**Concrete case:** a 5m bar at 15:55 ET has `LEAD(open, 2)` point to 09:30 ET the
next morning. `complete_fast = true`, but the return measures an overnight position,
not 5 minutes of intraday microstructure. The feature vector at 15:55 captures
end-of-day dynamics; the label includes overnight gap.

**No session boundary concept exists in forward_return_writer.py.** `service_utils.py`
has `normalize_session_type()` for session type strings (RTH/ETH) but no trading-hours
time ranges or date-boundary helpers.

**Fix approach:**
1. Pass `tf` into `_build_forward_return_sql(lookaheads, tf)` (currently takes only `lookaheads`)
2. For intraday TFs (5m, 15m, 1h): add `LEAD(m.timestamp, {n+1}) OVER w AS fwd_ts_{scale}` to the windowed CTE for each scale
3. Change `complete_{scale}` definition for intraday TFs:
   ```sql
   (open_{scale} IS NOT NULL
    AND (fwd_ts_{scale} AT TIME ZONE 'America/New_York')::date
        = (m.timestamp AT TIME ZONE 'America/New_York')::date
   ) AS complete_{scale}
   ```
4. For '1d' TF: no change - `(open_{scale} IS NOT NULL)` is correct for daily
5. The SQL builder must branch on `tf` to emit different `complete_` definitions

**Timezone note:** `market_data_ohlcv.timestamp` stores UTC (IBKR convention). ET
conversion uses `AT TIME ZONE 'America/New_York'` which handles DST automatically.
No hardcoded UTC offsets.

**Call site update:** `_label_symbol_tf` already receives `tf`; just pass it through
to `_build_forward_return_sql`.

**Daily TF exemption:** daily bars never cross overnight gaps within their own
LEAD() because the window is partitioned by (symbol, tf) and ordered by date. A
daily bar's T+1 is always the next trading day, which is correct for daily IC.

**Backward compatibility:** forward_returns rows already in DB will have stale
`complete_fast/mid/slow/extended` values for intraday rows where `bar_ts` is at
session close. The HWM logic in `_label_symbol_tf` only re-fetches the tail window
(`max_n + 1` bars before current max). After fix, a full re-run with truncated
forward_returns will be needed to get correct `complete_` flags for the full history.

---

### Issue 3: BH-FDR Meta-Level Gate (P1) - ensemble_trainer.py

**Flow from ic_engine to ensemble:**
- ic_engine computes `passes_fdr` per (feature, symbol, tf, regime, lookahead) and
  stores it in `feature_ic_scores`
- ensemble_trainer queries (lines 251-262):
  ```sql
  SELECT feature_name, ic_sharpe, ic_ci_lower, ic_ci_upper, ic_sign, lookahead_bars
  FROM feature_ic_scores
  WHERE symbol = $1 AND tf = $2 AND regime = $3
    AND is_pooled = false AND passes_walkforward = true
    AND reliable = true AND ic_sharpe IS NOT NULL
  ```
  **`passes_fdr` is NOT in this filter.** A feature that passes FDR in only 1 of 232
  cells currently receives the same ensemble weight candidacy as one passing in 200.
- Strata discovery (lines 202-208) also does not filter on `passes_fdr`

**Correct insertion point:** a pre-processing step in `EnsembleTrainer.execute()` that
computes per-feature FDR pass rate across ALL (symbol, tf) cells, then builds an
exclusion set. This runs once before the per-stratum loop.

**SQL for meta-gate:**
```sql
SELECT feature_name,
  SUM(CASE WHEN passes_fdr THEN 1 ELSE 0 END)::float / COUNT(*) AS fdr_pass_rate
FROM feature_ic_scores
WHERE is_pooled = false AND reliable = true
GROUP BY feature_name
```

Features where `fdr_pass_rate < alpha.ensemble.meta_fdr_min_fraction` are excluded
from all strata. The exclusion set is computed once and passed into `_process_stratum`.

**New APR key required:** `alpha.ensemble.meta_fdr_min_fraction` (default 0.50 = 50%).
Must be seeded in migration 171. The 50% default means a feature must pass FDR in
the majority of (symbol, tf) cells to be eligible.

**Why not filter at the SQL level:** per-stratum SQL already filters on multiple
conditions; adding a correlated subquery for FDR pass rate per feature across all
cells would be expensive. Computing it once in Python is cleaner.

---

### Issue 4: Feature Collinearity (P1) - ic_engine.py

**61 feature names** (from `FeatureVector` dataclass - ic_engine.py uses these verbatim):

Dense correlation clusters (will inflate BH-FDR evidence for their factor):
- **Momentum (5):** `momentum_z_fast`, `momentum_z_mid`, `momentum_z_slow`,
  `momentum_reversal_z`, `momentum_rank_z` - all measure price momentum, correlated
  by construction (fast/mid/slow are nested lookbacks)
- **RSI (3):** `rsi_fast`, `rsi_mid`, `rsi_slow` - near-identical signal at different periods
- **CCI (3):** `cci_fast`, `cci_mid`, `cci_slow` - same
- **Aroon (2):** `aroon_fast`, `aroon_slow`
- **CTF (3):** `ctf_momentum`, `ctf_vwap_align`, `ctf_regime_align` - derived from
  same higher-timeframe data
- **HMM state (3):** `hmm_regime_prob`, `hmm_entropy`, `hmm_duration` - derived from
  same Markov chain
- **Volume flow (4):** `ofi_z`, `ofi_div`, `cvd_slope_z`, `cmf` - different normalizations
  of similar order/money flow signal
- **Calendar (10):** `dow_sin`, `dow_cos`, `month_position`, `quarter_position`,
  `days_to_month_end`, `in_ny_session`, `in_london_kz`, `in_overlap`, `power_hour`,
  `opening_range` - discrete calendar signals, many mutually exclusive

**Where to implement:** inside `_compute_symbol_tf` in ic_engine.py, after building
`X_sub` for a given regime (before BH-FDR collection). This is per (symbol, tf, regime)
since correlation structure may vary by regime.

**Scipy approach (verified in Phase 138 research):**
```python
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform

corr = np.corrcoef(X_sub.T)  # [n_features, n_features]
dist = np.sqrt(0.5 * (1 - np.clip(corr, -1, 1)))  # correlation distance
Z = linkage(squareform(dist, checks=False), method='average')
cluster_ids = fcluster(Z, t=alpha.ic.cluster_max_corr, criterion='distance')
```

**Where to store cluster membership:** add `cluster_id SMALLINT` column to
`feature_ic_scores`. This requires migration 171. Cluster IDs are local to each
(symbol, tf, regime) run - they are for ensemble use, not absolute identifiers.

**New APR key:** `alpha.ic.cluster_max_corr` (default 0.70 correlation threshold -
features with pairwise corr >= 0.70 are clustered together). Seeded in migration 171.

**BH-FDR with clustering:** only the cluster representative (highest-IC-magnitude
feature) has its p-value included in the BH-FDR batch. Non-representatives have
`passes_fdr = false`, `bh_adjusted_p = NULL`. The `cluster_id` field enables the
ensemble_trainer to apply additional cluster-level weight caps alongside the existing
`cluster_deflate_weights` function.

---

### Issue 5: IC Sharpe min_windows (P1) - APR update only

**Current value:** `alpha.ic.sharpe_min_windows = 10` (confirmed in config_state).

**Fix:** single SQL UPDATE in migration 171:
```sql
UPDATE config_state SET config_value = '30', updated_at = NOW()
WHERE config_key = 'alpha.ic.sharpe_min_windows';
```

No code change required. `_load_apr` reads this key at startup and passes it to
`_compute_ic_rolling_metrics` via `apr["sharpe_min_windows"]`. The function
already gates on `n_windows_possible >= sharpe_min_windows`.

**Statistical motivation:** SE(IC Sharpe) ≈ 1/√n_windows. At n=10: SE ≈ 0.32. At
n=30: SE ≈ 0.18. The current gate is too permissive to distinguish signal from noise.

**Side effect on corpus:** more (symbol, tf, regime) cells will have `ic_sharpe = NULL`
after this change. Specifically: SPY at 1h has ~26K independent obs / 2000 per window
= 13 windows. With min=30 windows, SPY 1h will have `ic_sharpe = NULL` for most
regime/lookahead combinations. This means the ensemble will not have IC Sharpe data
for 1h strata on most symbols. This is intentional - we want to be honest about what
we can measure.

---

### Issue 7: all_results_global Accumulates Forever (P2) - ic_engine.py:1171,1186

**Verified behavior (lines 1171-1196):**
```python
all_results_global: list[dict] = []  # line 1171

for result in pool.map(_run_ic_worker, worker_args, chunksize=1):
    ...
    all_results_global.extend(result["all_results"])   # line 1186
    if result["all_results"]:
        for tf in tfs:
            tf_results = [r for r in result["all_results"] if r.get("tf") == tf]
            if tf_results:
                _emit_health_gauges(symbol, tf, tf_results)  # uses result[], NOT global
```

`_emit_health_gauges` on line 1191 uses `result["all_results"]` (the per-symbol
result dict), NOT `all_results_global`. After the `pool.map` loop ends, `all_results_global`
is never referenced again. The list accumulates all result dicts from all symbols but
is then garbage collected at function return.

**Memory estimate at full scale:** 58 symbols x 4 TFs x ~6 regime passes x 61 features
x 4 lookaheads = ~341,568 dicts. Each dict has ~25 keys. This is meaningful but not
catastrophic on current hardware. The todo's "17M dicts" estimate is for a hypothetical
5000-symbol universe.

**Fix:** delete line 1171 (`all_results_global: list[dict] = []`) and line 1186
(`all_results_global.extend(result["all_results"])`). No functional change.

---

### Issue 8: training_window_end Derived from Live Data (P2) - ic_engine.py:1083-1085

**Current code:**
```python
with conn.cursor() as cur:
    cur.execute("SELECT MAX(bar_ts) FROM feature_vectors")
    training_window_end = cur.fetchone()[0]
```

No `--training-window-end` CLI arg exists in the arg parser (lines 1033-1055). The
argparse setup has `--symbols`, `--tf`, and `--workers` only.

**Fix:** add to arg parser:
```python
parser.add_argument(
    "--training-window-end",
    default=None,
    help="Explicit training window end timestamp (ISO 8601). "
         "Default: MAX(bar_ts) FROM feature_vectors. "
         "Set explicitly to keep PKs stable across multi-run corpus builds.",
)
```

Then in main:
```python
if args.training_window_end:
    training_window_end = datetime.fromisoformat(args.training_window_end)
    _logger.info("ic_engine.training_window_end_explicit", value=str(training_window_end))
else:
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(bar_ts) FROM feature_vectors")
        training_window_end = cur.fetchone()[0]
    _logger.warning(
        "ic_engine.training_window_end_from_max",
        value=str(training_window_end),
        note="Pass --training-window-end to stabilize PKs across runs",
    )
```

The corpus_pipeline_run.sh should be updated to pass `--training-window-end` using
the value captured at pipeline start.

---

## Architecture Patterns

### Per-Scale Subsampling Refactor (Issue 1)

The refactor moves subsampling from regime-level to scale-level. The structure changes
from:

```
for regime in regime_passes:
    [subsample once at stride=60]
    [degenerate detect on X_sub]
    for scale in scales:
        [use X_sub, returns_sub, complete_sub]
```

To:

```
for regime in regime_passes:
    [degenerate detect on X_regime - full regime data]
    for scale in scales:
        [subsample at stride=lookahead_bars for this scale]
        [use X_sub_scale, returns_sub_scale, complete_sub_scale]
```

**Degenerate detection moving to X_regime:** a feature constant across the full
regime may still have variance in a small subsample; detecting on the full data is
strictly more correct. The `non_degenerate_mask` is shared across scales (a feature
either has signal variance or it doesn't).

**`_compute_ic_rolling_metrics` signature change:** the `stride` parameter becomes
`scale_stride` and is now passed per-scale. The function divides `sharpe_window_size`
by this stride to get the subsampled window size (line 430: `sharpe_window_size // stride`).
This is still correct.

### Session Boundary SQL (Issue 2)

The SQL builder `_build_forward_return_sql` gains a `tf` parameter and emits
different `complete_` definitions for intraday vs daily. The intraday version
requires additional `LEAD(timestamp)` projections in the windowed CTE.

For intraday, the CTE grows by `len(lookaheads)` additional LEAD columns (one
forward timestamp per scale). This is negligible overhead; TimescaleDB computes
LEAD over its chunk indexes efficiently.

### Meta-FDR Gate (Issue 3)

The meta-gate is a pre-computation step in `EnsembleTrainer.execute()` that runs
once, before the per-stratum loop. It queries all `feature_ic_scores` rows grouped
by feature_name to produce a `meta_eligible_features: set[str]`. Inside
`_process_stratum`, after fetching ic_rows, filter:
```python
ic_rows = [r for r in ic_rows if r["feature_name"] in meta_eligible_features]
```

This is clean - no change to `select_features_per_stratum` or the downstream
weight derivation functions.

### Cluster-Aware BH-FDR (Issue 4)

Clustering runs inside the per-regime pass, after subsampling and degenerate
detection, before the per-scale loop. Cluster IDs are stable across scales for
the same (symbol, tf, regime) pass (computed once from X_sub at the first scale).

**Representative selection:** within each cluster, pick the feature with the
highest `|ic_value|` (absolute IC magnitude) as the representative. Only
representatives enter the `pvals_flat` list. Non-representatives get
`passes_fdr = False` and `bh_adjusted_p = None`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Hierarchical clustering | Custom dendrogram | `scipy.cluster.hierarchy.linkage` + `fcluster` |
| Correlation distance | Manual formula | `scipy.spatial.distance.squareform` on corr matrix |
| BH-FDR correction | Manual rank-based correction | `statsmodels.stats.multitest.multipletests(..., method='fdr_bh')` - already used |
| ET timezone conversion | Hardcoded UTC offsets | PostgreSQL `AT TIME ZONE 'America/New_York'` (handles DST) |

---

## Common Pitfalls

### Pitfall 1: Degenerate Mask Computed on Subsampled Data
**What goes wrong:** Moving subsampling inside the scale loop while keeping
degenerate detection on `X_sub` means each scale computes a potentially different
`non_degenerate_mask`. A feature might appear non-degenerate at stride=1 but
degenerate at stride=60 (if variance is concentrated in excluded rows).
**Prevention:** compute `non_degenerate_mask` once from `X_regime` (full
regime data, no subsampling). One mask, shared across all scales.

### Pitfall 2: `_compute_ic_rolling_metrics` Receives Old-Style `stride`
**What goes wrong:** `_compute_ic_rolling_metrics(X_sub, ..., stride)` converts
`sharpe_window_size` from raw to subsampled via `sharpe_window_size // stride`.
If you pass the new `scale_stride` but forget to update the function call site,
the window size conversion remains correct. But if you accidentally pass the old
`max_lookahead` stride (60) for the fast scale, IC Sharpe uses 60x fewer windows
than available.
**Prevention:** the call site change at lines 750-759 must use `scale_stride`, not
any `max_lookahead` variable. Verify in tests that fast-scale IC Sharpe windows
increase by ~60x after the fix.

### Pitfall 3: forward_return_writer HWM Logic After Session Fix
**What goes wrong:** `_label_symbol_tf` uses HWM to resume: it refetches the last
`max_n+1` bars before the current max. If forward_returns already has rows with
stale `complete_` flags (pre-fix run), the HWM will skip the older rows.
**Prevention:** for the first run after the fix, truncate `forward_returns` and
run from scratch. Add a note to the corpus_pipeline_run.sh.

### Pitfall 4: Cluster ID Instability Across Runs
**What goes wrong:** correlation-based clustering can produce different cluster
assignments if X_sub changes (e.g., new bars added). This makes `cluster_id` in
`feature_ic_scores` non-comparable across runs.
**Prevention:** `cluster_id` is scoped to a single (symbol, tf, regime, training_window_end)
run and is used only within that run for BH-FDR gating. Do not join cluster_id
across different `training_window_end` values.

### Pitfall 5: Meta-FDR Gate Applied Before BH-FDR Stabilizes
**What goes wrong:** if ic_engine runs on only a few symbols (partial run),
the meta-FDR gate in ensemble_trainer would use a low-N pass rate. A feature
might be excluded for having low pass rate only because it hasn't been evaluated
on most symbols yet.
**Prevention:** ensemble_trainer should log a warning when `total_cells_evaluated`
(denominator in pass rate) is below some floor (e.g., 10% of expected cells).
Add `n_evaluated_cells` to the meta-gate log output.

---

## Code Examples

### Per-Scale Subsampling (Issue 1 Fix Pattern)

```python
# At regime level: degenerate detection on FULL regime data
feature_stds = np.std(X_regime, axis=0)
degenerate_mask = feature_stds < 1e-8
non_degenerate_mask = ~degenerate_mask
# ... log n_degenerate ...

X_regime_nd = X_regime[:, non_degenerate_mask]

for scale_idx, scale in enumerate(_SCALES):
    lookahead_bars = lookaheads[scale]
    scale_stride = max(subsample_min_stride, lookahead_bars)  # per-scale stride
    sub_idx = np.arange(0, n_regime_raw, scale_stride)

    X_sub_nd = X_regime_nd[sub_idx]           # already non-degenerate cols
    returns_sub = returns_regime[sub_idx]
    complete_sub = complete_regime[sub_idx]
    n_independent = len(sub_idx)

    if n_independent < min_reliable_n:
        # ... skip ...
        continue

    ranks_X_scale = rankdata(X_sub_nd, axis=0)
    # ... rest of per-scale IC computation ...
    # _compute_ic_rolling_metrics(X_sub_nd, returns_sub, scale_idx,
    #     complete_sub[:, scale_idx], apr, non_degenerate_mask, n_features, scale_stride)
```

### Session Boundary SQL (Issue 2 Fix Pattern)

```python
def _build_forward_return_sql(lookaheads: dict[str, int], tf: str) -> str:
    is_intraday = tf in ("5m", "15m", "1h")
    max_n = max(lookaheads.values())
    frame_size = max_n + 1

    lead_col_list = [
        f"LEAD(m.open, {n + 1}) OVER w AS open_{scale}"
        for scale, n in lookaheads.items()
    ]
    lead_t1 = "LEAD(m.open, 1) OVER w AS open_entry"

    if is_intraday:
        fwd_ts_cols = [
            f"LEAD(m.timestamp, {n + 1}) OVER w AS fwd_ts_{scale}"
            for scale, n in lookaheads.items()
        ]
        # ...include fwd_ts_cols in CTE...
        complete_col_list = [
            f"(open_{scale} IS NOT NULL "
            f"AND (fwd_ts_{scale} AT TIME ZONE 'America/New_York')::date "
            f"    = (m.timestamp AT TIME ZONE 'America/New_York')::date"
            f") AS complete_{scale}"
            for scale in lookaheads
        ]
    else:
        # Daily TF: no session boundary issue
        complete_col_list = [
            f"(open_{scale} IS NOT NULL) AS complete_{scale}"
            for scale in lookaheads
        ]
```

### Meta-FDR Gate (Issue 3 Fix Pattern)

```python
# In EnsembleTrainer.execute(), before the per-stratum loop:
meta_fdr_min_fraction = _cfg_float(cfg, "alpha.ensemble.meta_fdr_min_fraction", 0.50)

fdr_pass_rates = await conn.fetch("""
    SELECT feature_name,
           SUM(CASE WHEN passes_fdr THEN 1 ELSE 0 END)::float / COUNT(*) AS fdr_pass_rate,
           COUNT(*) AS n_cells
    FROM feature_ic_scores
    WHERE is_pooled = false AND reliable = true
    GROUP BY feature_name
""")

meta_eligible_features = {
    r["feature_name"] for r in fdr_pass_rates
    if r["fdr_pass_rate"] >= meta_fdr_min_fraction
}

n_total_cells = sum(r["n_cells"] for r in fdr_pass_rates)
self.logger.info(
    "ensemble_trainer.meta_fdr_gate",
    n_eligible=len(meta_eligible_features),
    n_total=len(fdr_pass_rates),
    min_fraction=meta_fdr_min_fraction,
    n_total_cells_evaluated=n_total_cells,
)

# Then in _process_stratum, after fetching ic_rows:
ic_rows = [r for r in ic_rows if dict(r)["feature_name"] in meta_eligible_features]
```

---

## Schema Changes

One migration (171) covers all Phase 140 schema and APR changes.

### New APR Keys to Seed

| Key | Value | Rationale |
|-----|-------|-----------|
| `alpha.ensemble.meta_fdr_min_fraction` | `0.50` | Feature must pass FDR in 50% of cells |
| `alpha.ic.cluster_max_corr` | `0.70` | Correlation threshold for BH-FDR clustering |
| `alpha.ic.sharpe_min_windows` UPDATE | `30` (from 10) | SE floor for IC Sharpe reliability |

### Schema Column

`feature_ic_scores`: add `cluster_id SMALLINT NULL` (NULL for rows computed
before Phase 140; non-NULL after).

```sql
ALTER TABLE feature_ic_scores ADD COLUMN cluster_id SMALLINT NULL;
COMMENT ON COLUMN feature_ic_scores.cluster_id IS
    'Correlation cluster ID for this (symbol, tf, regime, training_window_end) run. '
    'Cluster representative has the highest |ic_value| within cluster. '
    'Non-representatives have passes_fdr=false. NULL for pre-Phase-140 rows.';
```

---

## State of the Art

| Old Behavior | New Behavior |
|--------------|--------------|
| stride = max(subsample_min_stride, 60) for ALL scales | stride = max(subsample_min_stride, lookahead_bars) PER SCALE |
| complete_{scale} = open not NULL (crosses sessions) | complete_{scale} = open not NULL AND same ET day (intraday) |
| passes_fdr per (symbol, tf) cell, no meta-gate | passes_fdr per cell + meta-level gate in ensemble_trainer |
| BH-FDR applied to all 61 features independently | BH-FDR applied to cluster representatives only |
| sharpe_min_windows = 10 (SE = 0.32) | sharpe_min_windows = 30 (SE = 0.18) |
| all_results_global grows unbounded in memory | removed |
| training_window_end always derived from MAX(bar_ts) | --training-window-end CLI arg for PK stability |

---

## Files Touched

| File | Issues | Change Type |
|------|--------|-------------|
| `services/ic_engine.py` | 1, 4, 7, 8 | Refactor subsampling loop; clustering; remove global; add CLI arg |
| `services/forward_return_writer.py` | 2 | Add tf param to SQL builder; session boundary in complete_ |
| `services/ensemble_trainer.py` | 3 | Add meta-FDR pre-computation and stratum filter |
| `production/migrations/171_ic_correctness.sql` | 4, 5 | cluster_id column; 3 APR key changes |
| `production/scripts/corpus_pipeline_run.sh` | 8 | Pass --training-window-end at step 4 (ic_engine) |

---

## Open Questions

1. **Cluster ID reuse across (symbol, tf, regime) strata**
   - What we know: clustering is per (symbol, tf, regime), so cluster IDs are local
   - What's unclear: should the planner assign canonical cluster names
     (e.g., "momentum_cluster") from a pre-defined taxonomy instead of integers?
   - Recommendation: integer IDs are sufficient for Phase 140. A canonical taxonomy
     can be built after seeing the empirical cluster structure from actual data.

2. **Corpus pipeline re-run scope after P0 fixes**
   - What we know: forward_returns and feature_ic_scores are both empty right now;
     the corpus pipeline is at step 1 (feature_factory). P0 fixes must be in place
     before step 2 (forward_return_writer) runs.
   - What's unclear: corpus_pipeline_run.sh step ordering and whether phase 140 changes
     can be merged before the pipeline reaches step 2.
   - Recommendation: treat this as a hard dependency. Plan task ordering to commit
     ic_engine and forward_return_writer changes before the corpus pipeline progresses.

---

## Sources

### Primary (HIGH confidence)
- `services/ic_engine.py` (read in full, lines 1-1225) - stride bug, all_results_global,
  training_window_end, feature names, _compute_ic_rolling_metrics signature
- `services/forward_return_writer.py` (read in full) - SQL builder, session boundary absence
- `services/ensemble_trainer.py` (lines 1-310 read) - feature_ic_scores query, passes_fdr
  absence, meta-gate insertion point
- `src/intelligence/ensemble/feature_selector.py` (read in full) - how rows are consumed
- `src/intelligence/schemas.py` via `FeatureVector` dataclass introspection - all 61 feature
  names confirmed
- `config_state` database query - confirmed `alpha.ic.sharpe_min_windows = 10` live value
- `production/migrations/` listing - confirmed next migration number is 171

### Secondary (MEDIUM confidence)
- `.planning/phases/138-ic-engine-forward-returns/138-RESEARCH.md` - background on IC
  methodology, scipy patterns, SQL patterns
- `.planning/todos/pending/001-ic-engine-correctness-p0.md` - issue definitions and file refs

---

## Metadata

**Confidence breakdown:**
- P0 stride bug fix: HIGH - code read verbatim, structural dependency chain traced
- P0 session boundary fix: HIGH - SQL verified, no existing session logic found
- P1 meta-FDR gate: HIGH - ensemble_trainer query verified, passes_fdr absence confirmed
- P1 collinearity approach: MEDIUM - scipy clustering is standard; cluster threshold 0.70 is
  a reasonable starting point but empirical validation should inform the APR value
- P1 sharpe_min_windows: HIGH - current value confirmed in DB, fix is a 1-line SQL update
- P2 cleanups: HIGH - code read verbatim, behavior confirmed

**Research date:** 2026-06-25
**Valid until:** 2026-07-25 (stable codebase; no external dependencies)
