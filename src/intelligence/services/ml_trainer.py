"""MLTrainer — nightly oneshot LightGBM training pipeline (Phase 070).

Systemd Type=oneshot service invoked by indicagent-ml-training.timer (nightly 03:00 UTC).

Responsibilities:
  1. Delta gate: skip training if fewer than _DELTA_GATE_MIN new resolved signals since last run
  2. Build training matrix via feature_builder.build_training_matrix()
  3. Segment training: global model + per-hmm_regime models (D-04 regime gate: n >= 100)
  4. Walk-forward 60/20/20 temporal split — no shuffling
  5. LightGBM binary classification with early stopping on validation set
  6. SHAP TreeExplainer feature importance → MLflow artifact (Plan 04 inference contract)
  7. ModelRegistry.register() — shadow status until manual/automated promotion
  8. SIGUSR1 to indicagent-alpha-swarm to trigger model reload in running service

Error handling: any top-level exception is caught, logged, and swallowed — exits 0 so
systemd timer fires again the next night (oneshot success semantics).

Checkpoint file: logs/ml_training_checkpoint.json — persists last_trained_count across runs.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import numpy as np
import shap
import structlog

from src.config.settings import Settings
from src.core.agent.base import BaseDaemon
from src.core.database_manager import create_pool as create_db_pool
from src.core.ml.registry import ModelRegistry
from src.core.service_utils import setup_service_logging
from src.intelligence.ml.feature_builder import (
    build_training_matrix,
    encode_features,
    filter_segment,
    split_walk_forward,
)

logger = structlog.get_logger(__name__)

# D-04 regime gate: regime models and global model both require n >= 100
_MIN_SAMPLE_SIZE = 100

# Delta gate: retrain only after at least 50 new resolved non-shadow signals
_DELTA_GATE_MIN = 50

# Checkpoint file: persists last_trained_count across systemd invocations
_CHECKPOINT_PATH = "logs/ml_training_checkpoint.json"

# Training segments: global + three HMM regime segments (0=ranging, 1=trending up, 2=trending dn)
_SEGMENTS = [{"global": True}, {"hmm_regime": 0}, {"hmm_regime": 1}, {"hmm_regime": 2}]

# MLflow tracking server (loopback only — no external exposure per ASVS V1.4)
_MLFLOW_TRACKING_URI = "http://localhost:5000"

# Systemd unit that receives SIGUSR1 for model reload
_SWARM_UNIT = "indicagent-alpha-swarm"

# Metadata columns excluded from feature vectors
_META_COLS = frozenset(
    {"signal_id", "timestamp", "timeframe", "pnl_r", "win_label", "features_snapshot"}
)


class MLTrainer(BaseDaemon):
    """Nightly LightGBM training agent.

    Runs as a systemd Type=oneshot service, training segment models and registering
    artifacts via ModelRegistry. Sends SIGUSR1 to indicagent-alpha-swarm after
    successful registration to trigger in-process model reload.
    """

    def __init__(self, settings: Settings) -> None:
        setup_service_logging("logs/ml_trainer.log")
        super().__init__("MLTrainingComputeAgent")
        self.settings = settings
        self._pool: asyncpg.Pool | None = None
        self._registry: ModelRegistry | None = None
        self._last_trained_count: int = 0

    async def _setup(self) -> None:
        # Lazy import: mlflow was removed from requirements.txt 2026-08-03 (dormant
        # dependency) -- deferring the import here means this module still imports cleanly
        # for any caller that never reaches this dormant training path.
        import mlflow

        self._pool = await create_db_pool(self.settings.database_url)
        self._registry = ModelRegistry(self._pool)
        self._last_trained_count = self._read_checkpoint()
        mlflow.set_tracking_uri(_MLFLOW_TRACKING_URI)
        logger.info(
            "ml_training.setup_complete",
            last_trained_count=self._last_trained_count,
        )

    async def _teardown(self) -> None:
        if self._pool:
            await self._pool.close()

    async def _run(self) -> None:
        """One-shot training entry point.

        Catches all exceptions at the top level so systemd Type=oneshot exits 0,
        ensuring the timer fires again the following night regardless of failures.
        """
        import time as _time

        from src.observability.metrics import ML_TRAINING_SECONDS

        t0 = _time.monotonic()
        try:
            await self._train_all_segments()
        except Exception:
            logger.exception("ml_training.error_top_level")
            return
        finally:
            ML_TRAINING_SECONDS.record(_time.monotonic() - t0)

    def _read_checkpoint(self) -> int:
        """Read last_trained_count from checkpoint file. Returns 0 if absent or corrupt."""
        path = Path(_CHECKPOINT_PATH)
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return int(data.get("last_trained_count", 0))
            except Exception:
                logger.warning("ml_training.checkpoint_read_failed", path=_CHECKPOINT_PATH)
        return 0

    def _write_checkpoint(self, count: int) -> None:
        """Atomically write last_trained_count to checkpoint file."""
        path = Path(_CHECKPOINT_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"last_trained_count": count, "updated_at": datetime.now(UTC).isoformat()})
        )
        tmp.replace(path)

    async def _should_retrain(self) -> tuple[bool, int]:
        """Delta gate: return (should_retrain, current_count).

        Caller is responsible for updating self._last_trained_count after a successful
        training run — mutation is deferred to avoid checkpoint inconsistency on failure.
        """
        async with self._pool.acquire() as conn:
            current_count = await conn.fetchval(
                "SELECT COUNT(*) FROM signal_ledger WHERE outcome IS NOT NULL AND is_shadow = FALSE"
            )
        current_count = int(current_count or 0)
        delta = current_count - self._last_trained_count
        if delta < _DELTA_GATE_MIN:
            logger.info(
                "ml_training.delta_gate_skip",
                delta=delta,
                current_count=current_count,
                last_trained_count=self._last_trained_count,
                required=_DELTA_GATE_MIN,
            )
            return False, current_count
        return True, current_count

    async def _train_all_segments(self) -> None:
        """Build matrix, train each segment, write checkpoint, optionally signal swarm."""
        should, current_count = await self._should_retrain()
        if not should:
            return

        df = await build_training_matrix(self._pool)
        if len(df) == 0:
            logger.info("ml_training.empty_matrix")
            return

        promoted_any = False
        for segment in _SEGMENTS:
            model_id = await self._train_segment(df, segment)
            if model_id:
                promoted_any = True

        # Update count only after all segments complete successfully
        self._last_trained_count = current_count
        self._write_checkpoint(self._last_trained_count)

        if promoted_any:
            self._signal_swarm_reload()

    async def _train_segment(self, df: Any, segment: dict[str, Any]) -> str | None:
        """Train and register a single segment model. Returns model_id str or None if gated.

        D-04 gate: each segment (including global) requires n >= _MIN_SAMPLE_SIZE before fitting.
        Inference (Plan 04) relies on this gate — a regime model in the registry implies
        n_regime >= 100 was enforced here during training.
        """
        import lightgbm as lgb
        import mlflow
        import mlflow.lightgbm
        from sklearn.metrics import log_loss, roc_auc_score

        seg_df = filter_segment(df, segment)

        if len(seg_df) < _MIN_SAMPLE_SIZE:
            logger.info(
                "ml_training.gate_skip",
                n=len(seg_df),
                segment=str(segment),
                required=_MIN_SAMPLE_SIZE,
            )
            return None

        train_df, val_df, test_df = split_walk_forward(seg_df)

        if len(train_df) < _MIN_SAMPLE_SIZE:
            logger.info(
                "ml_training.gate_skip",
                n=len(train_df),
                segment=str(segment),
                stage="post_split_train_small",
            )
            return None

        if len(val_df) == 0 or len(test_df) == 0:
            logger.info(
                "ml_training.gate_skip",
                n=len(seg_df),
                segment=str(segment),
                stage="insufficient_val_or_test",
            )
            return None

        # Build feature column list: all columns except metadata
        feature_cols = [c for c in seg_df.columns if c not in _META_COLS]

        X_train, y_train, final_cols = encode_features(train_df, feature_cols)
        X_val, y_val, val_cols = encode_features(val_df, feature_cols)  # capture val_cols
        X_test, y_test, test_cols = encode_features(test_df, feature_cols)  # capture test_cols

        # Align val/test to same column set as train (one-hot may produce different dummies)
        # encode_features returns columns from the input df — segments may share the same set,
        # but after one-hot encoding on smaller slices, some dummy cols may be missing.
        # Reindex: add missing cols as 0, drop extra cols, enforce final_cols order.
        def _align_X(X: Any, cols_actual: list[str], cols_target: list[str]) -> Any:
            import numpy as np

            n_rows = X.shape[0]
            aligned = np.zeros((n_rows, len(cols_target)), dtype=np.float64)
            for i, col in enumerate(cols_target):
                if col in cols_actual:
                    j = cols_actual.index(col)
                    aligned[:, i] = X[:, j]
            return aligned

        X_val = _align_X(X_val, list(val_cols), list(final_cols))
        X_test = _align_X(X_test, list(test_cols), list(final_cols))

        with mlflow.start_run() as run:
            mlflow.log_params(
                {
                    "segment": str(segment),
                    "n_train": len(train_df),
                    "n_val": len(val_df),
                    "n_test": len(test_df),
                    "feature_count": len(final_cols),
                }
            )

            params = {"objective": "binary", "metric": "binary_logloss", "verbose": -1}
            dtrain = lgb.Dataset(X_train, label=y_train)
            dval = lgb.Dataset(X_val, reference=dtrain)

            model = lgb.train(
                params,
                dtrain,
                num_boost_round=200,
                valid_sets=[dval],
                callbacks=[lgb.early_stopping(20, verbose=False)],
            )

            preds = model.predict(X_test)
            test_loss = float(log_loss(y_test, preds))
            test_auc = float(roc_auc_score(y_test, preds))

            mlflow.log_metrics({"test_logloss": test_loss, "test_auc": test_auc})

            # SHAP feature importance — JSON summary (not full per-sample matrices)
            # The "feature_cols" list in this artifact is the inference contract:
            # Plan 04's MLEvaluator loads this in _setup_models() and uses
            # feature_cols to align inference feature ordering with training.
            n_shap = min(500, X_val.shape[0])
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X_val[:n_shap])
            # For binary classification, TreeExplainer returns a list[ndarray] (one per class).
            # Take class-1 values; for multi-class or single-output the array is used directly.
            sv = shap_values[1] if isinstance(shap_values, list) else shap_values
            del shap_values  # release class-0 array (binary classifier) before feature loop
            feature_importance = {
                col: float(np.abs(sv[:, i]).mean()) for i, col in enumerate(list(final_cols))
            }
            mlflow.log_dict(
                {"feature_importance": feature_importance, "feature_cols": list(final_cols)},
                "shap_importance.json",
            )

            mlflow.lightgbm.log_model(model, artifact_path="model")

            artifact_uri = f"runs:/{run.info.run_id}/model"
            model_id = await self._registry.register(
                run_id=run.info.run_id,
                segment=segment,
                artifact_path=artifact_uri,
                model_type="lightgbm",
            )

        logger.info(
            "ml_training.segment_registered",
            segment=str(segment),
            model_id=model_id,
            test_auc=test_auc,
            n_train=len(train_df),
        )
        return model_id

    def _signal_swarm_reload(self) -> None:
        """Send SIGUSR1 to indicagent-alpha-swarm to trigger in-process model reload."""
        result = subprocess.run(
            ["systemctl", "kill", "-s", "SIGUSR1", _SWARM_UNIT],
            capture_output=True,
            check=False,
        )
        logger.info(
            "ml_training.swarm_reload_signal_sent",
            returncode=result.returncode,
            stderr=result.stderr.decode(errors="ignore"),
        )
