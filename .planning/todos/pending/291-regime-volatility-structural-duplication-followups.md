# 291 - `regime_volatility` path duplicates several trend-path functions instead of sharing them

**Filed:** 2026-08-09
**Source:** Phase 172 execute-phase `/simplify` gate, reuse/simplification/altitude-angle reviews
**Status:** pending, not blocking

## The gap

Phase 172 generalized the *inner* layers of `services/regime_writer.py`
(`_build_label_map`, `_state_groups_by_vocab`, `_alpha_history_to_regime_probs`,
`_walk_forward_hmm_full`) to take a `vocab` parameter, correctly sharing code between the
legacy trend path and the new volatility path with the trend path byte-for-byte preserved.
It stopped one layer short at three call sites, which got copy-pasted instead of
parameterized — flagged independently by 2-3 review angles each, which is a strong signal:

1. **`_compute_symbol_tf_volatility_walk_forward` is a ~65-line copy of
   `_compute_symbol_tf_walk_forward`** — differs only in two log-event-name strings and the
   row-tuple's probability-column order. Every future fix to walk-forward accumulation
   semantics (duration-reset edge cases, churn-cursor behavior) has to land in two places.
2. **`_fetch_obs_matrix_volatility` is a ~40-line copy of `_fetch_obs_matrix`** — differs
   only in the SELECT column list and which builder it calls; the cursor-streaming/gate
   logic (a documented gotcha) is now stated twice.
3. **`_write_regime_volatility_results` is a ~90-line copy of `_write_regime_results`** —
   now partially addressed (this phase's own `/simplify` pass extracted `col_types`
   derivation into a shared `_regime_family_col_types()` helper), but the surrounding
   write/verify/log structure is still duplicated.

Two smaller structural gaps in the same area, also flagged:

4. **20-element positional worker-args tuple** (`_run_symbol_worker`) is defended by a
   21-line docstring plus a dedicated arity-pinning test rather than replaced with a
   `NamedTuple` — the docstring itself names the failure mode ("a future insertion before
   position 19 shifts every element after it and binds silently").
5. **OTel attribute asymmetry**: `REGIME_WRITER_NULL_REGIME_REMAINING`/
   `REGIME_WRITER_ROWS_UPDATED_TOTAL` are recorded with `{symbol, tf}` for the legacy family
   and `{symbol, tf, regime_column}` for the new one — deliberate (preserves the legacy
   series identity per the code's own comment), but leaves one instrument with two
   incompatible attribute schemas going forward.

## Why deferred, not fixed in the phase's own cleanup pass

Items 1-3 touch HMM-fitting and DB-write hot paths this project treats as correctness-
sensitive (CLAUDE.md's DAG invariants, the repeated emphasis across Phase 172's own plans on
keeping the legacy trend path byte-identical). A same-session structural refactor right after
a 7-plan corpus relabel landed carries more regression risk than the duplication itself
currently costs. Worth doing with dedicated test coverage in its own pass, not as a drive-by.

## Where

- `services/regime_writer.py` — the three duplicated function pairs listed above
- `services/regime_writer.py::_run_symbol_worker` / the pack site (~line 2450) / unpack site
  (~line 2083) — worker-args tuple
