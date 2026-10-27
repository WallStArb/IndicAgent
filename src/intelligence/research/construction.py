"""The construction rule: a book forecast to position weights (unified design 4.3, 12.3).

One protocol over the five rules portfolio.py implements. `weights` gives the positions a book
holds (S8, the member evidence runs); `returns` is the evaluate() construction slot, {name:
per-row gross return}, used by the shift null and the power check. Each rule wraps the
portfolio.py function unchanged, so a rule reproduces it bit for bit. During discovery the
construction is fixed at R1 (rank_vol_neutral); the other four are selectable by a spec for the
construction attempt at capital readiness.
"""

from __future__ import annotations

import dataclasses
from typing import Protocol

import numpy as np

from src.intelligence.research.evaluate import rows_config
from src.intelligence.research.portfolio import (
    FIXED_SIGN_ARM,
    RANK_VOL_NEUTRAL_ARM,
    CovariancePlan,
    PortfolioConfig,
    arm_returns,
    arm_weights,
    fixed_sign_returns,
    fixed_sign_weights,
    rank_vol_neutral_returns,
    rank_vol_neutral_weights,
)
from src.intelligence.research.spec import BookSpec, FamilySpec


class ConstructionRule(Protocol):
    @property
    def name(self) -> str: ...

    def weights(
        self,
        forecast: np.ndarray,
        *,
        vol: np.ndarray,
        fwd: np.ndarray | None,
        plan: CovariancePlan | None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """(position weights [n, m], has_position [n]); a row without a position is all zero."""
        ...

    def returns(
        self,
        forecast: np.ndarray,
        fwd: np.ndarray,
        plan: CovariancePlan | None,
        *,
        vol: np.ndarray,
    ) -> dict[str, np.ndarray]: ...


Arrays = np.ndarray


def _positioned(w: Arrays) -> tuple[Arrays, Arrays]:
    """A calibrated arm's [n, m] weights in the protocol's form: a row before the first
    calibration (all NaN) holds no position and is zero; any other NaN stays NaN, loud."""
    has_position = ~np.isnan(w).all(axis=1)
    return np.where(has_position[:, None], w, 0.0), has_position


def _require_plan(rule: str, plan: CovariancePlan | None) -> CovariancePlan:
    if plan is None:
        raise ValueError(f"construction {rule} sizes from a covariance plan; none was given")
    return plan


@dataclasses.dataclass(frozen=True)
class RankVolNeutral:
    """R1: weights from direction * centred rank / trailing vol; ignores `fwd` and `plan`."""

    direction: float
    coverage_floor: int
    name: str = RANK_VOL_NEUTRAL_ARM

    def weights(
        self, forecast: Arrays, *, vol: Arrays, fwd: Arrays | None, plan: CovariancePlan | None
    ) -> tuple[Arrays, Arrays]:
        return rank_vol_neutral_weights(
            forecast, vol=vol, direction=self.direction, coverage_floor=self.coverage_floor
        )

    def returns(
        self, forecast: Arrays, fwd: Arrays, plan: CovariancePlan | None, *, vol: Arrays
    ) -> dict[str, Arrays]:
        return rank_vol_neutral_returns(
            forecast,
            fwd,
            plan,
            vol=vol,
            direction=self.direction,
            coverage_floor=self.coverage_floor,
        )


@dataclasses.dataclass(frozen=True)
class CalibratedArm:
    """One of phase 179's calibrated arms (ic_proportional, vol_normalized, mean_variance):
    sizes from the plan's covariance and an embargoed IC calibration on `fwd`; ignores `vol`.
    `cfg` is in rows (evaluate.rows_config), as plan_covariance's was."""

    name: str
    cfg: PortfolioConfig
    ic_shrinkage_k: float

    def weights(
        self, forecast: Arrays, *, vol: Arrays, fwd: Arrays | None, plan: CovariancePlan | None
    ) -> tuple[Arrays, Arrays]:
        if fwd is None:
            raise ValueError(f"construction {self.name} calibrates on fwd; none was given")
        plan = _require_plan(self.name, plan)
        w = arm_weights(forecast, fwd, plan, self.cfg, self.ic_shrinkage_k)[self.name]
        return _positioned(w)

    def returns(
        self, forecast: Arrays, fwd: Arrays, plan: CovariancePlan | None, *, vol: Arrays
    ) -> dict[str, Arrays]:
        plan = _require_plan(self.name, plan)
        r = arm_returns(forecast, fwd, plan, self.cfg, self.ic_shrinkage_k)[self.name]
        return {self.name: r}


@dataclasses.dataclass(frozen=True)
class FixedSign:
    """The fixed-sign arm: direction * sign(forecast) / sigma from the plan; ignores `vol`."""

    direction: float
    name: str = FIXED_SIGN_ARM

    def weights(
        self, forecast: Arrays, *, vol: Arrays, fwd: Arrays | None, plan: CovariancePlan | None
    ) -> tuple[Arrays, Arrays]:
        return fixed_sign_weights(
            forecast, _require_plan(self.name, plan), direction=self.direction
        )

    def returns(
        self, forecast: Arrays, fwd: Arrays, plan: CovariancePlan | None, *, vol: Arrays
    ) -> dict[str, Arrays]:
        plan = _require_plan(self.name, plan)
        return fixed_sign_returns(forecast, fwd, plan, direction=self.direction)


def resolve_rule(spec: FamilySpec | BookSpec, bars_per_session: int) -> ConstructionRule:
    """The spec's construction rule. The calibrated arms read their calibration from the
    spec's scoring block in rows (the config evaluate() builds), so they need no fields of
    their own."""
    c = spec.construction
    if c.name == RANK_VOL_NEUTRAL_ARM:
        return RankVolNeutral(float(c.direction), c.coverage_floor)
    if c.name == FIXED_SIGN_ARM:
        return FixedSign(float(c.direction))
    cfg = rows_config(spec.scoring.evaluation_config(), bars_per_session)
    return CalibratedArm(c.name, cfg, spec.scoring.ic_shrinkage_k)
