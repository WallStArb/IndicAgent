# src/intelligence/plugins/validator.py

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from prometheus_client import Counter as PrometheusCounter
from prometheus_client import Gauge as PrometheusGauge

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
        from ..intelligence.plugins import registry
        self.registry = registry
        setup_service_logging("plugin_validator")

        # Create Prometheus metrics once to avoid duplicates
        # Handle duplicate registration gracefully (can happen in tests)
        try:
            self._registered_plugins_gauge = PrometheusGauge(
                "plugin_validator_registered_plugins_total",
                "Total registered plugins per tier",
                ["tier"]
            )
        except ValueError:
            # Already registered, get existing instance
            from prometheus_client import REGISTRY
            for collector in REGISTRY._collector_to_names:
                if "plugin_validator_registered_plugins_total" in REGISTRY._collector_to_names[collector]:
                    self._registered_plugins_gauge = collector

        try:
            self._validation_status_gauge = PrometheusGauge(
                "plugin_validator_validation_status",
                "Validation result status",
                ["validation", "status"]
            )
        except ValueError:
            from prometheus_client import REGISTRY
            for collector in REGISTRY._collector_to_names:
                if "plugin_validator_validation_status" in REGISTRY._collector_to_names[collector]:
                    self._validation_status_gauge = collector

        try:
            self._validation_errors_counter = PrometheusCounter(
                "plugin_validator_validation_errors_total",
                "Total validation errors",
                ["validation"]
            )
        except ValueError:
            from prometheus_client import REGISTRY
            for collector in REGISTRY._collector_to_names:
                if "plugin_validator_validation_errors_total" in REGISTRY._collector_to_names[collector]:
                    self._validation_errors_counter = collector

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
                # Try both indicator and pattern registries
                try:
                    plugin = self.registry.get_indicator(plugin_name)
                except KeyError:
                    try:
                        plugin = self.registry.get_pattern(plugin_name)
                    except KeyError:
                        plugin = None
                if plugin is None:
                    results.append(
                        ValidationError(
                            tier=tier_name,
                            plugin=plugin_name,
                            message="Plugin not registered in registry"
                        )
                    )

        return ValidationResult(
            name="tier_list_registration",
            status="PASS" if not results else "FAIL",
            details=results
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
            try:
                plugin = self.registry.get_pattern(plugin_name)
            except KeyError:
                try:
                    plugin = self.registry.get_indicator(plugin_name)
                except KeyError:
                    plugin = None
            if plugin is None:
                continue  # Skip if plugin not found (caught by tier_list_validation)
            if not hasattr(plugin, "regime_type"):
                results.append(
                    ValidationError(
                        tier="I7",
                        plugin=plugin_name,
                        message="Missing required attribute: regime_type"
                    )
                )
            elif plugin.regime_type not in ("trend", "mean_reversion", "any"):
                results.append(
                    ValidationError(
                        tier="I7",
                        plugin=plugin_name,
                        message=f"Invalid regime_type: {plugin.regime_type}"
                    )
                )

        # All plugins need name, outputs, inputs
        for tier_name, tier_list in all_tiers:
            for plugin_name in tier_list:
                try:
                    plugin = self.registry.get_indicator(plugin_name)
                except KeyError:
                    try:
                        plugin = self.registry.get_pattern(plugin_name)
                    except KeyError:
                        plugin = None
                if plugin is None:
                    continue  # Skip if plugin not found (caught by tier_list_validation)
                for attr in ("name", "outputs", "inputs"):
                    if not hasattr(plugin, attr):
                        results.append(
                            ValidationError(
                                tier=tier_name,
                                plugin=plugin_name,
                                message=f"Missing required attribute: {attr}"
                            )
                        )

        return ValidationResult(
            name="required_attributes",
            status="PASS" if not results else "FAIL",
            details=results
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
                details=[ValidationError(
                    tier="unknown",
                    plugin="schema",
                    message=str(e)
                )]
            )

    def _detect_orphaned_plugins(self) -> ValidationResult:
        """Verify all imported plugin modules have corresponding files."""

        import re

        plugin_dir = Path(__file__).parent.parent / "intelligence"
        register_plugins_path = plugin_dir / "register_plugins.py"
        content = register_plugins_path.read_text()

        # Extract all import statements from register_plugins.py
        # Pattern matches: from .indicators.<name> import plugin
        # NOT: from .composites.adx_events import plugin (subdirectory)
        imported_plugins = re.findall(r"from \.(indicators|patterns)\.(\w+) import plugin", content)

        # Verify each imported module has a file
        missing_files = []
        for category, module_name in imported_plugins:
            # Convert to file path: intelligence/indicators/<module_name>.py
            module_file = plugin_dir / category / f"{module_name}.py"
            if not module_file.exists():
                missing_files.append(
                    ValidationError(
                        tier="unknown",
                        plugin=f"{category}.{module_name}",
                        message=f"Missing import module file: {module_file}"
                    )
                )

        return ValidationResult(
            name="orphaned_plugins",
            status="PASS" if not missing_files else "WARN",
            details=missing_files
        )

    def _validate_trend_sets_sync(self) -> ValidationResult:
        """Ensure TREND_SETUPS in aggregator matches TIER_I7."""


        # Derive expected trend setups from TIER_I7
        expected_trends = frozenset()
        for plugin_name in TIER_I7:
            try:
                plugin = self.registry.get_pattern(plugin_name)
            except KeyError:
                try:
                    plugin = self.registry.get_indicator(plugin_name)
                except KeyError:
                    plugin = None
            if plugin is not None and hasattr(plugin, "regime_type"):
                if plugin.regime_type == "trend":
                    expected_trends |= frozenset([plugin.name])

        if TREND_SETUPS != expected_trends:
            diff = (TREND_SETUPS - expected_trends) | (expected_trends - TREND_SETUPS)
            return ValidationResult(
                name="trend_sets_sync",
                status="FAIL",
                details=[ValidationError(
                    tier="I7",
                    plugin="aggregator",
                    message=f"TREND_SETUPS out of sync with TIER_I7: {diff}"
                )]
            )

        return ValidationResult(
            name="trend_sets_sync",
            status="PASS",
            details=[]
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
            self._registered_plugins_gauge.labels(tier=tier_name).set(len(tier_list))

        # Validation status
        for result in report.results:
            self._validation_status_gauge.labels(
                validation=result.name,
                status=result.status
            ).set(1 if result.status == "PASS" else 0)

        # Error count
        for result in report.results:
            if result.status != "PASS":
                self._validation_errors_counter.labels(
                    validation=result.name
                ).inc(len(result.details))
