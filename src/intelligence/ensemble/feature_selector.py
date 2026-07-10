"""
Feature selection from feature_ic_scores for ensemble weight derivation.

Pure functions only — no DB imports, no Kafka imports.

Input rows must already be filtered to:
    WHERE is_pooled = false AND ic_ci_lower > 0 AND passes_fdr = true
      AND reliable = true AND ic_sharpe IS NOT NULL AND passes_walkforward = true
for one (symbol, tf, regime) stratum. (passes_walkforward added 2026-07-09 —
cross-sectional significance alone does not distinguish real signal from the tail
of expected false discoveries BH-FDR budgets for; see ensemble_trainer.py's
_process_stratum, the caller that enforces this filter before rows reach here.)

Lookahead disambiguation (Pitfall 1 from RESEARCH.md):
    For each feature_name, keep the single row with the highest quality_weight.
    quality_weight = ic_ci_lower * max(sharpe_floor, ic_sharpe_hac)

    This replaces the old ic_sharpe-only selection — quality_weight ensures that
    features with positive CI but near-zero Sharpe still receive a small positive
    weight (Renaissance principle: aggregate many weak signals, not just strong ones).

    Never average across lookaheads — that dilutes the signal.
    Tie-break: when two lookaheads share identical quality_weight, prefer the
    shorter lookahead (ORDER BY quality_weight DESC, lookahead_bars ASC).
    Shorter lookahead converges faster and is less likely to be a noise artifact.
"""

from __future__ import annotations


def compute_quality_weight(ic_ci_lower: float, ic_sharpe: float, sharpe_floor: float) -> float:
    """Renaissance IC gate weight: ic_ci_lower * max(sharpe_floor, ic_sharpe).

    Ensures features with positive CI but near-zero Sharpe still receive a small
    positive weight (aggregate many weak signals, not just strong ones).
    APR key: alpha.ensemble.sharpe_floor (default 0.05).
    """
    return float(ic_ci_lower) * max(sharpe_floor, float(ic_sharpe))


def select_features_per_stratum(
    rows: list[dict],
    sharpe_floor: float,
) -> list[dict]:
    """Select one row per feature_name from ic_scores rows for one (symbol, tf, regime).

    Parameters
    ----------
    rows:
        List of dicts from feature_ic_scores, pre-filtered to one (symbol, tf, regime)
        stratum with is_pooled=false, ic_ci_lower > 0, passes_fdr=true, reliable=true,
        ic_sharpe IS NOT NULL.
    sharpe_floor:
        Floor applied to ic_sharpe before multiplying by ic_ci_lower in the
        quality_weight formula. APR key: alpha.ensemble.sharpe_floor (default 0.05).
        Ensures features with positive CI but near-zero Sharpe still get a small weight.

    Returns
    -------
    list[dict]
        One row per feature_name — the row with the highest quality_weight for that
        feature. quality_weight = ic_ci_lower * max(sharpe_floor, ic_sharpe).
        When two rows tie on quality_weight, the one with the smaller lookahead_bars is
        returned (shorter lookahead wins on tie). Each returned dict carries at minimum:
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
        lookahead_bars = row.get("lookahead_bars", 0)

        if ic_sharpe is None or ic_ci_lower is None:
            continue

        qw = compute_quality_weight(float(ic_ci_lower), float(ic_sharpe), sharpe_floor)

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
