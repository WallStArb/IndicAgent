"""Panel-source members and the orthogonalization stage (todo 653; families 9 and 10).

Two additions to the member route, both outside `battery_pass.RUNNER_STATISTIC_FUNCTIONS` so no
recorded battery pass changes its code key (tests pin both keys):

1. `compute_panel_members`: a member with `panel_source` reads a field of the book's own panel (the
   total-return close or the share volume), on the book clock with no alignment, instead of the S1
   residual bar returns. Same call convention as every member, `fn(source, bars_per_session=...,
   coverage_floor=..., **params)`, then the membership mask (non-member cells NaN).
2. `orthogonalize_members`: a pure stage after the members and the mask. Each row's member values
   become their cross-sectional OLS residual on (1, e, |e|), e the S1 residual return summed over
   the member's `sum_sessions` sessions ending at the row. The fit runs over the member names with
   finite values (ledger 2026-11-22h), so a non-member cell can not move a member's residual. A row
   with fewer than `min_names` finite names is NaN.

The runner calls `runner.compute_family_members`, which calls these two functions; a battery for a
family using them calls the same two, so a pass covers the stage (tests pin the function objects).
Pure functions over arrays: determinism and pure_compute hold; every read is row d or earlier.
"""

from __future__ import annotations

import functools

import numpy as np

from src.intelligence.research import membership
from src.intelligence.research.families import volume_shock
from src.intelligence.research.panel import Panel
from src.intelligence.research.spec import FamilySpec, MemberSpec, resolve_member


def panel_source_array(panel: Panel, source: str) -> np.ndarray:
    """The panel field a `panel_source` member reads: [rows, names], NaN where missing."""
    return getattr(panel, source)


def panel_source_members(spec: FamilySpec) -> list[MemberSpec]:
    return [m for m in spec.members if m.panel_source is not None]


def _fn(spec: FamilySpec, m: MemberSpec, bars_per_session: int):
    fn = resolve_member(m.signal)
    if getattr(fn, "needs_session_dates", False):
        raise ValueError(f"member {m.name}: a panel_source member takes no session dates")
    return functools.partial(
        fn,
        bars_per_session=bars_per_session,
        coverage_floor=spec.construction.coverage_floor,
        **m.params,
    )


def compute_panel_members(
    spec: FamilySpec, panel: Panel, *, bars_per_session: int
) -> dict[str, np.ndarray]:
    """S2 for the panel_source members: the member function over the panel field, then the
    membership mask when the panel carries one (as `runner.compute_members` does)."""
    out = {
        m.name: _fn(spec, m, bars_per_session)(panel_source_array(panel, m.panel_source))
        for m in panel_source_members(spec)
    }
    if panel.member is not None:
        out = {
            name: membership.apply_member_mask(alpha, panel.member, bars_per_session)
            for name, alpha in out.items()
        }
    return out


def orthogonalize_members(
    spec: FamilySpec,
    members: dict[str, np.ndarray],
    resid_bar: np.ndarray,
    *,
    bars_per_session: int,
) -> dict[str, np.ndarray]:
    """The stage: members that declare `orthogonalize` are replaced by their per-row residual on
    the trailing sum of `resid_bar` and its absolute value; the others pass through untouched."""
    out = dict(members)
    sums: dict[int, np.ndarray] = {}  # one trailing sum of the S1 residual per window length
    for m in spec.members:
        if m.orthogonalize is None:
            continue
        if bars_per_session != 1:  # the spec refuses a non-1d book at load; this guards callers
            raise ValueError(f"member {m.name}: orthogonalize needs the 1d book clock")
        o = m.orthogonalize
        if o.sum_sessions not in sums:
            sums[o.sum_sessions] = volume_shock.trailing_sum(
                np.asarray(resid_bar, dtype=float), o.sum_sessions
            )
        out[m.name] = volume_shock.residualize_rows(
            members[m.name], sums[o.sum_sessions], min_names=o.min_names
        )
    return out
