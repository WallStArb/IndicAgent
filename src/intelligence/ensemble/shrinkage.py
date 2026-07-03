"""
Empirical-Bayes IC shrinkage toward a leave-one-out peer-group prior.

Pure functions only — no DB imports, no Kafka imports.

Two functions:
    shrink_ic                  — shrink a single cell's raw IC toward ic_prior via
                                  w = n_eff / (n_eff + k)
    leave_one_out_group_prior  — peer-group mean excluding the cell being shrunk

`k` (APR key alpha.ic.shrinkage_k) and `n_eff` (sourced from ic_engine.py's existing
n_independent) are always passed in as function arguments — callers load `k` from APR
via ConfigService.get_sync(). The only numeric constant in this module is the implicit
degenerate-guard boundary at n_eff <= 0 and n_group == 1, both mathematical necessities
(APR-exempt), not tunable thresholds.
"""

from __future__ import annotations

import numpy as np


# Source: standard empirical-Bayes / James-Stein shrinkage-to-group-mean formulation,
# structurally consistent with the general form documented at
# https://en.wikipedia.org/wiki/James%E2%80%93Stein_estimator and empirical-Bayes
# hierarchical-shrinkage treatments (search-verified structural match, see RESEARCH.md).
def shrink_ic(
    ic_raw: float,
    n_eff: float,
    ic_prior: float,
    k: float,
) -> tuple[float, float]:
    """Shrink a single cell's raw IC toward its peer-group prior.

    w = n_eff / (n_eff + k): as n_eff -> infinity, w -> 1 (trust the raw estimate);
    as n_eff -> 0, w -> 0 (trust the prior). k calibrates how many "effective
    observations" of prior strength to inject — the classic empirical-Bayes
    "prior sample size" interpretation.

    Parameters
    ----------
    ic_raw:
        The cell's raw (unshrunk) IC estimate.
    n_eff:
        Effective sample size for the raw estimate (sourced from ic_engine.py's
        existing n_independent). Values <= 0 are degenerate — see below.
    ic_prior:
        The leave-one-out peer-group prior (see leave_one_out_group_prior).
    k:
        Prior-strength calibration constant, in units of "effective observations".
        Loaded from APR key alpha.ic.shrinkage_k.

    Returns
    -------
    (ic_shrunk, shrinkage_weight):
        ic_shrunk: the shrunk IC estimate.
        shrinkage_weight: w in [0, 1] — the raw-estimate mixing weight.

    Degenerate case: n_eff <= 0 -> returns (ic_prior, 0.0) — zero effective
    observations means full shrinkage to the prior, not a divide-by-zero or a
    spurious ic_raw pass-through.
    """
    if n_eff <= 0:
        return ic_prior, 0.0
    w = n_eff / (n_eff + k)
    ic_shrunk = w * ic_raw + (1.0 - w) * ic_prior
    return ic_shrunk, w


def leave_one_out_group_prior(group_ic_values: np.ndarray, self_index: int) -> float:
    """Compute the peer-group mean IC excluding the cell being shrunk.

    prior = (sum(group) - group[self_index]) / (n_group - 1)

    This is the textbook-correct empirical-Bayes construction: the prior for a cell
    must not include that cell's own raw IC, or the shrinkage partially shrinks a
    value toward a mean that includes itself, biasing the apparent shrinkage benefit
    upward. Not immaterial at the smallest peer groups (cross_tf, macro have n=3).

    Parameters
    ----------
    group_ic_values:
        Array of raw IC values for every member of the peer group, including self.
    self_index:
        Index of the cell being shrunk within group_ic_values.

    Returns
    -------
    float
        The leave-one-out group mean. If the group has only one member (no peers),
        there is no leave-one-out mean to compute — the contract falls back to the
        self value rather than raising ZeroDivisionError or returning NaN.
    """
    n_group = len(group_ic_values)
    if n_group <= 1:
        return float(group_ic_values[self_index])
    total = float(np.sum(group_ic_values))
    return (total - float(group_ic_values[self_index])) / (n_group - 1)
