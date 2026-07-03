"""Unit tests for ensemble_trainer.py's E1 alpha.ensemble.ic_input wiring (Phase 142B.1-03).

Covers the pure column-resolution helper and the APR compile-time binding contract.
No DB — mirrors tests/unit/test_ensemble_trainer.py's mock-free, class-contract style.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from services.ensemble_trainer import EnsembleConfig, _resolve_ic_input_column


class TestResolveIcInputColumn:
    def test_default_resolves_to_ic_sharpe_hac(self) -> None:
        assert _resolve_ic_input_column("ic_sharpe_hac") == "ic_sharpe_hac"

    def test_ic_shrunk_resolves_to_ic_shrunk(self) -> None:
        assert _resolve_ic_input_column("ic_shrunk") == "ic_shrunk"

    def test_unknown_value_raises_value_error(self) -> None:
        """Fail loud on an unknown ic_input value -- never silently fall back to the
        wrong column (D-05)."""
        with pytest.raises(ValueError, match="Unknown alpha.ensemble.ic_input value"):
            _resolve_ic_input_column("not_a_real_column")

    def test_empty_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            _resolve_ic_input_column("")


class TestEnsembleConfigIcInputField:
    def test_from_apr_default_is_ic_sharpe_hac(self) -> None:
        """No alpha.ensemble.ic_input key present -> defaults to 'ic_sharpe_hac'
        (v1 behavior preserved when the APR key is unset)."""
        config = EnsembleConfig.from_apr({})
        assert config.ic_input == "ic_sharpe_hac"

    def test_from_apr_reads_ic_shrunk_override(self) -> None:
        config = EnsembleConfig.from_apr({"alpha.ensemble.ic_input": "ic_shrunk"})
        assert config.ic_input == "ic_shrunk"

    def test_ic_input_field_exists_on_dataclass(self) -> None:
        assert "ic_input" in EnsembleConfig.__dataclass_fields__


class TestSourceStructure:
    """Grep-style source assertions matching the plan's acceptance criteria."""

    def test_ic_input_loaded_via_cfg_helper_not_ad_hoc(self) -> None:
        source = Path(project_root / "services" / "ensemble_trainer.py").read_text()
        assert '_cfg(cfg, "alpha.ensemble.ic_input", "ic_sharpe_hac")' in source

    def test_ic_shrunk_where_clause_present(self) -> None:
        source = Path(project_root / "services" / "ensemble_trainer.py").read_text()
        assert "ic_shrunk IS NOT NULL" in source

    def test_no_ad_hoc_config_service_get_calls_added(self) -> None:
        """Acceptance criterion: grep count of ConfigService.get must not increase --
        all APR reads go through EnsembleConfig.from_apr(), never scattered ad hoc
        calls inside _process_stratum."""
        source = Path(project_root / "services" / "ensemble_trainer.py").read_text()
        assert source.count("ConfigService.get") == 0
