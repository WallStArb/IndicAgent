"""Risk-based position sizing calculator for futures trading."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class PositionSize:
    """Result of a position sizing calculation."""

    contracts: int
    risk_per_contract: float
    total_risk: float
    capped: bool = False


def calculate_position_size(
    *,
    entry_price: float,
    stop_loss: float,
    direction: int,
    point_value: float,
    risk_amount: float,
    max_contracts: int = 100,
) -> PositionSize:
    """Calculate the number of contracts to trade given risk parameters.

    Args:
        entry_price: Intended entry price.
        stop_loss: Stop-loss price.
        direction: 1 for long, -1 for short (unused in calc but documents intent).
        point_value: Dollar value per point of the futures contract.
        risk_amount: Maximum dollar amount willing to risk on the trade.
        max_contracts: Hard cap on number of contracts.

    Returns:
        PositionSize with contracts, per-contract risk, total risk, and cap flag.
    """
    stop_distance = abs(entry_price - stop_loss)

    if stop_distance <= 0 or point_value <= 0:
        return PositionSize(contracts=0, risk_per_contract=0.0, total_risk=0.0)

    risk_per_contract = stop_distance * point_value
    raw_contracts = math.floor(risk_amount / risk_per_contract)

    capped = False
    if raw_contracts > max_contracts:
        raw_contracts = max_contracts
        capped = True

    contracts = max(raw_contracts, 0)
    total_risk = contracts * risk_per_contract

    return PositionSize(
        contracts=contracts,
        risk_per_contract=round(risk_per_contract, 2),
        total_risk=round(total_risk, 2),
        capped=capped,
    )
