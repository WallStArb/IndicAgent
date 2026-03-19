"""Unit tests for rebuild_ohlcv.py verification gate logic.

Tests mock psycopg2 connections — no live DB required.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from production.scripts.rebuild_ohlcv import verify_v2_ready


class TestVerifyV2ChunkCountGate:
    """verify_v2_ready() rejects when chunk_count >= 200."""

    def test_verify_v2_chunk_count_gate_fails(self):
        """Returns (False, {...}) when chunk_count is 250 (>= 200 threshold)."""
        conn = MagicMock()
        cursor_ctx = MagicMock()
        cursor_ctx.__enter__ = MagicMock(return_value=cursor_ctx)
        cursor_ctx.__exit__ = MagicMock(return_value=False)
        cursor_ctx.fetchone.return_value = (250,)  # chunk_count = 250
        conn.cursor.return_value = cursor_ctx

        passed, details = verify_v2_ready(conn)

        assert passed is False
        assert details["chunk_count"] == 250
        assert details["reason"] == "chunk_count >= 200"

    def test_verify_v2_chunk_count_exactly_200_fails(self):
        """Returns (False, {...}) when chunk_count is exactly 200 (boundary)."""
        conn = MagicMock()
        cursor_ctx = MagicMock()
        cursor_ctx.__enter__ = MagicMock(return_value=cursor_ctx)
        cursor_ctx.__exit__ = MagicMock(return_value=False)
        cursor_ctx.fetchone.return_value = (200,)  # chunk_count = 200 — boundary
        conn.cursor.return_value = cursor_ctx

        passed, details = verify_v2_ready(conn)

        assert passed is False
        assert details["chunk_count"] == 200
        assert "chunk_count >= 200" in details["reason"]


class TestVerifyV2LatencyGate:
    """verify_v2_ready() rejects when benchmark query >= 500ms."""

    def test_verify_v2_latency_gate_fails(self):
        """Returns (False, {...}) when the benchmark query takes >= 500ms."""
        conn = MagicMock()

        call_count = 0

        def make_cursor():
            nonlocal call_count
            cursor_ctx = MagicMock()
            cursor_ctx.__enter__ = MagicMock(return_value=cursor_ctx)
            cursor_ctx.__exit__ = MagicMock(return_value=False)
            if call_count == 0:
                # First cursor: chunk_count query → 150 (passes gate)
                cursor_ctx.fetchone.return_value = (150,)
            else:
                # Second cursor: benchmark query — latency will be injected via
                # monotonic patch, so fetchall just returns empty
                cursor_ctx.fetchall.return_value = []
            call_count += 1
            return cursor_ctx

        conn.cursor.side_effect = make_cursor

        # Simulate a slow query: monotonic returns values 600ms apart
        monotonic_values = iter([0.0, 0.601])  # 601ms elapsed
        with patch("production.scripts.rebuild_ohlcv.time.monotonic", side_effect=monotonic_values):
            passed, details = verify_v2_ready(conn)

        assert passed is False
        assert details["elapsed_ms"] >= 500
        assert details["reason"] == "latency >= 500ms"

    def test_verify_v2_latency_gate_exactly_500ms_fails(self):
        """Returns (False, {...}) when elapsed_ms is exactly 500ms (boundary)."""
        conn = MagicMock()

        call_count = 0

        def make_cursor():
            nonlocal call_count
            cursor_ctx = MagicMock()
            cursor_ctx.__enter__ = MagicMock(return_value=cursor_ctx)
            cursor_ctx.__exit__ = MagicMock(return_value=False)
            if call_count == 0:
                cursor_ctx.fetchone.return_value = (150,)
            else:
                cursor_ctx.fetchall.return_value = []
            call_count += 1
            return cursor_ctx

        conn.cursor.side_effect = make_cursor

        monotonic_values = iter([0.0, 0.500])  # exactly 500ms
        with patch("production.scripts.rebuild_ohlcv.time.monotonic", side_effect=monotonic_values):
            passed, details = verify_v2_ready(conn)

        assert passed is False
        assert details["reason"] == "latency >= 500ms"


class TestVerifyV2Passes:
    """verify_v2_ready() passes when chunk_count < 200 AND latency < 500ms."""

    def test_verify_v2_passes(self):
        """Returns (True, {...}) with measured values when all gates pass."""
        conn = MagicMock()

        call_count = 0

        def make_cursor():
            nonlocal call_count
            cursor_ctx = MagicMock()
            cursor_ctx.__enter__ = MagicMock(return_value=cursor_ctx)
            cursor_ctx.__exit__ = MagicMock(return_value=False)
            if call_count == 0:
                # chunk_count = 150 → < 200, passes
                cursor_ctx.fetchone.return_value = (150,)
            else:
                cursor_ctx.fetchall.return_value = []
            call_count += 1
            return cursor_ctx

        conn.cursor.side_effect = make_cursor

        # 120ms — well under 500ms threshold
        monotonic_values = iter([0.0, 0.120])
        with patch("production.scripts.rebuild_ohlcv.time.monotonic", side_effect=monotonic_values):
            passed, details = verify_v2_ready(conn)

        assert passed is True
        assert details["chunk_count"] == 150
        assert details["elapsed_ms"] == 120.0

    def test_verify_v2_passes_minimum_values(self):
        """Returns (True, {...}) even with chunk_count=1 and near-zero latency."""
        conn = MagicMock()

        call_count = 0

        def make_cursor():
            nonlocal call_count
            cursor_ctx = MagicMock()
            cursor_ctx.__enter__ = MagicMock(return_value=cursor_ctx)
            cursor_ctx.__exit__ = MagicMock(return_value=False)
            if call_count == 0:
                cursor_ctx.fetchone.return_value = (1,)
            else:
                cursor_ctx.fetchall.return_value = []
            call_count += 1
            return cursor_ctx

        conn.cursor.side_effect = make_cursor

        monotonic_values = iter([0.0, 0.001])  # 1ms
        with patch("production.scripts.rebuild_ohlcv.time.monotonic", side_effect=monotonic_values):
            passed, details = verify_v2_ready(conn)

        assert passed is True
        assert details["chunk_count"] == 1
        assert details["elapsed_ms"] == 1.0
