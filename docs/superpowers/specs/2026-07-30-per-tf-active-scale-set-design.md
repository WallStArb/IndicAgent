# Per-tf active-scale set for the forward-return lookahead grid

Closes the "structurally removing that tier requires touching `ic_engine.py`'s fixed
`_SCALES`-indexed compute loops (deferred to a separate follow-up todo)" gap
`LOOKAHEAD_FALLBACKS_BY_TF`'s own docstring (`services/_batch_utils.py`) has named since
todo 146 landed. Directly informed by, but explicitly decoupled from, todo 208's still-open
investigation into whether the same-ET-session completeness gate should exist at all for
5m/15m/1h.

## Problem

`ic_engine.py`'s `_SCALES: tuple[str, ...] = ("fast", "mid", "slow", "extended")` is a
module-level constant, threaded through 12 call sites (plus its own definition) (loops, `len()` array-sizing, SQL
column-list builders), applied identically to every timeframe. `1h` has zero real
observations for `slow`/`extended` — confirmed live 2026-07-30, `complete_slow`/
`complete_extended` average 0.000 across the entire `forward_returns` table for `tf='1h'`
— yet `config_state` still carries live `alpha.ic.lookahead.1h.slow=20`/`.extended=60`
values with nothing marking them non-functional. `ic_engine` still attempts computation
against these cells; they simply produce no usable rows. This is silent-but-not-wrong
today (no bad data gets written), but it wastes compute and gives a reader of
`config_state` no signal that two of 1h's four "configured" tiers are dead.

Two things must NOT happen as part of fixing this:
1. **No premature methodology verdict.** Todo 208 is actively checking whether removing
   the session gate restores real `slow`/`extended` signal for 1h. If this fix hardcodes
   "1h has 2 tiers" into `_SCALES`'s replacement, it silently pre-answers 208's question
   inside what should be a plumbing change.
2. **No speculative schema expansion.** The diagnostic's own dense per-tf grids
   (`ops_lookahead_horizon_response.py`) top out around 6-9 points for characterization;
   there's no evidence any tf needs more than today's 4 named production tiers. Building
   for unbounded cardinality (a `forward_returns` row-per-horizon renormalization) pays a
   real cost — hypertable row multiplication, and a rewrite of `ic_engine.py`'s vectorized
   numpy compute layer, which reads `return_fast`/`return_mid`/etc. as flat columns
   directly into arrays — for a need that likely doesn't exist at that scale.

## Design — mechanism (ships now, independent of todo 208's outcome)

**New APR key, `alpha.ic.active_scales.{tf}`** — a JSON list of scale names ic_engine
actually attempts computation for on that tf, e.g. `alpha.ic.active_scales.1h =
["fast", "mid"]`. `alpha.ic.lookahead.{tf}.{scale}` (the bar-count values, all 16 keys)
are untouched — the metadata stays even for excluded scales, only whether `ic_engine`
computes against them changes. Loaded via `_batch_utils.cfg()`'s existing list-default
path (todo 187's fix already makes this safe — `json.loads` on a JSON-array APR value,
no new infrastructure).

**This is a factual/derived state, not a permanent commitment.** `active_scales.1h`
excludes `slow`/`extended` today because that's what `forward_returns`'s live
completeness says, not because of a judgment call about whether it should be that way
forever. The moment todo 208's Step 2 changes what's measurable, updating
`active_scales.1h` is a one-line `config_history`-audited config change — no code
touches this decision again. This is the whole point of putting it in APR rather than a
Python literal.

**Shared resolver, `_batch_utils.active_scales_for_tf(tf, cfg) -> tuple[str, ...]`**,
adjacent to the existing `lookaheads_for_tf` — same shared-resolver pattern
(`ICEngineConfig`/`EnsembleICConfig` both call it, stay independent frozen+picklable
dataclasses per existing constraint). Default table
`ACTIVE_SCALES_FALLBACKS_BY_TF: dict[str, tuple[str, ...]]` lives next to
`LOOKAHEAD_FALLBACKS_BY_TF` for the same single-source-of-truth reason; seeded today as
`{"5m": (fast,mid,slow,extended), "15m": (...), "1h": (fast,mid), "1d": (...)}`.

**12 call sites in `ic_engine.py`:** replace the module-level `_SCALES` reference with
`active_scales_for_tf(tf, cfg)` at each site (`enumerate(_SCALES)` loops, `len(_SCALES)`
array-sizing, `f"return_{s}" for s in _SCALES` column-list builders) — every one already
runs inside per-`tf` scope, confirmed by direct inspection; none require a shared width
across timeframes, so this is mechanical substitution, not a restructure.

**Fingerprint correctness — `ICEngineConfig` gains a new field, `active_scales: dict[str,
tuple[str, ...]]`** (same shape convention as the existing `lookahead_fast: dict[str,
int]` field), added to `_COMPUTATIONAL_CONFIG_FIELDS`
(`_compute_apr_snapshot_key`'s classification set) alongside the existing
`lookahead_fast/mid/slow/extended` entries. **No new test needed for the
"forgot to classify a new field" failure mode** — `test_ic_engine_fingerprint.py`
already asserts `_COMPUTATIONAL_CONFIG_FIELDS ∪ _OPERATIONAL_CONFIG_FIELDS` partitions
`dataclasses.fields(ICEngineConfig)` exactly; leaving the new field unclassified fails
that test loudly by construction. This is the single most important correctness
property of the whole change: a stale fingerprint would silently skip recomputing a
cell whose active-scale set just changed, treating it as "already correct" under the
old shape.

**Compute-skip for excluded scales, not silent-empty-attempt.** Today, `ic_engine`
attempts IC computation against 1h's `slow`/`extended` and gets nothing back (0% valid
N). Post-fix, `active_scales_for_tf` excludes them entirely — this changes zero rows in
`feature_ic_scores` (an attempt against 0% completeness already produces no row) but
removes real, currently-wasted compute (fewer cells × fewer scales × 249 features × CI
computation, across every 1h symbol/regime cell in every corpus run).

**Downstream sweep — not `ic_engine.py` alone.** Todo 202 already found
`ops_ic_shrinkage.py`'s global bars→scale reverse map broken under a per-tf grid; the
same defect class applies here. Audit before landing: `ops_ic_shrinkage.py`,
`ensemble_ic_engine.py`'s EIC-02 `_calibrate_hold_max_bars` decay walk (does it assume
exactly 4 scales per tf?), and anything rendering `alpha.ic.lookahead.*`/
`alpha.ic.active_scales.*` (dashboard `/config/parameters`, if it enumerates scales by a
hardcoded list rather than reading the APR keys present). Per CLAUDE.md's "file/class
rename requires a grep sweep" rule — `grep -rn "_SCALES\b" services/ src/ scripts/
tests/` at implementation time, not just the sites found during this design pass.

## Design — values (explicitly deferred, not decided by this spec)

`active_scales.1h = ("fast", "mid")` is the only value change this spec makes, and it's
justified purely by today's measured 0.000 completeness — not a prediction about 208's
outcome. `5m`/`15m`/`1d` keep all four scales active (unchanged from today). If todo 208
Step 2 lands and 1h's `slow`/`extended` completeness becomes nonzero, updating
`active_scales.1h` back to include them is the *entire* required change — no code, no
migration, no second design.

## Rejected alternatives

**Widen `forward_returns` to 6-8 named columns speculatively.** Moves the hardcoded
ceiling without removing it, and worsens naming clarity (a slot name stops meaning the
same bar-count-relative-position across tfs once cardinality varies). Rejected — no
evidence any tf needs more than 4 today.

**Normalize `forward_returns` to one row per `(symbol, tf, bar_ts, horizon_bars)`.**
Textbook-correct for genuinely unbounded cardinality, and it's the shape
`feature_ic_scores` already uses (`lookahead_bars` as an explicit column) — but it
multiplies row count on an already-35M-row hypertable and forces a rewrite of
`ic_engine.py`'s vectorized numpy compute (currently pulls `return_fast`/`return_mid`/
etc. straight into arrays; a long format needs a pivot/JOIN at every read site).
Rejected as solving a cardinality problem (potentially dozens of horizons) that the
actual evidence (diagnostic grids topping out at 6-9 points, and those for
*characterization*, not necessarily all needed in production) doesn't support paying
for.

**Escape hatch, not built now:** if todo 208 or a future finding proves some tf
genuinely needs a 5th/6th named production tier, the additive fix is one
`ALTER TABLE forward_returns ADD COLUMN return_xlong ...` + one new qualifier name +
extending `active_scales_for_tf`'s vocabulary — small, backward-compatible (existing
rows get NULL), not a renormalization. Documented here so a future implementer doesn't
default to the long-format rewrite out of not knowing a cheaper path exists.

## Sequencing — interaction with the in-flight corpus pipeline

The corpus rebuild pipeline launched 2026-07-30 (`regime_writer → forward_return_writer
→ cross_sectional_regime_model → ic_engine`) is currently paused before step 5
(`ic_engine`), intercepted deliberately pending todo 208's Step 1 empirical check.
**This mechanism should land before that pipeline resumes, not after** — `ic_engine` is
an hours-long run; resuming it now under the old global `_SCALES`, then redoing it again
once this mechanism ships, wastes a full corpus pass for no reason. Todo 208's Step 1
(`ops_lookahead_horizon_response.py --allow-overnight`, a separate read-only diagnostic)
can run independently in parallel with implementing this mechanism — they don't block
each other, but both should land before `ic_engine` resumes for the real run, so the
corpus gets computed once under final logic.

## Out of scope

- Todo 208 Step 2 itself (removing the session gate in `forward_return_writer.py`) —
  separate plan, gated on Step 1's empirical result.
- Building the 5th/6th-tier schema escape hatch — only if a future finding demonstrates
  the need; not speculative work now.
- A `regime_coverage_auditor.py`-style automated auditor to keep `active_scales` in sync
  with live completeness going forward (currently hand-set via migration) — worth
  considering later, not required for this fix to be correct.

## Testing

- Unit tests for `active_scales_for_tf` resolution (default fallback, APR override, both
  `ICEngineConfig`/`EnsembleICConfig` call paths) — mirrors existing `lookaheads_for_tf`
  test pattern.
- `test_ic_engine_fingerprint.py`'s existing partition-completeness assertion covers the
  new `active_scales` field automatically once added to `ICEngineConfig` — verify it
  fails if classification is (deliberately, for the test) omitted, then confirm it
  passes once classified correctly.
- Regression test: two `ICEngineConfig` instances differing only in `active_scales`
  produce different `_compute_apr_snapshot_key` output.
- Grep-based boundary test (same pattern as `test_market_data_ohlcv_boundary.py`'s
  allow-list) asserting no remaining bare `_SCALES` references outside
  `active_scales_for_tf`'s own definition — prevents a future hardcode from silently
  reintroducing the fixed-4-uniform assumption.
- Live verification once merged: confirm 1h's `ic_engine` cells for `slow`/`extended`
  are skipped (not attempted-and-empty) via a scoped `--symbols`/`--tf 1h` throwaway run,
  compare wall-clock/row-count against a pre-fix baseline.

## References

- `.planning/todos/pending/146-lookahead-grid-per-tf-recalibration.md`,
  `.planning/todos/pending/208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md`,
  `.planning/todos/pending/202-per-tf-lookahead-grid-downstream-consumers-stale.md`
- `services/_batch_utils.py` — `cfg()`, `LOOKAHEAD_FALLBACKS_BY_TF`, `lookaheads_for_tf`
  (the exact pattern this design extends)
- `services/ic_engine.py` — `_SCALES` (12 call sites + definition), `_COMPUTATIONAL_CONFIG_FIELDS`/
  `_compute_apr_snapshot_key` (Phase 162 fingerprint mechanism)
- `tests/unit/test_ic_engine_fingerprint.py` — existing partition-completeness guard
- CLAUDE.md APR mandate, "Behavioral lists" category — JSON-typed APR values
