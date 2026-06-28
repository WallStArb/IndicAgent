---
**Created:** 2026-06-28
**Area:** ml
**Type:** new_feature
**Priority:** P3
**Effort:** 5-7 days
**Benefit:** Enables non-parametric hypothesis testing; bootstrap-based confidence intervals
**Risk:** low (new service, isolated)
**Gate:** None
---

# 017 — Non-Parametric Hypothesis Backtester

**Priority:** Medium — high research leverage; zero new infrastructure.
**Prerequisite:** AnalogEngine (012) retrieval primitive must be built first.

## What

A research tool that points AnalogEngine's K-NN retrieval at an arbitrary query vector and
reads the empirical outcome distribution. Answers "Is this edge real?" without any new
computation layer.

## Why

Current hypothesis testing requires running the full IC pipeline. A researcher with a
candidate feature vector or a regime-filtered query should be able to ask: "Given bars
that look like this, what was the distribution of forward returns?" The AnalogEngine
already does this for production — this just exposes it as an interactive research primitive.

## Scope

1. **Query interface** — accept a partial or full feature vector (dict of feature_name → value);
   L2-normalize; run K-NN against `feature_embeddings` with optional regime filter
2. **Outcome read** — for each neighbor, fetch `forward_return_fast/mid/slow` from
   `forward_returns` at neighbor's (symbol, tf, bar_ts)
3. **Distribution summary** — median, CI lower/upper (bootstrap), n_analogs, OOD flag
   (nearest distance > `alpha.analog.ood_distance_threshold`), regime match fraction
4. **Output** — JSON blob + optional histogram (ASCII or Matplotlib) for notebook use
5. **Entry point** — `production/scripts/analog_backtest.py --query '{"momentum_z_fast": 1.2, ...}'
   [--regime bull] [--tf 1h] [--k 50]`

## Files

| File | Change |
|------|--------|
| `production/scripts/analog_backtest.py` | New script; thin wrapper over AnalogEngine retrieval |
| `src/intelligence/analog_engine.py` | Expose `query(vector, regime, tf, k)` as public method |

## APR Keys

Reuses `alpha.analog.k_neighbors`, `alpha.analog.ood_distance_threshold` — no new keys.

## Success Criteria

- Script returns distribution JSON for a hand-crafted query vector in < 2s
- OOD flag fires when query has no close historical neighbors
- Regime filter reduces n_analogs correctly (verified against raw SQL count)
- Works from a Jupyter notebook via `import subprocess; subprocess.run([...])`
