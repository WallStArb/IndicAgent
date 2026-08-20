#!/usr/bin/env python3
"""Cross-Sectional Regime Model — generic dispatcher that populates market_regimes.

Generalizes services/equity_regime_model.py: instead of a single hardcoded 'equity'
label, this dispatcher iterates every enabled group in APR key alpha.regime.groups
(JSON array) and writes group-scoped regime labels to market_regimes.regime_group
(migration 222 renamed asset_class -> regime_group).

Groups are defined in APR key alpha.regime.groups (JSON array). Each group:
  - name: string key written to market_regimes.regime_group
  - tag_filter: list of tag patterns (prefix match, * stripped) to resolve peer symbols
  - signal_type: key in src/intelligence/regime_signals/REGISTRY
  - params_prefix: APR namespace for signal thresholds
  - enabled: bool

Signal modules (src/intelligence/regime_signals/) implement:
  - compute(ref_bars, params) -> (pd.Series, pd.Series) | None
  - build_tiers(params) -> (tiers1, tiers2)
  - PROB_KEYS: tuple[str, str]

Data flow per group per TF:
  1. Resolve peer symbols from instrument_tags (startup, once)
  2. Fetch all peer (+ reference) symbol bars for this TF (fresh connection, avoids
     idle termination)
  3. Pre-scale the group's daily-bar-denominated window params to this TF via
     _tf_window() (RESEARCH.md Pattern 5 — window params in alpha.*_regime.* APR
     keys are always DAILY-bar counts; every signal module stays TF-agnostic)
  4. Call signal_module.compute(ref_bars, scaled_params) -> (sig1, sig2)
  5. Align signals, drop NaN warmup rows
  6. Call _assign_labels(...) -> list[tuple]
  7. Batch-insert into market_regimes (ON CONFLICT (regime_group, tf, ts) DO UPDATE)

Not a real-time daemon — this is a batch/oneshot labeling tool exempt from the
"only writer subclasses touch DB" rule exactly as equity_regime_model.py and
backfill_feature_factory.py are. Single-process, no worker pool: DB fetch is the
bottleneck, label assignment is vectorized numpy (a pool would add no throughput).

Usage:
    python services/cross_sectional_regime_model.py
    python services/cross_sectional_regime_model.py --tf 5m 1h
    python services/cross_sectional_regime_model.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg
import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services._batch_utils import connect_db_from_url
from services._batch_utils import load_config_service_sync as _load_config_service
from src.config.settings import Settings
from src.core.service_utils import setup_service_logging
from src.intelligence.regime_signals import REGISTRY
from src.intelligence.regime_signals.tf_window import _tf_window
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers

setup_service_logging("logs/cross_sectional_regime_model.log")

_logger = structlog.get_logger(__name__)

_JOB = "cross-sectional-regime-model"
_DEFAULT_TFS: list[str] = ["5m", "15m", "1h", "1d"]

# Fallback default for cfg.get_sync("alpha.regime.groups", ...) — matches migration
# 222's seeded config exactly. Only used if the APR key is somehow unset (should not
# happen post-migration; this is a defensive fallback, not the source of truth).
_DEFAULT_GROUPS_JSON = json.dumps(
    [
        {
            "name": "equity",
            "tag_filter": ["eq_*", "intl_*"],
            "signal_type": "breadth_vol",
            "params_prefix": "alpha.equity_regime",
            "enabled": True,
        },
        {
            "name": "rates",
            "tag_filter": ["fi_*"],
            "signal_type": "curve_credit",
            "params_prefix": "alpha.rates_regime",
            "enabled": True,
        },
        {
            "name": "commodity_energy",
            "tag_filter": [
                "commodity_energy_crude",
                "commodity_energy_natgas",
                "commodity_energy_pipeline",
            ],
            "signal_type": "commodity_momentum_ts",
            "params_prefix": "alpha.commodity_energy_regime",
            "enabled": False,
        },
        {
            "name": "commodity_metals",
            "tag_filter": ["commodity_metals_precious", "commodity_metals_industrial"],
            "signal_type": "commodity_momentum_ts",
            "params_prefix": "alpha.commodity_metals_regime",
            "enabled": False,
        },
        {
            "name": "commodity_agri",
            "tag_filter": ["commodity_agri"],
            "signal_type": "commodity_momentum_ts",
            "params_prefix": "alpha.commodity_agri_regime",
            "enabled": False,
        },
        {
            "name": "fx",
            "tag_filter": ["fx_*", "crypto"],
            "signal_type": "fx_dollar_carry",
            "params_prefix": "alpha.fx_regime",
            "enabled": False,
        },
    ]
)

# Window-param keys treated as DAILY-bar counts, pre-scaled to the target TF via
# _tf_window() before being passed to a signal module's compute(). Every group's
# window-denominated APR key (see migration 222's config_schema descriptions) is
# named with a "_window" suffix by convention — this set enumerates the exact keys
# accepted by each signal module today (breadth_vol/curve_credit/commodity_momentum_ts/
# fx_dollar_carry all read one of these from `params`, per their compute() signatures).
_WINDOW_PARAM_KEYS: frozenset[str] = frozenset(
    {
        "realized_vol_window",
        "vix_z_window",
        "ma_window",
        "curve_window",
        "credit_window",
        "momentum_window",
    }
)

# ---------------------------------------------------------------------------
# Pure helpers — exported for unit tests
# ---------------------------------------------------------------------------


def _parse_group_configs(raw: str | list[dict]) -> list[dict]:
    """Parse and filter group config JSON from APR. Returns only enabled groups.

    Accepts EITHER a raw JSON string OR an already-parsed list[dict].

    The JSON-typed APR key alpha.regime.groups returns an ALREADY-PARSED list[dict]
    once cached: ConfigService._parse_value() calls json.loads() at cache-load time
    for value_type='json' keys (src/config/config_service.py:94-95), and
    load_config_service_sync() (services/_batch_utils.py) populates the cache via
    that same _parse_value() path. Calling json.loads() again on an already-parsed
    list, or str()-ing it first, are both bugs: str(list_of_dicts) produces a
    Python-repr string (single quotes, True/False) that is NOT valid JSON and raises
    inside a second json.loads() call. The isinstance(raw, list) branch below is what
    actually fires for the live cached value; the json.loads() branch exists for
    callers passing a raw string directly (tests, or a string-typed fallback default).
    """
    if isinstance(raw, list):
        configs = raw
    else:
        try:
            configs = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as error:
            raise ValueError(f"alpha.regime.groups contains invalid JSON: {error}") from error
    return [g for g in configs if g.get("enabled", True)]


def _resolve_group_symbols(
    tags_by_symbol: dict[str, set[str]],
    tag_filter: list[str],
) -> list[str]:
    """Return sorted list of symbols whose tags match any pattern in tag_filter.

    Pattern matching: strip trailing '*' and test if any tag starts with that prefix.
    """
    prefixes = [p.rstrip("*") for p in tag_filter]
    matched = [
        sym
        for sym, tags in tags_by_symbol.items()
        if any(any(t.startswith(pfx) for t in tags) for pfx in prefixes)
    ]
    return sorted(matched)


def _assert_ascending_tiers(
    tiers: list[tuple[str, float]], group_name: str = "<unknown>", tier_label: str = "<unknown>"
) -> None:
    """Crash-loud guard (todo 335, hardened in code review): _bucket() silently
    mis-labels a malformed tiers list instead of raising -- confirmed live in
    commodity_momentum_ts and fx_dollar_carry, where a descending list caused the
    last-applied (widest) where() clause to overwrite every narrower bucket,
    collapsing half of both modules' label vocabularies to permanently-unreachable
    dead states. Requires STRICTLY ascending bounds (ties are also rejected -- a
    repeated bound reproduces the same overwrite-collapse bug even though the list
    is technically non-decreasing) and at least 2 tuples (a single-entry list is
    the exact shape of fx_dollar_carry's original tiers2 bug: every _bucket() call
    falls through to the sole catch-all tuple, and every other label is
    permanently unreachable without _bucket() ever raising).
    """
    if len(tiers) < 2:
        raise ValueError(
            f"{group_name}.{tier_label} has only {len(tiers)} tuple(s): {tiers} -- "
            f"_bucket() needs at least one real threshold plus a catch-all; a single-entry "
            f"list makes every OTHER label permanently unreachable without raising (todo 335)."
        )
    bounds = [upper for _, upper in tiers[:-1]]
    if bounds != sorted(set(bounds)):
        raise ValueError(
            f"{group_name}.{tier_label} is not STRICTLY ascending-sorted by upper_bound: "
            f"{tiers} -- _bucket() requires strictly ascending order with no ties (last "
            f"tuple's bound is ignored, only its name is used as the catch-all default); a "
            f"descending or tied list silently collapses buckets instead of raising (todo 335)."
        )


def _bucket(
    vals: np.ndarray,
    tiers: list[tuple[str, float]],
    *,
    group_name: str = "<unknown>",
    tier_label: str = "<unknown>",
) -> np.ndarray:
    """Assign tier names by threshold. tiers sorted ascending by upper_bound; last = inf.

    A value is assigned to the first tier whose upper_bound STRICTLY exceeds the value.
    Validates tiers on every call (code review, todo 335) rather than relying on callers
    to remember _assert_ascending_tiers -- scripts/analysis/regime_boundary_churn_check.py
    calls this directly without going through main()'s explicit guard, so the contract has
    to live here to cover every caller, not just main()'s.
    """
    _assert_ascending_tiers(tiers, group_name, tier_label)
    result = np.full(len(vals), tiers[-1][0], dtype=object)
    for name, upper in reversed(tiers[:-1]):
        result = np.where(vals < upper, name, result)
    return result


def _assign_labels(
    group_name: str,
    tf: str,
    ts_arr: list,
    sig1_arr: np.ndarray,
    sig2_arr: np.ndarray,
    tiers1: list[tuple[str, float]],
    tiers2: list[tuple[str, float]],
    prob_keys: tuple[str, str],
) -> list[tuple]:
    """Vectorized label assignment. No DB, no pandas.

    Returns list of (regime_group, tf, ts, regime_label, prob_dict) — regime_group is
    set on EVERY emitted row (column renamed from asset_class per migration 222).
    regime_label = "{tier1}_{tier2}".

    LABEL-VOCABULARY-UNIQUENESS INVARIANT (RESEARCH.md Pitfall 4): feature_ic_scores
    has no regime_group column — group identity is implicit in regime_label string
    uniqueness across all enabled groups. Every signal module's build_tiers() tier
    vocabulary MUST stay non-overlapping with every other enabled group's vocabulary
    (breadth_vol/curve_credit/commodity_momentum_ts/fx_dollar_carry document this
    invariant in their own module docstrings). If a future group's build_tiers() ever
    reuses a tier name from another enabled group, two semantically different regimes
    would collide under the same regime_label string in downstream feature_ic_scores
    rows, silently corrupting ensemble eligibility queries. Not schema-enforced —
    verify manually when adding a new group's signal module.
    """
    labels1 = _bucket(sig1_arr, tiers1, group_name=group_name, tier_label="tiers1")
    labels2 = _bucket(sig2_arr, tiers2, group_name=group_name, tier_label="tiers2")
    return [
        (
            group_name,
            tf,
            ts_arr[i],
            f"{labels1[i]}_{labels2[i]}",
            {prob_keys[0]: float(sig1_arr[i]), prob_keys[1]: float(sig2_arr[i])},
        )
        for i in range(len(ts_arr))
    ]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _load_tags_by_symbol(conn: Any) -> dict[str, set[str]]:
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, array_agg(tag) FROM instrument_tags GROUP BY symbol")
        return {row[0]: set(row[1]) for row in cur.fetchall()}


def _fetch_group_bars(dsn: str, tf: str, symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Fetch close prices for all symbols in one query. Returns dict[symbol, DataFrame].

    Uses a fresh connection to avoid idle-connection termination during long fetches
    (the 2026-07-08 idle-connection data-loss incident rationale — see
    equity_regime_model.py._compute_breadth_fraction for the original precedent).
    """
    sql = """
        SELECT symbol, timestamp, close
        FROM market_data_ohlcv_tradeable
        WHERE symbol = ANY(%s) AND timeframe = %s
        ORDER BY symbol, timestamp ASC
    """
    fresh_conn = psycopg.connect(dsn)
    fresh_conn.autocommit = True
    try:
        with fresh_conn.cursor() as cur:
            cur.execute(sql, (symbols, tf))
            rows = cur.fetchall()
    finally:
        fresh_conn.close()

    result: dict[str, list] = {}
    for sym, ts, close in rows:
        result.setdefault(sym, []).append((ts, float(close)))

    return {
        sym: pd.DataFrame(entries, columns=["timestamp", "close"])
        for sym, entries in result.items()
    }


def _scale_window_params(params: dict[str, str], tf: str) -> dict[str, Any]:
    """Pre-scale every DAILY-bar-denominated window param to the target TF's bar count.

    RESEARCH.md Pattern 5: window params in alpha.*_regime.* APR keys are always
    daily-bar counts (see migration 222's config_schema descriptions); every signal
    module's compute() treats params it receives as ALREADY bar-scaled and stays
    TF-agnostic. This is the dispatcher's sole responsibility to apply — signal
    modules never call _tf_window() themselves.

    Non-window params (thresholds) pass through unscaled, as raw config_state
    string values — signal modules cast them (float()/int()) internally.
    """
    scaled: dict[str, Any] = dict(params)
    for key in _WINDOW_PARAM_KEYS:
        if key in params:
            scaled[key] = _tf_window(int(params[key]), tf)
    return scaled


def _write_rows(conn: Any, rows: list[tuple]) -> int:
    """Batch-insert regime rows into market_regimes. Returns count written."""
    insert_sql = """
        INSERT INTO market_regimes (regime_group, tf, ts, regime_label, regime_prob_vector)
        VALUES (%(regime_group)s, %(tf)s, %(ts)s, %(regime_label)s, %(regime_prob_vector)s::jsonb)
        ON CONFLICT (regime_group, tf, ts)
        DO UPDATE SET
            regime_label = EXCLUDED.regime_label,
            regime_prob_vector = EXCLUDED.regime_prob_vector
    """
    batch = [
        {
            "regime_group": r[0],
            "tf": r[1],
            "ts": r[2],
            "regime_label": r[3],
            "regime_prob_vector": json.dumps(r[4]),
        }
        for r in rows
    ]
    with conn.cursor() as cur:
        cur.executemany(insert_sql, batch)
    conn.commit()
    return len(batch)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cross-Sectional Regime Model — populate market_regimes for all enabled groups"
    )
    parser.add_argument("--tf", nargs="*", default=_DEFAULT_TFS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        init_otel_providers(service_name=_JOB)
    except OTelInitError as error:
        _logger.warning("cross_sectional_regime_model.otel_init_failed", error=str(error))

    t0 = time.monotonic()
    status = "success"
    exit_code = 0
    settings = Settings()
    conn = None

    try:
        dsn = settings.database_url
        conn = connect_db_from_url(settings.database_url)
        cfg = _load_config_service(conn)

        raw_groups = cfg.get_sync("alpha.regime.groups", _DEFAULT_GROUPS_JSON)
        group_configs = _parse_group_configs(raw_groups)

        if not group_configs:
            _logger.error("cross_sectional_regime_model.no_enabled_groups")
            status = "failure"
            exit_code = 1
            return

        tags_by_symbol = _load_tags_by_symbol(conn)

        for group in group_configs:
            group_name = group["name"]
            signal_type = group["signal_type"]
            params_prefix = group["params_prefix"]

            signal_mod = REGISTRY.get(signal_type)
            if signal_mod is None:
                # Fail loud: an unknown signal_type is a config-authoring error
                # (operator-authored alpha.regime.groups JSON), never a silent skip.
                raise RuntimeError(
                    f"Unknown signal_type '{signal_type}' for group '{group_name}'. "
                    f"Available: {list(REGISTRY.keys())}"
                )

            peer_symbols = _resolve_group_symbols(tags_by_symbol, group["tag_filter"])
            if not peer_symbols:
                _logger.warning(
                    "cross_sectional_regime_model.no_peer_symbols",
                    group=group_name,
                    tag_filter=group["tag_filter"],
                )
                continue

            _logger.info(
                "cross_sectional_regime_model.group_start",
                group=group_name,
                signal_type=signal_type,
                n_symbols=len(peer_symbols),
            )

            # Load raw APR params for this group's signal (string values — scaled/cast below)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT config_key, config_value FROM config_state WHERE config_key LIKE %s",
                    (f"{params_prefix}.%",),
                )
                raw_params = cur.fetchall()
            prefix_len = len(params_prefix) + 1
            params = {row[0][prefix_len:]: row[1] for row in raw_params}

            tiers1, tiers2 = signal_mod.build_tiers(params)
            _assert_ascending_tiers(tiers1, group_name, "tiers1")
            _assert_ascending_tiers(tiers2, group_name, "tiers2")

            total_written = 0
            for tf in args.tf:
                # Pre-scale daily-bar window params to this TF's bar count BEFORE compute()
                # (RESEARCH.md Pattern 5) — signal modules stay TF-agnostic.
                scaled_params = _scale_window_params(params, tf)

                # Reference symbols a signal module needs regardless of peer-group
                # membership (e.g. fx_dollar_carry anchors on UUP/HYG) — fetch alongside
                # peer symbols so compute() always sees them in ref_bars.
                reference_symbols = list(getattr(signal_mod, "REFERENCE_SYMBOLS", ()))
                fetch_symbols = sorted(set(peer_symbols) | set(reference_symbols))

                _logger.info(
                    "cross_sectional_regime_model.fetching_bars",
                    group=group_name,
                    tf=tf,
                    n_symbols=len(fetch_symbols),
                )

                ref_bars = _fetch_group_bars(dsn, tf, fetch_symbols)

                if not ref_bars:
                    _logger.warning(
                        "cross_sectional_regime_model.no_bars",
                        group=group_name,
                        tf=tf,
                    )
                    continue

                result = signal_mod.compute(ref_bars, scaled_params)
                if result is None:
                    _logger.warning(
                        "cross_sectional_regime_model.signal_returned_none",
                        group=group_name,
                        tf=tf,
                    )
                    continue

                sig1, sig2 = result
                combined = pd.DataFrame({"s1": sig1, "s2": sig2.reindex(sig1.index)}).dropna()

                if combined.empty:
                    _logger.warning(
                        "cross_sectional_regime_model.no_valid_rows",
                        group=group_name,
                        tf=tf,
                    )
                    continue

                rows = _assign_labels(
                    group_name=group_name,
                    tf=tf,
                    ts_arr=combined.index.tolist(),
                    sig1_arr=combined["s1"].to_numpy(),
                    sig2_arr=combined["s2"].to_numpy(),
                    tiers1=tiers1,
                    tiers2=tiers2,
                    prob_keys=signal_mod.PROB_KEYS,
                )

                # Log per (group, tf) — never per row (CLAUDE.md hot-path logging rule).
                distinct_labels = {r[3] for r in rows}
                _logger.info(
                    "cross_sectional_regime_model.tf_computed",
                    group=group_name,
                    tf=tf,
                    n_rows=len(rows),
                    distinct_labels=sorted(distinct_labels),
                )

                if args.dry_run:
                    continue

                # Reconnect before write: bar fetch can take minutes for 5m TF, and the
                # original conn may have gone idle long enough for the server to close it.
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                conn = connect_db_from_url(settings.database_url)

                n_written = _write_rows(conn, rows)
                total_written += n_written
                _logger.info(
                    "cross_sectional_regime_model.tf_written",
                    group=group_name,
                    tf=tf,
                    n_written=n_written,
                )

            _logger.info(
                "cross_sectional_regime_model.group_complete",
                group=group_name,
                total_written=total_written,
            )

        if args.dry_run:
            _logger.info("cross_sectional_regime_model.dry_run_complete")

        elapsed = time.monotonic() - t0
        _logger.info(
            "cross_sectional_regime_model.complete",
            elapsed_s=round(elapsed, 2),
            status=status,
        )

    except Exception as error:
        _logger.error("cross_sectional_regime_model.run_failed", error=str(error))
        status = "failure"
        exit_code = 1
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB, "status": status})
        flush_and_shutdown_metrics()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
