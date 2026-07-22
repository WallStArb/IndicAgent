---
status: pending
priority: P1
filed: 2026-07-22
source: found during Task 4 live verification of the symbol_hmm restoration fix
  (worktree restore-symbol-hmm-ic-measurement) -- ic_engine.py's dual-write pass
  correctly computed zero symbol_hmm cells for LQD/PFF (2 of the 12 rates-group
  symbols scoped in that verification run) because their per-symbol HMM regime
  label is null for every single bar. Checking corpus-wide surfaced 5 more
  symbols with the identical gap.
---

# 7 corpus symbols have zero non-null per-symbol HMM regime labels -- `regime_writer.py` has never labeled them

## What's wrong

`feature_vectors.regime` (the per-symbol HMM label, written by `regime_writer.py`) is
NULL for 100% of rows for **7 symbols**: `LQD`, `PFF`, `RSP`, `USMV`, `UUP`, `VWO`, `XRT`.
Verified live 2026-07-22:

```sql
SELECT symbol, count(*) AS total_rows, count(regime) AS non_null_regime_rows
FROM feature_vectors GROUP BY symbol HAVING count(regime) = 0 ORDER BY symbol;
```
returns exactly these 7 symbols, all with `non_null_regime_rows = 0`.

This is not a data-sparsity artifact -- all 7 have decades of bar history (e.g. `LQD`
2006-2026, `RSP`/`VWO`/`XRT` also from 2006), more history than several symbols
(`TLT` included, 2016-2026) whose per-symbol HMM labels compute fine. Something about
`regime_writer.py`'s HMM fit or invocation is failing or being skipped for these 7
specific symbols -- not root-caused further here (out of scope for the investigation
that found this).

**Downstream consequence, concretely observed:** any `ic_engine.py` dual-write pass
targeting a regime-group-routed symbol among these 7 (currently none are, since `rates`
is the only group with `dual_write_symbol_hmm=true` and none of these 7 are `rates`-tagged
-- but this will bite the moment `equity`'s analogous question, todo 167, is ever
resolved toward dual-write, since some of these 7 -- `RSP`, `USMV`, `XRT` -- are
equity-routed) will silently compute zero `symbol_hmm` cells for that symbol, not because
routing or dual-write logic is wrong, but because there is no regime label at all to
condition on. The dual-write mechanism handles this correctly today (empty label set ->
zero iterations, no crash, no fabricated data) -- but it is a symptom that the underlying
per-symbol HMM measurement is silently absent for these symbols regardless of any regime
routing question, which is a real, independent data-completeness gap.

## Fix direction

Not investigated here -- needs its own root-cause pass:
1. Check whether `regime_writer.py` has ever been run with these 7 symbols in scope
   (`python services/regime_writer.py --symbols LQD PFF RSP USMV UUP VWO XRT`) and
   whether it errors, silently skips, or writes null by design for some symbol
   characteristic these 7 share (e.g. HMM convergence failure, insufficient variance,
   a data-quality gate rejecting all their bars).
2. Check `regime_writer.py`'s logs (not present in `logs/regime_writer.log` as of this
   filing -- may need a fresh run with logging enabled, or logs may have rotated) for
   any historical error signal.
3. Once root-caused, either fix the underlying issue and backfill these 7 symbols'
   `feature_vectors.regime`, or if there's a legitimate reason these symbols can't be
   HMM-labeled (e.g. `PFF`'s preferred-share character makes trend-state HMM
   inapplicable), document that as an explicit, reasoned exclusion rather than a silent
   gap discovered by accident.

## References

- `services/regime_writer.py` -- the per-symbol HMM writer this gap traces to
- `.superpowers/sdd/progress.md` (worktree `restore-symbol-hmm-ic-measurement`) -- Task 4's
  live verification notes, where this was found
- Sibling gap: [167](167-equity-cross-sectional-vs-symbol-hmm-never-falsifier-tested.md)
  (equity's cross-sectional-vs-symbol-hmm decision never falsifier-tested) -- if that
  todo's fix direction 1 (build an equity D-05-equivalent gate) is ever pursued, this
  gap must be resolved first for `RSP`/`USMV`/`XRT` (the 3 of these 7 that are
  equity-routed), or the gate will silently exclude them rather than genuinely testing them
