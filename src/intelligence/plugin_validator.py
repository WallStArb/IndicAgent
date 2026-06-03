# src/intelligence/plugins/validator.py

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.service_utils import setup_service_logging

# Deferred import to avoid circular import with plugins/__init__.py
# Registry imported in __init__() when needed
from src.intelligence.register_plugins import (
    TIER_I1,
    TIER_I2,
    TIER_I3,
    TIER_I4,
    TIER_I5,
    TIER_I6,
    TIER_I7,
    TIER_SMC,
    validate_schema_coverage,
)
from src.intelligence.trading.aggregator import TREND_SETUPS

# ---------------------------------------------------------------------------
# Module-level OTel metrics (imported from central registry — Task 2)
# ---------------------------------------------------------------------------
from src.observability.metrics import (  # noqa: E402
    PLUGIN_VALIDATOR_ERRORS as _VALIDATION_ERRORS_COUNTER,
)
from src.observability.metrics import (
    PLUGIN_VALIDATOR_REGISTERED_PLUGINS as _REGISTERED_PLUGINS_GAUGE,
)
from src.observability.metrics import (
    PLUGIN_VALIDATOR_VALIDATION_STATUS as _VALIDATION_STATUS_GAUGE,
)


def build_synthetic_frames(n: int = 60, seed: int = 0) -> dict[str, pd.DataFrame]:
    """Synthetic OHLCV frames for plugin state-contract probing."""
    rng = np.random.default_rng(seed)
    close = 5000.0 * np.cumprod(1 + rng.normal(0.0001, 0.005, n))
    spread = rng.uniform(0.001, 0.003, n)
    open_ = close * (1 + rng.normal(0, 0.001, n))
    high = np.maximum(close * (1 + spread), close)
    low = np.minimum(close * (1 - spread), close)
    # Second pass ensures high/low envelope the perturbed open as well
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))
    volume = rng.lognormal(10, 0.5, n).astype(float)
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})
    return {"main": df}


@dataclass
class ValidationError:
    """Represents a single validation error."""

    tier: str
    plugin: str
    message: str


@dataclass
class ValidationResult:
    """Represents result of a single validation check."""

    name: str
    status: str  # "PASS", "FAIL", "WARN"
    details: list[ValidationError]


@dataclass
class ValidationReport:
    """Comprehensive validation report with all check results."""

    results: list[ValidationResult] = field(default_factory=list)

    def add(self, result: ValidationResult) -> None:
        self.results.append(result)

    def has_errors(self) -> bool:
        return any(r.status == "FAIL" for r in self.results)

    def error_count(self) -> int:
        return sum(len(r.details) for r in self.results if r.status != "PASS")

    def result_for(self, name: str) -> ValidationResult | None:
        for r in self.results:
            if r.name == name:
                return r
        return None

    def print_details(self) -> None:
        """Print detailed error output for logs."""
        for r in self.results:
            if r.status != "PASS":
                for error in r.details:
                    print(f"  [{r.name}] {error.tier}/{error.plugin}: {error.message}")


class PluginValidator:
    """Comprehensive validation of plugin registration state.

    Runs at service startup to ensure:
    - All tier list plugins are registered
    - All registered plugins have required attributes
    - No orphaned plugin files exist in filesystem
    - All plugin outputs are covered by schema
    - TREND_SETUPS matches TIER_I7 regime_type="trend" entries

    Emits Prometheus metrics for instrumentation.
    """

    def __init__(self) -> None:
        # Lazy import to avoid circular import
        from src.intelligence.plugins import registry

        self.registry = registry
        setup_service_logging("logs/plugin_validator.log")

        # Reference module-level OTel instruments (imported from metrics.py)
        self._registered_plugins_gauge = _REGISTERED_PLUGINS_GAUGE
        self._validation_status_gauge = _VALIDATION_STATUS_GAUGE
        self._validation_errors_counter = _VALIDATION_ERRORS_COUNTER

    def validate_all(self) -> ValidationReport:
        """Run all validations and return comprehensive report."""
        report = ValidationReport()

        # 1. Tier list validation
        report.add(self._validate_tier_lists())

        # 2. Required attributes
        report.add(self._validate_required_attributes())

        # 3. Schema coverage
        report.add(self._validate_schema_coverage())

        # 4. Orphan detection (filesystem scan)
        report.add(self._detect_orphaned_plugins())

        # 5. TREND_SETUPS sync
        report.add(self._validate_trend_sets_sync())

        # 6. SETUP_PRIORITY completeness (Phase 112: no-op, dict removed, ranking is data-driven)
        report.add(self._validate_setup_priority_sync())

        # 7. Incremental _state contract
        report.add(self._validate_incremental_state_contract())

        # Emit metrics
        self._emit_metrics(report)

        # Hard-crash on errors
        if report.has_errors():
            report.print_details()
            raise RuntimeError(f"Plugin validation failed: {report.error_count()} errors")

        return report

    def _validate_tier_lists(self) -> ValidationResult:
        """Ensure all plugins in TIER_* lists are registered."""

        results = []

        all_tiers = [
            ("I1", TIER_I1),
            ("I2", TIER_I2),
            ("I3", TIER_I3),
            ("I4", TIER_I4),
            ("I5", TIER_I5),
            ("SMC", TIER_SMC),
            ("I6", TIER_I6),
            ("I7", TIER_I7),
        ]

        for tier_name, tier_list in all_tiers:
            for plugin_name in tier_list:
                plugin = self.registry.get_indicator(plugin_name) or self.registry.get_pattern(
                    plugin_name
                )
                if plugin is None:
                    results.append(
                        ValidationError(
                            tier=tier_name,
                            plugin=plugin_name,
                            message="Plugin not registered in registry",
                        )
                    )

        return ValidationResult(
            name="tier_list_registration", status="PASS" if not results else "FAIL", details=results
        )

    def _validate_required_attributes(self) -> ValidationResult:
        """Ensure plugins have required class attributes."""

        results = []

        all_tiers = [
            ("I1", TIER_I1),
            ("I2", TIER_I2),
            ("I3", TIER_I3),
            ("I4", TIER_I4),
            ("I5", TIER_I5),
            ("SMC", TIER_SMC),
            ("I6", TIER_I6),
            ("I7", TIER_I7),
        ]

        # I7 requires regime_type
        for plugin_name in TIER_I7:
            plugin = self.registry.get_pattern(plugin_name) or self.registry.get_indicator(
                plugin_name
            )
            if plugin is None:
                continue  # Skip if plugin not found (caught by tier_list_validation)
            if not hasattr(plugin, "regime_type"):
                results.append(
                    ValidationError(
                        tier="I7",
                        plugin=plugin_name,
                        message="Missing required attribute: regime_type",
                    )
                )
            elif plugin.regime_type not in ("trend", "mean_reversion", "any"):
                results.append(
                    ValidationError(
                        tier="I7",
                        plugin=plugin_name,
                        message=f"Invalid regime_type: {plugin.regime_type}",
                    )
                )

        # All plugins need name, outputs, inputs
        for tier_name, tier_list in all_tiers:
            for plugin_name in tier_list:
                plugin = self.registry.get_indicator(plugin_name) or self.registry.get_pattern(
                    plugin_name
                )
                if plugin is None:
                    continue  # Skip if plugin not found (caught by tier_list_validation)
                for attr in ("name", "outputs", "inputs"):
                    if not hasattr(plugin, attr):
                        results.append(
                            ValidationError(
                                tier=tier_name,
                                plugin=plugin_name,
                                message=f"Missing required attribute: {attr}",
                            )
                        )

        return ValidationResult(
            name="required_attributes", status="PASS" if not results else "FAIL", details=results
        )

    def _validate_schema_coverage(self) -> ValidationResult:
        """Reuse existing validate_schema_coverage() function."""

        try:
            validate_schema_coverage()  # Raises RuntimeError on gaps
            return ValidationResult(name="schema_coverage", status="PASS", details=[])
        except RuntimeError as e:
            # Parse error message to extract gaps
            return ValidationResult(
                name="schema_coverage",
                status="FAIL",
                details=[ValidationError(tier="unknown", plugin="schema", message=str(e))],
            )

    def _detect_orphaned_plugins(self) -> ValidationResult:
        """Verify all imported plugin modules have corresponding files."""

        import re

        plugin_dir = Path(__file__).parent.parent / "intelligence"
        register_plugins_path = plugin_dir / "register_plugins.py"
        content = register_plugins_path.read_text()

        # Extract all import statements from register_plugins.py
        # Pattern matches: from src.intelligence.features.<tier>.<name> import plugin
        imported_plugins = re.findall(
            r"from src\.intelligence\.features\.([\w]+)\.([\w]+) import plugin", content
        )

        # Verify each imported module has a file
        missing_files = []
        for category, module_name in imported_plugins:
            # Convert to file path: intelligence/features/<tier>/<module_name>.py
            module_file = plugin_dir / "features" / category / f"{module_name}.py"
            if not module_file.exists():
                missing_files.append(
                    ValidationError(
                        tier="unknown",
                        plugin=f"{category}.{module_name}",
                        message=f"Missing import module file: {module_file}",
                    )
                )

        return ValidationResult(
            name="orphaned_plugins",
            status="PASS" if not missing_files else "WARN",
            details=missing_files,
        )

    def _validate_trend_sets_sync(self) -> ValidationResult:
        """Ensure TREND_SETUPS in aggregator matches TIER_I7."""

        # Derive expected trend setups from TIER_I7
        expected_trends = frozenset()
        for plugin_name in TIER_I7:
            plugin = self.registry.get_pattern(plugin_name) or self.registry.get_indicator(
                plugin_name
            )
            if plugin is not None and hasattr(plugin, "regime_type"):
                if plugin.regime_type == "trend":
                    expected_trends |= frozenset([plugin.name])

        if TREND_SETUPS != expected_trends:
            diff = (TREND_SETUPS - expected_trends) | (expected_trends - TREND_SETUPS)
            return ValidationResult(
                name="trend_sets_sync",
                status="FAIL",
                details=[
                    ValidationError(
                        tier="I7",
                        plugin="aggregator",
                        message=f"TREND_SETUPS out of sync with TIER_I7: {diff}",
                    )
                ],
            )

        return ValidationResult(name="trend_sets_sync", status="PASS", details=[])

    def _validate_setup_priority_sync(self) -> ValidationResult:
        """Phase 112 2-C: SETUP_PRIORITY removed — validation replaced by no-op PASS.

        Ranking is now fully data-driven via perf_multiplier from setup_performance.
        This validator previously checked SETUP_PRIORITY completeness; that check
        is no longer relevant since the dict no longer exists.
        """
        return ValidationResult(
            name="setup_priority_sync",
            status="PASS",
            details=[],
        )

    def _validate_incremental_state_contract(self) -> ValidationResult:
        """Verify every incremental plugin returns _state in compute_next() output.

        Catches the class of bug where a developer sets supports_incremental=True
        but forgets to include _state in the compute_next() return dict, causing
        silent state corruption in production (the Renaissance bug).
        """
        frames = build_synthetic_frames()
        all_tiers = [
            ("I1", TIER_I1),
            ("I2", TIER_I2),
            ("I3", TIER_I3),
            ("I4", TIER_I4),
            ("I5", TIER_I5),
            ("SMC", TIER_SMC),
            ("I6", TIER_I6),
            ("I7", TIER_I7),
        ]

        errors: list[ValidationError] = []

        def add_error(tier: str, plugin: str, message: str) -> None:
            errors.append(ValidationError(tier=tier, plugin=plugin, message=message))

        missing_state_hint = "Pattern: return {**outputs, '_state': state}"

        for tier_name, tier_list in all_tiers:
            for plugin_name in tier_list:
                plugin = self.registry.get_indicator(plugin_name) or self.registry.get_pattern(
                    plugin_name
                )
                if plugin is None or not getattr(plugin, "supports_incremental", False):
                    continue

                # Phase 1: seed state via compute_full()
                try:
                    seed_result = plugin.compute_full(frames)
                except Exception as error:
                    add_error(
                        tier_name,
                        plugin_name,
                        f"compute_full() raised during state contract check: {error}",
                    )
                    continue

                if not isinstance(seed_result, dict) or not seed_result:
                    continue

                if "_state" not in seed_result:
                    add_error(
                        tier_name,
                        plugin_name,
                        f"compute_full() returned non-empty dict without _state. {missing_state_hint}",
                    )
                    continue

                state = seed_result.get("_state")
                if not state:
                    continue

                # Phase 2: incremental step via compute_next()
                try:
                    result = plugin.compute_next(frames, state=state)
                except Exception as error:
                    add_error(
                        tier_name,
                        plugin_name,
                        f"compute_next() raised during state contract check: {error}",
                    )
                    continue

                if isinstance(result, dict) and result and "_state" not in result:
                    add_error(
                        tier_name,
                        plugin_name,
                        f"compute_next() returned non-empty dict without _state. {missing_state_hint}",
                    )

        return ValidationResult(
            name="incremental_state_contract",
            status="PASS" if not errors else "FAIL",
            details=errors,
        )

    def _emit_metrics(self, report: ValidationReport) -> None:
        """Emit Prometheus metrics for instrumentation."""

        all_tiers = [
            ("I1", TIER_I1),
            ("I2", TIER_I2),
            ("I3", TIER_I3),
            ("I4", TIER_I4),
            ("I5", TIER_I5),
            ("SMC", TIER_SMC),
            ("I6", TIER_I6),
            ("I7", TIER_I7),
        ]

        # Plugin counts per tier
        for tier_name, tier_list in all_tiers:
            self._registered_plugins_gauge.add(len(tier_list), {"tier": tier_name})

        # Validation status
        for result in report.results:
            self._validation_status_gauge.add(
                1 if result.status == "PASS" else 0,
                {"validation": result.name, "status": result.status},
            )

        # Error count
        for result in report.results:
            if result.status != "PASS":
                self._validation_errors_counter.add(
                    len(result.details), {"validation": result.name}
                )
