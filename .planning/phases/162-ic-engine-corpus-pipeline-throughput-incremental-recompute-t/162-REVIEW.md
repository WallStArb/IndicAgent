---
phase: 162-ic-engine-corpus-pipeline-throughput-incremental-recompute-t
reviewed: 2026-07-23T00:00:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - production/migrations/249_ic_feature_block_apr_keys.sql
  - production/migrations/250_ic_cross_sectional_bootstrap_threads_per_tf.sql
  - production/migrations/251_ic_cell_fingerprints.sql
  - production/migrations/252_ic_refresh_min_new_fraction.sql
  - scripts/ops/corpus/ops_ic_fingerprint_equivalence.py
  - services/_batch_utils.py
  - services/ensemble_ic_engine.py
  - services/ic_engine.py
  - src/intelligence/statistics/ic_math.py
  - tests/unit/test_batch_utils_short_lived_conn.py
  - tests/unit/test_ic_engine_checkpoint_key.py
  - tests/unit/test_ic_engine_compute_split.py
  - tests/unit/test_ic_engine_dual_write_symbol_hmm.py
  - tests/unit/test_ic_engine_fingerprint.py
  - tests/unit/test_ic_engine_parallelism.py
  - tests/unit/test_ic_math_walk_forward_folds.py
findings:
  critical: 1
  warning: 2
  info: 2
  total: 5
status: issues_found
---

# Phase 162: Code Review Report

**Reviewed:** 2026-07-23T00:00:00Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Reviewed the Phase 162 ic_engine.py throughput/incremental-recompute work (extracted
`short_lived_conn`/`build_walk_forward_folds`, per-tf bootstrap threads, the new
`ic_cell_fingerprints` whole-cell idempotency mechanism, and the fingerprint-equivalence
proof harness) plus the subsequent simplify-pass refactor (`_resolve_symbol_routing`
dedup, watermark-query caching, `ThreadPoolExecutor` reuse in `_subsample_and_rank`, and
the `_check_cell_size`/`_fp_row`/`_load_per_tf_apr_dict` helper extractions).

The math extraction (`build_walk_forward_folds`, `ic_math.py`), the feature-blocked
rank/IC/CI/fold rewrite (`_subsample_and_rank`), the `ThreadPoolExecutor` reuse, and the
`CellTooLargeError`/`_check_cell_size` crash-loud ceiling are all well-tested and
correct — the equivalence proof (`test_subsample_and_rank_feature_blocked_matches_unblocked`)
is a genuinely convincing bit-identical check, and the per-tf bootstrap-thread migration
(249/250) is sound.

However, the whole-cell fingerprint gate — the mechanism this phase exists to build, and
the one most load-bearing for silently-stale data risk — has one real, provable BLOCKER:
`_compute_upstream_watermark()`'s cross-sectional branch is called from the per-symbol
fingerprint pre-pass without the `regime_group`/`symbol_list` arguments it needs, so a
regime-group-routed symbol's own `pass_type='cross_sectional'` fingerprint watermark is
silently computed against `None` inputs instead of that symbol's real data. This defeats
the exact "silent wrong answers are worse than loud crashes" invariant migration 251 and
`_compute_upstream_watermark`'s own docstring were written to guarantee, for every symbol
routed into a regime group (the primary Phase 144 configuration). No test exercises this
path (`_symbol_expected_cells` is tested in isolation; `_compute_upstream_watermark` is
tested only via its group-level cross-sectional call site), and the `ops_ic_fingerprint_equivalence.py`
harness's own A/B methodology cannot catch this class of bug (see finding detail).

Two warnings and two info items round out the rest — no other correctness bugs found in
the reviewed surface.

## Critical Issues

### CR-01: Per-symbol cross-sectional fingerprint watermark computed against `None` symbol/group scope — silently defeats the fingerprint invalidation guarantee for every regime-group-routed symbol

**File:** `services/ic_engine.py:4327-4351` (buggy call site), `services/ic_engine.py:950-1022` (`_compute_upstream_watermark`), `services/ic_engine.py:1137-1166` (`_symbol_expected_cells`)

**Issue:**

`_compute_symbol_tf` writes a per-symbol row with `regime_scope='cross_sectional'`
(`symbol=<real instrument symbol>`, not `'POOLED'`) whenever that symbol is routed to an
enabled regime group (see `services/ic_engine.py:2059-2116`, `_resolve_regime_scope(False,
cross_sectional=True)`). `_symbol_expected_cells` correctly enumerates this as one of the
symbol's expected fingerprint cells: `(tf, "cross_sectional")` (line ~1158-1163).

The per-symbol fingerprint pre-pass loop in `main()` computes this cell's current
fingerprint like this:

```python
# services/ic_engine.py:4333-4346
for tf, pass_type in expected_cells:
    current_fp = {
        "code_content_key": content_key,
        "apr_snapshot_key": apr_snapshot_key,
        "upstream_watermark": _compute_upstream_watermark(
            conn,
            symbol,
            tf,
            pass_type,
            feature_registry_watermark=feature_registry_watermark,
            fr_fv_cache=fr_fv_cache,
            mr_tags_cache=mr_tags_cache,
        ),
    }
```

Note `regime_group=` and `symbol_list=` are **not** passed (both default to `None`).
Inside `_compute_upstream_watermark` (line 992-993):

```python
is_cross_sectional = pass_type == "cross_sectional"
symbols_for_fr_fv = symbol_list if is_cross_sectional else ([symbol] if symbol else [])
```

When `pass_type == "cross_sectional"` (true for every regime-group-routed symbol —
the normal, primary Phase 144 configuration, not an edge case), `is_cross_sectional`
becomes `True` even though this call site is fingerprinting the **per-symbol** row, not
the group-pooled `POOLED` cell the function's own docstring describes ("there is no
single instrument symbol... symbol_list carries that peer set"). `symbols_for_fr_fv`
therefore becomes `symbol_list`, i.e. `None` — not `[symbol]`.

Consequences, traced through to the SQL:
1. `_watermark_forward_returns_feature_vectors(conn, None, tf)` executes `WHERE symbol =
   ANY(%(symbols)s)` with `symbols=None`. Postgres never matches any row against
   `ANY(NULL)`, so this silently returns `count=0, max_bar_ts=None, max_computed_at=None`
   — never the real per-symbol forward_returns/feature_vectors state — regardless of what
   that symbol's actual data looks like.
2. `fr_fv_key = (regime_group if is_cross_sectional else symbol, tf) = (None, tf)` — the
   memoization cache key collapses across **every** routed symbol sharing that `tf`, so
   the first routed symbol's (already-wrong) degenerate result is silently reused for
   every other routed symbol at that `tf` too.
3. The `is_cross_sectional` branch also fires `_watermark_market_regimes_instrument_tags(conn,
   regime_group=None, tf, symbol_list=None)` — `WHERE regime_group = NULL` and `WHERE
   symbol = ANY(NULL)` again match nothing, so an HMM relabel (`market_regimes.regime_label`
   changing in place) or an `instrument_tags` edit for this symbol's peer set is *never*
   detected for this cell either.

Net effect: once this cell's fingerprint is written on a first run, its "current"
watermark on every subsequent run is deterministically re-derived via the identical
broken path, so it always matches the stored value — `_fingerprint_is_valid` returns
`True` forever, independent of `code_content_key`/`apr_snapshot_key` staying fixed. A
price-sanity correction to a routed symbol's bars, a feature recompute, or an HMM
relabel of its regime group will **never** invalidate that symbol's own
`regime_scope='cross_sectional'` rows in `feature_ic_scores` — exactly the "silent
partial-stale" failure class migration 251's header comment and `_compute_upstream_watermark`'s
own docstring say this mechanism exists to prevent ("silent wrong answers are worse than
loud crashes", CLAUDE.md north star; this is also functionally the same severity class as
T-162-03-01, which the group-pooled cross-sectional call site was explicitly hardened
against — that hardening was never extended to this call site).

This is not a corner case: any symbol routed into an enabled `alpha.regime.groups` entry
(the standard, intended Phase 144 configuration for the equity ETF universe) hits this
path on every corpus run. It does not crash (`ANY(NULL)` degrades to an empty match, not
an error — consistent with the 162-simplify-pass commit's own claim of a clean
`ops_ic_fingerprint_equivalence.py` re-verification run), which is exactly why it went
undetected: the equivalence harness only diffs a force-refresh run against a
fingerprint-skip run with **no intervening data mutation**, so both runs derive the same
(broken) watermark and agree — the harness cannot detect an invalidation failure by
construction, only a values-still-correct-on-first-write proof.

No unit test exercises this: `test_ic_engine_fingerprint.py` tests `_compute_upstream_watermark`'s
output only via hand-built dicts (never calls the function itself against a routed-symbol
`pass_type='cross_sectional'` scenario), and `test_symbol_expected_cells_routed_symbol_gets_pooled_and_cross_sectional`
only asserts the *cell key set*, not that the watermark computed for that cell is correctly
scoped.

**Fix:** Distinguish the two "cross_sectional" meanings explicitly at the call site — the
per-symbol prepass loop is fingerprinting *this symbol's own* row, not a group-pooled
cell, so it must not rely on `is_cross_sectional`'s group-scoped defaults. Pass the real
symbol-scoped inputs and this symbol's routed group explicitly:

```python
for tf, pass_type in expected_cells:
    routed_group_name, _ = _resolve_symbol_routing(
        symbol, symbol_regime_class, group_by_name, equity_model_enabled
    )
    current_fp = {
        "code_content_key": content_key,
        "apr_snapshot_key": apr_snapshot_key,
        "upstream_watermark": _compute_upstream_watermark(
            conn,
            symbol,
            tf,
            pass_type,
            regime_group=routed_group_name if pass_type == "cross_sectional" else None,
            symbol_list=[symbol] if pass_type == "cross_sectional" else None,
            feature_registry_watermark=feature_registry_watermark,
            fr_fv_cache=fr_fv_cache,
            mr_tags_cache=mr_tags_cache,
        ),
    }
```

This still isn't a perfect fit for `_compute_upstream_watermark`'s current two-shape
contract (its docstring's "symbol_list carries the peer set" framing is for the
group-pooled `POOLED` cell only) — the cleaner long-term fix is to give
`_compute_upstream_watermark` a third explicit mode (or a boolean `own_symbol_cross_sectional=True`
flag) so `symbols_for_fr_fv` always resolves to `[symbol]` for a per-symbol row regardless
of `pass_type`, while `regime_group`/full peer `symbol_list` stay reserved for the actual
group-pooled `POOLED` cell. Either way, add a test that calls `_compute_upstream_watermark`
(or the full pre-pass loop) for a *routed* symbol's `cross_sectional` cell and asserts the
forward_returns/feature_vectors components change when that symbol's own data changes —
the current test suite has no such assertion.

## Warnings

### WR-01: `ThreadPoolExecutor` created even when `max_workers == 0`/negative would be silently treated as serial, but a misconfigured APR value of `0` for `cross_sectional_bootstrap_threads` is not distinguished from "unset"

**File:** `services/ic_engine.py:1483` (`_subsample_and_rank`), `production/migrations/250_ic_cross_sectional_bootstrap_threads_per_tf.sql:32-33` (min_value 1)

**Issue:** `pool = ThreadPoolExecutor(max_workers=max_workers) if max_workers > 1 else None`
silently falls back to the serial path for any `max_workers <= 1`, including `0` or a
negative value. The APR schema for `alpha.ic.cross_sectional_bootstrap_threads.{tf}`
constrains `min_value=1`, so this can't happen through the config UI/DB constraint in
practice — but `ICEngineConfig` is a plain frozen dataclass with no runtime validation of
its own, and a direct `ICEngineConfig(...)` construction (e.g. in a future test or a
one-off script) with `cross_sectional_bootstrap_threads={"5m": 0, ...}` would silently
degrade to the serial path rather than raising. Low likelihood, low blast radius (never
worse than "slower than expected", never a correctness issue since the serial path is
still correct) — flagged as a robustness gap, not a live bug.

**Fix:** Optional: assert `max_workers >= 1` at the top of `_subsample_and_rank`, or note
in the dataclass field's docstring that `0`/negative values are silently treated as
serial rather than rejected.

### WR-02: `_compute_upstream_watermark`'s `is_cross_sectional` branch conflates two structurally different cell shapes under one boolean, which is what let CR-01 slip through review

**File:** `services/ic_engine.py:950-1022`

**Issue:** The function's docstring states pass_type `'cross_sectional'` always means "the
cell pools regime_group's whole peer set" and "there is no single instrument symbol" —
but this is only true for the group-pooled `POOLED` cell computed in the `cs_cell_plan`
loop. The exact same `pass_type` string also identifies a **per-symbol** row
(`_compute_symbol_tf`'s own `regime_scope='cross_sectional'` output, `symbol=<real
symbol>`) whenever that symbol is routed. `_compute_upstream_watermark` has no way to
distinguish these two callers apart from whether `regime_group`/`symbol_list` happen to
be passed — a silent, easy-to-miss coupling (exactly what happened at CR-01's call site).
This is a design smell independent of CR-01's specific fix: any future caller of
`_compute_upstream_watermark(..., pass_type="cross_sectional", ...)` that forgets to pass
`regime_group`/`symbol_list` reproduces the identical class of bug with no signal at the
call site that anything is wrong.

**Fix:** Make the two shapes structurally distinct — e.g. a `cell_kind: Literal["per_symbol",
"group_pooled"]` parameter (or two thin wrapper functions,
`_compute_upstream_watermark_for_symbol` / `_compute_upstream_watermark_for_group`) so a
caller cannot pass `pass_type="cross_sectional"` without also being forced to supply the
matching scope arguments, and the two docstring halves stop describing mutually
inconsistent contracts under one function signature.

## Info

### IN-01: `_NULL_MARKER` constant defined but never referenced

**File:** `services/_batch_utils.py:19`

**Issue:** `_NULL_MARKER = r"\N"` is defined at module scope but has zero references
anywhere in this file or elsewhere in the codebase (verified via grep). `bulk_update_by_key`'s
CSV writer uses an inline `"" if v is None else v` (the correct NULL sentinel for `COPY
... FORMAT CSV`, which differs from the `\N` sentinel used by the default TEXT format) —
so the constant appears to be a leftover from an earlier TEXT-format implementation.
Pre-existing (not introduced by this phase), but the file is in this review's scope.

**Fix:** Remove the dead constant, or wire it in if a future `COPY ... FORMAT TEXT` path
is added.

### IN-02: `n_watermark_queries` log line's stated formula depends on `dict` insertion-order coincidence, not a documented invariant

**File:** `services/ic_engine.py:4421-4426`

**Issue:** `n_watermark_queries = 1 + len(fr_fv_cache) + len(mr_tags_cache)` is computed
*after* both the per-symbol prepass loop and the cross-sectional `cs_cell_plan` discovery
loop have both already populated `fr_fv_cache`/`mr_tags_cache` — the comment above it
("1 (feature_registry...) + actual cache-miss round trips") is accurate only because both
loops share the exact same two cache dicts by reference. This is correct as written, but
it's an observability-only value (a log line), and the accuracy depends on no future
refactor moving this log statement between the two loops or giving either loop its own
cache instance. Not a functional bug — flagged only because it's easy to silently break
in a later edit with no test coverage (this log line has no assertion anywhere in the
test suite).

**Fix:** Optional: add a one-line comment at the log statement itself (not just the
`n_watermark_queries` assignment above it) noting it must run after both loops complete,
or add a cheap unit test asserting the count formula against synthetic cache dicts.

---

_Reviewed: 2026-07-23T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
