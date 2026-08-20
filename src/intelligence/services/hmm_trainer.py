"""HMMTrainer — offline Baum-Welch training pipeline (Phase 082, Plan 03).

Systemd Type=oneshot service invoked by indicagent-hmm-training.timer (monthly).

Responsibilities:
  1. For each configured timeframe (1m, 5m, 15m, 1h, 4h, 1d):
     a. Query intelligence_features for the lookback window
     b. Build observation matrix replicating HMMRegimePlugin._build_observation() feature set
     c. Fit hmmlearn.GaussianHMM (Baum-Welch, n_components=3, covariance_type="diag")
     d. Atomically write config/hmm_parameters_{tf}.json (transition_matrix, emission_means,
        emission_variances keys matching HMMRegimePlugin._load_parameters() contract)
  2. After all TF writes complete, emit SIGUSR1 to indicagent-intelligence-pipeline.service
     so live HMMRegimePlugin instances hot-reload parameters without service restart.

Separation of concerns: this agent TRAINS only. Inference is handled by the four
HMMRegimePlugin instances in intelligence_pipeline_agent (TIER_SMC). No runtime state
is shared — the JSON files are the handoff point.

Minimum row threshold: 500 rows per TF. TFs below threshold are skipped (logged) but
do not fail the overall run. This prevents training on trivially small datasets.

Error handling: per-TF failures are caught and logged; the agent proceeds to remaining TFs.
Top-level exception is caught in start() so systemd oneshot exit code remains 0.

Lookback days defaults per TF (used for query window):
  1m  → 30 days  (~43,200 bars on liquid futures)
  5m  → 60 days  (~17,280 bars)
  15m → 90 days  (~8,640 bars)
  1h  → 180 days (~4,320 bars)
  4h  → 365 days (~2,190 bars)
  1d  → 730 days (~730 bars)
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import structlog

from src.config.settings import Settings
from src.core import vocabulary_access
from src.core.service_utils import setup_service_logging

logger = structlog.get_logger(__name__)

# Lookback days per TF — controls query window
_LOOKBACK_DAYS_BY_TF: dict[str, int] = {
    "1m": 30,
    "5m": 60,
    "15m": 90,
    "1h": 180,
    "4h": 365,
    "1d": 730,
}

# Minimum number of valid (non-NaN) rows required to attempt training
_MIN_ROWS_FOR_TRAINING = 500

# HMM configuration
_N_COMPONENTS = 3
_COVARIANCE_TYPE = "diag"
_N_ITER = 50

# Systemd unit that receives SIGUSR1 for HMM parameter reload
_PIPELINE_UNIT = "indicagent-intelligence-pipeline.service"

# Config directory for parameter files
_CONFIG_DIR = Path("config")


class HMMTrainer:
    """Per-TF HMM training agent.

    Reads intelligence_features from TimescaleDB, fits GaussianHMM via Baum-Welch
    for each configured timeframe, writes atomic JSON parameter files, and signals
    the live intelligence pipeline to reload parameters.

    Args:
        db_manager: DatabaseManager instance with a connection pool.
        settings: Application settings.
        target_tfs: Tuple of timeframe strings to train. Defaults to CVR's registered
            `timeframe` codes if not provided.
        lookback_days: Override lookback per TF. Uses _LOOKBACK_DAYS_BY_TF if not provided.
    """

    def __init__(
        self,
        db_manager: Any,
        settings: Settings,
        target_tfs: tuple[str, ...] | None = None,
        lookback_days: dict[str, int] | None = None,
    ) -> None:
        setup_service_logging("logs/hmm_trainer.log")
        self._db = db_manager
        self._settings = settings
        if target_tfs is None:
            target_tfs = vocabulary_access.standard_timeframes()
        self._target_tfs = target_tfs
        self._lookback_days = lookback_days or dict(_LOOKBACK_DAYS_BY_TF)
        self._config_service: Any | None = None

    async def _load_apr_config(self) -> None:
        """Load HMM hyperparameters from APR, falling back to module-level defaults."""
        from src.config.config_service import ConfigService  # noqa: PLC0415

        cfg = self._config_service
        if cfg is None:
            cfg = ConfigService(self._settings.database_url, pool=self._db.pool)

        self._n_components = int(await cfg.get("feature.hmm.n_components", _N_COMPONENTS))
        self._n_iter = int(await cfg.get("feature.hmm.n_iter", _N_ITER))
        self._min_rows = int(
            await cfg.get("feature.hmm.min_rows_for_training", _MIN_ROWS_FOR_TRAINING)
        )
        self._vol_window = int(await cfg.get("feature.hmm.vol_window", 20))

        for tf in self._target_tfs:
            key = f"feature.hmm.lookback_days.{tf}"
            fallback = self._lookback_days.get(tf, 60)
            self._lookback_days[tf] = int(await cfg.get(key, fallback))

    async def run(self) -> dict[str, str]:
        """Train GaussianHMM for each TF and write parameter files.

        Returns:
            Dict mapping TF string to the path of the written parameter file.
            TFs that were skipped (insufficient data or error) are absent from the dict.
        """
        await self._load_apr_config()
        written: dict[str, str] = {}

        for tf in self._target_tfs:
            try:
                path = await self._train_tf(tf)
                if path is not None:
                    written[tf] = path
            except Exception:
                logger.exception("hmm_training.tf_error", tf=tf)

        logger.info(
            "hmm_training.run_complete",
            trained_tfs=list(written.keys()),
            skipped_tfs=[tf for tf in self._target_tfs if tf not in written],
        )
        return written

    async def _train_tf(self, tf: str) -> str | None:
        """Train a single TF and write its parameter file.

        Returns:
            Path string of written file, or None if skipped.
        """
        symbol_rows = await self._query_features(tf)
        if not symbol_rows:
            logger.info("hmm_training.no_rows", tf=tf)
            return None

        obs_matrix, lengths = self._build_obs_matrix(symbol_rows)
        n_rows = obs_matrix.shape[0]

        if n_rows < self._min_rows:
            logger.info(
                "hmm_training.insufficient_rows",
                tf=tf,
                n=n_rows,
                required=self._min_rows,
                reason="skipping training",
            )
            return None

        logger.info("hmm_training.fitting", tf=tf, n_rows=n_rows, n_symbols=len(lengths))
        params = self._fit_hmm(obs_matrix, lengths, tf)
        if params is None:
            return None

        file_path = self._write_params(tf, params)
        logger.info("hmm_training.params_written", tf=tf, path=file_path, n_rows=n_rows)
        return file_path

    async def _query_features(self, tf: str) -> dict[str, list[dict[str, Any]]]:
        """Query intelligence_features per symbol for the given TF.

        Returns a dict of symbol -> chronologically ordered rows. Querying per symbol
        prevents mixing return sequences across instruments (which corrupts log returns).

        Selects the columns needed to replicate HMMRegimePlugin._build_observation():
          - close price (bar->>'c') for computing log returns + realized vol
          - rsi_14, adx_14, atr_14, macd_histogram_12_26_9 from technical_indicators JSONB
        """
        days = self._lookback_days.get(tf, 60)
        since = datetime.now(UTC) - timedelta(days=days)

        # Fetch distinct symbols first (fast index scan)
        async with self._db.pool.acquire() as conn:
            symbol_rows = await conn.fetch(
                "SELECT DISTINCT symbol FROM intelligence_features WHERE tf = $1 AND ts >= $2",
                tf,
                since,
            )
            symbols = [r["symbol"] for r in symbol_rows]

        sql = """
            SELECT
                ts,
                (bar->>'c')::float AS close,
                (technical_indicators->>'rsi_14')::float AS rsi_14,
                (technical_indicators->>'adx_14')::float AS adx_14,
                (technical_indicators->>'atr_14')::float AS atr_14,
                (technical_indicators->>'macd_histogram_12_26_9')::float AS macd_hist
            FROM intelligence_features
            WHERE tf = $1
              AND symbol = $2
              AND ts >= $3
            ORDER BY ts ASC
        """
        result: dict[str, list[dict[str, Any]]] = {}
        async with self._db.pool.acquire() as conn:
            for symbol in symbols:
                rows = await conn.fetch(sql, tf, symbol, since)
                if rows:
                    result[symbol] = [dict(r) for r in rows]

        return result

    def _build_obs_matrix(
        self, symbol_rows: dict[str, list[dict[str, Any]]]
    ) -> tuple[np.ndarray, list[int]]:
        """Build concatenated observation matrix and lengths for hmmlearn multi-sequence fit.

        Replicates HMMRegimePlugin._build_observation() logic per symbol, then concatenates.
        hmmlearn's fit(X, lengths=lengths) treats each symbol's sequence independently,
        preventing cross-symbol return contamination.

        Returns:
            (obs, lengths) where obs is shape (T_total, n_features) and lengths[i] is the
            number of rows contributed by symbol i. Symbols with fewer than 2 valid closes
            are skipped.
        """
        all_obs: list[np.ndarray] = []
        lengths: list[int] = []
        n_features_global: int | None = None

        for symbol, rows in symbol_rows.items():
            obs = self._build_symbol_obs(rows)
            if obs.shape[0] < 2:
                continue
            n_features = obs.shape[1]
            if n_features_global is None:
                n_features_global = n_features
            elif n_features != n_features_global:
                # Dimension mismatch (one symbol 2D, another 5D) — skip to keep matrix uniform
                continue
            all_obs.append(obs)
            lengths.append(obs.shape[0])

        if not all_obs:
            return np.empty((0, 2), dtype=float), []

        return np.vstack(all_obs), lengths

    def _build_symbol_obs(self, rows: list[dict[str, Any]]) -> np.ndarray:
        """Build obs matrix for a single symbol's row sequence."""
        valid_rows = [r for r in rows if r["close"] is not None]
        if len(valid_rows) < 2:
            return np.empty((0, 2), dtype=float)

        closes = np.array([r["close"] for r in valid_rows], dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratios = closes[1:] / closes[:-1]
            ratios = np.where(ratios > 0, ratios, 1e-10)
            returns = np.log(ratios)

        # Realized volatility: rolling std (match HMMRegimePlugin.vol_window)
        vol_window = getattr(self, "_vol_window", 20)
        realized_vols = np.array(
            [
                float(np.std(returns[max(0, i - vol_window + 1) : i + 1])) if i >= 1 else 0.005
                for i in range(len(returns))
            ],
            dtype=float,
        )

        indicator_rows = valid_rows[1:]  # align with returns (drop first row)

        rsi_vals = np.array(
            [r["rsi_14"] if r["rsi_14"] is not None else float("nan") for r in indicator_rows],
            dtype=float,
        )
        adx_vals = np.array(
            [r["adx_14"] if r["adx_14"] is not None else float("nan") for r in indicator_rows],
            dtype=float,
        )
        atr_vals = np.array(
            [r["atr_14"] if r["atr_14"] is not None else float("nan") for r in indicator_rows],
            dtype=float,
        )
        macd_vals = np.array(
            [
                r["macd_hist"] if r["macd_hist"] is not None else float("nan")
                for r in indicator_rows
            ],
            dtype=float,
        )

        # Rows with near-zero ATR (Globex off-hours, subnormal floats) produce macd/atr → ∞
        # and cause EM divergence. 0.05 is the minimum meaningful ATR for liquid futures on 1m.
        _MIN_ATR = 0.05
        valid_indicator_mask = ~(
            np.isnan(rsi_vals)
            | np.isnan(adx_vals)
            | np.isnan(atr_vals)
            | np.isnan(macd_vals)
            | (atr_vals < _MIN_ATR)
        )
        use_5d = valid_indicator_mask.sum() / max(1, len(returns)) >= 0.5

        if use_5d:
            rsi_norm = (rsi_vals - 50.0) / 50.0
            adx_norm = adx_vals / 50.0
            macd_norm = macd_vals / atr_vals  # atr_vals >= _MIN_ATR guaranteed by mask above
            obs = np.column_stack([returns, realized_vols, rsi_norm, adx_norm, macd_norm])
        else:
            obs = np.column_stack([returns, realized_vols])

        mask = ~np.isnan(obs).any(axis=1)
        return obs[mask]

    def _fit_hmm(self, obs: np.ndarray, lengths: list[int], tf: str) -> dict[str, Any] | None:
        """Fit GaussianHMM on observation matrix and return serializable parameter dict.

        Args:
            obs: Concatenated observation matrix (T_total, n_features).
            lengths: Per-symbol sequence lengths for hmmlearn multi-sequence fit.

        Returns:
            Dict with keys transition_matrix, emission_means, emission_variances
            (matching HMMRegimePlugin._load_parameters() contract), or None on failure.
        """
        try:
            from hmmlearn import hmm as hmmlib  # noqa: PLC0415
        except ImportError:
            logger.error("hmm_training.hmmlearn_not_installed", tf=tf)
            return None

        try:
            model = hmmlib.GaussianHMM(
                n_components=self._n_components,
                covariance_type=_COVARIANCE_TYPE,
                n_iter=self._n_iter,
            )
            model.fit(obs, lengths=lengths if len(lengths) > 1 else None)

            # Serialize parameters — keys must match HMMRegimePlugin._load_parameters().
            # hmmlearn may return covars_ as (K, D, D) for "diag" type; extract the
            # diagonal so emission_variances is always (K, D).
            covars = model.covars_
            if covars.ndim == 3:
                d = covars.shape[1]
                covars = covars[:, np.arange(d), np.arange(d)]
            params: dict[str, Any] = {
                "transition_matrix": model.transmat_.tolist(),
                "emission_means": model.means_.tolist(),
                "emission_variances": covars.tolist(),
                "n_components": self._n_components,
                "covariance_type": _COVARIANCE_TYPE,
                "n_features": obs.shape[1],
                "trained_at": datetime.now(UTC).isoformat(),
                "tf": tf,
                "n_training_rows": int(obs.shape[0]),
            }

            max_abs_mean = float(np.abs(model.means_).max())
            if max_abs_mean > 1e4:
                logger.warning(
                    "hmm_training.degenerate_fit",
                    tf=tf,
                    max_abs_emission_mean=max_abs_mean,
                    reason="refusing to write — likely outlier in training data",
                )
                return None

            convergence_monitor = getattr(model, "monitor_", None)
            if convergence_monitor is not None:
                iter_count = getattr(convergence_monitor, "iter", None)
                converged = getattr(convergence_monitor, "converged", None)
                params["n_iter_actual"] = iter_count
                params["converged"] = converged
                if converged is not None:
                    logger.info(
                        "hmm_training.fit_complete",
                        tf=tf,
                        converged=converged,
                        n_iter=iter_count,
                        n_rows=obs.shape[0],
                        n_features=obs.shape[1],
                    )

            return params

        except Exception:
            logger.exception("hmm_training.fit_error", tf=tf)
            return None

    def _write_params(self, tf: str, params: dict[str, Any]) -> str:
        """Atomically write parameter JSON to config/hmm_parameters_{tf}.json.

        Uses write-to-tmp then os.rename for atomicity — live readers never see
        a half-written file.

        Returns:
            Final file path string.
        """
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        final_path = _CONFIG_DIR / f"hmm_parameters_{tf}.json"
        tmp_path = _CONFIG_DIR / f"hmm_parameters_{tf}.json.tmp"

        try:
            tmp_path.write_text(json.dumps(params, indent=2))
            os.rename(tmp_path, final_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        return str(final_path)

    def emit_sigusr1(self) -> None:
        """Send SIGUSR1 to indicagent-intelligence-pipeline.service to trigger HMM reload.

        Reads MainPID via 'systemctl show' (read-only, no polkit gate) and sends
        SIGUSR1 directly via os.kill(). Both services run as the same user so the
        signal is permitted. Falls back gracefully if systemctl is unavailable or the
        PID cannot be resolved.
        """
        systemctl = self._find_systemctl()
        if systemctl is None:
            logger.warning(
                "hmm_training.sigusr1_skipped",
                reason="systemctl not available -- development mode",
                unit=_PIPELINE_UNIT,
            )
            return

        result = subprocess.run(
            [systemctl, "show", _PIPELINE_UNIT, "--property=MainPID", "--value"],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(
                "hmm_training.sigusr1_skipped",
                reason="systemctl show failed",
                stderr=result.stderr.decode(errors="ignore"),
            )
            return

        pid_str = result.stdout.decode().strip()
        try:
            pid = int(pid_str)
        except ValueError:
            logger.warning("hmm_training.sigusr1_skipped", reason="invalid pid", pid_str=pid_str)
            return

        if pid <= 0:
            logger.warning("hmm_training.sigusr1_skipped", reason="pid not running", pid=pid)
            return

        try:
            os.kill(pid, signal.SIGUSR1)
            logger.info("hmm_training.sigusr1_sent", unit=_PIPELINE_UNIT, pid=pid)
        except ProcessLookupError:
            logger.warning("hmm_training.sigusr1_skipped", reason="process not found", pid=pid)
        except PermissionError:
            logger.warning("hmm_training.sigusr1_skipped", reason="permission denied", pid=pid)

    @staticmethod
    def _find_systemctl() -> str | None:
        """Return path to systemctl binary, or None if not found."""
        import shutil  # noqa: PLC0415

        return shutil.which("systemctl")

    async def start(self) -> None:
        """Orchestrate training run: run() then emit_sigusr1().

        Top-level entry point for asyncio.run(). Catches all exceptions so the
        systemd oneshot service exits 0 regardless of failures.
        """
        logger.info(
            "hmm_training.start",
            target_tfs=list(self._target_tfs),
            n_components=getattr(self, "_n_components", _N_COMPONENTS),
            n_iter=getattr(self, "_n_iter", _N_ITER),
        )

        try:
            written = await self.run()

            if written:
                self.emit_sigusr1()
            else:
                logger.warning(
                    "hmm_training.no_params_written",
                    reason="all TFs skipped or errored — skipping SIGUSR1",
                )

            logger.info(
                "hmm_training.complete",
                params_written=len(written),
                tfs=list(written.keys()),
            )

        except Exception:
            logger.exception("hmm_training.error_top_level")
            # Intentional: swallow so systemd exits 0 and timer fires again next month
