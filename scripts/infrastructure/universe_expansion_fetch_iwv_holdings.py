#!/usr/bin/env python3
"""
universe_expansion_fetch_iwv_holdings.py — Russell 3000 population sourcing (Phase 174, Plan 04)

Fetches the iShares IWV (Russell 3000 ETF) public holdings export — the issuer's own
source of truth for Russell 3000 membership (RESEARCH.md "Don't Hand-Roll" table) — and
parses it into a validated symbol/name/market_cap population frame. Plan 08's market-cap-
stratified sampling script consumes this frame's narrow three-column contract; it does not
read the issuer's raw column names directly.

D-02: Russell 3000 is the definitional target population, sourced systematically with no
cherry-picking. This module answers RESEARCH.md's Open Question 1 (does the file expose
market cap directly, or must it be derived) empirically, against the real downloaded file,
rather than assuming.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd
import structlog

# sys.path bootstrap: this file is scripts/infrastructure/<this file>.py -- 3 parents
# reach repo root (infrastructure/ -> scripts/ -> root). See
# infrastructure_run_historical_pipeline.py's own header comment for the class of bug
# this guards against (a wrong parent count silently breaks `import src` unless
# PYTHONPATH is already set externally by every production invocation).
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics  # noqa: E402

_logger = structlog.get_logger(__name__)

# Verified live 2026-09-15 (this session): the issuer's fund-page "Download Holdings"
# link resolves to this path, which returns the real CSV export directly -- no session
# cookies or JS execution required. The older `.ajax?fileType=csv&fileName=...` endpoint
# (a plausible-looking guess) was tried first and confirmed to serve an HTML single-page-
# app shell instead, even with browser-like headers and a warmed cookie jar from the
# product page -- see the `<html` body-sniff check in _validate_response() below, which
# is what actually catches that failure mode (Content-Type alone does not: the fake page
# claimed `text/csv`, the real file returns `text/plain`).
DEFAULT_URL = (
    "https://www.ishares.com/us/products/239714/ishares-russell-3000-etf/latest-holdings.csv"
)

# Browser-like headers -- iShares/BlackRock sits behind a CDN + bot-mitigation layer
# (SourceDefense, observed in response headers) that can answer a default Python
# urllib User-Agent with an HTTP 403 or a challenge page. Module-level so the fallback
# source path (Barchart / StockAnalysis.com, per PLAN interfaces) reuses the identical
# header set via the same fetch_holdings(url=...) override.
HTTP_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/vnd.ms-excel,text/plain,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# An issuer export is hundreds of KB; the fake `.ajax`-endpoint challenge shell observed
# live this session was actually LARGER (~1.4MB) than the real file (~390KB) -- so this
# size floor alone does not catch that failure mode. It stays as a cheap first-pass guard
# against a genuinely truncated/empty response; the `<html` body sniff below is the
# check that actually discriminates the real file from the challenge shell.
_MIN_PLAUSIBLE_BYTES = 50_000

# Content-Type is NOT a reliable discriminator for this endpoint: the real file returns
# `text/plain; charset=utf-8` while the fake challenge-shell response (observed live,
# via the wrong `.ajax` endpoint) returned `text/csv;charset=UTF-8` -- the exact opposite
# of what a naive check would assume. Kept permissive; only an explicit `html` marker is
# treated as a hard rejection signal from this header alone.
_ACCEPTABLE_CONTENT_TYPE_MARKERS = ("csv", "octet-stream", "excel", "plain")

# Header row index (0-indexed) in the real downloaded file. iShares prepends 8 lines of
# fund-level metadata (fund name, "Fund Holdings as of", inception date, shares
# outstanding, Stock/Bond/Cash/Other asset-class totals) plus one blank separator line
# before the real column header. Verified live 2026-09-15 against the real download --
# if a future issuer schema change shifts this, parse_holdings() below fails loud via
# the header-mismatch ValueError rather than silently mis-parsing.
HEADER_ROW_INDEX = 9

# Verbatim column-name list from the real downloaded file (2026-09-15). Recorded as a
# decision per RESEARCH.md Open Question 1, not assumed from documentation.
EXPECTED_COLUMNS = [
    "Ticker",
    "Name",
    "Sector",
    "Asset Class",
    "Market Value",
    "Weight (%)",
    "Notional Value",
    "Quantity",
    "Price",
    "Location",
    "Exchange",
    "Currency",
    "FX Rate",
    "Market Currency",
    "Accrual Date",
]

# Asset Class values observed in the real file that are NOT Russell 3000 equity
# constituents -- futures overlay positions and cash/margin sleeves iShares carries for
# portfolio-management purposes, not index membership. Verified live 2026-09-15: 2
# 'Futures' rows (RTY/ES E-mini overlay), 1 'Money Market', 1 'Cash', 1 'Cash Collateral
# and Margins' (5 filler rows out of 2,580 total data rows in the real file).
NON_EQUITY_ASSET_CLASSES = frozenset(
    {"Futures", "Money Market", "Cash", "Cash Collateral and Margins"}
)

# Ticker validation per Task 2 / threat T-174-03 / T-174-02: uppercase, bounded length.
# Anything else (including a bare "-" placeholder for unlisted/escrow securities, or a
# ticker string carrying SQL metacharacters) is rejected and counted, never coerced.
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _decode_bytes(raw: bytes) -> tuple[str, str]:
    """Decode response bytes, falling back to latin-1 on a UTF-8 decode failure.

    Issuer exports have historically switched encodings between UTF-8 and
    Windows-1252/latin-1. This is used only to determine and log which encoding the
    real file decoded as -- the raw bytes are written to disk verbatim regardless (see
    fetch_holdings()), so the exact bytes that produced a given sample stay auditable.
    """
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


def _validate_response(url: str, status: int, content_type: str, body: bytes) -> None:
    """Fail loud on a non-200, non-CSV-ish, or challenge-page response.

    A silently-saved 403/challenge page would otherwise surface downstream as a
    confusing header-mismatch ValueError in parse_holdings() -- these checks catch it
    at the source, before anything is written to disk.
    """
    if status != 200:
        raise RuntimeError(
            f"IWV holdings fetch failed: {url} returned HTTP {status} (expected 200)."
        )

    content_type_lower = content_type.lower()
    if "html" in content_type_lower:
        raise RuntimeError(
            f"IWV holdings fetch failed: {url} returned Content-Type '{content_type}', "
            "which indicates an HTML challenge/error page, not a holdings export."
        )
    if not any(marker in content_type_lower for marker in _ACCEPTABLE_CONTENT_TYPE_MARKERS):
        raise RuntimeError(
            f"IWV holdings fetch failed: {url} returned unexpected Content-Type "
            f"'{content_type}' (expected csv/octet-stream/excel/plain-text-ish)."
        )

    if len(body) < _MIN_PLAUSIBLE_BYTES:
        raise RuntimeError(
            f"IWV holdings fetch failed: response body is only {len(body)} bytes "
            f"(minimum plausible size is {_MIN_PLAUSIBLE_BYTES}) -- likely a challenge "
            "page or truncated response, not the real holdings export."
        )

    sniff = body[:512].lower()
    if b"<html" in sniff:
        raise RuntimeError(
            f"IWV holdings fetch failed: response body's first 512 bytes contain "
            f"'<html' (status={status}, content_type='{content_type}', "
            f"bytes={len(body)}) -- this is an HTML challenge/app-shell page, not the "
            "real CSV holdings export. Confirmed live 2026-09-15: an alternate/guessed "
            "endpoint can serve exactly this shape of bot-mitigation shell even on a "
            "200 response labeled Content-Type: text/csv -- DEFAULT_URL above is the "
            "endpoint verified NOT to do this."
        )


def fetch_holdings(dest_path: Path, url: str | None = None) -> Path:
    """Download the iShares IWV holdings export to dest_path and return it.

    Writes the response body to disk verbatim (no parse-on-the-fly) so the exact bytes
    that produced a given sample stay auditable. Raises RuntimeError, naming the
    observed value, if the response fails any of the status/content-type/body-
    plausibility checks in _validate_response().
    """
    target_url = url or DEFAULT_URL
    request = urllib.request.Request(target_url, headers=HTTP_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            status = response.status
            content_type = response.headers.get("Content-Type", "")
            body = response.read()
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"IWV holdings fetch failed: {target_url} returned HTTP {error.code}."
        ) from error
    except urllib.error.URLError as error:
        raise RuntimeError(
            f"IWV holdings fetch failed: could not reach {target_url} ({error.reason})."
        ) from error

    _validate_response(target_url, status, content_type, body)

    _, encoding = _decode_bytes(body)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(body)

    _logger.info(
        "fetch_holdings.complete",
        url=target_url,
        status=status,
        content_type=content_type,
        bytes=len(body),
        encoding=encoding,
        dest=str(dest_path),
    )
    return dest_path


def _parse_money(raw: str | None) -> float | None:
    """Parse a currency-formatted string ('$1,234.56', '1,234.56', '-') to a float.

    Returns None for empty/placeholder/malformed values rather than raising -- the
    caller counts and rejects these rows instead of coercing them into the population.
    """
    if raw is None:
        return None
    cleaned = raw.strip().replace("$", "").replace(",", "")
    if not cleaned or cleaned in {"-", "N/A", "NaN", "n/a"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_holdings(path: Path) -> pd.DataFrame:
    """Parse a downloaded IWV holdings CSV into a validated symbol/name/market_cap frame.

    Treats the file as untrusted input (T-174-03): the header is validated against the
    recorded schema (loud ValueError on drift), non-equity filler rows are dropped by
    Asset Class, and each retained row's ticker/market-cap are validated before being
    accepted -- rejected rows are counted, never silently coerced into the population.

    Returns a frame with exactly the columns `symbol`, `name`, `market_cap` -- callers
    depend on this narrow contract, not on the issuer's column names. Rejection/filler/
    acceptance counts are attached via df.attrs (n_rows_raw, n_filler_dropped,
    n_rejected, n_accepted) and logged once at the end, never per-row.
    """
    raw_bytes = path.read_bytes()
    text, _encoding = _decode_bytes(raw_bytes)
    lines = text.splitlines()

    if len(lines) <= HEADER_ROW_INDEX:
        raise ValueError(
            f"IWV holdings file has only {len(lines)} lines; expected the header row "
            f"at index {HEADER_ROW_INDEX} per the recorded schema. File may be "
            "truncated or not the expected artifact."
        )

    header_line = lines[HEADER_ROW_INDEX]
    actual_columns = next(csv.reader([header_line]))
    if actual_columns != EXPECTED_COLUMNS:
        raise ValueError(
            f"IWV holdings header mismatch at row {HEADER_ROW_INDEX}: expected "
            f"{EXPECTED_COLUMNS}, got {actual_columns}. The issuer schema may have "
            "changed -- re-verify against the real file and update EXPECTED_COLUMNS/"
            "HEADER_ROW_INDEX deliberately, do not silently adapt to a drifted schema."
        )

    data_lines = lines[HEADER_ROW_INDEX:]
    reader = csv.DictReader(data_lines)

    n_rows_raw = 0
    n_filler_dropped = 0
    n_rejected = 0
    records: list[dict[str, Any]] = []

    for row in reader:
        if row is None:
            continue
        n_rows_raw += 1
        ticker_raw = (row.get("Ticker") or "").strip()
        name = (row.get("Name") or "").strip()
        asset_class = (row.get("Asset Class") or "").strip()
        market_value_raw = row.get("Market Value")

        if asset_class in NON_EQUITY_ASSET_CLASSES:
            n_filler_dropped += 1
            continue

        if not _TICKER_RE.match(ticker_raw):
            n_rejected += 1
            continue

        market_cap = _parse_money(market_value_raw)
        if market_cap is None or not math.isfinite(market_cap) or market_cap <= 0:
            n_rejected += 1
            continue

        records.append({"symbol": ticker_raw, "name": name, "market_cap": market_cap})

    n_accepted = len(records)
    df = pd.DataFrame(records, columns=["symbol", "name", "market_cap"])
    df.attrs["n_rows_raw"] = n_rows_raw
    df.attrs["n_filler_dropped"] = n_filler_dropped
    df.attrs["n_rejected"] = n_rejected
    df.attrs["n_accepted"] = n_accepted

    _logger.info(
        "parse_holdings.complete",
        n_rows_raw=n_rows_raw,
        n_filler_dropped=n_filler_dropped,
        n_rejected=n_rejected,
        n_accepted=n_accepted,
    )
    return df


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch and parse the iShares IWV (Russell 3000 ETF) holdings export."
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path("/var/tmp/iwv_holdings.csv"),
        help="Local path to write the downloaded holdings file to.",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="Override the holdings export URL (e.g. a fallback source).",
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Skip the download and parse an already-downloaded --dest file.",
    )
    args = parser.parse_args(argv)

    status = "success"
    try:
        if not args.skip_fetch:
            fetch_holdings(args.dest, url=args.url)
        df = parse_holdings(args.dest)
        print(
            f"n_rows_raw={df.attrs.get('n_rows_raw')} "
            f"n_filler_dropped={df.attrs.get('n_filler_dropped')} "
            f"n_rejected={df.attrs.get('n_rejected')} "
            f"n_accepted={df.attrs.get('n_accepted')}"
        )
    except Exception as error:
        status = "failure"
        _logger.error("universe_expansion_fetch_iwv_holdings.failed", error=str(error))
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    finally:
        JOB_COMPLETED_TOTAL.add(
            1, {"job": "universe-expansion-fetch-iwv-holdings", "status": status}
        )
        flush_and_shutdown_metrics()
    return 0


if __name__ == "__main__":
    from src.observability.otel import OTelInitError, init_otel_providers

    try:
        init_otel_providers("universe-expansion-fetch-iwv-holdings")
    except OTelInitError as error:
        print(f"[warn] OTel init failed — metrics disabled: {error}")
    sys.exit(main())
