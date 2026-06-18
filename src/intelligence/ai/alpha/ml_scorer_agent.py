"""MLEvaluator — LightGBM inference multiplier agent (Phase 070).

No LLM dependency. Loads promoted models from ModelRegistry at startup and runs
synchronous LightGBM inference to produce a multiplier in [0.0, 2.0].

FEATURE ORDERING
----------------
Training (Plan 03) calls ``encode_features()`` in feature_builder.py, which produces
a post-encoding column list stored as ``feature_cols`` inside the MLflow artifact
``shap_importance.json``.  At inference time, ``_setup_models()`` loads that artifact
and populates ``self._feature_cols``.  ``_extract_features()`` projects the runtime
feature vector onto ``self._feature_cols`` in exactly that order — guaranteeing that
the inference matrix has the same shape and column ordering as the training matrix.

Key sources:
  - ``SHADOW_FEATURE_KEYS`` (from feature_builder.py): the 25 shadow feature keys
    captured at signal-fire time and stored in ``features_snapshot`` on signal_ledger.
  - ``self._feature_cols`` (from MLflow shap_importance.json): post-encoding column
    list produced by training — the authoritative inference column order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import mlflow
import numpy as np
import structlog

from src.core.ai.evaluator import Evaluator
from src.core.ai.output import AgentOutput
from src.core.ai.prompt_utils import clamp
from src.core.ml.registry import ModelRegistry
from src.intelligence.ai.context import SignalContext
from src.intelligence.ml.feature_builder import SHADOW_FEATURE_KEYS

if TYPE_CHECKING:
    from src.core.ai.agent_dependencies import AgentDependencies

logger = structlog.get_logger(__name__)

# Segments to load at startup: one global + three HMM-regime-specific models.
_SEGMENTS: list[tuple[dict[str, Any], str]] = [
    ({"global": True}, "global"),
    ({"hmm_regime": 0}, "regime_0"),
    ({"hmm_regime": 1}, "regime_1"),
    ({"hmm_regime": 2}, "regime_2"),
]

# Bar-context feature keys used at training time (from _TRAINING_SQL in feature_builder.py).
# These supplement SHADOW_FEATURE_KEYS in the feature vector.
_BAR_CONTEXT_KEYS: tuple[str, ...] = (
    "hmm_regime",
    "trend_regime",
    "session_type",
    "atr_pct",
    "volume_z_score",
    "tod_multiplier",
)

# Categorical keys requiring one-hot encoding (mirrors feature_builder._CATEGORICAL_KEYS)
_CATEGORICAL_KEYS: frozenset[str] = frozenset(
    {
        "profile",
        "ctf_momentum_regime",
        "ctf_sr_regime",
        "ctf_hmm_regime_label",
        "ctf_volatility_regime",
        "ctf_orderflow_regime",
        "exhaustion_side",
        "hmm_regime",
        "session_type",
    }
)


class MLEvaluator(Evaluator):
    """LightGBM inference multiplier agent.

    Loads promoted models from ModelRegistry on startup.  Selects the
    regime-specific model when context.smc.hmm_regime is set, falls back
    to the global model, and returns neutral(error="no_promoted_model") when
    no models are promoted — which is the expected first-launch state at Phase 70 ship.

    shadow_only=True: never affects live trade decisions until registry promotion.
    """

    output_schema: ClassVar[dict] = {"multiplier": float, "ml_score": float, "segment": str}

    agent_id = "ml_scorer_v1"
    group = "alpha"
    tiers_needed = frozenset()
    latency_budget_ms = 50.0
    # Phase 109: shadow_only defaults to True (FAIL-CLOSED).
    # Promotion to live requires an explicit ai.agent.<agent_id>.shadow_mode=false
    # config entry. If config load fails or the key is missing, agent STAYS shadow.
    shadow_only: bool = True

    def _apply_shadow_mode_config(self) -> None:
        """Read ai.agent.<self.agent_id>.shadow_mode from config; fail-closed on miss.

        Called by:
          - AlphaSwarm._setup() after agents are constructed (initial load)
          - AlphaSwarm._on_config_message_received() on Kafka update
            (hot-reload -- see alpha_swarm_agent.py Part B)
        """
        override = self.get_config(f"ai.agent.{self.agent_id}.shadow_mode", None)
        if override is None:
            return  # keep class default True (fail-closed)
        # override may arrive as bool (from RUNTIME_DEFAULTS) or str (from Kafka); normalize:
        if isinstance(override, bool):
            self.shadow_only = override
        elif isinstance(override, str):
            self.shadow_only = override.strip().lower() in ("true", "1", "yes")
        # Unknown type - keep fail-closed (do nothing)

    def __init__(self, *, dependencies: AgentDependencies, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if dependencies.pool is None:
            raise ValueError("MLEvaluator requires dependencies.pool")
        self._pool = dependencies.pool
        self._registry = ModelRegistry(dependencies.pool)
        # segment_key -> loaded MLflow pyfunc model
        self._models: dict[str, Any] = {}
        # Post-encoding column list from MLflow shap_importance.json.
        # This is the training/inference column-alignment contract written by Plan 03's
        # MLTrainer (mlflow.log_dict({"feature_cols": ...}, "shap_importance.json")).
        # Populated in _setup_models(); empty until first successful load.
        self._feature_cols: list[str] = []

    async def _setup_models(self) -> None:
        """Load promoted models and shap_importance.json feature column list from MLflow.

        Iterates all four segments.  Skips segments with no promoted model.
        Loads self._feature_cols from the shap_importance.json artifact on the
        first successfully loaded model (all segments share the same feature_cols
        list because Plan 03 writes it once per training run).
        """
        new_models: dict[str, Any] = {}
        new_feature_cols: list[str] = list(
            self._feature_cols
        )  # preserve existing on partial reload

        for segment_dict, key in _SEGMENTS:
            model = await self._registry.load_latest(segment_dict)
            if model is None:
                continue
            new_models[key] = model

            # Load feature_cols from shap_importance.json artifact (once per reload cycle)
            if not new_feature_cols:
                run_id = await self._registry.get_latest_run_id(segment_dict)
                if run_id is not None:
                    try:
                        artifact = mlflow.artifacts.load_dict(
                            f"runs:/{run_id}/shap_importance.json"
                        )
                        new_feature_cols = list(artifact["feature_cols"])
                        logger.info(
                            "ml_scorer.feature_cols_loaded",
                            n_cols=len(new_feature_cols),
                            run_id=run_id,
                        )
                    except Exception as error:
                        logger.warning(
                            "ml_scorer.feature_cols_load_failed",
                            run_id=run_id,
                            error=str(error),
                        )
                        # Fallback: shadow keys + bar context in canonical order
                        new_feature_cols = list(SHADOW_FEATURE_KEYS) + list(_BAR_CONTEXT_KEYS)

        # Atomic assignment — CPython dict assignment is atomic; safe for shadow-only hot-swap
        self._models = new_models
        if new_feature_cols:
            self._feature_cols = new_feature_cols

        logger.info(
            "ml_scorer.models_loaded",
            loaded_count=len(self._models),
            keys=list(self._models.keys()),
            feature_cols_len=len(self._feature_cols),
        )

    def _select_model(self, context: SignalContext) -> tuple[Any, str]:
        """Select regime-specific or global model based on context.smc.hmm_regime.

        D-04: regime model presence in self._models implies n_regime >= 100 was met at
        training time (enforced by Plan 03's _train_segment gate).  No runtime sample
        check needed here.
        """
        hmm_regime: int | None = None
        if context.smc is not None:
            hmm_regime = context.smc.hmm_regime  # type: ignore[attr-defined]

        if hmm_regime in (0, 1, 2):
            regime_key = f"regime_{hmm_regime}"
            if regime_key in self._models:
                return self._models[regime_key], regime_key

        if "global" in self._models:
            return self._models["global"], "global"

        return None, "none"

    def _extract_features(self, context: SignalContext) -> np.ndarray | None:
        """Build a flat (1, N) feature vector from SignalContext, projected onto self._feature_cols.

        Feature sources:
          1. SHADOW_FEATURE_KEYS from context.i7 (QuantSignalContext has no _shadow dict
             directly — the features_snapshot is not on SignalContext at inference time).
             At inference time we read shadow features from context.i6 + context.smc where
             available, defaulting missing numeric keys to 0.0 and categoricals to "unknown".
          2. Bar context keys from context.i1, context.i4, context.smc.

        The resulting dict is one-hot encoded for categorical keys, then projected to
        self._feature_cols order (loaded from shap_importance.json at startup).
        Any column in self._feature_cols absent from the assembled dict defaults to 0.0.
        """
        if not self._feature_cols:
            return None

        raw: dict[str, Any] = {}

        # --- Shadow feature keys (25 keys from confidence.py capture_signal_features) ---
        # At inference time these come from the live context tier dicts.
        i6 = context.i6
        smc = context.smc
        i4 = context.i4
        i1 = context.i1
        i7 = context.i7

        # Map SHADOW_FEATURE_KEYS to available context fields
        i6_dict: dict[str, Any] = {}
        if i6 is not None:
            try:
                i6_dict = {k: v for k, v in i6.model_dump(exclude_none=True).items()}
            except Exception:
                i6_dict = {}

        smc_dict: dict[str, Any] = {}
        if smc is not None:
            try:
                smc_dict = {k: v for k, v in smc.model_dump(exclude_none=True).items()}
            except Exception:
                smc_dict = {}

        i4_dict: dict[str, Any] = {}
        if i4 is not None:
            try:
                i4_dict = {k: v for k, v in i4.model_dump(exclude_none=True).items()}
            except Exception:
                i4_dict = {}

        i1_dict: dict[str, Any] = {}
        if i1 is not None:
            try:
                i1_dict = {k: v for k, v in i1.model_dump(exclude_none=True).items()}
            except Exception:
                i1_dict = {}

        # Build shadow feature values — search i6, smc, i4 in priority order
        combined_context = {**i4_dict, **smc_dict, **i6_dict}
        if i7 is not None:
            try:
                raw["profile"] = str(i7.winner_plugin or "unknown")
                raw["existing_confidence"] = float(i7.winner_confidence or 0.0)
            except Exception:
                raw["profile"] = "unknown"
                raw["existing_confidence"] = 0.0

        for key in SHADOW_FEATURE_KEYS:
            if key in raw:
                continue
            val = combined_context.get(key)
            if key in _CATEGORICAL_KEYS:
                raw[key] = str(val) if val is not None else "unknown"
            else:
                raw[key] = float(val) if val is not None else 0.0

        # --- Bar context keys ---
        raw["hmm_regime"] = int(smc_dict.get("hmm_regime", 0) or 0)
        raw["trend_regime"] = float(i4_dict.get("trend_regime", 0.0) or 0.0)
        raw["session_type"] = str(i4_dict.get("session_type", "unknown") or "unknown")
        raw["atr_pct"] = float(i1_dict.get("atr_pct", 0.0) or 0.0)
        raw["volume_z_score"] = float(i1_dict.get("volume_z_score", 0.0) or 0.0)
        raw["tod_multiplier"] = 1.0  # not available at inference time; safe default

        # --- One-hot encode categoricals ---
        encoded: dict[str, float] = {}
        for key, val in raw.items():
            if key in _CATEGORICAL_KEYS:
                encoded[f"{key}_{val}"] = 1.0
            else:
                try:
                    encoded[key] = float(val)
                except (TypeError, ValueError):
                    encoded[key] = 0.0

        # --- Project onto self._feature_cols (training column order) ---
        feature_vector = np.array(
            [encoded.get(col, 0.0) for col in self._feature_cols], dtype=np.float32
        )
        return feature_vector.reshape(1, -1)

    async def _compute(self, context: SignalContext) -> AgentOutput:
        """Run LightGBM inference and return a multiplier in [0.0, 2.0].

        Returns neutral(error="no_promoted_model") when no models are loaded —
        the expected first-launch state at Phase 70 ship.
        """
        if not self._models:
            # Expected first-launch state — no models promoted yet.
            return self._neutral(error="no_promoted_model", latency_ms=0.0)

        features = self._extract_features(context)
        if features is None:
            return self._neutral(error="feature_extraction_failed", latency_ms=0.0)

        model, segment_key = self._select_model(context)
        if model is None:
            return self._neutral(error="no_promoted_model", latency_ms=0.0)

        try:
            ml_score = float(model.predict(features)[0])
        except Exception as error:
            logger.warning(
                "ml_scorer.predict_failed",
                error=str(error),
                segment=segment_key,
            )
            return self._neutral(error="predict_exception", latency_ms=0.0)

        multiplier = clamp(ml_score * 2.0, 0.0, 2.0)

        return self._build_multiplier_output(
            context=context,
            multiplier=multiplier,
            confidence=ml_score,
            payload={"ml_score": ml_score, "segment": segment_key},
            prompt_version="v1",
        )
