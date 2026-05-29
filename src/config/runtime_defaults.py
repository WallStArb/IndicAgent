"""
Runtime defaults for OPS config keys migrated to the config DB in Phase 109.

These constants are the CODE-LEVEL FALLBACK used by Settings.get_config_value()
when the config DB / Kafka are unavailable, addressing the consensus review
finding that returning None for numeric thresholds is unsafe.

Phase 110 will:
  (a) migrate every call site (e.g., services/alpha_swarm_agent.py's
      self.settings.SWARM_* references) to BaseAgent.get_config() with explicit
      defaults at each call site, then
  (b) remove the corresponding fields from Settings, then
  (c) remove this module.

Keys mirror the dotted notation used in config_schema; values mirror the
pre-migration values in settings.py exactly.
"""

# regime.*
_DEFAULT_REGIME_PROB_MIN: float = 0.30
_DEFAULT_REGIME_DUR_MIN: int = 1

# swarm.*
_DEFAULT_SWARM_MIN_CONFIDENCE: float = 0.60
_DEFAULT_SWARM_MIN_TF_MINUTES: int = 5
_DEFAULT_SWARM_WEIGHT_MIN_SAMPLES: int = 30
_DEFAULT_SWARM_WEIGHT_FLOOR: float = 0.05
_DEFAULT_SWARM_MAX_CONCURRENT_CALLS: int = 8

# roll.*
_DEFAULT_ROLL_MONITOR_WINDOW_SIZE: int = 100
_DEFAULT_ROLL_MONITOR_THRESHOLD_DEFAULT: float = 1.2
_DEFAULT_ROLL_MONITOR_POSTROLL_BARS: int = 10
_DEFAULT_ROLL_MONITOR_COOLDOWN_MIN: int = 30
_DEFAULT_ROLL_CONFIRMATION_BARS: int = 3
_DEFAULT_ROLL_TIME_OF_DAY_GATED: bool = True

# cross_asset.*
_DEFAULT_CROSS_ASSET_WINDOW_BARS: int = 20

# macro.*
_DEFAULT_MACRO_WINDOW_BARS: int = 10

# Lookup table used by Settings.get_config_value as the typed fallback.
# Keys are the dotted notation OPS keys; values are the typed Python defaults.
RUNTIME_DEFAULTS: dict[str, object] = {
    "regime.prob_min": _DEFAULT_REGIME_PROB_MIN,
    "regime.dur_min": _DEFAULT_REGIME_DUR_MIN,
    "swarm.min_confidence": _DEFAULT_SWARM_MIN_CONFIDENCE,
    "swarm.min_tf_minutes": _DEFAULT_SWARM_MIN_TF_MINUTES,
    "swarm.weight_min_samples": _DEFAULT_SWARM_WEIGHT_MIN_SAMPLES,
    "swarm.weight_floor": _DEFAULT_SWARM_WEIGHT_FLOOR,
    "swarm.max_concurrent_calls": _DEFAULT_SWARM_MAX_CONCURRENT_CALLS,
    "roll.monitor_window_size": _DEFAULT_ROLL_MONITOR_WINDOW_SIZE,
    "roll.threshold_default": _DEFAULT_ROLL_MONITOR_THRESHOLD_DEFAULT,
    "roll.postroll_bars": _DEFAULT_ROLL_MONITOR_POSTROLL_BARS,
    "roll.cooldown_min": _DEFAULT_ROLL_MONITOR_COOLDOWN_MIN,
    "roll.confirmation_bars": _DEFAULT_ROLL_CONFIRMATION_BARS,
    "roll.time_of_day_gated": _DEFAULT_ROLL_TIME_OF_DAY_GATED,
    "cross_asset.window_bars": _DEFAULT_CROSS_ASSET_WINDOW_BARS,
    "macro.window_bars": _DEFAULT_MACRO_WINDOW_BARS,
}
