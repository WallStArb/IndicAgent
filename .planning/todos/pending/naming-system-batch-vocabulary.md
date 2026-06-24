---
title: Add Batch Compute Category to Naming System Vocabulary B
created: 2026-06-24
source: Renaissance naming audit — BaseBatch pattern has no taxonomy row
priority: low
---

# Context

`BaseBatch` (`src/core/agent/base_batch.py`) is a recognized Ring 2 base class used by
`EnsembleBuilder` and `AlphaEmitter` today, and will be used by all 6 AlphaEngine DAG
nodes after the `batch-pipeline-basebatch-promotion` todo is complete. It has no
corresponding row in Vocabulary B of `docs/foundation/naming-system.md`.

Without a taxonomy row, there is no canonical suffix guidance for batch compute classes,
no I/O contract definition, and no example set — leaving future engineers to invent
suffixes ad hoc (which is how `Builder` and `Emitter` appeared).

---

## Work Item

Add the following rows to Vocabulary B in `docs/foundation/naming-system.md`, after
the `Trainer` row:

```markdown
| `Optimizer` | Constructs a model artifact via mathematical optimization (e.g., covariance optimization, Ledoit-Wolf) | DB → DB (weight artifact) | `EnsembleOptimizer` |
| `BatchWriter` | Reads from DB, computes, and writes results to DB in batch (no Kafka, no daemon loop) | DB → DB | `FeatureVectorBatchWriter`, `ForwardReturnAnalyzer` |
```

Also add a note clarifying the `Writer` suffix is restricted to the streaming path:

> **`Writer` is Kafka → DB only.** For batch DB → DB persistence, use `BatchWriter` or
> the appropriate analytical suffix (`Analyzer`, `Trainer`). A class that reads from the
> database and writes back to the database is not a `Writer` — it is a batch compute node.

Also add `Optimizer` and `BatchWriter` to the disambiguating notes section, clarifying
that these are batch-only (no daemon loop, no Kafka subscription) and always extend
`BaseBatch`, not `BaseDaemon`.

---

## Gate

- `batch-pipeline-basebatch-promotion` complete — so the taxonomy row has live examples
  to reference in the `Example` column
