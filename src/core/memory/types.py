"""
Memory return-type dataclasses — Ring 0 contract layer.

These are the read-only value types returned by MemoryClient methods.
All are frozen dataclasses so agents cannot mutate recalled history.
Wave 2 backend implementations and MemoryClient return these types.

Version: 1.0.0
Phase: 097 (agent-memory)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Episode:
    """Single episodic memory entry returned by EpisodicBackend.recall().

    Fields
    ------
    id : str
        UUID of the raw episode row (stringified per asyncpg convention).
    ts : datetime
        Bar timestamp when the episode was recorded (UTC).
    kind : str
        Episode kind — one of 'episodic', 'disagreement', 'relational'
        (mirrors memory_episode_kind ENUM).
    signal_id : str
        UUID of the originating signal (stringified).
    symbol : str
        Instrument symbol (e.g. 'ES', 'MES').
    timeframe : str
        Bar timeframe string (e.g. '5m', '15m').
    agent_id : str
        ID of the AI agent that generated the episode.
    hmm_regime : str
        HMM regime label at the time of the episode (e.g. 'trending_up').
    vol_regime : str
        Volatility regime label (e.g. 'normal', 'elevated').
    entry_type : str
        Entry type (one of the canonical 5: at_close, at_pullback, at_limit,
        at_reclaim, zone_proximal).
    regime_epoch : int
        Distributional epoch from memory_system_state at write time.
        Used for epoch-weighted recall — episodes from different epochs
        are weighted by epoch_decay^(current_epoch - regime_epoch).
    outcome : str | None
        Resolved outcome from signal_outcomes. None if not yet labeled.
    pnl_r : float | None
        Realized PnL in R-multiples. None if not yet resolved.
    mae : float | None
        Max adverse excursion (R). None if not yet resolved.
    mfe : float | None
        Max favorable excursion (R). None if not yet resolved.
    bars_in_trade : int | None
        Bars from activation to exit. None if not yet resolved.
    memory_assisted : bool
        True when MemoryClient.recall() returned results for this episode.
        Used for feedback loop detection (C-04).
    payload : dict
        Snapshot of the SignalContext embedding text and any auxiliary data
        stored at write time.
    similarity : float
        Cosine similarity score from HNSW recall (0.0-1.0).
    epoch_weight : float
        Epoch-decay weight applied during rerank. epoch_decay^(delta_epoch).
        Agents should multiply trust in this episode by epoch_weight.
    """

    id: str
    ts: datetime
    kind: str
    signal_id: str
    symbol: str
    timeframe: str
    agent_id: str
    hmm_regime: str
    vol_regime: str
    entry_type: str
    regime_epoch: int
    outcome: str | None
    pnl_r: float | None
    mae: float | None
    mfe: float | None
    bars_in_trade: int | None
    memory_assisted: bool
    payload: dict
    similarity: float
    epoch_weight: float


@dataclass(frozen=True)
class CalibrationStats:
    """Outcome-driven calibration statistics for an agent/setup cohort.

    Returned by CalibrationBackend.get_calibration(). All rows in
    memory_calibration_promoted carry a CHECK (sample_n >= 30) constraint —
    this object will never represent sub-threshold cohorts.

    Fields — key design notes
    -------------------------
    correction_factor : float | None
        Multiplicative correction applied to agent predictions. None when
        correction_factor_stable is False (variance across rolling sub-windows
        too high for reliable application). Agents must gate on
        correction_factor_stable before trusting this value.

    bootstrapped : bool
        True when this row was written from memory_calibration_promoted (N>=30
        gate met, circular block bootstrap applied).
        False when sample_n is populated but the N>=30 gate was not met —
        represents a partial/cold-start row. Agents should reduce confidence
        weight proportionally when bootstrapped=False.

    skill_score : float
        Brier skill score relative to trivial predictor (base_rate). Negative
        values mean the agent performs worse than predicting base_rate every
        time. Flag as unreliable when skill_score < 0.

    feedback_loop_quarantine : bool
        True when the promotion job detected statistically significant
        difference in outcomes between memory-assisted and non-assisted
        episodes (C-04). Agents should treat calibration as suspect when True.
        quarantine_review_at gives the scheduled re-evaluation timestamp.

    p_signal : float | None
        Propensity score = sample_n / n_eligible. Lower values indicate higher
        selection bias (few eligible bars generated signals). None when
        n_eligible is not yet populated (nightly backfill pending).
    """

    agent_id: str
    symbol: str
    hmm_regime: str
    entry_type: str
    regime_epoch: int
    sample_n: int
    mean_prediction: float
    actual_rate: float
    calibration_error: float
    calibration_error_variance: float
    correction_factor: float | None
    correction_factor_stable: bool
    bootstrapped: bool
    skill_score: float
    information_coefficient: float
    ic_p_value: float
    brier_score: float
    base_rate: float
    ci_lower: float
    ci_upper: float
    p_value_corrected: float
    p_signal: float | None
    feedback_loop_quarantine: bool
    quarantine_review_at: datetime | None
    promoted_at: datetime | None
    window_start: datetime | None
    window_end: datetime | None


@dataclass(frozen=True)
class RegimeHistory:
    """Regime duration and transition priors for a (symbol, timeframe) pair.

    Returned by RegimeBackend.get_regime_history(). Provides Markov priors
    for the current regime and duration distribution statistics.

    Fields — key design notes
    -------------------------
    elapsed_bars : int
        Bars elapsed in the current regime, computed at query time from
        (NOW() - ts_start). Never stored in the DB to avoid staleness.

    transition_probs : dict | None
        Markov transition probability vector from current_regime to each
        next regime. None when transition_n < 30 (C-03 discipline applied
        to satellite table — no inference below gate).

    win_rate : float | None
        Fraction of signals in this regime that achieved a positive pnl_r.
        None when signal_count < 30 (same N-gate as transition_probs).

    duration_p25_bars / duration_median_bars / duration_p75_bars : int
        Duration distribution statistics over closed regime periods.
        Useful for estimating remaining regime life.

    transition_n : int
        Number of observed regime transitions. Agents can use this to
        assess confidence in transition_probs estimates.
    """

    symbol: str
    timeframe: str
    current_regime: str
    ts_start: datetime
    elapsed_bars: int
    duration_median_bars: int
    duration_p25_bars: int
    duration_p75_bars: int
    transition_probs: dict | None
    transition_n: int
    win_rate: float | None
    avg_pnl_r: float
