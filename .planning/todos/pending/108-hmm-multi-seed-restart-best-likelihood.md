---
status: pending
priority: P2
filed: 2026-07-12
source: todo 026 P2a, split out after verifying it's the one item in 026 with no
  fork and no fix landed anywhere else
---

# Multi-seed HMM restart, keep best log-likelihood (todo 026 P2a)

**Restart mechanism built 2026-07-31** — `alpha.hmm.n_restarts` APR key (migration 277,
default 1, byte-identical to prior single-seed behavior at default) and the multi-seed loop
in `regime_writer.py` are in, with tests proving both the default-preserving property and
best-log-likelihood selection on synthetic seeds. Remaining scope: the empirical
before/after validation (log-likelihood + label-agreement delta on a few real symbols) and
any corpus-wide rollout decision — deliberately not attempted here, needs live corpus
compute time this session avoided touching.

## Gap

`regime_writer.py:513-547` fits `GaussianHMM` with a single fixed seed
(`alpha.hmm.random_state`, APR default 42). On EM non-convergence it retries **once, same
seed, doubled `n_iter`** (`retry_model` at line 531) — this is a convergence retry, not a
multi-seed-restart-and-keep-best-log-likelihood strategy. GaussianHMM's EM objective is
non-convex; a single seed (even a converged one) can land in a worse local optimum than a
different seed would find, and there is currently no way to know whether that's happening.

No seed-stability check exists either (the related, but distinct, todo 034 secondary
finding): nothing compares label agreement or log-likelihood spread across multiple seeds
to flag a fit as brittle. Note: that specific check is scoped separately, bundled into
todo 026's gated P4a work (rolling refit) and into deferred todo 036's proposed
`RegimeModelIntegrityMonitor` — this todo is narrower, just the fit-time
restart-and-keep-best mechanism itself.

## Proposed scope

Fit with `alpha.hmm.n_restarts` (new APR key, default 3-5) different seeds derived
deterministically from `hmm_random_state` (e.g. `hmm_random_state + i`, keeps the
existing hashlib-safe deterministic-per-symbol RNG property from the HMM improvement
plan), keep the model with the highest converged log-likelihood. Replaces the current
single-retry-on-non-convergence block, not additive to it — the multi-seed loop
subsumes the retry case (a seed that doesn't converge simply loses on log-likelihood
to one that does).

## Not yet done

Nothing built yet. No empirical evidence current single-seed fits are landing in bad
local optima — this is a robustness gap, not a proven bug, so scope any fix to the
restart mechanism itself and measure before/after log-likelihood + label-agreement
delta on a few symbols before rolling out corpus-wide.

## References

- `.planning/todos/deferred/026-hmm-regime-audit-optimization.md` — original P2a finding,
  this todo's source
- `.planning/todos/completed/034-hmm-walk-forward-refit.md` — where the seed-stability
  check idea originated (folded into 026, not the same item as this todo)
- `.planning/todos/deferred/036-regime-model-integrity-monitor.md` — proposed runtime
  monitor that would consume a seed-stability score, once one exists
- `services/regime_writer.py:513-547` — current single-seed fit + convergence-retry code
