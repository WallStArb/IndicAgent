"""The gateway auth probe's outcome mapping (todo 395).

The probe's I/O is a live IBKR handshake; the unit-testable surface is the
outcome mapping -- gauge value and job status -- and that a probe failure is
recorded as a probe failure, never as success.
"""

from __future__ import annotations

from scripts.infrastructure.infrastructure_gateway_auth_probe import auth_state


def test_a_successful_handshake_maps_to_authenticated_success():
    assert auth_state(True) == (1, "success")


def test_a_failed_or_timed_out_handshake_maps_to_unauthenticated_failure():
    assert auth_state(False) == (0, "failure")
