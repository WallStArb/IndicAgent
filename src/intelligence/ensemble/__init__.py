"""
Ensemble math library: shrinkage covariance, IC shrinkage and mean-variance weights.

Pure functions only, Ring 1 domain module. No DB imports, no Kafka imports.

The package holds three modules, `covariance`, `shrinkage` and `weights`, consumed by
`src/intelligence/portfolio/weighting.py` (and through it the research package).
Importers use the submodules directly; this init imports nothing, so loading one
submodule loads no other. The old-chain modules (`alpha_score`, `feature_selector`,
`stratum_fit`) were deleted in phase 186 plan 19.
"""
