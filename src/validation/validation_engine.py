"""
Computational correctness validation engine.

Compares production values from intelligence_features to reference
implementations to detect calculation errors.
"""

import asyncpg
import numpy as np
from typing import Dict, List

from src.validation.reference_implementations import (
    rsi_reference,
    macd_reference,
    atr_reference,
    vwap_reference,
    volatility_reference,
)


class ComputationalCorrectnessValidator:
    """Validate every calculation in the pipeline against reference implementations."""

    TOLERANCES = {
        "i1_rsi": 0.01,
        "i1_macd": 0.01,
        "i1_atr": 0.05,
        "i4_volatility": 0.02,
        "i4_vwap": 0.05,
    }

    def __init__(self, db: asyncpg.Connection):
        """Initialize validator with database connection.

        Args:
            db: asyncpg connection or connection pool
        """
        self.db = db

    async def fetch_production_data(
        self, symbol: str, tf: str, hours: int = 24
    ) -> Dict[str, List]:
        """Fetch data from intelligence_features for validation.

        Args:
            symbol: Trading symbol (e.g., "ES")
            tf: Timeframe (e.g., "5m", "15m", "1h")
            hours: Hours of historical data to fetch

        Returns:
            Dict with lists of values for each field
        """
        query = """
            SELECT ts,
                   bar->>'close' as close,
                   bar->>'high' as high,
                   bar->>'low' as low,
                   bar->>'volume' as volume,
                   i1->>'rsi_14' as i1_rsi,
                   i1->>'macd_12_26_9' as i1_macd,
                   i1->>'atr_14' as i1_atr,
                   i4->>'volatility' as i4_volatility,
                   i4->>'vwap' as i4_vwap
            FROM intelligence_features
            WHERE symbol = $1 AND tf = $2
              AND ts > NOW() - INTERVAL '%s hours'
            ORDER BY ts ASC
        """ % hours

        rows = await self.db.fetch(query, symbol, tf)

        return {
            "ts": [r["ts"] for r in rows],
            "close": [float(r["close"]) if r["close"] is not None else np.nan for r in rows],
            "high": [float(r["high"]) if r["high"] is not None else np.nan for r in rows],
            "low": [float(r["low"]) if r["low"] is not None else np.nan for r in rows],
            "volume": [float(r["volume"]) if r["volume"] is not None else np.nan for r in rows],
            "i1_rsi": [float(r["i1_rsi"]) if r["i1_rsi"] is not None else np.nan for r in rows],
            "i1_macd": [float(r["i1_macd"]) if r["i1_macd"] is not None else np.nan for r in rows],
            "i1_atr": [float(r["i1_atr"]) if r["i1_atr"] is not None else np.nan for r in rows],
            "i4_volatility": [float(r["i4_volatility"]) if r["i4_volatility"] is not None else np.nan for r in rows],
            "i4_vwap": [float(r["i4_vwap"]) if r["i4_vwap"] is not None else np.nan for r in rows],
        }

    def validate_field(
        self, field_name: str, ref_values: np.ndarray, prod_values: np.ndarray
    ) -> Dict:
        """Validate a single field against reference implementation.

        Args:
            field_name: Name of the field being validated
            ref_values: Reference implementation values
            prod_values: Production values from intelligence_features

        Returns:
            Dict with validation results (passed, max_diff, mean_diff, samples)
        """
        # Skip NaN values in comparison
        mask = ~np.isnan(ref_values) & ~np.isnan(prod_values)
        valid_samples = np.sum(mask)

        if valid_samples == 0:
            return {
                "field": field_name,
                "passed": False,
                "error": "No valid samples to compare",
                "samples": 0,
                "max_diff": np.nan,
                "mean_diff": np.nan,
                "std_diff": np.nan,
                "tolerance": self.TOLERANCES.get(field_name, 0.01),
            }

        diff = np.abs(ref_values[mask] - prod_values[mask])
        tolerance = self.TOLERANCES.get(field_name, 0.01)

        return {
            "field": field_name,
            "max_diff": float(np.max(diff)),
            "mean_diff": float(np.mean(diff)),
            "std_diff": float(np.std(diff)),
            "tolerance": tolerance,
            "passed": bool(np.max(diff) < tolerance),
            "samples": int(valid_samples),
            "error": None,
        }

    async def run_validation(
        self, symbol: str = "ES", tf: str = "5m", hours: int = 24
    ) -> Dict[str, Dict]:
        """Run full computational correctness validation.

        Args:
            symbol: Trading symbol to validate
            tf: Timeframe to validate
            hours: Hours of data to validate

        Returns:
            Dict mapping field names to validation results
        """
        data = await self.fetch_production_data(symbol, tf, hours)

        results = {}

        # Validate I1: RSI
        ref_rsi = rsi_reference(data["close"])
        prod_rsi = np.array(data["i1_rsi"])
        results["i1_rsi"] = self.validate_field("i1_rsi", ref_rsi, prod_rsi)

        # Validate I1: MACD
        ref_macd = macd_reference(data["close"])
        prod_macd = np.array(data["i1_macd"])
        results["i1_macd"] = self.validate_field("i1_macd", ref_macd["macd"], prod_macd)

        # Validate I1: ATR
        ref_atr = atr_reference(data["high"], data["low"], data["close"])
        prod_atr = np.array(data["i1_atr"])
        results["i1_atr"] = self.validate_field("i1_atr", ref_atr, prod_atr)

        # Validate I4: Volatility
        ref_vol = volatility_reference(data["close"])
        prod_vol = np.array(data["i4_volatility"])
        results["i4_volatility"] = self.validate_field("i4_volatility", ref_vol, prod_vol)

        # Validate I4: VWAP
        ref_vwap = vwap_reference(data["high"], data["low"], data["close"], data["volume"])
        prod_vwap = np.array(data["i4_vwap"])
        results["i4_vwap"] = self.validate_field("i4_vwap", ref_vwap, prod_vwap)

        # Persist results
        await self.persist_results(symbol, tf, results)

        return results

    async def persist_results(
        self, symbol: str, tf: str, results: Dict[str, Dict]
    ) -> None:
        """Write validation results to database.

        Args:
            symbol: Trading symbol
            tf: Timeframe
            results: Validation results from run_validation()
        """
        await self.db.execute(
            """
            INSERT INTO intelligence_metrics (
                symbol, timeframe,
                i1_rsi_correct,
                i1_macd_correct,
                i1_atr_correct,
                i4_volatility_correct,
                i4_vwap_correct
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
            symbol,
            tf,
            results.get("i1_rsi", {}).get("passed"),
            results.get("i1_macd", {}).get("passed"),
            results.get("i1_atr", {}).get("passed"),
            results.get("i4_volatility", {}).get("passed"),
            results.get("i4_vwap", {}).get("passed"),
        )
