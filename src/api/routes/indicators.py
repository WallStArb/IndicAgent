"""
Technical Indicators API Routes

Endpoints for accessing technical analysis indicators.
"""

import pandas as pd
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...indicators import IndicatorCalculations

logger = structlog.get_logger(__name__)
router = APIRouter()


class IndicatorRequest(BaseModel):
    """Request model for indicator calculations."""

    symbol: str
    timeframe: str = "1h"
    indicator: str
    parameters: dict | None = None


class IndicatorResponse(BaseModel):
    """Response model for indicator calculations."""

    symbol: str
    timeframe: str
    indicator: str
    data: dict
    timestamp: str
    backend_used: str


@router.get("/available")
async def get_available_indicators():
    """Get list of available indicators."""
    return {
        "indicators": [
            "rsi",
            "macd",
            "bollinger_bands",
            "moving_averages",
            "stochastic",
            "williams_r",
            "cci",
            "atr",
            "adx",
            "obv",
            "mfi",
            "vwap",
            "pivot_points",
            "fibonacci",
            "support_resistance",
        ],
        "backends": ["talib", "pandas_ta", "finta"],
        "timeframes": ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
    }


@router.post("/calculate")
async def calculate_indicator(request: IndicatorRequest):
    """Calculate a specific technical indicator."""
    try:
        # Initialize indicator calculator
        calc = IndicatorCalculations(backend="auto")

        # Generate sample data for demonstration
        # In production, this would fetch real market data
        sample_data = _generate_sample_data(request.symbol, request.timeframe)

        # Calculate the requested indicator
        if request.indicator == "rsi":
            result = calc.calculate_rsi(
                sample_data,
                period=request.parameters.get("period", 14) if request.parameters else 14,
            )
        elif request.indicator == "macd":
            result = calc.calculate_macd(sample_data)
        elif request.indicator == "bollinger_bands":
            result = calc.calculate_bollinger_bands(sample_data)
        elif request.indicator == "moving_averages":
            result = calc.calculate_moving_averages(sample_data)
        elif request.indicator == "stochastic":
            result = calc.calculate_stochastic(sample_data)
        elif request.indicator == "williams_r":
            result = calc.calculate_williams_r(sample_data)
        elif request.indicator == "cci":
            result = calc.calculate_cci(sample_data)
        elif request.indicator == "atr":
            result = calc.calculate_atr(sample_data)
        elif request.indicator == "support_resistance":
            result = calc.calculate_support_resistance(sample_data)
        else:
            raise HTTPException(
                status_code=400, detail=f"Unsupported indicator: {request.indicator}"
            )

        if result is None:
            raise HTTPException(status_code=422, detail="Failed to calculate indicator")

        return IndicatorResponse(
            symbol=request.symbol,
            timeframe=request.timeframe,
            indicator=request.indicator,
            data=result,
            timestamp=pd.Timestamp.now().isoformat(),
            backend_used=calc.backend,
        )

    except Exception as e:
        logger.error("Indicator calculation failed", error=str(e), request=request.dict())
        raise HTTPException(status_code=500, detail=f"Calculation failed: {str(e)}") from e


@router.get("/backends")
async def get_backend_status():
    """Get status of available backends."""
    calc = IndicatorCalculations()

    return {
        "current_backend": calc.backend,
        "backend_manager": str(calc.backend_manager),
        "detected_backend": calc.backend_enum.value,
    }


def _generate_sample_data(symbol: str, timeframe: str, periods: int = 100) -> pd.DataFrame:
    """Generate sample OHLCV data for demonstration."""
    from datetime import datetime, timedelta

    import numpy as np

    # Generate sample price data
    np.random.seed(42)  # For reproducible results
    base_price = 100.0

    dates = pd.date_range(
        start=datetime.now() - timedelta(days=periods), periods=periods, freq="1H"
    )

    # Random walk for prices
    returns = np.random.normal(0, 0.01, periods)
    prices = base_price * np.exp(np.cumsum(returns))

    # Generate OHLCV data
    opens = prices
    highs = prices * (1 + np.abs(np.random.normal(0, 0.005, periods)))
    lows = prices * (1 - np.abs(np.random.normal(0, 0.005, periods)))
    closes = prices * (1 + np.random.normal(0, 0.002, periods))
    volumes = np.random.randint(10000, 100000, periods)

    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes}, index=dates
    )
