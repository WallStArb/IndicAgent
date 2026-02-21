"""
Core data models for the Multi-Timeframe Trading Signal Platform.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AssetClass(StrEnum):
    """Asset class classification."""

    FUTURES = "futures"
    EQUITY = "equity"
    CRYPTO = "crypto"
    FX = "fx"
    OPTION = "option"


class Instrument(BaseModel):
    """Generic tradable instrument — provider-agnostic."""

    symbol: str
    name: str = ""
    asset_class: AssetClass = AssetClass.FUTURES
    exchange: str = ""
    sector: str = ""
    tick_size: float = 0
    # Futures-specific — empty/zero for equities and crypto
    base: str = ""
    expiry: str = ""
    point_value: float = 0
    # Escape hatch for provider-specific metadata
    provider_meta: dict = {}


class DataSource(StrEnum):
    """Available data sources."""

    IBKR = "ibkr"
    ALPACA = "alpaca"
    SCHWAB = "schwab"
    TALIB = "talib"
    FINTA = "finta"
    SYSTEM = "system"
    CALCULATED = "calculated"


class Timeframe(StrEnum):
    """Available timeframes."""

    ONE_MINUTE = "1m"
    FIVE_MINUTE = "5m"
    FIFTEEN_MINUTE = "15m"
    THIRTY_MINUTE = "30m"
    ONE_HOUR = "1h"
    FOUR_HOUR = "4h"
    ONE_DAY = "1d"
    ONE_WEEK = "1w"


class SignalGrade(StrEnum):
    """Signal grading system."""

    A_GRADE = "A"  # Premium signals (≥120 points)
    B_GRADE = "B"  # Standard signals (80-119 points)
    C_GRADE = "C"  # Marginal signals (60-79 points)


class OHLCVData(BaseModel):
    """OHLCV market data structure."""

    timestamp: datetime
    symbol: str
    timeframe: Timeframe
    source: DataSource
    open: float
    high: float
    low: float
    close: float
    volume: int


class TechnicalIndicator(BaseModel):
    """Technical indicator data structure."""

    timestamp: datetime
    symbol: str
    timeframe: Timeframe
    source: DataSource = DataSource.TALIB
    indicator_name: str
    values: dict[
        str, float | str | None
    ]  # e.g., {"macd": 0.1, "signal": 0.05, "histogram": 0.05, "trend": "bullish"}


class MACDData(BaseModel):
    """MACD indicator specific structure."""

    timestamp: datetime
    symbol: str
    timeframe: Timeframe
    macd_line: float
    signal_line: float
    histogram: float

    @property
    def divergence_strength(self) -> float:
        """Calculate divergence strength metric."""
        return abs(self.macd_line - self.signal_line)


class SignalScore(BaseModel):
    """Signal scoring components."""

    divergence_strength: float = Field(ge=0, le=200)  # 30% weight
    level_proximity: float = Field(ge=0, le=200)  # 25% weight
    volume_confirmation: float = Field(ge=0, le=200)  # 20% weight
    timing_quality: float = Field(ge=0, le=200)  # 15% weight
    pattern_quality: float = Field(ge=0, le=200)  # 10% weight

    @property
    def composite_score(self) -> float:
        """Calculate weighted composite score."""
        return (
            self.divergence_strength * 0.30
            + self.level_proximity * 0.25
            + self.volume_confirmation * 0.20
            + self.timing_quality * 0.15
            + self.pattern_quality * 0.10
        )

    @property
    def grade(self) -> SignalGrade:
        """Determine signal grade based on composite score."""
        score = self.composite_score
        if score >= 120:
            return SignalGrade.A_GRADE
        elif score >= 80:
            return SignalGrade.B_GRADE
        else:
            return SignalGrade.C_GRADE


class TradingSignal(BaseModel):
    """Trading signal structure."""

    id: str | None = None
    timestamp: datetime
    symbol: str
    timeframe: Timeframe
    signal_type: str  # "bullish_divergence" or "bearish_divergence"
    entry_price: float
    stop_loss: float | None = None
    target_price: float | None = None
    score: SignalScore
    grade: SignalGrade
    confidence: float = Field(ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Performance tracking
    is_active: bool = True
    exit_price: float | None = None
    exit_timestamp: datetime | None = None
    pnl: float | None = None


class MarketRegime(StrEnum):
    """Market regime classification."""

    BULL = "bull"
    BEAR = "bear"
    RANGE = "range"
    VOLATILE = "volatile"


class SystemHealth(BaseModel):
    """System health monitoring."""

    timestamp: datetime
    component: str
    status: str  # "healthy", "warning", "error"
    message: str
    metrics: dict[str, Any] = Field(default_factory=dict)


class UniversalDataKey(BaseModel):
    """Universal data format key: source.symbol.timeframe.datatype."""

    source: DataSource
    symbol: str
    timeframe: Timeframe
    datatype: str

    def __str__(self) -> str:
        return f"{self.source.value}.{self.symbol}.{self.timeframe.value}.{self.datatype}"

    @classmethod
    def from_string(cls, key: str) -> "UniversalDataKey":
        """Parse universal data key from string."""
        parts = key.split(".")
        if len(parts) != 4:
            raise ValueError(f"Invalid universal data key format: {key}")

        source, symbol, timeframe, datatype = parts
        return cls(
            source=DataSource(source),
            symbol=symbol,
            timeframe=Timeframe(timeframe),
            datatype=datatype,
        )

    @classmethod
    def create_ohlcv_key(
        cls, source: DataSource, symbol: str, timeframe: Timeframe, timestamp: datetime
    ) -> str:
        """Create universal data key for OHLCV data."""
        return f"{source.value}.{symbol}.{timeframe.value}.ohlcv"

    @classmethod
    def create_indicator_key(
        cls,
        source: DataSource,
        symbol: str,
        timeframe: Timeframe,
        indicator_name: str,
        timestamp: datetime,
    ) -> str:
        """Create universal data key for technical indicator."""
        return f"{source.value}.{symbol}.{timeframe.value}.{indicator_name}"


class DataQuality(BaseModel):
    """Data quality metrics."""

    timestamp: datetime
    source: DataSource
    symbol: str
    timeframe: Timeframe
    completeness: float = Field(ge=0, le=1)  # % of expected data points
    accuracy: float = Field(ge=0, le=1)  # Data validation score
    timeliness: float = Field(ge=0, le=1)  # How fresh is the data
    overall_score: float = Field(ge=0, le=1)
