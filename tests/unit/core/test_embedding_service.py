"""Unit tests for EmbeddingService.

Locks the contracts:
  - D-22: serialize uses percentile tokens (rsi_pct, atr_pct), never raw values
  - D-13/D-19: embed() returns None on litellm error or dimension mismatch, never raises
  - embed_context() returns (None, text) on failure — text always returned for audit (D-05)
  - LiteLLM routing: embed() and embed_batch() call litellm.aembedding, never raw httpx
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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


def _make_litellm_response(vectors: list[list[float]]) -> MagicMock:
    """Build a fake litellm EmbeddingResponse with one or more vectors."""
    response = MagicMock()
    response.data = [{"embedding": v} for v in vectors]
    return response


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
# embed() tests — mocked via litellm.aembedding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_returns_none_on_litellm_error():
    """embed() returns None when litellm.aembedding raises — never propagates."""
    with patch(
        "src.core.memory.embedding.litellm.aembedding",
        new=AsyncMock(side_effect=Exception("connection refused")),
    ):
        svc = EmbeddingService()
        result = await svc.embed("ES 5m at_close regime:trending_up")
    assert result is None


@pytest.mark.asyncio
async def test_embed_returns_none_on_timeout():
    """embed() returns None on timeout — never propagates exception."""
    with patch(
        "src.core.memory.embedding.litellm.aembedding",
        new=AsyncMock(side_effect=TimeoutError("timeout")),
    ):
        svc = EmbeddingService()
        result = await svc.embed("ES 5m at_close regime:trending_up")
    assert result is None


@pytest.mark.asyncio
async def test_embed_returns_none_on_dim_mismatch():
    """embed() returns None when litellm returns a vector of wrong dimension."""
    fake_response = _make_litellm_response([[0.1] * 384])  # wrong — should be 768
    with patch(
        "src.core.memory.embedding.litellm.aembedding",
        new=AsyncMock(return_value=fake_response),
    ):
        svc = EmbeddingService()
        result = await svc.embed("ES 5m at_close regime:trending_up")
    assert (
        result is None
    ), f"Expected None for dim-mismatch but got vector of len {len(result) if result else 'None'}"


@pytest.mark.asyncio
async def test_embed_returns_vector_on_success():
    """embed() returns a 768-dim list[float] on a successful litellm response."""
    fake_response = _make_litellm_response([[0.1] * 768])
    with patch(
        "src.core.memory.embedding.litellm.aembedding",
        new=AsyncMock(return_value=fake_response),
    ):
        svc = EmbeddingService()
        result = await svc.embed("ES 5m at_close regime:trending_up")
    assert result is not None
    assert len(result) == 768


@pytest.mark.asyncio
async def test_embed_passes_model_and_api_base():
    """embed() forwards model and api_base to litellm.aembedding."""
    fake_response = _make_litellm_response([[0.5] * 768])
    mock_aembedding = AsyncMock(return_value=fake_response)
    with patch("src.core.memory.embedding.litellm.aembedding", new=mock_aembedding):
        svc = EmbeddingService(model="ollama/nomic-embed-text", api_base="http://localhost:11434")
        await svc.embed("test text")
    mock_aembedding.assert_called_once_with(
        model="ollama/nomic-embed-text",
        input=["test text"],
        api_base="http://localhost:11434",
    )


# ---------------------------------------------------------------------------
# embed_batch() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_batch_returns_vectors():
    """embed_batch() returns a same-length list of 768-dim vectors."""
    fake_response = _make_litellm_response([[0.1] * 768, [0.2] * 768])
    with patch(
        "src.core.memory.embedding.litellm.aembedding",
        new=AsyncMock(return_value=fake_response),
    ):
        svc = EmbeddingService()
        results = await svc.embed_batch(["text one", "text two"])
    assert len(results) == 2
    assert all(r is not None and len(r) == 768 for r in results)


@pytest.mark.asyncio
async def test_embed_batch_returns_none_per_mismatch():
    """embed_batch() returns None for items with wrong dimension."""
    fake_response = _make_litellm_response([[0.1] * 768, [0.2] * 384])  # second is wrong
    with patch(
        "src.core.memory.embedding.litellm.aembedding",
        new=AsyncMock(return_value=fake_response),
    ):
        svc = EmbeddingService()
        results = await svc.embed_batch(["text one", "text two"])
    assert results[0] is not None and len(results[0]) == 768
    assert results[1] is None


@pytest.mark.asyncio
async def test_embed_batch_returns_all_none_on_error():
    """embed_batch() returns [None]*len(texts) when litellm raises."""
    with patch(
        "src.core.memory.embedding.litellm.aembedding",
        new=AsyncMock(side_effect=Exception("offline")),
    ):
        svc = EmbeddingService()
        results = await svc.embed_batch(["a", "b", "c"])
    assert results == [None, None, None]


@pytest.mark.asyncio
async def test_embed_batch_empty_input():
    """embed_batch([]) returns [] without calling litellm."""
    mock_aembedding = AsyncMock()
    with patch("src.core.memory.embedding.litellm.aembedding", new=mock_aembedding):
        svc = EmbeddingService()
        results = await svc.embed_batch([])
    assert results == []
    mock_aembedding.assert_not_called()


# ---------------------------------------------------------------------------
# embed_context() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_context_returns_text_even_on_failure():
    """embed_context() always returns the serialized text even when embedding fails (D-05)."""
    with patch(
        "src.core.memory.embedding.litellm.aembedding",
        new=AsyncMock(side_effect=Exception("offline")),
    ):
        svc = EmbeddingService()
        ctx = _context_minimal()
        vector, text = await svc.embed_context(ctx)

    assert vector is None
    assert isinstance(text, str)
    assert len(text) > 0
    assert "ES" in text


@pytest.mark.asyncio
async def test_embed_context_returns_vector_and_text_on_success():
    """embed_context() returns (list[float](768), text) when litellm succeeds."""
    fake_response = _make_litellm_response([[0.5] * 768])
    with patch(
        "src.core.memory.embedding.litellm.aembedding",
        new=AsyncMock(return_value=fake_response),
    ):
        svc = EmbeddingService()
        ctx = _context_with_percentiles()
        vector, text = await svc.embed_context(ctx)

    assert vector is not None
    assert len(vector) == 768
    assert isinstance(text, str)
    assert "ES" in text
