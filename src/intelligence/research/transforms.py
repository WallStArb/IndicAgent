"""Panel transforms: the S0 source panel to the analysis panel members and S1 see, resolved once
from a spec's `panel.transform` (None is the identity).

A transform owns everything that depends on the analysis panel's shape: how the source becomes
the analysis panel, how S1 residualizes its bar returns and its forward target, which rows S3
must always probe, and the causality probe of the transform itself. The runner calls these and
never branches on which transform it holds.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable

import numpy as np

from src.intelligence.research import legs
from src.intelligence.research.factors import FactorSpec, residual_returns
from src.intelligence.research.panel import Panel, bar_returns, forward_returns


def _identity_s1_bar(panel: Panel, factor_spec: FactorSpec) -> np.ndarray:
    return residual_returns(
        bar_returns(panel), bars_per_session=panel.bars_per_session, spec=factor_spec
    ).residual


def _identity_s1_target(panel: Panel, horizon: int, factor_spec: FactorSpec) -> np.ndarray:
    raw = forward_returns(panel.open, horizon, panel.session, closes=panel.close)
    return residual_returns(
        raw, bars_per_session=panel.bars_per_session, horizon=horizon, spec=factor_spec
    ).residual


def _legs_s1_target(panel: Panel, horizon: int, factor_spec: FactorSpec) -> np.ndarray:
    if horizon != 1:
        raise ValueError(f"a session-legs panel's target is horizon 1, got {horizon}")
    return legs.target_residuals(panel, factor_spec)


def _identity_apply(source: Panel, source_hash: str | None) -> Panel:
    return source


def _no_extra_rows(panel: Panel) -> np.ndarray:
    return np.empty(0, dtype=np.int64)


def _legs_apply(source: Panel, source_hash: str | None) -> Panel:
    return legs.session_legs(source, source_hash=source_hash)


def _legs_probe(source: Panel, rows: np.ndarray, seed: int) -> None:
    legs.transform_causality_probe(source, rows, seed=seed)


def _legs_probe_rows(panel: Panel) -> np.ndarray:
    """One row 0 and one row 1 (the signal row) of the middle session."""
    mid = panel.n_sessions // 2 * legs.LEGS
    return np.array([mid, mid + legs.SIGNAL_LEG])


@dataclasses.dataclass(frozen=True)
class PanelTransform:
    name: str | None
    # source panel, source content hash -> analysis panel
    apply: Callable[[Panel, str | None], Panel]
    s1_bar: Callable[[Panel, FactorSpec], np.ndarray]
    s1_target: Callable[[Panel, int, FactorSpec], np.ndarray]
    # analysis panel -> rows S3 always probes, added to guards.probe_rows
    extra_probe_rows: Callable[[Panel], np.ndarray]
    # source sub-panel, analysis rows, seed -> None or GuardFailure; None when the analysis
    # panel is the source (nothing to probe beyond S1)
    probe: Callable[[Panel, np.ndarray, int], None] | None


IDENTITY = PanelTransform(
    name=None,
    apply=_identity_apply,
    s1_bar=_identity_s1_bar,
    s1_target=_identity_s1_target,
    extra_probe_rows=_no_extra_rows,
    probe=None,
)

SESSION_LEGS = PanelTransform(
    name=legs.TRANSFORM,
    apply=_legs_apply,
    s1_bar=legs.leg_residuals,
    s1_target=_legs_s1_target,
    extra_probe_rows=_legs_probe_rows,
    probe=_legs_probe,
)

_BY_NAME = {t.name: t for t in (IDENTITY, SESSION_LEGS)}


def resolve(name: str | None) -> PanelTransform:
    """The transform a spec's `panel.transform` names (None is the identity)."""
    try:
        return _BY_NAME[name]
    except KeyError as error:
        raise ValueError(
            f"unknown panel transform {name!r}; one of {sorted(map(str, _BY_NAME))}"
        ) from error
