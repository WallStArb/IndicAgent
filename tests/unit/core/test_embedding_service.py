"""Unit tests for EmbeddingService.

Locks the contracts:
  - D-22: serialize uses percentile tokens (rsi_pct, atr_pct), never raw values
  - D-13/D-19: embed() returns None on HTTP error or dimension mismatch, never raises
  - embed_context() returns (None, text) on failure — text always returned for audit (D-05)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.core.memory.embedding import EmbeddingService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _context_with_percentiles(**kwargs) -> SimpleNamespace:
    """Build a minimal context with explicit percentile fields."""
    defaults = {
        "symbol": "ES",
        "timeframe": "5m",
        "entry_type": "at_close",
        "hmm_regime": "trending_up",
        "vol_regime": "normal",
        "rsi_pct": 0.72,
        "atr_pct": 0.45,
        "hmm_prob": 0.88,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _context_minimal() -> SimpleNamespace:
    """Build a context with only mandatory tokens — optional fields absent."""
    return SimpleNamespace(
        symbol="ES",
        timeframe="5m",
        entry_type="at_close",
        hmm_regime="trending_up",
        vol_regime="normal",
    )


# ---------------------------------------------------------------------------
# Serialization tests
# ---------------------------------------------------------------------------


def test_serialize_uses_percentiles():
    """serialize() produces percentile tokens and excludes raw RSI integers."""
    svc = EmbeddingService()
    ctx = _context_with_percentiles(rsi_pct=0.72, atr_pct=0.45)
    text = svc.serialize(ctx)

    assert "rsi_pct:" in text, f"Missing rsi_pct token in: {text!r}"
    assert "atr_pct:" in text, f"Missing atr_pct token in: {text!r}"
    assert "ES" in text
    assert "5m" in text
    assert "at_close" in text

    # D-22: raw RSI value must NOT appear as a standalone token
    # (e.g. "rsi:55" would be wrong; only "rsi_pct:0.72" is allowed)
    assert "rsi:" not in text, f"Found raw rsi token in: {text!r}"


def test_serialize_includes_identity_tokens():
    """serialize() always includes symbol, timeframe, entry_type, regime tokens."""
    svc = EmbeddingService()
    ctx = _context_minimal()
    text = svc.serialize(ctx)

    assert "ES" in text
    assert "5m" in text
    assert "at_close" in text
    assert "regime:trending_up" in text
    assert "vol:normal" in text


def test_serialize_handles_missing_optional_fields():
    """serialize() returns a valid non-empty string even when optional fields are absent."""
    svc = EmbeddingService()
    ctx = _context_minimal()  # no rsi_pct, atr_pct, hmm_prob, etc.
    text = svc.serialize(ctx)

    assert isinstance(text, str)
    assert len(text) > 0
    # Mandatory tokens still present
    assert "ES" in text
    assert "at_close" in text
    # Optional tokens absent (no None-based tokens)
    assert "rsi_pct:" not in text
    assert "atr_pct:" not in text


def test_serialize_hmm_prob_token():
    """serialize() includes hmm_prob when provided."""
    svc = EmbeddingService()
    ctx = _context_with_percentiles(hmm_prob=0.91)
    text = svc.serialize(ctx)
    assert "hmm_prob:0.91" in text


def test_serialize_swing_structure_token():
    """serialize() includes swing token when provided."""
    svc = EmbeddingService()
    ctx = _context_with_percentiles(swing="HL")
    text = svc.serialize(ctx)
    assert "swing:HL" in text


# ---------------------------------------------------------------------------
# embed() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_returns_none_on_http_error():
    """embed() returns None when the HTTP call raises — never propagates exception."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.ConnectError("connection refused")

    svc = EmbeddingService(http_client=mock_client)
    result = await svc.embed("ES 5m at_close regime:trending_up")

    assert result is None


@pytest.mark.asyncio
async def test_embed_returns_none_on_timeout():
    """embed() returns None on timeout — never propagates exception."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.ReadTimeout("timeout")

    svc = EmbeddingService(http_client=mock_client)
    result = await svc.embed("ES 5m at_close regime:trending_up")

    assert result is None


@pytest.mark.asyncio
async def test_embed_returns_none_on_dim_mismatch():
    """embed() returns None when Ollama returns a vector of wrong dimension."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    # Return 384-dim vector (wrong — nomic-embed-text should be 768)
    mock_response.json.return_value = {"embedding": [0.1] * 384}

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    svc = EmbeddingService(http_client=mock_client)
    result = await svc.embed("ES 5m at_close regime:trending_up")

    assert (
        result is None
    ), f"Expected None for dim-mismatch but got vector of len {len(result) if result else 'None'}"


@pytest.mark.asyncio
async def test_embed_returns_vector_on_success():
    """embed() returns a 768-dim list[float] on a successful Ollama response."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"embedding": [0.1] * 768}

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    svc = EmbeddingService(http_client=mock_client)
    result = await svc.embed("ES 5m at_close regime:trending_up")

    assert result is not None
    assert len(result) == 768


# ---------------------------------------------------------------------------
# embed_context() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_context_returns_text_even_on_failure():
    """embed_context() always returns the serialized text even when embedding fails (D-05)."""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.ConnectError("offline")

    svc = EmbeddingService(http_client=mock_client)
    ctx = _context_minimal()
    vector, text = await svc.embed_context(ctx)

    assert vector is None
    assert isinstance(text, str)
    assert len(text) > 0
    assert "ES" in text


@pytest.mark.asyncio
async def test_embed_context_returns_vector_and_text_on_success():
    """embed_context() returns (list[float](768), text) when Ollama succeeds."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"embedding": [0.5] * 768}

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    svc = EmbeddingService(http_client=mock_client)
    ctx = _context_with_percentiles()
    vector, text = await svc.embed_context(ctx)

    assert vector is not None
    assert len(vector) == 768
    assert isinstance(text, str)
    assert "ES" in text
