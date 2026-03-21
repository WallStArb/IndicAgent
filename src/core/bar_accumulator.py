"""BarAccumulator — session-aware 1m→HTF bar aggregator.

BarAccumulator receives 1m BarMessage objects and emits completed higher-timeframe
bars (5m, 15m, 1h) with source="htf_derived". It replaces the stateful aggregation
logic currently embedded in TimeframeBuilder with a typed, testable module.

Design decisions (D-12, D-13, D-14, D-15):
- Input: 1m bars only; non-1m bars return [] without error (D-15)
- Output: list[BarMessage] of completed HTF bars for each boundary crossed
- OHLCV aggregation: open=first.open, high=max, low=min, close=last.close, volume=sum
- source: all emitted bars have source="htf_derived" (D-13)
- session parameter: TradingSession controls session-break behavior (D-14)
- Session break: partial accumulated bar is closed and emitted at session boundary;
  new accumulator state starts fresh for the next session

TradingSession (D-14):
- Holds session break schedule for the instrument's session type
- is_session_break(prev_ts_seconds, curr_ts_seconds) returns True when a session
  boundary falls between the two timestamps
- Prevents bar data from two different trading sessions being merged into one bar

Implementation: Wave 1 (44.1-02). All method bodies raise NotImplementedError.
Tests: tests/unit/core/test_bar_accumulator.py.
"""

from __future__ import annotations

from src.core.schemas.bar_message import BarMessage, SessionType


class TradingSession:
    """Holds session break schedule for session-aware partial bar close (D-14).

    Session break = boundary where partial accumulated bar must be closed and
    emitted rather than carried forward into the next session.

    Args:
        session_type: The session type governing break detection logic.
    """

    def __init__(self, session_type: SessionType = SessionType.RTH) -> None:
        self.session_type = session_type

    def is_session_break(self, prev_ts: int, curr_ts: int) -> bool:
        """Return True if a session boundary falls between prev_ts and curr_ts.

        Args:
            prev_ts: Unix timestamp (seconds) of the previous bar's open time.
            curr_ts: Unix timestamp (seconds) of the current bar's open time.

        Returns:
            True when a session boundary falls strictly between prev_ts and curr_ts.
            False when both timestamps are within the same session window.
        """
        raise NotImplementedError


class BarAccumulator:
    """Session-aware 1m→HTF bar aggregator.

    Receives 1m BarMessage objects and emits completed higher-timeframe bars.
    Each (symbol, tf) combination maintains independent accumulator state.

    Args:
        timeframes: List of target timeframe strings to accumulate into.
                    Defaults to ["5m", "15m", "1h"].
        session:    TradingSession for session-break detection. Defaults to
                    TradingSession(SessionType.RTH).
    """

    def __init__(
        self,
        timeframes: list[str] | None = None,
        session: TradingSession | None = None,
    ) -> None:
        self._timeframes = timeframes or ["5m", "15m", "1h"]
        self._session = session or TradingSession()
        self._accumulators: dict[str, dict] = {}  # key = "{symbol}:{tf}"

    def update(self, bar_1m: BarMessage) -> list[BarMessage]:
        """Process a 1m bar and return any completed HTF bars.

        For each target timeframe, checks whether the 1m bar crosses the
        next TF boundary. If it does, emits the completed bar with
        source="htf_derived" and starts a new accumulator for that TF.

        Also handles session breaks: if prev_ts and curr_ts span a session
        boundary, the partial bar is closed and emitted before accumulating
        the new bar into a fresh state.

        Args:
            bar_1m: A completed 1m BarMessage. Non-1m bars return [] immediately.

        Returns:
            List of completed BarMessage objects (may be empty, or contain one
            completed bar per timeframe that crossed a boundary this bar).
        """
        raise NotImplementedError

    def current_partial(self, symbol: str, tf: str) -> BarMessage | None:
        """Return the in-progress (not yet complete) bar for (symbol, tf).

        Returns None if no 1m bars have been accumulated for (symbol, tf) yet.
        The returned bar has source="htf_derived" and reflects the OHLCV state
        of all 1m bars accumulated so far in the current TF window.
        """
        raise NotImplementedError
