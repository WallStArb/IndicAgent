"""Unit tests for ensemble_trainer.py's E2 alpha.ensemble.weight_method wiring (Phase 142B.1-04).

Covers `resolve_stratum_weights()` -- the pure branch-selection + condition-number-fallback
helper extracted from `_process_stratum` for testability -- and `EnsembleConfig`'s
`weight_method`/`mv_condition_max` APR binding.

No DB -- mirrors tests/unit/test_ensemble_trainer_ic_input.py's mock-free, class-contract
style, and tests/unit/test_ensemble_mean_variance.py's synthetic-covariance convention.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from services.ensemble_trainer import (
    EnsembleConfig,
    cluster_deflate_weights,
    resolve_stratum_weights,
)
from src.intelligence.ensemble.weights import mean_variance_weights


def _well_conditioned_inputs() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Diagonal (hence well-conditioned) covariance -> mean_variance_weights succeeds."""
    cov = np.diag([1.0, 2.0, 4.0])
    corr = np.eye(3)
    ic_shrunk = np.array([1.0, 1.0, 1.0])
    aged_quality_weights = np.array([1.0, 1.0, 1.0])
    return cov, corr, ic_shrunk, aged_quality_weights


def _ill_conditioned_inputs() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Two near-identical rows/cols -> condition number far exceeds any sane condition_max."""
    cov = np.array(
        [
            [1.0, 0.999999999, 0.0],
            [0.999999999, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    corr = cov.copy()
    ic_shrunk = np.array([1.0, 1.0, 1.0])
    aged_quality_weights = np.array([1.0, 1.0, 1.0])
    return cov, corr, ic_shrunk, aged_quality_weights


# ---------------------------------------------------------------------------
# resolve_stratum_weights branch-selection + fallback tests
# ---------------------------------------------------------------------------


class TestResolveStratumWeightsBranchSelection:
    def test_mean_variance_success_skips_cluster_deflation(self) -> None:
        """Well-conditioned Sigma -> mean_variance branch selected, cluster_deflate_weights
        is NEVER called on the success path (D-08: Sigma^-1.IC already decorrelates
        continuously; binary cluster capping would double-penalize)."""
        cov, corr, ic_shrunk, aged = _well_conditioned_inputs()
        ic_signs = np.ones_like(ic_shrunk)
        with patch("services.ensemble_trainer.cluster_deflate_weights") as mock_deflate:
            result = resolve_stratum_weights(
                "mean_variance", aged, cov, corr, ic_shrunk, ic_signs, 0.20, 0.80, 0.40, 1000.0
            )
        assert result.method_used == "mean_variance"
        assert result.condition_number is not None
        assert np.isfinite(result.condition_number)
        mock_deflate.assert_not_called()
        assert float(result.weights.sum()) == pytest.approx(1.0, abs=1e-6)

    def test_ill_conditioned_falls_back_to_cluster_deflation(self) -> None:
        """Ill-conditioned Sigma -> mean_variance_weights returns (None, cond); the
        stratum falls back to the exact same cluster_deflate_weights path the
        ic_proportional method uses (RESEARCH.md Pitfall 3 hard fallback requirement).
        This test fails if the fallback branch were removed (regression guard)."""
        cov, corr, ic_shrunk, aged = _ill_conditioned_inputs()
        ic_signs = np.ones_like(ic_shrunk)

        result = resolve_stratum_weights(
            "mean_variance", aged, cov, corr, ic_shrunk, ic_signs, 0.20, 0.80, 0.40, 1000.0
        )
        assert result.method_used == "mean_variance_fallback"
        assert result.condition_number is not None
        assert result.condition_number > 1000.0

        expected = resolve_stratum_weights(
            "ic_proportional", aged, cov, corr, ic_shrunk, ic_signs, 0.20, 0.80, 0.40, 1000.0
        )
        np.testing.assert_allclose(result.weights, expected.weights)
        np.testing.assert_allclose(result.raw_weights, expected.raw_weights)

    def test_ic_proportional_uses_cluster_deflation(self) -> None:
        """Default method routes through derive_weights -> cluster_deflate_weights,
        calling the real cluster_deflate_weights exactly once (v1 path unchanged)."""
        cov, corr, ic_shrunk, aged = _well_conditioned_inputs()
        ic_signs = np.ones_like(ic_shrunk)
        with patch(
            "services.ensemble_trainer.cluster_deflate_weights",
            wraps=cluster_deflate_weights,
        ) as mock_deflate:
            result = resolve_stratum_weights(
                "ic_proportional", aged, cov, corr, ic_shrunk, ic_signs, 0.20, 0.80, 0.40, 1000.0
            )
        assert result.method_used == "ic_proportional"
        assert result.condition_number is None
        mock_deflate.assert_called_once()

    def test_unknown_weight_method_raises(self) -> None:
        """Fail loud on an unrecognized weight_method -- never silently default to the
        wrong path (regression guard)."""
        cov, corr, ic_shrunk, aged = _well_conditioned_inputs()
        ic_signs = np.ones_like(ic_shrunk)
        with pytest.raises(ValueError, match="Unknown alpha.ensemble.weight_method value"):
            resolve_stratum_weights(
                "not_a_real_method", aged, cov, corr, ic_shrunk, ic_signs, 0.20, 0.80, 0.40, 1000.0
            )

    def test_cap_applied_after_mean_variance(self) -> None:
        """A raw MV entry above max_feature_weight is capped in the final weights --
        mean_variance_weights() itself returns uncapped output; derive_weights' cap
        logic runs afterward, unchanged (D-08). Six features (one dominant, five equal
        small ones) mirrors test_ensemble_math.py's own non-degenerate cap test shape --
        a 2-feature extreme-skew input can trigger derive_weights' redistribution loop
        to re-equalize rather than stay capped, which is a property of that shared
        function, not something this test is meant to probe."""
        cov = np.diag([1.0, 10.0, 10.0, 10.0, 10.0, 10.0])
        corr = np.eye(6)
        ic_shrunk = np.array([1.0, 1.0, 1.0, 1.0, 1.0, 1.0])
        ic_signs = np.ones(6)
        aged = np.ones(6)
        max_weight = 0.20

        raw, _cond = mean_variance_weights(cov, ic_shrunk, 1000.0)
        assert raw is not None
        assert raw[0] > max_weight  # precondition: raw output is genuinely uncapped

        result = resolve_stratum_weights(
            "mean_variance", aged, cov, corr, ic_shrunk, ic_signs, max_weight, 0.80, 0.40, 1000.0
        )
        assert result.method_used == "mean_variance"
        assert float(result.weights.max()) <= max_weight + 1e-9


# ---------------------------------------------------------------------------
# E2 sign-path correctness (Component E, todo 094, BLOCKER 3): the mathematically
# correct combination signs the OUTPUT of Sigma^-1.mu, not the input mu itself --
# Sigma^-1.(s.mu) != s.(Sigma^-1.mu) once a contrarian is non-trivially correlated
# with another selected feature (the sign matrix and Sigma^-1 do not commute off
# the diagonal).
# ---------------------------------------------------------------------------


class TestE2SignPathCorrectness:
    def _correlated_contrarian_inputs(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """2 features, |corr|=0.7 (non-trivial), feature 1 is a contrarian (ic_sign=-1)
        with a smaller-magnitude signed IC than feature 0's positive IC -- chosen so the
        wrong input-signed formula flips feature 1 negative (re-zeroed by derive_weights'
        >0 filter) while the correct output-signed formula keeps it positive."""
        cov = np.array([[1.0, 0.7], [0.7, 1.0]])
        ic_shrunk = np.array([0.8, -0.3])  # signed: feature0 positive, feature1 contrarian
        ic_signs = np.array([1.0, -1.0])
        return cov, ic_shrunk, ic_signs

    def test_input_signed_and_output_signed_formulas_diverge(self) -> None:
        """Discriminator: the WRONG formula Sigma^-1.(s.mu) and the CORRECT formula
        s.(Sigma^-1.mu) must produce genuinely different vectors on a correlated
        contrarian input -- if they matched, this test (and BLOCKER 3) would be moot."""
        cov, ic_shrunk, ic_signs = self._correlated_contrarian_inputs()

        # WRONG: sign applied to the INPUT before the solve.
        wrong_raw, _ = mean_variance_weights(cov, ic_signs * ic_shrunk, condition_max=1000.0)
        # CORRECT: sign applied to the OUTPUT of the unmodified solve.
        mv_raw, _ = mean_variance_weights(cov, ic_shrunk, condition_max=1000.0)
        correct_signed = ic_signs * mv_raw

        assert wrong_raw is not None
        assert mv_raw is not None
        assert not np.allclose(wrong_raw, correct_signed), (
            "Input-signed and output-signed formulas must diverge on a correlated "
            "contrarian input -- Sigma^-1 and the sign matrix do not commute off-diagonal."
        )
        # The wrong formula re-zeros the contrarian (negative entry survives into
        # derive_weights' >0 filter); the correct formula does not.
        assert wrong_raw[1] < 0.0, "wrong (input-signed) formula flips the contrarian negative"
        assert correct_signed[1] > 0.0, "correct (output-signed) formula keeps contrarian positive"

    def test_resolve_stratum_weights_matches_output_signed_not_input_signed(self) -> None:
        """resolve_stratum_weights' actual implementation must match the CORRECT
        output-signed result and the contrarian must survive into the final weights
        (nonzero weight), not be silently re-zeroed by the wrong input-signed path."""
        cov, ic_shrunk, ic_signs = self._correlated_contrarian_inputs()
        corr = cov.copy()  # already a correlation matrix here (unit diagonal)
        aged_quality_weights = np.array([0.8, 0.3])  # positive-convention, unused on success path

        result = resolve_stratum_weights(
            "mean_variance",
            aged_quality_weights,
            cov,
            corr,
            ic_shrunk,
            ic_signs,
            0.90,  # max_feature_weight -- generous, not the thing under test here
            0.80,
            0.40,
            1000.0,
        )
        assert result.method_used == "mean_variance"
        # The contrarian (index 1) must have survived into the final weight vector.
        assert result.weights[1] > 0.0, (
            "Contrarian feature was re-zeroed -- resolve_stratum_weights is using the "
            "wrong input-signed formula (BLOCKER 3 regression)"
        )

    def test_equivalence_all_positive_signs_output_signing_is_a_no_op(self) -> None:
        """When every ic_sign is +1, ic_signs * mv_raw == mv_raw exactly -- the E2 path
        is byte-for-byte unchanged from its pre-Component-E behavior for the all-positive
        (pre-Component-E champion) case."""
        cov = np.array([[1.0, 0.3], [0.3, 1.0]])
        ic_shrunk = np.array([0.6, 0.4])
        ic_signs = np.ones_like(ic_shrunk)

        mv_raw, _ = mean_variance_weights(cov, ic_shrunk, condition_max=1000.0)
        assert mv_raw is not None
        np.testing.assert_array_equal(ic_signs * mv_raw, mv_raw)


# ---------------------------------------------------------------------------
# EnsembleConfig.weight_method / mv_condition_max APR binding
# ---------------------------------------------------------------------------


class TestEnsembleConfigWeightMethodFields:
    def test_from_apr_default_is_ic_proportional(self) -> None:
        """No alpha.ensemble.weight_method key present -> defaults to 'ic_proportional'
        (v1 behavior preserved when the APR key is unset)."""
        config = EnsembleConfig.from_apr({})
        assert config.weight_method == "ic_proportional"

    def test_from_apr_reads_mean_variance_override(self) -> None:
        config = EnsembleConfig.from_apr({"alpha.ensemble.weight_method": "mean_variance"})
        assert config.weight_method == "mean_variance"

    def test_from_apr_default_mv_condition_max(self) -> None:
        config = EnsembleConfig.from_apr({})
        assert config.mv_condition_max == pytest.approx(1000.0)

    def test_from_apr_reads_mv_condition_max_override(self) -> None:
        config = EnsembleConfig.from_apr({"alpha.ensemble.mv_condition_max": 500.0})
        assert config.mv_condition_max == pytest.approx(500.0)

    def test_weight_method_field_exists_on_dataclass(self) -> None:
        assert "weight_method" in EnsembleConfig.__dataclass_fields__

    def test_mv_condition_max_field_exists_on_dataclass(self) -> None:
        assert "mv_condition_max" in EnsembleConfig.__dataclass_fields__


# ---------------------------------------------------------------------------
# Source-structure assertions (grep-style, matching PLAN.md acceptance criteria)
# ---------------------------------------------------------------------------


class TestSourceStructure:
    def test_weight_method_loaded_via_cfg_helper_not_ad_hoc(self) -> None:
        source = Path(project_root / "services" / "ensemble_trainer.py").read_text()
        assert '_cfg(cfg, "alpha.ensemble.weight_method", "ic_proportional")' in source

    def test_mv_condition_max_loaded_via_cfg_helper(self) -> None:
        source = Path(project_root / "services" / "ensemble_trainer.py").read_text()
        assert '_cfg(cfg, "alpha.ensemble.mv_condition_max", 1000.0)' in source

    def test_mean_variance_weights_called_with_mv_condition_max(self) -> None:
        source = Path(project_root / "services" / "ensemble_trainer.py").read_text()
        assert source.count("mean_variance_weights(") >= 1
        assert "mean_variance_weights(cov_matrix, ic_shrunk, mv_condition_max)" in source

    def test_fallback_log_record_present(self) -> None:
        """A structured log record must exist for the fallback path -- never a silent skip
        (T-142B1-04-03)."""
        source = Path(project_root / "services" / "ensemble_trainer.py").read_text()
        assert "ensemble_trainer.weight_method_fallback" in source

    def test_default_ic_proportional_branch_preserves_original_call(self) -> None:
        """The original derive_weights -> cluster_deflate_weights call shape is still
        present verbatim inside resolve_stratum_weights' ic_proportional branch."""
        source = Path(project_root / "services" / "ensemble_trainer.py").read_text()
        assert "raw_weights = derive_weights(aged_quality_weights, max_feature_weight)" in source
        assert (
            "cluster_deflate_weights(\n            raw_weights, corr_matrix, "
            "max_cluster_corr, max_cluster_weight\n        )" in source
        )

    def test_no_new_event_kwarg_collisions(self) -> None:
        """structlog 'event' kwarg collision must not be introduced -- use signal=/payload=/
        other names, never event=<value>."""
        source = Path(project_root / "services" / "ensemble_trainer.py").read_text()
        assert "event=" not in source

    def test_no_ad_hoc_config_service_get_calls_added(self) -> None:
        source = Path(project_root / "services" / "ensemble_trainer.py").read_text()
        assert source.count("ConfigService.get") == 0
