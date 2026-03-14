"""
Core data models for the Multi-Timeframe Trading Signal Platform.
"""

from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, time
from datetime import datetime as _datetime
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator


class AssetClass(StrEnum):
    """Asset class classification."""

    FUTURES = "futures"
    EQUITY = "equity"
    CRYPTO = "crypto"
    FX = "fx"
    OPTION = "option"


_ALL_ASSET_CLASSES: frozenset["AssetClass"] = frozenset(AssetClass)


@dataclass(frozen=True)
class TradingSession:
    """Defines when a market is open, including trading breaks and trading days."""

    open_time: time
    close_time: time
    timezone: str
    trading_days: frozenset[int] = frozenset({0, 1, 2, 3, 4})
    trading_breaks: tuple[tuple[time, time], ...] = ()

    def is_open(self, utc_ts: _datetime) -> bool:
        """True if market is open at utc_ts (trading_breaks do NOT close the session)."""
        local = utc_ts.astimezone(ZoneInfo(self.timezone))
        if local.weekday() not in self.trading_days:
            return False
        t = local.time().replace(second=0, microsecond=0)
        if self.open_time == self.close_time:
            return True
        elif self.open_time < self.close_time:
            return self.open_time <= t < self.close_time
        else:
            return t >= self.open_time or t < self.close_time

    def in_trading_break(self, utc_ts: _datetime) -> bool:
        """True if currently in a scheduled intra-session break."""
        if not self.trading_breaks:
            return False
        local = utc_ts.astimezone(ZoneInfo(self.timezone))
        t = local.time().replace(second=0, microsecond=0)
        return any(start <= t < end for start, end in self.trading_breaks)

    def elapsed_fraction(self, utc_ts: _datetime) -> float | None:
        """Fraction of trading day elapsed (0.0→1.0, breaks excluded from denominator).

        Returns None for all-day sessions or when closed.
        """
        if self.open_time == self.close_time:
            return None
        if not self.is_open(utc_ts):
            return None
        local = utc_ts.astimezone(ZoneInfo(self.timezone))
        t = local.time().replace(second=0, microsecond=0)
        anchor = _date(2000, 1, 2)  # Monday anchor for safe time arithmetic
        t_dt = _datetime.combine(anchor, t)
        op_dt = _datetime.combine(anchor, self.open_time)
        cl_dt = _datetime.combine(anchor, self.close_time)
        if self.open_time > self.close_time:  # midnight wrap
            next_day = _date(2000, 1, 3)
            cl_dt = _datetime.combine(next_day, self.close_time)
            if t < self.open_time:
                t_dt = _datetime.combine(next_day, t)
        session_total = (cl_dt - op_dt).total_seconds()
        elapsed = (t_dt - op_dt).total_seconds()
        for brk_start, brk_end in self.trading_breaks:
            bs_dt = _datetime.combine(anchor, brk_start)
            be_dt = _datetime.combine(anchor, brk_end)
            bs_dt = max(bs_dt, op_dt)
            be_dt = min(be_dt, cl_dt)
            if be_dt > bs_dt:
                session_total -= (be_dt - bs_dt).total_seconds()
            if be_dt <= t_dt:
                elapsed -= max(0.0, (be_dt - bs_dt).total_seconds())
            elif bs_dt < t_dt:
                elapsed -= (t_dt - bs_dt).total_seconds()
        if session_total <= 0:
            return None
        return max(0.0, min(1.0, elapsed / session_total))


EXCHANGE_SESSIONS: dict[str, "TradingSession"] = {
    "nyse": TradingSession(time(9, 30), time(16, 0), "America/New_York"),
    "lse": TradingSession(time(8, 0), time(16, 30), "Europe/London"),
    "tse": TradingSession(
        time(9, 0),
        time(15, 30),
        "Asia/Tokyo",
        trading_breaks=((time(11, 30), time(12, 30)),),
    ),
    "hkex": TradingSession(
        time(9, 30),
        time(16, 0),
        "Asia/Hong_Kong",
        trading_breaks=((time(12, 0), time(13, 0)),),
    ),
    "sse": TradingSession(
        time(9, 30),
        time(15, 0),
        "Asia/Shanghai",
        trading_breaks=((time(11, 30), time(13, 0)),),
    ),
    "asx": TradingSession(time(10, 0), time(16, 0), "Australia/Sydney"),
}

CONTINUOUS_SESSIONS: dict[str, "TradingSession"] = {
    "futures_24_5": TradingSession(
        time(18, 0),
        time(17, 0),
        "Etc/GMT+6",  # Fixed UTC-6 (CST); CME quotes hours in CST year-round
        trading_days=frozenset({0, 1, 2, 3, 4, 6}),
    ),
    "fx_24_5": TradingSession(
        time(0, 0),
        time(0, 0),
        "UTC",
        trading_days=frozenset({0, 1, 2, 3, 4, 6}),
    ),
    "crypto_24_7": TradingSession(
        time(0, 0),
        time(0, 0),
        "UTC",
        trading_days=frozenset(range(7)),
    ),
}

SESSION_REGISTRY: dict[str, "TradingSession"] = {
    **EXCHANGE_SESSIONS,
    **CONTINUOUS_SESSIONS,
}

MARKET_OVERLAPS: dict[str, tuple[str, str]] = {
    "tokyo_london": ("tse", "lse"),
    "london_ny": ("lse", "nyse"),
    "ny_sydney": ("nyse", "asx"),
}


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
    session_id: str = "futures_24_5"

    @field_validator("session_id")
    @classmethod
    def _validate_session_id(cls, v: str) -> str:
        if v not in SESSION_REGISTRY:
            raise ValueError(f"Unknown session_id {v!r}. Known: {list(SESSION_REGISTRY)}")
        return v

    @property
    def trading_session(self) -> TradingSession:
        return SESSION_REGISTRY[self.session_id]


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
