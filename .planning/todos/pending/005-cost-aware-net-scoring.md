# 005 — Cost-Aware Net Scoring

**Priority:** Medium — correctness issue at short horizons; should land before any live
trading evaluation of short-TF alpha.
**Scope:** Single transform in the scoring engine; ~1-2 files.

## What

Transform expected gross return E[R] to expected net return E[R]_net by subtracting a
modeled transaction cost (spread + slippage) before consumption by the ensemble and
downstream emitters. At short horizons, gross +0.2R with 0.25R estimated cost is a
losing trade — the ensemble must see net, not gross.

## Why

The scoring engine currently emits gross IC-weighted expected returns. At 5m and 15m
horizons, transaction costs are a non-trivial fraction of the edge. Without net scoring,
the ensemble can emit on signals that are gross-positive but net-negative. This is a
silent wrong answer.

## Design

### Phase 1 — Conservative static estimate (this todo)

```
E[R]_net = E[R]_gross - cost_model(symbol, tf)
cost_model(symbol, tf) = spread_estimate + slippage_estimate
```

- `spread_estimate`: half-spread from last observed bid/ask in `market_data_ohlcv` OHLCV
  fields (or a per-symbol APR default if not available)
- `slippage_estimate`: APR default by asset class (equity ETF vs futures vs FX)
- Apply only where `tf IN ('5m', '15m')` by default (APR: `alpha.scoring.net_cost_tfs`)

### Phase 2 — Calibrate from realized fills (future todo)

After live trading accumulates fills in `trade_executions`, regress `actual_fill_price`
against `expected_fill_price` per (symbol, tf) to produce calibrated slippage estimates.
Phase 2 is out of scope here.

## APR Keys

| Key | Default | Description |
|-----|---------|-------------|
| `alpha.scoring.equity_spread_default_r` | 0.10 | Default half-spread in R units for equity ETFs `[initial_estimate]` |
| `alpha.scoring.futures_spread_default_r` | 0.15 | Default half-spread for futures `[initial_estimate]` |
| `alpha.scoring.fx_spread_default_r` | 0.05 | Default half-spread for FX `[initial_estimate]` |
| `alpha.scoring.slippage_default_r` | 0.05 | Default slippage across all asset classes `[initial_estimate]` |
| `alpha.scoring.net_cost_tfs` | `["5m","15m"]` | TFs where cost transform is applied `[user_preference]` |

## Files

| File | Change |
|------|--------|
| `src/intelligence/scoring_engine.py` | Add `_net_expected_return(symbol, tf, gross_r)` method; apply before emitting score |
| `src/intelligence/ensemble_builder.py` | Consume `net_expected_r` instead of `expected_r` in weight calculation |
| New migration | Insert 5 APR keys into `config_schema` + `config_state` |

## Output Contract

Score Object gains `expected_r_net` alongside existing `expected_r_gross`. Downstream
consumers use `expected_r_net`. `expected_r_gross` is preserved for diagnostics.

## Success Criteria

- `expected_r_net < expected_r_gross` for all 5m/15m scores
- `expected_r_net` is null for 1h/1d scores (cost not applied at those horizons)
- Ensemble weight calculation uses net values; verified against ad-hoc SQL
- APR keys appear in `/config/parameters` dashboard
