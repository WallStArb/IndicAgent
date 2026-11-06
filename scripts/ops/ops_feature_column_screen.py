"""Gate the stored feature columns of feature_vectors per timeframe and name (todo 564 done-when
3; todo 584 design D3, gates G1-G3). A column that carries no information, starts far later than
its declared memory, or is mostly an exact 0.0 fill reads as real to the S0 read; the gates name
it when it appears in a stage's output or in a pilot chunk before a full pass.

Screened columns are the registry's numeric feature columns (`feature_vectors_numeric_columns`).
Per (tf, name) and column:
- G1 dead: all NULL, no finite value (all NaN or infinite), or one value across its finite rows
  (NaN warmup and infinities do not make a constant column live), outside the registry's declared
  applicable outputs for the timeframe. The control canary_constant must hold its declared value on
  every row.
- G2 warmup gap: the first finite row index minus the declared `feature_memory_bars`, above
  `threshold.pilot_gate.warmup_gap_bars`. Columns with no finite memory (path dependent: the HMM
  regime outputs) have no declared memory and are covered by G1 only.
- G3 fill audit: the exact-0.0 share of finite post-warmup rows, above
  `threshold.pilot_gate.zero_share_max`, for a column outside the kernels' `zero_is_state` set.
A name with no more rows than a column's declared memory is not judged on that column (empty is
expected). Names with fewer than --min-name-rows rows on a timeframe are not judged at all.

The screen is one pass grouped by (tf, symbol): per column the non-null and finite counts, the
first finite row number, finite min and max, and the zero and finite counts after warmup. The row
number is a window over a Merge Append of the chunks' primary-key indexes (EXPLAIN-checked, no sort
of the wide rows). It runs serially, in one snapshot, with no statement timeout. --tf, --symbol and
--pilot filters are served by the primary key (symbol, tf, bar_ts); with none of them the pass
reads the whole hypertable, so run that after the rebuild stops writing. --pilot reads the name
list from the APR key `infra.pilot_gate.names` (JSON list).

Run: .venv/bin/python scripts/ops/ops_feature_column_screen.py [--pilot | --symbol SPY ...]
     [--tf 1d ...] [--min-rows 1000] [--min-name-rows 252]
Output: a JSON report under logs/ and the gate counts on stdout. Exit 0 when every gate passes,
1 when any gate fails, 2 when nothing was screened or a requested --tf was missing or below
--min-rows, so the completion record can gate on it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from itertools import batched
from pathlib import Path

import psycopg
from psycopg import IsolationLevel, sql

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from services._batch_utils import get_list_config, load_config_service_sync  # noqa: E402
from services.backfill_feature_factory import _build_feature_factory_config  # noqa: E402
from services.corpus_rerun_apr import MAX_NULL_FRACTION_KEY  # noqa: E402
from src.config.settings import get_settings  # noqa: E402
from src.intelligence.features.contract.registry import (  # noqa: E402
    default_registry,
    feature_memory_bars,
)
from src.intelligence.features.feature_vector_persistence import (  # noqa: E402
    feature_vectors_numeric_columns,
)
from src.intelligence.features.kernels.control import _CANARY_CONSTANT_VALUE  # noqa: E402

DECLARED_CONSTANTS = {"canary_constant": _CANARY_CONSTANT_VALUE}
REPORT_DIR = project_root / "logs"
# per column: non-null count, finite count, first finite row number, finite min, finite max,
# exact-0.0 rows after warmup, finite rows after warmup
STATS_PER_COLUMN = 7
COLUMNS_PER_PASS = 230  # 7 x 230 + 3 stays under Postgres's 1,664-entry target-list cap
GATES = ("G1", "G2", "G3")
NULL_GATE = "G6"
WARMUP_GAP_KEY = "threshold.pilot_gate.warmup_gap_bars"
ZERO_SHARE_KEY = "threshold.pilot_gate.zero_share_max"
PILOT_NAMES_KEY = "infra.pilot_gate.names"
# Every APR key the screen reads (the corpus rerun pins their values, 186-31).
APR_KEYS: tuple[str, ...] = (WARMUP_GAP_KEY, ZERO_SHARE_KEY, PILOT_NAMES_KEY, MAX_NULL_FRACTION_KEY)
# G6 tiers carried from the deleted corpus verifier (todo 584 4b-2 group 4, D1 rule 2): these
# columns are None wherever their object does not exist (no intraday session on 1d for the
# session volume profile pair; no qualifying support or resistance cluster in the window), so
# the share gate would fail honest data. They fail G6 only when entirely NULL on a tf where the
# object can exist, and are skipped on the tfs listed (structurally absent there).
ABSENCE_EXEMPT_TFS: dict[str, frozenset[str]] = {
    "poc_dist_atr": frozenset({"1d"}),
    "va_position": frozenset({"1d"}),
    "sr_support_dist": frozenset(),
    "sr_resist_dist": frozenset(),
}
EXAMPLES = 20  # names listed per failing column in the report; counts are always complete


def classify(non_null: int, finite: int, low: float | None, high: float | None) -> str | None:
    """Name why a column is dead on one name, or None when it carries information."""
    if non_null == 0:
        return "all_null"
    if finite == 0:
        return "no_finite"
    if low == high:
        return "constant"
    return None


def judge(column: str, non_null: int, finite: int, low, high) -> str | None:
    """classify(), except a declared constant must hold its value on every row: it is named
    when any row is NaN or infinite or differs."""
    why = classify(non_null, finite, low, high)
    if column not in DECLARED_CONSTANTS or why in ("all_null", "no_finite"):
        return why
    held = non_null == finite and low == high == DECLARED_CONSTANTS[column]
    return (
        None if held else f"not_declared_constant ({low}..{high}, {non_null - finite} non-finite)"
    )


def applicable_columns(registry, columns: tuple[str, ...], tf: str) -> frozenset[str]:
    """The columns the registry declares meaningful on `tf`. Until the registry carries the
    declaration every column is applicable, so every dead column fails G1."""
    # TODO(584 D1): `KernelRegistry.applicable_outputs(tf)` lands with design D1 (item 2).
    declared = getattr(registry, "applicable_outputs", None)
    return frozenset(columns) if declared is None else frozenset(declared(tf)) & frozenset(columns)


def zero_is_state(registry) -> frozenset[str]:
    """Outputs where 0.0 is a measured state (G3 skips them).

    Declared per kernel since todo 584 item 4c; pinned registry-wide by
    tests/unit/intelligence/test_kernel_no_object_contract.py.
    """
    return frozenset(o for k in registry.kernels for o in k.zero_is_state)


def declared_memory(registry, config, columns: tuple[str, ...]) -> dict[str, int | None]:
    """Declared memory in bars per column; None only where the kernel is path dependent (no
    finite memory). A column no kernel produces raises, so a registry and schema mismatch is loud.
    """
    return {
        column: (
            None
            if registry.is_path_dependent(column)
            else feature_memory_bars(column, config, registry)
        )
        for column in columns
    }


def _failing(by_column: dict[str, list[str]]) -> dict[str, dict]:
    """Per failing column: the count of names and a few examples."""
    return {
        c: {"n_names": len(v), "examples": sorted(v)[:EXAMPLES]}
        for c, v in sorted(by_column.items())
    }


def registry_declarations(registry) -> dict[str, bool]:
    """Whether the registry carries the D1 declarations G1 and G3 need."""
    return {
        "applicable_outputs": hasattr(registry, "applicable_outputs"),
        "zero_is_state": any(hasattr(k, "zero_is_state") for k in registry.kernels),
    }


def screen_rows(
    columns: tuple[str, ...],
    rows: list[tuple],
    *,
    memory: dict[str, int | None],
    applicable: dict[str, frozenset[str]],
    zero_state: frozenset[str],
    min_rows: int,
    min_name_rows: int,
    warmup_gap_max: int,
    zero_share_max: float,
) -> tuple[dict[str, dict], dict[str, int]]:
    """Per-timeframe gate report from the per-(tf, symbol) rows (tf, symbol, row count, then
    STATS_PER_COLUMN per column), and the timeframes skipped below min_rows."""
    by_tf: dict[str, list[tuple]] = defaultdict(list)
    for tf, symbol, n_rows, *stats in rows:
        by_tf[tf].append((symbol, n_rows, stats))
    report: dict[str, dict] = {}
    skipped: dict[str, int] = {}
    for tf, names in sorted(by_tf.items()):
        n_rows = sum(n for _, n, _ in names)
        if n_rows < min_rows:
            skipped[tf] = n_rows
            continue
        judged = [(symbol, n, stats) for symbol, n, stats in names if n >= min_name_rows]
        reasons: dict[str, Counter] = defaultdict(Counter)
        judged_for: Counter = Counter()  # names a column was judged on (history above its memory)
        fails: dict[str, dict[str, list[str]]] = {g: defaultdict(list) for g in GATES}
        for symbol, n, stats in judged:
            per_column = batched(stats, STATS_PER_COLUMN, strict=True)
            for column, (non_null, finite, first_rn, low, high, zeros, finite_post) in zip(
                columns, per_column, strict=True
            ):
                mem = memory[column]
                if mem is not None and n <= mem:
                    continue  # history shorter than the declared memory: empty is expected
                judged_for[column] += 1
                why = judge(column, non_null, finite, low, high)
                if why:
                    reasons[column][why] += 1
                    if column in applicable[tf]:
                        fails["G1"][column].append(symbol)
                    continue
                if mem is not None and first_rn - 1 - mem > warmup_gap_max:
                    fails["G2"][column].append(symbol)
                if (
                    column not in zero_state
                    and finite_post
                    and zeros / finite_post > zero_share_max
                ):
                    fails["G3"][column].append(symbol)
        dead = {c: dict(r) for c, r in reasons.items() if r.total() == judged_for[c]}

        report[tf] = {
            "n_rows": n_rows,
            "n_names": len(names),
            "n_names_judged": len(judged),
            "unjudged_names": sorted(symbol for symbol, n, _ in names if n < min_name_rows),
            "dead": dict(sorted(dead.items())),
            "partial": {c: dict(r) for c, r in sorted(reasons.items()) if c not in dead},
            **{gate: _failing(fails[gate]) for gate in GATES},
        }
    return report, skipped


def null_share_gate(
    columns: tuple[str, ...],
    rows: list[tuple],
    *,
    memory: dict[str, int | None],
    applicable: dict[str, frozenset[str]],
    max_null_fraction: float,
    min_name_rows: int,
    worst: int = EXAMPLES,
) -> dict[str, dict]:
    """G6 per tf: the NULL or non-finite share of each applicable column, pooled over the
    judged names. A column with a declared memory is measured over the rows past it; a column
    without one (path dependent: the HMM outputs, adx, hurst and the session and weekly levels)
    from each name's first finite row, so a hole anywhere after its warmup counts and a name
    with no finite row counts every row. No applicable column goes unmeasured: one with judged
    names but no measurable row fails. Returns, per tf, the failing columns with their reason
    and the worst shares whatever their verdict."""
    measured: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])  # [rows, finite]
    judged_tfs: set[str] = set()
    for tf, _symbol, n, *stats in rows:
        if n < min_name_rows:
            continue
        judged_tfs.add(tf)
        for column, cell in zip(columns, batched(stats, STATS_PER_COLUMN, strict=True)):
            _non_null, finite, first_rn, *_rest, finite_post = cell
            mem = memory[column]
            if mem is None:
                span = n if first_rn is None else n - first_rn + 1
                measured[(tf, column)][0] += span
                measured[(tf, column)][1] += finite
            elif n > mem:
                measured[(tf, column)][0] += n - mem
                measured[(tf, column)][1] += finite_post
    out: dict[str, dict] = {}
    for tf in sorted({tf for tf, *_ in rows}):
        shares: dict[str, float] = {}
        failing: dict[str, str] = {}
        for column in columns:
            if column not in applicable[tf] or tf in ABSENCE_EXEMPT_TFS.get(column, ()):
                continue
            total, finite = measured.get((tf, column), (0, 0))
            if not total:
                if tf in judged_tfs:
                    failing[column] = "cannot be measured: no judged name has a row past its warmup"
                continue
            share = 1 - finite / total
            shares[column] = round(share, 6)
            if column in ABSENCE_EXEMPT_TFS:
                if finite == 0:
                    failing[column] = "entirely NULL where the object can exist (D1 rule 2)"
            elif share > max_null_fraction:
                failing[column] = f"null share {share:.1%} > {max_null_fraction:.1%}"
        out[tf] = {
            "max_null_fraction": max_null_fraction,
            "failing": failing,
            "worst": dict(sorted(shares.items(), key=lambda kv: -kv[1])[:worst]),
        }
    return out


def gate_failures(report: dict[str, dict]) -> dict[str, int]:
    """Failing (column, name) cells per gate over every timeframe."""
    return {
        gate: sum(v["n_names"] for r in report.values() for v in r[gate].values()) for gate in GATES
    }


def apr_value(cfg, key: str):
    """An APR value; a missing key raises (no copy of the seed lives in this script)."""
    value = cfg.get_sync(key, None)
    if value is None:
        raise KeyError(f"APR key {key!r} is missing; migration 557 seeds it")
    return value


def _query(
    columns: tuple[str, ...], memory: dict[str, int | None], where: sql.Composable
) -> sql.Composed:
    def aggregates(c: str) -> sql.Composed:
        finite = "{c} > '-Infinity' AND {c} < 'Infinity'"  # NaN sorts above Infinity: excluded
        return sql.SQL(
            f"count({{c}}), count(*) FILTER (WHERE {finite}), min(rn) FILTER (WHERE {finite}), "
            f"min({{c}}) FILTER (WHERE {finite}), max({{c}}) FILTER (WHERE {finite}), "
            f"count(*) FILTER (WHERE {{c}} = 0 AND rn > {{m}}), "
            f"count(*) FILTER (WHERE {finite} AND rn > {{m}})"
        ).format(c=sql.Identifier(c), m=sql.Literal(memory[c] or 0))

    return sql.SQL(
        "SELECT tf, symbol, count(*), {aggs} FROM ("
        "SELECT tf, symbol, row_number() OVER (PARTITION BY symbol, tf ORDER BY bar_ts) AS rn, {cols}"
        " FROM feature_vectors{where}) t GROUP BY tf, symbol ORDER BY tf, symbol"
    ).format(
        aggs=sql.SQL(", ").join(aggregates(c) for c in columns),
        cols=sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        where=where,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-rows", type=int, default=1000, help="skip timeframes with fewer rows"
    )
    parser.add_argument(
        "--min-name-rows",
        type=int,
        default=252,
        help="do not judge a name with fewer rows on a timeframe",
    )
    parser.add_argument("--tf", action="append", help="restrict to these timeframes")
    parser.add_argument("--symbol", action="append", help="restrict to these symbols")
    parser.add_argument("--pilot", action="store_true", help="the APR pilot name list")
    parser.add_argument(
        "--null-gate",
        action="store_true",
        help=f"also gate G6, the post-warmup NULL share per (tf, column), at {MAX_NULL_FRACTION_KEY}",
    )
    args = parser.parse_args(argv)
    if args.pilot and args.symbol:
        parser.error("--pilot and --symbol both name the symbols; give one")

    columns = feature_vectors_numeric_columns()
    registry = default_registry()
    with psycopg.connect(get_settings().database_url) as conn:
        cfg = load_config_service_sync(conn)
        warmup_gap_max = int(apr_value(cfg, WARMUP_GAP_KEY))
        zero_share_max = float(apr_value(cfg, ZERO_SHARE_KEY))
        max_null = float(apr_value(cfg, MAX_NULL_FRACTION_KEY)) if args.null_gate else None
        if args.pilot:
            args.symbol = get_list_config(cfg, PILOT_NAMES_KEY, [])
            if not args.symbol:
                parser.error("APR key infra.pilot_gate.names is empty")
        memory = declared_memory(registry, _build_feature_factory_config(cfg), columns)
        filters, params = [], []
        for key, values in (("tf", args.tf), ("symbol", args.symbol)):
            if values:
                filters.append(sql.SQL("{} = ANY(%s)").format(sql.Identifier(key)))
                params.append(values)
        where = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(filters) if filters else sql.SQL("")

        rows_by_key: dict[tuple[str, str], list] = {}
        conn.commit()  # the APR reads opened a transaction; the isolation level needs none
        conn.isolation_level = IsolationLevel.REPEATABLE_READ  # one snapshot for every pass
        conn.execute("SET max_parallel_workers_per_gather = 0")
        conn.execute("SET statement_timeout = 0")
        for part in batched(columns, COLUMNS_PER_PASS, strict=False):
            for tf, symbol, n_rows, *stats in conn.execute(_query(part, memory, where), params):
                rows_by_key.setdefault((tf, symbol), [tf, symbol, n_rows]).extend(stats)
    timeframes = {tf for tf, _ in rows_by_key}
    report, skipped = screen_rows(
        columns,
        list(rows_by_key.values()),
        memory=memory,
        applicable={tf: applicable_columns(registry, columns, tf) for tf in timeframes},
        zero_state=zero_is_state(registry),
        min_rows=args.min_rows,
        min_name_rows=args.min_name_rows,
        warmup_gap_max=warmup_gap_max,
        zero_share_max=zero_share_max,
    )

    for tf, n_rows in skipped.items():
        print(f"{tf}: {n_rows} rows, skipped (below --min-rows {args.min_rows})")
    for tf, entry in report.items():
        print(
            f"{tf}: {entry['n_rows']} rows, {entry['n_names_judged']} of {entry['n_names']} names "
            f"judged; dead on every name: {len(entry['dead'])}, on some: {len(entry['partial'])}; "
            f"failing columns G1 {len(entry['G1'])}, G2 {len(entry['G2'])}, G3 {len(entry['G3'])}"
        )
    failures = gate_failures(report)
    nulls: dict[str, dict] = {}
    if max_null is not None:
        nulls = null_share_gate(
            columns,
            [r for r in rows_by_key.values() if r[0] in report],
            memory=memory,
            applicable={tf: applicable_columns(registry, columns, tf) for tf in report},
            max_null_fraction=max_null,
            min_name_rows=args.min_name_rows,
        )
        failures[NULL_GATE] = sum(len(entry["failing"]) for entry in nulls.values())
        for tf, entry in nulls.items():
            print(f"{tf}: G6 failing columns {len(entry['failing'])}; worst {entry['worst']}")
    seen = {symbol for _, symbol in rows_by_key}
    missing_symbols = sorted(set(args.symbol or ()) - seen)
    missing_tf = sorted(set(args.tf or ()) - set(report))
    declared = registry_declarations(registry)
    if not all(declared.values()):
        print(
            f"registry declarations missing {declared}: G1 and G3 are not calibrated until 584 D1"
        )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / f"feature_column_screen_{stamp}.json"
    payload = {
        "generated": stamp,
        "tf": args.tf,
        "symbols": args.symbol,
        "pilot": args.pilot,
        "min_rows": args.min_rows,
        "min_name_rows": args.min_name_rows,
        "warmup_gap_bars": warmup_gap_max,
        "zero_share_max": zero_share_max,
        "n_columns": len(columns),
        "registry_declarations": declared,
        "skipped": skipped,
        "missing_tf": missing_tf,
        "missing_symbols": missing_symbols,
        "gate_failures": failures,
        "report": report,
        "null_gate": nulls,
    }
    path.write_text(json.dumps(payload, indent=1, sort_keys=True))
    print(f"gate failures {failures}; report: {path}")
    if not report or missing_tf or missing_symbols:
        print(f"not screened: {missing_tf + missing_symbols or 'everything'}")
        return 2
    return 1 if any(failures.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
