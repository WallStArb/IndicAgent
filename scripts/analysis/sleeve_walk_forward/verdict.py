"""S4: the decision rules of pre-registration section 8, pure.

An arm qualifies iff adjusted p < alpha and its excess is positive in at least
min_positive_sub_periods sub-periods. FAIL: none qualifies. PASS: some arm qualifies. ACT: a
qualifying arm has adjusted p < alpha / n_tested and a positive holdout excess (S5); with several
at that level the smallest adjusted p is the ACT arm. Before S5 an ACT-level arm stays PASS with
act_pending_holdout. FIDELITY = BROKEN issues no token.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from scripts.analysis.sleeve_walk_forward.config import HarnessConfig
from src.intelligence.research.evaluate import EvaluationResult


def decide(
    res: EvaluationResult,
    cfg: HarnessConfig,
    *,
    fidelity_ok: bool,
    holdout_excess: dict[str, float] | None = None,
) -> dict[str, Any]:
    per_arm = {}
    for j, arm in enumerate(res.arms):
        positive = int((res.sub_period_excess[j] > 0).sum())
        p = float(res.adjusted_p[j])
        per_arm[arm] = {
            "adjusted_p": p,
            "excess": float(res.excess[j]),
            "sub_period_excess": res.sub_period_excess[j].tolist(),
            "positive_sub_periods": positive,
            "excess_ci": res.excess_ci[j].tolist(),
            "qualifies": p < cfg.alpha and positive >= cfg.min_positive_sub_periods,
        }
    out: dict[str, Any] = {
        "fidelity": "OK" if fidelity_ok else "BROKEN",
        "per_arm": per_arm,
        "qualifying_arms": [a for a in res.arms if per_arm[a]["qualifies"]],
        "act_arm": None,
        "act_pending_holdout": False,
    }
    if not fidelity_ok:
        out["sleeve_verdict"] = None
        return out
    act_level = sorted(
        (a for a in out["qualifying_arms"] if per_arm[a]["adjusted_p"] < cfg.alpha / cfg.n_tested),
        key=lambda a: per_arm[a]["adjusted_p"],
    )
    verdict = "PASS" if out["qualifying_arms"] else "FAIL"
    if act_level:
        best = act_level[0]
        if holdout_excess is None:
            out["act_pending_holdout"] = True
        elif holdout_excess[best] > 0:
            verdict, out["act_arm"] = "ACT", best
    out["sleeve_verdict"] = verdict
    return out


def safe_evaluate(
    evaluate_fn: Callable[..., EvaluationResult], *args: Any, **kwargs: Any
) -> tuple[EvaluationResult | None, str | None]:
    """Run S3; a degenerate null or undefined Sharpe (ValueError from panel_null or
    annualized_sharpe) becomes FIDELITY BROKEN with the reason, never a token."""
    try:
        return evaluate_fn(*args, **kwargs), None
    except ValueError as error:
        return None, str(error)
