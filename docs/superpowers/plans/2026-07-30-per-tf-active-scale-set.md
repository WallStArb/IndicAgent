# Per-tf Active-Scale Set Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `ic_engine.py`'s hardcoded global `_SCALES = ("fast", "mid", "slow", "extended")` tuple with a per-tf `active_scales` set read from APR, so a timeframe with zero real observations at a tier (1h's `slow`/`extended`, 0.000 completeness, live-measured) stops being computed at all, instead of silently attempted-and-discarded.

**Architecture:** One new JSON-typed APR key family, `alpha.ic.active_scales.{tf}`, loaded through the two existing config-access idioms this codebase already uses (`ConfigService.get_sync` for `ICEngineConfig`, `_batch_utils.cfg()` for `EnsembleICConfig`), resolved to a canonically-ordered tuple via one new shared function in `_batch_utils.py`, and substituted at `ic_engine.py`'s 12 existing `_SCALES` call sites — no schema migration, no rewrite of the numpy compute layer.

**Tech Stack:** Python 3.14, PostgreSQL/TimescaleDB (`config_schema`/`config_state`/`config_history`), pytest.

## Global Constraints

- No `forward_returns` schema change — `return_{scale}`/`complete_{scale}` columns stay as-is (per the approved spec's rejection of both the widen-to-8-columns and full-normalization alternatives).
- `alpha.ic.lookahead.{tf}.{scale}` (the 16 bar-count keys, migration 269) are untouched — this plan only changes *which* scales `ic_engine` attempts, never the bar-count values.
- `active_scales.1h = ["fast", "mid"]` is the only value change, justified solely by today's measured 0.000 completeness for `slow`/`extended` — not a prediction about todo 208's outcome. `5m`/`15m`/`1d` keep all four scales active, unchanged.
- Every new `ICEngineConfig` field must be classified into exactly one of `_COMPUTATIONAL_CONFIG_FIELDS`/`_OPERATIONAL_CONFIG_FIELDS`, or `test_ic_engine_fingerprint.py`'s existing partition test fails the build.
- Do not touch this plan's out-of-scope items (see below) — file follow-up todos instead if something new surfaces.

**Out of scope (do not implement here):**
- Todo 208 Step 2 (removing the session-boundary gate) — separate plan, gated on its own empirical check.
- A 5th/6th named production tier, or `forward_returns` schema widening — no evidence any tf needs it today.
- An automated auditor keeping `active_scales` in sync with live completeness going forward — worth considering later, not required for correctness now.

---

## File Structure

| File | Responsibility |
|---|---|
| `services/_batch_utils.py` | New `ACTIVE_SCALES_FALLBACKS_BY_TF` constant, new `canonicalize_active_scales()` pure function, new `get_list_config()` ConfigService helper (sibling of the existing `get_dict_config()`) |
| `services/ic_engine.py` | `ICEngineConfig` gains `active_scales: dict[str, tuple[str, ...]]` field + `active_scales_for(tf)` method + `from_apr()` loading + `_COMPUTATIONAL_CONFIG_FIELDS` classification; 12 `_SCALES` call sites become local-variable bindings of `config.active_scales_for(tf)` |
| `services/ensemble_ic_engine.py` | `EnsembleICConfig` gains the same field/method/loading (mirrors `ICEngineConfig`, no fingerprint classification needed — no fingerprint mechanism exists in this file) |
| `production/migrations/271_ic_active_scales.sql` | Seeds `alpha.ic.active_scales.{5m,15m,1h,1d}` — `1h` gets `["fast","mid"]`, the other three get all four scales |
| `tests/unit/test_batch_utils_active_scales.py` | New file: `canonicalize_active_scales()` behavior (ordering, unknown-scale rejection, empty-input handling) |
| `tests/unit/test_ic_engine_fingerprint.py` | Extended: new field classified, snapshot key moves on `active_scales` change, deterministic regardless of configured JSON-array order |
| `tests/unit/test_ic_engine_active_scales_boundary.py` | New file: grep-based boundary test asserting no bare `_SCALES` reference survives outside its own definition line |

---

### Task 1: `_batch_utils.py` — canonicalization helper + fallback table + ConfigService list loader

**Files:**
- Modify: `services/_batch_utils.py` (add after `get_dict_config`, ~line 223)
- Test: `tests/unit/test_batch_utils_active_scales.py` (new)

**Interfaces:**
- Produces: `_CANONICAL_SCALE_ORDER: tuple[str, ...]` (module constant, `("fast", "mid", "slow", "extended")`), `ACTIVE_SCALES_FALLBACKS_BY_TF: dict[str, tuple[str, ...]]`, `canonicalize_active_scales(scales: list[str] | tuple[str, ...]) -> tuple[str, ...]`, `get_list_config(cfg_service: ConfigService, key: str, default: list) -> list`

**Why `canonicalize_active_scales` exists (read before implementing):** `ic_engine.py`'s `_compute_apr_snapshot_key()` serializes dict-valued `ICEngineConfig` fields as `",".join(f"{k}={value[k]}" for k in sorted(value))` — it sorts the outer dict by tf, but does **not** sort a tuple *value*. If an operator edits `alpha.ic.active_scales.1h` via the `/config/parameters` dashboard to `["mid","fast"]` (semantically identical to `["fast","mid"]`, just reordered), an unsorted tuple would produce a *different* fingerprint string for an unchanged active set, triggering a spurious full recompute of every 1h cell. Fixing this inside `_compute_apr_snapshot_key()` would mean special-casing tuple-valued dict entries in a function shared by every other COMPUTATIONAL field — broader blast radius than necessary. Instead, `canonicalize_active_scales()` normalizes at the point of load: whatever order the configured JSON array has, always return a subset of `_CANONICAL_SCALE_ORDER` in that fixed canonical order. This makes `active_scales.{tf}` a well-defined *set* (order-independent) rather than an ordered list, which is also the correct mental model — the configured JSON array's order was never meant to carry meaning.

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests: services/_batch_utils.py's canonicalize_active_scales() and
ACTIVE_SCALES_FALLBACKS_BY_TF (per-tf active-scale-set design, 2026-07-30 spec)."""

from __future__ import annotations

import pytest

from services._batch_utils import (
    ACTIVE_SCALES_FALLBACKS_BY_TF,
    canonicalize_active_scales,
)


def test_canonicalize_preserves_canonical_order_regardless_of_input_order():
    assert canonicalize_active_scales(["mid", "fast"]) == ("fast", "mid")
    assert canonicalize_active_scales(["extended", "fast", "slow", "mid"]) == (
        "fast",
        "mid",
        "slow",
        "extended",
    )


def test_canonicalize_accepts_tuple_input():
    assert canonicalize_active_scales(("mid", "fast")) == ("fast", "mid")


def test_canonicalize_deduplicates():
    assert canonicalize_active_scales(["fast", "fast", "mid"]) == ("fast", "mid")


def test_canonicalize_rejects_unknown_scale_name():
    """Silent wrong answers are worse than loud crashes (CLAUDE.md) -- a typo'd
    scale name (e.g. 'fsat') must raise, not silently produce a smaller active set."""
    with pytest.raises(ValueError, match="fsat"):
        canonicalize_active_scales(["fsat", "mid"])


def test_canonicalize_empty_input_returns_empty_tuple():
    assert canonicalize_active_scales([]) == ()


def test_active_scales_fallbacks_cover_all_four_tfs():
    assert set(ACTIVE_SCALES_FALLBACKS_BY_TF.keys()) == {"5m", "15m", "1h", "1d"}


def test_active_scales_fallback_1h_excludes_slow_extended():
    """1h's slow/extended have 0.000 measured completeness under the current
    same-session gate (see todo 208) -- the fallback reflects today's data, not a
    permanent commitment. Reversible via config alone once todo 208 resolves."""
    assert ACTIVE_SCALES_FALLBACKS_BY_TF["1h"] == ("fast", "mid")


def test_active_scales_fallback_other_tfs_keep_all_four():
    for tf in ("5m", "15m", "1d"):
        assert ACTIVE_SCALES_FALLBACKS_BY_TF[tf] == ("fast", "mid", "slow", "extended")


def test_active_scales_fallbacks_already_canonically_ordered():
    for tf, scales in ACTIVE_SCALES_FALLBACKS_BY_TF.items():
        assert scales == canonicalize_active_scales(scales), (
            f"ACTIVE_SCALES_FALLBACKS_BY_TF[{tf!r}] is not canonically ordered"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_batch_utils_active_scales.py -v`
Expected: FAIL (`ImportError: cannot import name 'ACTIVE_SCALES_FALLBACKS_BY_TF'`)

- [ ] **Step 3: Implement in `services/_batch_utils.py`**

Add immediately after `get_dict_config` (after line 223, before the trailing blank lines at EOF — check current EOF with `tail -5 services/_batch_utils.py` first):

```python
_CANONICAL_SCALE_ORDER: tuple[str, ...] = ("fast", "mid", "slow", "extended")


def canonicalize_active_scales(scales: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    """Normalize a configured active-scale list to _CANONICAL_SCALE_ORDER, deduped.

    The APR value's configured order is never semantically meaningful -- an
    operator editing alpha.ic.active_scales.{tf} via /config/parameters could
    write ["mid","fast"] or ["fast","mid"] and mean the identical active set.
    Canonicalizing here (rather than sorting inside _compute_apr_snapshot_key)
    keeps the fingerprint hash deterministic without special-casing tuple-valued
    dict entries in a function shared by every other COMPUTATIONAL config field.

    Raises ValueError on any name outside _CANONICAL_SCALE_ORDER -- a typo'd scale
    name must fail loud, not silently shrink the active set (CLAUDE.md: silent
    wrong answers are worse than loud crashes).
    """
    scale_set = set(scales)
    unknown = scale_set - set(_CANONICAL_SCALE_ORDER)
    if unknown:
        raise ValueError(
            f"canonicalize_active_scales: unknown scale name(s) {sorted(unknown)} -- "
            f"must be a subset of {_CANONICAL_SCALE_ORDER}."
        )
    return tuple(s for s in _CANONICAL_SCALE_ORDER if s in scale_set)


ACTIVE_SCALES_FALLBACKS_BY_TF: dict[str, tuple[str, ...]] = {
    "5m": _CANONICAL_SCALE_ORDER,
    "15m": _CANONICAL_SCALE_ORDER,
    "1h": ("fast", "mid"),
    "1d": _CANONICAL_SCALE_ORDER,
}
"""Per-tf active-scale set (2026-07-30 design, docs/superpowers/specs/2026-07-30-
per-tf-active-scale-set-design.md). 1h excludes slow/extended: live-measured
0.000 completeness under the current same-ET-session completeness gate (see
LOOKAHEAD_FALLBACKS_BY_TF's docstring above and todo 208). This reflects today's
measured data, not a permanent commitment -- reversible via a single config
change (alpha.ic.active_scales.1h) alone, no code change, if todo 208's
investigation into removing the session gate changes what's measurable. Single
source of truth for ICEngineConfig/EnsembleICConfig's from_apr() -- do not
re-literal this table in either file; import it from here."""


def get_list_config(cfg_service: ConfigService, key: str, default: list) -> list:
    """Read a JSON-array APR key via ConfigService.get_sync(), tolerating either a
    pre-parsed list (the normal case -- load_config_service_sync's _parse_value
    already json.loads()s value_type='json' keys at cache-load time) or a raw JSON
    string (test/fallback default path). Sibling of get_dict_config above -- same
    isinstance-guard shape, list instead of dict."""
    v = cfg_service.get_sync(key, default)
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        return json.loads(v)
    return default
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_batch_utils_active_scales.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add services/_batch_utils.py tests/unit/test_batch_utils_active_scales.py
git commit -m "feat(batch_utils): add canonicalize_active_scales + per-tf active-scale fallback table"
```

---

### Task 2: `ic_engine.py` — `ICEngineConfig` field, method, loading, fingerprint classification

**Files:**
- Modify: `services/ic_engine.py:92-95` (import block), `:462-466` (field block), `:573-584` (add `active_scales_for` method), `:607-629` (`from_apr` loading), `:715-757` (`_COMPUTATIONAL_CONFIG_FIELDS`)
- Test: `tests/unit/test_ic_engine_fingerprint.py` (extend existing file)

**Interfaces:**
- Consumes: `ACTIVE_SCALES_FALLBACKS_BY_TF`, `canonicalize_active_scales`, `get_list_config` from Task 1
- Produces: `ICEngineConfig.active_scales: dict[str, tuple[str, ...]]`, `ICEngineConfig.active_scales_for(tf: str) -> tuple[str, ...]` — Task 3's 12 call sites consume this method directly

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_ic_engine_fingerprint.py`, immediately after the existing `_make_config` helper (after line 71):

```python
def test_make_config_includes_active_scales_default():
    """_make_config's base dict must include active_scales or every existing test
    in this file breaks on ICEngineConfig's field-count growth -- same discipline
    as every prior field addition (see this file's existing base dict)."""
    cfg = _make_config()
    assert cfg.active_scales["1h"] == ("fast", "mid")
    assert cfg.active_scales["5m"] == ("fast", "mid", "slow", "extended")
```

Add a new section after the existing Task 1 tests (after `test_apr_snapshot_key_unchanged_by_cross_sectional_bootstrap_threads_change`, currently ending ~line 149):

```python
# ---------------------------------------------------------------------------
# active_scales field (2026-07-30 per-tf active-scale-set design)
# ---------------------------------------------------------------------------


def test_active_scales_for_returns_canonical_tuple():
    cfg = _make_config()
    assert cfg.active_scales_for("1h") == ("fast", "mid")
    assert cfg.active_scales_for("5m") == ("fast", "mid", "slow", "extended")


def test_apr_snapshot_key_moves_on_active_scales_change():
    """active_scales is COMPUTATIONAL -- excluding a scale changes which cells get
    attempted, so it must move the fingerprint or a stale cell would silently be
    treated as already-correct under the old scale set."""
    cfg_a = _make_config(
        active_scales={
            "5m": ("fast", "mid", "slow", "extended"),
            "15m": ("fast", "mid", "slow", "extended"),
            "1h": ("fast", "mid", "slow", "extended"),
            "1d": ("fast", "mid", "slow", "extended"),
        }
    )
    cfg_b = _make_config(
        active_scales={
            "5m": ("fast", "mid", "slow", "extended"),
            "15m": ("fast", "mid", "slow", "extended"),
            "1h": ("fast", "mid"),
            "1d": ("fast", "mid", "slow", "extended"),
        }
    )
    assert _compute_apr_snapshot_key(cfg_a) != _compute_apr_snapshot_key(cfg_b)


def test_apr_snapshot_key_deterministic_regardless_of_active_scales_tuple_order():
    """An operator reordering the configured JSON array (semantically identical
    active set) must NOT move the fingerprint -- canonicalize_active_scales()
    (called at load time in from_apr, not here) is what guarantees this in
    production; this test proves _compute_apr_snapshot_key itself doesn't need to
    re-sort, AS LONG AS both configs already hold canonically-ordered tuples."""
    cfg_a = _make_config(active_scales={"5m": ("fast", "mid"), "15m": (), "1h": (), "1d": ()})
    cfg_b = _make_config(active_scales={"5m": ("fast", "mid"), "15m": (), "1h": (), "1d": ()})
    assert _compute_apr_snapshot_key(cfg_a) == _compute_apr_snapshot_key(cfg_b)
```

Update `_make_config`'s base dict (line ~58-71) to add `active_scales` — this is a **required** field (no default), so every direct `ICEngineConfig(...)` construction site must supply it:

```python
        lookahead_extended={"5m": 39, "15m": 10, "1h": 60, "1d": 10},
        active_scales={
            "5m": ("fast", "mid", "slow", "extended"),
            "15m": ("fast", "mid", "slow", "extended"),
            "1h": ("fast", "mid"),
            "1d": ("fast", "mid", "slow", "extended"),
        },
        equity_model_enabled=True,
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_ic_engine_fingerprint.py -v`
Expected: FAIL (`TypeError: ICEngineConfig.__init__() got an unexpected keyword argument 'active_scales'`)

- [ ] **Step 3: Add the import in `services/ic_engine.py`**

Current import block (lines 92-95):
```python
    LOOKAHEAD_FALLBACKS_BY_TF,
    ...
    lookaheads_for_tf,
```

Change to:
```python
    ACTIVE_SCALES_FALLBACKS_BY_TF,
    LOOKAHEAD_FALLBACKS_BY_TF,
    ...
    canonicalize_active_scales,
    get_list_config,
    lookaheads_for_tf,
```
(Keep the existing alphabetical-ish grouping the file already uses — check the exact surrounding lines with `sed -n '85,100p' services/ic_engine.py` before editing, since other names are interleaved.)

- [ ] **Step 4: Add the field to `ICEngineConfig`**

After line 466 (`lookahead_extended: dict[str, int]`), add:
```python
    active_scales: dict[str, tuple[str, ...]]
```

- [ ] **Step 5: Add the `active_scales_for` method**

After the existing `lookaheads_for` method (after line 584), add:
```python
    def active_scales_for(self, tf: str) -> tuple[str, ...]:
        """Which scales ic_engine actually attempts computation for on this tf
        (2026-07-30 per-tf active-scale-set design). A scale absent here still has
        a bar-count value in lookahead_{fast,mid,slow,extended} (metadata persists)
        but is never attempted -- distinct from a scale that's active but happens
        to score below a reliability gate at runtime."""
        return self.active_scales[tf]
```

- [ ] **Step 6: Load it in `from_apr`**

After the existing `_lookahead_by_scale` comprehension (after line 613, before `return cls(`), add:
```python
        # Active-scale set per tf (2026-07-30 design) -- which of the four scales
        # ic_engine actually attempts, distinct from the bar-count VALUES above
        # (lookahead_{fast,mid,slow,extended}), which stay populated even for an
        # excluded scale. canonicalize_active_scales() guarantees a deterministic
        # tuple order regardless of how the configured JSON array is written, so
        # _compute_apr_snapshot_key's fingerprint never moves on a semantically-
        # unchanged reorder.
        active_scales = {
            tf: canonicalize_active_scales(
                get_list_config(cfg, f"alpha.ic.active_scales.{tf}", list(fb))
            )
            for tf, fb in ACTIVE_SCALES_FALLBACKS_BY_TF.items()
        }
```

Then add `active_scales=active_scales,` to the `cls(...)` call, immediately after `lookahead_extended=_lookahead_by_scale["extended"],` (line 629).

- [ ] **Step 7: Classify the new field in `_COMPUTATIONAL_CONFIG_FIELDS`**

In the `_COMPUTATIONAL_CONFIG_FIELDS` frozenset (after the `"lookahead_extended"` entry, line 727), add:
```python
        # Which scales are attempted at all for a tf (2026-07-30 design) -- excluding
        # a scale changes which feature_ic_scores rows get written, same class of
        # change as the lookahead bar-count values themselves.
        "active_scales",
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_ic_engine_fingerprint.py -v`
Expected: PASS (all existing + 4 new tests)

- [ ] **Step 9: Run the full existing ic_engine test suite to check nothing else broke**

Run: `.venv/bin/pytest tests/unit/test_hac_ic_sharpe.py tests/unit/test_ic_engine_lifecycle_hook.py -v`
Expected: FAIL — these are the two other direct-construction sites `_make_config`'s docstring already warned about (line 477-479, 539-540). Each needs `active_scales=...` added to its own `ICEngineConfig(...)` call sites.

- [ ] **Step 10: Fix the two other direct-construction test files**

Run `grep -n "ICEngineConfig(" tests/unit/test_hac_ic_sharpe.py tests/unit/test_ic_engine_lifecycle_hook.py` to find every construction site. Add `active_scales={"5m": ("fast","mid","slow","extended"), "15m": ("fast","mid","slow","extended"), "1h": ("fast","mid"), "1d": ("fast","mid","slow","extended")},` to each (match the exact dict Task 2 Step 1 used, for consistency across the test suite).

- [ ] **Step 11: Run full suite again**

Run: `.venv/bin/pytest tests/unit/test_hac_ic_sharpe.py tests/unit/test_ic_engine_lifecycle_hook.py tests/unit/test_ic_engine_fingerprint.py -v`
Expected: PASS

- [ ] **Step 12: Commit**

```bash
git add services/ic_engine.py tests/unit/test_ic_engine_fingerprint.py tests/unit/test_hac_ic_sharpe.py tests/unit/test_ic_engine_lifecycle_hook.py
git commit -m "feat(ic_engine): add ICEngineConfig.active_scales field + fingerprint classification"
```

---

### Task 3: `ic_engine.py` — substitute the 12 `_SCALES` call sites

**Files:**
- Modify: `services/ic_engine.py:162` (definition — keep as fallback-only, see below), `:1833`, `:2188-2189`, `:2222`, `:2330`, `:2337-2338`, `:2400`, `:2744`, `:3033-3034`, `:3094`
- Test: `tests/unit/test_ic_engine_active_scales_boundary.py` (new)

**Interfaces:**
- Consumes: `ICEngineConfig.active_scales_for(tf)` from Task 2
- Produces: nothing new — this task changes internal behavior only, no new public interface

**Correctness invariant (read before implementing):** within any ONE of the four functions below, `config.active_scales_for(tf)` must be called exactly once and bound to a local variable, then that local variable used everywhere the function previously read `_SCALES`. `_compute_symbol_tf` builds a `[n_aligned, n_scales]`-shaped matrix (`return_cols`, `complete_cols`, `n_scales` at lines 2188-2230) whose column order is defined by whatever tuple was iterated at build time; `_compute_one_regime_cell` later reads `returns_sub[:, scale_idx]`/`complete_sub[:, scale_idx]` using `enumerate()` over that same conceptual tuple. Both functions already receive `config` and `tf` as parameters (confirmed by direct inspection), so calling `config.active_scales_for(tf)` independently in each is safe (pure function of frozen, immutable inputs) — the invariant is just "same `tf` string in both places," which is already guaranteed since it's the same call chain. Do not read `_SCALES` (the module constant) directly at any of these sites after this task — Task 3's own boundary test enforces this.

- [ ] **Step 1: Write the failing boundary test**

```python
"""Boundary test: after the 2026-07-30 per-tf active-scale-set design landed, no
bare `_SCALES` module-constant reference should survive in ic_engine.py's compute
functions -- every call site must resolve the active set per-tf via
config.active_scales_for(tf) instead. Mirrors test_market_data_ohlcv_boundary.py's
allow-list pattern."""

from __future__ import annotations

import re
from pathlib import Path

_IC_ENGINE_PATH = Path(__file__).parent.parent.parent / "services" / "ic_engine.py"

# Lines allowed to reference the bare _SCALES name: its own definition, and any
# future explicitly-reviewed exception added here with a comment explaining why.
_ALLOWED_LINE_PATTERNS = (
    r'^_SCALES:\s*tuple\[str, \.\.\.\]\s*=',  # the definition itself
)


def test_no_bare_scales_reference_outside_allow_list():
    lines = _IC_ENGINE_PATH.read_text().splitlines()
    violations = []
    for i, line in enumerate(lines, start=1):
        if "_SCALES" not in line:
            continue
        if any(re.match(pat, line.strip()) for pat in _ALLOWED_LINE_PATTERNS):
            continue
        violations.append((i, line.strip()))
    assert not violations, (
        "Bare _SCALES reference(s) found outside the allow-list -- use "
        f"config.active_scales_for(tf) instead: {violations}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_ic_engine_active_scales_boundary.py -v`
Expected: FAIL (12 violations reported, one per current `_SCALES` call site)

- [ ] **Step 3: `_compute_one_regime_cell` (line 1833)**

Before the existing loop, add a local binding. Current code:
```python
    for scale_idx, scale in enumerate(_SCALES):
```
Change to (add the binding line immediately before, matching this function's existing local-variable style — check `sed -n '1722,1735p' services/ic_engine.py` for exact indentation before editing):
```python
    scales = config.active_scales_for(tf)
    for scale_idx, scale in enumerate(scales):
```

- [ ] **Step 4: `_compute_symbol_tf` (lines 2188-2189, 2222, 2330, 2337-2338, 2400)**

This function uses `_SCALES` five times. Add ONE local binding near the top of the function (find the first use at line 2188, check `sed -n '2061,2075p' services/ic_engine.py` for where local variables are already bound in this function's preamble, add there):
```python
    scales = config.active_scales_for(tf)
```
Then replace each of the five bare `_SCALES` references with `scales`:
- Line 2188: `return_cols = ", ".join(f"return_{s}" for s in scales)`
- Line 2189: `complete_cols = ", ".join(f"complete_{s}" for s in scales)`
- Line 2222: `n_scales = len(scales)`
- Line 2330: `n_scales = len(scales)` (a second, later local `n_scales` binding in the same function — verify via `sed -n '2320,2340p' services/ic_engine.py` whether this is truly a second independent code path or a typo/duplicate; if it's a second cross-symbol-fetch code path within the same function, it needs the same `scales` variable already bound at the top, not a re-derivation)
- Line 2337: `return_cols_cf = ", ".join(f"fr.return_{s}" for s in scales)`
- Line 2338: `complete_cols_cf = ", ".join(f"fr.complete_{s}" for s in scales)`

- [ ] **Step 5: `_compute_one_cross_sectional_cell` (line 2744)**

Same pattern as Step 3:
```python
    scales = config.active_scales_for(tf)
    for scale_idx, scale in enumerate(scales):
```

- [ ] **Step 6: `_compute_cross_sectional_tf` (lines 3033-3034, 3094)**

Same pattern as Step 4 — one binding near the top of the function, three substitutions:
```python
    scales = config.active_scales_for(tf)
```
- Line 3033: `return_cols = ", ".join(f'"fr".return_{s}' for s in scales)`
- Line 3034: `complete_cols = ", ".join(f'"fr".complete_{s}' for s in scales)`
- Line 3094: `n_scales = len(scales)`

- [ ] **Step 7: Run the boundary test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_ic_engine_active_scales_boundary.py -v`
Expected: PASS

- [ ] **Step 8: Run ic_engine's existing unit tests to check nothing broke**

Run: `.venv/bin/pytest tests/unit/ -k "ic_engine" -v`
Expected: PASS. If any test constructs a matrix/mock assuming exactly 4 scales for `1h`, it will need updating here — inspect the failure and fix inline (this is expected surface area, not a plan gap, given the correctness invariant this task changes).

- [ ] **Step 9: Commit**

```bash
git add services/ic_engine.py tests/unit/test_ic_engine_active_scales_boundary.py
git commit -m "feat(ic_engine): resolve active scales per-tf at all 12 _SCALES call sites"
```

---

### Task 4: `ensemble_ic_engine.py` — mirror `EnsembleICConfig`, audit `_select_hold_bars_from_decay`

**Files:**
- Modify: `services/ensemble_ic_engine.py:92` (import), `:165-168` (field block), `:192-200` (add method), `:207-226` (`from_apr` loading)
- Test: extend the file's existing config test (find via `grep -rn "class.*EnsembleICConfig\|_make.*config" tests/unit/test_ensemble_ic*.py`)

**Interfaces:**
- Consumes: `ACTIVE_SCALES_FALLBACKS_BY_TF`, `canonicalize_active_scales` from Task 1, and `_batch_utils.cfg()` (already imported in this file) — NOT `get_list_config` (that's the `ConfigService` idiom; this file's `from_apr(cfg: dict[str, Any])` uses the raw-dict idiom instead, matching its existing `lookahead_fast=_lookahead_by_scale["fast"]` pattern at line 223)
- Produces: `EnsembleICConfig.active_scales: dict[str, tuple[str, ...]]`, `EnsembleICConfig.active_scales_for(tf: str) -> tuple[str, ...]`

**Critical gotcha (read before implementing):** `_batch_utils.cfg(cfg_dict, key, default)`'s JSON-safe branch is `if isinstance(default, (list, dict))`. `ACTIVE_SCALES_FALLBACKS_BY_TF`'s values are **tuples**, not lists — `isinstance((), (list, dict))` is `False`. Passing a tuple default straight into `_cfg()` would silently fall through to the unsafe `type(default)(val)` branch, and `tuple('["fast","mid"]')` splits the raw string into individual characters (the exact documented bug `cfg()`'s own docstring warns about for `list()`). **You must pass a `list(...)` conversion of the fallback as `_cfg()`'s default, never the tuple directly**, then canonicalize the result back to a tuple afterward.

- [ ] **Step 1: Write the failing test**

Find the existing `EnsembleICConfig` test helper first:
```bash
grep -rn "def _make_config\|EnsembleICConfig(" tests/unit/test_ensemble_ic_engine*.py | head -5
```
Add `active_scales={...}` (same dict shape as Task 2 Step 1) to that helper's base dict, matching whatever pattern it already uses for `lookahead_extended`. Add:

```python
def test_ensemble_ic_config_active_scales_for_returns_canonical_tuple():
    cfg = _make_config()  # or whatever this test file's existing helper is named
    assert cfg.active_scales_for("1h") == ("fast", "mid")
    assert cfg.active_scales_for("5m") == ("fast", "mid", "slow", "extended")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ic_engine*.py -k active_scales -v`
Expected: FAIL (`TypeError` or `AttributeError`)

- [ ] **Step 3: Add the import**

At line 92 (`from services._batch_utils import LOOKAHEAD_FALLBACKS_BY_TF, connect_db_from_url, lookaheads_for_tf`), change to:
```python
from services._batch_utils import (
    ACTIVE_SCALES_FALLBACKS_BY_TF,
    LOOKAHEAD_FALLBACKS_BY_TF,
    canonicalize_active_scales,
    connect_db_from_url,
    lookaheads_for_tf,
)
```

- [ ] **Step 4: Add the field (after line 168, `lookahead_extended: dict[str, int]`)**

```python
    active_scales: dict[str, tuple[str, ...]]
```

- [ ] **Step 5: Add the method (after `lookaheads_for`, after line 200)**

```python
    def active_scales_for(self, tf: str) -> tuple[str, ...]:
        """Mirrors ICEngineConfig.active_scales_for (2026-07-30 design) -- same
        per-tf active-scale semantics, independent frozen dataclass."""
        return self.active_scales[tf]
```

- [ ] **Step 6: Load it in `from_apr` (after the `_lookahead_by_scale` block, after line 213, before `return cls(`)**

```python
        # Active-scale set per tf (2026-07-30 design) -- see ICEngineConfig's
        # identical field for the full rationale. list(fb) NOT fb directly: _cfg()'s
        # JSON-safe branch only triggers on a list/dict default, and
        # ACTIVE_SCALES_FALLBACKS_BY_TF's values are tuples.
        active_scales = {
            tf: canonicalize_active_scales(
                _cfg(cfg, f"alpha.ic.active_scales.{tf}", list(fb))
            )
            for tf, fb in ACTIVE_SCALES_FALLBACKS_BY_TF.items()
        }
```

Add `active_scales=active_scales,` to the `cls(...)` call, immediately after `lookahead_extended=_lookahead_by_scale["extended"],` (line 226).

- [ ] **Step 7: Audit `_select_hold_bars_from_decay`'s own `_SCALES` usage (line 340) — confirm no change needed**

This function's `_SCALES` (defined independently at `ensemble_ic_engine.py:114`, NOT `ic_engine.py`'s copy) is used as: `ordered_scales = [s for s in _SCALES if s in by_scale]`. `by_scale` is built from `cells` — actual `feature_ic_scores` rows fetched for one `(symbol, tf, regime)` group. Once Task 3 ships, `ic_engine` stops writing `1h` `slow`/`extended` rows going forward, so `by_scale` for a 1h group will naturally never contain those keys — `ordered_scales` already degrades correctly via its existing `if s in by_scale` guard, no code change required. Run this confirmation check, don't skip it:
```bash
grep -n "_SCALES\b" services/ensemble_ic_engine.py
```
Expected output: exactly 2 lines — the definition (line 114) and the `ordered_scales` usage (line 340). If more usages exist than these two, stop and re-investigate before continuing (the audit assumption above only holds for this exact usage shape). Leave this file's own `_SCALES` constant untouched — it is a distinct module-level definition from `ic_engine.py`'s, this task does not rename or remove it.

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ic_engine*.py -v`
Expected: PASS (may require adding `active_scales=...` to other direct `EnsembleICConfig(...)` construction sites in this or other test files — same pattern as Task 2 Step 10; find them via `grep -rln "EnsembleICConfig(" tests/unit/`)

- [ ] **Step 9: Commit**

```bash
git add services/ensemble_ic_engine.py tests/unit/test_ensemble_ic_engine*.py
git commit -m "feat(ensemble_ic_engine): mirror active_scales field, confirm decay-walk needs no change"
```

---

### Task 5: Migration — seed `alpha.ic.active_scales.{tf}`

**Files:**
- Create: `production/migrations/271_ic_active_scales.sql` (verify 271 is actually the next free number before writing — concurrent sessions may have landed migrations since this plan was written: `ls production/migrations/ | sort -t_ -k1 -n | tail -3`)

**Interfaces:**
- Consumes: nothing (pure SQL)
- Produces: 4 live `config_schema`/`config_state`/`config_history` rows read by Task 2/4's `from_apr()`

- [ ] **Step 1: Write the migration**, following migration 269's exact structure (schema INSERT, state INSERT, history INSERT, all `ON CONFLICT DO NOTHING`, wrapped in `BEGIN`/`COMMIT`):

```sql
-- Migration 271: alpha.ic.active_scales.{tf} -- per-tf active-scale set
--
-- ic_engine.py's _SCALES was a hardcoded global 4-tuple ("fast","mid","slow",
-- "extended") applied uniformly to every timeframe, even though 1h has zero real
-- observations for slow/extended (0.000 completeness, live-measured 2026-07-30
-- against forward_returns under the current same-ET-session completeness gate --
-- see docs/superpowers/specs/2026-07-30-per-tf-active-scale-set-design.md and
-- todo 208). This key controls WHICH scales ic_engine attempts computation for,
-- per tf -- distinct from alpha.ic.lookahead.{tf}.{scale} (migration 269), which
-- stores the bar-count VALUES and is untouched by this migration.
--
-- 1h excludes slow/extended based on TODAY'S measured completeness, not a
-- prediction about todo 208's still-open investigation into whether the
-- session-boundary gate should exist at all. Reversible via a single config
-- change to this key alone (no code, no migration) if that investigation changes
-- what's measurable for 1h.

BEGIN;

INSERT INTO config_schema (config_key, value_type, description)
VALUES
    ('alpha.ic.active_scales.5m', 'json',
     '[rca_analysis] JSON array of scale names ic_engine.py attempts computation '
     'for on 5m -- subset of ["fast","mid","slow","extended"]. All four active; 5m '
     'has no measured completeness collapse at any tier (see todo 146''s full-corpus '
     'diagnostic). Order in the array is not meaningful -- canonicalized to fast, '
     'mid, slow, extended order at load time regardless of how written here.'),
    ('alpha.ic.active_scales.15m', 'json',
     '[rca_analysis] JSON array of scale names ic_engine.py attempts computation '
     'for on 15m. Same rationale as 5m -- all four active.'),
    ('alpha.ic.active_scales.1h', 'json',
     '[rca_analysis] JSON array of scale names ic_engine.py attempts computation '
     'for on 1h. Excludes slow/extended: live-measured 0.000 completeness under '
     'the current same-ET-session completeness gate (7 bars/session ceiling) -- '
     'see docs/superpowers/specs/2026-07-30-per-tf-active-scale-set-design.md. '
     'NOT a permanent commitment -- reversible via this key alone if todo 208''s '
     'session-gate investigation changes what''s measurable for 1h.'),
    ('alpha.ic.active_scales.1d', 'json',
     '[rca_analysis] JSON array of scale names ic_engine.py attempts computation '
     'for on 1d. Same rationale as 5m -- all four active (1d has no session-'
     'boundary gate at all, per forward_return_writer.py).')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.ic.active_scales.5m', '["fast","mid","slow","extended"]', 1),
    ('alpha.ic.active_scales.15m', '["fast","mid","slow","extended"]', 1),
    ('alpha.ic.active_scales.1h', '["fast","mid"]', 1),
    ('alpha.ic.active_scales.1d', '["fast","mid","slow","extended"]', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.ic.active_scales.5m', 1, '["fast","mid","slow","extended"]',
     'migration_271', 'Seed per-tf active-scale set (2026-07-30 design) -- 5m unaffected.'),
    (NOW(), 'alpha.ic.active_scales.15m', 1, '["fast","mid","slow","extended"]',
     'migration_271', 'Seed per-tf active-scale set (2026-07-30 design) -- 15m unaffected.'),
    (NOW(), 'alpha.ic.active_scales.1h', 1, '["fast","mid"]',
     'migration_271', 'Seed per-tf active-scale set (2026-07-30 design) -- 1h excludes '
     'slow/extended, 0.000 measured completeness. Reversible via this key alone.'),
    (NOW(), 'alpha.ic.active_scales.1d', 1, '["fast","mid","slow","extended"]',
     'migration_271', 'Seed per-tf active-scale set (2026-07-30 design) -- 1d unaffected.')
ON CONFLICT DO NOTHING;

COMMIT;
```

- [ ] **Step 2: Apply the migration**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/271_ic_active_scales.sql`
Expected: `BEGIN` / `INSERT 0 4` (x3) / `COMMIT`

- [ ] **Step 3: Verify live**

Run: `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_key, config_value FROM config_state WHERE config_key LIKE 'alpha.ic.active_scales.%' ORDER BY config_key;"`
Expected: 4 rows, `1h` shows `["fast","mid"]`, the other three show all four scales.

- [ ] **Step 4: Commit**

```bash
git add production/migrations/271_ic_active_scales.sql
git commit -m "feat(migration): seed alpha.ic.active_scales.{tf} (271)"
```

---

### Task 6: Downstream sweep verification + full-suite check

**Files:**
- None modified (verification-only task, per Task 4 Step 7's audit finding that `ops_ic_shrinkage.py` already needs no change)
- Test: full suite

**Interfaces:** none (this task produces no code; it produces a verified, documented absence of further changes needed)

- [ ] **Step 1: Confirm `ops_ic_shrinkage.py` needs no change**

Already audited in Task 4 Step 7's docstring reasoning: `_lookahead_bars_to_scale_by_tf` (line 235) builds its reverse map from `lookaheads_by_tf` (the bar-count VALUES, untouched by this plan), not from any hardcoded scale-count assumption, and todo 202 already made it tf-scoped. Run to confirm no `_SCALES` or hardcoded-4 assumption exists there:
```bash
grep -n "_SCALES\b\|len(.*scale" scripts/ops/alpha/ops_ic_shrinkage.py
```
Expected: no output (or only unrelated matches — inspect manually if anything appears).

- [ ] **Step 2: Confirm no dashboard/API code hardcodes the 4-scale list**

```bash
grep -rn "fast.*mid.*slow.*extended\|active_scales" src/api/ 2>/dev/null
```
Expected: no output, or generic key-driven rendering only (not a hardcoded scale enumeration) — if a hardcoded enumeration IS found, it needs a fix; file it as a new step here rather than skipping.

- [ ] **Step 3: Repo-wide grep sweep for any other `_SCALES`-pattern reference this plan's file-by-file review might have missed**

```bash
grep -rn "_SCALES\b" services/ src/ scripts/ tests/
```
Expected: exactly the two `ic_engine.py`-owned occurrences (definition + Task 3's boundary-test allow-list) and the two `ensemble_ic_engine.py`-owned occurrences (definition + `ordered_scales`, confirmed unchanged in Task 4 Step 7). Anything else found here is new scope — stop and evaluate before proceeding; do not silently expand this task's diff without understanding why grep found it.

- [ ] **Step 4: Run the complete unit test suite**

Run: `.venv/bin/pytest tests/unit/ -q`
Expected: 0 failures.

- [ ] **Step 5: Run `/simplify` on the changed files**

Per this project's Done-Coding SOP, invoke `/simplify` on `services/_batch_utils.py`, `services/ic_engine.py`, `services/ensemble_ic_engine.py` before review.

- [ ] **Step 6: Run `/review`**

Per this project's Done-Coding SOP.

- [ ] **Step 7: Live verification (once merged, NOT part of the unit-test gate)**

This step runs only after the corpus pipeline's paused `ic_engine` step is resumed (per the spec's sequencing note — this plan's changes should land BEFORE that resume, not after). Once `ic_engine` has run against real 1h data:
```sql
SELECT lookahead_bars, count(*) FROM feature_ic_scores
WHERE tf = '1h' AND training_window_end = '<the run's training_window_end>'
GROUP BY lookahead_bars ORDER BY lookahead_bars;
```
Expected: only `lookahead_bars` values corresponding to `fast`(1)/`mid`(2) appear — no rows at `20`(slow)/`60`(extended). This also confirms the fingerprint DELETE-before-INSERT mechanism (`_FINGERPRINT_INVALIDATE_DELETE_SQL`, scoped by `(symbol, tf, regime_scope, training_window_end)` — not by scale) correctly purges any pre-existing stale `slow`/`extended` rows for 1h as a side effect of `active_scales` now being a COMPUTATIONAL fingerprint field, with no separate cleanup script needed.

- [ ] **Step 8: Final commit / branch merge**

Follow CLAUDE.md's Done-Coding SOP steps 4-6 (commit on feature branch → `git checkout main && git merge --ff-only <branch>` → prune worktree). Do NOT push unless explicitly asked.

---

## Self-Review Notes (completed during plan authoring, not a step to execute)

- **Spec coverage:** every decision in `docs/superpowers/specs/2026-07-30-per-tf-active-scale-set-design.md`'s "Design — mechanism" section has a task (Task 1: canonicalization + fallback table; Task 2: `ICEngineConfig` field/fingerprint; Task 3: 12 call sites; Task 5: migration). "Design — values" (1h's exact scale set) is Task 5's migration content. "Downstream sweep" is Task 4 Step 7 (`ensemble_ic_engine.py`, found to need no change beyond the mirrored field) + Task 6 (verification of `ops_ic_shrinkage.py` and the dashboard, both found to need no change). "Rejected alternatives" and "Out of scope" are not implementation items by design.
- **Refinement beyond the spec, not a contradiction:** the spec's text said "Loaded via `_batch_utils.cfg()`'s existing list-default path" for both configs. Direct inspection during planning found this codebase actually has TWO distinct config-loading idioms (`ConfigService.get_sync` for `ICEngineConfig`, raw-dict `_batch_utils.cfg()` for `EnsembleICConfig`) — this plan implements each correctly via its own idiom (`get_list_config` new helper for the former, `_cfg()` with the tuple-to-list gotcha fixed for the latter) rather than forcing one mechanism where the codebase already uses two. This is the kind of precision gap a design spec reasonably leaves to planning.
- **Type consistency:** `ICEngineConfig.active_scales_for(tf) -> tuple[str, ...]` and `EnsembleICConfig.active_scales_for(tf) -> tuple[str, ...]` have identical signatures, matching `lookaheads_for`'s existing precedent of independent-but-identical methods on both frozen dataclasses.
