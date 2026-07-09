# 088 — hold_max_bars calibration doesn't distinguish confirmed decay from censored data

Source: `/simplify` altitude review of the 2026-07-09 `_select_hold_bars_from_decay` bug fix
(`services/ensemble_ic_engine.py`).

The fix (same-day) corrected a real bug: the fallback used to hardcode the "extended" (60-bar)
ceiling regardless of whether that scale was ever reliably measured. It now returns
`preceding_bars` — the longest scale actually confirmed non-decaying — instead.

That fix is correct but incomplete in one respect: `_select_hold_bars_from_decay` still returns
a bare `int` in two structurally different situations:

1. **Confirmed decay boundary** — an explicit below-threshold cell was observed; `preceding_bars`
   is the last scale before a confirmed-decaying one.
2. **Censored (no data beyond)** — every qualifying scale stayed above threshold, but we don't
   know if the edge truly persists past `preceding_bars`, or if "extended" (or whichever scale
   would tell us) was simply never measurable (right-censored, the common case given "extended"
   passes FDR in only ~0.5% of cells corpus-wide).

`_calibrate_hold_max_bars`'s median-across-symbols aggregation (`services/ensemble_ic_engine.py`
~line 1085) can't tell these apart — a group of symbols with real decay at bar 5 and a group
merely lacking longer-horizon data at bar 20 get blended into one median with no differentiation
(classic right-censoring-ignored bias). The `config_history` `reason=` string written at
calibration time (~lines 1091-1095) also doesn't record which case applies, even though that
field is this project's own provenance record for exactly this kind of distinction.

**Proposed fix:** have `_select_hold_bars_from_decay` return a small result type (e.g.
`(hold_bars: int, censored: bool)` or a dataclass) instead of a bare `int`, so the caller can
(a) record the censored fraction in the `reason` string, and (b) decide deliberately whether
censored and confirmed values should be pooled in the same median or handled separately.

Not urgent — the 2026-07-09 fix already removed the worse bug (silently claiming confirmed
60-bar persistence with zero evidence). This is a refinement on top of a now-honest baseline,
not a correctness emergency. Worth doing before Phase 142B's frame simulation leans heavily on
these hold_max_bars values for real position-sizing/hold decisions, since silently mixing
confirmed and censored values in a median make in the meantime is optimistic (assumes censored
values skew toward the confirmed-decay behavior rather than understating true persistence).
