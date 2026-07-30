# Forward-Return Horizon Grid — Is `fast/mid/slow/extended` the Right Shape?

**Version:** 1.1
**Status:** proposal — architecture verdict and staged plan; the per-tf horizon VALUES remain
open pending the empirical characterization run in §6, which is unblocked and ready to run
**Priority:** medium-high (measurement-integrity plumbing; blocks nothing today, but every
future corpus rebuild re-pays the cost of not settling it)
**Milestone:** none — follow-up to todo 208 Step 3, informs todos 209/210/211/214 sequencing
**Last Updated:** 2026-07-30
**Tags:** ic-engine, forward-returns, lookahead, apr, measurement-integrity, todo-208, todo-214
**Author:** Opus 5 (Claude Code research pass, 2026-07-30). Every code claim below was
re-verified against the working tree at commit `8ba7c7e9` (branch
`worktree-per-tf-active-scale-set`); no claim is carried over from todo 208's text without
independent check. No live IC data was consulted — `feature_ic_scores` is empty (see §6).
**Amended by:** Sonnet 5, same day. Two changes: (1) §0.3 originally asserted
`forward_return_writer` had already completed at a specific timestamp — that was checked and
found FALSE at the time (it was still running, ~46% through); corrected below to state the
dependency correctly rather than assert a wrong completion time (it has since actually
completed, confirmed live: `DONE in 2291s`, and `ic_engine` is now running as of this edit).
(2) §6.3's grid-selection rule is replaced with a calendar-anchored version per user direction
(2026-07-30 discussion) — confirmed, independently, that gradient names are a legitimate
*relative* label for smoothing-window indicators (MA/MACD) but not for forward-return horizons,
which need to represent the same real-world time span across every tf to be comparable; the
original rule (select purely by completeness/power, log-spaced) didn't guarantee that. See §6.3
for the resolved rule.

---

## 0. What was independently verified this pass (and what changed the answer)

Three verifications materially changed the conclusion versus what todo 208's design addendum
assumed. Stating them first because the rest of the document depends on them:

1. **`feature_ic_scores` is already keyed on `lookahead_bars` (int), not on a scale name.**
   `production/migrations/156_ic_engine_tables.sql`: PK is
   `(feature_name, symbol, tf, regime, lookahead_bars, training_window_end)`; there is no
   `lookahead` text column on this table at all. The IC *output* grain is already
   horizon-count-native and variable-length ready. `corpus_manifest_verifier.py` Check 3
   likewise compares `set[int]` of bar counts per tf, not scale names.

2. **The "~13 positionally-indexed `_SCALES` call sites in `ic_engine.py`" no longer exist.**
   Today's per-tf active-scale-set merge replaced all of them. Every compute site now binds
   `scales = config.active_scales_for(tf)` (`ic_engine.py:1876, 2159, 2762, 3025`), iterates
   `enumerate(scales)` (`:1877, :2445, :2790`), sizes arrays with `n_scales = len(scales)`
   (`:2264`), and builds SQL column lists from `scales` (`:2232-2233`). The remaining
   positional indexing (`row[1 + j]`, `row[1 + n_scales + j]`, `complete_mat[:, scale_idx]`)
   is already parameterized by `len(scales)` — it is cardinality-agnostic.
   `tests/unit/test_ic_engine_active_scales_boundary.py` enforces that no bare `_SCALES`
   reference survives. **`ic_engine.py` already supports a per-tf grid of 1–4 horizons with
   zero code change.** Only `ensemble_ic_engine.py` still iterates the flat module constant
   (todo 210, P1, a real correctness bug in its own right).

3. **The empirical step todo 208 calls "blocked on the rebuild" is not blocked — and this does
   not depend on where the in-flight rebuild happens to be.**
   `ops_lookahead_horizon_response.py` computes its own forward returns directly from
   `market_data_ohlcv_tradeable` and reads `feature_vectors` + `feature_registry`. It touches
   `feature_ic_scores` for exactly one thing — `MAX(training_window_end)` as a sample cutoff —
   and it already has a `--vintage` flag added precisely to override that when the table is
   empty (`ops_lookahead_horizon_response.py:339-351`). It never reads `forward_returns` at all.
   `feature_vectors` and the OHLCV view were both already fully populated before today's rebuild
   started (today's rebuild only touches `forward_returns` onward) — so the characterization run
   was runnable from the moment this document was requested, independent of `forward_return_writer`'s
   progress. (For the record: `forward_return_writer` has since completed — confirmed live,
   `DONE in 2291s` in `logs/corpus_pipeline/resume_20260730_1240.log` — and `ic_engine` is now
   running. Neither fact changes this point; it was never gated on either.) See §6 for the one
   small script gap that must be closed first.

Also verified: `forward_returns` still has 4 physical column families
(`return_{fast,mid,slow,extended}`, `complete_*`, `*_suspect`); `alpha_ensemble_ic` carries
*both* `lookahead` (text scale name, part of `event_row_id`) and `lookahead_bars` (int);
`docs/foundation/naming-system.md §7` licenses gradient vocabulary at 2, 3, and 4 levels and
explicitly cites "IC lookahead horizons (`return_extended`)" as the 4-level example.

---

## 1. Verdict

**The premise is right about provenance and half right about consequence. I do not recommend
the full refactor todo 208 sketched, and I do not recommend leaving it alone either.**

### 1.1 Where the framing is correct

"Exactly 4, uniform across tfs" was never derived. Migration 159 renamed
`return_1bar/5bar/20bar/60bar` to `return_fast/mid/slow/extended` and seeded four
`[initial_estimate]` APR keys; there is no document anywhere in the repo justifying the
cardinality. Todo 146 re-pointed the *values* per tf and explicitly deferred the *count*.
The count is inherited array-shape convenience. That much is established fact, not a framing
suggestion.

**The sharper version of the criticism — and the one I would actually defend — is a category
error, not a cardinality error.** `naming-system.md §7`'s gradient vocabulary exists for
*tiering a spectrum with semantic labels*, where the label carries meaning independent of the
number behind it (`rsi_fast` vs `rsi_slow` — a reader knows what those mean without knowing
the periods). A forward-return horizon grid is not a semantic tiering; it is a **sampled
numeric axis**. Its points have no meaning other than their bar count. Applying gradient
naming to it produced three downstream defects that a plain numeric axis would never have had:

- **The name is not stable across tfs, but code pins it as if it were.**
  `alpha.ensemble_ic.gate_lookahead = 'fast'` and `ic_engine.py`'s lifecycle hook
  (`:3987-3990`, pinned to `lookahead_mid`) both select cells by *scale name*, across all four
  tfs at once. Post-146, `mid` is 6 bars at 5m (30 minutes), 2 bars at 15m (30 minutes),
  2 bars at 1h (2 hours), and 2 bars at 1d (2 days). Pinning "the mid scale" therefore pools
  four different real horizons under one filter. The `gate_lookahead` default is *accidentally*
  safe only because `fast = 1` on every tf; change it to `mid` and the EIC-04 gate silently
  becomes a cross-horizon average. This is the concrete cost of naming a numeric axis.
- **Two APR key families express one concept.** `alpha.ic.lookahead.{tf}.{scale}` (16 keys)
  plus `alpha.ic.active_scales.{tf}` (4 keys) can represent contradictory states — a scale
  active with no bar count, or a bar count seeded for an inactive scale (which is exactly
  1h's live state today: `lookahead.1h.slow=20` sitting next to what was, until this morning's
  revert, an active-set excluding it). A single ordered list of bar counts makes the
  contradiction unrepresentable.
- **The count is capped at 4 by vocabulary, not by evidence.** §7 has no fifth gradient word.
  If a tf ever needs 5 measurement points, the naming system blocks it, and the natural fix
  (inventing a fifth adjective) makes the category error worse.

### 1.2 Where the framing overreaches

- **"The 4-slot structure is a structural blocker" is no longer true for `ic_engine.py`.**
  Per §0.2, 1–4 per-tf horizons already work today. The blocker is *only* at the >4 boundary,
  and only in three places: `forward_returns`' 4 physical columns, `_batch_utils`'s
  `lookaheads_for_tf(fast, mid, slow, extended, tf)` 4-positional signature plus the four
  matching `ICEngineConfig`/`EnsembleICConfig` fields, and §7's vocabulary.
- **"Let the number of production horizons be whatever the curve says" is the wrong rule, and
  I want to push back on it explicitly.** Todo 208 proposes choosing production horizons at
  points "where the curve's *shape* changes (rises, peaks, decays)." That is selection on the
  dependent variable. Placing measurement points where measured IC is largest, then reporting
  IC at those points as the production estimate, imports winner's-curse bias into the
  production number — the exact bias `ops_lookahead_horizon_response.py`'s own docstring warns
  about for feature shortlisting ("fixes CI miscalibration, NOT winner's-curse selection
  bias"). `docs/foundation/principles.md`'s resist-overfitting stance applies directly.
  **Grid placement should be driven by censoring and statistical power — completeness(h) and
  effective N(h), which are properties of the data-availability process and independent of the
  signal — not by where IC happens to peak.** Where IC peaks is a *finding measured on* the
  grid, and it belongs downstream, in `_select_hold_bars_from_decay`'s already-FDR-and-
  walk-forward-gated decay walk.
- **Denser is not free.** Each production horizon is another IC estimate, another bootstrap CI,
  and another member of the BH-FDR family (currently 249 features x K horizons x regimes).
  Doubling K roughly doubles the family and dilutes every feature's FDR-adjusted p. There is a
  real statistical reason to keep the *production* K small — which is precisely why the
  measurement/decision decoupling in §4 matters more than the cardinality question does.

### 1.3 The recommendation in one paragraph

Replace the **interface** (four scalar named APR keys plus a parallel active-set key, and four
positional config fields) with **one ordered, variable-length list of bar counts per tf**;
retire the scale names to what they actually are — *ordered physical column slots* in
`forward_returns`, i.e. schema identifiers, APR-exempt under CLAUDE.md; and add explicit
bar-count-valued **decision anchors** so the 1–2 points downstream logic consumes stop being
selected by a cross-tf-unstable name. Choose the actual per-tf bar-count VALUES from a **shared
calendar ladder** (one ordered set of real time spans — e.g. ~30 min / ~2 hr / ~1 day / ~1
week — defined once, converted to bar counts per tf, filtered by each tf's own reachability
ceiling) rather than from per-tf-independent log-spacing, so a stored horizon means the same
real-world span everywhere it is comparable at all — see §6.3. Keep the **storage width at 4**
for now and treat widening past 4 as a separate, data-gated decision that no evidence currently
supports. Do not do any of this until the characterization run in §6 exists and the in-flight
rebuild has finished — and when it is done, batch it with todos 209/210/211 into a single
rebuild window (§5).

---

## 2. Proposed architecture

### 2.1 APR key shape

**New (4 keys):**

```
alpha.ic.lookahead_grid.{5m,15m,1h,1d}    value_type='json'
```

Value: a JSON array of positive ints, e.g. `alpha.ic.lookahead_grid.5m = [1, 6, 12, 39]`.
This is CLAUDE.md's APR category 2 ("behavioral lists — lists controlling WHAT the algorithm
processes → APR as JSON"), the same category the just-landed `alpha.ic.active_scales.{tf}`
already uses.

**Retired (20 keys):** `alpha.ic.lookahead.{tf}.{scale}` (16, migration 269) and
`alpha.ic.active_scales.{tf}` (4, migrations 271/272). The list subsumes both: a horizon
absent from the list is not measured, which is exactly what an inactive scale means.

**Key-name note:** todo 208 suggested `alpha.ic.lookahead.{tf}`. Prefer
`alpha.ic.lookahead_grid.{tf}` — `alpha.ic.lookahead.5m` and `alpha.ic.lookahead.5m.fast` are
distinct rows but indistinguishable to any `LIKE 'alpha.ic.lookahead.%'` sweep, and several
consumers (`corpus_manifest_verifier.py:85-93`, `load_apr_dict_async`'s pattern list) do
prefix sweeps. A distinct prefix keeps the transition unambiguous and makes a stale reader
fail loudly (key absent → fallback) instead of silently reading half the family.

**New decision anchors (§4):**

```
alpha.ic.decision_horizon.{tf}     value_type='int'   -- bar count, must be a member of the grid
alpha.decay.lifecycle_horizon.{tf} value_type='int'   -- bar count, must be a member of the grid
```

These replace `alpha.ensemble_ic.gate_lookahead` (currently the string `'fast'`) and
`ic_engine.py`'s hardcoded `lookahead_mid` pin, respectively.

**Validation contract (fail loud at config load, per CLAUDE.md's "silent wrong answers are
worse than loud crashes"):** the grid must be non-empty, strictly ascending after
dedupe/sort, all elements ≥ 1, length ≤ `_MAX_GRID_SLOTS` (4 today), and each decision anchor
must be an element of its tf's grid.

### 2.2 `services/_batch_utils.py`

| Remove | Add |
|---|---|
| `LOOKAHEAD_FALLBACKS_BY_TF: dict[str, dict[str, int]]` | `LOOKAHEAD_GRID_FALLBACKS_BY_TF: dict[str, tuple[int, ...]]` |
| `lookaheads_for_tf(fast, mid, slow, extended, tf)` | `canonicalize_lookahead_grid(values) -> tuple[int, ...]` |
| `ACTIVE_SCALES_FALLBACKS_BY_TF`, `canonicalize_active_scales`, `_CANONICAL_SCALE_ORDER` | `SLOT_COLUMN_NAMES: tuple[str, ...] = ("fast","mid","slow","extended")`; `grid_to_slots(grid) -> dict[str, int]` |

```python
_MAX_GRID_SLOTS = len(SLOT_COLUMN_NAMES)  # 4 — the forward_returns physical width

def canonicalize_lookahead_grid(values: list[int] | tuple[int, ...]) -> tuple[int, ...]:
    """Dedupe + sort ascending + validate. Raises ValueError on empty, non-positive,
    or len > _MAX_GRID_SLOTS. Direct sibling of the just-retired
    canonicalize_active_scales(): same fail-loud contract, same reason for existing
    (a canonical order makes _compute_apr_snapshot_key's fingerprint invariant to a
    semantically-meaningless reorder of the configured JSON array)."""

def grid_to_slots(grid: tuple[int, ...]) -> dict[str, int]:
    """{slot_column_name: lookahead_bars} for the first len(grid) slots, in order.
    THE single adapter between the list-valued interface and the unchanged wide
    forward_returns schema. SLOT_COLUMN_NAMES are physical column identifiers
    (APR-exempt schema identifiers), NOT semantic scale labels — grid[i] lives in
    column return_{SLOT_COLUMN_NAMES[i]} and means nothing beyond that."""
```

`grid_to_slots` returns an insertion-ordered dict, so every existing `for scale, bars in
lookaheads.items()` / `", ".join(f"return_{s}" for s in lookaheads)` construction keeps working
byte-identically. That is deliberate: it is what keeps this a small diff.

### 2.3 `services/ic_engine.py`

- `ICEngineConfig`: delete 5 fields (`lookahead_fast/mid/slow/extended`, `active_scales`),
  add 2 (`lookahead_grid: dict[str, tuple[int, ...]]`,
  `lifecycle_horizon: dict[str, int]`). Update `_COMPUTATIONAL_CONFIG_FIELDS` accordingly —
  `test_ic_engine_fingerprint.py`'s partition assertion fails the build if either new field
  goes unclassified, so no new test is needed for that failure mode. Both are COMPUTATIONAL
  (the grid moves which rows get written; the lifecycle horizon is currently
  lifecycle-hook-only but gets the same conservative treatment `sign_symmetric` already has).
- `lookaheads_for(tf)` / `active_scales_for(tf)` → `grid_for(tf) -> tuple[int, ...]` and
  `slots_for(tf) -> dict[str, int]` (`= grid_to_slots(self.lookahead_grid[tf])`).
- **Compute call sites — mechanical, 2 lines each.** Current shape:
  ```python
  lookaheads = config.lookaheads_for(tf)      # :1806, :2152, :2756
  scales = config.active_scales_for(tf)       # :1876, :2159, :2762, :3025
  for scale_idx, scale in enumerate(scales):  # :1877, :2445, :2790
      lookahead_bars = lookaheads[scale]
  ```
  becomes
  ```python
  slots = config.slots_for(tf)
  for slot_idx, (slot, lookahead_bars) in enumerate(slots.items()):
  ```
  Everything downstream of those two lines — `n_scales = len(...)` (`:2264`),
  `returns_mat[i, j] = row[1 + j]` / `complete_mat[i, j] = row[1 + n_scales + j]`
  (`:2274-2275`), `complete_sub[:, scale_idx]` (`:1903-1904, :2450-2451, :2811-2812`),
  the SQL column-list builders (`:2232-2233` and the context-feature template) — is already
  length-parametric and needs **no change**. This is the §0.2 finding paying off: the array
  reshape this document would have had to propose two weeks ago has already happened.
- Lifecycle hook (`:3987-4010`): replace the `lookahead_mid`-per-tf pin with
  `config.lifecycle_horizon[tf]` and filter on `fis.lookahead_bars` in Python after the fetch,
  exactly as the current code already does (the comment there already documents why the
  per-tf pin happens in Python and not in SQL — that rationale is unchanged).
- Delete the module-level `_SCALES` constant once `ops_vol_normalized_target_ab.py` (todo 209)
  is migrated. Its docstring already flags that dependency.

### 2.4 `services/ensemble_ic_engine.py`

- Same config-field swap as §2.3. Delete the module-level `_SCALES` and
  `_SCALE_RETURN_COLUMNS` — both become `grid_to_slots(config.grid_for(tf))` and
  `{slot: f"return_{slot}" for slot in slots}`.
- `_run_ensemble_ic_worker`'s per-scale loop (`:951-1033`) currently iterates the flat
  `_SCALES` constant instead of the per-tf set. **This is todo 210 — a P1 measurement-integrity
  bug, not a cosmetic one** (its own gate is `np.isfinite(alpha_sub) & np.isfinite(returns_sub)`
  with no `complete_` term, so it will happily write IC rows from returns the completeness flag
  rejects). This refactor fixes it as a side effect, which is an argument for folding 210 into
  this work rather than fixing it twice.
- `_select_hold_bars_from_decay(cells, decay_threshold, scale_to_bars)` →
  `_select_hold_bars_from_decay(cells, decay_threshold)`. The walk currently does
  `by_scale = {c["lookahead"]: c}` then orders by `_SCALES`; it should order by
  `c["lookahead_bars"]` ascending directly. `alpha_ensemble_ic` already carries
  `lookahead_bars` as a NOT NULL column (migration 190:40), so no new data is needed. This
  is a net simplification — the `scale_to_bars` parameter and the `lookaheads_by_tf` dict
  built at `:1349` both disappear.
- `alpha_ensemble_ic.lookahead` (text) and `event_row_id =
  content_key(symbol, tf, regime, lookahead)`: keep the column, redefine it in the migration
  comment as the *slot name*, not a semantic scale. Changing `content_key` to use
  `lookahead_bars` would be more honest but rewrites every existing row's identity for no
  functional gain; not worth it inside this change.

### 2.5 `services/forward_return_writer.py`

- Module-level `_SCALES` → per-tf `slots_by_tf = {tf: grid_to_slots(grid_by_tf[tf])}`.
- `lookaheads_by_tf` (`:704-710`) reads the one list key per tf instead of 4 scalar keys.
- Three call sites currently pass the module constant and must become per-tf:
  `_build_insert_sql(_SCALES)` (`:770` — built once per run; becomes `insert_sql_by_tf`),
  `_emit_coverage(conn, symbols, tfs, _SCALES)` (`:816`), and the `n_scales`-shaped loops
  inside them.
- **`_apply_cross_symbol_corroboration` (`:819`) must keep using all four slot names**, not a
  per-tf subset: it operates table-wide across every tf in one pass, and the
  `return_{slot}_suspect` columns exist regardless of whether a given tf populates them
  (unwritten slots are `false`, so the OR-clause and the per-slot UPDATEs are no-ops for them).
  Passing a per-tf subset here would silently drop a tf's suspect flags from corroboration.
  Worth an explicit comment — this is the one place where "all physical slots" and "this tf's
  active horizons" genuinely differ.
- **New guard (see §5.2): grid provenance.** `forward_returns` inserts with
  `ON CONFLICT (symbol, tf, bar_ts) DO NOTHING`, and the slot→horizon binding lives only in
  APR. If the grid for a tf changes without truncating that tf's rows, slot *i* keeps a stale
  horizon's return while `ic_engine` labels it with the new bar count — every downstream IC
  number is then mislabeled with no error anywhere. Propose: emit a
  `lookahead_grid` integrity fact per `(tf, training_window_end)` via the existing
  `emit_integrity_fact_sync` path (the module already does this for `price_sanity`), and
  refuse to run incrementally for a tf whose last recorded grid differs from the configured
  one unless an explicit `--rebuild-grid` flag is passed (which truncates that tf first).

### 2.6 Other consumers (all already bar-count-native or trivially adapted)

- `src/observability/corpus_manifest_verifier.py` — `_APR_DEFAULT_LOOKAHEADS_BY_TF` /
  `_LOOKAHEAD_SCALES` / `_APR_DEFAULT_ACTIVE_SCALES_BY_TF` collapse to one grid table; Check 3
  already compares `set[int]` of bar counts and needs no logic change.
- `scripts/ops/alpha/ops_ensemble_ic_gate.py`, `ops_ensemble_weight_compare.py` — filter
  `WHERE lookahead_bars = $1` with the per-tf `decision_horizon` instead of
  `WHERE lookahead = 'fast'` across all tfs.
- `services/cross_sectional_spread_tracker.py` — reads `return_fast`/`return_slow` directly
  (`:745-754`). Under slot semantics these are "slot 0" and "slot 2", which is *not* what that
  module means; it wants a short and a long horizon. Give it its own two explicit anchors
  rather than leaving it pinned to slot indices.
- Todos 209 / 211 (`ops_vol_normalized_target_ab.py`, `ops_ensemble_ablation.py`,
  `ops_interaction_primitives_pilot.py`) — already-filed stale-scale-tuple consumers; they
  must be migrated in the same pass or they read a retired key family.

### 2.7 Alternatives considered and rejected

| Option | Verdict |
|---|---|
| **A. Do nothing.** Keep 16+4 scalar keys, re-point values only. | Rejected, but it is the *second*-best option and much better than a premature rewrite. Leaves the name-pinning defect (`gate_lookahead`) and the representable-contradiction defect live, but costs nothing. If §6's data shows all four tfs want ~4 log-spaced points, do only the key consolidation and stop. |
| **B. Widen `forward_returns` to 6–8 named columns.** | Rejected. Same fixed shape, plus §7 has no fifth gradient word — inventing one deepens the category error. If width ever must grow, go to slot-numbered columns (`return_h0..h5`), never more adjectives. |
| **C. Normalize `forward_returns` to long form** (row per `(symbol, tf, bar_ts, lookahead_bars)`). | Rejected for now, on the same grounds the per-tf-active-scale-set spec rejected it: ~4x row multiplication on a hypertable already tracking ~36.8M feature-vector rows, plus a pivot in `ic_engine`'s vectorized numpy fetch path, for cardinality no evidence currently demands. **Re-open condition:** if §6's characterization shows any tf whose usable log-horizon range genuinely needs >4 sample points to characterize, this becomes the right answer and B stays wrong. |
| **D. List-valued APR + fixed 4 physical slots (proposed).** | Accepted. Fixes the interface defects at ~1 day of work and no schema migration, while leaving the storage-width question open and cheap to revisit. |

---

## 3. Effect on todo 214 (the `ic_engine`/`ensemble_ic_engine` duplication)

**Net easier, not harder.** This change deletes two of the duplicated constructs outright
(`_SCALES` and `_SCALE_RETURN_COLUMNS` exist in both files today) and moves the per-tf
resolution into one `_batch_utils` function both engines call — the same shared-resolver
pattern `lookaheads_for_tf` already established and that 214 wants generalized. It also
removes `_select_hold_bars_from_decay`'s dependency on a scale-name→bars dict, which is one
fewer parameter the eventual shared compute core has to thread. The one caution: do not do
214's extraction and this change at the same time. 214's own note ("refactoring the compute
path while its correctness semantics are actively changing would conflate two different kinds
of change") applies verbatim here — this change *is* a semantics change to that path.
Sequence: this first, then 214 on top of settled behavior.

---

## 4. Decoupling measurement from decision — the actual mechanism

Today there is no decoupling: `hold_max_bars` calibration, the EIC-04 gate, the lifecycle
hook, and IC measurement all read the same four slots, and the first three select by *scale
name*. The mechanism to separate them is small and concrete:

**Measurement layer** — `alpha.ic.lookahead_grid.{tf}`, a list of K bar counts (K ≤ 4 today).
`ic_engine` and `ensemble_ic_engine` measure every element and write one
`feature_ic_scores` / `alpha_ensemble_ic` row per horizon, keyed by `lookahead_bars`. K is
chosen by the §6.3 rule (power and censoring), not by signal strength.

**Decision layer** — two scalar, per-tf, bar-count-valued APR anchors:
- `alpha.ic.decision_horizon.{tf}` — the single horizon the EIC-04 gate and any
  single-horizon comparison read. Replaces `gate_lookahead='fast'`.
- `alpha.decay.lifecycle_horizon.{tf}` — the single horizon the lifecycle hook's
  one-row-per-(feature, tf, regime) fetch pins to. Replaces the `lookahead_mid` hardcode.

**The connecting contract** is a load-time validation, not a data flow: each anchor must be an
element of its tf's grid, checked in `from_apr()` and raised as a `ValueError` if violated.
That single assertion is what makes the two layers independently changeable — you can add or
move a measurement horizon without touching any decision, and you can re-point a decision
anchor without re-measuring anything, but you can never end up with a decision reading a
horizon nobody measured.

**`hold_max_bars` is the one consumer that legitimately needs the whole curve, not an anchor.**
`_select_hold_bars_from_decay` walks the horizons in ascending order looking for the first
FDR-and-walk-forward-qualifying cell whose `ic_sharpe` drops below `decay_threshold`, and
returns the preceding horizon's bar count. That walk is the *correct* place for IC-shape
selection, because it is already gated on `passes_fdr AND reliable AND walk_forward_stable`
and already distinguishes a confirmed decay boundary from a right-censored one (todo 088).
Two consequences worth stating plainly:
- The walk needs **K ≥ 3** to ever return a non-censored answer that is not the trivial
  `hold_bars = 1`. A tf whose grid the data collapses to 2 points has effectively opted out of
  empirical hold-horizon calibration and will always report `censored=True`. That is a hard
  floor on K that no IC-curve reading can override, and it is an argument *against* todo 208's
  "1h might genuinely want 2 real points" outcome being treated as costless.
- Because that walk already exists and is already correctly gated, **the case for adding
  production horizons purely to "characterize the curve better" is weak.** Characterization is
  what `ops_lookahead_horizon_response.py` is for, and it needs no production schema at all.
  That is the real decoupling: dense measurement lives in a read-only diagnostic, and only the
  horizons a decision consumes get persisted at corpus scale.

---

## 5. Migration and rollout

### 5.1 Sequencing — it cannot ride the current rebuild

The current rebuild's `forward_return_writer` stage completed today under the existing 4-scale
grid with the corrected (session-agnostic) completeness definition (confirmed live,
`DONE in 2291s`), and `ic_engine` is now running against that output — this is the first real
post-208 measurement of the production grid. (An earlier `ic_engine` invocation in this same
session was deliberately killed before doing real work, to avoid measuring against the
pre-208-fix `forward_returns`; that is not the run in progress now.) So:

- **Do not touch the branch or the pipeline to insert this.** Let `ic_engine` run to
  completion against the grid that is already in `forward_returns`. That run is the first
  post-208 measurement of the production grid and is itself evidence (§6.2).
- Changing the grid changes `forward_returns` column *semantics* (which horizon lives in which
  slot), so it requires a `forward_returns` rebuild for any tf whose grid moves — the same
  discipline todo 146 Step 3 and todo 208 Step 2 both imposed. It cannot be a partial patch.
- **Batch it.** This change, todo 210 (P1, fixed as a side effect), todo 209, and todo 211 all
  touch the same key family and all require the same rebuild. Doing them as one change in one
  rebuild window is one ~27h `ic_engine` run instead of four. Given this is the fourth
  consecutive week of touching this plumbing (146 → 202 → 208 → active-scale-set), rebuild-run
  economics are the dominant cost, not code time.

### 5.2 Staged cutover

**Stage 0 (now, zero production risk, no rebuild):** run the characterization (§6.1). Fix the
one script gap it needs. Nothing in production changes.

**Stage 1 (after the in-flight `ic_engine` run finishes):** cross-check the diagnostic curve
against real production IC at the four current horizons (§6.2). This is the honesty check on
the diagnostic — bounded recent window + Fisher-z versus full history + block bootstrap.

**Stage 2 (one batched change, one rebuild window):** land the APR consolidation, the config
and call-site changes, the decision anchors, the grid-provenance guard, and todos 209/210/211.
Seed the new grid values from the §6.3 rule, with the rule itself written into the migration
description so the choice is auditable rather than eyeballed. Truncate and rebuild
`forward_returns` for any tf whose grid moved; `ic_engine`'s existing fingerprint mechanism
(the grid field is COMPUTATIONAL) forces the corresponding `feature_ic_scores` recompute
automatically.

**Stage 3 (only if Stage 0 demands it):** revisit option C. Do not scope it speculatively.

**A "measure densely first, cut over later" staging is *not* recommended.** It sounds prudent,
but writing a dense grid into production `forward_returns` while downstream still consumes the
old points means either widening the schema first (option B, rejected) or two rebuilds instead
of one. The dense measurement already has a home that costs nothing: the diagnostic script.

---

## 6. Empirical validation plan

### 6.1 Step 0 — available now, not blocked

Contrary to todo 208's "blocked on `feature_ic_scores`" note, `ops_lookahead_horizon_response.py`
needs only `market_data_ohlcv_tradeable`, `feature_vectors`, and `feature_registry`, all
populated, plus a `--vintage` override for the sample cutoff. Use the same
`training_window_end` the rebuild used, `2025-12-24T05:15:00+00:00`.

```
python scripts/ops/alpha/ops_lookahead_horizon_response.py --tf 1h  --allow-overnight \
    --vintage 2025-12-24T05:15:00+00:00 --max-symbols 80
python scripts/ops/alpha/ops_lookahead_horizon_response.py --tf 15m --allow-overnight \
    --vintage 2025-12-24T05:15:00+00:00 --max-symbols 80
python scripts/ops/alpha/ops_lookahead_horizon_response.py --tf 1d \
    --vintage 2025-12-24T05:15:00+00:00 --max-symbols 80
```

**One script gap must be closed first, or the comparison is not apples-to-apples.**
`--allow-overnight` currently rejects 5m and 1d (`_OVERNIGHT_HORIZON_GRIDS` has entries only
for 15m and 1h, and `main()` errors otherwise, `:466-472`). 1d needs no flag — it never had a
gate. **5m does**: without the flag, its default path still applies the same-ET-session
completeness gate that `forward_return_writer` removed this morning, so a default-mode 5m run
now measures a *different completeness definition than production uses*. Add a 5m entry to
`_OVERNIGHT_HORIZON_GRIDS` (bars-per-session 78; multi-day points at 78/156/390/780 mirroring
the 1,2,5,10-day spacing the 15m/1h grids already use) and allow the flag for it. Small,
read-only-script-only change; it does not require a rebuild and can precede everything else.

### 6.2 What to look for

Read the three reported columns *together*, never the IC magnitude alone (the script's own
header says so):

1. **`completeness` vs horizon.** Post-208 this should now stay near 1.0 for every tf until
   the corpus tail. If 1h's `complete_slow`/`complete_extended` do not move off the 0.000 that
   todo 208 recorded pre-fix, the gate removal did not take effect and everything else is moot.
   This is the cheapest possible regression check on this morning's fix.
2. **`n_valid` after per-horizon stride subsampling** (`stride = max(min_stride, h)`). This
   falls roughly as 1/h and is the real ceiling on how long a horizon can be measured at all.
   The largest h where `n_valid ≥ min_reliable_n` (100) is each tf's **usable ceiling `h_max`**.
3. **`median_ci_halfwidth` vs `median_abs_ic`.** The horizon where the half-width overtakes
   the point estimate is the statistical noise floor. Note this is Fisher-z by default and
   Fisher-z is already documented as miscalibrated on this corpus (~30% canary hit rate) — use
   it for *shape*, and re-check any specific horizon with `--features <shortlist> --bootstrap`.
4. **`canary_raw_sig`** across horizons — if the known-null controls light up persistently
   rather than at ~5%, the CI is miscalibrated at that horizon and its numbers are unusable
   regardless of what the IC column says.

### 6.3 The pre-registered grid-selection rule (write this down *before* looking at IC)

**Resolved 2026-07-30 (calendar-anchoring amendment — see header).** Per §1.2, placement must
key on availability and power, not on signal. That alone is not sufficient: log-spacing each
tf's grid independently by power would still let "the 2nd point" mean an unrelated real-world
span at every tf — the exact category error §1.1 already condemned in the *names*, just
reappearing one level down in the *selection method*. A forward-return horizon has to represent
the same real-world time span across every tf to be a meaningful, comparable measurement — that
is the whole point of measuring it, and it is not true of a smoothing window (§1.1's MA/MACD
contrast: a "fast" vs "slow" moving average is a legitimate relative label because nothing
requires the absolute period to mean the same thing across timeframes; a "what happens next"
question does require that, because it is the actual object a portfolio decision — hold this
position 30 minutes vs. a week — is asking about). The rule below wraps the original
availability/power gate around a shared calendar ladder instead of replacing it:

1. **Define one calendar ladder, shared across every tf, chosen once.** A geometrically-spaced
   sequence of real time spans — the exact rungs are a calibration detail to pin down against
   §6.1's actual data, not asserted here, but should land roughly 3–5x apart and span "the next
   few bars" through "several trading sessions": something in the shape of ~30 min, ~2 hr, ~1
   trading day, ~1 week. Defined once, not per tf — that is the entire fix.
2. **Convert each rung to a bar count per tf** using that tf's own bar interval and a ~6.5-hour
   trading session (this codebase's existing working assumption — 5m: 78 bars/session, 15m: 26
   bars/session, 1h: ~7 bars/session, 1d: 1 bar/session, per todo 208's own numbers). Sub-day
   rungs convert directly (`target_minutes / bar_interval_minutes`); multi-day rungs convert via
   `bars_per_session × trading_days`. Round to the nearest whole bar.
3. **A rung finer than a tf's own bar interval does not exist for that tf — it is dropped, not
   approximated.** 1h cannot express "30 minutes ahead"; its native resolution is coarser than
   that rung. This is why per-tf participation on the shared ladder is naturally sparse rather
   than forced-uniform: 5m likely reaches every rung; 1d likely reaches only the longest one or
   two. Sparse-but-shared beats dense-but-incomparable.
4. **Apply the original reachability gate to the converted bar count, unchanged:** discard a
   rung whose bar count exceeds `h_max(tf)` (the completeness/power ceiling from §6.2), and snap
   to the nearest dense-grid horizon actually measured in the characterization run.
5. **Always include native 1-bar resolution** as the finest point — same rationale as before:
   the shortest executable horizon, the one point every tf can express identically in bar terms,
   and what `gate_lookahead` already and safely assumes. (1-bar is, not coincidentally, also
   where every tf's own native resolution rung would land if it were on the shared ladder — the
   two rules agree here, not just coexist.)
6. **Cap at K ≤ 4** (physical slot width). **Floor at K ≥ 3 where reachable** —
   `_select_hold_bars_from_decay` needs 3 points to ever return a non-censored answer (§4). If
   fewer than 3 ladder rungs are reachable for a tf, that tf has opted out of empirical
   hold-horizon calibration regardless of selection method — a real, pre-flagged possibility
   (§4's note on todo 208's "1h might genuinely want 2 points"), not a failure of this rule.

Neither half of this is sufficient alone: pure log-spacing-by-power (the original rule) can
produce four horizons with no shared real-world meaning across tfs; a calendar ladder with no
reachability gate would happily seed a horizon a tf's data cannot reliably support. The two
together are the actual answer — comparable AND measurable.

**Confirms this design if:** `h_max` and the noise-floor crossing differ materially across tfs
(so a per-tf-derived grid is doing real work, not just relabeling a grid that would have come out
the same anyway), *and* completeness now extends well past the session boundary at 1h/15m (so
the ceiling is data-length-bound, not session-bound), *and* the resulting per-tf grids, once
converted back to calendar time, actually land near the shared ladder rather than requiring the
ladder itself to be re-tuned per tf (if every tf's reachable ceiling forces a wildly different
ladder, the "shared" premise itself needs revisiting, not just the grid).

**Refutes / de-scopes this design if:** all four tfs land on `K = 4` with roughly the same
log-spacing shape after normalizing for bars-per-session. In that case the fixed-4 grid was
accidentally right, and the correct outcome is the cheap subset of §2 only — consolidate 20
APR keys into 4, add the two decision anchors (the name-pinning defect in §1.1 is real
regardless of what the curve says), re-point the bar-count values, and skip everything else.
**That is a genuinely possible outcome and should not be argued away.**

### 6.4 Cross-check once `feature_ic_scores` repopulates

Compare the diagnostic's four production horizons against the real `feature_ic_scores` rows
for the same `(tf, lookahead_bars)`. The diagnostic uses a bounded recent window
(`--max-bars-per-symbol 20000`), up to 30–80 symbols, pooled regimes, and Fisher-z; production
uses full history, all symbols, regime strata, and a circular block bootstrap. Agreement in
*shape* validates using the diagnostic to place the grid. Disagreement in shape means the
diagnostic is not a valid instrument for this decision and the grid must be re-derived from
production rows directly — a slower loop, but the correct one.

---

## 7. Sizing and risk

### 7.1 Size

**Stage 0:** hours. One `_OVERNIGHT_HORIZON_GRIDS` entry plus four read-only runs.

**Stage 2:** roughly one focused day of code, plus one rebuild window (~27h `ic_engine`,
unattended). Touched: `_batch_utils.py` (net −1 function, +2), `ic_engine.py` (config fields,
~7 call sites at 2 lines each, fingerprint classification, lifecycle-hook anchor),
`ensemble_ic_engine.py` (same swap, plus todo 210's loop fix and `_select_hold_bars_from_decay`
simplification), `forward_return_writer.py` (per-tf slot derivation, per-tf insert SQL, the
provenance guard), `corpus_manifest_verifier.py`, one migration, the three ops scripts from
todos 209/211, and ~8 test files (`test_ic_engine_fingerprint.py`,
`test_ic_engine_active_scales_boundary.py` → renamed/retargeted, `test_ensemble_ic_config.py`,
`test_forward_return_writer.py`, `test_batch_utils_active_scales.py` → replaced,
`test_corpus_manifest_verifier.py`, `test_ensemble_ic_decay.py`,
`test_ic_engine_compute_split.py`).

It is a *small* change with a *wide* blast radius — the diff is mostly mechanical, but it
crosses the measurement layer's fingerprint, schema semantics, and half a dozen ops scripts.

### 7.2 Risks, most severe first

1. **Silent slot/horizon mismatch (highest).** `forward_returns` inserts
   `ON CONFLICT DO NOTHING` and stores no record of which horizon each slot holds. Change the
   grid without truncating and slot *i* keeps the old horizon's returns while `ic_engine`
   labels them with the new bar count. Nothing errors; every downstream IC number is silently
   wrong. `ic_engine`'s fingerprint protects `feature_ic_scores` from staleness but knows
   nothing about `forward_returns`' contents. **Mitigation is mandatory, not optional:** the
   grid-provenance integrity fact plus incremental-run refusal in §2.5, and a full truncate +
   rebuild of any tf whose grid moves.
2. **Overfitting the grid to noise.** Addressed structurally by §6.3 — select on
   completeness/N (properties of data availability), never on measured IC. If that rule is
   abandoned mid-flight in favour of "the curve peaks at 12 bars, put a point there," this
   change becomes net-negative and should not ship.
3. **FDR family inflation.** Every added production horizon dilutes every feature's
   BH-adjusted p across the whole family. The `K ≤ 4` cap is doing real statistical work, not
   just respecting a schema width.
4. **Churn cost.** Fourth consecutive change to this plumbing in a week, each needing a
   corpus rebuild. The mitigation is the batching in §5.1 — and the honest acknowledgment that
   the do-nothing option (§2.7 A) is defensible if §6 comes back saying the current grid is
   already near-optimal.
5. **`alpha_ensemble_ic.lookahead` identity.** Keeping the text column as a slot name is
   pragmatic but leaves a name in a primary-key-adjacent position that no longer means what a
   reader expects. Mitigate with an explicit migration comment; do not silently redefine it.
6. **Losing the `gate_lookahead` accident.** The EIC-04 gate is safe today only because
   `fast = 1` on every tf. If the per-tf anchors in §4 are implemented but any tf's grid
   subsequently drops 1 from its first slot, the anchor validation catches it loudly. Without
   the anchors, the same change is silent. This is an argument for doing the anchor half even
   in the minimal (§6.3-refuted) scenario.

---

## 8. Bottom line

The 4-tier `fast/mid/slow/extended` grid is not structurally blocking anything in
`ic_engine.py` any more — today's per-tf active-scale-set merge already made the compute path
cardinality-agnostic from 1 to 4, and `feature_ic_scores` was always keyed on `lookahead_bars`
rather than a scale name. What is genuinely wrong is narrower and more specific than "the
4-slot structure": a **sampled numeric axis was given semantic gradient names**, which produced
a cross-tf-unstable identity that three decision consumers still pin on, two APR key families
that can contradict each other, and a cardinality cap set by vocabulary rather than evidence.

Fix the interface — one ordered list of bar counts per tf, plus explicit bar-count decision
anchors validated as grid members. Leave the storage width at 4 until data says otherwise.
Choose grid points by censoring and power, never by where IC looks best — **and choose the
underlying calendar targets from one shared ladder, not per-tf independently**, so a stored
horizon means the same real-world span at every tf it's reachable for; the same category-error
argument that killed gradient names for returns (§1.1) applies one level down to how the values
themselves get picked. And do none of it until the characterization run — which is available
today, not blocked — says whether the per-tf grids actually differ enough to be worth a rebuild
window.

---

## References

- `.planning/todos/pending/208-intraday-same-session-forward-return-gate-inconsistent-with-trade-construction.md`
  — the proposal this document stress-tests; §1.2 disagrees with its Step-3 selection method
- `.planning/todos/pending/146-lookahead-grid-per-tf-recalibration.md` — the per-tf bar-count
  grid this would supersede
- `.planning/todos/pending/{209,210,211,214}-*.md` — the four already-filed consumers/refactors
  that must be sequenced with this
- `docs/superpowers/specs/2026-07-30-per-tf-active-scale-set-design.md` — the APR-driven per-tf
  config pattern this proposal extends (and whose option-B/option-C rejections it upholds)
- `docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md` Q1 — the original
  finding that the grid was never tf-scaled
- `docs/foundation/adaptive-parameter-registry.md`; `CLAUDE.md` APR mandate category 2 —
  behavioral lists as JSON
- `docs/foundation/naming-system.md §7` — the gradient vocabulary whose 4-level entry is the
  proximate source of "exactly 4"
- `production/migrations/156_ic_engine_tables.sql` (`feature_ic_scores` PK on `lookahead_bars`),
  `159_forward_returns_gradient_columns.sql` (the original rename), `190_alpha_ensemble_ic.sql`
  (`lookahead` text + `lookahead_bars` int), `269`/`271`/`272` (the current key families)
- `scripts/ops/alpha/ops_lookahead_horizon_response.py` — the characterization instrument;
  `--vintage` is why §6.1 is not blocked
