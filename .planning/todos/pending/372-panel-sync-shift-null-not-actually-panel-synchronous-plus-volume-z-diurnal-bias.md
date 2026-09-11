---
status: pending
priority: P1
filed: 2026-09-09
source: AGY adversarial review round 3 of the H-B ("confirmed_reversal") redesign
  (docs/plans/2026-09-06-extreme-volume-divergence-h-b-redesign-fable.md), two findings
  verified against source independently before filing, not accepted on the review's say-so
---

# Two findings from H-B review round 3 that reach beyond H-B: `Panel.sync_shift_null_p` isn't panel-synchronous when per-symbol active-date counts vary, and `volume_z` has no diurnal detrending

## Status (2026-09-11)

Finding 1 fixed in code: `_panel_synchronous_shift_indices` shifts on the shared
`self.calendar` index rather than `k % m` per symbol. Regression tests
(`tests/unit/test_alpha_score_residual_panel_sync_shift.py`, 3 tests) pass. Design by
Fable; NOT yet independently adversarially reviewed (AGY/Codex both rate-limited the
session the fix landed). Finding 2 (`volume_z` diurnal detrending) untouched. Stays
`pending` until both land.

## Finding 1: `Panel.sync_shift_null_p`'s per-symbol block shift breaks the "panel-synchronous" property it's named for

`scripts/analysis/alpha_score_residual_single_security_15m.py:199-230`, `sync_shift_null_p`:

```python
n_cal = len(self.calendar)                    # panel-wide unique date count
ks = rng.integers(1, n_cal, size=n_null)       # ONE shift k per replicate, panel-wide
...
def _one_rep(i):
    k = int(ks[i])
    for s in self.family:
        starts, counts, sl = self.sym_blocks[s]
        m = len(starts)                        # THIS SYMBOL's own active-date count
        perm = (np.arange(m) + k % m) % m       # shift applied mod m, not mod n_cal
```

Verified directly against source (not from the review's assertion): `k` is drawn once per
null replicate and is meant to represent one common calendar-date shift applied to the whole
panel ("panel-synchronous" — every symbol's data paired with a different date's returns, same
date-offset for all symbols, preserving same-day cross-sectional correlation structure under
the null). But the actual permutation for symbol `s` is `k % m` where `m = len(starts)` is
**that symbol's own count of active dates** (dates on which `s` has at least one row in the
panel). When `m` varies across symbols — which it will, especially for any construction built
on a sparse, per-symbol-varying event set like H-B's `E` — the same nominal `k` maps to a
different effective calendar-date offset per symbol. The null no longer pairs all symbols with
one shared alternate date; it silently degrades toward an independent per-symbol shift,
losing the cross-sectional-correlation protection the panel-synchronous design was meant to
provide (independent per-symbol nulls can understate the true false-positive rate when returns
are correlated across symbols on the same date — exactly the failure mode "panel-synchronous"
exists to prevent).

**Scope:** this is shared, already-used testing machinery, not new to H-B.
`alpha_score_residual_single_security_15m.py`'s own already-closed result (workstream 2,
FAIL verdict, 2026-09-03, see memory `project_personal_scale_edge_program.md`) used this same
method. **Not claiming that result is wrong** — its panel was likely closer to a dense daily
series with modest per-symbol date-count variance (holidays/gaps), a much smaller version of
the effect than H-B's sparse event panel would produce, and the FAIL verdict there was driven
by a near-zero effect size (0/231 symbols BY-FDR qualifying), not a borderline significance
call this null-shift gap would plausibly flip. But this needs an actual check, not an assumption
either way, before citing that result's null test as airtight, and it hard-blocks trusting
H-B's own null test as currently speced (H-B's per-symbol qualifying-date-count variance will
be large by construction).

## Finding 2: `volume_z` has no diurnal/session-boundary detrending

`src/intelligence/feature_factory.py:1046-1055` (`_fixed_window_zscore_series`) and
`:2165` (`_volume_z_series_full`): a plain rolling z-score over the flat per-bar volume
array, with no awareness of session boundaries or time-of-day. Verified directly against
source. At 15m (26 bars/session), a bar at 9:45am-10:15am has most of its trailing 20-bar
window filled with the *previous session's* low-volume afternoon bars, then diluted by the
open's structurally elevated volume (the standard U-shaped intraday volume "smile") — meaning
`volume_z` is systematically inflated in the first ~45-60 minutes of each session for reasons
having nothing to do with genuine volume anomaly.

**This affects H-A too**, not just H-B — H-A's `extreme_volume_divergence_t` statistic reads
`volume_z_t` at the exact bar it gates on, with the same lack of detrending. H-A has already
cleared two AGY review rounds without this being caught. Not reopening H-A's already-reviewed
design over this now, but it should be checked (a reported, ungated morning-vs-afternoon
sub-panel, matching the fix locked for H-B) before H-A's Track 1 results are trusted, not
assumed clean because two reviews already passed.

## What to do

1. **Finding 1**: decide a fix for `Panel.sync_shift_null_p` — shift on the shared
   `self.calendar` index directly (map `k` to a real calendar-date offset, then look up each
   symbol's own blocks for those shifted dates, rather than `k % m` per symbol) rather than a
   per-symbol modular shift. Needs its own design/review pass given it's shared, already-tested
   infrastructure — not a quick inline patch. Before fixing, check how much `m` actually varied
   across symbols in the closed `alpha_score_residual` run (cheap, from already-persisted data)
   to bound how exposed that closed result actually was — informational, not gating this fix.
2. **Finding 2**: add a reported (ungated) morning-vs-afternoon sub-panel check to both H-A's
   and H-B's Track 1 execution before either is trusted, matching AGY round 3's amendment 3 for
   H-B.

## Verification

- `Panel.sync_shift_null_p` read directly, `scripts/analysis/alpha_score_residual_single_security_15m.py:199-230`.
- `_fixed_window_zscore_series`/`_volume_z_series_full` read directly,
  `src/intelligence/feature_factory.py:1046-1055`, `:2165`.
- Both independently re-verified against source during the H-B redesign's round 3 review,
  2026-09-09 — not accepted from the review's assertion alone.
