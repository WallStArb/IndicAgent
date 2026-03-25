"""
Renaissance Pipeline Audit Framework

Validates computational correctness, cross-tier consistency, and latency
across the entire intelligence pipeline (I1-I7).

Usage:
    from src.validation import ValidationEngine, CrossTierValidator, AuditReporter
    validator = ValidationEngine(db)
    results = await validator.run_validation("ES", "5m", hours=24)
"""

from src.validation.reference_implementations import (
    rsi_reference,
    macd_reference,
    atr_reference,
    vwap_reference,
    volatility_reference,
)

# Validators and reporter will be added in subsequent tasks
__all__ = [
    # Reference implementations
    "rsi_reference",
    "macd_reference",
    "atr_reference",
    "vwap_reference",
    "volatility_reference",
]
