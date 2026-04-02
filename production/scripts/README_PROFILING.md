# Phase 0 Profiling Scripts

## Renaissance Principle

> "Measure twice, cut once. Don't optimize without understanding."

Before parallelizing the pipeline, we measure:
1. **Delta Distribution** - How much do prices move bar-to-bar?
2. **Information Rate** - How often do plugin outputs change?
3. **Economic Value** - Which symbols generate the most profit? (TODO: needs signal outcomes)

## Quick Start

### Run All Measurements (Recommended)

```bash
# Activate venv
source .venv/bin/activate

# Run complete Phase 0 profiling
.venv/bin/python production/scripts/phase0_profile_pipeline.py

# Results saved to: production/scripts/phase0_results.json
```

### Run Individual Measurements

```bash
# Measure delta distribution
.venv/bin/python production/scripts/measure_delta_distribution.py

# Measure information rate
.venv/bin/python production/scripts/measure_information_rate.py
```

## Output Interpretation

### Delta Distribution

**Good for filtering:**
- `90% of bars move < 0.05%` → Aggressive filtering (90% reduction)
- `90% of bars move < 0.10%` → Standard filtering (90% reduction)
- `75% of bars move < 0.20%` → Conservative filtering (75% reduction)

**Bad for filtering:**
- `90% of bars move > 0.20%` → Don't filter (would drop valuable signals)

### Information Rate

**Good for caching:**
- `I1 change rate < 30%` → Cache I1 outputs (70%+ hit rate)
- `I7 change rate < 30%` → Cache I7 outputs (70%+ hit rate)

**Bad for caching:**
- `I1/I7 change rate > 50%` → Don't cache (low hit rate)

## Decision Matrix

| Delta P90 | I1 Change Rate | Strategy | Improvement | Complexity |
|-----------|----------------|----------|-------------|------------|
| < 0.05% | Any | Aggressive filtering | 20x | Low |
| < 0.10% | Any | Standard filtering | 10x | Low |
| > 0.10% | < 30% | Incremental (I1) | 3-5x | Medium |
| > 0.10% | > 30% | Parallelization | 10x | High |

## Example Output

```
=== OVERALL DELTA DISTRIBUTION (95382 bars) ===

50% of bars move < 0.0123%
75% of bars move < 0.0456%
90% of bars move < 0.0891%
95% of bars move < 0.1234%
Mean: 0.0456%

=== RENAISSANCE RECOMMENDATION ===

✓ DELTA-BASED FILTERING recommended
  → Filter out bars with < 0.09% change (catches 90% of noise)
  → Expected reduction: 90% fewer bars to process
  → Throughput improvement: 10x (without code changes)

=== INFORMATION RATE BY TIER ===

I1: 23.4% change rate (median: 21.5%, P75: 28.3%, P90: 35.1%)
I7: 45.6% change rate (median: 43.2%, P75: 52.1%, P90: 61.8%)

=== RENAISSANCE RECOMMENDATION ===

✓ INCREMENTAL COMPUTATION recommended for I1
  → Cache I1 outputs (only 23.4% change rate)
  → Expected cache hit rate: 76.6%
  → Throughput improvement: 4.3x (without parallelization)

=== OVERALL STRATEGY ===

RECOMMENDATION: Incremental computation
→ Implement output caching for low-change-rate tiers
→ Defer parallelization until caching is proven insufficient
```

## Next Steps

1. **Run Phase 0 profiling** - Let data drive the decision
2. **Implement recommended strategy** - Start with simplest fix
3. **Measure improvement** - Verify throughput increased
4. **Iterate if needed** - Try secondary strategies if primary insufficient

## Troubleshooting

**No data available:**
```bash
# Check if intelligence_features has data
docker exec timescaledb psql -U postgres -d indicagent -c "SELECT COUNT(*) FROM intelligence_features;"

# Check if market_data_ohlcv has data
docker exec timescaledb psql -U postgres -d indicagent -c "SELECT COUNT(*) FROM market_data_ohlcv WHERE timeframe = '1m';"
```

**Permission errors:**
```bash
# Make scripts executable
chmod +x production/scripts/*.py
```

**Import errors:**
```bash
# Ensure running from project root
cd /home/bg/dev/indicagent

# Or use PYTHONPATH
PYTHONPATH=/home/bg/dev/indicagent .venv/bin/python production/scripts/phase0_profile_pipeline.py
```

## Files

- `phase0_profile_pipeline.py` - Main entry point (run this)
- `measure_delta_distribution.py` - Delta distribution measurement
- `measure_information_rate.py` - Information rate measurement
- `README_PROFILING.md` - This file
- `phase0_results.json` - Output (generated after running)

## Thread Pool Benchmark (Phase 58)

Benchmarks `ThreadPoolExecutor` pool size for the intelligence pipeline's
`asyncio.gather` + `run_in_executor` pattern.

### How to run

```bash
.venv/bin/python production/scripts/benchmark_thread_pool.py > benchmark_results.csv
```

### Pool sizes tested

[28, 48, 64, 96, 128] — covers range from slightly above CPU count (24) to 5x.

### Interpreting results

- `bars_per_sec` = primary metric (higher is better)
- Look for the "knee" — the pool size after which throughput plateaus
- Set `INTELLIGENCE_THREAD_POOL_WORKERS=<optimal>` in `.env`
- If results are flat, default (`cpu_count * 2 = 48`) is fine

### Results

_(Run benchmark and paste CSV output here)_
