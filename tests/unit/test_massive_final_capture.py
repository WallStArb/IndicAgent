"""Massive final capture: unit planning, resume, guards and the mirror comparison (HTTP stubbed)."""

from __future__ import annotations

import gzip
import json
from datetime import date

import pytest

from scripts.infrastructure.massive import massive_final_capture as mfc
from scripts.infrastructure.massive.massive_reference_capture import Response, RestConfig

BASE = "https://api.massive.com"
CFG = RestConfig(MASSIVE_API_KEY="test-key")


def _ok(payload: dict) -> Response:
    return Response(200, "Thu, 26 Nov 2026 10:00:00 GMT", json.dumps(payload).encode())


class Vendor:
    """Routes URLs to canned JSON; counts calls; ``next_url`` pagination on ``/paged``."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.status_for: dict[str, int] = {}

    def __call__(self, url: str) -> Response:
        self.calls.append(url)
        for fragment, status in self.status_for.items():
            if fragment in url:
                return Response(status, "", b'{"status":"ERROR"}')
        if "market=fx&active=true" in url:
            return _ok({"results": [{"ticker": "C:EURUSD"}, {"ticker": "C:USDJPY"}]})
        if "market=crypto&active=true" in url:
            return _ok({"results": [{"ticker": "X:BTCUSD"}]})
        if "tickers?market=" in url:
            return _ok({"results": []})
        if "/v2/reference/news" in url and "cursor=" not in url:
            return _ok({"results": [{"id": 1}], "next_url": f"{BASE}/v2/reference/news?cursor=A"})
        return _ok({"results": [{"id": 2}]})


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(mfc, "setup_service_logging", lambda *a, **k: None)
    monkeypatch.setattr(mfc, "flush_and_shutdown_metrics", lambda: None)


def _args(tmp_path, *extra: str):
    return mfc.parse_args(
        ["--data-root", str(tmp_path), "--captured-at", "20261126", "--min-free-gb", "0", *extra]
    )


def _run(tmp_path, vendor, *extra: str) -> int:
    return mfc.run(_args(tmp_path, *extra), cfg=CFG, fetch_fn=vendor, sleep=lambda s: None)


def test_month_slices_cut_at_the_capture_date():
    slices = mfc.month_slices(date(2026, 9, 1), date(2026, 11, 27))
    assert [s[0] for s in slices] == ["2026-09", "2026-10", "2026-11"]
    assert slices[-1][1:] == (date(2026, 11, 1), date(2026, 11, 27))


def test_options_units_split_expired_and_active_around_the_capture_date():
    plan = mfc.Plan(None, "20261126", date(2026, 11, 26), "20261126")  # type: ignore[arg-type]
    keys = {u.key for u in mfc.options_contract_units(plan)}
    assert "2026-11-25@expired" in keys and "2026-11-25@active" not in keys
    assert "2026-11-27@active" in keys and "2026-11-27@expired" not in keys
    assert {"2026-11-26@expired", "2026-11-26@active"} <= keys  # both on the day
    assert not any(k.startswith("2026-11-28") for k in keys)  # a Saturday


def test_unknown_family_refused(tmp_path):
    assert _run(tmp_path, Vendor(), "--only", "nope") == 2


def test_capture_resume_verify_and_summary(tmp_path):
    vendor = Vendor()
    assert _run(tmp_path, vendor, "--only", "economy,news") == 0
    root = tmp_path / "reference"
    pages = list(root.glob("*/20261126/*.json.gz"))
    assert pages and all(not p.name.endswith(".part") for p in pages)
    news_pages = sorted((root / "news" / "20261126").glob("2026-11__p*.json.gz"))
    assert len(news_pages) == 2  # next_url followed
    assert json.loads(gzip.decompress(news_pages[0].read_bytes()))["results"] == [{"id": 1}]
    summary = json.loads((root / "final_manifest" / "20261126.summary.json").read_text())
    assert summary["endpoints"]["economy_inflation"]["pages"] == 1
    assert len(summary["manifest_sha256"]) == 64
    assert not (root / "manifest").exists()  # the reference loader's glob is untouched
    first_calls = len(vendor.calls)
    assert _run(tmp_path, vendor, "--only", "economy,news") == 0
    assert len(vendor.calls) == first_calls  # resumed, nothing refetched
    assert mfc.run(_args(tmp_path, "--verify")) == 0
    pages[0].write_bytes(gzip.compress(b'{"tampered": true}'))
    assert mfc.run(_args(tmp_path, "--verify")) == 1


def test_fx_crypto_lists_feed_the_aggregate_units(tmp_path):
    vendor = Vendor()
    assert _run(tmp_path, vendor, "--only", "fx_crypto_lists,fx_crypto_aggs") == 0
    aggs = [c for c in vendor.calls if "/v2/aggs/ticker/" in c]
    assert sorted(aggs) == sorted(
        f"{BASE}/v2/aggs/ticker/{t}/range/1/day/2000-01-01/2026-11-26?limit=50000&sort=asc"
        for t in ("C:EURUSD", "C:USDJPY", "X:BTCUSD")
    )


def test_aggregates_without_saved_lists_stop_loudly(tmp_path):
    assert _run(tmp_path, Vendor(), "--only", "fx_crypto_aggs") == 2


def test_denied_endpoint_is_reported_and_others_continue(tmp_path):
    vendor = Vendor()
    vendor.status_for["/fed/v1/inflation?"] = 403
    assert _run(tmp_path, vendor, "--only", "economy") == 1
    assert list((tmp_path / "reference" / "economy_labor_market" / "20261126").glob("*.gz"))


def test_budget_stops_the_run(tmp_path):
    assert _run(tmp_path, Vendor(), "--only", "economy", "--budget-gb", "0") == 2


def test_related_companies_skip_delisted(tmp_path):
    listing = tmp_path / "reference" / "tickers_active" / "20261126"
    listing.mkdir(parents=True)
    rows = [{"ticker": "AAA"}, {"ticker": "OLD", "delisted_utc": "2020-01-02T00:00:00Z"}]
    (listing / "all__p0001.json.gz").write_bytes(
        gzip.compress(json.dumps({"results": rows}).encode())
    )
    vendor = Vendor()
    assert _run(tmp_path, vendor, "--only", "related_companies") == 0
    assert vendor.calls == [f"{BASE}/v1/related-companies/AAA"]


def test_mirror_compare_reports_missing_and_changed(tmp_path, monkeypatch, capsys):
    assert _run(tmp_path, Vendor(), "--only", "economy") == 0
    root = tmp_path / "reference"
    local = mfc.local_inventory(root, "20261126")
    assert any(p.startswith("final_manifest/") for p in local)
    monkeypatch.setattr(mfc, "remote_inventory", lambda *a, **k: dict(local))
    assert mfc.run(_args(tmp_path, "--mirror-verify")) == 0
    broken = dict(local)
    first = sorted(broken)[0]
    broken[first] += 1
    del broken[sorted(broken)[-1]]
    monkeypatch.setattr(mfc, "remote_inventory", lambda *a, **k: broken)
    assert mfc.run(_args(tmp_path, "--mirror-verify")) == 1
    assert "missing 1, size differs 1" in capsys.readouterr().out


def test_mirror_push_refuses_under_the_spare_floor(tmp_path, monkeypatch):
    assert _run(tmp_path, Vendor(), "--only", "economy") == 0
    monkeypatch.setattr(mfc, "mirror_free_gb", lambda *a: 10.0)
    assert mfc.run(_args(tmp_path, "--mirror-push")) == 2


def test_aggregate_family_is_paced_between_requests(tmp_path):
    sleeps: list[float] = []
    args = _args(tmp_path, "--only", "fx_crypto_lists,fx_crypto_aggs", "--concurrency", "1")
    assert mfc.run(args, cfg=CFG, fetch_fn=Vendor(), sleep=sleeps.append) == 0
    paced = [s for s in sleeps if s > 12.0]  # the stub clock does not advance
    assert len(paced) == 2  # three pairs, two waits
