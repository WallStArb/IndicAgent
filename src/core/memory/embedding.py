"""
EmbeddingService — Ring 0 text-to-vector adapter for agent memory.

Serializes a SignalContext (or any object with matching attributes) into a
percentile-based text string and calls the Ollama nomic-embed-text model to
produce a 768-dimensional embedding vector.

Design decisions:
    D-05: embedding_text stored alongside the vector for audit and re-embedding.
    D-06: nomic-embed-text via Ollama — same model as Mem0 config, no new infra.
    D-22: percentile fields (rsi_pct, atr_pct, ...) not raw values — comparable
          across instruments and market conditions.
    D-13/D-19: embed() returns None on any failure, never raises.

Ring 0 rule: no Ring 1 imports at module top. SignalContext accessed via
getattr with defaults so this module stays portable.

Phase: 097 (agent-memory)
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

from src.observability.metrics import MEMORY_EMBED_LATENCY_MS

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL = "nomic-embed-text"
_EMBED_DIM = 768
_DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
_HTTP_TIMEOUT = 10.0  # seconds — generous; embedding model is local


class EmbeddingService:
    """Convert a signal context into a 768-dim embedding via Ollama nomic-embed-text.

    Usage::

        svc = EmbeddingService()
        text = svc.serialize(context)          # percentile-based text string
        vector = await svc.embed(text)          # list[float](768) or None
        vector, text = await svc.embed_context(context)  # convenience combo

    The caller (MemoryEpisodeWriter) persists `embedding_text` alongside the
    vector so re-embedding after a model change is always possible (D-05).
    """

    EMBED_DIM: int = _EMBED_DIM

    def __init__(
        self,
        ollama_base_url: str = _DEFAULT_OLLAMA_BASE_URL,
        model: str = _MODEL,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = ollama_base_url.rstrip("/")
        self._model = model
        # Caller may inject a shared client; if not, we create a private one.
        self._client = http_client
        self._owns_client = http_client is None

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def serialize(self, context: Any) -> str:
        """Build a percentile-based embedding text from a SignalContext-like object.

        Uses getattr with defaults so this method works on any duck-typed object
        and never imports Ring 1 types at module level (Ring 0 invariant).

        Token ordering: identity tokens first (symbol, timeframe, entry_type,
        regime), then percentile indicators. Raw values (ATR, RSI, ...) are
        explicitly excluded per D-22.

        Args:
            context: Any object exposing the SignalContext field names via
                attribute access. Missing fields fall back to safe defaults.

        Returns:
            A single space-delimited string suitable as Ollama prompt input.
        """
        # --- Identity tokens (mandatory) ---
        symbol = getattr(context, "symbol", "UNK")
        timeframe = getattr(context, "timeframe", "UNK")
        entry_type = getattr(context, "entry_type", "UNK")

        # Regime label — HMM regime is the primary distributional label (C-01).
        hmm_regime = getattr(context, "hmm_regime", None) or getattr(context, "regime_type", "UNK")

        # Vol regime label — normal / elevated / compressed etc.
        vol_regime = getattr(context, "vol_regime", None) or getattr(
            context, "volatility_regime", "UNK"
        )

        tokens: list[str] = [
            str(symbol),
            str(timeframe),
            str(entry_type),
            f"regime:{hmm_regime}",
            f"vol:{vol_regime}",
        ]

        # --- Percentile indicators (D-22: use _pct variants, not raw values) ---

        # HMM state probability (already 0-1, comparable across instruments)
        hmm_prob = getattr(context, "hmm_prob", None)
        if hmm_prob is not None:
            tokens.append(f"hmm_prob:{hmm_prob:.2f}")

        # Trend score — CTF composite trend (0-1 percentile space)
        trend_score = getattr(context, "trend_score", None) or getattr(context, "ctf_trend", None)
        if trend_score is not None:
            tokens.append(f"trend:{trend_score:.2f}")

        # CTF composite score (cross-timeframe confluence, 0-1)
        ctf_score = getattr(context, "ctf_score", None) or getattr(context, "ctf_composite", None)
        if ctf_score is not None:
            tokens.append(f"ctf:{ctf_score:.2f}")

        # RSI percentile rank across recent bars — NOT the raw RSI value
        rsi_pct = getattr(context, "rsi_pct", None) or getattr(context, "rsi_percentile", None)
        if rsi_pct is not None:
            tokens.append(f"rsi_pct:{rsi_pct:.2f}")

        # ATR percentile — volatility positioning relative to history
        atr_pct = getattr(context, "atr_pct", None) or getattr(context, "atr_percentile", None)
        if atr_pct is not None:
            tokens.append(f"atr_pct:{atr_pct:.2f}")

        # Swing structure — HL (higher-low), LH (lower-high), HH, LL, etc.
        swing_structure = getattr(context, "swing_structure", None) or getattr(
            context, "swing", None
        )
        if swing_structure is not None:
            tokens.append(f"swing:{swing_structure}")

        # Volume relative percentile — above/below average session volume
        vol_pct = getattr(context, "vol_pct", None) or getattr(context, "volume_percentile", None)
        if vol_pct is not None:
            tokens.append(f"vol_pct:{vol_pct:.2f}")

        # Momentum percentile (Rate-of-Change or MACD histogram percentile)
        mom_pct = getattr(context, "momentum_pct", None) or getattr(context, "roc_pct", None)
        if mom_pct is not None:
            tokens.append(f"mom_pct:{mom_pct:.2f}")

        return " ".join(tokens)

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    async def embed(self, text: str) -> list[float] | None:
        """Call Ollama nomic-embed-text and return a 768-dim vector.

        Args:
            text: The serialized embedding text (output of serialize()).

        Returns:
            list[float] of length 768, or None on HTTP error, timeout, or
            dimension mismatch. Never raises (D-13/D-19).
        """
        t0 = time.monotonic()
        client = await self._get_client()
        try:
            response = await client.post(
                f"{self._base_url}/api/embeddings",
                json={"model": self._model, "prompt": text},
                timeout=_HTTP_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            vector: list[float] = data["embedding"]

            if len(vector) != _EMBED_DIM:
                log.warning(
                    "embedding_dimension_mismatch",
                    expected=_EMBED_DIM,
                    received=len(vector),
                    model=self._model,
                )
                return None

            elapsed_ms = (time.monotonic() - t0) * 1000
            MEMORY_EMBED_LATENCY_MS.record(elapsed_ms, {"batch": "false"})
            return vector

        except Exception as error:
            log.warning(
                "embedding_failed",
                model=self._model,
                error=str(error),
                error_type=type(error).__name__,
            )
            return None

    async def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Embed a list of texts sequentially (Ollama API is single-prompt).

        Args:
            texts: List of serialized embedding texts.

        Returns:
            List of vectors (or None entries for failures), same length as input.
            OTel records each call with batch="true" label.
        """
        results: list[list[float] | None] = []
        client = await self._get_client()

        for text in texts:
            t0 = time.monotonic()
            try:
                response = await client.post(
                    f"{self._base_url}/api/embeddings",
                    json={"model": self._model, "prompt": text},
                    timeout=_HTTP_TIMEOUT,
                )
                response.raise_for_status()
                data = response.json()
                vector: list[float] = data["embedding"]

                if len(vector) != _EMBED_DIM:
                    log.warning(
                        "embedding_dimension_mismatch",
                        expected=_EMBED_DIM,
                        received=len(vector),
                        model=self._model,
                    )
                    results.append(None)
                    continue

                elapsed_ms = (time.monotonic() - t0) * 1000
                MEMORY_EMBED_LATENCY_MS.record(elapsed_ms, {"batch": "true"})
                results.append(vector)

            except Exception as error:
                log.warning(
                    "embedding_failed",
                    model=self._model,
                    error=str(error),
                    error_type=type(error).__name__,
                )
                results.append(None)

        return results

    async def embed_context(self, context: Any) -> tuple[list[float] | None, str]:
        """Serialize context, embed it, and return (vector, embedding_text).

        Convenience method for MemoryEpisodeWriter: both the vector and the
        serialized text are needed so the text can be persisted for audit (D-05).

        Args:
            context: Any SignalContext-like object.

        Returns:
            Tuple of (vector or None, embedding_text). embedding_text is always
            returned even when embedding fails — the writer stores it for
            re-embedding after model changes.
        """
        text = self.serialize(context)
        vector = await self.embed(text)
        return vector, text

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the shared client, creating it lazily if not injected."""
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP client if we own it."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
