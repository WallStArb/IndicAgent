"""Contribution accounting kernels (phase 187 plan 14, design 13): who earned a book's forecast and
who is necessary. Pure numpy, no I/O, process-pool safe; diagnostics only: nothing here is a test,
and nothing edits the book it measures.

Two different questions with two different measures:
- attribution (additive): the member terms sum exactly to the forecast's predictive covariance
  with the target. A member's `term` is its additive share of the book forecast in a cell, the
  combiner's own v_k * s_k (z-score or fold-centred signal times applied weight).
- marginal (counterfactual): leave-one-family-out and Shapley values over a caller-supplied value
  function, which refits and scores a subset. The kernels never refit, so they stay testable with
  a cheap fake and the runner owns the refit path.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Sequence

import numpy as np

ValueFn = Callable[[tuple[int, ...]], float]


def attribution(terms: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, float]:
    """(per-member attribution [K], total). `terms` [n, m, K] holds each member's additive term
    per cell, NaN where the cell is not scored by the book; an absent member of a scored cell may
    be 0 or NaN. `target` [n, m]. A scored cell has a finite target and at least one finite term.
    Member k's attribution is sum over scored cells of term_k * (r - rbar_t) / N with rbar_t the
    row mean of the target over that row's scored cells; the K values sum to the same expression
    on the forecast, the covariance of the forecast with the target, exactly."""
    if terms.ndim != 3 or target.shape != terms.shape[:2]:
        raise ValueError(f"terms {terms.shape} and target {target.shape} do not align")
    scored = np.isfinite(terms).any(axis=2) & np.isfinite(target)
    n_scored = int(scored.sum())
    if n_scored == 0:
        return np.full(terms.shape[2], np.nan), float("nan")
    r = np.where(scored, target, 0.0)
    rows = scored.sum(axis=1)
    rbar = np.divide(r.sum(axis=1), rows, out=np.zeros(len(rows)), where=rows > 0)
    dev = np.where(scored, target - rbar[:, None], 0.0)
    per_member = (
        np.array(
            [float((np.nan_to_num(terms[:, :, k]) * dev).sum()) for k in range(terms.shape[2])]
        )
        / n_scored
    )
    return per_member, float(per_member.sum())


def group_totals(per_member: np.ndarray, groups: Sequence[str]) -> dict[str, float]:
    """Attribution summed by accounting group, in first-seen group order."""
    if len(groups) != len(per_member):
        raise ValueError("one group per member")
    out: dict[str, float] = {}
    for value, group in zip(per_member, groups, strict=True):
        out[group] = out.get(group, 0.0) + float(value)
    return out


def leave_one_out(value: ValueFn, k: int) -> np.ndarray:
    """v(all) - v(all but i) for each of k players."""
    full = tuple(range(k))
    base = value(full)
    return np.array([base - value(tuple(j for j in full if j != i)) for i in range(k)])


def shapley_exact(value: ValueFn, k: int) -> np.ndarray:
    """Exact Shapley values by subset enumeration (2^k value calls, each subset once);
    value(()) is the empty book's value and must be 0 or a fixed baseline."""
    cache: dict[tuple[int, ...], float] = {}

    def v(subset: tuple[int, ...]) -> float:
        if subset not in cache:
            cache[subset] = value(subset)
        return cache[subset]

    phi = np.zeros(k)
    for i in range(k):
        others = [j for j in range(k) if j != i]
        for size in range(k):
            weight = math.factorial(size) * math.factorial(k - size - 1) / math.factorial(k)
            for subset in itertools.combinations(others, size):
                with_i = tuple(sorted((*subset, i)))
                phi[i] += weight * (v(with_i) - v(subset))
    return phi


def shapley_sampled(
    value: ValueFn, k: int, samples: int, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    """(Shapley estimate, standard error) by seeded permutation sampling: the marginal
    contribution of each player along `samples` random orders. Same seed, same output."""
    rng = np.random.default_rng(seed)
    cache: dict[tuple[int, ...], float] = {}

    def v(subset: tuple[int, ...]) -> float:
        if subset not in cache:
            cache[subset] = value(subset)
        return cache[subset]

    draws = np.zeros((samples, k))
    for s in range(samples):
        order = rng.permutation(k)
        built: tuple[int, ...] = ()
        previous = v(built)
        for player in order:
            built = tuple(sorted((*built, int(player))))
            current = v(built)
            draws[s, player] = current - previous
            previous = current
    se = draws.std(axis=0, ddof=1) / math.sqrt(samples) if samples > 1 else np.full(k, np.nan)
    return draws.mean(axis=0), se


def uniqueness(z: np.ndarray) -> np.ndarray:
    """Per member 1 - R^2 of its z-score on the other members' z-scores, pooled over the rows
    where every member is finite. `z` [N, K]; 0 for a member that is a linear combination of the
    others, 1 for an orthogonal one."""
    rows = np.isfinite(z).all(axis=1)
    x = z[rows]
    k = x.shape[1]
    if x.shape[0] <= k:
        return np.full(k, np.nan)
    x = x - x.mean(axis=0)
    out = np.empty(k)
    for j in range(k):
        others = np.delete(x, j, axis=1)
        if others.shape[1] == 0:
            out[j] = 1.0
            continue
        beta, *_ = np.linalg.lstsq(others, x[:, j], rcond=None)
        resid = x[:, j] - others @ beta
        total = float(x[:, j] @ x[:, j])
        out[j] = float(resid @ resid) / total if total > 0 else np.nan
    return np.clip(out, 0.0, 1.0)


def effective_breadth(z: np.ndarray) -> float:
    """(sum lambda)^2 / sum lambda^2 of the member correlation matrix over rows where every
    member is finite: K for orthogonal members, 1 for identical ones."""
    rows = np.isfinite(z).all(axis=1)
    x = z[rows]
    if x.shape[0] < 2 or x.shape[1] < 1:
        return float("nan")
    corr = np.corrcoef(x, rowvar=False)
    lam = np.linalg.eigvalsh(np.atleast_2d(corr))
    return float(lam.sum() ** 2 / (lam**2).sum())


def sign_stability(fold_weights: np.ndarray) -> np.ndarray:
    """Per member, the fraction of folds whose fitted weight keeps the member's modal sign.
    `fold_weights` [F, K]; NaN and zero folds are not counted; NaN for a member with no signed
    fold."""
    signs = np.sign(fold_weights)
    out = np.full(fold_weights.shape[1], np.nan)
    for k in range(fold_weights.shape[1]):
        s = signs[:, k]
        s = s[np.isfinite(s) & (s != 0)]
        if s.size:
            out[k] = max((s > 0).sum(), (s < 0).sum()) / s.size
    return out


def correlation_clusters(z_train: np.ndarray, threshold: float) -> np.ndarray:
    """Group labels [K] from complete-linkage hierarchical clustering at distance
    1 - |corr| <= 1 - threshold, computed on the training rows given and nothing else (the
    caller passes a training fold, never the full vintage)."""
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform

    rows = np.isfinite(z_train).all(axis=1)
    k = z_train.shape[1]
    if k == 1 or rows.sum() < 2:
        return np.arange(1, k + 1)
    corr = np.corrcoef(z_train[rows], rowvar=False)
    dist = 1.0 - np.abs(np.nan_to_num(corr))
    np.fill_diagonal(dist, 0.0)
    tree = linkage(squareform(dist, checks=False), method="complete")
    return fcluster(tree, t=1.0 - threshold, criterion="distance")
