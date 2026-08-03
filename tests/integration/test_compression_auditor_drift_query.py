"""Integration test for CompressionAuditor's drift query against the real database.

Exists specifically because tests/unit/services/test_compression_auditor.py's mocked
asyncpg pool could not catch a real regression: the drift query's grace-period
parameter was originally passed as a Python str (f"{hours} hours") to a `$1::interval`
cast. A mock accepts any Python value and round-trips it unchanged, so the unit suite
was green — but real asyncpg negotiates the parameter's server-side type from the
query text and encodes it via its interval codec, which requires a
datetime.timedelta-like object, not a string. This only surfaced once the daemon was
deployed and its live journal showed "'str' object has no attribute 'days'" on every
audit cycle. This test exercises the real connection so that class of bug fails CI
next time instead of shipping silently, same lesson as the compression policy bug
this daemon exists to catch in the first place.

Read-only: SELECTs the real timescaledb_information.jobs/chunks catalog views. Does
not call CALL run_job() -- remediation is exercised only by the mocked unit suite,
never against a live database from a test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services"))

from services.compression_auditor import CompressionAuditor  # noqa: E402

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.requires_db
async def test_drift_query_executes_without_type_error_against_real_db():
    """A full _run_audit() cycle against the live database logs no audit_error --
    proof the grace-period parameter's type is accepted by real asyncpg/Postgres,
    not just by a mock."""
    agent = CompressionAuditor()
    await agent._setup()
    try:
        errors: list[str] = []
        agent.logger = agent.logger.bind()  # keep real logger; also capture via patch below
        original_error = agent.logger.error

        def _capture_error(event, *args, **kwargs):
            errors.append(event)
            return original_error(event, *args, **kwargs)

        agent.logger.error = _capture_error
        await agent._run_audit()
        assert errors == [], f"_run_audit logged error(s) against the real DB: {errors}"
    finally:
        await agent._teardown()
