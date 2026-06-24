"""
Feature selection from feature_ic_scores for ensemble weight derivation.

Pure functions only — no DB imports, no Kafka imports.

Input rows must already be filtered to:
    WHERE is_pooled = false AND passes_walkforward = true
      AND reliable = true AND ic_sharpe IS NOT NULL
for one (symbol, tf, regime) stratum.

Lookahead disambiguation (Pitfall 1 from RESEARCH.md):
    For each feature_name, keep the single row with the highest ic_sharpe.
    Never average across lookaheads — that dilutes the signal.
    Tie-break: when two lookaheads share identical ic_sharpe, prefer the
    shorter lookahead (ORDER BY ic_sharpe DESC, lookahead_bars ASC).
    Shorter lookahead converges faster and is less likely to be a noise artifact.
"""

from __future__ import annotations


def select_features_per_stratum(rows: list[dict]) -> list[dict]:
    """Select one row per feature_name from ic_scores rows for one (symbol, tf, regime).

    Parameters
    ----------
    rows:
        List of dicts from feature_ic_scores, pre-filtered to one (symbol, tf, regime)
        stratum with is_pooled=false, passes_walkforward=true, reliable=true,
        ic_sharpe IS NOT NULL.

    Returns
    -------
    list[dict]
        One row per feature_name — the row with the highest ic_sharpe for that feature.
        When two rows tie on ic_sharpe, the one with the smaller lookahead_bars is
        returned (shorter lookahead wins on tie). Each returned dict carries at minimum:
        feature_name, ic_sharpe, ic_ci_lower, ic_ci_upper, ic_sign, lookahead_bars.
    """
    if not rows:
        return []

    # Group rows by feature_name, keeping the best per feature.
    # Sort key: (-ic_sharpe, lookahead_bars) — max ic_sharpe first, then min lookahead.
    best: dict[str, dict] = {}
    for row in rows:
        feature_name = row["feature_name"]
        ic_sharpe = row.get("ic_sharpe")
        lookahead_bars = row.get("lookahead_bars", 0)

        if ic_sharpe is None:
            continue

        if feature_name not in best:
            best[feature_name] = row
            continue

        existing = best[feature_name]
        existing_sharpe = existing.get("ic_sharpe", float("-inf"))
        existing_lookahead = existing.get("lookahead_bars", 0)

        # Prefer higher ic_sharpe; break ties by shorter lookahead_bars
        if ic_sharpe > existing_sharpe or (
            ic_sharpe == existing_sharpe and lookahead_bars < existing_lookahead
        ):
            best[feature_name] = row

    return list(best.values())
