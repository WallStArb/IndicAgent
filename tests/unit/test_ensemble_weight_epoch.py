"""Unit tests for per-run weight epoch + DO UPDATE upsert + APR-backed stale cliff.

Covers Task 2 of Phase 141.1 Plan 04: EnsembleConfig.weight_stale_max_days binding,
_effective_weight_version CLI-override helper, and the DO UPDATE (not DO NOTHING)
upsert SQL at both ensemble_weights and ensemble_alpha write sites.

No live DB — pure unit tests against config-binding logic and module source text.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import services.ensemble_trainer as ensemble_trainer_module
from services.ensemble_trainer import EnsembleConfig, _effective_weight_version


class TestWeightStaleMaxDaysBinding:
    """EnsembleConfig.from_apr must bind weight_stale_max_days from APR."""

    def test_binds_from_apr_key(self) -> None:
        cfg = {"alpha.ensemble.weight_stale_max_days": "45"}
        config = EnsembleConfig.from_apr(cfg)
        assert config.weight_stale_max_days == 45
        assert isinstance(config.weight_stale_max_days, int)

    def test_defaults_to_90_when_missing(self) -> None:
        cfg: dict = {}
        config = EnsembleConfig.from_apr(cfg)
        assert config.weight_stale_max_days == 90


class TestEffectiveWeightVersion:
    """_effective_weight_version(cli_arg, apr_default) resolves the per-run epoch."""

    def test_returns_cli_value_when_provided(self) -> None:
        assert _effective_weight_version("run_20260624", "v1") == "run_20260624"

    def test_returns_apr_default_when_cli_none(self) -> None:
        assert _effective_weight_version(None, "v1") == "v1"

    def test_returns_apr_default_when_cli_empty_string(self) -> None:
        assert _effective_weight_version("", "v1") == "v1"


class TestUpsertSQL:
    """ensemble_weights and ensemble_alpha INSERTs must use DO UPDATE, never DO NOTHING."""

    def _source(self) -> str:
        return inspect.getsource(ensemble_trainer_module)

    def test_no_do_nothing_remains(self) -> None:
        source = self._source()
        assert "DO NOTHING" not in source

    def test_ensemble_weights_insert_uses_do_update(self) -> None:
        source = self._source()
        assert "ON CONFLICT (symbol, tf, regime, weight_version, feature_name)" in source
        assert "DO UPDATE SET" in source

    def test_ensemble_alpha_insert_uses_do_update(self) -> None:
        source = self._source()
        assert "ON CONFLICT (symbol, tf, bar_ts, weight_version)" in source
        assert "DO UPDATE SET" in source


class TestStaleCliffUsesAPR:
    """The aging branch must reference config.weight_stale_max_days, not a literal 90."""

    def test_no_bare_literal_90_comparison(self) -> None:
        source = inspect.getsource(ensemble_trainer_module)
        assert "> 90" not in source

    def test_aging_logic_references_weight_stale_max_days(self) -> None:
        source = inspect.getsource(ensemble_trainer_module)
        assert "config.weight_stale_max_days" in source


class TestWeightVersionCLIOverride:
    """EnsembleTrainer accepts a CLI weight-version override threaded into config."""

    def test_init_accepts_weight_version_override(self) -> None:
        from services.ensemble_trainer import EnsembleTrainer

        trainer = EnsembleTrainer(
            db_dsn="postgresql://localhost/test", weight_version_override="run_20260624"
        )
        assert trainer._weight_version_override == "run_20260624"

    def test_init_defaults_weight_version_override_to_none(self) -> None:
        from services.ensemble_trainer import EnsembleTrainer

        trainer = EnsembleTrainer(db_dsn="postgresql://localhost/test")
        assert trainer._weight_version_override is None
