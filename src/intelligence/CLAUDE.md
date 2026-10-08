# Intelligence layer (Ring 1)

Domain code: pure functions over arrays, state at the edges. Ring rule, naming and the research invariants are in the root `CLAUDE.md`; this file lists what lives here now.

## Live (v3.5)

| Package | What it is |
|---|---|
| `bars/` | Pure bar-integrity modules (scrub rules, seam detection, d2-v2 daily derivation types, verdict gate, D0 labels). |
| `research/` | The research DAG (S0 snapshot to S8 book test), runner, panel kernel (`panel.forward_returns`), spec. Edits here require `repro_frozen` to report bit-identical. |
| `statistics/` | Test statistics, StepM and the shared numeric kernels. Same `repro_frozen` rule. |
| `measure/` | The fresh IC engine's three jobs as pure functions: proposer, IC term structure, member monitoring. |
| `ensemble/` | Shrinkage covariance, IC shrinkage and mean-variance weights. |
| `portfolio/` | Instrument-level portfolio construction primitives. |
| `regime_signals/` | Signal-type registry for regime modules. |
| `concept_registry_service.py` | UCR; the only writer of a concept status. |

Package docstrings in each `__init__.py` are the source of truth for details.

## v2.x remainder (do not build on it)

`pipeline/`, `plugins/`, `trading/`, `composites/`, `register_plugins.py` and `archive/` stay only because `services/feature_vector_pipeline.py` imports `src.intelligence.pipeline`, whose `__init__` pulls in the executor and the plugin tier. Todo 509 trims that import and frees the rest. The I1-I7 signal path, the typed bus and the I8 AI stack were removed in plan 185-45; the archive is the local git tag `archive/v2x-ai-stack-2026-10` and `data/backups/185-45/` (kept until about 2026-11-06). The pre-removal text of this file, including the plugin protocol, the LLM provider chain and the Ollama rules, is in git history at the tag.
