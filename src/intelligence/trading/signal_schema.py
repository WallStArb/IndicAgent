"""Signal v1 schema definition and validation."""

from __future__ import annotations

REQUIRED_SIGNAL_FIELDS = frozenset({
    "type", "symbol", "timeframe", "timestamp", "signal_type",
    "setup_plugin", "direction", "entry_price", "stop_loss", "targets",
    "confidence", "risk_reward_ratio", "regime_context", "confluence_score",
    "supporting_factors", "invalidation_conditions", "ttl_bars",
})


def validate_signal(signal: dict) -> bool:
    """Validate a signal.v1 dictionary. Returns True if valid."""
    if not isinstance(signal, dict):
        return False
    if not REQUIRED_SIGNAL_FIELDS.issubset(signal.keys()):
        return False
    if signal.get("type") != "signal.v1":
        return False
    conf = signal.get("confidence")
    if not isinstance(conf, (int, float)) or conf < 0.0 or conf > 1.0:
        return False
    direction = signal.get("direction")
    if direction not in (1, -1, 1.0, -1.0):
        return False
    targets = signal.get("targets")
    if not isinstance(targets, list) or len(targets) == 0:
        return False
    return True


def make_signal(
    *,
    symbol: str,
    timeframe: str,
    timestamp: str,
    signal_type: str,
    setup_plugin: str,
    direction: int,
    entry_price: float,
    stop_loss: float,
    targets: list[float],
    confidence: float,
    regime_context: str,
    confluence_score: float,
    supporting_factors: list[str],
    invalidation_conditions: list[str],
    ttl_bars: int = 10,
) -> dict:
    """Construct a validated signal.v1 dict."""
    risk = abs(entry_price - stop_loss)
    rr = abs(targets[0] - entry_price) / risk if risk > 0 else 0.0
    return {
        "type": "signal.v1",
        "symbol": symbol,
        "timeframe": timeframe,
        "timestamp": timestamp,
        "signal_type": signal_type,
        "setup_plugin": setup_plugin,
        "direction": direction,
        "entry_price": round(entry_price, 2),
        "stop_loss": round(stop_loss, 2),
        "targets": [round(t, 2) for t in targets],
        "confidence": round(min(1.0, max(0.0, confidence)), 4),
        "risk_reward_ratio": round(rr, 2),
        "regime_context": regime_context,
        "confluence_score": round(confluence_score, 4),
        "supporting_factors": supporting_factors,
        "invalidation_conditions": invalidation_conditions,
        "ttl_bars": ttl_bars,
    }
