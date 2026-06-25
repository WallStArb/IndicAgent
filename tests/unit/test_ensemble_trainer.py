"""Unit tests for EnsembleTrainer service.

Tests the data-shaping logic and class contract. No live DB — asyncpg pool is mocked.
"""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from services.ensemble_trainer import EnsembleTrainer
from src.core.agent.base_batch import BaseBatch


class TestEnsembleTrainerClassContract:
    """Verify the BaseBatch subclass contract is met."""

    def test_job_name(self) -> None:
        """EnsembleTrainer must declare job_name = 'ensemble-trainer'."""
        assert EnsembleTrainer.job_name == "ensemble-trainer"

    def test_compute_version(self) -> None:
        """EnsembleTrainer must declare compute_version."""
        assert EnsembleTrainer.compute_version == "1.0.0"

    def test_is_base_batch_subclass(self) -> None:
        """EnsembleTrainer must extend BaseBatch."""
        assert issubclass(EnsembleTrainer, BaseBatch)

    def test_has_execute_method(self) -> None:
        """EnsembleTrainer must implement the abstract execute() method."""
        assert hasattr(EnsembleTrainer, "execute")
        assert callable(EnsembleTrainer.execute)

    def test_instantiation_requires_db_dsn(self) -> None:
        """EnsembleTrainer can be instantiated with a db_dsn string."""
        # Should not raise; no DB connection made at init time.
        builder = EnsembleTrainer(db_dsn="postgresql://localhost/test")
        assert builder.job_name == "ensemble-trainer"


class TestEnsembleTrainerImports:
    """Verify the ensemble math library is imported correctly."""

    def test_imports_select_features_per_stratum(self) -> None:
        from services.ensemble_trainer import select_features_per_stratum

        assert callable(select_features_per_stratum)

    def test_imports_compute_shrinkage_covariance(self) -> None:
        from services.ensemble_trainer import compute_shrinkage_covariance

        assert callable(compute_shrinkage_covariance)

    def test_imports_derive_weights(self) -> None:
        from services.ensemble_trainer import derive_weights

        assert callable(derive_weights)

    def test_imports_cluster_deflate_weights(self) -> None:
        from services.ensemble_trainer import cluster_deflate_weights

        assert callable(cluster_deflate_weights)

    def test_imports_effective_n(self) -> None:
        from services.ensemble_trainer import effective_n

        assert callable(effective_n)


class TestCfgHelpers:
    """Verify the APR config dict helpers."""

    def test_cfg_float_returns_float(self) -> None:
        from services.ensemble_trainer import _cfg_float

        cfg = {"alpha.ensemble.max_feature_weight": "0.20"}
        result = _cfg_float(cfg, "alpha.ensemble.max_feature_weight", 0.5)
        assert result == 0.20
        assert isinstance(result, float)

    def test_cfg_float_returns_default_when_missing(self) -> None:
        from services.ensemble_trainer import _cfg_float

        cfg: dict = {}
        result = _cfg_float(cfg, "alpha.ensemble.max_feature_weight", 0.25)
        assert result == 0.25

    def test_cfg_int_returns_int(self) -> None:
        from services.ensemble_trainer import _cfg_int

        cfg = {"alpha.ensemble.min_passing_features": "5"}
        result = _cfg_int(cfg, "alpha.ensemble.min_passing_features", 3)
        assert result == 5
        assert isinstance(result, int)

    def test_cfg_str_returns_str(self) -> None:
        from services.ensemble_trainer import _cfg_str

        cfg = {"alpha.ensemble.weight_version": "v2"}
        result = _cfg_str(cfg, "alpha.ensemble.weight_version", "v1")
        assert result == "v2"
        assert isinstance(result, str)
