"""
EmbeddingService — Ring 0 text-to-vector adapter for agent memory.

Serializes a SignalContext (or any object with matching attributes) into a
percentile-based text string and calls litellm.aembedding() to produce a
768-dimensional embedding vector.

Design decisions:
    D-05: embedding_text stored alongside the vector for audit and re-embedding.
    D-06: embeddings route via litellm.aembedding() — consistent with all other
          LLM calls in the system. Default model ollama/nomic-embed-text (768-dim,
          local Ollama, no new infra). Swap via EMBEDDING_MODEL in .env.
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

import litellm
import structlog

from src.observability.metrics import MEMORY_EMBED_LATENCY_MS

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_MODEL = "ollama/nomic-embed-text"
_EMBED_DIM = 768


class EmbeddingService:
    """Convert a signal context into a 768-dim embedding via litellm.aembedding().

    Usage::

        svc = EmbeddingService(model="ollama/nomic-embed-text",
                               api_base="http://localhost:11434")
        text = svc.serialize(context)          # percentile-based text string
        vector = await svc.embed(text)          # list[float](768) or None
        vector, text = await svc.embed_context(context)  # convenience combo

    The caller (MemoryEpisodeWriter) persists `embedding_text` alongside the
    vector so re-embedding after a model change is always possible (D-05).

    The model is routed through litellm.aembedding() for provider consistency.
    For ollama/ prefixed models, api_base must point to the Ollama server.
    """

    EMBED_DIM: int = _EMBED_DIM

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        api_base: str | None = None,
        # Legacy parameter accepted for backward compatibility; ignored.
        ollama_base_url: str | None = None,
    ) -> None:
        self._model = model
        # For ollama/ models, api_base routes the call to the local server.
        # When caller passes ollama_base_url (legacy), treat it as api_base.
        if api_base is not None:
            self._api_base: str | None = api_base
        elif ollama_base_url is not None:
            self._api_base = ollama_base_url
        else:
            self._api_base = None

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
            A single space-delimited string suitable as LiteLLM embedding input.
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
        # Use explicit `is None` guards throughout this block — `or`-chaining treats
        # 0.0 as falsy, which silently drops extreme-percentile readings (WR-01).
        trend_score = getattr(context, "trend_score", None)
        if trend_score is None:
            trend_score = getattr(context, "ctf_trend", None)
        if trend_score is not None:
            tokens.append(f"trend:{trend_score:.2f}")

        # CTF composite score (cross-timeframe confluence, 0-1)
        # Read from top-level ctf_score column (promoted by migration 130).
        # ctf_composite alias removed — top-level columns are the single source of truth.
        ctf_score = getattr(context, "ctf_score", None)
        if ctf_score is not None:
            tokens.append(f"ctf:{ctf_score:.2f}")

        # RSI percentile rank across recent bars — NOT the raw RSI value
        rsi_pct = getattr(context, "rsi_pct", None)
        if rsi_pct is None:
            rsi_pct = getattr(context, "rsi_percentile", None)
        if rsi_pct is not None:
            tokens.append(f"rsi_pct:{rsi_pct:.2f}")

        # ATR percentile — volatility positioning relative to history
        atr_pct = getattr(context, "atr_pct", None)
        if atr_pct is None:
            atr_pct = getattr(context, "atr_percentile", None)
        if atr_pct is not None:
            tokens.append(f"atr_pct:{atr_pct:.2f}")

        # Swing structure — HL (higher-low), LH (lower-high), HH, LL, etc.
        swing_structure = getattr(context, "swing_structure", None)
        if swing_structure is None:
            swing_structure = getattr(context, "swing", None)
        if swing_structure is not None:
            tokens.append(f"swing:{swing_structure}")

        # Volume relative percentile — above/below average session volume
        vol_pct = getattr(context, "vol_pct", None)
        if vol_pct is None:
            vol_pct = getattr(context, "volume_percentile", None)
        if vol_pct is not None:
            tokens.append(f"vol_pct:{vol_pct:.2f}")

        # Momentum percentile (Rate-of-Change or MACD histogram percentile)
        mom_pct = getattr(context, "momentum_pct", None)
        if mom_pct is None:
            mom_pct = getattr(context, "roc_pct", None)
        if mom_pct is not None:
            tokens.append(f"mom_pct:{mom_pct:.2f}")

        return " ".join(tokens)

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    async def embed(self, text: str) -> list[float] | None:
        """Call litellm.aembedding and return a 768-dim vector.

        Args:
            text: The serialized embedding text (output of serialize()).

        Returns:
            list[float] of length 768, or None on error or dimension mismatch.
            Never raises (D-13/D-19).
        """
        t0 = time.monotonic()
        try:
            response = await litellm.aembedding(
                model=self._model,
                input=[text],
                api_base=self._api_base,
            )
            vector: list[float] = response.data[0]["embedding"]

            if len(vector) != _EMBED_DIM:
                log.warning(
                    "embedding_dimension_mismatch",
                    expected=_EMBED_DIM,
                    received=len(vector),
                    model=self._model,
                )
                return None

            return vector

        except Exception as error:
            log.warning(
                "embedding_failed",
                model=self._model,
                error=str(error),
                error_type=type(error).__name__,
            )
            return None

        finally:
            # Record latency on all exit paths: success, dim-mismatch, and exception.
            # Degraded calls (dim-mismatch, Ollama errors) must appear in the histogram
            # so p95 reflects real failure behaviour, not only healthy calls (WR-03).
            elapsed_ms = (time.monotonic() - t0) * 1000
            MEMORY_EMBED_LATENCY_MS.record(elapsed_ms, {"batch": "false"})

    async def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Embed a list of texts in a single litellm.aembedding batch call.

        LiteLLM accepts a list as the `input` parameter; the response contains
        one entry per item in the same order. Each item is validated independently
        — a dim mismatch on one entry does not fail the others.

        Args:
            texts: List of serialized embedding texts.

        Returns:
            List of vectors (or None entries for failures), same length as input.
            OTel records the call with batch="true" label.
        """
        if not texts:
            return []

        t0 = time.monotonic()
        try:
            response = await litellm.aembedding(
                model=self._model,
                input=texts,
                api_base=self._api_base,
            )
            results: list[list[float] | None] = []
            for item in response.data:
                vector: list[float] = item["embedding"]
                if len(vector) != _EMBED_DIM:
                    log.warning(
                        "embedding_dimension_mismatch",
                        expected=_EMBED_DIM,
                        received=len(vector),
                        model=self._model,
                    )
                    results.append(None)
                else:
                    results.append(vector)

            elapsed_ms = (time.monotonic() - t0) * 1000
            MEMORY_EMBED_LATENCY_MS.record(elapsed_ms, {"batch": "true"})
            return results

        except Exception as error:
            log.warning(
                "embedding_failed",
                model=self._model,
                error=str(error),
                error_type=type(error).__name__,
            )
            return [None] * len(texts)

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
    # Lifecycle (no-op — litellm manages its own transport)
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """No-op: litellm manages its own HTTP transport."""
