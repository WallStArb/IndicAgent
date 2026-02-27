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
    # Optional framing fields — populated by TradeFramer post-aggregation
    entry_type: str = "at_close",
    stop_type: str = "atr",
    target_labels: list[str] | None = None,
    target_types: list[str] | None = None,
    rr_t1: float | None = None,
    rr_t2: float | None = None,
    rr_t3: float | None = None,
    framing_method: str = "atr_fallback",
) -> dict:
    """Construct a validated signal.v1 dict."""
    risk = abs(entry_price - stop_loss)
    rr = abs(targets[0] - entry_price) / risk if risk > 0 else 0.0
    sig = {
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
        "entry_type": entry_type,
        "stop_type": stop_type,
        "target_labels": target_labels or [],
        "target_types": target_types or [],
        "framing_method": framing_method,
    }
    if rr_t1 is not None:
        sig["rr_t1"] = round(rr_t1, 2)
    if rr_t2 is not None:
        sig["rr_t2"] = round(rr_t2, 2)
    if rr_t3 is not None:
        sig["rr_t3"] = round(rr_t3, 2)
    return sig
