"""
Centralized Backend Management for Technical Analysis Indicators.

This module provides unified backend detection, import management, and
configuration for all technical analysis indicator modules.
"""

from enum import Enum
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class Backend(Enum):
    """Supported technical analysis backends."""

    PANDAS_TA = "pandas_ta"
    TALIB = "talib"
    FINTA = "finta"
    MANUAL = "manual"


class BackendManager:
    """
    Centralized backend management for technical analysis calculations.

    Features:
    - Single source of truth for backend availability
    - Lazy loading of backend libraries
    - Performance optimization through singleton pattern
    - Centralized error handling for imports
    - Latest API usage for all backends
    """

    _instance: Optional["BackendManager"] = None
    _backends_initialized: bool = False

    def __new__(cls) -> "BackendManager":
        """Singleton pattern implementation."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize backend manager (singleton-safe)."""
        if not self._backends_initialized:
            self._available_backends: dict[Backend, bool] = {}
            self._backend_modules: dict[Backend, Any] = {}
            self._backend_versions: dict[Backend, str] = {}
            self._detect_all_backends()
            self._backends_initialized = True

    def _detect_all_backends(self) -> None:
        """Detect all available backends and load modules."""
        backend_configs = {
            Backend.TALIB: {
                "import_name": "talib",
                "module_attr": "talib",
                "test_attr": "__version__",
                "priority": 1,  # Highest priority - TA-Lib preferred
            },
            Backend.PANDAS_TA: {
                "import_name": "pandas_ta",
                "module_attr": "pandas_ta",
                "test_attr": "version",
                "priority": 2,  # Second priority - comprehensive (130+ indicators)
            },
            Backend.FINTA: {
                "import_name": "finta",
                "module_attr": "TA",
                "test_attr": None,
                "priority": 3,  # Third priority - fallback
            },
        }

        for backend, config in backend_configs.items():
            try:
                module = __import__(config["import_name"])

                # Test that the module is properly loaded
                if config["test_attr"] and hasattr(module, config["test_attr"]):
                    test_val = getattr(module, config["test_attr"])
                    self._backend_versions[backend] = str(test_val)

                # Store the specific module/class we need
                if config["module_attr"] == "TA":
                    from finta import TA

                    self._backend_modules[backend] = TA
                else:
                    self._backend_modules[backend] = module

                self._available_backends[backend] = True
                logger.info(
                    f"Backend {backend.value} detected and loaded",
                    version=self._backend_versions.get(backend, "unknown"),
                    priority=config["priority"],
                    capabilities=self._get_backend_capabilities(backend),
                )

            except ImportError as e:
                self._available_backends[backend] = False
                logger.debug(f"Backend {backend.value} not available: {e}")
            except Exception as e:
                self._available_backends[backend] = False
                logger.warning(f"Error loading backend {backend.value}: {e}")

    def _get_backend_capabilities(self, backend: Backend) -> str:
        """Get human-readable capabilities for a backend."""
        capabilities = {
            Backend.PANDAS_TA: "130+ indicators, vectorized operations, pandas integration",
            Backend.TALIB: "158 functions, C-optimized performance, industry standard",
            Backend.FINTA: "Pure Python, easy installation, good documentation",
            Backend.MANUAL: "Custom calculations, fallback implementation",
        }
        return capabilities.get(backend, "Unknown capabilities")

    def is_available(self, backend: Backend) -> bool:
        """Check if a backend is available."""
        return self._available_backends.get(backend, False)

    def get_module(self, backend: Backend) -> Any | None:
        """Get the module for a specific backend."""
        return self._backend_modules.get(backend)

    def get_version(self, backend: Backend) -> str | None:
        """Get the version of a specific backend."""
        return self._backend_versions.get(backend)

    def detect_best_backend(
        self,
        preferred: str | Backend | None = None,
        priority_order: list[Backend] | None = None,
    ) -> Backend:
        """
        Detect the best available backend based on priority.

        Priority order (best to worst):
        1. talib - TA-Lib preferred (performance optimized, industry standard)
        2. pandas_ta - Comprehensive fallback (130+ indicators)
        3. finta - Pure Python fallback (easy installation)
        4. manual - Custom calculations
        """
        if priority_order is None:
            priority_order = [
                Backend.TALIB,  # TA-Lib preferred
                Backend.PANDAS_TA,  # Comprehensive fallback
                Backend.FINTA,  # Pure Python fallback
                Backend.MANUAL,  # Custom calculations
            ]

        # If preferred is specified and available, use it
        if preferred:
            if isinstance(preferred, str):
                # Handle "auto" string
                if preferred.lower() == "auto":
                    # Let the priority order determine the best backend
                    pass
                else:
                    try:
                        preferred = Backend(preferred)
                        if self.is_available(preferred):
                            logger.info(f"Using preferred backend: {preferred.value}")
                            return preferred
                    except ValueError:
                        logger.warning(f"Invalid backend preference: {preferred}")
            else:
                if self.is_available(preferred):
                    logger.info(f"Using preferred backend: {preferred.value}")
                    return preferred

        # Find the best available backend based on priority order
        for backend in priority_order:
            if self.is_available(backend):
                logger.info(f"Selected backend: {backend.value}")
                return backend

        # If no backend is available, fall back to manual
        logger.warning("No technical analysis backend available, using manual calculations")
        return Backend.MANUAL

    def get_backend_info(self) -> dict[str, Any]:
        """Get comprehensive information about all backends."""
        info = {
            "available_backends": {},
            "recommended_backend": None,
            "backend_priorities": {
                "pandas_ta": "Primary - Most comprehensive (130+ indicators)",
                "talib": "Secondary - Performance optimized (158 functions)",
                "finta": "Fallback - Pure Python implementation",
                "manual": "Last resort - Custom calculations",
            },
        }

        for backend in Backend:
            is_available = self.is_available(backend)
            version = self.get_version(backend) if is_available else None

            info["available_backends"][backend.value] = {
                "available": is_available,
                "version": version,
                "module_loaded": backend in self._backend_modules,
            }

        # Determine recommended backend
        recommended = self.detect_best_backend()
        info["recommended_backend"] = {
            "name": recommended.value,
            "version": self.get_version(recommended),
            "reason": "Best available based on priority order",
        }

        return info

    def get_all_available_backends(self) -> list[Backend]:
        """Get all available backends."""
        return [backend for backend in Backend if self.is_available(backend)]

    def get_backend_capabilities(self) -> dict[str, list[str]]:
        """Get capabilities of each available backend."""
        capabilities = {
            "pandas_ta": [
                "130+ indicators",
                "Vectorized operations",
                "Pandas integration",
                "Custom indicators",
                "Real-time calculations",
            ],
            "talib": [
                "158 functions",
                "C-optimized performance",
                "Industry standard",
                "Professional grade",
                "Low-level control",
            ],
            "finta": [
                "Pure Python",
                "Easy installation",
                "Good documentation",
                "Cross-platform",
                "Educational",
            ],
            "manual": [
                "Custom calculations",
                "Full control",
                "No dependencies",
                "Educational",
                "Fallback option",
            ],
        }

        return {
            backend.value: capabilities[backend.value]
            for backend in Backend
            if self.is_available(backend)
        }


# Global instance
_backend_manager: BackendManager | None = None


def get_backend_manager() -> BackendManager:
    """Get the global backend manager instance."""
    global _backend_manager
    if _backend_manager is None:
        _backend_manager = BackendManager()
    return _backend_manager


def detect_backend(preferred: str | None = None) -> Backend:
    """Detect the best available backend."""
    manager = get_backend_manager()
    return manager.detect_best_backend(preferred)


def is_backend_available(backend: str | Backend) -> bool:
    """Check if a specific backend is available."""
    manager = get_backend_manager()
    if isinstance(backend, str):
        backend = Backend(backend)
    return manager.is_available(backend)
