# Restore Symbol-HMM IC Measurement For Routed Symbols Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore `feature_ic_scores` `symbol_hmm`-scope measurement for symbols routed to a
regime group whose Stage-1 conditioning decision is still open (`rates` only), unblocking
Phase 144's D-05 acceptance gate's F1 falsifier — without doubling measurement cost for
`equity`-routed symbols, whose analogous question isn't being asked yet.

**Architecture:** `services/ic_engine.py`'s `_compute_symbol_tf` already fetches
`feature_vectors.regime` (the per-symbol HMM label) unconditionally for every symbol — the
expensive I/O is shared regardless of routing. Extract the per-regime-label compute body
(clustering + per-scale IC/CI/walk-forward/Sharpe) into a pure, module-level, independently
testable function, and call it three ways: once for the pooled cell (always, exactly once —
pooled doesn't condition on regime labels at all), once for the symbol's "primary" label
source (today's exact behavior, unchanged), and — only when the symbol's routed group has a
new per-group APR flag `dual_write_symbol_hmm=true` — once more using the symbol's own
per-symbol HMM labels, scope-tagged `symbol_hmm`. The downstream cluster-representative/BH-FDR
selection step (already correct, operates on the accumulated result list regardless of how
many passes produced it) needs no changes.

**Tech Stack:** Python 3.14, numpy, scipy, psycopg2, pytest, PostgreSQL/TimescaleDB.

## Global Constraints

- New APR field lives inside the existing `alpha.regime.groups` JSON-list APR key (one new
  per-group field, `dual_write_symbol_hmm: bool`, default `false` via `.get(..., False)` —
  no new APR key, no schema migration needed since `config_value` is plain TEXT).
- Set `dual_write_symbol_hmm: true` for the `rates` group ONLY. Do not touch `equity`'s
  config or any other group.
- No DAG/topology change: same inputs (`feature_vectors`, `forward_returns`,
  `market_regimes`), same output table (`feature_ic_scores`).
- No change to `_backfill_bh_fdr` or the cluster-representative selection step — verified
  during design that the corpus-wide BH-FDR family already correctly absorbs additional
  `symbol_hmm` rows without special-casing.
- The pooled cell (`is_pooled=True`, `_POOLED_REGIME_SENTINEL`) must be computed exactly
  once per (symbol, tf) regardless of how many regime-label passes run — it does not
  condition on regime labels, so computing it per-pass would silently waste compute
  re-deriving the identical cell (caught and fixed during design, not present in the
  original code, which only ever ran one pass per symbol).
- Full spec: `docs/superpowers/specs/2026-07-21-restore-symbol-hmm-ic-measurement-for-routed-symbols-design.md`.

---

### Task 1: Extract `_compute_one_regime_cell` as a pure, testable function

**Files:**
- Modify: `services/ic_engine.py:975-1264` (inside `_compute_symbol_tf`)
- Test: `tests/unit/test_ic_engine_dual_write_symbol_hmm.py` (new file)

**Interfaces:**
- Produces: `_compute_one_regime_cell(regime_label, is_pooled, mask, resolved_regime_scope, *, X_aligned, returns_mat, complete_mat, config, symbol, tf, rng, existing_keys, training_window_end, feature_status_map, run_ts) -> tuple[list[dict], int]` — returns `(result_rows, n_skipped)` for exactly one cell. Module-level (not nested), independently testable without a DB connection.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_ic_engine_dual_write_symbol_hmm.py`:

```python
"""Unit tests for _compute_one_regime_cell (extracted per-regime-cell IC compute)
and the dual-write pass restructuring in _compute_symbol_tf.

No live DB — these tests call the pure, module-level per-cell function directly
with tiny synthetic numpy arrays.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from services.ic_engine import (  # noqa: E402
    _compute_one_regime_cell,
    _POOLED_REGIME_SENTINEL,
    ICEngineConfig,
)


def _make_config() -> ICEngineConfig:
    """Minimal ICEngineConfig with just enough real values for a tiny synthetic run.
    lookaheads must include every _SCALES entry the module defines."""
    return ICEngineConfig(
        subsample_min_stride=1,
        min_reliable_n=4,
        fdr_alpha=0.05,
        walk_forward_folds=1,
        cluster_max_corr=0.8,
        bootstrap_block_size={"5m": 2},
        bootstrap_resamples=50,
    )


def _synthetic_inputs(n_rows: int = 40, n_features: int = 3):
    rng = np.random.default_rng(42)
    X = rng.standard_normal((n_rows, n_features)).astype(np.float32)
    returns_mat = rng.standard_normal((n_rows, 4)).astype(np.float64)  # 4 = len(_SCALES)
    complete_mat = np.ones((n_rows, 4), dtype=bool)
    return X, returns_mat, complete_mat


def test_pooled_cell_produces_is_pooled_true_rows():
    X, returns_mat, complete_mat = _synthetic_inputs()
    config = _make_config()
    rng = np.random.default_rng(1)
    rows, n_skipped = _compute_one_regime_cell(
        _POOLED_REGIME_SENTINEL,
        True,
        np.ones(len(X), dtype=bool),
        "pooled",
        X_aligned=X,
        returns_mat=returns_mat,
        complete_mat=complete_mat,
        config=config,
        symbol="TEST",
        tf="5m",
        rng=rng,
        existing_keys=frozenset(),
        training_window_end=None,
        feature_status_map=None,
        run_ts=None,
    )
    assert all(r["is_pooled"] is True for r in rows)
    assert all(r["regime_scope"] == "pooled" for r in rows)


def test_regime_cell_uses_resolved_regime_scope_param():
    """The resolved_regime_scope argument controls the written regime_scope --
    not a recomputed is_pooled/cross_sectional flag inside the function."""
    X, returns_mat, complete_mat = _synthetic_inputs()
    config = _make_config()
    rng = np.random.default_rng(1)
    mask = np.ones(len(X), dtype=bool)
    rows, _ = _compute_one_regime_cell(
        "trending_up",
        False,
        mask,
        "symbol_hmm",
        X_aligned=X,
        returns_mat=returns_mat,
        complete_mat=complete_mat,
        config=config,
        symbol="TLT",
        tf="5m",
        rng=rng,
        existing_keys=frozenset(),
        training_window_end=None,
        feature_status_map=None,
        run_ts=None,
    )
    assert all(r["regime_scope"] == "symbol_hmm" for r in rows)
    assert all(r["regime"] == "trending_up" for r in rows)
    assert all(r["is_pooled"] is False for r in rows)


def test_existing_keys_dedup_skips_cell():
    """A cell_key already in existing_keys must be skipped (n_skipped incremented),
    never re-appended to result rows -- this is the existing dedup behavior, must
    survive the extraction unchanged."""
    X, returns_mat, complete_mat = _synthetic_inputs(n_features=1)
    config = _make_config()
    rng = np.random.default_rng(1)
    mask = np.ones(len(X), dtype=bool)

    # First call to discover the feature name this synthetic run will produce.
    rows, _ = _compute_one_regime_cell(
        "trending_up",
        False,
        mask,
        "symbol_hmm",
        X_aligned=X,
        returns_mat=returns_mat,
        complete_mat=complete_mat,
        config=config,
        symbol="TLT",
        tf="5m",
        rng=np.random.default_rng(1),
        existing_keys=frozenset(),
        training_window_end="2026-01-01",
        feature_status_map=None,
        run_ts=None,
    )
    assert len(rows) == 1
    feat_name = rows[0]["feature_name"]
    existing = frozenset({(feat_name, "TLT", "5m", "trending_up", rows[0]["lookahead_bars"], False)})

    rows2, n_skipped2 = _compute_one_regime_cell(
        "trending_up",
        False,
        mask,
        "symbol_hmm",
        X_aligned=X,
        returns_mat=returns_mat,
        complete_mat=complete_mat,
        config=config,
        symbol="TLT",
        tf="5m",
        rng=rng,
        existing_keys=existing,
        training_window_end="2026-01-01",
        feature_status_map=None,
        run_ts=None,
    )
    assert rows2 == []
    assert n_skipped2 >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_ic_engine_dual_write_symbol_hmm.py -v`
Expected: FAIL — `ImportError: cannot import name '_compute_one_regime_cell'`

- [ ] **Step 3: Read the exact current code to extract**

Read `services/ic_engine.py:975-1264` in full (the block starting at
`# Process: each distinct regime + one pooled pass` through the end of the
`for feat_idx, feat_name in enumerate(_FEATURE_NAMES):` inner loop, right before the
`# Context features:` comment). This is the body you are moving — do not rewrite its
numerical logic, only restructure the wrapping/parameters as described below.

- [ ] **Step 4: Add the extracted function**

Add this new module-level function to `services/ic_engine.py`, placed directly above
`_compute_symbol_tf` (before its `def` line):

```python
def _compute_one_regime_cell(
    regime_label: str,
    is_pooled: bool,
    mask: np.ndarray,
    resolved_regime_scope: str,
    *,
    X_aligned: np.ndarray,
    returns_mat: np.ndarray,
    complete_mat: np.ndarray,
    config: "ICEngineConfig",
    symbol: str,
    tf: str,
    rng: np.random.Generator,
    existing_keys: set[tuple] | frozenset[tuple],
    training_window_end: Any,
    feature_status_map: dict[str, str] | None,
    run_ts: datetime,
) -> tuple[list[dict], int]:
    """Compute clustering + per-scale IC/CI/walk-forward/Sharpe for ONE regime cell.

    Extracted from _compute_symbol_tf's single-pass loop (todo: restore symbol_hmm
    measurement for regime-group-routed symbols) so the same per-cell compute logic
    can run multiple times per (symbol, tf) -- once for the pooled cell (always,
    exactly once), once for the symbol's primary label source (cross-sectional or
    its own per-symbol HMM), and optionally once more for a dual-write pass using a
    second label source under a different regime_scope tag.

    resolved_regime_scope is passed in explicitly (not recomputed via
    _resolve_regime_scope(is_pooled, cross_sectional) internally) since a caller now
    decides scope per call, not per (is_pooled, cross_sectional) combination.

    rng is a shared, stateful np.random.Generator -- calling this function consumes
    draws from it by design (matches the existing per-worker RNG-scope contract:
    never re-seeded per-cell, advanced monotonically across every cell a worker
    computes for its symbol).

    Returns (result_rows, n_skipped_features) for this cell only. Does NOT populate
    pvals_flat/pval_result_idxs -- cluster-representative selection for BH-FDR runs
    downstream in _compute_symbol_tf, after ALL cells (across every pass) have been
    accumulated into all_results, and needs no changes for this to work correctly
    regardless of how many passes contributed rows.
    """
    lookaheads = config.lookaheads
    subsample_min_stride = config.subsample_min_stride
    min_reliable_n = config.min_reliable_n
    walk_forward_folds = config.walk_forward_folds
    cluster_max_corr = config.cluster_max_corr
    n_features = len(_FEATURE_NAMES)

    result_rows: list[dict] = []
    n_skipped = 0

    X_regime = X_aligned[mask]
    returns_regime = returns_mat[mask]
    complete_regime = complete_mat[mask]
    n_regime_raw = X_regime.shape[0]

    # --- PASTE HERE: the body of services/ic_engine.py:1002-1264 (the code you
    # read in Step 3), UNCHANGED, with exactly these two substitutions: ---
    #
    # 1. Every `IC_ENGINE_CELLS_SKIPPED_TOTAL.add(...)` call followed by
    #    `n_skipped += ...` stays exactly as-is (n_skipped is now a local, returned
    #    at the end instead of mutating an enclosing nonlocal).
    #
    # 2. The line reading:
    #      "regime_scope": _resolve_regime_scope(is_pooled, cross_sectional),
    #    becomes:
    #      "regime_scope": resolved_regime_scope,
    #
    # 3. Replace `all_results.append({...})` with `result_rows.append({...})`
    #    (same dict body, different accumulator name).
    #
    # No other lines change. The `if cell_key in existing_keys: ... continue`
    # dedup check, the degenerate-feature masking, dendrogram clustering, per-scale
    # subsampling, IC/CI/walk-forward/Sharpe computation, and result-dict
    # construction are all moved verbatim.

    return result_rows, n_skipped
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_ic_engine_dual_write_symbol_hmm.py -v`
Expected: PASS (3 tests) — if `ICEngineConfig` construction fails on missing required
fields, check the dataclass's actual field list (`grep -n "class ICEngineConfig" -A 40
services/ic_engine.py`) and add whatever additional fields are required with reasonable
defaults matching existing test files' pattern (e.g. `tests/unit/test_hac_ic_sharpe.py`
already constructs `ICEngineConfig` directly — copy its minimal-construction pattern).

- [ ] **Step 6: Restructure `_compute_symbol_tf`'s call site**

Replace `services/ic_engine.py`'s original lines 975-1264 (now extracted into the function
above) with:

```python
        # Pooled pass -- always exactly once, regardless of how many regime-label
        # sources this (symbol, tf) computes. Pooled doesn't condition on regime
        # labels at all (mask = all rows), so running it per label-source would
        # silently duplicate the identical (feature, symbol, tf, lookahead,
        # is_pooled=True) cell.
        all_results: list[dict] = []
        pvals_flat: list[float] = []
        pval_result_idxs: list[int] = []
        n_committed = 0
        n_skipped = 0

        pooled_rows, pooled_skipped = _compute_one_regime_cell(
            _POOLED_REGIME_SENTINEL,
            True,
            np.ones(len(aligned_idx), dtype=bool),
            "pooled",
            X_aligned=X_aligned,
            returns_mat=returns_mat,
            complete_mat=complete_mat,
            config=config,
            symbol=symbol,
            tf=tf,
            rng=rng,
            existing_keys=existing_keys,
            training_window_end=training_window_end,
            feature_status_map=feature_status_map,
            run_ts=run_ts,
        )
        all_results.extend(pooled_rows)
        n_skipped += pooled_skipped

        # Primary pass -- today's exact existing behavior: cross-sectional labels
        # when mr_dict is provided, else the symbol's own per-symbol HMM labels.
        primary_scope = "cross_sectional" if cross_sectional else "symbol_hmm"
        for regime_label in [r for r in set(regime_aligned_market) if r is not None]:
            primary_rows, primary_skipped = _compute_one_regime_cell(
                regime_label,
                False,
                regime_aligned_market == regime_label,
                primary_scope,
                X_aligned=X_aligned,
                returns_mat=returns_mat,
                complete_mat=complete_mat,
                config=config,
                symbol=symbol,
                tf=tf,
                rng=rng,
                existing_keys=existing_keys,
                training_window_end=training_window_end,
                feature_status_map=feature_status_map,
                run_ts=run_ts,
            )
            all_results.extend(primary_rows)
            n_skipped += primary_skipped

        # Dual-write pass (restore symbol_hmm measurement for regime-group-routed
        # symbols): only when this symbol's routed group has dual_write_symbol_hmm
        # set true in alpha.regime.groups. Uses the symbol's own per-symbol HMM
        # labels (regime_aligned, always fetched above regardless of routing) --
        # never the pooled sentinel here, per the note above.
        if cross_sectional and dual_write_symbol_hmm:
            for regime_label in [r for r in set(regime_aligned) if r is not None]:
                dual_rows, dual_skipped = _compute_one_regime_cell(
                    regime_label,
                    False,
                    regime_aligned == regime_label,
                    "symbol_hmm",
                    X_aligned=X_aligned,
                    returns_mat=returns_mat,
                    complete_mat=complete_mat,
                    config=config,
                    symbol=symbol,
                    tf=tf,
                    rng=rng,
                    existing_keys=existing_keys,
                    training_window_end=training_window_end,
                    feature_status_map=feature_status_map,
                    run_ts=run_ts,
                )
                all_results.extend(dual_rows)
                n_skipped += dual_skipped
```

This replaces the original `regime_passes = list(distinct_regimes) + [_POOLED_REGIME_SENTINEL]`
loop entirely. Leave everything after this block (the `# Context features:` section at the
original line 1266 onward) completely unchanged — it already reads `all_results`,
`pvals_flat`, `pval_result_idxs`, `n_skipped` from local scope, which still exist with the
same names.

- [ ] **Step 7: Add the new `dual_write_symbol_hmm` parameter to `_compute_symbol_tf`'s signature**

`services/ic_engine.py:779-791`, add one new parameter after `mr_dict`:

```python
    mr_dict: dict | None = None,
    dual_write_symbol_hmm: bool = False,
) -> tuple[list[dict], list[dict], dict[str, Any]]:
```

Update the docstring's `mr_dict` paragraph (currently ending "...falls back to
feature_vectors.regime.") by adding directly after it:

```
    dual_write_symbol_hmm: when True AND mr_dict is provided (cross_sectional=True),
    ALSO computes a symbol_hmm-scoped pass using the symbol's own feature_vectors.regime
    labels, in addition to the primary cross-sectional pass. Has no effect when
    mr_dict is None (there is no "dual" to add -- the primary pass already IS symbol_hmm
    in that case). Governed by the routed group's dual_write_symbol_hmm APR field in
    alpha.regime.groups (restore-symbol-hmm-ic-measurement fix).
```

- [ ] **Step 8: Run the full test file plus existing ic_engine tests**

Run: `.venv/bin/pytest tests/unit/test_ic_engine_dual_write_symbol_hmm.py tests/unit/test_ic_engine_clustering.py tests/unit/test_ic_engine_routing.py tests/unit/test_ic_engine_stride.py tests/unit/test_ic_engine_vectorized.py -v`
Expected: PASS (all) — confirms the extraction didn't change default (non-dual-write) behavior.

- [ ] **Step 9: Commit**

```bash
git add services/ic_engine.py tests/unit/test_ic_engine_dual_write_symbol_hmm.py
git commit -m "feat(regime-hmm): extract per-regime-cell compute, add dual-write pass for symbol_hmm restoration"
```

---

### Task 2: Thread `dual_write_symbol_hmm` through `_run_ic_worker` and `main()`

**Files:**
- Modify: `services/ic_engine.py:2503-2536` (`_run_ic_worker`'s args unpacking + its call to `_compute_symbol_tf`)
- Modify: `services/ic_engine.py:3444-3461` (`main()`'s `worker_args` construction)
- Test: `tests/unit/test_ic_engine_routing.py`

**Interfaces:**
- Consumes: `_compute_symbol_tf`'s new `dual_write_symbol_hmm` parameter (Task 1).
- Produces: `_run_ic_worker`'s `args` tuple gains a 10th element,
  `dual_write_symbol_hmm_by_group: dict[str, bool]` (or a simpler per-symbol resolved bool —
  see Step 1 below for the exact shape decision).

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_ic_engine_routing.py`:

```python
def test_build_symbol_regime_class_preserves_dual_write_field():
    """_build_symbol_regime_class itself only maps symbol -> group NAME; the
    dual_write_symbol_hmm field must be readable from the caller's own
    group_configs list (keyed by name), not lost anywhere in the routing path."""
    from services.ic_engine import _build_symbol_regime_class

    group_configs = [
        {"name": "rates", "tag_filter": ["fi_*"], "enabled": True, "dual_write_symbol_hmm": True},
        {"name": "equity", "tag_filter": ["eq_*"], "enabled": True, "dual_write_symbol_hmm": False},
    ]
    tags_by_symbol = {"TLT": {"fi_treasury"}, "SPY": {"eq_broad"}}
    symbol_regime_class = _build_symbol_regime_class(tags_by_symbol, group_configs)
    group_by_name = {g["name"]: g for g in group_configs}

    assert group_by_name[symbol_regime_class["TLT"]]["dual_write_symbol_hmm"] is True
    assert group_by_name[symbol_regime_class["SPY"]]["dual_write_symbol_hmm"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_ic_engine_routing.py -k dual_write -v`
Expected: FAIL if `_build_symbol_regime_class` strips unknown fields from group configs, or
PASS immediately if it already passes dicts through unmodified (it should — it only reads
`g["name"]` and `g.get("tag_filter", [])`, never reconstructs the dict). If it passes
immediately, that confirms no change is needed to `_build_symbol_regime_class` itself — move
directly to Step 3 without modifying that function.

- [ ] **Step 3: Update `main()`'s `worker_args` construction**

`services/ic_engine.py`, in `main()` right after the `symbol_regime_class`/`enabled_groups`
setup (~line 3219-3229, after `unrouted_symbols = ...`), add:

```python
            group_by_name: dict[str, dict] = {g["name"]: g for g in enabled_groups}
```

Then modify the `worker_args` list comprehension (~line 3444-3461) — the tuple element that
currently reads:

```python
                        (
                            mr_dicts_by_group.get(symbol_regime_class.get(symbol))
                            if enabled_groups
                            else None
                        ),
```

stays exactly as-is (this is still the `mr_dict` element, unchanged), and gets ONE new
element appended after it:

```python
                        (
                            group_by_name.get(symbol_regime_class.get(symbol), {}).get(
                                "dual_write_symbol_hmm", False
                            )
                            if enabled_groups
                            else False
                        ),
```

- [ ] **Step 4: Update `_run_ic_worker`'s args unpacking and its call to `_compute_symbol_tf`**

`services/ic_engine.py:2526-2536`, add the new element to the unpacking tuple:

```python
    (
        symbol,
        tfs,
        dsn,
        training_window_end,
        existing_keys_frozen,
        config,
        run_ts,
        feature_status_map,
        mr_dict_by_tf,
        dual_write_symbol_hmm,
    ) = args
```

Update the docstring's `Args:` block (~line 2514-2519) to add
`dual_write_symbol_hmm (bool) -- resolved once per symbol from its routed group's APR field`
to the tuple description.

`services/ic_engine.py:2568-2580`, add the new argument to the `_compute_symbol_tf` call:

```python
                tf_pooled, tf_regime, stats = _compute_symbol_tf(
                    dsn=dsn,
                    symbol=symbol,
                    tf=tf,
                    training_window_end=training_window_end,
                    existing_keys=existing_keys,
                    config=config,
                    tracer=noop_tracer,
                    run_ts=run_ts,
                    rng=rng,
                    feature_status_map=feature_status_map,
                    mr_dict=mr_dict_by_tf.get(tf) if mr_dict_by_tf else None,
                    dual_write_symbol_hmm=dual_write_symbol_hmm,
                )
```

- [ ] **Step 5: Run the routing test plus a full ic_engine test sweep**

Run: `.venv/bin/pytest tests/unit/test_ic_engine_routing.py tests/unit/test_ic_engine_dual_write_symbol_hmm.py tests/unit/test_ic_engine_lifecycle_hook.py tests/unit/test_ic_engine_parallelism.py -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add services/ic_engine.py tests/unit/test_ic_engine_routing.py
git commit -m "feat(regime-hmm): thread dual_write_symbol_hmm from APR group config to the per-symbol worker"
```

---

### Task 3: Seed `dual_write_symbol_hmm: true` for the `rates` group only

**Files:**
- Create: `production/migrations/247_regime_groups_dual_write_symbol_hmm.sql`

**Context:** `alpha.regime.groups`'s `config_value` column is plain TEXT holding a JSON
array (not JSONB) — this migration replaces the full string value with the field added to
the `rates` entry only. Current live value (verified 2026-07-21):

```json
[{"name":"equity","tag_filter":["eq_*","intl_*"],"signal_type":"breadth_vol","params_prefix":"alpha.equity_regime","enabled":true},{"name":"rates","tag_filter":["fi_*"],"signal_type":"curve_credit","params_prefix":"alpha.rates_regime","enabled":true},{"name":"commodity_energy","tag_filter":["commodity_energy_crude","commodity_energy_natgas","commodity_energy_pipeline"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_energy_regime","enabled":false},{"name":"commodity_metals","tag_filter":["commodity_metals_precious","commodity_metals_industrial"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_metals_regime","enabled":false},{"name":"commodity_agri","tag_filter":["commodity_agri"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_agri_regime","enabled":false},{"name":"fx","tag_filter":["fx_*","crypto"],"signal_type":"fx_dollar_carry","params_prefix":"alpha.fx_regime","enabled":false}]
```

- [ ] **Step 1: Write the migration**

```sql
-- Migration 247: alpha.regime.groups -- add dual_write_symbol_hmm to the rates group only
--
-- ic_engine.py:965 (`cross_sectional = mr_dict is not None`) permanently replaces a
-- routed symbol's per-symbol HMM IC measurement with cross-sectional measurement --
-- verified live 2026-07-21: TLT (routed to `rates`) has zero symbol_hmm-scope
-- feature_ic_scores rows since 2026-07-17, before the most recent corpus rebuild, and
-- will never get another one under the pre-fix code. This breaks Phase 144's D-05
-- acceptance gate, whose F1 falsifier requires comparing TLT's per-symbol HMM against
-- the new rates cross-sectional label -- data that cannot exist without this fix.
--
-- dual_write_symbol_hmm is a per-group field (not a new APR key) governing whether
-- ic_engine.py's new dual-write pass (see services/ic_engine.py's
-- _compute_one_regime_cell / _compute_symbol_tf) ALSO computes a symbol_hmm-scoped
-- measurement pass for that group's routed symbols, alongside the primary
-- cross-sectional pass.
--
-- Set true for `rates` ONLY. `rates` has an open Stage-1 conditioning question (D-05
-- exists specifically to answer it: does per-symbol HMM or the new cross-sectional
-- label better separate IC for this group's members?) -- dual-write while that
-- question is open, per this project's "shadow mode first" principle. `equity`'s
-- analogous question was never asked (silently defaulted to cross-sectional-only the
-- moment routing shipped, no falsifier gate ever built) -- a separate, real gap, filed
-- as its own follow-up todo, NOT solved here by accelerating equity's measurement cost
-- before any gate exists to consume that data. Flipping equity's flag later, if that
-- gate gets built, is a one-line APR change, zero code, thanks to this migration's
-- mechanism being general per-group rather than hardcoded to `rates`.

BEGIN;

UPDATE config_state
SET config_value = '[{"name":"equity","tag_filter":["eq_*","intl_*"],"signal_type":"breadth_vol","params_prefix":"alpha.equity_regime","enabled":true},{"name":"rates","tag_filter":["fi_*"],"signal_type":"curve_credit","params_prefix":"alpha.rates_regime","enabled":true,"dual_write_symbol_hmm":true},{"name":"commodity_energy","tag_filter":["commodity_energy_crude","commodity_energy_natgas","commodity_energy_pipeline"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_energy_regime","enabled":false},{"name":"commodity_metals","tag_filter":["commodity_metals_precious","commodity_metals_industrial"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_metals_regime","enabled":false},{"name":"commodity_agri","tag_filter":["commodity_agri"],"signal_type":"commodity_momentum_ts","params_prefix":"alpha.commodity_agri_regime","enabled":false},{"name":"fx","tag_filter":["fx_*","crypto"],"signal_type":"fx_dollar_carry","params_prefix":"alpha.fx_regime","enabled":false}]',
    version = version + 1
WHERE config_key = 'alpha.regime.groups';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'alpha.regime.groups', version, config_value, 'migration_247',
       'Add dual_write_symbol_hmm=true to rates group only, restoring symbol_hmm IC '
       'measurement for its routed symbols -- unblocks Phase 144 D-05 F1 falsifier. '
       'equity left unchanged (its analogous question was never falsifier-tested; '
       'filed as a separate follow-up todo, not solved here).'
FROM config_state WHERE config_key = 'alpha.regime.groups';

COMMIT;
```

- [ ] **Step 2: Apply the migration**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/247_regime_groups_dual_write_symbol_hmm.sql`
Expected: `BEGIN` / `UPDATE 1` / `INSERT 0 1` / `COMMIT`

- [ ] **Step 3: Verify the field is readable and correctly scoped**

Run:
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT config_value::json->1->>'name' AS group_2_name,
       config_value::json->1->>'dual_write_symbol_hmm' AS group_2_dual_write,
       config_value::json->0->>'name' AS group_1_name,
       config_value::json->0->'dual_write_symbol_hmm' AS group_1_dual_write
FROM config_state WHERE config_key = 'alpha.regime.groups';
"
```
Expected: `group_2_name=rates`, `group_2_dual_write=true`, `group_1_name=equity`,
`group_1_dual_write` is SQL `NULL` (field absent, `.get(..., False)` in code handles this).

- [ ] **Step 4: Commit**

```bash
git add production/migrations/247_regime_groups_dual_write_symbol_hmm.sql
git commit -m "feat(regime-hmm): seed dual_write_symbol_hmm=true for the rates group"
```

---

### Task 4: Live verification — scoped re-run + D-05 gate re-run

**Files:** none (verification only)

- [ ] **Step 1: Re-run `ic_engine.py` scoped to the `rates` group's 12 symbols**

Run: `.venv/bin/python services/ic_engine.py --symbols TLT IEF SHY HYG LQD EMB AGG TIP BIL MUB PFF EDV`

This is a real batch job; it may take several minutes. Let it run to completion — look for
a completion log line before proceeding.

- [ ] **Step 2: Verify fresh `symbol_hmm` rows exist for TLT**

Run:
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT regime_scope, count(*), max(computed_at) FROM feature_ic_scores
WHERE symbol = 'TLT' GROUP BY regime_scope ORDER BY regime_scope;
"
```
Expected: a `symbol_hmm` row with `count > 0` and `max(computed_at)` matching today's run
(previously: zero `symbol_hmm` rows for TLT, `max(computed_at)` stuck at 2026-07-17).

- [ ] **Step 3: Verify `cross_sectional` rows for TLT were NOT disturbed**

Run:
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT count(*) FROM feature_ic_scores WHERE symbol = 'TLT' AND regime_scope = 'cross_sectional';
"
```
Expected: non-zero (the existing 7,130+ rows, now possibly refreshed by this re-run too,
still present — the primary pass is unchanged).

- [ ] **Step 4: Verify `equity` symbols are unaffected**

Run:
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT regime_scope, count(*) FROM feature_ic_scores WHERE symbol = 'SPY' GROUP BY regime_scope;
"
```
Expected: still zero `symbol_hmm` rows for `SPY` (equity's `dual_write_symbol_hmm` stays
`false` — this run didn't even touch SPY since `--symbols` scoped it to the rates group only,
but confirm no unintended side effect regardless).

- [ ] **Step 5: Re-run Phase 144's D-05 acceptance gate**

Run: `.venv/bin/python scripts/analysis/phase144_regime_separation_gate.py`

Record the full output. Confirm the `TLT per-symbol HMM (regime_scope=symbol_hmm)` table is
no longer `(no rows)` and the F1/F2 falsifier verdict is no longer "cannot evaluate F1... 
INCONCLUSIVE" — record whatever real verdict (F1 triggered / not triggered, F2 outcome) the
gate now produces. This is the actual, real answer to Phase 144's Stage-1 conditioning
question for `rates` — report it accurately whatever it is, do not treat any particular
outcome as required for this task to succeed.

- [ ] **Step 6: No commit for this task** (verification only, no file changes)

---

### Task 5: File the equity follow-up todo

**Files:**
- Create: `.planning/todos/pending/167-equity-cross-sectional-vs-symbol-hmm-never-falsifier-tested.md`

- [ ] **Step 1: Write the todo**

```markdown
---
status: pending
priority: P2
filed: 2026-07-21
source: found while fixing todo (restore-symbol-hmm-ic-measurement, unblocks Phase 144's
  D-05 gate) -- the same silent-suppression mechanism affects the equity regime group too,
  a separate and older question nobody ever built a falsifier gate to test.
---

# `equity` group's cross-sectional-vs-per-symbol-HMM Stage-1 conditioning decision was never falsifier-tested

## What's wrong

`services/ic_engine.py`'s regime-group routing (`cross_sectional = mr_dict is not None`,
line ~965) permanently replaces a routed symbol's per-symbol HMM (`symbol_hmm`-scope)
`feature_ic_scores` measurement with cross-sectional measurement the moment that symbol
matches an enabled regime group's `tag_filter`. This was just fixed for the `rates` group
(migration 247, `alpha.regime.groups`' new per-group `dual_write_symbol_hmm` field) because
Phase 144's D-05 acceptance gate needed fresh `symbol_hmm` data to evaluate its F1 falsifier
for `TLT`.

The same silent suppression has applied to every `equity`-routed symbol (e.g. `SPY`, ~50+
symbols) since equity's cross-sectional regime group was first enabled -- verified live
2026-07-21: `SPY` has zero `symbol_hmm`-scope rows in `feature_ic_scores`. Unlike `rates`,
no D-05-equivalent falsifier gate was ever built to test whether cross-sectional labels
actually separate IC better than per-symbol HMM for equity symbols -- the choice was a
silent implementation-order side effect of when routing shipped, not an earned, proven
decision. Per this project's own principles ("earn promotion through proof," "resist
overfitting," "empirical over theoretical"), an unproven default masquerading as settled is
exactly the class of gap that should rank above "merely convenient."

## Fix direction

Not urgent, not solved by this fix. Two possible directions, need a real design decision:
1. Build an equity-scoped equivalent of Phase 144's D-05 F1/F2 falsifier gate (same
   `evaluate_frame_gate`/separation-metric machinery, different symbol universe), then
   decide whether to set `alpha.regime.groups`' `equity` entry's `dual_write_symbol_hmm=true`
   temporarily while that gate runs -- mechanism is already general-purpose (one-line APR
   change, zero code, per migration 247's design).
2. Decide the cross-sectional choice for equity is self-evidently correct enough (e.g. the
   equity cross-sectional model has a much longer track record / more validation than
   `rates` did) and explicitly document that as an accepted, reasoned default rather than
   an unexamined one -- still requires SOME evidence-gathering, not a rubber-stamp.

Do not silently accelerate this into `dual_write_symbol_hmm=true` for equity without either
building the gate or making the explicit reasoned-default case -- that would repeat the
exact "accelerate before it's justified" mistake this whole investigation started from.

## References

- `services/ic_engine.py:965` -- the suppression mechanism
- `production/migrations/247_regime_groups_dual_write_symbol_hmm.sql` -- the `rates` fix
  this todo is the sibling of
- `scripts/analysis/phase144_regime_separation_gate.py` -- the D-05 falsifier gate pattern
  an equity-scoped equivalent would follow
- `docs/superpowers/specs/2026-07-21-restore-symbol-hmm-ic-measurement-for-routed-symbols-design.md`
  -- design doc that first surfaced this as an explicit out-of-scope follow-up
```

- [ ] **Step 2: Add to `PRIORITIES.md`**

Read `.planning/todos/PRIORITIES.md`, find the P2 section, add a one-line entry:
`167-equity-cross-sectional-vs-symbol-hmm-never-falsifier-tested.md` with a short
description matching the todo's title, following the existing entries' format exactly.

- [ ] **Step 3: Commit**

```bash
git add .planning/todos/pending/167-equity-cross-sectional-vs-symbol-hmm-never-falsifier-tested.md .planning/todos/PRIORITIES.md
git commit -m "docs(167): file equity cross-sectional-vs-symbol-hmm untested-default follow-up"
```

---

## Final Step: Run the full unit suite

- [ ] Run: `.venv/bin/pytest tests/unit/ -q`
- [ ] Expected: all green, no regressions introduced by any task above.
