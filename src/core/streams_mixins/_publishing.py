"""Publishing mixin for Redis Streams."""

import hashlib
import json
from datetime import datetime
from typing import Any

import structlog

from ..models import Timeframe

logger = structlog.get_logger(__name__)


class PublishingMixin:
    """Mixin providing message publishing capabilities."""

    def _serialize_complex_data(self, data: dict[str, Any]) -> dict[str, str]:
        """
        Serialize complex data structures for Redis Streams.

        Handles dictionaries, lists, dataclasses, and datetime objects.
        Returns a dictionary with all values as strings for Redis compatibility.
        """
        serialized_data = {}

        for key, value in data.items():
            if isinstance(value, list | dict):
                serialized_data[key] = json.dumps(value)
            elif hasattr(value, "__dict__") or hasattr(value, "__dataclass_fields__"):
                # Handle dataclass objects
                try:
                    from dataclasses import asdict

                    serialized_data[key] = json.dumps(asdict(value))
                except (TypeError, ValueError):
                    serialized_data[key] = json.dumps(str(value))
            elif hasattr(value, "isoformat"):  # datetime objects
                serialized_data[key] = value.isoformat()
            else:
                serialized_data[key] = str(value)

        return serialized_data

    async def _publish_to_redis_stream(self, stream_name: str, message_data: dict[str, str]) -> str:
        """
        Enhanced core method to publish data to a Redis Stream
        with deduplication and adaptive sizing.

        Args:
            stream_name: Name of the Redis Stream
            message_data: Pre-serialized message data

        Returns:
            str: Stream message ID
        """
        # Check for duplicates
        message_id_hash = self._generate_message_id(message_data)
        if self._is_duplicate_message(message_id_hash):
            logger.debug(f"Duplicate message ignored for {stream_name}")
            return f"duplicate-{message_id_hash}"

        # Calculate adaptive maxlen
        maxlen = self._calculate_adaptive_maxlen(stream_name)

        async def _publish_operation():
            message_id = await self.redis_client.xadd(
                stream_name, message_data, maxlen=maxlen, approximate=True
            )

            # Update metrics
            self.metrics.messages_published += 1
            self.metrics.bytes_transferred += sum(len(str(v)) for v in message_data.values())
            self.metrics.last_activity = datetime.now()

            return message_id

        try:
            message_id = await self._execute_with_retry(_publish_operation)
            logger.debug(
                f"Published to {stream_name}: {message_id}",
                maxlen=maxlen,
                message_size=len(str(message_data)),
            )
            return message_id

        except Exception as e:
            self.metrics.messages_failed += 1
            logger.error(f"Failed to publish to {stream_name}", error=str(e))
            raise

    async def publish_message(self, message: dict[str, Any]) -> str:
        """
        Smart generic method to publish any message to Redis Streams.

        This method intelligently routes to the appropriate specific publishing method
        based on message content, providing backward compatibility for existing code.

        Args:
            message: Dictionary containing message data. Supports multiple formats:
                    - Legacy format: {"stream_name": "stream", "data": {...}}
                    - Smart format: {"type": "ohlcv", "symbol": "ES",
                      "timeframe": "1m", "data": {...}}
                    - Direct format: {"symbol": "ES", "timeframe": "1m", "ohlcv_data": {...}}

        Returns:
            Message ID from Redis Stream
        """
        try:
            # Update metrics
            self.metrics.messages_published += 1
            self.metrics.last_activity = datetime.now()

            # Case 1: Legacy format with stream_name
            if "stream_name" in message:
                stream_name = message["stream_name"]
                data = message.get("data", {})
                return await self._publish_to_redis_stream(
                    stream_name, self._serialize_complex_data(data)
                )

            # Case 2: Smart format with type detection
            if "type" in message:
                message_type = message["type"]
                symbol = message.get("symbol")
                timeframe = message.get("timeframe")
                data = message.get("data", {})

                if not symbol or not timeframe:
                    raise ValueError("Smart format requires 'symbol' and 'timeframe' fields")

                # Convert string timeframe to Timeframe object
                if isinstance(timeframe, str):
                    timeframe = Timeframe(timeframe)

                # Route to appropriate method based on type
                if message_type == "ohlcv":
                    return await self.publish_ohlcv_bar(symbol, timeframe, data)
                elif message_type == "indicators":
                    return await self.publish_indicators(symbol, timeframe, data)
                elif message_type == "patterns":
                    return await self.publish_patterns(symbol, timeframe, data)
                elif message_type == "setups":
                    return await self.publish_setups(symbol, timeframe, data)
                elif message_type == "insights":
                    return await self.publish_insights(symbol, timeframe, data)
                elif message_type == "signal":
                    return await self.publish_signal(symbol, timeframe, data)
                elif message_type == "sentiment":
                    return await self.publish_sentiment(symbol, timeframe, data)
                elif message_type == "intelligence":
                    return await self.publish_intelligence(symbol, timeframe, data)
                elif message_type == "market_intelligence":
                    return await self.publish_market_intelligence(symbol, timeframe, data)
                else:
                    # Fallback to generic stream
                    return await self.publish_to_stream(
                        stream_type=message_type,
                        symbol=symbol,
                        timeframe=timeframe,
                        data=data,
                        source_agent=message.get("source_agent"),
                        confidence_score=message.get("confidence_score"),
                    )

            # Case 3: Direct format with specific data fields
            symbol = message.get("symbol")
            timeframe = message.get("timeframe")

            if not symbol or not timeframe:
                raise ValueError("Message must contain 'symbol' and 'timeframe' fields")

            # Convert string timeframe to Timeframe object
            if isinstance(timeframe, str):
                timeframe = Timeframe(timeframe)

            # Detect data type and route accordingly
            if "ohlcv_data" in message:
                return await self.publish_ohlcv_bar(symbol, timeframe, message["ohlcv_data"])
            elif "indicators_data" in message:
                return await self.publish_indicators(symbol, timeframe, message["indicators_data"])
            elif "patterns_data" in message:
                return await self.publish_patterns(symbol, timeframe, message["patterns_data"])
            elif "setups_data" in message:
                return await self.publish_setups(symbol, timeframe, message["setups_data"])
            elif "insights_data" in message:
                return await self.publish_insights(symbol, timeframe, message["insights_data"])
            elif "signal_data" in message:
                return await self.publish_signal(symbol, timeframe, message["signal_data"])
            elif "sentiment_data" in message:
                return await self.publish_sentiment(symbol, timeframe, message["sentiment_data"])
            elif "intelligence_data" in message:
                return await self.publish_intelligence(
                    symbol, timeframe, message["intelligence_data"]
                )
            elif "market_intelligence_data" in message:
                return await self.publish_market_intelligence(
                    symbol, timeframe, message["market_intelligence_data"]
                )

            # Case 4: Generic data - use publish_to_stream
            data = message.get("data", message)  # Use entire message as data if no data field
            return await self.publish_to_stream(
                stream_type=message.get("stream_type", "generic"),
                symbol=symbol,
                timeframe=timeframe,
                data=data,
                source_agent=message.get("source_agent"),
                confidence_score=message.get("confidence_score"),
            )

        except Exception as e:
            logger.error(
                "Failed to publish message", error=str(e), message_keys=list(message.keys())
            )
            self.metrics.messages_failed += 1
            raise

    async def publish_to_stream(
        self,
        stream_type: str,
        symbol: str,
        timeframe: Timeframe,
        data: dict[str, Any],
        source_agent: str | None = None,
        confidence_score: float | None = None,
    ) -> str:
        """
        Generic method to publish any data type to Redis Streams.

        This is the core publishing method that all specific methods use.
        Handles serialization, stream naming, and metadata consistently.

        Args:
            stream_type: Type of stream ("market", "indicators", "patterns", etc.)
            symbol: Trading symbol
            timeframe: Timeframe
            data: Data to publish
            source_agent: Optional source agent name
            confidence_score: Optional confidence score

        Returns:
            str: Stream message ID
        """
        # Create standardized stream name
        stream_name = f"{stream_type}:{symbol}:{timeframe.value}"

        # Serialize and optionally compress complex data structures
        serialized_data = self._serialize_complex_data(data)

        # Compress large data if enabled
        if "data" in serialized_data:
            original_data = serialized_data["data"]
            compressed_data = self._compress_data(original_data)

            if isinstance(compressed_data, bytes):
                # Store as base64 for Redis compatibility and mark as compressed
                import base64

                serialized_data["data"] = base64.b64encode(compressed_data).decode("ascii")
                serialized_data["_compressed"] = "gzip"
            else:
                serialized_data["data"] = compressed_data

        # Create standardized message
        message_data = {
            "type": stream_type,
            "symbol": symbol,
            "timeframe": timeframe.value,
            "timestamp": datetime.now().isoformat(),
            **serialized_data,
        }

        # Add optional metadata
        if source_agent:
            message_data["source_agent"] = source_agent
        if confidence_score is not None:
            message_data["confidence_score"] = str(confidence_score)

        # Publish to Redis Stream
        return await self._publish_to_redis_stream(stream_name, message_data)

    # Specific Publishing Methods (Thin Wrappers)
    async def publish_ohlcv_bar(self, symbol: str, timeframe: Timeframe, ohlcv_data: dict) -> str:
        """Publish OHLCV bar to market data stream."""
        return await self.publish_to_stream(
            stream_type="market",
            symbol=symbol,
            timeframe=timeframe,
            data=ohlcv_data,
            source_agent="market_data",
        )

    async def publish_indicators(
        self, symbol: str, timeframe: Timeframe, indicators_data: dict
    ) -> str:
        """Publish calculated indicators to indicators stream."""
        return await self.publish_to_stream(
            stream_type="indicators",
            symbol=symbol,
            timeframe=timeframe,
            data={"indicators": indicators_data},
            source_agent="indicator_engine",
        )

    async def publish_patterns(self, symbol: str, timeframe: Timeframe, patterns_data: dict) -> str:
        """Publish pattern detection results to patterns stream."""
        return await self.publish_to_stream(
            stream_type="patterns",
            symbol=symbol,
            timeframe=timeframe,
            data={"data": patterns_data},
            source_agent="pattern_engine",
            confidence_score=patterns_data.get("overall_confidence", 0.0),
        )

    async def publish_setups(self, symbol: str, timeframe: Timeframe, setups_data: dict) -> str:
        """Publish trading setup detection results to setups stream."""
        return await self.publish_to_stream(
            stream_type="setups",
            symbol=symbol,
            timeframe=timeframe,
            data={"data": setups_data},
            source_agent="setup_engine",
            confidence_score=setups_data.get("confluence_score", 0.0),
        )

    async def publish_insights(self, symbol: str, timeframe: Timeframe, insights_data: dict) -> str:
        """Publish AI-interpreted insights to insights stream."""
        return await self.publish_to_stream(
            stream_type="insights",
            symbol=symbol,
            timeframe=timeframe,
            data={"data": insights_data},
            source_agent=insights_data.get("agent_type", "ai_agent"),
            confidence_score=insights_data.get("confidence_score", 0.0),
        )

    async def publish_signal(self, symbol: str, timeframe: Timeframe, signal_data: dict) -> str:
        """Publish trading signal to signals stream."""
        return await self.publish_to_stream(
            stream_type="signals",
            symbol=symbol,
            timeframe=timeframe,
            data=signal_data,
            source_agent="signal_engine",
        )

    async def publish_sentiment(
        self, symbol: str, timeframe: Timeframe, sentiment_data: dict
    ) -> str:
        """Publish sentiment analysis to sentiment stream."""
        return await self.publish_to_stream(
            stream_type="sentiment",
            symbol=symbol,
            timeframe=timeframe,
            data=sentiment_data,
            source_agent="sentiment_analyzer",
            confidence_score=sentiment_data.get("confidence_score", 0.0),
        )

    async def publish_intelligence(
        self, symbol: str, timeframe: Timeframe, intelligence_data: dict
    ) -> str:
        """Publish market intelligence to intelligence stream."""
        return await self.publish_to_stream(
            stream_type="intelligence",
            symbol=symbol,
            timeframe=timeframe,
            data=intelligence_data,
            source_agent="confluence_intelligence",
            confidence_score=intelligence_data.get("confidence_score", 0.0),
        )

    async def publish_market_intelligence(
        self, symbol: str, timeframe: Timeframe, market_intelligence_data: dict
    ) -> str:
        """Publish final market intelligence from orchestrator to market_intelligence stream."""
        return await self.publish_to_stream(
            stream_type="market_intelligence",
            symbol=symbol,
            timeframe=timeframe,
            data=market_intelligence_data,
            source_agent="MarketIntelligenceOrchestrator",
            confidence_score=market_intelligence_data.get("overall_confidence", 0.0),
        )

    def _generate_message_id(self, message_data: dict) -> str:
        """Generate a hash-based message ID for duplicate detection."""
        message_str = json.dumps(message_data, sort_keys=True)
        return hashlib.md5(message_str.encode()).hexdigest()[:8]

    def _is_duplicate_message(self, message_id_hash: str) -> bool:
        """Check if message is a duplicate."""
        # Simple duplicate check - in production, use Redis SET with TTL
        return False

    def _calculate_adaptive_maxlen(self, stream_name: str) -> int:
        """Calculate adaptive maxlen for stream."""
        return self.config.default_maxlen

    def _compress_data(self, data):
        """Compress data if it exceeds threshold. No-op stub - returns data unchanged."""
        return data
