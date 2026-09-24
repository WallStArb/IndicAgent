import numpy as np

from scripts.analysis.sleeve_walk_forward.config import DEFAULT_CONFIG
from scripts.analysis.sleeve_walk_forward.evaluate import EvaluationResult
from scripts.analysis.sleeve_walk_forward.verdict import decide, safe_evaluate

ARMS = ("ic_proportional", "vol_normalized", "mean_variance")
ALL_POS = [1, 1, 1]


def _res(p, sub=None):
    j = len(ARMS)
    sub = sub if sub is not None else [ALL_POS] * j
    return EvaluationResult(
        arms=ARMS,
        sharpe_obs=np.ones(j),
        sharpe_null=np.zeros((10, j)),
        shifts=np.arange(10),
        adjusted_p=np.array(p, dtype=float),
        excess=np.ones(j),
        sub_period_excess=np.array(sub, dtype=float),
        excess_ci=np.zeros((j, 2)),
    )


def _decide(res, **kw):
    return decide(res, DEFAULT_CONFIG, fidelity_ok=kw.pop("fidelity_ok", True), **kw)


def test_fail_when_no_arm_below_alpha():
    out = _decide(_res([0.2, 0.3, 0.06]))
    assert out["sleeve_verdict"] == "FAIL" and out["qualifying_arms"] == []


def test_p_exactly_alpha_does_not_qualify():
    assert _decide(_res([0.05, 0.5, 0.5]))["sleeve_verdict"] == "FAIL"


def test_one_positive_sub_period_does_not_qualify():
    r = _res([0.01, 0.2, 0.2], [[1, -1, -1], ALL_POS, ALL_POS])
    assert _decide(r)["sleeve_verdict"] == "FAIL"


def test_pass_with_two_positive_sub_periods():
    r = _res([0.01, 0.2, 0.2], [[1, 1, -1], ALL_POS, ALL_POS])
    out = _decide(r)
    assert out["sleeve_verdict"] == "PASS" and out["qualifying_arms"] == ["ic_proportional"]
    assert out["per_arm"]["ic_proportional"]["positive_sub_periods"] == 2


def test_act_level_without_holdout_is_pass_pending():
    out = _decide(_res([0.001, 0.2, 0.2]))
    assert out["sleeve_verdict"] == "PASS" and out["act_pending_holdout"] is True
    assert out["act_arm"] is None


def test_act_with_positive_holdout():
    out = _decide(_res([0.001, 0.2, 0.2]), holdout_excess={"ic_proportional": 0.1})
    assert out["sleeve_verdict"] == "ACT" and out["act_arm"] == "ic_proportional"


def test_negative_holdout_downgrades_act_to_pass():
    out = _decide(_res([0.001, 0.2, 0.2]), holdout_excess={"ic_proportional": -0.1})
    assert out["sleeve_verdict"] == "PASS" and out["act_arm"] is None


def test_smallest_adjusted_p_is_the_act_arm():
    out = _decide(
        _res([0.002, 0.001, 0.2]), holdout_excess={"ic_proportional": 1.0, "vol_normalized": 1.0}
    )
    assert out["act_arm"] == "vol_normalized"


def test_act_threshold_is_alpha_over_n_tested():
    # 0.05 / 15 = 0.00333; 0.004 qualifies for PASS only.
    out = _decide(_res([0.004, 0.2, 0.2]), holdout_excess={"ic_proportional": 1.0})
    assert out["sleeve_verdict"] == "PASS"


def test_broken_fidelity_issues_no_token():
    out = _decide(_res([0.001, 0.2, 0.2]), fidelity_ok=False)
    assert out["sleeve_verdict"] is None and out["fidelity"] == "BROKEN"


def test_safe_evaluate_turns_degenerate_null_into_broken():
    def boom(*_a, **_k):
        raise ValueError("arm null has zero variance: arms [2]")

    res, error = safe_evaluate(boom)
    assert res is None and "zero variance" in error
