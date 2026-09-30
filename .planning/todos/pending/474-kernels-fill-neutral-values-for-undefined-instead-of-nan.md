---
status: pending
priority: P2
filed: 2026-09-30
source: plan 186-15 review (altitude, no_fill invariant)
---

# Kernel outputs fill a neutral value where the quantity is undefined

## What

The `no_fill` invariant (missing is NaN) holds at the input edge (186-12 made the macro inputs NaN)
but not inside several kernels, which return a neutral number for "undefined". Each of these is
stored as a real reading:

- `poc_dist_atr` 0.0 when there is no POC or the ATR is invalid; `va_position` 0.5 when the value
  area has zero width (`vp_sr.py`, `_NEUTRAL_VP_EXTRA`).
- S/R distance, strength and age columns 0.0 when no pivot cluster exists (`_SR_FALLBACK`).
- `_SWEEP_FALLBACK` and the other SMC fallbacks return 0.0 for "no sweep ever", "no OB in window".
- `cross_tf.py`: `htf_last_log_ret[0] = 0.0` (the `_build_ctf_series` docstring says the first
  bar has no prior bar), `ctf_vwap_align` is computed from closes when a window has no volume
  (VWAP filled with the close), and the `ext_ctf_*` inputs are 0.0 before the first HTF close.

Some of these are a meaningful zero ("no sweep" is a state), some are not ("no POC" is not a
distance of 0). The registry cannot tell them apart, so a consumer cannot either.

## Options

1. Keep the fills and document each. No change to stored values; the ambiguity stays.
2. Undefined is NaN everywhere; the states that are real zeros keep 0.0.
3. Undefined is NaN by default, and a kernel may fill a neutral value only by declaring a
   `neutral_reason` on the output, enforced in the registry (a test lists every declared reason).

## Recommendation

Option 3, together with the nullable-column decision of todo 463 (the `FeatureVector` fields are
non-nullable floats, so NaN cannot be stored until that lands). It changes stored values, so the
golden fixtures regenerate in their own commit with the reason in the message, after a
per-column review of which fills are real states. Do it inside the 186-25 rebuild window so the
regenerated columns are written once.

## Steps

1. List every fill with its state (real zero or undefined) in a table in the todo.
2. Add `neutral_reason` to the `Kernel` output contract and the registry check.
3. Switch the undefined ones to NaN behind a failing test per column.
4. Regenerate the goldens in a separate commit; run the IC impact check on the changed columns.
