"""The horizon rule, the book's fourth part (unified design 4.4; Garleanu and Pedersen 2013).

Partial adjustment toward the construction's target weights, row by row in panel order and across
session boundaries:

    w_t = w_(t-1) + kappa * (w*_t - w_(t-1)),   w*_t = 0 on a row without a target position

Causal: w_t reads w*_s for s <= t only. On a row where no order can execute (`tradable` False,
a grid slot no name traded) the book is held, not adjusted. kappa is a cost device pinned in the
spec before the attempt and never tuned on outcomes; kappa = 1 is the identity (every discovery
book, and a spec writes it by leaving the rule unset).

reach_rows, the rows a target weight still moves the book, enters the book's E17 memory (design
4.5): the first lag at which (1 - kappa)^lag falls below REACH_CUTOFF. A name whose target has
been flat for more than reach_rows rows is closed out to exactly 0, so the declared reach is the
true reach and a decayed position does not linger as a phantom holding.
"""

from __future__ import annotations

import dataclasses

import numpy as np

# Design 4.5's definition of a horizon rule's reach (APR-exempt, like guards.MEMORY_TOLERANCE):
# beyond it a target weight moves the book by less than a thousandth of itself.
REACH_CUTOFF = 1e-3


def _read_only(*arrays: np.ndarray) -> tuple[np.ndarray, ...]:
    out = tuple(a.view() for a in arrays)
    for a in out:
        a.flags.writeable = False
    return out


@dataclasses.dataclass(frozen=True)
class HorizonRule:
    kappa: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 < self.kappa <= 1.0:
            raise ValueError(f"kappa must be in (0, 1], got {self.kappa}")

    @property
    def identity(self) -> bool:
        return self.kappa >= 1.0  # kappa is at most 1, so this is kappa == 1

    @property
    def reach_rows(self) -> int:
        """The first lag with (1 - kappa)^lag < REACH_CUTOFF, by exact search (no float log)."""
        if self.identity:
            return 0
        lag, weight = 1, 1.0 - self.kappa
        while weight >= REACH_CUTOFF:
            lag += 1
            weight *= 1.0 - self.kappa
        return lag

    def apply(
        self,
        weights: np.ndarray,
        has_position: np.ndarray,
        tradable: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """(smoothed weights [n, m], has_position [n]), both read-only for every kappa, so the
        identity's views and a smoothed book share one contract. A row holds a position when any
        smoothed weight is nonzero, so a decaying book keeps scoring after its target goes
        flat."""
        if self.identity:
            return _read_only(weights, has_position)
        target = np.where(has_position[:, None], np.nan_to_num(weights), 0.0)
        can_trade = np.ones(len(target), dtype=bool) if tradable is None else tradable
        reach = self.reach_rows
        out = np.empty_like(target)
        prev = np.zeros(target.shape[1])
        flat_rows = np.zeros(target.shape[1], dtype=np.int64)  # rows since a nonzero target
        for t in range(len(target)):
            if can_trade[t]:
                prev = prev + self.kappa * (target[t] - prev)
                flat_rows = np.where(target[t] != 0.0, 0, flat_rows + 1)
                prev = np.where(flat_rows > reach, 0.0, prev)
            out[t] = prev
        return _read_only(out, (out != 0.0).any(axis=1))
