# I6 Plugin Backtest Infrastructure

Renaissance-style discipline: Prove I6 plugins work on historical data before production deployment.

## Purpose

The backtest infrastructure enables scientific validation of I6 (cross-timeframe confluence) plugins on 6+ months of historical market data. This follows the Renaissance principle: **"Earn the right through proof"** — no signal reaches production without statistically significant evidence (p < 0.05, sufficient N).

### Why Backtest I6 Plugins?

- **Fast iteration:** Test parameter changes in minutes, not weeks
- **Feature selection:** Keep IC > 0.05, tweak IC 0.02-0.05, kill IC < 0.02
- **Regime awareness:** Validate that signals work in specific market regimes (trending vs ranging)
- **Risk reduction:** Catch bugs and edge cases before live deployment
- **ML foundation:** Generate labeled training data for v2.3 ML layer

## Usage

### 1. Backtest an I6 Plugin

```bash
# Backtest CrossTimeframeConfluencePlugin on 6 months of data
python tools/backtest_i6_plugin.py \
  --plugin CrossTimeframeConfluencePlugin \
  --start 2025-10-01 \
  --end 2026-04-01 \
  --symbols ES NQ CL \
  --timeframes 5m 15m 1h \
  --output /tmp/cross_tf_backtest.csv

# Output: CSV with columns
# ts, symbol, tf, ctf_score, ctf_trend_alignment, ..., pnl_r, hmm_regime
```

**Parameters:**
- `--plugin`: Plugin class name (must be registered in `src/intelligence/register_plugins.py`)
- `--start`: Backtest start date (YYYY-MM-DD)
- `--end`: Backtest end date (YYYY-MM-DD)
- `--symbols`: Optional symbol filter (default: all active contracts)
- `--timeframes`: Optional timeframe filter (default: all standard TFs)
- `--output`: Output CSV path

### 2. Validate Backtest Results

```bash
# Compute Information Coefficient (IC) and p-value
python tools/validate_i6_backtest.py \
  --input /tmp/cross_tf_backtest.csv \
  --field ctf_score \
  --min-ic 0.05 \
  --alpha 0.01
```

**Output:**
```
Validation Results: ctf_score
Overall: IC=0.082, p=0.003, n=1247 ✓ PASSED
Regimes:
  hmm_regime_0 (ranging): IC=0.034, p=0.042, n=423 ✗ FAILED
  hmm_regime_1 (trending_up): IC=0.124, p=0.001, n=518 ✓ PASSED
  hmm_regime_2 (trending_down): IC=0.091, p=0.018, n=306 ✓ PASSED

Conclusion: Plugin shows strong signal in trending regimes, weak in ranging.
Recommendation: Deploy to shadow mode, monitor regime-specific performance.
```

**Parameters:**
- `--input`: Backtest CSV path from `backtest_i6_plugin.py`
- `--field`: Field name to validate (must exist in CSV)
- `--min-ic`: Minimum IC threshold (default: 0.05)
- `--alpha`: Significance threshold (default: 0.01 for Bonferroni correction)
- `--min-n`: Minimum sample size (default: 30)

## Decision Criteria

### Keep (IC > 0.05)

- **Strong signal:** IC > 0.10 → deploy to production
- **Moderate signal:** IC 0.05-0.10 → deploy to shadow mode, monitor
- **Regime-specific:** IC > 0.05 in at least 1 regime → deploy with regime gate

### Tweak (IC 0.02-0.05)

- **Weak signal:** IC 0.02-0.05 → adjust parameters, retry
- **Tuning examples:**
  - Lookback window (try 5, 10, 20, 50 bars)
  - Thresholds (try 0.3, 0.5, 0.7 for confluence scores)
  - Weights (trend vs structure vs regime)
- **Retest:** Run backtest after each parameter change, track IC improvement

### Kill (IC < 0.02)

- **No signal:** IC < 0.02 → abandon, do not deploy
- **Anti-signal:** IC < -0.02 → invert direction OR kill (risk of overfitting)
- **Document:** Add findings to `docs/plans/` for future reference

## Parameter Tuning Workflow

### Example: Tuning CrossTFMomentumDivergencePlugin

```bash
# Baseline: lookback=20
# Step 1: Test different lookback windows
for lookback in 10 20 30 50; do
  # Update plugin parameter in code
  sed -i "s/min_lookback = [0-9]*/min_lookback = $lookback/" \
    src/intelligence/confluence/cross_tf_momentum_divergence.py

  # Run backtest
  python tools/backtest_i6_plugin.py \
    --plugin CrossTFMomentumDivergencePlugin \
    --start 2025-10-01 --end 2026-04-01 \
    --output /tmp/backtest_lb${lookback}.csv

  # Validate
  python tools/validate_i6_backtest.py \
    --input /tmp/backtest_lb${lookback}.csv \
    --field ctf_momentum_divergence
done

# Step 2: Compare IC across lookback values
# Pick best lookback (highest IC with p < 0.01)
```

### Grid Search Example

```bash
# Test 5 lookback × 5 threshold = 25 combinations
for lookback in 10 20 30 50 100; do
  for threshold in 0.3 0.5 0.7 0.8 0.9; do
    # Update plugin parameters
    # Run backtest
    # Validate
    # Log results to /tmp/grid_search.csv
  done
done

# Sort by IC, pick best parameters
cat /tmp/grid_search.csv | sort -t',' -k3 -rn
```

## Regime Analysis

### Why Regime-Segmented Validation?

Markets behave differently in trending vs ranging regimes. A signal that works in trending markets may fail in ranging markets (and vice versa).

**Regime types:**
- `hmm_regime=0`: Ranging/sideways (low volatility, mean-reversion)
- `hmm_regime=1`: Trending up (upward momentum)
- `hmm_regime=2`: Trending down (downward momentum)

**Interpretation:**
```
# Good: Works in trending regimes only
hmm_regime_0: IC=0.034, p=0.042 ✗ FAILED
hmm_regime_1: IC=0.124, p=0.001 ✓ PASSED
hmm_regime_2: IC=0.091, p=0.018 ✓ PASSED
→ Deploy with regime_type='trend' gate (suppress in ranging)

# Bad: Works nowhere
All regimes: IC < 0.02, p > 0.05 ✗ FAILED
→ Kill plugin

# Excellent: Works in all regimes
All regimes: IC > 0.08, p < 0.01 ✓ PASSED
→ Deploy to production unconditionally
```

## Data Requirements

### Minimum Sample Size

- **30 bars:** Minimum for statistical significance (min_n parameter)
- **100+ bars:** Preferred for robust IC estimates
- **1000+ bars:** Ideal for regime-segmented analysis (300+ per regime)

### Date Range Recommendations

- **6+ months:** Capture multiple market regimes
- **Include both bull and bear periods:** Test signal robustness
- **Avoid stale data:** Use recent 12-24 months max (market structure changes)

## Advanced Usage

### Custom Symbol Lists

```bash
# Test only equity indices
python tools/backtest_i6_plugin.py \
  --plugin CrossTimeframeConfluencePlugin \
  --start 2025-10-01 --end 2026-04-01 \
  --symbols ES NQ RTY YM \
  --output /tmp/equity_indices.csv

# Test only energy futures
python tools/backtest_i6_plugin.py \
  --plugin CrossTimeframeConfluencePlugin \
  --start 2025-10-01 --end 2026-04-01 \
  --symbols CL NG RB HO \
  --output /tmp/energy_futures.csv
```

### Timeframe-Specific Validation

```bash
# Test if signal works better on higher timeframes
for tf in 5m 15m 1h 4h; do
  python tools/backtest_i6_plugin.py \
    --plugin CrossTimeframeConfluencePlugin \
    --start 2025-10-01 --end 2026-04-01 \
    --timeframes $tf \
    --output /tmp/backtest_${tf}.csv

  python tools/validate_i6_backtest.py \
    --input /tmp/backtest_${tf}.csv \
    --field ctf_score
done
```

## Troubleshooting

### No Data Found

```
WARNING: No data found in intelligence_features for date range
```

**Cause:** `intelligence_features` table is empty for specified date range.

**Fix:**
1. Check data exists: `SELECT COUNT(*) FROM intelligence_features WHERE ts BETWEEN '2025-10-01' AND '2026-04-01';`
2. Adjust date range to match available data
3. Run backfill: `python scripts/historical_backfill.py`

### Empty Results

```
WARNING: No valid backtest results generated
```

**Cause:** Plugin returns empty dict for all bars.

**Fix:**
1. Check plugin `compute_full()` implementation
2. Verify `outputs` frozenset matches returned keys
3. Add debug logging to plugin

### Low IC Everywhere

```
Overall: IC=0.003, p=0.850 ✗ FAILED
All regimes: IC < 0.02 ✗ FAILED
```

**Cause:** Signal has no predictive power.

**Fix:**
1. Review plugin logic for bugs
2. Try parameter tuning (lookback, thresholds)
3. If IC remains < 0.02 after tuning → kill plugin

## Integration with CI/CD

### Pre-commit Hook

Add to `.git/hooks/pre-commit`:

```bash
# Run backtest on any modified I6 plugin
CHANGED_PLUGINS=$(git diff --name-only | grep "src/intelligence/confluence/")

if [ -n "$CHANGED_PLUGINS" ]; then
  echo "Running backtest on modified I6 plugins..."
  python tools/backtest_i6_plugin.py --plugin CrossTimeframeConfluencePlugin \
    --start 2025-10-01 --end 2026-04-01 --output /tmp/backtest.csv

  python tools/validate_i6_backtest.py \
    --input /tmp/backtest.csv --field ctf_score --min-ic 0.02

  if [ $? -ne 0 ]; then
    echo "ERROR: Plugin backtest failed (IC < 0.02)"
    exit 1
  fi
fi
```

## References

- **Plan:** `.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-00-PLAN.md`
- **Context:** `.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-CONTEXT.md`
- **Renaissance Review:** `.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-RENAISSANCE-REVIEW-R&D.md`

## License

Internal tool — IndicAgent project use only.
