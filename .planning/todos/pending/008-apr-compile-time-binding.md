# 008 — APR Compile-Time Binding (eliminate per-call hash lookups)

**Priority: Medium — architectural correctness; eliminates 100+ hash lookups per compute call**
**Gate: Before streaming path re-enabled (IntelligencePipeline or FeatureVectorWriter live)**
**Source:** `docs/plans/2026-06-26-renaissance-optimization-roadmap.md` (ARCH-001)

---

## Problem

Every call to `cfg.get_sync(key, default)` in hot paths (ic_engine, ensemble_trainer,
regime_writer) does a hash lookup into the config dict. The ic_engine has ~25 APR keys
read inside worker loops — at 58 symbols × 4 TFs × N iterations, this is thousands of
redundant hash lookups per corpus run.

More importantly: APR keys loaded inside compute loops mean config can silently change
mid-run if config_state is updated externally. The correct semantic is: bind config at
service startup, use it immutably for the entire run.

---

## Fix

For each service with multiple APR keys, define a frozen config dataclass and load once:

```python
@dataclass(frozen=True)
class ICEngineConfig:
    min_observations: int
    fdr_alpha: float
    sharpe_min_windows: int
    subsample_min_stride: int
    cluster_max_corr: float
    regime_purge_bars: int
    # ... all keys

    @classmethod
    def from_apr(cls, cfg: ConfigService) -> "ICEngineConfig":
        return cls(
            min_observations=int(cfg.get_sync("alpha.ic.min_observations", 500)),
            fdr_alpha=float(cfg.get_sync("alpha.ic.fdr_alpha", 0.05)),
            ...
        )
```

Load once in `execute()` before any worker dispatch. Pass as immutable argument into
all worker functions. Zero hash lookups inside workers.

---

## Scope

- `services/ic_engine.py` — ICEngineConfig dataclass, load in execute()
- `services/ensemble_trainer.py` — EnsembleConfig dataclass
- `services/regime_writer.py` — RegimeConfig dataclass
- `services/feature_factory.py` / `backfill_feature_factory.py` — FeatureFactoryConfig (already partially exists)

Pattern already established in FeatureFactory — extend to all batch services.
