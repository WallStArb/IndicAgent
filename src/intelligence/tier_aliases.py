"""
Intelligence Tier Functional Aliases

Maps internal tier codes (I1-I8) to human-readable functional names.
Internal code continues using TIER_I1, TIER_I2, etc. for brevity and architecture clarity.
External APIs, metrics, documentation, and user-facing content use functional names.

Tier System (I1-I8): Progressive intelligence classification
Functional Names: Self-documenting descriptions for external consumption
"""

from __future__ import annotations

__all__ = [
    "TIER_FUNCTIONAL_NAMES",
    "FUNCTIONAL_TO_TIER",
    "TIER_DESCRIPTIONS",
    "tier_to_functional",
    "functional_to_tier",
    "all_tier_codes",
    "all_functional_names",
    "is_valid_tier",
    "is_valid_functional_name",
    "get_tier_description",
]

# Tier → Functional Name Mapping
TIER_FUNCTIONAL_NAMES: dict[str, str] = {
    "I1": "technical_indicators",
    "I2": "composite_events",
    "I3": "market_structure",
    "I4": "market_context",
    "I5": "pattern_intelligence",
    "I6": "confluence_synthesis",
    "I7": "trading_signals",
    "I8": "ai_narrative",
}

# Reverse mapping for lookups
FUNCTIONAL_TO_TIER: dict[str, str] = {v: k for k, v in TIER_FUNCTIONAL_NAMES.items()}

# Human-readable descriptions for documentation
TIER_DESCRIPTIONS: dict[str, str] = {
    "I1": "Technical Indicators - Mathematical features from OHLCV data",
    "I2": "Composite Events - Discrete market events and crossovers",
    "I3": "Market Structure - Swing patterns, S/R levels, geometry",
    "I4": "Market Context - Regime detection, volatility, session context",
    "I5": "Pattern Intelligence - Classic chart patterns and formations",
    "I6": "Confluence Synthesis - Cross-timeframe and multi-tier synthesis",
    "I7": "Trading Signals - Setup detection and signal generation",
    "I8": "AI Narrative - LLM-powered market analysis and commentary",
}


def tier_to_functional(tier_code: str) -> str:
    """Convert tier code (I1, I7) to functional name (technical_indicators, trading_signals)."""
    return TIER_FUNCTIONAL_NAMES.get(tier_code, tier_code)


def functional_to_tier(functional_name: str) -> str:
    """Convert functional name (trading_signals) to tier code (I7)."""
    return FUNCTIONAL_TO_TIER.get(functional_name, functional_name)


def all_tier_codes() -> frozenset[str]:
    """Return all valid tier codes."""
    return frozenset(TIER_FUNCTIONAL_NAMES.keys())


def all_functional_names() -> frozenset[str]:
    """Return all functional names."""
    return frozenset(TIER_FUNCTIONAL_NAMES.values())


def is_valid_tier(tier_code: str) -> bool:
    """Check if tier code is valid."""
    return tier_code in TIER_FUNCTIONAL_NAMES


def is_valid_functional_name(functional_name: str) -> bool:
    """Check if functional name is valid."""
    return functional_name in FUNCTIONAL_TO_TIER


def get_tier_description(tier_code: str) -> str:
    """Get human-readable tier description."""
    return TIER_DESCRIPTIONS.get(tier_code, f"Tier {tier_code}")
