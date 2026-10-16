"""ops_d2_raw_equivalence.py - the daily rule over ohlcv_raw against stored canonical 1d (read-only).

Phase 191 plan 08, the daily rule's balance check (design doc step 6, "each with its own balance
check"; T-191-24). For each symbol it runs the daily stage's own read and rule
(services/bar_derivation.read_daily_inputs and daily_rule.derive_daily_v2, no write) and compares
the produced 1d series with the stored canonical 1d rows of CANONICAL_1D_SOURCES: a whole-series
bar_content_digest over the values with the (vendor, kind) pair as each row's rule set, and, when
the digests differ, every differing date.

Each difference is tagged mechanically:
- rule_only_after_stored_end: a date the rule produces after the symbol's last stored canonical
  date (canonical 1d stops at the cutover until the daily stage runs again);
- rule_only, stored_only: a date only one side holds, inside the stored span;
- value: OHLCV differ; label: values equal, the (vendor, kind) identity differs.

The allow-list (--allowlist, reviewed JSON) explains tags: "classes" maps a tag to a reason for
every symbol, "symbols" maps a symbol to {"tags": [...], "reason": ...}. Exit 0 only when every
symbol is equal or each of its tags is explained; otherwise exit 1 and the report names them.
TEMPORARY: one-shot equivalence check, deleted at plan 191-17.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import numpy as np

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import asyncpg  # noqa: E402

from services._batch_utils import load_apr_dict_async  # noqa: E402
from services.bar_derivation import read_daily_inputs, read_daily_params  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.intelligence.bars.daily_rule import derive_daily_v2  # noqa: E402
from src.intelligence.bars.digest import bar_content_digest  # noqa: E402
from src.intelligence.bars.sources import (  # noqa: E402
    CANONICAL_1D_KINDS,
    CANONICAL_1D_VENDORS,
)

Bar = tuple[float, float, float, float, int | None, str, str]

TAG_AFTER_END = "rule_only_after_stored_end"
TAG_RULE_ONLY = "rule_only"
TAG_STORED_ONLY = "stored_only"
TAG_VALUE = "value"
TAG_LABEL = "label"
_EXAMPLES = 5

# two ANY arrays, not a composite-array parameter: asyncpg cannot bind a list of tuples to a
# (text, text)[] without explicit codecs, and the cross product the pair of arrays admits holds
# no canonical rows (the same pattern services/bar_derivation reads stored 1d with)
_STORED_VENDORS = CANONICAL_1D_VENDORS
_STORED_KINDS = CANONICAL_1D_KINDS

_STORED_SQL = """
SELECT ("timestamp" AT TIME ZONE 'UTC')::date AS bar_date, open, high, low, close, volume,
       vendor, kind
FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = '1d' AND vendor = ANY($2::text[]) AND kind = ANY($3::text[])
"""
_SYMBOLS_SQL = """
SELECT symbol FROM instruments WHERE is_active AND compute_eligible_1d
UNION
SELECT DISTINCT symbol FROM market_data_ohlcv WHERE timeframe = '1d'
ORDER BY 1
"""


def series_digest(series: Mapping[date, Bar]) -> str:
    """bar_content_digest over a whole 1d series; each row's (vendor, kind) is its rule set."""
    days = sorted(series)
    epoch = np.array(
        [int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp()) for d in days],
        dtype=np.int64,
    )

    def column(i: int) -> np.ndarray:
        return np.array([series[d][i] for d in days], dtype=np.float64)

    volume = np.array(
        [np.nan if series[d][4] is None else series[d][4] for d in days], dtype=np.float64
    )
    return bar_content_digest(
        epoch,
        column(0),
        column(1),
        column(2),
        column(3),
        volume,
        [(series[d][5], series[d][6]) for d in days],
    )


@dataclass
class Comparison:
    """One symbol's rule-over-raw series against its stored canonical 1d."""

    symbol: str
    digest_rule: str
    digest_stored: str
    n_rule: int
    n_stored: int
    digest_rule_in_span: str = ""
    tags: dict[str, int] = field(default_factory=dict)
    examples: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    @property
    def equal(self) -> bool:
        return self.error is None and self.digest_rule == self.digest_stored

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "equal": self.equal,
            "digest_rule": self.digest_rule,
            "digest_stored": self.digest_stored,
            "equal_in_span": self.error is None and self.digest_rule_in_span == self.digest_stored,
            "n_rule": self.n_rule,
            "n_stored": self.n_stored,
            "tags": self.tags,
            "examples": self.examples,
            "error": self.error,
        }


def compare(symbol: str, rule: Mapping[date, Bar], stored: Mapping[date, Bar]) -> Comparison:
    """Digest both series; when they differ, tag every differing date (module docstring)."""
    result = Comparison(symbol, series_digest(rule), series_digest(stored), len(rule), len(stored))
    stored_end = max(stored, default=None)
    # The rule's series cut at the last stored date: equal here means canonical holds exactly
    # what the rule over raw produces, only not yet the sessions after the cutover.
    result.digest_rule_in_span = series_digest(
        {d: bar for d, bar in rule.items() if stored_end is not None and d <= stored_end}
    )
    if result.digest_rule == result.digest_stored:
        return result
    for day in sorted(set(rule) | set(stored)):
        new, old = rule.get(day), stored.get(day)
        if new == old:
            continue
        if old is None:
            tag = TAG_AFTER_END if stored_end is None or day > stored_end else TAG_RULE_ONLY
        elif new is None:
            tag = TAG_STORED_ONLY
        elif _values(new) == _values(old):
            tag = TAG_LABEL
        else:
            tag = TAG_VALUE
        result.tags[tag] = result.tags.get(tag, 0) + 1
        if tag != TAG_AFTER_END and len(result.examples) < _EXAMPLES:
            result.examples.append(
                {"date": day.isoformat(), "tag": tag, "rule": new, "stored": old}
            )
    return result


def _values(bar: Bar) -> tuple:
    """OHLCV compared by value (float equality of stored doubles; NULL volume equals NULL)."""
    return tuple(bar[:5])


def unexplained(comparison: Mapping[str, Any], allowlist: Mapping[str, Any]) -> list[str]:
    """The comparison's tags (and error) no allow-list entry explains; empty when equal."""
    if comparison["equal"]:
        return []
    if comparison.get("error"):
        return ["error"]
    by_class = set(allowlist.get("classes", {}))
    by_symbol = set(allowlist.get("symbols", {}).get(comparison["symbol"], {}).get("tags", []))
    return sorted(tag for tag in comparison["tags"] if tag not in by_class | by_symbol)


async def compare_symbol(conn: Any, symbol: str, params: Any) -> Comparison:
    stored: dict[date, Bar] = {
        r["bar_date"]: (
            r["open"],
            r["high"],
            r["low"],
            r["close"],
            r["volume"],
            r["vendor"],
            r["kind"],
        )
        for r in await conn.fetch(_STORED_SQL, symbol, list(_STORED_VENDORS), list(_STORED_KINDS))
    }
    try:
        observations, splits = await read_daily_inputs(conn, symbol)
        derived = derive_daily_v2(
            observations,
            params.policy,
            splits,
            symbol=symbol,
            basis_window_sessions=params.window,
            basis_tolerance_bp=params.tolerance_bp,
        )
    except Exception as error:  # a rule failure is a reported difference, never a crash
        result = Comparison(symbol, "", series_digest(stored), 0, len(stored))
        result.error = f"{type(error).__name__}: {error}"
        return result
    rule: dict[date, Bar] = {
        b.bar_date: (b.open, b.high, b.low, b.close, b.volume, b.vendor, b.kind)
        for b in derived.bars
    }
    return compare(symbol, rule, stored)


async def run(args: argparse.Namespace) -> int:
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    out = Path(args.out)
    done: dict[str, dict[str, Any]] = {}
    if out.exists() and not args.fresh:
        for line in out.read_text().splitlines():
            row = json.loads(line)
            done[row["symbol"]] = row
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=args.concurrency)
    try:
        async with pool.acquire() as conn:
            apr = await load_apr_dict_async(
                conn,
                ["infra.bar_derivation.%", "threshold.bar_integrity.%", "threshold.bar_scrub.%"],
            )
            params = await read_daily_params(conn, apr)
            symbols = args.symbols or [r[0] for r in await conn.fetch(_SYMBOLS_SQL)]
        todo = [s for s in symbols if s not in done]
        gate = asyncio.Semaphore(args.concurrency)
        lock = asyncio.Lock()
        with out.open("w" if args.fresh else "a") as handle:

            async def one(symbol: str) -> None:
                async with gate, pool.acquire() as conn:
                    row = (await compare_symbol(conn, symbol, params)).as_dict()
                async with lock:
                    handle.write(json.dumps(row, default=str) + "\n")
                    handle.flush()
                    done[symbol] = row
                    if len(done) % 100 == 0:
                        print(f"{len(done)}/{len(symbols)} done", flush=True)

            await asyncio.gather(*(one(s) for s in todo))
    finally:
        await pool.close()
    return report([done[s] for s in symbols], args.allowlist)


def report(rows: list[dict[str, Any]], allowlist_path: str | None) -> int:
    allowlist = json.loads(Path(allowlist_path).read_text()) if allowlist_path else {}
    totals: dict[str, int] = {}
    failing: dict[str, list[str]] = {}
    for row in rows:
        for tag, n in row["tags"].items():
            totals[tag] = totals.get(tag, 0) + n
        missing = unexplained(row, allowlist)
        if missing:
            failing[row["symbol"]] = missing
    n_equal = sum(row["equal"] for row in rows)
    print(
        json.dumps(
            {
                "symbols": len(rows),
                "equal": n_equal,
                "equal_in_span": sum(bool(row.get("equal_in_span")) for row in rows),
                "differing": len(rows) - n_equal,
                "errors": sum(bool(row.get("error")) for row in rows),
                "date_tags": totals,
                "symbols_by_tag": {
                    tag: sum(1 for row in rows if tag in row["tags"]) for tag in sorted(totals)
                },
                "unexplained": failing,
            },
            indent=2,
        )
    )
    return 1 if failing else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--all", action="store_true", help="every active 1d name and every name with canonical 1d"
    )
    scope.add_argument("--symbols", nargs="+", help="these symbols only")
    parser.add_argument("--allowlist", default=None, help="reviewed explained-differences JSON")
    parser.add_argument(
        "--out",
        default=str(project_root / "logs" / "d2_raw_equivalence.jsonl"),
        help="per-symbol JSONL results; an existing file resumes (skips done symbols)",
    )
    parser.add_argument("--fresh", action="store_true", help="ignore an existing --out file")
    parser.add_argument("--concurrency", type=int, default=6)
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
