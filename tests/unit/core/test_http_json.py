"""get_json: retries server and transport errors, not client errors, and never leaks a secret."""

import asyncio

import httpx
import pytest

import src.core.retry_utils as retry_utils
from src.core.http_json import HttpJsonError, get_json

SECRET = "s3cr3t-key"


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch):
    monkeypatch.setattr(retry_utils, "exponential_backoff_with_jitter", lambda *a, **k: 0.0)


def _client(responses):
    calls = []

    def handler(request):
        calls.append(request)
        status, body = responses[min(len(calls), len(responses)) - 1]
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


def _get(client, **kwargs):
    async def go():
        async with client:
            return await get_json(client, "https://x.test/obs", {"api_key": SECRET}, **kwargs)

    return asyncio.run(go())


def test_server_error_is_retried_then_succeeds():
    client, calls = _client([(503, {}), (200, {"ok": 1})])
    assert _get(client, secret=SECRET, max_attempts=3) == {"ok": 1}
    assert len(calls) == 2


def test_rate_limit_is_retried():
    client, calls = _client([(429, {}), (200, {"ok": 1})])
    assert _get(client, secret=SECRET, max_attempts=3) == {"ok": 1}
    assert len(calls) == 2


def test_client_error_is_not_retried():
    client, calls = _client([(404, {})])
    with pytest.raises(HttpJsonError):
        _get(client, secret=SECRET, max_attempts=3)
    assert len(calls) == 1


def test_secret_never_appears_in_the_error_or_its_chain():
    client, _ = _client([(400, {})])
    with pytest.raises(HttpJsonError) as caught:
        _get(client, secret=SECRET, max_attempts=1)
    assert SECRET not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
