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

## Root cause (2026-07-24, live-verified, not two lines of the same bug)

Ran `regime_writer.py --symbols <SYM> --tf 1d` directly for 3 of the 7 and read
`logs/regime_writer.log`'s `degenerate_model_skipped` events. **Not one root cause --
two distinct failure shapes bundled under the same 100%-NULL symptom:**

| Symbol | min_fraction | Occupation across 5 states | Shape |
|---|---|---|---|
| LQD | 0.0472 | 0.259 / 0.189 / 0.222 / **0.047** / 0.283 | **hairline near-miss** — all 5 states genuinely populated, one state at 4.72% vs a 5% floor |
| USMV | 0.0436 | 0.199 / **0.044** / 0.262 / 0.293 / 0.203 | same shape — near-miss, not collapse |
| PFF | **0.0** | 0.293 / 0.385 / 0.036 / 0.287 / **0.000** | **true degenerate collapse** — one of 5 states never occurs at all |

`feature.hmm.min_state_occupation=0.05` is `[initial_estimate]` (confirmed via
`config_schema.description`) -- **never checked against its own occupation-fraction
distribution corpus-wide**, the exact same failure pattern already found and documented
for `equity_regime_model`'s vix/breadth cut-points (todo 092). LQD/USMV look like real
victims of an uncalibrated threshold, not genuinely unlabelable instruments.

PFF is different in kind, not degree: a literal zero-occupation state is not a threshold
question, it's evidence that a fixed `K=5` doesn't fit this instrument's actual dynamics
(preferred shares trade more like credit/bond hybrids -- plausibly genuinely
lower-regime-complexity than K=5 assumes). This is the same "K=4, per-symbol params"
question already flagged as deferred in the original HMM design decisions -- worth
reopening specifically for instrument types like this rather than forcing one global K
onto every symbol.

(RSP/UUP/VWO/XRT not yet run individually -- a batch loop timed out mid-run this session;
the pattern above is enough to know the fix branches by symbol, not a single global
threshold change.)

## Compression wall was the real root cause for most of these 7 -- and for 7 MORE never previously known (2026-07-24)

Built the todo-169 coverage monitor and it immediately found **14 symbols**, not 7: the
original list plus `DIA`, `EFA`, `FXI`, `FXY`, `GLD`, `IWM`, `SPY` -- including the literal
benchmark index ETFs. Root cause: `feature_vectors`' entire hypertable (all 83 chunks,
including the currently-active one) was compressed, despite a stated `compress_after=6
months` policy that no other hypertable in the system uses (everywhere else: 7-30 days).
`regime_writer.py`'s `UPDATE ... SET regime` against a compressed chunk is catastrophically
slow -- confirmed directly: SPY's model fit fine (`converged: true`) but the write didn't
finish inside 180s isolated, with zero other contention. Decompressed the whole table
(83/83 chunks, ~20GB, trivial against 742GB free) -- SPY's 1d write then completed in 7.4s,
all 4,780 rows, zero remaining nulls; SPY's 5m (390,387 rows) converged and wrote cleanly
in 257s (real compute cost, not a bug).

**Root cause of the compression closed for good, no more open question:** `compress_after=6
months` is NOT misconfigured and is NOT the mechanism that compressed the active chunk --
`production/migrations/201_feature_vectors_float32.sql` did. That migration (a legitimate,
well-reasoned float64->float32 storage change) HAD to decompress every chunk to run
`ALTER COLUMN TYPE` (TimescaleDB refuses that op on compressed chunks), and its own tail
deliberately recompresses every chunk afterward as a separate statement -- including
chunks the normal 6-month policy would have left alone. This was a correct migration with
an unflagged side effect, not a recurring bug -- the ongoing 12h policy job will behave
normally going forward and should not prematurely recompress young chunks again unless a
future migration does the same decompress-all/recompress-all pattern. Worth a one-line note
in this project's migration conventions (decompress-driven migrations should flag if any
backfill tool has in-flight work before recompressing), not a code fix. **This means most of the original 7 (and all 7 newly
found) were never a modeling problem at all** -- LQD/PFF/USMV happened to ALSO fail their
own, separate, real gate (see below), which is why they still show null after
decompression; the other symbols may simply need a normal run now that the write path
works. Full incident/cleanup detail (a self-inflicted lock pileup from overlapping test
invocations, safely resolved via `pg_terminate_backend`, zero data damage) recorded in
session context, not repeated here.

## Occupation-threshold recalibration check: 0.05 is NOT obviously miscalibrated (correction)

Before assuming `min_state_occupation=0.05` was simply an uncalibrated guess (the initial
hypothesis), pulled the actual corpus-wide distribution from the 198 (symbol, tf) cells that
have ALREADY succeeded: worst observed min-occupation across all of them is **0.0502** --
essentially sitting exactly at the current floor, with p05=0.0558, median=0.0826.
**Every single successful fit in the whole corpus clears 0.05 by a narrow-to-comfortable
margin; none sit meaningfully below it.** This means 0.05 is not an arbitrary, badly-guessed
threshold the way todo 092's cut-points were -- it looks empirically reasonable. LQD
(0.0472) and USMV (0.0436) are genuinely at or past the tail of what real, trustworthy fits
look like, not clear victims of a bad floor. **Revise: don't lower the threshold.** Treat
LQD/USMV the same way as PFF's true collapse -- candidates for a per-symbol `n_components`
reduction (K<5), not a global floor change.

## Final closure (2026-07-24) — all 14 symbols individually re-tested, disposition complete

Ran every one of the 14 gap symbols across all 4 tf post-decompression:

**Fully fixed (compression was the only problem):** `DIA`, `GLD`, `IWM`, `SPY` — all 4 tf
clean, converged, populated.

**Partially fixed — `1d` (and often more) now clean, specific intraday cells remain
genuinely degenerate:** `EFA` (1h), `FXI` (1h), `FXY` (15m — severe collapse,
min_fraction~0.00008 — and 1h), `RSP` (15m/1h/5m), `UUP` (15m/5m — 5m is a true collapse,
2 of 5 states never occur), `VWO` (5m), `XRT` (5m).

**Never a compression problem, still fully null at every tf:** `LQD`, `PFF`, `USMV`.

**Tested and ruled out as the cause of the remaining 23 degenerate cells** (don't
re-investigate):
- `min_state_occupation=0.05` miscalibration — corpus-wide check across 198
  already-successful cells shows the worst successful fit is 0.0502, right at the floor.
- `min_hold_bars` smoothing — called `_compute_symbol_tf` directly (real function, zero
  DB writes) at `min_hold_bars` in {1,2,3,5} against `RSP/5m`, `FXY/15m`, `UUP/5m` — zero
  effect on any of them, still degenerate at every value tested.

**Verdict:** the remaining pattern (near-universal success at `1d`, failures concentrated
at intraday tf, for lower-beta/mean-reverting instrument types) reads as a genuine limit
of applying one uniform K=5 trend-state HMM at high frequency to instruments that likely
don't have 5 well-separated intraday regimes — not a bug, not a miscalibrated threshold,
not a smoothing artifact. Building per-symbol K override infrastructure for a bounded,
fully-identified set of ~10 symbols is not proportionate — documented as a reasoned,
explicit exclusion directly in `regime_writer.py`'s module docstring instead, so the next
person who notices these gaps doesn't re-investigate from scratch.

**Status: CLOSED.** Coverage monitor (todo 169) ships as a real, tested, deployable
artifact (`services/regime_coverage_auditor.py` + systemd unit files) so any FUTURE
regression of this class is caught immediately rather than by accident.

## Fix direction (superseded by Final closure above, kept for history)

1. **Do not fix by uniformly lowering `min_state_occupation`.** That would let PFF's
   genuine zero-occupation state through silently -- exactly the "silent wrong answer"
   this gate exists to prevent.
2. Pull the occupation-fraction distribution for `min_state` across the WHOLE corpus
   (all symbols, not just these 7) before picking any new floor -- same
   "validate against the real distribution, not a guess" methodology todo 092 already
   established for the sibling cut-point problem. This determines whether 0.05 is even
   in a reasonable range, or needs to move (in either direction).
3. For near-miss symbols (LQD/USMV-shaped): recalibrating the floor from step 2 likely
   resolves them for free.
4. For true-collapse symbols (PFF-shaped, and check RSP/UUP/VWO/XRT against this same
   split before assuming they're all one or the other): investigate a lower per-symbol
   `n_components` rather than forcing K=5 -- reopens the deferred "per-symbol K" question
   from the original HMM design decisions, scoped narrowly to instruments that
   demonstrably can't support 5 states rather than a corpus-wide K change.
5. Once resolved (either direction, per symbol), backfill `feature_vectors.regime` for
   whichever symbols get real labels, and document any symbol that legitimately can't
   support K=5 as a reasoned, explicit exclusion -- not a silent gap.

## References

- `services/regime_writer.py` -- the per-symbol HMM writer this gap traces to
- `.superpowers/sdd/progress.md` (worktree `restore-symbol-hmm-ic-measurement`) -- Task 4's
  live verification notes, where this was found
- Sibling gap: [167](167-equity-cross-sectional-vs-symbol-hmm-never-falsifier-tested.md)
  (equity's cross-sectional-vs-symbol-hmm decision never falsifier-tested) -- if that
  todo's fix direction 1 (build an equity D-05-equivalent gate) is ever pursued, this
  gap must be resolved first for `RSP`/`USMV`/`XRT` (the 3 of these 7 that are
  equity-routed), or the gate will silently exclude them rather than genuinely testing them
