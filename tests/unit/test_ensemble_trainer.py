"""Unit tests for EnsembleTrainer service.

Tests the data-shaping logic and class contract. No live DB — asyncpg pool is mocked.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

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


# Config-dict casting (cfg()) and APR loading (load_apr_dict_async()) moved to
# services._batch_utils (todo 048, 2026-07-02) -- see tests/unit/test_batch_utils.py.
# ensemble_trainer.py, alpha_publisher.py, and ensemble_ic_engine.py all import
# the same shared helpers now instead of each defining their own copy.


class TestAssertPrerequisitesManifestGate:
    """Regression guard (high-effort code review, 2026-07-08): feature_ic_scores having
    nonzero rows is not sufficient evidence the ic_engine.py run that wrote them
    finished. ic_engine.py is the sole writer of feature_ic_scores -- one hop
    upstream of the identical gap already closed for ensemble_trainer's own
    downstream readers (ensemble_ic_engine.py, alpha_publisher.py)."""

    @pytest.mark.asyncio
    async def test_raises_when_no_ic_engine_manifest_exists(self, tmp_path):
        from services.ensemble_trainer import _assert_prerequisites

        conn = AsyncMock()
        conn.fetchval.return_value = 5

        with pytest.raises(RuntimeError, match="No manifest found for prerequisite step"):
            await _assert_prerequisites(conn, manifest_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_raises_when_ic_engine_manifest_status_is_not_success(self, tmp_path):
        from services.ensemble_trainer import _assert_prerequisites
        from src.observability.corpus_manifest import CorpusManifest

        conn = AsyncMock()
        conn.fetchval.return_value = 5
        manifest = CorpusManifest("ic_engine", tmp_path)
        manifest.add_error("crashed mid-run")
        manifest.write()

        with pytest.raises(RuntimeError, match="status='failed'"):
            await _assert_prerequisites(conn, manifest_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_passes_when_ic_engine_manifest_succeeded(self, tmp_path):
        from services.ensemble_trainer import _assert_prerequisites
        from src.observability.corpus_manifest import CorpusManifest

        conn = AsyncMock()
        conn.fetchval.return_value = 5
        manifest = CorpusManifest("ic_engine", tmp_path)
        manifest.mark_success()
        manifest.write()

        await _assert_prerequisites(conn, manifest_dir=tmp_path)
