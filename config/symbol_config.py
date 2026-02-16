"""
Symbol Configuration Manager - Single Source of Truth

Manages all market symbols for the IndicAgent platform.
Provides centralized symbol management with base symbols and active contracts.
"""

import json
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


class SymbolConfig:
    """Centralized symbol configuration manager."""

    # Base symbols - single source of truth
    BASE_SYMBOLS = {
        "ES": {"name": "E-mini S&P 500", "exchange": "CME", "point_value": 50, "tick_size": 0.25},
        "NQ": {"name": "E-mini Nasdaq", "exchange": "CME", "point_value": 20, "tick_size": 0.25},
        "RTY": {
            "name": "E-mini Russell 2000",
            "exchange": "CME",
            "point_value": 50,
            "tick_size": 0.10,
        },
        "CL": {
            "name": "Crude Oil WTI",
            "exchange": "NYMEX",
            "point_value": 1000,
            "tick_size": 0.01,
        },
        "NG": {
            "name": "Natural Gas",
            "exchange": "NYMEX",
            "point_value": 10000,
            "tick_size": 0.001,
        },
        "GC": {"name": "Gold", "exchange": "COMEX", "point_value": 100, "tick_size": 0.10},
        "SI": {"name": "Silver", "exchange": "COMEX", "point_value": 5000, "tick_size": 0.005},
        "PL": {"name": "Platinum", "exchange": "NYMEX", "point_value": 50, "tick_size": 0.10},
        "HG": {"name": "Copper", "exchange": "COMEX", "point_value": 25000, "tick_size": 0.0005},
        "VX": {
            "name": "CBOE VIX Futures",
            "exchange": "CFE",
            "point_value": 1000,
            "tick_size": 0.05,
        },
    }

    def __init__(self, config_path: str | None = None):
        """Initialize symbol configuration."""
        if config_path is None:
            config_path = Path(__file__).parent / "dashboard_symbols.json"

        self.config_path = Path(config_path)
        self._config = None
        self.load_config()

    def load_config(self) -> dict:
        """Load configuration from JSON file."""
        try:
            with open(self.config_path) as f:
                self._config = json.load(f)

            logger.info(f"✅ Loaded symbol configuration from {self.config_path}")
            return self._config

        except FileNotFoundError:
            logger.error(f"❌ Symbol config file not found: {self.config_path}")
            # Return default configuration
            self._config = {
                "dashboard_symbols": {"futures": [], "etfs": []},
                "active_profile": "futures",
                "profiles": {"futures": {"symbols": list(self.BASE_SYMBOLS.keys())}},
            }
            return self._config

        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in symbol config: {e}")
            raise

    def get_base_symbols(self) -> list[str]:
        """Get all base symbols."""
        return list(self.BASE_SYMBOLS.keys())

    def get_base_symbol_info(self, symbol: str) -> dict | None:
        """Get information for a base symbol."""
        return self.BASE_SYMBOLS.get(symbol)

    def get_active_contracts(self) -> list[str]:
        """Get currently active futures contracts."""
        # This would typically be determined by current date and rollover logic
        # For now, return the most common active contracts
        # Front-month contracts as of Feb 2026
        current_contracts = [
            "ESH6",   # S&P 500 E-mini (Mar 2026)
            "NQH6",   # Nasdaq E-mini (Mar 2026)
            "RTYH6",  # Russell E-mini (Mar 2026)
            "CLH6",   # Crude Oil (Mar 2026)
            "NGH6",   # Natural Gas (Mar 2026)
            "GCJ6",   # Gold (Apr 2026)
            "SIH6",   # Silver (Mar 2026)
            "PLJ6",   # Platinum (Apr 2026)
            "HGH6",   # Copper (Mar 2026)
            "VXH6",   # VIX (Mar 2026)
        ]
        return current_contracts

    def get_all_symbols(self) -> list[str]:
        """Get all symbols (base + active contracts)."""
        base_symbols = self.get_base_symbols()
        active_contracts = self.get_active_contracts()
        return base_symbols + active_contracts

    def get_active_symbols(self) -> list[str]:
        """Get symbols for the active profile."""
        if not self._config:
            self.load_config()

        active_profile = self._config.get("active_profile", "futures")
        profiles = self._config.get("profiles", {})

        if active_profile in profiles:
            symbols = profiles[active_profile].get("symbols", [])
            logger.info(f"📊 Active profile '{active_profile}': {symbols}")
            return symbols

        # Fallback to base symbols
        logger.warning(f"⚠️ Profile '{active_profile}' not found, using base symbols")
        return self.get_base_symbols()

    def get_symbol_info(self, symbol: str) -> dict | None:
        """Get detailed information for a symbol."""
        # Check base symbols first
        if symbol in self.BASE_SYMBOLS:
            return self.BASE_SYMBOLS[symbol]

        # Check configuration file
        if not self._config:
            self.load_config()

        dashboard_symbols = self._config.get("dashboard_symbols", {})

        # Check futures
        for future in dashboard_symbols.get("futures", []):
            if future.get("symbol") == symbol:
                return future

        # Check ETFs
        for etf in dashboard_symbols.get("etfs", []):
            if etf.get("symbol") == symbol:
                return etf

        return None

    def get_all_profiles(self) -> dict[str, dict]:
        """Get all available profiles."""
        if not self._config:
            self.load_config()

        return self._config.get("profiles", {})

    def set_active_profile(self, profile_name: str) -> bool:
        """Set the active profile."""
        if not self._config:
            self.load_config()

        profiles = self._config.get("profiles", {})
        if profile_name not in profiles:
            logger.error(f"❌ Profile '{profile_name}' not found")
            return False

        self._config["active_profile"] = profile_name

        # Save back to file
        try:
            with open(self.config_path, "w") as f:
                json.dump(self._config, f, indent=2)

            logger.info(f"✅ Set active profile to '{profile_name}'")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to save config: {e}")
            return False

    def get_display_name(self, symbol: str) -> str:
        """Get display name for a symbol."""
        info = self.get_symbol_info(symbol)
        if info and "name" in info:
            return info["name"]
        return symbol

    def get_contract_code(self, symbol: str) -> str:
        """Get contract code for futures symbols."""
        info = self.get_symbol_info(symbol)
        if info and "contract" in info:
            return info["contract"]
        return symbol

    def is_futures_symbol(self, symbol: str) -> bool:
        """Check if symbol is a futures contract."""
        return symbol in self.BASE_SYMBOLS or symbol in self.get_active_contracts()

    def is_base_symbol(self, symbol: str) -> bool:
        """Check if symbol is a base symbol."""
        return symbol in self.BASE_SYMBOLS

    def get_exchange(self, symbol: str) -> str | None:
        """Get exchange for a symbol."""
        info = self.get_symbol_info(symbol)
        if info and "exchange" in info:
            return info["exchange"]
        return None

    def get_point_value(self, symbol: str) -> float | None:
        """Get point value for a futures symbol."""
        info = self.get_symbol_info(symbol)
        if info and "point_value" in info:
            return info["point_value"]
        return None

    def get_tick_size(self, symbol: str) -> float | None:
        """Get tick size for a futures symbol."""
        info = self.get_symbol_info(symbol)
        if info and "tick_size" in info:
            return info["tick_size"]
        return None


# Global instance
symbol_config = SymbolConfig()


def get_base_symbols() -> list[str]:
    """Get all base symbols."""
    return symbol_config.get_base_symbols()


def get_active_contracts() -> list[str]:
    """Get currently active futures contracts."""
    return symbol_config.get_active_contracts()


def get_all_symbols() -> list[str]:
    """Get all symbols (base + active contracts)."""
    return symbol_config.get_all_symbols()


def get_dashboard_symbols() -> list[str]:
    """Get symbols for dashboard display."""
    return symbol_config.get_active_symbols()


def get_symbol_display_name(symbol: str) -> str:
    """Get display name for dashboard."""
    return symbol_config.get_display_name(symbol)


def get_futures_contract(symbol: str) -> str:
    """Get futures contract code."""
    return symbol_config.get_contract_code(symbol)


def is_futures(symbol: str) -> bool:
    """Check if symbol is futures."""
    return symbol_config.is_futures_symbol(symbol)


def is_base_symbol(symbol: str) -> bool:
    """Check if symbol is a base symbol."""
    return symbol_config.is_base_symbol(symbol)


def get_exchange(symbol: str) -> str | None:
    """Get exchange for a symbol."""
    return symbol_config.get_exchange(symbol)


def get_point_value(symbol: str) -> float | None:
    """Get point value for a futures symbol."""
    return symbol_config.get_point_value(symbol)


def get_tick_size(symbol: str) -> float | None:
    """Get tick size for a futures symbol."""
    return symbol_config.get_tick_size(symbol)
