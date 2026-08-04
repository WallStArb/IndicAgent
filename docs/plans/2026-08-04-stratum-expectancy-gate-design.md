# `stratum_expectancy_gate` — Reusable Regime×Direction Expectancy Gate Design

**Goal:** Extract the day-clustered bootstrap gate machinery (`frame_gate_passes`/
`evaluate_frame_gate`) out of `services/counterfactual_tracker.py` into a proper Ring 1
shared module, and add one small, named, tested specialization —
`evaluate_stratum_expectancy_gate` — that answers a single question: does a given
(regime × direction) stratum have a statistically valid, non-zero expected value, or is
it noise?

**Non-goal:** wiring this into `alpha_publisher.py`, any construction, or any live
emission path. This spec covers a pure, reusable statistical primitive only. Per
CLAUDE.md's "prove edge before production infra," a construction earns the right to be
gated by this — the gate does not go looking for a construction to attach to.

---

## Background

Todo 179 (`.planning/todos/completed/179-gate166-concurrent-exposure-diagnostic.md`,
filed 2026-07-23, closed 2026-07-31) diagnosed why Phase 166's frame-recalibration
candidates both failed Gate 2. After multiple rigor passes (concentration-aware sizing,
single-symbol isolation, raw-barrier-free forward returns, a 234-cell joint sweep across
9 cross-sectional regimes × 6 symbol_hmm states × 3 scales, and historical replication
back to 2006), the investigation concluded: **zero regime/direction slice in the
per-symbol directional construction shows a real, replicating, non-circular positive
expectancy.** The one candidate that looked promising (`low_bull` × `trending_down`)
failed to replicate out-of-window and failed even in its own discovery window once
`alpha_score > 0` conditioning was removed. The project moved to a different
construction (Phase 167, `cross_sectional_relative_value`) rather than continuing to
chase a regime-conditional fix for the abandoned one.

Todo 179's own text poses the code-level question this design answers: *"does
`ensemble_trainer.py`'s regime-stratified weight training actually suppress firing... or
is there no expectancy floor at emission time at all?"* Reading `alpha_publisher.py`'s
emission query directly (2026-08-03) confirms: there is none. Its `WHERE` clause filters
on `effective_n`, a per-timeframe `alpha_score` threshold, and a CI/cost-hurdle check —
`regime` is selected but never appears in the predicate. Weight *training* is
regime-conditioned (`ensemble_weights` is keyed by `(symbol, tf, regime, weight_version,
feature_name)`); emission is not.

Because todo 179 already closed with a definitive null result, wiring a fix into
`alpha_publisher.py` today has nothing real to gate. What's still missing, independent of
that specific construction's fate, is a **reusable, tested, named primitive** for the
question todo 179 had to answer by hand with a scratchpad script every time it came up.
Building that now — decoupled from any specific consumer — means the next construction
that needs this check (whatever it turns out to be) does not re-derive it ad hoc.

### Why this is an extraction, not new statistics

The day-clustered bootstrap gate this needs already exists and is already fully generic:

- `frame_gate_passes()` (`services/counterfactual_tracker.py:173`) — day-clustered
  BCa/analytic bootstrap CI on a `(pnl_r_values, cluster_ids)` pair. Returns
  `(passes, ci_lower, ci_upper)`.
- `evaluate_frame_gate()` (`services/counterfactual_tracker.py:921`) — groups rows by an
  arbitrary `group_key` callable and calls `frame_gate_passes` per group. Already used
  two different ways in this codebase: `counterfactual_tracker.py`'s native `(tf,
  regime)` default grouping, and `cross_sectional_spread_tracker.py`'s
  `evaluate_spread_gate()` (`services/cross_sectional_spread_tracker.py:395-444`), which
  calls it with `group_key=lambda row: (row["scale"], row["cost_bps"])` and renames the
  generic `tf`/`regime` output fields to `scale`/`cost_bps`.

There is no new bootstrap math to write. The gap is structural: this generic core is
defined inside a Ring 2 service file it has no domain reason to live in (Ring 2 is for
daemons — `counterfactual_tracker.py` is a `BaseBatch` oneshot, and `frame_gate_passes`/
`evaluate_frame_gate` have zero DB/Kafka/daemon dependencies), and
`cross_sectional_spread_tracker.py` already imports it cross-service
(`from services.counterfactual_tracker import (...)`) — a Ring-2-importing-Ring-2
dependency on what is actually shared statistics. `src/intelligence/statistics/ic_math.py`
already establishes the correct pattern for exactly this situation (explicitly documented
as "the shared Ring-1 extraction point for `ic_engine.py`, `ensemble_ic_engine.py`, and
ops scripts"). This design applies the identical treatment to the gate machinery.

---

## Design

### Module layout

```
src/intelligence/statistics/
    ic_math.py                          (existing, unchanged)
    gate_math.py                        NEW

        frame_gate_passes(...)          moved verbatim from counterfactual_tracker.py:173
        evaluate_frame_gate(...)        moved verbatim from counterfactual_tracker.py:921
        evaluate_stratum_expectancy_gate(...)   NEW — see below
```

Ring 1 (`src/intelligence/`), not Ring 0: `regime` and `direction` are domain vocabulary
(per `docs/foundation/glossary.md`'s `regime` entry), which fails Ring 0's portability
test. `ic_math.py` sits at the same ring for the same reason (IC is a domain-specific
quantitative-finance concept, not portable infrastructure) despite being equally
dependency-free.

### `evaluate_stratum_expectancy_gate`

```python
def evaluate_stratum_expectancy_gate(
    rows: Iterable[Mapping[str, Any]],
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int,
    min_clusters: int | None = None,
) -> list[dict[str, Any]]:
    """Day-clustered bootstrap expectancy verdict per (regime, direction) stratum.

    Each input row carries `regime`, `direction`, `cluster_id` (a calendar date), and
    `pnl_r` (the realized or simulated per-bar return for that stratum). Delegates
    entirely to `evaluate_frame_gate` with `group_key=lambda r: (r["regime"],
    r["direction"])` -- no bootstrap logic is reimplemented here, matching
    `evaluate_spread_gate`'s own precedent in `cross_sectional_spread_tracker.py`.

    Returns one verdict dict per (regime, direction) cell: `regime`, `direction`,
    `n_bars`, `n_clusters`, `ci_lower`, `ci_upper`, `passes`, `coverage`. `passes=True`
    means this stratum's day-clustered bootstrap CI lower bound clears zero -- a
    statistically valid, non-zero expected value, not proof of a tradeable edge on its
    own (n_bars/n_clusters and `coverage` must also be checked by the caller against
    whatever sufficiency floor its own context requires).
    """
```

Field renaming mirrors `evaluate_spread_gate` exactly: `evaluate_frame_gate`'s grouping
core always populates `tf`/`regime` regardless of what was actually grouped by (a
pre-existing, documented constraint — passing a 3-tuple `group_key` raises `ValueError:
too many values to unpack`); this function renames `tf` → `regime`, `regime` →
`direction`, `n_frames` → `n_bars` before returning.

### Explicitly out of scope

- **Row assembly.** How a construction turns its own realized/simulated returns into
  `{regime, direction, cluster_id, pnl_r}` rows is construction-specific integration
  work. Building a generic row-assembly helper now, with no real consumer, means
  guessing at a shape that may not fit whatever construction eventually needs this —
  YAGNI.
- **A persisted verdict table.** `gate_evaluations` exists for construction-level gates
  (`gate166_*`, `gate1_signal`) that have a real run to record. A table for verdicts
  nothing produces yet is infrastructure with no consumer — the same anti-pattern
  "prove edge before production infra" already rules out elsewhere in this codebase.
- **Wiring into `alpha_publisher.py` or any construction.** Not scoped here. See
  Non-goal above.

---

## Consumer migration (mechanical, no behavior change)

`services/counterfactual_tracker.py` and `services/cross_sectional_spread_tracker.py`
both change their import of `frame_gate_passes`/`evaluate_frame_gate` to
`src/intelligence/statistics/gate_math.py`. Neither file's own logic changes. Existing
test suites for both (`tests/unit/test_counterfactual_tracker.py`,
`tests/unit/test_counterfactual_tracker_exit_priority.py`,
`tests/unit/test_cross_sectional_spread_tracker.py`) must pass unmodified — any test that
needs updating indicates the extraction changed behavior, which would be a bug in the
extraction, not an expected side effect.

---

## Testing

- **Equivalence test:** run identical fixture data through the pre-extraction import path
  (captured before the move) and the post-extraction `gate_math` import, assert
  bit-identical output. Same discipline `structural_confluence.py`'s own docstring used
  when porting `zone_engine.py`'s architecture (Phase 166 Plan 03).
- **`evaluate_stratum_expectancy_gate` unit tests:**
  - Correct `(regime, direction)` grouping from mixed-stratum input rows.
  - Degenerate case: fewer than 2 day-clusters in a cell → `(False, nan, nan)`, matching
    `frame_gate_passes`'s existing documented contract (reused unmodified, not
    reimplemented).
  - `min_clusters` coverage floor: a cell below the floor returns `coverage="insufficient"`,
    `passes=None` (matches `evaluate_frame_gate`'s existing behavior, exercised through
    the new wrapper).
  - Field-renaming correctness: output carries `regime`/`direction`, never leaks the
    generic `tf`/`regime` names `evaluate_frame_gate` returns internally.

---

## Naming, checked against `docs/foundation/naming-system.md`

- **`expectancy`**, not `eligibility`: `ensemble_trainer.py`'s `_eligibility_where`
  (`services/ensemble_trainer.py:108`) already names a *different* concept — per-feature
  training eligibility, not per-stratum trade eligibility. Reusing "eligibility" for both
  fails the Whiteboard Test (a quant reading `stratum_eligibility_gate` cold could not
  tell it apart from feature eligibility without reading the implementation).
  "Expectancy" is standard quantitative-finance vocabulary (E[R] per trade) and states
  precisely what is being tested.
- **`gate_math.py`**, not a new taxonomy category: mirrors `ic_math.py`'s existing,
  established naming exactly. `docs/foundation/glossary.md` has no existing entries for
  `expectancy`, `stratum`, or `gate` — no collision.
- **No class, no daemon suffix:** this is a Vocabulary A pure function
  (`src/intelligence/statistics/`), matching `frame_gate_passes`/`evaluate_frame_gate`/
  `evaluate_spread_gate`'s own existing shape. No `Evaluator`/`Analyzer`/`Gate` class
  wrapper — none of the taxonomy's mathematical-object suffixes fit a stateless function,
  and inventing a class here would violate the "mechanism vs role" test for no benefit.

---

## Renaissance-principle checklist

- **Ruthlessly eliminate complexity:** no new bootstrap statistics; 100% reuse of
  already-generic, already-proven machinery.
- **Data integrity paramount:** equivalence test proves the extraction is behavior-preserving
  before anything downstream can depend on the new location.
- **Component reuse / SoC:** the day-clustered gate core moves to where its own
  domain-vocabulary-free, DB/Kafka-free nature already says it belongs (Ring 1), fixing a
  real Ring-2-importing-Ring-2 coupling as a side effect, not a target.
- **DAG discipline:** pure function, no I/O, no cycle — `rows in → verdicts out`.
- **Guard against hidden bias:** built with zero live consumer, on the explicit record
  that the construction that motivated it has no proven edge — nothing about this
  design's correctness depends on that construction's fate.
- **Don't automate what isn't proven:** deliberately stops short of wiring, a persisted
  table, or row-assembly helpers — all of which would be guessing at a shape for a
  consumer that does not exist yet.
