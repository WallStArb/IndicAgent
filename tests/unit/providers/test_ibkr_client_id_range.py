"""Todo 542: a client id outside the rotation range must fail loudly, never restart the gateway."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.providers import ibkr as ibkr_module


@pytest.mark.asyncio
@pytest.mark.parametrize("client_id", [ibkr_module._MAX_CLIENT_ID + 1, 77, -1])
async def test_out_of_range_client_id_raises_without_a_gateway_restart(monkeypatch, client_id):
    restart = AsyncMock(return_value=True)
    monkeypatch.setattr(ibkr_module, "_restart_ib_gateway", restart)
    with pytest.raises(ValueError, match="client id"):
        await ibkr_module._connect_with_circuit_breaker("127.0.0.1", 7497, client_id, 1.0)
    restart.assert_not_called()
