"""Unit tests for EnsembleTrainer service.

Tests the data-shaping logic and class contract. No live DB — asyncpg pool is mocked.
"""

from __future__ import annotations

import inspect
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
            await _assert_prerequisites(conn, sign_symmetric=False, manifest_dir=tmp_path)

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
            await _assert_prerequisites(conn, sign_symmetric=False, manifest_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_passes_when_ic_engine_manifest_succeeded(self, tmp_path):
        from services.ensemble_trainer import _assert_prerequisites
        from src.observability.corpus_manifest import CorpusManifest

        conn = AsyncMock()
        conn.fetchval.return_value = 5
        manifest = CorpusManifest("ic_engine", tmp_path)
        manifest.mark_success()
        manifest.write()

        await _assert_prerequisites(conn, sign_symmetric=False, manifest_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_passes_with_sign_symmetric_true(self, tmp_path):
        """sign_symmetric=True must not break the startup gate -- it only changes
        which SQL WHERE clause is evaluated, not the gate's control flow."""
        from services.ensemble_trainer import _assert_prerequisites
        from src.observability.corpus_manifest import CorpusManifest

        conn = AsyncMock()
        conn.fetchval.return_value = 5
        manifest = CorpusManifest("ic_engine", tmp_path)
        manifest.mark_success()
        manifest.write()

        await _assert_prerequisites(conn, sign_symmetric=True, manifest_dir=tmp_path)


class TestEligibilityRequiresWalkForward:
    """Regression guard (2026-07-09): a fresh corpus measurement showed the top of the
    IC leaderboard concentrated in regime-conditional cells with wf_fold_count=0 --
    CI+FDR significance alone does not distinguish real signal from the tail of
    expected false discoveries BH-FDR budgets for. Every query that defines which
    feature_ic_scores rows are eligible to feed the ensemble must also require
    passes_walkforward = true, not just ic_ci_lower/passes_fdr/reliable/ic_sharpe_hac.
    The condition lives once in `_eligibility_where()` (a builder, not a module
    constant, as of Component E / todo 094 -- the significance clause is now
    flag-gated on alpha.ensemble.sign_symmetric), interpolated into all four call
    sites -- these tests check (a) the builder's output carries the condition for
    both flag values and (b) every site still calls the builder, so a future edit
    can't silently drop the requirement at a single call site. SQL-text inspection,
    no live DB required -- mirrors the _source() pattern in TestUpsertSQL
    (test_ensemble_weight_epoch.py)."""

    def test_eligibility_builder_requires_walkforward_both_flag_values(self) -> None:
        from services.ensemble_trainer import _eligibility_where

        for sign_symmetric in (False, True):
            base_where, full_where = _eligibility_where(sign_symmetric)
            assert "passes_walkforward = true" in base_where
            assert "passes_walkforward = true" in full_where

    def test_startup_gate_uses_eligibility_builder(self) -> None:
        from services.ensemble_trainer import _assert_prerequisites

        assert "_eligibility_where" in inspect.getsource(_assert_prerequisites)

    def test_strata_enumeration_and_meta_fdr_denominator_use_eligibility_builder(self) -> None:
        """_execute_inner contains two eligibility-defining queries: the meta-FDR
        denominator (pre-FDR base) and the strata enumeration (full, post-FDR)."""
        from services.ensemble_trainer import EnsembleTrainer

        source = inspect.getsource(EnsembleTrainer._execute_inner)
        assert "_eligibility_where" in source
        assert "eligibility_base_where" in source
        assert "eligibility_where" in source

    def test_stratum_ic_fetch_uses_eligibility_builder(self) -> None:
        from services.ensemble_trainer import EnsembleTrainer

        assert "_eligibility_where" in inspect.getsource(EnsembleTrainer._process_stratum)


class TestSignSymmetricEligibility:
    """Component E (todo 094): alpha.ensemble.sign_symmetric is the champion/challenger
    behavior switch. sign_symmetric=False must reproduce the pre-Component-E predicate
    string byte-for-byte (equivalence property); sign_symmetric=True must admit
    contrarian (ic_sign=-1) rows via a CI-on-their-own-side clause without changing the
    positive-side clause at all."""

    _OLD_BASE_WHERE = (
        "symbol = 'POOLED' AND is_pooled = true AND regime != '_pooled'"
        " AND ic_ci_lower > 0"
        " AND reliable = true AND ic_sharpe_hac IS NOT NULL"
        " AND passes_walkforward = true"
    )

    def test_flag_off_is_byte_identical_to_pre_component_e_predicate(self) -> None:
        from services.ensemble_trainer import _eligibility_where

        base_where, full_where = _eligibility_where(sign_symmetric=False)
        assert base_where == self._OLD_BASE_WHERE
        assert full_where == self._OLD_BASE_WHERE + " AND passes_fdr = true"

    def test_flag_on_admits_negative_sign_via_ci_upper(self) -> None:
        from services.ensemble_trainer import _eligibility_where

        base_where, _ = _eligibility_where(sign_symmetric=True)
        assert "(ic_sign = 1 AND ic_ci_lower > 0)" in base_where
        assert "(ic_sign = -1 AND ic_ci_upper < 0)" in base_where

    def test_flag_on_positive_side_clause_unchanged(self) -> None:
        """ic_sign=1 rows must be admitted by the SAME condition (ic_ci_lower > 0)
        whether the flag is on or off -- only the OR-branch for contrarians is new."""
        from services.ensemble_trainer import _eligibility_where

        base_off, _ = _eligibility_where(sign_symmetric=False)
        base_on, _ = _eligibility_where(sign_symmetric=True)
        assert "ic_ci_lower > 0" in base_off
        assert "ic_ci_lower > 0" in base_on

    def test_effective_sign_symmetric_cli_override_precedence(self) -> None:
        from services.ensemble_trainer import _effective_sign_symmetric

        assert _effective_sign_symmetric(True, False) is True
        assert _effective_sign_symmetric(False, True) is False
        assert _effective_sign_symmetric(None, True) is True
        assert _effective_sign_symmetric(None, False) is False


class TestFeatureStatusAtEvalFilter:
    """Regression lock (LIFECYCLE-02, Phase 143 Plan 03): the feature-IC selection
    query in _process_stratum must keep filtering WHERE feature_status_at_eval =
    'active', excluding candidate and shadow_only periods where IC data was gathered
    but the feature was not (or no longer) actively governed. This is already-correct
    Phase 139 code -- this test exists purely to fail loudly if a future edit silently
    drops the filter, since ic_engine's Plan 03 post-run lifecycle hook now depends on
    this filter to make feature status changes (demotion/promotion) actually take
    effect on the next ensemble_trainer run."""

    def test_stratum_ic_fetch_filters_feature_status_at_eval_active(self) -> None:
        from services.ensemble_trainer import EnsembleTrainer

        source = inspect.getsource(EnsembleTrainer._process_stratum)
        assert "feature_status_at_eval = 'active'" in source


class TestStratumSkipsAreNeverSilent:
    """Regression lock: a timeframe whose every stratum gets skipped (e.g. 1h -- only
    3 total meta-eligible features across all regimes, never enough to clear
    min_passing_features) must be distinguishable from a healthy quiet run. Before this
    fix, every skip path logged at .debug (invisible at the service's configured INFO
    level) and returned None -- a total-coverage blackout on an entire timeframe looked
    identical to nothing-to-report. See CLAUDE.md's "silent wrong answers are worse than
    loud crashes" and T-142B1-04-03's existing "never a silent skip" precedent for
    weight_method_fallback, which this now matches."""

    def test_process_stratum_returns_bool_not_none(self) -> None:
        from services.ensemble_trainer import EnsembleTrainer

        sig = inspect.signature(EnsembleTrainer._process_stratum)
        assert sig.return_annotation == "bool"

    def test_no_skip_path_logs_at_debug_level(self) -> None:
        """Every early-return skip reason must log at .warning or louder -- .debug is
        invisible at this service's configured level, which is exactly how 1h's total
        blackout went unnoticed."""
        from services.ensemble_trainer import EnsembleTrainer

        source = inspect.getsource(EnsembleTrainer._process_stratum)
        assert "log.debug(" not in source

    def test_execute_emits_per_tf_coverage_integrity_fact(self) -> None:
        from services.ensemble_trainer import EnsembleTrainer

        source = inspect.getsource(EnsembleTrainer._execute_inner)
        assert "ensemble_stratum_coverage" in source
        assert "emit_integrity_fact_async" in source


class TestResolvePerTf:
    def test_falls_back_to_default_when_unset(self) -> None:
        from services.ensemble_trainer import _resolve_per_tf

        assert _resolve_per_tf({}, "alpha.ensemble.min_passing_features", "1h", 5) == 5

    def test_uses_per_tf_override_when_set(self) -> None:
        from services.ensemble_trainer import _resolve_per_tf

        cfg = {"alpha.ensemble.min_passing_features.1h": "3"}
        assert _resolve_per_tf(cfg, "alpha.ensemble.min_passing_features", "1h", 5) == 3

    def test_other_timeframes_unaffected_by_1h_override(self) -> None:
        from services.ensemble_trainer import _resolve_per_tf

        cfg = {"alpha.ensemble.min_passing_features.1h": "3"}
        assert _resolve_per_tf(cfg, "alpha.ensemble.min_passing_features", "15m", 5) == 5


class TestAssertFeasibleThresholds:
    def test_raises_on_infeasible_pair(self) -> None:
        from services.ensemble_trainer import _assert_feasible_thresholds

        cfg = {
            "alpha.ensemble.min_passing_features.1h": "2",
            "alpha.ensemble.max_feature_weight.1h": "0.20",
        }
        with pytest.raises(RuntimeError, match="infeasible"):
            _assert_feasible_thresholds(
                cfg, ["1h"], global_min_passing_features=5, global_max_feature_weight=0.20
            )

    def test_passes_on_feasible_pair(self) -> None:
        from services.ensemble_trainer import _assert_feasible_thresholds

        cfg = {
            "alpha.ensemble.min_passing_features.1h": "3",
            "alpha.ensemble.max_feature_weight.1h": "0.34",
        }
        _assert_feasible_thresholds(
            cfg, ["1h"], global_min_passing_features=5, global_max_feature_weight=0.20
        )

    def test_global_default_pair_is_feasible(self) -> None:
        from services.ensemble_trainer import _assert_feasible_thresholds

        _assert_feasible_thresholds(
            {}, ["5m", "15m", "1d"], global_min_passing_features=5, global_max_feature_weight=0.20
        )
