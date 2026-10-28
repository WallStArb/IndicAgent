"""ops_d191q_arbitration.py - the D-191-Q three-vendor 1d arbitration, read-only (todo 545).

Where Alpaca SIP and IBKR disagree on a 1d close from 2016-01-04, Tradier decides which one is
right (src/intelligence/bars/vendor_arbitration.py). This captures that evidence once, before
plan 191-20 deletes Tradier, so the script refuses to run when no Tradier 1d raw row exists.

Per name (every name with Alpaca 1d raw rows, plus every name holding a live 1d symbol row): the
daily stage's own inputs (services.bar_derivation.read_daily_inputs, session dates per vendor),
each vendor's current-scale close per session (daily_rule.vendor_basis_closes, zero-volume Alpaca
bars dropped), and IBKR's verified 1d head (ohlcv_provider_head). The window is 2016-01-04 to
Tradier's last 1d session. Thresholds are APR: fallback_basis_tolerance_bp,
fallback_basis_window_sessions (the span minimum: a basis difference is a level held over the
basis window, the head seam test's length) and tradier_admission_min_agree_share. The first full
run with D7's vendor_ratio_run_min_sessions (5) wrote 64 IBKR rows of 5 to 16 sessions at 0.2 to
111 bp (close-definition episodes on thin ETFs, SPY and IWM in March 2020) beside 65 genuine basis
spans of 62 or more sessions; the basis window separates them.

Writes two files and nothing to the database (the session is read-only):
- the policy plan, the exact document `ops_source_policy.py --plan` takes (default under
  data/policy_plans/, gitignored);
- the evidence report (markdown): classes, the IBKR symbol rows (holds as interim rows), the hold
  list, the quarantine list, the IBKR-defective spans, the disposition of every live 1d symbol
  row, the plan's sha256, the pinned default ids and the raw fingerprint. The fingerprint is
  read before and after the names; a change in between refuses the run (exit 3).

Usage: python -m scripts.ops.bars.ops_d191q_arbitration [--plan-out PATH] [--report PATH]
       [--symbols A,B]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import asyncpg  # noqa: E402

from scripts.ops.bars.ops_source_policy import read_raw_fingerprint  # noqa: E402
from services._batch_utils import cfg as _cfg  # noqa: E402
from services.bar_derivation import read_daily_inputs  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.intelligence.bars.daily_rule import (  # noqa: E402
    VENDOR_ALPACA,
    VENDOR_IBKR,
    VENDOR_TRADIER,
    vendor_basis_closes,
)
from src.intelligence.bars.sessions import nyse_sessions  # noqa: E402
from src.intelligence.bars.vendor_arbitration import (  # noqa: E402
    SEAM,
    ArbitrationParams,
    LiveSymbolRow,
    NameArbitration,
    arbitrate,
    build_plan,
)

_KEY_TOL = "threshold.bar_integrity.fallback_basis_tolerance_bp"
_KEY_RUN = "threshold.bar_integrity.fallback_basis_window_sessions"
_KEY_SHARE = "threshold.bar_integrity.tradier_admission_min_agree_share"
_KEY_QUARANTINE = "threshold.bar_scrub.view_disagreement_rel"
# Fallbacks equal to the seeded APR values; the run reads APR.
_DEFAULT_TOL = 10.0
_DEFAULT_RUN = 20
_DEFAULT_SHARE = 0.9
_DEFAULT_QUARANTINE = 0.02
_PROGRESS_EVERY = 100

_READ_ONLY_SQL = "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"
_TRADIER_LAST_SQL = """
SELECT max(("timestamp" AT TIME ZONE 'UTC')::date) FROM ohlcv_raw
WHERE vendor = 'tradier' AND kind = 'consolidated' AND timeframe = '1d'
"""
_ALPACA_NAMES_SQL = """
SELECT DISTINCT symbol FROM ohlcv_raw
WHERE vendor = 'alpaca' AND kind = 'sip_rth' AND timeframe = '1d'
"""
_VERIFIED_HEADS_SQL = """
SELECT symbol, (head_ts AT TIME ZONE 'UTC')::date AS head FROM ohlcv_provider_head
WHERE provider = 'ibkr' AND timeframe = '1d' AND head_kind = 'verified'
"""
_LIVE_DEFAULT_IDS_SQL = """
SELECT policy_id::text AS policy_id FROM bar_source_policy_current
WHERE timeframe = '1d' AND symbol IS NULL
"""
_LIVE_SYMBOL_ROWS_SQL = """
SELECT policy_id::text AS policy_id, symbol, valid_from, valid_to, primary_source, fallback_source
FROM bar_source_policy_current
WHERE timeframe = '1d' AND symbol IS NOT NULL
"""


def default_paths(now: datetime) -> tuple[Path, Path]:
    stamp = now.strftime("%Y%m%d")
    return (
        project_root / "data" / "policy_plans" / f"d191q_1d_plan_{stamp}.json",
        project_root
        / ".planning"
        / "phases"
        / "191-unified-raw-bar-table"
        / "191-D191Q-ARBITRATION.md",
    )


async def run(
    conn: Any,
    *,
    plan_path: Path,
    report_path: Path,
    symbols: Sequence[str] | None = None,
    now: datetime | None = None,
) -> int:
    """The arbitration over one read-only session; 2 when Tradier's rows are gone."""
    now = now or datetime.now(UTC)
    await conn.execute(_READ_ONLY_SQL)
    window_end = await conn.fetchval(_TRADIER_LAST_SQL)
    if window_end is None:
        print(
            "refused: no Tradier 1d raw rows; the arbitration exists to capture them before "
            "plan 191-20 deletes them",
            file=sys.stderr,
        )
        return 2
    apr = {
        r["config_key"]: r["config_value"]
        for r in await conn.fetch(
            "SELECT config_key, config_value FROM config_state WHERE config_key = ANY($1::text[])",
            [_KEY_TOL, _KEY_RUN, _KEY_SHARE, _KEY_QUARANTINE],
        )
    }
    params = ArbitrationParams(
        window_start=SEAM,
        window_end=window_end,
        tolerance_bp=float(_cfg(apr, _KEY_TOL, _DEFAULT_TOL)),
        min_sessions=int(_cfg(apr, _KEY_RUN, _DEFAULT_RUN)),
        min_class_share=float(_cfg(apr, _KEY_SHARE, _DEFAULT_SHARE)),
        quarantine_rel=float(_cfg(apr, _KEY_QUARANTINE, _DEFAULT_QUARANTINE)),
    )
    fingerprint = await read_raw_fingerprint(conn, window_end)
    default_ids = sorted(r["policy_id"] for r in await conn.fetch(_LIVE_DEFAULT_IDS_SQL))
    calendar = sorted(nyse_sessions(SEAM, now.date()))
    heads = {r["symbol"]: r["head"] for r in await conn.fetch(_VERIFIED_HEADS_SQL)}
    live = [
        LiveSymbolRow(
            r["policy_id"],
            r["symbol"],
            r["valid_from"],
            r["valid_to"],
            r["primary_source"],
            r["fallback_source"],
        )
        for r in await conn.fetch(_LIVE_SYMBOL_ROWS_SQL)
    ]
    names = sorted(
        set(symbols)
        if symbols
        else {r["symbol"] for r in await conn.fetch(_ALPACA_NAMES_SQL)} | {r.symbol for r in live}
    )
    results: list[NameArbitration] = []
    for i, symbol in enumerate(names, 1):
        observations, splits = await read_daily_inputs(conn, symbol)
        closes = vendor_basis_closes(observations, splits)
        results.append(
            arbitrate(
                symbol,
                closes[VENDOR_ALPACA],
                closes[VENDOR_IBKR],
                closes[VENDOR_TRADIER],
                params,
                sessions=calendar,
                ibkr_head_verified=heads.get(symbol),
            )
        )
        if i % _PROGRESS_EVERY == 0:
            print(f"arbitration: {i}/{len(names)}", file=sys.stderr, flush=True)
    evidence = {
        "run_at": now.isoformat(),
        "script": "scripts/ops/bars/ops_d191q_arbitration.py",
        "plan_path": str(plan_path),
    }
    if symbols:
        live = [r for r in live if r.symbol in set(symbols)]
        evidence["symbols"] = sorted(symbols)
    if await read_raw_fingerprint(conn, window_end) != fingerprint:
        print(
            "refused: the 1d raw rows changed while the arbitration read them; run it again",
            file=sys.stderr,
        )
        return 3
    plan = build_plan(
        results,
        live,
        params,
        evidence=evidence,
        live_default_ids=default_ids,
        raw_fingerprint=fingerprint,
    )
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(plan, indent=1, sort_keys=True)
    plan_path.write_text(text)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(plan, plan_path, hashlib.sha256(text.encode()).hexdigest())
    )
    print(json.dumps(plan["evidence"]["span_actions"]))
    return 0


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.4f}"


def _ratio(num: float | None, den: float | None) -> float | None:
    return None if num is None or not den else num / den


def render_report(plan: dict[str, Any], plan_path: Path, plan_sha256: str) -> str:
    """The owner-facing evidence record of one arbitration run, rendered from the plan alone."""
    ev = plan["evidence"]
    prm = ev["params"]
    out = [
        "# D-191-Q three-vendor 1d arbitration (todo 545)",
        "",
        "Author: scripts/ops/bars/ops_d191q_arbitration.py (read-only session). Informed by: "
        "D-191-Q in docs/plans/2026-10-12-unified-raw-bar-table-design.md, todo 545.",
        "",
        f"Run {ev['run_at']}. Window {prm['window_start']} to {prm['window_end']} (Tradier's last "
        f"1d session). Tolerance {prm['tolerance_bp']} bp per session, a span of at least "
        f"{prm['min_sessions']} sessions, a class share of at least {prm['min_class_share']}. "
        f"{ev['n_names']} names. Plan: `{plan_path}` (gitignored), sha256 `{plan_sha256}`, the "
        "document `ops_source_policy.py --plan` takes; nothing was written to the database. "
        f"Raw fingerprint through {plan['raw_fingerprint']['through']}: "
        + ", ".join(
            f"{k} {v['rows']:,} rows, last served {v['max_served_at']}"
            for k, v in plan["raw_fingerprint"]["series"].items()
        )
        + f". Retired defaults pinned: {', '.join(plan['retire_default_ids'])}.",
        "",
        "## Classes",
        "",
        "| Class | Action | Spans | Sessions | Names |",
        "|-------|--------|-------|----------|-------|",
        *[
            f"| {c['class']} | {c['action']} | {c['spans']} | {c['sessions']:,} | {c['names']} |"
            for c in ev["classes"]
        ],
        "",
        "Actions: row = an IBKR symbol row (IBKR = Tradier and Alpaca differs; a three-way span "
        "where IBKR and Tradier both adjusted; Alpaca history discontinuous with IBKR's first bar, "
        "no bar until it); evidence = IBKR is wrong and Alpaca serves (Alpaca = Tradier); hold = "
        "an interim IBKR row for the owner to decide (Alpaca does not serve); noise = shorter than "
        "the span minimum (Alpaca serves, quarantine below); info = Alpaca history continuous "
        "with IBKR's first bar (Alpaca serves).",
        "",
        f"## IBKR symbol rows ({len(plan['symbol_rows'])})",
        "",
        "Interim rows are the holds: IBKR serves until the owner decides.",
        "",
        "| Symbol | Class | Interim | From | To (excl.) | Sessions | IBKR/Alpaca | Tradier/Alpaca |",
        "|--------|-------|---------|------|------------|----------|-------------|----------------|",
    ]
    for row in plan["symbol_rows"]:
        e = row["evidence"]
        out.append(
            f"| {row['symbol']} | {e['class']} | {'yes' if e['interim'] else ''} | "
            f"{row['valid_from']} | {row['valid_to']} | {e['n_sessions']} | "
            f"{_fmt(e['median_ibkr_over_alpaca'])} | {_fmt(e['median_tradier_over_alpaca'])} |"
        )
    out += [
        "",
        f"## Hold list ({len(plan['hold'])})",
        "",
        "IBKR/Tradier is the ratio of the two medians: near 1 on a three_way span means IBKR and "
        "Tradier both adjusted the history (a spin-off) with factors a few bp apart, so the "
        "per-session test could not call it alpaca_differs.",
        "",
        "| Symbol | Class | From | To | Sessions | With Tradier | IBKR/Alpaca | Tradier/Alpaca "
        "| IBKR/Tradier |",
        "|--------|-------|------|----|----------|--------------|-------------|----------------"
        "|--------------|",
    ]
    for h in sorted(plan["hold"], key=lambda h: (h["class"], -h["n_sessions"])):
        out.append(
            f"| {h['symbol']} | {h['class']} | {h['start']} | {h['end']} | {h['n_sessions']} | "
            f"{h['n_tradier']} | {_fmt(h['median_ibkr_over_alpaca'])} | "
            f"{_fmt(h['median_tradier_over_alpaca'])} | "
            f"{_fmt(_ratio(h['median_ibkr_over_alpaca'], h['median_tradier_over_alpaca']))} |"
        )
    out += [
        "",
        f"## Quarantine ({len(plan['quarantine'])} sessions, rule `{plan['quarantine_rule']}`)",
        "",
        "Short spans where IBKR equals Tradier and Alpaca's close is more than the view "
        "disagreement threshold off: each session is a quarantine flag the apply writes through "
        "the flag writer (the rule must be in threshold.bar_scrub.quarantine_rules first).",
        "",
        "| Symbol | Session | Alpaca | IBKR | Tradier |",
        "|--------|---------|--------|------|---------|",
        *[
            f"| {q['symbol']} | {q['session']} | {q['alpaca']} | {q['ibkr']} | {q['tradier']} |"
            for q in plan["quarantine"]
        ],
    ]
    defective: Counter[str] = Counter()
    for d in plan["ibkr_defective"]:
        defective[d["symbol"]] += d["n_sessions"]
    out += [
        "",
        f"## IBKR-defective spans ({len(plan['ibkr_defective'])} spans, {len(defective)} names, "
        f"{sum(defective.values()):,} sessions)",
        "",
        "Alpaca agrees with Tradier and IBKR does not: Alpaca serves under the default, no row. "
        "Largest names by sessions:",
        "",
        "| Symbol | Sessions |",
        "|--------|----------|",
        *[f"| {s} | {n} |" for s, n in defective.most_common(30)],
        "",
        f"## Live symbol rows ({len(plan['retire_symbol_rows']) + len(plan['keep_symbol_rows'])})",
        "",
        "Retired: "
        + ", ".join(
            f"{k} {v}"
            for k, v in sorted(
                Counter(r["disposition"] for r in plan["retire_symbol_rows"]).items()
            )
        )
        + f". Kept: {len(plan['keep_symbol_rows'])}.",
        "",
        "| Symbol | Kept because |",
        "|--------|--------------|",
        *[f"| {k['symbol']} | {k['reason']} |" for k in plan["keep_symbol_rows"]],
        "",
    ]
    return "\n".join(out)


async def _main(args: argparse.Namespace) -> int:
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    plan_default, report_default = default_paths(datetime.now(UTC))
    conn = await asyncpg.connect(dsn)
    try:
        return await run(
            conn,
            plan_path=Path(args.plan_out) if args.plan_out else plan_default,
            report_path=Path(args.report) if args.report else report_default,
            symbols=[s for s in (args.symbols or "").split(",") if s] or None,
        )
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan-out", default=None)
    parser.add_argument("--report", default=None)
    parser.add_argument("--symbols", default=None, help="comma-separated subset (a trial run)")
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
