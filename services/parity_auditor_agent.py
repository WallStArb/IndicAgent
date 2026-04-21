#!/usr/bin/env python3
"""ParityAuditorAgent — timer-based shadow vs primary comparison engine.

Compares intelligence_features vs feature_snapshots_shadow every 5 minutes,
stores field-level violations in feature_parity_violations, emits parity_match_rate
Prometheus metrics per (symbol, tf), and self-certifies parity after
CERTIFICATION_THRESHOLD (12) consecutive clean 5-min windows.

Architecture:
    Timer loop (every COMPARISON_INTERVAL_SECS seconds):
      1. Fetch rows from intelligence_features and feature_snapshots_shadow (last 10 min)
      2. Compare row-by-row using _compare_rows() pure function
      3. Store FieldViolations in feature_parity_violations via ParityRepository
      4. Emit parity_match_rate gauge per (symbol, tf)
      5. Derive certification from fetch_clean_cycles query (D-01: no state table)
      6. If all pairs certified: publish SHADOW_PARITY_CERTIFIED to topic_system_events

Renaissance principle: Earn the right through proof — 60 consecutive clean minutes,
not human judgment. Instrument everything.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncpg
import structlog
from aiokafka import AIOKafkaProducer

from src.core.agent.base import BaseAgent
from src.core.schemas.parity import FieldViolation
from src.core.stream_keys import topic_alert_requests, topic_system_events
from src.observability.metrics import (
    PARITY_CYCLES_TOTAL,
    PARITY_MATCH_RATE,
    PARITY_VIOLATIONS_TOTAL,
    SHADOW_AHEAD_ROWS_TOTAL,
)
from src.persistence.repository.parity_repository import ParityRepository

# ── Module-level constants ────────────────────────────────────────────────────

NUMERIC_TOLERANCE: float = 1e-9
CERTIFICATION_THRESHOLD: int = 12  # 12 × 5 min = 60 consecutive clean minutes
COMPARISON_INTERVAL_SECS: int = 300  # 5 minutes
PARITY_ALERT_THRESHOLD: float = 0.95
METRICS_PORT: int = 9133  # port :9133 (9119/9120 already taken by signal_writer/bar_aggregator)

# Join keys — not comparison targets
_SKIP_COLUMNS: tuple[str, ...] = ("ts", "symbol", "tf")

logger = structlog.get_logger(__name__)


# ── Pure comparison function ──────────────────────────────────────────────────


def _compare_rows(
    primary: dict,
    shadow: dict,
    *,
    _prefix: str = "",
) -> list[FieldViolation]:
    """Compare two rows (dicts) field-by-field and return FieldViolation list.

    Pure function — no I/O, fully unit-testable.

    Args:
        primary: Row dict from intelligence_features.
        shadow: Row dict from feature_snapshots_shadow.
        _prefix: Internal — dotted path prefix for recursive JSONB traversal.

    Returns:
        List of FieldViolation objects (empty = clean row).
    """
    violations: list[FieldViolation] = []

    # Extract row identity from primary (for top-level calls, not recursive)
    ts = primary.get("ts")
    symbol = primary.get("symbol", "")
    tf = primary.get("tf", "")

    # Collect all column names to compare (union of both row dicts)
    all_keys = set(primary.keys()) | set(shadow.keys())

    for col in all_keys:
        # Skip join keys at top level
        if not _prefix and col in _SKIP_COLUMNS:
            continue

        p_val = primary.get(col)
        s_val = shadow.get(col)

        # Dotted field path for nested keys
        field_name = f"{_prefix}{col}" if _prefix else col

        # Both None — no violation
        if p_val is None and s_val is None:
            continue

        # One is None, other is not — violation
        if (p_val is None) != (s_val is None):
            violations.append(
                FieldViolation(
                    ts=ts,
                    symbol=symbol,
                    tf=tf,
                    field_name=field_name,
                    primary_value=json.dumps(p_val),
                    shadow_value=json.dumps(s_val),
                    abs_diff=None,
                )
            )
            continue

        # Both are dicts (JSONB) — recurse with dotted prefix
        if isinstance(p_val, dict) and isinstance(s_val, dict):
            # Pass row identity fields through for recursive calls
            p_sub = dict(p_val)
            p_sub.setdefault("ts", ts)
            p_sub.setdefault("symbol", symbol)
            p_sub.setdefault("tf", tf)
            s_sub = dict(s_val)
            s_sub.setdefault("ts", ts)
            s_sub.setdefault("symbol", symbol)
            s_sub.setdefault("tf", tf)
            nested = _compare_rows(
                p_sub,
                s_sub,
                _prefix=f"{field_name}.",
            )
            violations.extend(nested)
            continue

        # Both are numeric (int or float)
        if isinstance(p_val, (int, float)) and isinstance(s_val, (int, float)):
            diff = abs(float(p_val) - float(s_val))
            if diff > NUMERIC_TOLERANCE:
                violations.append(
                    FieldViolation(
                        ts=ts,
                        symbol=symbol,
                        tf=tf,
                        field_name=field_name,
                        primary_value=str(p_val),
                        shadow_value=str(s_val),
                        abs_diff=diff,
                    )
                )
            continue

        # String or other — exact equality
        if p_val != s_val:
            violations.append(
                FieldViolation(
                    ts=ts,
                    symbol=symbol,
                    tf=tf,
                    field_name=field_name,
                    primary_value=str(p_val),
                    shadow_value=str(s_val),
                    abs_diff=None,
                )
            )

    return violations


# ── Agent ─────────────────────────────────────────────────────────────────────


class ParityAuditorAgent(BaseAgent):
    """Timer-based parity auditor: compares intelligence_features vs feature_snapshots_shadow.

    Runs every COMPARISON_INTERVAL_SECS (5 min). Derives certification state from
    feature_parity_violations query — no separate state table (D-01).

    Certification: SHADOW_PARITY_CERTIFIED published to topic_system_events when all
    active (symbol, tf) pairs have CERTIFICATION_THRESHOLD clean consecutive cycles.
    """

    def __init__(self) -> None:
        super().__init__(name="ParityAuditorAgent", metrics_port=METRICS_PORT, max_idle_seconds=600)

        self._pool: asyncpg.Pool | None = None
        self._repo: ParityRepository | None = None
        self._producer: AIOKafkaProducer | None = None


    async def _maybe_alert_parity(self, symbol: str, tf: str, match_rate: float) -> None:
        """Publish HIGH alert to topic_alert_requests when match_rate < PARITY_ALERT_THRESHOLD."""
        if match_rate >= PARITY_ALERT_THRESHOLD:
            return
        if self._producer is None:
            return
        payload = {
            "severity": "HIGH",
            "source": "parity_auditor",
            "symbol": symbol,
            "tf": tf,
            "match_rate": match_rate,
            "threshold": PARITY_ALERT_THRESHOLD,
            "message": (
                f"Parity match rate {match_rate:.3f} below threshold"
                f" {PARITY_ALERT_THRESHOLD} for ({symbol}, {tf})"
            ),
            "fired_at": datetime.now(UTC).isoformat(),
        }
        topic = topic_alert_requests(self.settings.env_name)
        await self._producer.send_and_wait(
            topic,
            key=f"parity_alert:{symbol}:{tf}".encode(),
            value=json.dumps(payload).encode(),
        )
        self.logger.warning(
            "parity_match_rate_alert",
            symbol=symbol,
            tf=tf,
            match_rate=match_rate,
            threshold=PARITY_ALERT_THRESHOLD,
        )

    async def _run(self) -> None:
        """Main timer loop — runs comparison cycle every COMPARISON_INTERVAL_SECS."""
        self._pool = await asyncpg.create_pool(self.settings.database_url)
        self._repo = ParityRepository(self._pool)

        self._producer = AIOKafkaProducer(bootstrap_servers=self.settings.kafka_bootstrap_servers)
        await self._producer.start()

        self.logger.info("parity_auditor_started", interval_secs=COMPARISON_INTERVAL_SECS)

        while not self._stop_event.is_set():
            try:
                await self._compare_cycle()
            except Exception as exc:
                self.logger.error("compare_cycle_error", error=str(exc))

            # Wait for interval or stop event
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=COMPARISON_INTERVAL_SECS)
                break  # stop event was set
            except TimeoutError:
                pass  # normal — continue loop

    async def _compare_cycle(self) -> None:
        """Run one comparison cycle: fetch, compare, store violations, emit metrics."""
        assert self._repo is not None

        now = datetime.now(UTC)
        since = now - timedelta(minutes=10)  # D-02: 2× timer interval
        run_id = uuid.uuid4()

        # Fetch rows from both tables
        primary_rows = await self._repo.fetch_window("intelligence_features", since, now)
        shadow_rows = await self._repo.fetch_window("feature_snapshots_shadow", since, now)

        # Build lookup dicts keyed by (ts, symbol, tf)
        def _row_key(row: dict) -> tuple:
            return (row["ts"], row["symbol"], row["tf"])

        primary_map: dict[tuple, dict] = {_row_key(r): r for r in primary_rows}
        shadow_map: dict[tuple, dict] = {_row_key(r): r for r in shadow_rows}

        all_keys = set(primary_map.keys()) | set(shadow_map.keys())

        all_violations: list[FieldViolation] = []
        # Per (symbol, tf): track matched count and clean matched count
        pair_stats: dict[tuple[str, str], dict] = {}

        for key in all_keys:
            ts, sym, tf = key
            pair = (sym, tf)
            if pair not in pair_stats:
                pair_stats[pair] = {"matched": 0, "clean": 0}

            in_primary = key in primary_map
            in_shadow = key in shadow_map

            if in_primary and not in_shadow:
                # Primary-only: skip — shadow hasn't caught up (D-07)
                continue

            if in_shadow and not in_primary:
                # Shadow-only: increment counter, never FieldViolation (D-03/D-07)
                SHADOW_AHEAD_ROWS_TOTAL.labels(symbol=sym, tf=tf).inc()
                continue

            # Both present — compare
            violations = _compare_rows(primary_map[key], shadow_map[key])
            pair_stats[pair]["matched"] += 1
            if not violations:
                pair_stats[pair]["clean"] += 1
            else:
                all_violations.extend(violations)

        # Store violations if any
        if all_violations and self._repo is not None:
            await self._repo.insert_violations(all_violations, run_id)

        # Emit per-pair metrics
        for (sym, tf), stats in pair_stats.items():
            matched = stats["matched"]
            clean = stats["clean"]
            match_rate = clean / matched if matched > 0 else 1.0
            PARITY_MATCH_RATE.labels(symbol=sym, tf=tf).set(match_rate)
            await self._maybe_alert_parity(sym, tf, match_rate)
            pair_violations = sum(1 for v in all_violations if v.symbol == sym and v.tf == tf)
            if pair_violations:
                PARITY_VIOLATIONS_TOTAL.labels(symbol=sym, tf=tf).inc(pair_violations)

        PARITY_CYCLES_TOTAL.inc()

        self.logger.info(
            "parity_cycle_complete",
            run_id=str(run_id),
            primary_rows=len(primary_rows),
            shadow_rows=len(shadow_rows),
            violations=len(all_violations),
            pairs=len(pair_stats),
        )

        # Certification check: derive from feature_parity_violations (D-01)
        await self._check_certification(pair_stats)

    async def _check_certification(self, pair_stats: dict[tuple[str, str], dict]) -> None:
        """Check if all active (symbol, tf) pairs are certified.

        Certification is derived from fetch_clean_cycles query over
        feature_parity_violations — no in-memory counters (D-01).
        Publishes SHADOW_PARITY_CERTIFIED to topic_system_events when all certified.
        """
        assert self._repo is not None

        if not pair_stats:
            return

        all_certified = True
        for sym, tf in pair_stats:
            clean_cycles = await self._repo.fetch_clean_cycles(sym, tf, CERTIFICATION_THRESHOLD)
            if clean_cycles < CERTIFICATION_THRESHOLD:
                all_certified = False
                self.logger.debug(
                    "pair_not_certified",
                    symbol=sym,
                    tf=tf,
                    clean_cycles=clean_cycles,
                    threshold=CERTIFICATION_THRESHOLD,
                )
                break

        if all_certified and self._producer is not None:
            event = {
                "event_type": "SHADOW_PARITY_CERTIFIED",
                "certified_at": datetime.now(UTC).isoformat(),
                "threshold": CERTIFICATION_THRESHOLD,
                "pairs": list(pair_stats.keys()),
            }
            topic = topic_system_events(self.settings.env_name)
            await self._producer.send_and_wait(
                topic,
                key=b"parity_certification",
                value=json.dumps(event, default=str).encode(),
            )
            self.logger.info(
                "shadow_parity_certified",
                topic=topic,
                pairs=len(pair_stats),
            )

    async def stop(self) -> None:
        """Drain and close connections."""
        self.logger.info("parity_auditor_stopping")
        self._stop_event.set()
        if self._producer:
            await self._producer.stop()
        if self._pool:
            await self._pool.close()
        await super().stop()


# ── Entrypoint ────────────────────────────────────────────────────────────────


async def main() -> None:
    agent = ParityAuditorAgent()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
