"""AlertingAgent -- centralized alert dispatcher (SRP: dispatch only).

Consume topic_alert_requests, dispatch CRITICAL -> Telegram, HIGH/MEDIUM -> Discord.
Separates alert dispatch from service auditing (Single Responsibility Principle).

Phase 67 Plan 01 — OBS-WEBHOOK-DISPATCHER consumer side.
"""

from __future__ import annotations

import time

import aiohttp

from src.config.settings import get_settings
from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaConsumerClient
from src.core.stream_keys import topic_alert_requests
from src.observability.metrics import ALERTING_DISPATCH_TOTAL, ALERTING_LATENCY_SECONDS


class AlertingAgent(BaseAgent):
    """Consume topic_alert_requests, dispatch CRITICAL -> Telegram, HIGH/MEDIUM -> Discord.

    Any agent can publish alert requests via BaseAgent._send_alert(). This agent
    consumes and routes to the correct channel based on severity:
    - CRITICAL -> Telegram (urgent, human-critical)
    - HIGH/MEDIUM -> Discord (operational alerts)

    Metrics are emitted for every dispatch attempt (success/failure) and latency.
    Gracefully handles missing credentials (no-op when token/URL is empty).
    HTTP errors are logged, not raised (service stays alive).
    """

    def __init__(self) -> None:
        settings = get_settings()
        super().__init__(name="alerting_agent", metrics_port=9132, settings=settings)
        self._http_session: aiohttp.ClientSession | None = None
        self._consumer: KafkaConsumerClient | None = None

    @property
    def topics_consumed(self) -> list[str]:
        """Kafka topics this agent reads from."""
        return [topic_alert_requests(self.env_name)]

    async def _setup(self) -> None:
        """Initialize Kafka consumer and HTTP session."""
        self._consumer = KafkaConsumerClient(
            topic_alert_requests(self.env_name),
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id="alerting_consumer",
        )
        await self._consumer.start()
        self._http_session = aiohttp.ClientSession()

    async def _teardown(self) -> None:
        """Close HTTP session and Kafka consumer."""
        if self._consumer:
            await self._consumer.stop()
        if self._http_session:
            await self._http_session.close()

    async def _run(self) -> None:
        """Main loop: consume alert requests and dispatch by severity."""
        assert self._consumer is not None
        async for _topic, _key, payload in self._consumer.messages():
            if not self.running:
                break
            severity = payload.get("severity", "MEDIUM")
            message = payload.get("message", "")
            source = payload.get("source", "unknown")
            if severity == "CRITICAL":
                await self._dispatch_telegram(message, source)
            elif severity in ("HIGH", "MEDIUM"):
                await self._dispatch_discord(message, source, severity)
            else:
                self.logger.debug("alerting.unknown_severity", severity=severity)

    async def _dispatch_telegram(self, message: str, source: str) -> bool:
        """Dispatch alert to Telegram bot API.

        Returns True on success (HTTP 200), False on failure or missing credentials.
        Emits ALERTING_DISPATCH_TOTAL and ALERTING_LATENCY_SECONDS metrics.
        """
        token = self.settings.telegram_bot_token
        chat_id = self.settings.telegram_chat_id
        if not token or not chat_id:
            return False

        start = time.monotonic()
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            text = f"*[CRITICAL]* {source}\n{message}"
            assert self._http_session is not None
            async with self._http_session.post(
                url,
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                elapsed = time.monotonic() - start
                if resp.status == 200:
                    ALERTING_DISPATCH_TOTAL.labels(
                        channel="telegram", severity="CRITICAL", status="success"
                    ).inc()
                    ALERTING_LATENCY_SECONDS.labels(channel="telegram").observe(elapsed)
                    return True
                else:
                    ALERTING_DISPATCH_TOTAL.labels(
                        channel="telegram", severity="CRITICAL", status="failure"
                    ).inc()
                    self.logger.warning("alerting.telegram_failed", status=resp.status)
                    return False
        except Exception as exc:
            ALERTING_DISPATCH_TOTAL.labels(
                channel="telegram", severity="CRITICAL", status="failure"
            ).inc()
            self.logger.error("alerting.telegram_error", error=str(exc))
            return False

    async def _dispatch_discord(self, message: str, source: str, severity: str) -> bool:
        """Dispatch alert to Discord webhook URL.

        Returns True on success (HTTP 200/204), False on failure or missing URL.
        Emits ALERTING_DISPATCH_TOTAL and ALERTING_LATENCY_SECONDS metrics.
        """
        url = self.settings.discord_webhook_url
        if not url:
            return False

        start = time.monotonic()
        try:
            content = f"**[{severity}]** {source}\n{message}"
            assert self._http_session is not None
            async with self._http_session.post(
                url,
                json={"content": content},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                elapsed = time.monotonic() - start
                if resp.status in (200, 204):
                    ALERTING_DISPATCH_TOTAL.labels(
                        channel="discord", severity=severity, status="success"
                    ).inc()
                    ALERTING_LATENCY_SECONDS.labels(channel="discord").observe(elapsed)
                    return True
                else:
                    ALERTING_DISPATCH_TOTAL.labels(
                        channel="discord", severity=severity, status="failure"
                    ).inc()
                    self.logger.warning("alerting.discord_failed", status=resp.status)
                    return False
        except Exception as exc:
            ALERTING_DISPATCH_TOTAL.labels(
                channel="discord", severity=severity, status="failure"
            ).inc()
            self.logger.error("alerting.discord_error", error=str(exc))
            return False


if __name__ == "__main__":
    import asyncio

    asyncio.run(AlertingAgent().start())
