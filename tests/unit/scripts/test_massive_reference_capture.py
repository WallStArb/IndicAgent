"""Capture, resume, retry and safety logic of the Massive REST reference capture (todo 600).

No Massive network: responses come from a fake fetch function keyed by URL; the one redirect test
talks to two throwaway servers on 127.0.0.1.
"""

from __future__ import annotations

import argparse
import fcntl
import http.server
import json
import threading
import urllib.error
from pathlib import Path

import pytest

from scripts.infrastructure.massive import massive_reference_capture as cap

BASE = "https://api.massive.com"
DAY = "Tue, 10 Nov 2026 12:00:00 GMT"


@pytest.fixture
def cfg() -> cap.RestConfig:
    return cap.RestConfig(MASSIVE_API_KEY="secret-key-123", MASSIVE_REST_URL=BASE)


class FakeApi:
    """URL -> Response (or a callable returning one); records every URL asked."""

    def __init__(self, routes: dict) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, url: str) -> cap.Response:
        self.calls.append(url)
        answer = self.routes[url]
        return answer() if callable(answer) else answer


def ok(payload: dict) -> cap.Response:
    return cap.Response(200, DAY, json.dumps(payload).encode())


def make_ctx(tmp_path: Path, cfg: cap.RestConfig, api, sleeps: list | None = None, captured="d"):
    sleeps = [] if sleeps is None else sleeps
    manifest = cap.Manifest(tmp_path / "manifest" / f"{captured}.jsonl")
    return cap.Context(cfg, tmp_path, captured, manifest, api, sleeps.append)


SPLITS = cap.list_unit(cap.LIST_ENDPOINTS[2])
FIRST = f"{BASE}/stocks/v1/splits?limit=5000"
SECOND = f"{BASE}/stocks/v1/splits?cursor=2"


class TestUrlsAndKeys:
    def test_strip_key_removes_only_the_api_key_without_reencoding(self):
        assert cap.strip_key(f"{BASE}/v3/x?limit=5&apiKey=SECRET&cursor=a%2Fb") == (
            f"{BASE}/v3/x?limit=5&cursor=a%2Fb"
        )
        assert cap.strip_key(f"{BASE}/v3/x?apiKey=SECRET") == f"{BASE}/v3/x"

    def test_ticker_is_quoted(self):
        row = cap.TickerRow("A/B", None)
        unit = cap.ticker_unit(cap.TICKER_ENDPOINTS[2], row)
        assert unit.first_url(BASE).endswith("ticker=A%2FB&limit=5000")
        assert row.key == "A/B@active"

    def test_delisted_overview_is_dated_the_day_before_delisting(self):
        row = cap.TickerRow("AABA", "2019-06-03")
        overview = cap.ticker_unit(cap.TICKER_ENDPOINTS[0], row)
        assert overview.first_url(BASE) == f"{BASE}/v3/reference/tickers/AABA?date=2019-06-02"
        floats = cap.ticker_unit(cap.TICKER_ENDPOINTS[-1], row)
        assert floats.first_url(BASE) == f"{BASE}/stocks/vX/float?ticker=AABA"
        assert row.key == "AABA@2019-06-03"

    def test_foreign_next_url_raises_and_same_host_with_port_passes(self):
        foreign = json.dumps({"next_url": "https://evil.example/v3/x?c=1"}).encode()
        with pytest.raises(ValueError):
            cap.next_url_of(foreign, BASE)
        same = json.dumps({"next_url": f"{BASE}:443/v3/x?c=1"}).encode()
        assert cap.next_url_of(same, BASE) == f"{BASE}:443/v3/x?c=1"
        assert cap.next_url_of(b'{"results": []}', BASE) is None


class TestRetryAndThrottle:
    def test_retry_after_seconds_and_http_date(self):
        assert cap.parse_retry_after("7") == 7.0
        assert cap.parse_retry_after("") is None
        assert cap.parse_retry_after("garbage") is None
        now = cap.parsedate_to_datetime(DAY)
        assert cap.parse_retry_after("Tue, 10 Nov 2026 12:00:30 GMT", now) == 30.0

    def test_429_honours_retry_after_and_pauses_everyone(self, tmp_path, cfg, monkeypatch):
        monkeypatch.setattr(cap.random, "uniform", lambda a, b: 1.0)
        answers = iter([cap.Response(429, "", b"", "11"), ok({"results": []})])
        sleeps: list[float] = []
        clock = {"t": 0.0}
        ctx = make_ctx(tmp_path, cfg, lambda url: next(answers), sleeps)
        ctx.throttle = cap.Throttle(lambda: clock["t"])
        response = cap.fetch_with_retry(ctx, FIRST)
        assert response.status == 200
        assert ctx.throttle.remaining() == 11.0  # a shared pause, seen by every worker
        assert sleeps == [11.0]  # the retrying thread waited out the shared pause once

    def test_network_error_retries_then_succeeds(self, tmp_path, cfg):
        calls = {"n": 0}

        def flaky(url):
            calls["n"] += 1
            if calls["n"] < 3:
                raise urllib.error.URLError("boom")
            return ok({})

        ctx = make_ctx(tmp_path, cfg, flaky)
        ctx.throttle = cap.Throttle(
            lambda: 0.0
        )  # pauses never elapse in a frozen clock: no real wait
        ctx.sleep = lambda s: None
        assert cap.fetch_with_retry(ctx, FIRST).status == 200

    def test_gives_up_after_max_attempts(self, tmp_path, cfg):
        ctx = make_ctx(tmp_path, cfg, lambda url: cap.Response(503, "", b""))
        ctx.throttle = cap.Throttle(lambda: 0.0)
        with pytest.raises(RuntimeError):
            cap.fetch_with_retry(ctx, FIRST)

    def test_401_is_fatal_403_is_endpoint_scoped_redirect_refused(self, tmp_path, cfg):
        with pytest.raises(cap.AuthError):
            cap.fetch_with_retry(
                make_ctx(tmp_path, cfg, lambda u: cap.Response(401, "", b"")), FIRST
            )
        with pytest.raises(cap.EndpointDenied):
            cap.fetch_with_retry(
                make_ctx(tmp_path, cfg, lambda u: cap.Response(403, "", b"")), FIRST
            )
        with pytest.raises(RuntimeError, match="redirect refused"):
            cap.fetch_with_retry(
                make_ctx(tmp_path, cfg, lambda u: cap.Response(302, "", b"")), FIRST
            )


class TestRedirectNeverForwardsTheKey:
    def test_http_fetch_stops_at_a_redirect_to_another_host(self, cfg):
        seen: list[dict] = []

        class Target(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                seen.append(dict(self.headers))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):  # noqa: D401
                return

        target = http.server.HTTPServer(("127.0.0.1", 0), Target)

        class Redirector(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{target.server_port}/stolen")
                self.end_headers()

            def log_message(self, *args):
                return

        redirector = http.server.HTTPServer(("127.0.0.1", 0), Redirector)
        for server in (target, redirector):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            response = cap.http_fetch(cfg, f"http://127.0.0.1:{redirector.server_port}/x")
        finally:
            for server in (target, redirector):
                server.shutdown()
        assert response.status == 302
        assert seen == []  # the second host was never contacted, so it never saw the key


class TestCaptureUnit:
    def routes(self):
        return {
            FIRST: ok({"results": [{"ticker": "AAPL"}], "next_url": SECOND}),
            SECOND: ok({"results": [{"ticker": "NVDA"}]}),
        }

    def test_follows_pages_writes_files_and_manifest(self, tmp_path, cfg):
        api = FakeApi(self.routes())
        ctx = make_ctx(tmp_path, cfg, api)
        assert cap.capture_unit(SPLITS, ctx) == 2 and api.calls == [FIRST, SECOND]
        page2 = cap.page_path(tmp_path, "splits", "d", "all", 2)
        record = ctx.manifest.get("splits", "all", 2)
        assert record["status"] == 200 and record["url"] == SECOND
        assert record["sha256"] == cap.sha256_bytes(cap.read_page(page2))

    def test_resume_skips_recorded_intact_pages(self, tmp_path, cfg):
        cap.capture_unit(SPLITS, make_ctx(tmp_path, cfg, FakeApi(self.routes())))
        api = FakeApi({})  # any network call would KeyError
        assert cap.capture_unit(SPLITS, make_ctx(tmp_path, cfg, api)) == 0 and api.calls == []

    def test_corrupt_file_on_resume_is_fetched_again(self, tmp_path, cfg):
        cap.capture_unit(SPLITS, make_ctx(tmp_path, cfg, FakeApi(self.routes())))
        cap.write_page(
            cap.page_path(tmp_path, "splits", "d", "all", 1), b'{"results": ["tampered"]}'
        )
        api = FakeApi(self.routes())
        assert cap.capture_unit(SPLITS, make_ctx(tmp_path, cfg, api)) == 1
        assert api.calls == [FIRST]

    def test_file_without_record_is_fetched_again(self, tmp_path, cfg):
        cap.write_page(cap.page_path(tmp_path, "splits", "d", "all", 1), b"stale")
        api = FakeApi(self.routes())
        assert cap.capture_unit(SPLITS, make_ctx(tmp_path, cfg, api)) == 2

    def test_page_one_404_is_the_served_answer(self, tmp_path, cfg):
        url = f"{BASE}/v3/reference/tickers/ZZZZ"
        api = FakeApi({url: cap.Response(404, DAY, b'{"status":"NOT_FOUND"}')})
        ctx = make_ctx(tmp_path, cfg, api)
        unit = cap.ticker_unit(cap.TICKER_ENDPOINTS[0], cap.TickerRow("ZZZZ", None))
        assert cap.capture_unit(unit, ctx) == 1
        assert ctx.manifest.get("overview", "ZZZZ@active", 1)["status"] == 404

    def test_invalid_json_200_is_a_failure_and_not_recorded(self, tmp_path, cfg):
        api = FakeApi({FIRST: cap.Response(200, DAY, b"<html>proxy error</html>")})
        ctx = make_ctx(tmp_path, cfg, api)
        with pytest.raises(RuntimeError, match="not JSON"):
            cap.capture_unit(SPLITS, ctx)
        assert ctx.manifest.get("splits", "all", 1) is None

    def test_later_page_error_fails_the_unit_and_fresh_retry_restarts_at_page_one(
        self, tmp_path, cfg
    ):
        bad = {
            FIRST: ok({"results": [], "next_url": SECOND}),
            SECOND: cap.Response(400, DAY, b"{}"),
        }
        ctx = make_ctx(tmp_path, cfg, FakeApi(bad))
        with pytest.raises(RuntimeError, match="page 2"):
            cap.capture_unit(SPLITS, ctx)
        assert (
            ctx.manifest.get("splits", "all", 2) is None
        )  # nothing marks a truncated unit complete
        good = FakeApi(self.routes())
        assert cap.capture_unit(SPLITS, make_ctx(tmp_path, cfg, good), fresh=True) == 2
        assert good.calls == [FIRST, SECOND]

    def test_repeated_cursor_is_refused(self, tmp_path, cfg):
        loop = {FIRST: ok({"results": [], "next_url": FIRST})}
        with pytest.raises(RuntimeError, match="did not end"):
            cap.capture_unit(SPLITS, make_ctx(tmp_path, cfg, FakeApi(loop)))

    def test_endpoint_denied_skips_the_rest_of_that_endpoint(self, tmp_path, cfg):
        ctx = make_ctx(tmp_path, cfg, FakeApi({FIRST: cap.Response(403, DAY, b"{}")}))
        fetched, failed = cap.run_units([SPLITS, SPLITS], ctx, 1, 0)
        assert ctx.denied == {"splits"} and failed == [] and fetched == 0


class TestManifest:
    def test_torn_trailing_line_is_skipped_and_terminated(self, tmp_path):
        path = tmp_path / "m.jsonl"
        path.write_text(
            json.dumps({"endpoint": "e", "key": "k", "page": 1}) + '\n{"endpoint": "e", "ke'
        )
        manifest = cap.Manifest(path)
        assert manifest.get("e", "k", 1) is not None
        manifest.append({"endpoint": "e", "key": "k", "page": 2})
        assert json.loads(path.read_text().splitlines()[-1])["page"] == 2

    def test_damage_before_the_last_line_raises(self, tmp_path):
        path = tmp_path / "m.jsonl"
        path.write_text('{"bad\n' + json.dumps({"endpoint": "e", "key": "k", "page": 1}) + "\n")
        with pytest.raises(json.JSONDecodeError):
            cap.Manifest(path)


class TestTickersAndVerify:
    def test_ticker_rows_distinguish_reused_symbols_by_delisting_date(self, tmp_path):
        pages = {
            "tickers_active": [{"ticker": "EXE"}, {"ticker": "BRK.B"}],
            "tickers_delisted": [
                {"ticker": "EXE", "delisted_utc": "2010-05-04T04:00:00Z"},
                {"ticker": "LEH", "delisted_utc": "2008-09-17T04:00:00Z"},
            ],
        }
        for name, results in pages.items():
            cap.write_page(
                cap.page_path(tmp_path, name, "d", "all", 1),
                json.dumps({"results": results}).encode(),
            )
        assert [row.key for row in cap.ticker_rows(tmp_path, "d")] == [
            "BRK.B@active",
            "EXE@active",
            "EXE@2010-05-04",
            "LEH@2008-09-17",
        ]

    def test_verify_flags_corruption_and_missing(self, tmp_path, cfg):
        api = FakeApi({FIRST: ok({"results": []})})
        ctx = make_ctx(tmp_path, cfg, api)
        cap.capture_unit(SPLITS, ctx)
        mpath = ctx.manifest.path
        assert cap.verify_capture(tmp_path, mpath) == 0
        path = cap.page_path(tmp_path, "splits", "d", "all", 1)
        cap.write_page(path, b'{"results": [1]}')
        assert cap.verify_capture(tmp_path, mpath) == 1
        path.unlink()
        assert cap.verify_capture(tmp_path, mpath) == 1


class TestRun:
    def args(self, tmp_path, **over):
        base = dict(
            data_root=tmp_path,
            captured_at="20261110",
            only=None,
            ticker_limit=0,
            verify=False,
            env_file=tmp_path / ".env",
            concurrency=2,
            min_free_gb=0,
        )
        base.update(over)
        return argparse.Namespace(**base)

    def routes(self):
        def lst(*tickers):
            return ok({"results": [{"ticker": t} for t in tickers]})

        routes = {
            f"{BASE}/v3/reference/tickers?market=stocks&active=true&limit=1000": lst("AAPL"),
            f"{BASE}/v3/reference/tickers?market=stocks&active=false&limit=1000": ok(
                {"results": [{"ticker": "LEH", "delisted_utc": "2008-09-17T04:00:00Z"}]}
            ),
            f"{BASE}/stocks/v1/splits?limit=5000": ok({"results": []}),
            f"{BASE}/stocks/v1/dividends?limit=5000": ok({"results": []}),
            f"{BASE}/vX/reference/ipos?limit=1000": ok({"results": []}),
        }
        for row in (cap.TickerRow("AAPL", None), cap.TickerRow("LEH", "2008-09-17")):
            for endpoint in cap.TICKER_ENDPOINTS:
                routes[cap.ticker_unit(endpoint, row).first_url(BASE)] = ok({"key": row.key})
        return routes

    def test_full_run_then_idempotent_rerun_then_verify(self, tmp_path, cfg):
        api = FakeApi(self.routes())
        assert cap.run(self.args(tmp_path), cfg, api, lambda s: None) == 0
        first_calls = len(api.calls)
        assert first_calls == 5 + 2 * len(cap.TICKER_ENDPOINTS)
        assert cap.run(self.args(tmp_path), cfg, api, lambda s: None) == 0
        assert len(api.calls) == first_calls  # nothing refetched
        assert cap.run(self.args(tmp_path, verify=True), cfg, api, lambda s: None) == 0

    def test_ticker_phase_is_refused_when_a_list_failed(self, tmp_path, cfg, monkeypatch):
        monkeypatch.setattr(cap, "RETRY_PASSES", 0)
        routes = self.routes()
        routes[f"{BASE}/v3/reference/tickers?market=stocks&active=false&limit=1000"] = cap.Response(
            200, DAY, b"<html>"
        )
        api = FakeApi(routes)
        assert cap.run(self.args(tmp_path), cfg, api, lambda s: None) == 1
        assert not any("/overview" in c or "float" in c for c in api.calls)

    def test_ticker_limit_only_and_unknown_endpoint(self, tmp_path, cfg):
        api = FakeApi(self.routes())
        args = self.args(tmp_path, ticker_limit=1, only="float,tickers_active,tickers_delisted")
        cap.run(args, cfg, api, lambda s: None)
        assert sum("float" in c for c in api.calls) == 1
        assert cap.run(self.args(tmp_path, only="nope"), cfg, api, lambda s: None) == 2

    def test_auth_failure_exits_3(self, tmp_path, cfg):
        api = FakeApi({})
        api_fn = lambda url: cap.Response(401, "", b"")  # noqa: E731
        assert cap.run(self.args(tmp_path), cfg, api_fn, lambda s: None) == 3
        assert api.calls == []

    def test_floor_refusal_and_lock_exit_2(self, tmp_path, cfg):
        assert (
            cap.run(self.args(tmp_path, min_free_gb=10**9), cfg, FakeApi({}), lambda s: None) == 2
        )
        lock_path = tmp_path / "reference" / "manifest" / "20261110.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("w") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            assert cap.run(self.args(tmp_path), cfg, FakeApi({}), lambda s: None) == 2


class TestPitSnapshots:
    def test_month_ends_are_the_last_nyse_session_capped_at_the_last_file_day(self):
        from datetime import date

        days = cap.month_end_sessions(date(2003, 9, 1), date(2026, 11, 9))
        assert days[0] == date(2003, 9, 30) and days[-1] == date(2026, 11, 9)
        assert date(2008, 2, 29) in days and date(2016, 12, 30) in days  # 2016-12-31 a Saturday
        assert len(days) == len({(d.year, d.month) for d in days}) == 279

    def test_each_date_asks_active_and_inactive_with_the_date(self):
        from datetime import date

        units = cap.pit_units([date(2010, 3, 31)])
        assert [u.key for u in units] == ["2010-03-31@active", "2010-03-31@inactive"]
        assert units[0].first_url(BASE) == (
            f"{BASE}/v3/reference/tickers?market=stocks&active=true&date=2010-03-31&limit=1000"
        )
        assert "active=false&date=2010-03-31" in units[1].first_url(BASE)

    def test_a_snapshot_page_lands_under_pit_snapshots_with_its_manifest_line(self, tmp_path, cfg):
        from datetime import date

        unit = cap.pit_units([date(2010, 3, 31)])[0]
        api = FakeApi({unit.first_url(BASE): ok({"results": [{"ticker": "AAPL"}]})})
        ctx = make_ctx(tmp_path, cfg, api)
        assert cap.capture_unit(unit, ctx) == 1
        assert cap.page_path(tmp_path, "pit_snapshots", "d", "2010-03-31@active", 1).is_file()
        assert ctx.manifest.get("pit_snapshots", "2010-03-31@active", 1)["status"] == 200

    def test_the_mode_is_a_dry_run_without_apply(self, capsys):
        assert cap.main(["--pit-snapshots", "--pit-dates", "2010-03-31,2010-04-30"]) == 0
        assert "4 units" in capsys.readouterr().out
