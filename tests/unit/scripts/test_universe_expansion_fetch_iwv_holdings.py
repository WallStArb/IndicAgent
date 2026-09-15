import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from scripts.infrastructure.universe_expansion_fetch_iwv_holdings import (  # noqa: E402
    EXPECTED_COLUMNS,
    parse_holdings,
)

# The real iShares IWV export prepends 8 lines of fund-level metadata plus one blank
# separator line before the real column header (HEADER_ROW_INDEX = 9). Fixtures below
# reproduce this exact preamble shape so the parser's real-world header-skip logic is
# actually exercised, not a simplified stand-in.
_PREAMBLE = (
    "iShares Russell 3000 ETF\n"
    'Fund Holdings as of,"Sep 11, 2026"\n'
    'Inception Date,"May 22, 2000"\n'
    'Shares Outstanding,"46,750,000.00"\n'
    'Stock,"-"\n'
    'Bond,"-"\n'
    'Cash,"-"\n'
    'Other,"-"\n'
    "\n"
)
_HEADER = ",".join(EXPECTED_COLUMNS) + "\n"


def _row(
    ticker="AAPL",
    name="APPLE",
    sector="Information Technology",
    asset_class="Equity",
    market_value="1,324,110,902.15",
    weight="6.53",
) -> str:
    return (
        f'"{ticker}","{name}","{sector}","{asset_class}","{market_value}","{weight}",'
        f'"{market_value}","1,000.00","100.00","United States","NASDAQ","USD","1.00",'
        '"USD","-"\n'
    )


def _write_fixture(tmp_path: Path, data_rows: list[str], header: str = _HEADER) -> Path:
    content = _PREAMBLE + header + "".join(data_rows)
    fixture_path = tmp_path / "iwv_holdings_fixture.csv"
    fixture_path.write_text(content, encoding="utf-8")
    return fixture_path


def test_parse_holdings_skips_issuer_preamble(tmp_path):
    """The 8-line metadata preamble + blank separator line are skipped correctly."""
    path = _write_fixture(tmp_path, [_row(ticker="NVDA", market_value="1,403,545,761.70")])
    df = parse_holdings(path)
    assert list(df["symbol"]) == ["NVDA"]


def test_parse_holdings_header_mismatch_raises_value_error(tmp_path):
    """A drifted issuer schema fails loud instead of silently half-parsing."""
    bad_header = "Ticker,Name,Sector,Weight (%)\n"  # missing most recorded columns
    path = _write_fixture(tmp_path, [_row()], header=bad_header)
    try:
        parse_holdings(path)
        raise AssertionError("expected ValueError on header mismatch")
    except ValueError as error:
        assert "header mismatch" in str(error).lower()


def test_parse_holdings_drops_and_counts_filler_rows(tmp_path):
    """Non-equity filler rows (futures overlay, cash/margin sleeves) are dropped, not returned."""
    rows = [
        _row(ticker="AAPL"),
        _row(ticker="RTYZ6", name="RUSSELL 2000 EMINI", asset_class="Futures", market_value="0.00"),
        _row(ticker="MSFT"),
        _row(ticker="-", name="CASH", asset_class="Cash", market_value="1,000.00"),
        _row(
            ticker="-",
            name="MARGIN",
            asset_class="Cash Collateral and Margins",
            market_value="500.00",
        ),
        _row(ticker="-", name="MMKT", asset_class="Money Market", market_value="250.00"),
    ]
    path = _write_fixture(tmp_path, rows)
    df = parse_holdings(path)
    assert sorted(df["symbol"]) == ["AAPL", "MSFT"]
    assert df.attrs["n_filler_dropped"] == 4
    assert df.attrs["n_rows_raw"] == 6


def test_parse_holdings_rejects_sql_injection_ticker(tmp_path):
    """A ticker string carrying SQL metacharacters is rejected by the regex, not returned."""
    hostile_ticker = "AAPL'); DROP TABLE instruments;--"
    rows = [
        _row(ticker=hostile_ticker),
        _row(ticker="AAPL"),
    ]
    path = _write_fixture(tmp_path, rows)
    df = parse_holdings(path)
    assert hostile_ticker not in list(df["symbol"])
    assert list(df["symbol"]) == ["AAPL"]
    assert df.attrs["n_rejected"] == 1


def test_parse_holdings_rejects_malformed_negative_and_nan_market_cap(tmp_path):
    """Malformed, negative, and NaN market caps are rejected and counted, never coerced."""
    rows = [
        _row(ticker="AAPL", market_value="1,000.00"),
        _row(ticker="BADCAP", market_value="not-a-number"),
        _row(ticker="NEGCAP", market_value="-500.00"),
        _row(ticker="NANCAP", market_value="NaN"),
        _row(ticker="ZEROCAP", market_value="0.00"),
        _row(ticker="DASHCAP", market_value="-"),
    ]
    path = _write_fixture(tmp_path, rows)
    df = parse_holdings(path)
    assert list(df["symbol"]) == ["AAPL"]
    assert df.attrs["n_rejected"] == 5


def test_parse_holdings_handles_thousands_separators_and_dollar_sign(tmp_path):
    """Thousands separators and $ currency symbols are stripped before float parsing."""
    rows = [
        _row(ticker="NVDA", market_value="$1,403,545,761.70"),
        _row(ticker="AAPL", market_value="1,324,110,902.15"),
    ]
    path = _write_fixture(tmp_path, rows)
    df = parse_holdings(path)
    row = df[df["symbol"] == "NVDA"].iloc[0]
    assert row["market_cap"] == 1_403_545_761.70
    row2 = df[df["symbol"] == "AAPL"].iloc[0]
    assert row2["market_cap"] == 1_324_110_902.15


def test_parse_holdings_returns_exactly_three_contract_columns(tmp_path):
    """The returned frame exposes exactly symbol/name/market_cap -- not the issuer's raw columns."""
    path = _write_fixture(tmp_path, [_row()])
    df = parse_holdings(path)
    assert list(df.columns) == ["symbol", "name", "market_cap"]


def test_parse_holdings_accepts_ticker_with_dot_and_hyphen(tmp_path):
    """Tickers with '.' (share class) or '-' (rights/units) within the bounded regex are accepted."""
    rows = [
        _row(ticker="BRK.B", market_value="1,000.00"),
        _row(ticker="ABC-U", market_value="2,000.00"),
    ]
    path = _write_fixture(tmp_path, rows)
    df = parse_holdings(path)
    assert sorted(df["symbol"]) == ["ABC-U", "BRK.B"]
    assert df.attrs["n_rejected"] == 0


def test_parse_holdings_rejects_lowercase_and_overlong_ticker(tmp_path):
    """Lowercase and over-length tickers (>10 chars) are rejected by the bounded regex."""
    rows = [
        _row(ticker="aapl", market_value="1,000.00"),
        _row(ticker="TOOLONGTICKER", market_value="1,000.00"),
        _row(ticker="MSFT", market_value="1,000.00"),
    ]
    path = _write_fixture(tmp_path, rows)
    df = parse_holdings(path)
    assert list(df["symbol"]) == ["MSFT"]
    assert df.attrs["n_rejected"] == 2


def test_parse_holdings_accepted_count_matches_frame_length(tmp_path):
    """n_accepted in df.attrs always equals the returned frame's row count."""
    rows = [_row(ticker="AAPL"), _row(ticker="MSFT"), _row(ticker="NVDA")]
    path = _write_fixture(tmp_path, rows)
    df = parse_holdings(path)
    assert df.attrs["n_accepted"] == len(df) == 3
