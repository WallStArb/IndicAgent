---
status: pending
priority: P1
filed: 2026-07-22
source: found alongside todo 168 (7 symbols with zero non-null per-symbol HMM regime
  labels) -- that todo fixes the specific symbols; this todo is the missing systemic
  check that let the gap go undetected for years in the first place.
---

# No monitor checks that every corpus symbol has ANY per-symbol HMM regime coverage

## What's wrong

Todo 168 found 7 symbols (`LQD`, `PFF`, `RSP`, `USMV`, `UUP`, `VWO`, `XRT`) with
`feature_vectors.regime` NULL for 100% of rows -- `regime_writer.py`'s per-symbol HMM has
never labeled them, silently, for as long as those symbols have been in the corpus. This
was found by accident, during an unrelated investigation (Task 4 live verification of the
symbol_hmm dual-write restoration fix) -- nothing in the pipeline would have surfaced it
otherwise.

Checked the existing monitoring design against this specific failure mode and confirmed
the gap is real, not just unbuilt:
- `DistributionDriftMonitor` (Phase 149A design, `docs/research/intel-14-integrity-monitor.md`)
  watches `feature_vectors` column *distributions* for corruption -- it explicitly treats
  regime as a conditioning variable to avoid false alerts across regime transitions. A
  symbol with 100% NULL regime never trips a distribution check because there's no
  distribution to compare against; it's just silently absent.
- The deferred todo [036](../deferred/036-regime-model-integrity-monitor.md)
  (RegimeModelIntegrityMonitor) checks a *different* failure mode: whether the HMM refit
  respects the causal boundary and whether the chosen seed is stable. It assumes a symbol
  HAS labels and checks whether they were computed correctly -- it does not check whether a
  symbol has ANY labels at all. Confirmed by reading its full scope before filing this as a
  separate item rather than folding it in.

This is a "silent wrong answer" by this project's own principles: not a crash, not a
degraded metric anyone was watching, just complete absence for an unbounded amount of time.
The same failure shape (a per-symbol computation stage that can silently no-op for some
symbols, forever, undetected) is a systemic risk, not a one-off -- worth asking whether
other per-symbol pipeline stages have the same blind spot before assuming this is isolated
to `regime_writer.py`.

## Fix direction

A minimal version needs no new infrastructure -- this is one query, run periodically:

```sql
SELECT symbol, count(*) AS total_rows, count(regime) AS non_null_regime_rows
FROM feature_vectors GROUP BY symbol HAVING count(regime) = 0;
```

Any non-empty result is a canary that should always be empty -- alert-worthy the moment it
isn't, same pattern as `integrity_regime_model_causal_violation_total` in todo 036's design.
Does not need to wait on Phase 152's shared `IntegrityMonitor` infra to exist -- could ship
as a standalone check now (e.g. in `BarAuditor`'s cadence, or a small dedicated script) and
be folded into the shared monitor service later when 036 builds it, rather than gating a
zero-infrastructure check on unrelated infra that hasn't shipped.

Consider generalizing beyond `regime` once this ships: are there other per-symbol
`feature_vectors` columns (or other tables' per-symbol computed columns) that could exhibit
the same "100% null, nobody's watching" failure mode? Worth a quick audit, not a full
redesign.

## References

- [168](168-seven-symbols-zero-per-symbol-hmm-regime-labels.md) -- the specific data gap
  this monitor would have caught years earlier
- [036](../deferred/036-regime-model-integrity-monitor.md) -- adjacent monitor, different
  failure mode (causal-fit correctness, not coverage completeness), read in full before
  filing this as separate
- `services/regime_writer.py` -- the writer whose silent gap this monitor would detect
