"""S0: the only harness node that touches Postgres. Read-only, content-hashed.

Pre-registration section 5. Every connection runs with default_transaction_read_only = on, so
the harness cannot write feature_ic_scores, ensemble_weights or anything else. Rows are bounded
by end_exclusive, which may not pass alpha.validation.oos_start (checked before any fetch).

Routing, broadcast flags and feature groups are read with the queries production uses
(ic_engine's instruments/instrument_tags routing via _build_symbol_regime_class, its
concept_registry broadcast query, ops_ic_shrinkage's group query). Feature column types come
from the prepared statement's attributes, never from the fetched values (CLAUDE.md).

On disk: snapshot_<sha256[:16]>/ holding one .npy per array (memory-mapped on load) and
manifest.json. The hash covers every array's bytes and the manifest.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from pathlib import Path

import asyncpg
import numpy as np

from scripts.analysis.sleeve_walk_forward.results import GroupArrays, Snapshot
from services.cross_sectional_regime_model import _parse_group_configs
from services.ic_engine import _FEATURE_NAMES, _build_symbol_regime_class
from src.config.settings import dimension_where_clause

_SCALES = ("fast", "mid", "slow", "extended")
_NUMERIC = {"float4", "float8", "int2", "int4", "int8", "numeric", "bool"}
_POOL_SIZE = 6

_CONFIG_SQL = (
    "SELECT cs.config_key, cs.config_value, csc.value_type "
    "FROM config_state cs JOIN config_schema csc USING (config_key)"
)
_TAGS_SQL = (
    "SELECT i.symbol, array_remove(array_agg(t.tag), NULL::text) "
    "FROM instruments i "
    "LEFT JOIN instrument_tags t ON t.symbol = i.symbol AND t.source = 'human' "
    f"WHERE {dimension_where_clause('compute', 'i')} GROUP BY i.symbol"
)
_BROADCAST_SQL = (
    "SELECT cr.name FROM concept_registry cr JOIN concept_gate cg USING (concept_id) "
    "WHERE cr.domain = 'feature' AND cr.metadata->>'broadcast' = 'true'"
)
_GROUP_NAME_SQL = (
    "SELECT cr.name, cr.group_name FROM concept_registry cr "
    "JOIN concept_gate cg ON cg.concept_id = cr.concept_id WHERE cr.domain = 'feature'"
)
_FEATURE_ROWS_SQL = (
    "SELECT fv.bar_ts, "
    + ", ".join(f'fv."{f}"' for f in _FEATURE_NAMES)
    + ", "
    + ", ".join(f"fr.return_{s}" for s in _SCALES)
    + ", "
    + ", ".join(f"fr.complete_{s}" for s in _SCALES)
    + ", fr.bar_ts IS NOT NULL AS has_fr "
    "FROM feature_vectors fv "
    "LEFT JOIN forward_returns fr ON fr.symbol = fv.symbol AND fr.tf = fv.tf "
    "AND fr.bar_ts = fv.bar_ts AND fr.return_type = 'executable_open_to_open' "
    "WHERE fv.symbol = $1 AND fv.tf = '1d' AND fv.bar_ts >= $2 AND fv.bar_ts < $3 "
    "ORDER BY fv.bar_ts"
)
_BARS_SQL = (
    "SELECT timestamp, open, close FROM market_data_ohlcv_tradeable "
    "WHERE symbol = $1 AND timeframe = '1d' AND timestamp >= $2 AND timestamp < $3 "
    "ORDER BY timestamp"
)
_LABELS_SQL = (
    "SELECT regime_group, ts, regime_label FROM market_regimes "
    "WHERE tf = '1d' AND ts >= $1 AND ts < $2"
)


async def read_only_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn,
        min_size=1,
        max_size=_POOL_SIZE,
        server_settings={"default_transaction_read_only": "on"},
    )


def _day(ts) -> np.datetime64:
    return np.datetime64(ts.date() if hasattr(ts, "date") else ts, "D")


async def build_snapshot(
    dsn: str,
    out_dir: Path,
    *,
    sleeve: tuple[str, ...],
    start: str,
    end_exclusive: str,
    symbols: list[str] | None = None,
) -> Path:
    from datetime import UTC, datetime

    lo = datetime.fromisoformat(start).replace(tzinfo=UTC)
    hi = datetime.fromisoformat(end_exclusive).replace(tzinfo=UTC)
    pool = await read_only_pool(dsn)
    try:
        async with pool.acquire() as conn:
            apr = {k: (v, t) for k, v, t in await conn.fetch(_CONFIG_SQL)}
            # oos_start has no config_schema row, so production's APR query never returns it.
            oos = await conn.fetchval(
                "SELECT config_value::timestamptz FROM config_state "
                "WHERE config_key = 'alpha.validation.oos_start'"
            )
            if oos is None:
                raise ValueError("alpha.validation.oos_start is not set")
            if hi > oos:
                raise ValueError(
                    f"end_exclusive {end_exclusive} is past oos_start {oos.isoformat()}"
                )
            attrs = (await conn.prepare(_FEATURE_ROWS_SQL)).get_attributes()
            bad = [
                a.name for a in attrs[1 : 1 + len(_FEATURE_NAMES)] if a.type.name not in _NUMERIC
            ]
            if bad:
                raise TypeError(f"non-numeric feature columns: {bad}")
            tags = {s: set(t) for s, t in await conn.fetch(_TAGS_SQL)}
            broadcast = {r[0] for r in await conn.fetch(_BROADCAST_SQL)}
            feature_to_group = {n: g for n, g in await conn.fetch(_GROUP_NAME_SQL) if g}
            label_rows = await conn.fetch(_LABELS_SQL, lo, hi)
            spy = await conn.fetch(_BARS_SQL, "SPY", lo, hi)
        groups_cfg = _parse_group_configs(apr["alpha.regime.groups"][0])
        routing = _build_symbol_regime_class(tags, groups_cfg)
        universe = sorted(set(symbols) if symbols is not None else set(routing) | set(sleeve))

        async def fetch(sql: str, sym: str) -> list:
            async with pool.acquire() as c:
                return await c.fetch(sql, sym, lo, hi)

        feature_rows = await asyncio.gather(*(fetch(_FEATURE_ROWS_SQL, s) for s in universe))
        bar_rows = await asyncio.gather(*(fetch(_BARS_SQL, s) for s in sleeve))
    finally:
        await pool.close()

    sessions = np.array([_day(r["timestamp"]) for r in spy], dtype="datetime64[D]")
    arrays, manifest = _assemble(
        sessions, universe, feature_rows, sleeve, bar_rows, label_rows, routing, broadcast
    )
    manifest.update(
        oos_start=oos.isoformat(),
        start=start,
        end_exclusive=end_exclusive,
        sleeve=list(sleeve),
        universe=universe,
    )
    meta = {"apr": apr, "feature_to_group": feature_to_group, "manifest": manifest}
    return _write(Path(out_dir), arrays, meta)


def _assemble(sessions, universe, feature_rows, sleeve, bar_rows, label_rows, routing, broadcast):
    n_feat, n_s = len(_FEATURE_NAMES), len(_SCALES)
    blocks = {k: [] for k in ("symbol", "bar_ts", "X", "returns", "complete", "has_fr")}
    for sym, rows in zip(universe, feature_rows):
        if not rows:
            continue
        blocks["symbol"].append(np.full(len(rows), sym))
        blocks["bar_ts"].append(np.array([_day(r[0]) for r in rows], dtype="datetime64[D]"))
        blocks["X"].append(
            np.array(
                [[np.nan if v is None else v for v in r[1 : 1 + n_feat]] for r in rows], np.float32
            )
        )
        ret = [r[1 + n_feat : 1 + n_feat + n_s] for r in rows]
        blocks["returns"].append(np.array([[np.nan if v is None else v for v in x] for x in ret]))
        cmp = [r[1 + n_feat + n_s : 1 + n_feat + 2 * n_s] for r in rows]
        blocks["complete"].append(np.array([[bool(v) for v in x] for x in cmp]))
        blocks["has_fr"].append(np.array([r[-1] for r in rows], bool))
    cat = {k: np.concatenate(v) for k, v in blocks.items()}
    idx = np.searchsorted(sessions, cat["bar_ts"])
    on_session = (idx < len(sessions)) & (
        sessions[np.minimum(idx, len(sessions) - 1)] == cat["bar_ts"]
    )
    order = np.lexsort((cat["symbol"], cat["bar_ts"]))
    order = order[on_session[order]]
    arrays = {f"all_{k}": v[order] for k, v in cat.items()}
    arrays["all_session_idx"] = idx[order]
    arrays["all_group"] = np.array([routing.get(s, "") for s in arrays["all_symbol"]])
    for g in sorted({v for v in routing.values()}):
        labels = np.full(len(sessions), "", dtype=object)
        for grp, ts, label in label_rows:
            if grp == g:
                i = np.searchsorted(sessions, _day(ts))
                if i < len(sessions) and sessions[i] == _day(ts):
                    labels[i] = label
        arrays[f"labels_{g}"] = labels.astype(str)
    arrays["sessions"] = sessions
    sym_pos = {s: j for j, s in enumerate(sleeve)}
    sleeve_rows = np.isin(arrays["all_symbol"], list(sleeve))
    feats = np.full((len(sessions), len(sleeve), n_feat), np.nan, np.float32)
    has_row = np.zeros((len(sessions), len(sleeve)), bool)
    cols = np.array([sym_pos[s] for s in arrays["all_symbol"][sleeve_rows]], dtype=int)
    feats[arrays["all_session_idx"][sleeve_rows], cols] = arrays["all_X"][sleeve_rows]
    has_row[arrays["all_session_idx"][sleeve_rows], cols] = True
    opens = np.full((len(sessions), len(sleeve)), np.nan)
    closes = np.full((len(sessions), len(sleeve)), np.nan)
    for j, rows in enumerate(bar_rows):
        for ts, o, c in rows:
            i = np.searchsorted(sessions, _day(ts))
            if i < len(sessions) and sessions[i] == _day(ts):
                opens[i, j], closes[i, j] = o, c
    arrays.update(
        sleeve_features=feats,
        sleeve_has_row=has_row,
        sleeve_opens=opens,
        sleeve_closes=closes,
        broadcast_mask=np.array([f in broadcast for f in _FEATURE_NAMES]),
    )
    manifest = {
        "n_rows": int(len(order)),
        "n_rows_off_session": int((~on_session).sum()),
        "max_bar_ts": str(arrays["all_bar_ts"].max()) if len(order) else "",
        "feature_names": list(_FEATURE_NAMES),
        "groups": sorted({v for v in routing.values()}),
    }
    return arrays, manifest


def _write(out_dir: Path, arrays: dict[str, np.ndarray], meta: dict) -> Path:
    tmp = out_dir / "snapshot_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    digest = hashlib.sha256()
    for name in sorted(arrays):
        np.save(tmp / f"{name}.npy", arrays[name], allow_pickle=False)
        digest.update(name.encode())
        digest.update((tmp / f"{name}.npy").read_bytes())
    meta_text = json.dumps(meta, sort_keys=True, default=str)
    digest.update(meta_text.encode())
    (tmp / "meta.json").write_text(meta_text)
    final = out_dir / f"snapshot_{digest.hexdigest()[:16]}"
    shutil.rmtree(final, ignore_errors=True)
    tmp.rename(final)
    return final


def load_snapshot(path: Path) -> Snapshot:
    path = Path(path)
    meta = json.loads((path / "meta.json").read_text())

    def a(name: str) -> np.ndarray:
        return np.load(path / f"{name}.npy", mmap_mode="r", allow_pickle=False)

    sessions = a("sessions")
    group_of = a("all_group")
    labels = {g: a(f"labels_{g}") for g in meta["manifest"]["groups"]}
    session_idx = a("all_session_idx")

    def rows(mask: np.ndarray, label_by_session: np.ndarray) -> GroupArrays:
        return GroupArrays(
            symbols=a("all_symbol")[mask],
            bar_ts=a("all_bar_ts")[mask],
            session_idx=session_idx[mask],
            X=a("all_X")[mask],
            returns=a("all_returns")[mask],
            complete=a("all_complete")[mask],
            labels=label_by_session[session_idx[mask]],
        )

    has_fr = a("all_has_fr")
    equity = labels.get("equity", np.full(len(sessions), ""))
    return Snapshot(
        sessions=sessions,
        groups={g: rows((group_of == g) & has_fr, labels[g]) for g in labels},
        all_1d=rows(np.ones(len(group_of), bool), equity),
        sleeve_features=a("sleeve_features"),
        sleeve_has_row=a("sleeve_has_row"),
        sleeve_opens=a("sleeve_opens"),
        sleeve_closes=a("sleeve_closes"),
        equity_labels=equity,
        feature_names=meta["manifest"]["feature_names"],
        broadcast_mask=a("broadcast_mask"),
        feature_to_group=meta["feature_to_group"],
        apr={k: tuple(v) for k, v in meta["apr"].items()},
        manifest=meta["manifest"],
    )
