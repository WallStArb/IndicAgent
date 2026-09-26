"""Session-legs panel and per-leg S1 for family 2 (docs/plans/2026-09-25-family2-overnight-
intraday-prereg.md sections 2, 4 and 9, build requirement B1).

Each session of an intraday source panel becomes three rows:

| Row | open | close | bar return (panel.bar_returns) |
|---|---|---|---|
| 0, overnight | previous session's final close | bar 0's open | ln(open0 / final close of d-1) |
| 1, first bar | bar 0's open | bar 0's close | ln(close0 / open0) |
| 2, rest | bar 1's open | final close | ln(final close / close0) |

The final bar is panel.forward_returns' close-exit bar: the session's last row with any close
(half days end early); a name with no close there has NaN final close, never an earlier one.
Prices are not paired within a row: each leg's return needs exactly the prices in its formula
(row 1 needs bar 0's open and close, row 2 bar 0's close and the final close), and the target
needs bar 1's open and the final close, so a missing price removes only what reads it. Volume: rows 0 and 1 take bar 0's, row 2 the
sum of bars 1 through the final bar.

S1 runs per leg, each leg as its own one-row-per-session series, so every leg gets its own
market, group and principal-component loadings (prereg section 2). The target, the rest-of-
session return entered at bar 1's open, is residualized as its own session series with loadings
from strictly earlier sessions and placed on row 1; rows 0 and 2 carry no target.

Compute-only numpy with no I/O except `us_session_equity_symbols`.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from src.intelligence.research.factors import FactorSpec, residual_returns
from src.intelligence.research.panel import Panel, bar_returns, forward_returns

LEGS = 3  # overnight, first bar, rest of session: the transform's definition (APR-exempt)
SIGNAL_LEG = 1  # members' alpha row and the target row
TRANSFORM = "session_legs"

# The members' universe rule (prereg section 2, B3): current level-1 node EQ, no current
# international exposure tag. Pinned SQL, never built from caller text.
_US_SESSION_EQUITY_SQL = """
SELECT ic.symbol
FROM instrument_classification ic
JOIN classification_node n ON n.scheme = ic.scheme AND n.code = ic.code
WHERE ic.scheme = 'indicagent_v1' AND ic.valid_to IS NULL AND n.path[1] = 'EQ'
  AND NOT EXISTS (
    SELECT 1 FROM instrument_tags t
    WHERE t.symbol = ic.symbol AND t.valid_to IS NULL
      AND t.tag IN ('intl_developed', 'intl_em')
  )
ORDER BY ic.symbol
"""


def _final_rows(close: np.ndarray, bars_per_session: int) -> np.ndarray:
    """int [S], each session's last source row with any close, -1 for a session with none."""
    has_bar = np.isfinite(close).any(axis=1).reshape(-1, bars_per_session)
    last = bars_per_session - 1 - has_bar[:, ::-1].argmax(axis=1)
    rows = np.arange(len(has_bar)) * bars_per_session + last
    return np.where(has_bar.any(axis=1), rows, -1)


def session_legs(source: Panel, *, source_hash: str | None = None) -> Panel:
    """The three-row session-legs panel of an intraday source panel (module docstring)."""
    bps = source.bars_per_session
    if bps < 2:
        raise ValueError(f"session legs need an intraday source panel, got {bps} bar(s)/session")
    n_s, m = source.n_sessions, len(source.symbols)
    o = np.asarray(source.open, dtype=float).reshape(n_s, bps, m)
    c = np.asarray(source.close, dtype=float).reshape(n_s, bps, m)
    v = np.asarray(source.volume, dtype=float).reshape(n_s, bps, m)

    final = _final_rows(np.asarray(source.close, dtype=float), bps)
    final_close = np.full((n_s, m), np.nan)
    has = final >= 0
    final_close[has] = np.asarray(source.close, dtype=float)[final[has]]
    prev_final = np.vstack([np.full((1, m), np.nan), final_close[:-1]])

    bar_idx = np.arange(bps)[None, :]
    last_in_session = np.where(has, final - np.arange(n_s) * bps, -1)[:, None]
    in_rest = (bar_idx >= 1) & (bar_idx <= last_in_session)  # [S, bps]
    rest_v = np.where(in_rest[:, :, None] & np.isfinite(v), v, 0.0).sum(axis=1)
    any_rest = (in_rest[:, :, None] & np.isfinite(v)).any(axis=1)
    rest_volume = np.where(any_rest, rest_v, np.nan)

    legs_o = np.empty((n_s, LEGS, m))
    legs_c = np.empty((n_s, LEGS, m))
    legs_o[:, 0], legs_c[:, 0] = prev_final, o[:, 0]
    legs_o[:, 1], legs_c[:, 1] = o[:, 0], c[:, 0]
    legs_o[:, 2], legs_c[:, 2] = o[:, 1], final_close
    legs_v = np.stack([v[:, 0], v[:, 0], rest_volume], axis=1)

    ts = source.timestamps.reshape(n_s, bps)
    legs_ts = np.stack([ts[:, 0] - np.timedelta64(1, "m"), ts[:, 0], ts[:, 1]], axis=1).ravel()
    close_flat = legs_c.reshape(n_s * LEGS, m)
    manifest = {
        **source.manifest,
        "transform": TRANSFORM,
        "source_tf": source.tf,
        "source_bars_per_session": bps,
        "source_snapshot_hash": source_hash,
    }
    return dataclasses.replace(
        source,
        tf=f"{source.tf}_{TRANSFORM}",
        timestamps=legs_ts,
        bars_per_session=LEGS,
        valid=np.isfinite(close_flat).any(axis=1),
        open=legs_o.reshape(n_s * LEGS, m),
        close=close_flat,
        volume=legs_v.reshape(n_s * LEGS, m),
        manifest=manifest,
    )


def select_symbols(panel: Panel, symbols: list[str]) -> Panel:
    """The panel restricted to `symbols` present in it, in the panel's order. A requested symbol
    the panel lacks is not an error (the rule is S0 symbols intersected with the rule's names)."""
    keep = [j for j, s in enumerate(panel.symbols) if s in set(symbols)]
    if not keep:
        raise ValueError("the members' universe shares no symbol with the panel")
    idx = np.asarray(keep)
    return dataclasses.replace(
        panel,
        symbols=tuple(panel.symbols[j] for j in keep),
        open=np.asarray(panel.open)[:, idx],
        close=np.asarray(panel.close)[:, idx],
        volume=np.asarray(panel.volume)[:, idx],
        sectors=tuple(panel.sectors[j] for j in keep) if panel.sectors else (),
        valid=np.isfinite(np.asarray(panel.close)[:, idx]).any(axis=1),
    )


async def us_session_equity_symbols(dsn: str) -> list[str]:
    """The members' universe rule's names, sorted (B3)."""
    from src.intelligence.research.snapshot import read_only_pool  # noqa: PLC0415

    pool = await read_only_pool(dsn)
    try:
        rows = await pool.fetch(_US_SESSION_EQUITY_SQL)
    finally:
        await pool.close()
    return [r["symbol"] for r in rows]


def _interleave(per_leg: list[np.ndarray]) -> np.ndarray:
    n_s, m = per_leg[0].shape
    return np.stack(per_leg, axis=1).reshape(n_s * len(per_leg), m)


def leg_residuals(legs: Panel, factor_spec: FactorSpec) -> np.ndarray:
    """[3S, m] S1 residual bar returns, S1 run per leg on its session series."""
    r = bar_returns(legs).reshape(legs.n_sessions, LEGS, -1)
    return _interleave(
        [
            residual_returns(r[:, k], bars_per_session=1, spec=factor_spec).residual
            for k in range(LEGS)
        ]
    )


def raw_target(legs: Panel) -> np.ndarray:
    """[S, m] ln(final close / bar 1's open): row 1's horizon-1 close-exit forward return."""
    fwd = forward_returns(legs.open, 1, legs.session, closes=legs.close)
    return fwd[SIGNAL_LEG::LEGS]


def target_residuals(legs: Panel, factor_spec: FactorSpec) -> np.ndarray:
    """[3S, m] the S1 residual target on row 1, NaN on rows 0 and 2. horizon=0 gives a one-
    session lag: each refit's loadings end at the session before its block (prereg section 4)."""
    res = residual_returns(raw_target(legs), bars_per_session=1, horizon=0, spec=factor_spec)
    out = np.full((legs.n_sessions * LEGS, len(legs.symbols)), np.nan)
    out[SIGNAL_LEG::LEGS] = res.residual
    return out


def last_source_row_read(leg_rows: np.ndarray, source_bps: int) -> np.ndarray:
    """For legs rows, the latest source row each one's prices can read: rows 0 and 1 read
    through bar 0 of their session, row 2 through the session's last bar."""
    session, leg = np.divmod(leg_rows, LEGS)
    return session * source_bps + np.where(leg == 2, source_bps - 1, 0)


def transform_causality_probe(source: Panel, leg_rows: np.ndarray, *, seed: int) -> None:
    """S3 for the transform itself: for each legs row r, replace every source row after the
    latest one r reads (last_source_row_read), once with NaN and once with random rescaling,
    and raise GuardFailure if any legs price at or before r moves. Rows are visited latest first
    on one working copy per fill, as guards.causality_probe does, so each visit only extends the
    replaced tail. Guard-time only: it runs on S3's probe sub-panel, one transform per row."""
    from src.intelligence.research.guards import GuardFailure  # noqa: PLC0415

    base = session_legs(source)
    rows = np.sort(np.asarray(leg_rows))[::-1]
    last_read = last_source_row_read(rows, source.bars_per_session)
    rng = np.random.default_rng(seed)
    fields = ("open", "close", "volume")
    for fill in ("nan", "rescale"):
        work = {k: np.array(getattr(source, k), dtype=float) for k in fields}
        filled_from = len(source.timestamps)
        for r, last in zip(rows, last_read, strict=True):
            cut = int(last) + 1
            if cut < filled_from:
                for arr in work.values():
                    block = arr[cut:filled_from]
                    if fill == "nan":
                        block[:] = np.nan
                    else:
                        block *= np.exp(rng.normal(0.0, 0.5, block.shape))
                filled_from = cut
            out = session_legs(dataclasses.replace(source, **work))
            head = slice(0, int(r) + 1)
            for name in fields:
                if not np.array_equal(
                    getattr(out, name)[head], getattr(base, name)[head], equal_nan=True
                ):
                    raise GuardFailure(
                        f"lookahead: legs {name} at or before row {int(r)} changed when source "
                        f"rows from {cut} were replaced ({fill})"
                    )
