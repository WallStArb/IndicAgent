"""
Feature selection from feature_ic_scores for ensemble weight derivation.

Pure functions only — no DB imports, no Kafka imports.

Input rows must already be filtered by ensemble_trainer.py's `_eligibility_where()`
for one (symbol, tf, regime) stratum: symbol='POOLED', is_pooled=true,
regime != '_pooled', reliable=true, ic_sharpe_hac IS NOT NULL, passes_walkforward=true,
passes_fdr=true, plus a significance clause that is flag-gated on
alpha.ensemble.sign_symmetric (Component E, todo 094) -- `ic_ci_lower > 0` when the
flag is off (long-only, byte-identical to the pre-Component-E champion), or
`(ic_sign=1 AND ic_ci_lower>0) OR (ic_sign=-1 AND ic_ci_upper<0)` when the flag is on.
(passes_walkforward added 2026-07-09 — cross-sectional significance alone does not
distinguish real signal from the tail of expected false discoveries BH-FDR budgets
for; see ensemble_trainer.py's _process_stratum, the caller that enforces this filter
before rows reach here.)

Lookahead disambiguation (Pitfall 1 from RESEARCH.md):
    For each feature_name, keep the single row with the highest quality_weight.
    quality_weight = (ic_sign * nearest_ci_bound) * max(sharpe_floor, ic_sign * ic_sharpe)
    where nearest_ci_bound = ic_ci_lower for ic_sign=1, ic_ci_upper for ic_sign=-1.
    This reduces byte-for-byte to the old `ic_ci_lower * max(sharpe_floor, ic_sharpe)`
    for ic_sign=1 and preserves positive-magnitude quality weight on the negative-IC
    side via sign framing (not naive abs) -- a decay-signature row (positive
    full-sample IC, negative window Sharpe) is correctly NOT up-weighted by this
    formula, whereas abs(ic_sharpe) would up-weight it.

    This replaces the old ic_sharpe-only selection — quality_weight ensures that
    features with positive CI but near-zero Sharpe still receive a small positive
    weight (Renaissance principle: aggregate many weak signals, not just strong ones).

    Never average across lookaheads — that dilutes the signal.
    Tie-break: when two lookaheads share identical quality_weight, prefer the
    shorter lookahead (ORDER BY quality_weight DESC, lookahead_bars ASC).
    Shorter lookahead converges faster and is less likely to be a noise artifact.
"""

from __future__ import annotations


def compute_quality_weight(
    ic_ci_lower: float,
    ic_ci_upper: float,
    ic_sharpe: float,
    ic_sign: int,
    sharpe_floor: float,
) -> float:
    """Renaissance IC gate weight, sign-aware (Component E, todo 094):
    (ic_sign * nearest_ci_bound) * max(sharpe_floor, ic_sign * ic_sharpe), where
    nearest_ci_bound = ic_ci_lower for ic_sign=1 and ic_ci_upper for ic_sign=-1.

    Equivalence property: for ic_sign=1 this is byte-for-byte the old formula
    `ic_ci_lower * max(sharpe_floor, ic_sharpe)` (ic_sign multiplies by +1, a no-op).
    For ic_sign=-1, both factors are sign-flipped by ic_sign so the result stays
    positive-magnitude WITHOUT naive abs() -- abs(ic_sharpe) would misapply the
    sharpe_floor comparison to a negative-window-Sharpe decay-signature row and
    up-weight it; multiplying by the feature's own ic_sign first correctly keeps
    such rows down-weighted (Renaissance: distinguish real contrarian signal from
    directional-decay noise, don't just take a magnitude).

    Ensures features with a significant CI (on their own side) but near-zero
    |Sharpe| still receive a small positive weight (aggregate many weak signals,
    not just strong ones). APR key: alpha.ensemble.sharpe_floor (default 0.025, rescaled from 0.05 by todo 096/migration 230).
    """
    nearest_ci_bound = float(ic_ci_lower) if ic_sign == 1 else float(ic_ci_upper)
    signed_sharpe = ic_sign * float(ic_sharpe)
    return (ic_sign * nearest_ci_bound) * max(sharpe_floor, signed_sharpe)


def select_features_per_stratum(
    rows: list[dict],
    sharpe_floor: float,
) -> list[dict]:
    """Select one row per feature_name from ic_scores rows for one (symbol, tf, regime).

    Parameters
    ----------
    rows:
        List of dicts from feature_ic_scores, pre-filtered to one (symbol, tf, regime)
        stratum via ensemble_trainer.py's `_eligibility_where()` (sign-flag-gated
        significance clause, passes_fdr=true, reliable=true, ic_sharpe IS NOT NULL).
    sharpe_floor:
        Floor applied to the sign-adjusted ic_sharpe before multiplying by the
        sign-adjusted nearest CI bound in the quality_weight formula. APR key:
        alpha.ensemble.sharpe_floor (default 0.025, rescaled from 0.05 by todo 096/
        migration 230). Ensures features with a
        significant CI (on their own side) but near-zero |Sharpe| still get a small
        weight.

    Returns
    -------
    list[dict]
        One row per feature_name — the row with the highest quality_weight for that
        feature. quality_weight = (ic_sign * nearest_ci_bound) * max(sharpe_floor,
        ic_sign * ic_sharpe) -- see compute_quality_weight docstring. When two rows
        tie on quality_weight, the one with the smaller lookahead_bars is returned
        (shorter lookahead wins on tie). Each returned dict carries at minimum:
        feature_name, ic_sharpe, ic_ci_lower, ic_ci_upper, ic_sign, lookahead_bars,
        quality_weight.
    """
    if not rows:
        return []

    # Group rows by feature_name, keeping the best per feature.
    # Sort key: (-quality_weight, lookahead_bars) — max quality_weight first, then min lookahead.
    best: dict[str, dict] = {}
    for row in rows:
        feature_name = row["feature_name"]
        ic_sharpe = row.get("ic_sharpe")
        ic_ci_lower = row.get("ic_ci_lower")
        ic_ci_upper = row.get("ic_ci_upper")
        ic_sign = row.get("ic_sign")
        lookahead_bars = row.get("lookahead_bars", 0)

        if ic_sharpe is None or ic_ci_lower is None or ic_ci_upper is None or ic_sign is None:
            continue

        qw = compute_quality_weight(
            float(ic_ci_lower), float(ic_ci_upper), float(ic_sharpe), int(ic_sign), sharpe_floor
        )

        if feature_name not in best:
            best[feature_name] = {**row, "quality_weight": qw}
            continue

        existing = best[feature_name]
        existing_qw = existing.get("quality_weight", float("-inf"))
        existing_lookahead = existing.get("lookahead_bars", 0)

        # Prefer higher quality_weight; break ties by shorter lookahead_bars
        if qw > existing_qw or (qw == existing_qw and lookahead_bars < existing_lookahead):
            best[feature_name] = {**row, "quality_weight": qw}

    return list(best.values())
