#!/usr/bin/env python3
"""
Alpha Validation Gate — validate_alpha.py

Statistical validation gate that all new alpha sources must clear before live promotion.
"Earn the right through proof" — no indicator enters the live pipeline without passing
Pearson r > 0, p < 0.05, and N >= 30 against forward close-to-close returns.

Hard gates (all three must pass):
  - N >= 30 signal bars with complete forward return data
  - Pearson r > 0 (positive directional correlation)
  - Pearson p-value < 0.05 (statistically significant)

Informational only (not gates):
  - ADF stationarity test (momentum indicators expected non-stationary)
  - False-positive rate (no threshold until baselines exist)

Usage:
    python production/scripts/validate_alpha.py --plugin ind_ACOscillator --days 90
    python production/scripts/validate_alpha.py --plugin cmp_DerivativeOscillator --days 90
    python production/scripts/validate_alpha.py --plugin cmp_DerivativeOscillator --promote
    python production/scripts/validate_alpha.py --plugin patt_CandlestickPatterns \\
        --field three_white_soldiers --promote
    python production/scripts/validate_alpha.py --plugin cmp_DerivativeOscillator \\
        --symbol-filter ESH6,NQH6
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg2
import psycopg2.extras
from scipy.stats import pearsonr
from statsmodels.tsa.stattools import adfuller

# ---------------------------------------------------------------------------
# Path setup — consistent with historical_backfill.py pattern
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.config.settings import Settings  # noqa: E402

# ---------------------------------------------------------------------------
# Plugin registry — maps --plugin name to DB column, field, tier, signal_type
# ---------------------------------------------------------------------------
PLUGIN_REGISTRY: dict[str, dict[str, Any]] = {
    "ind_ACOscillator": {
        "column": "i1",
        "field": "ac",
        "tier": "I1",
        "register_fn": "register_indicator",
        "import_path": ".indicators.ac_oscillator",
        "import_alias": "ac_osc_plugin",
        "signal_type": "zero_cross",  # ac crosses 0 = signal
        "n_bars_by_tf": {"1m": 5, "default": 3},
    },
    "cmp_DerivativeOscillator": {
        "column": "i2",
        "field": "deriv_osc_cross_bullish",
        "tier": "I2",
        "register_fn": "register_pattern",
        "import_path": ".composites.derivative_oscillator",
        "import_alias": "deriv_osc_plugin",
        "signal_type": "binary",
        "n_bars_by_tf": {"1m": 5, "default": 3},
    },
    "patt_CandlestickPatterns": {
        "column": "i5",
        "field": None,  # --field flag required
        "tier": "I5",
        "register_fn": "register_pattern",
        "import_path": ".patterns.candlestick_patterns",
        "import_alias": "candlestick_plugin",
        "signal_type": "binary",
        "n_bars_by_tf": {"1m": 5, "default": 3},
        # secondary_patch: also patch candlestick_pattern_setup.py on --promote
        "secondary_patch": "candlestick_pattern_setup",
    },
    "evt_MACDEvents": {
        "column": "i2",
        "field": "macd_hist_accel",
        "tier": "I2",
        "register_fn": "register_pattern",
        "import_path": ".composites.macd_events",
        "import_alias": "macd_events_plugin",
        "signal_type": "directional",  # positive = bullish
        "n_bars_by_tf": {"1m": 5, "default": 3},
    },
}


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def _n_bars_for_tf(tf: str, n_bars_by_tf: dict[str, int]) -> int:
    return n_bars_by_tf.get(tf, n_bars_by_tf.get("default", 3))


def _compute_stats(
    df: pd.DataFrame,
    field: str,
    signal_type: str,
    n_bars_by_tf: dict[str, int],
) -> dict[str, Any]:
    """
    Compute all statistics for the validation gate.

    Parameters
    ----------
    df : DataFrame with columns [symbol, timeframe, feature_ts, close, field_value]
    field : The plugin output field name (signal column name in df)
    signal_type : 'binary', 'zero_cross', or 'directional'
    n_bars_by_tf : TF-to-N-bars mapping for forward return window

    Returns
    -------
    dict with all stat fields needed for the report and gates
    """
    # Build signal direction series per (symbol, timeframe) group, then concatenate.
    #
    # Correlation approach: include ALL bars with valid forward returns.
    # Signal direction: 1.0 when indicator fires (bullish), -1.0 when bearish,
    # 0.0 when not firing. We also count "N signal bars" = bars where direction != 0.
    #
    # This avoids the constant-input NaN problem: by including non-signal bars (direction=0)
    # we get variation in the signal series, enabling a proper Pearson test.
    signal_parts = []
    return_parts = []
    signal_fire_count = 0

    for (_symbol, tf), group in df.groupby(["symbol", "timeframe"]):
        group = group.sort_values("feature_ts").reset_index(drop=True)
        n_bars = _n_bars_for_tf(tf, n_bars_by_tf)

        # Forward return: close[t+N]/close[t] - 1, aligned to bar t via shift(-N)
        # pct_change(N) gives (close[t] - close[t-N]) / close[t-N]  → past return
        # shift(-N) moves that value backward N positions so row t gets the FUTURE N-bar return
        fwd_return = group["close"].pct_change(n_bars).shift(-n_bars)

        # Signal direction extraction
        field_vals = group[field]

        if signal_type == "binary":
            # 1.0 = bullish fire, 0.0 = not firing
            direction = field_vals.apply(lambda v: 1.0 if v > 0 else 0.0)
        elif signal_type == "zero_cross":
            # field crosses zero: +1 = bullish, -1 = bearish, 0 = no signal
            direction = field_vals.apply(
                lambda v: 1.0 if v > 0 else (-1.0 if v < 0 else 0.0)
            )
        elif signal_type == "directional":
            # Positive = bullish (+1), negative = bearish (-1), zero = no signal
            direction = field_vals.apply(
                lambda v: 1.0 if v > 0 else (-1.0 if v < 0 else 0.0)
            )
        else:
            direction = field_vals.apply(lambda v: 1.0 if v > 0 else (-1.0 if v < 0 else 0.0))

        # Count signal-fired bars (direction != 0) for the N gate
        signal_fire_count += int((direction != 0).sum())

        # Valid mask: forward return is available (include ALL bars, not just signal bars)
        valid_mask = fwd_return.notna() & direction.notna()
        signal_parts.append(direction[valid_mask])
        return_parts.append(fwd_return[valid_mask])

    if not signal_parts:
        return {
            "n_signal_bars": 0,
            "n_total_bars": len(df),
            "signal_frequency": 0.0,
            "adf_stat": None,
            "adf_pvalue": None,
            "adf_stationary": None,
            "pearson_r": None,
            "pearson_pvalue": None,
            "false_positive_rate": None,
        }

    all_signals = pd.concat(signal_parts)
    all_returns = pd.concat(return_parts)

    # n_signal_bars = bars where the indicator actually fired (direction != 0)
    n_signal = signal_fire_count
    n_total = len(df)

    # ADF test on forward returns series (informational — tests whether returns are stationary)
    # Note: momentum indicators expected non-stationary; ADF is NOT a hard gate
    try:
        adf_series = all_returns.dropna()
        if len(adf_series) >= 10:
            adf_result = adfuller(adf_series, autolag="AIC")
            adf_stat = float(adf_result[0])
            adf_pvalue = float(adf_result[1])
            adf_stationary = bool(adf_pvalue < 0.05)
        else:
            adf_stat = None
            adf_pvalue = None
            adf_stationary = None
    except Exception:
        adf_stat = None
        adf_pvalue = None
        adf_stationary = None

    # Pearson correlation (the gate)
    try:
        pearson_r_val, pearson_p_val = pearsonr(all_signals.values, all_returns.values)
        pearson_r = float(pearson_r_val)
        pearson_p = float(pearson_p_val)
    except Exception:
        pearson_r = float("nan")
        pearson_p = float("nan")

    # False-positive rate: bars where signal fired bullish but forward return < 0
    # (only among signal-fired bars, not the zeros)
    bullish_signal_mask = all_signals > 0
    if bullish_signal_mask.sum() > 0:
        fpr = float((all_returns[bullish_signal_mask] < 0).sum() / bullish_signal_mask.sum())
    else:
        fpr = None

    signal_freq = n_signal / n_total if n_total > 0 else 0.0

    return {
        "n_signal_bars": n_signal,
        "n_total_bars": n_total,
        "signal_frequency": round(signal_freq, 6),
        "adf_stat": adf_stat,
        "adf_pvalue": adf_pvalue,
        "adf_stationary": adf_stationary,
        "pearson_r": pearson_r,
        "pearson_pvalue": pearson_p,
        "false_positive_rate": fpr,
    }


# ---------------------------------------------------------------------------
# DB data fetching
# ---------------------------------------------------------------------------


def _count_qualifying_rows(
    conn: Any,
    column: str,
    field: str,
    days: int,
    symbol_filter: list[str] | None,
) -> int:
    """Return count of rows where the plugin field is present and non-null."""
    with conn.cursor() as cur:
        base_sql = f"""
            SELECT COUNT(*)
            FROM intelligence_features
            WHERE feature_ts >= NOW() - INTERVAL '{days} days'
            AND {column} ? %s
            AND ({column}->%s) IS NOT NULL
        """
        params: list[Any] = [field, field]
        if symbol_filter:
            placeholders = ", ".join(["%s"] * len(symbol_filter))
            base_sql += f" AND symbol IN ({placeholders})"
            params.extend(symbol_filter)
        cur.execute(base_sql, params)
        row = cur.fetchone()
        return int(row[0]) if row else 0


def _fetch_rows(
    conn: Any,
    column: str,
    field: str,
    days: int,
    symbol_filter: list[str] | None,
) -> list[tuple[Any, ...]]:
    """Fetch (symbol, timeframe, feature_ts, close, column_jsonb) rows."""
    with conn.cursor() as cur:
        base_sql = f"""
            SELECT symbol, timeframe, feature_ts, close, {column}
            FROM intelligence_features
            WHERE feature_ts >= NOW() - INTERVAL '{days} days'
            AND {column} ? %s
            ORDER BY symbol, timeframe, feature_ts
        """
        params: list[Any] = [field]
        if symbol_filter:
            placeholders = ", ".join(["%s"] * len(symbol_filter))
            base_sql = f"""
                SELECT symbol, timeframe, feature_ts, close, {column}
                FROM intelligence_features
                WHERE feature_ts >= NOW() - INTERVAL '{days} days'
                AND {column} ? %s
                AND symbol IN ({placeholders})
                ORDER BY symbol, timeframe, feature_ts
            """
            params = [field] + symbol_filter
        cur.execute(base_sql, params)
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Promote patching — register_plugins.py
# ---------------------------------------------------------------------------


def _patch_register_plugins(
    plugin_name: str,
    plugin_meta: dict[str, Any],
    project_root: Path,
) -> None:
    """
    Patch register_plugins.py at three insertion points.

    Strategy: Use sentinel comments (# END TIER_I1 etc.) as anchors.
    Fallback: If no sentinel found, insert after last relevant pattern.

    The file is backed up before patching and restored on failure.
    """
    reg_path = project_root / "src" / "intelligence" / "register_plugins.py"
    backup_path = reg_path.with_suffix(".py.bak")

    tier = plugin_meta["tier"]  # e.g. "I1", "I2", "I5"
    import_path = plugin_meta["import_path"]  # e.g. ".indicators.ac_oscillator"
    import_alias = plugin_meta["import_alias"]  # e.g. "ac_osc_plugin"
    register_fn = plugin_meta["register_fn"]  # e.g. "register_indicator"

    shutil.copy2(reg_path, backup_path)

    try:
        content = reg_path.read_text()

        # --- Point 1: Import ---
        import_line = f"from {import_path} import plugin as {import_alias}\n"
        import_sentinel = f"# END {tier}_IMPORTS"

        if import_line in content:
            # Already imported — skip
            pass
        elif import_sentinel in content:
            content = content.replace(import_sentinel, f"{import_line}{import_sentinel}")
        else:
            # Fallback: insert after last matching import pattern
            if tier == "I1":
                pattern = r"(from \.indicators\.[^\n]+\n)"
            elif tier == "I2":
                pattern = r"(from \.composites\.[^\n]+\n)"
            elif tier == "I5":
                pattern = r"(from \.patterns\.[^\n]+\n)"
            else:
                pattern = r"(from \.[^\n]+\n)"

            matches = list(re.finditer(pattern, content))
            if matches:
                last_match = matches[-1]
                insert_pos = last_match.end()
                content = content[:insert_pos] + import_line + content[insert_pos:]
            else:
                # Last resort: insert before `from .plugins import registry`
                content = content.replace(
                    "from .plugins import registry\n",
                    f"{import_line}from .plugins import registry\n",
                )

        # --- Point 2: Registration call in register_all_plugins() ---
        reg_line = f"    registry.{register_fn}({import_alias})\n"
        reg_sentinel = f"    # END {tier}_REGISTRATIONS"

        if reg_line in content:
            # Already registered — skip
            pass
        elif reg_sentinel in content:
            content = content.replace(reg_sentinel, f"{reg_line}{reg_sentinel}")
        else:
            # Fallback: insert before the blank line that ends the tier block
            # Find the last registration call for this tier
            if tier == "I1":
                last_i1_call = "registry.register_indicator(stoch_rsi_plugin)\n"
                content = content.replace(last_i1_call, f"{last_i1_call}{reg_line}")
            elif tier in ("I2", "I5"):
                # For I2/I5, find the comment that precedes I7 registrations
                i7_comment = "    # I7 Trading Setups\n"
                if i7_comment in content:
                    content = content.replace(i7_comment, f"{reg_line}\n{i7_comment}")
                else:
                    # Append before the end of register_all_plugins
                    content = content.replace(
                        "    registry.register_pattern(session_extremes_setup_plugin)\n",
                        f"    registry.register_pattern(session_extremes_setup_plugin)\n{reg_line}",
                    )

        # --- Point 3: Tier list entry ---
        tier_sentinel = f"    # END TIER_{tier}\n"
        tier_entry = f"    {import_alias}.name,\n"

        if tier_entry in content:
            # Already in tier list — skip
            pass
        elif tier_sentinel in content:
            content = content.replace(tier_sentinel, f"{tier_entry}{tier_sentinel}")
        else:
            # Fallback: find the TIER_* list closing bracket and insert before it
            # Match the TIER_I1/I2/I5 list: ends with `]\n`
            tier_list_pattern = rf"(TIER_{tier}: list\[str\] = \[.*?\])"
            tier_match = re.search(tier_list_pattern, content, re.DOTALL)
            if tier_match:
                old_list = tier_match.group(1)
                # Insert before closing ]
                new_list = old_list[:-1] + f"    {import_alias}.name,\n]"
                content = content.replace(old_list, new_list)

        reg_path.write_text(content)

        # Verify the patched file is importable
        check_cmd = (
            f"import sys; sys.path.insert(0, '{_PROJECT_ROOT}'); "
            "from src.intelligence.register_plugins import register_all_plugins"
        )
        result = subprocess.run(
            [sys.executable, "-c", check_cmd],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
        )
        if result.returncode != 0:
            raise RuntimeError(f"Patched register_plugins.py failed import check:\n{result.stderr}")

        backup_path.unlink(missing_ok=True)
        print(f"  Patched register_plugins.py — import + registration + TIER_{tier} entry added.")

    except Exception:
        # Restore backup on failure
        shutil.copy2(backup_path, reg_path)
        backup_path.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Promote patching — candlestick_pattern_setup.py
# ---------------------------------------------------------------------------


def _patch_candlestick_setup(
    field: str,
    project_root: Path,
) -> None:
    """
    Patch candlestick_pattern_setup.py to add a new pattern to:
    1. The named reads block (features.get lines)
    2. The candidates list

    Uses sentinel comments # END CANDLESTICK_READS and # END CANDLESTICK_CANDIDATES.
    Falls back to inserting after last features.get line / last candidates.append line.
    """
    setup_path = project_root / "src" / "intelligence" / "trading" / "candlestick_pattern_setup.py"
    backup_path = setup_path.with_suffix(".py.bak")
    shutil.copy2(setup_path, backup_path)

    try:
        content = setup_path.read_text()

        # --- Named read ---
        promoted_comment = "  # PROMOTED via validate_alpha.py"
        read_line = (
            f"        {field} = float(features.get(\"{field}\", 0.0))"
            f"{promoted_comment}\n"
        )
        read_sentinel = "        # END CANDLESTICK_READS\n"

        if f'features.get("{field}"' in content:
            # Already present
            pass
        elif read_sentinel in content:
            content = content.replace(read_sentinel, f"{read_line}{read_sentinel}")
        else:
            # Fallback: insert after last features.get line
            last_get = list(re.finditer(r"        \w+ = float\(features\.get\(", content))
            if last_get:
                insert_after = content.index("\n", last_get[-1].start()) + 1
                content = content[:insert_after] + read_line + content[insert_after:]

        # --- Candidate entry ---
        # Determine direction from field name convention
        bearish_words = ("bear", "crows", "evening", "down", "dark")
        direction = -1 if any(w in field for w in bearish_words) else 1
        # Map field to confidence score
        confidence_map = {
            "three_white_soldiers": 0.72,
            "three_black_crows": 0.72,
            "morning_star": 0.65,
            "evening_star": 0.65,
            "three_inside_up": 0.65,
            "three_inside_down": 0.65,
            "harami_cross": 0.58,
            "dark_cloud_cover": 0.55,
            "piercing_line": 0.55,
        }
        conf = confidence_map.get(field, 0.55)
        cand_line = (
            f"        if {field} > 0.0:\n"
            f"            candidates.append((1, {direction}, \"{field}\", {conf}, False))\n"
        )
        cand_sentinel = "        # END CANDLESTICK_CANDIDATES\n"

        if f'"{field}"' in content and "candidates.append" in content:
            # Check if this field's candidate is already present
            if f'"{field}", {conf}' in content:
                pass  # Already present
            elif cand_sentinel in content:
                content = content.replace(cand_sentinel, f"{cand_line}{cand_sentinel}")
            else:
                # Fallback: insert before `if not candidates:`
                content = content.replace(
                    "        if not candidates:\n",
                    f"{cand_line}\n        if not candidates:\n",
                    1,
                )
        elif cand_sentinel in content:
            content = content.replace(cand_sentinel, f"{cand_line}{cand_sentinel}")
        else:
            content = content.replace(
                "        if not candidates:\n",
                f"{cand_line}\n        if not candidates:\n",
                1,
            )

        setup_path.write_text(content)
        backup_path.unlink(missing_ok=True)
        print(f"  Patched candlestick_pattern_setup.py — added {field} to reads and candidates.")

    except Exception:
        shutil.copy2(backup_path, setup_path)
        backup_path.unlink(missing_ok=True)
        raise


# ---------------------------------------------------------------------------
# Main validation entry point
# ---------------------------------------------------------------------------


def run_validation(
    plugin: str,
    days: int,
    symbol_filter: list[str] | None,
    promote: bool,
    field: str | None,
    report_dir: Path,
) -> dict[str, Any]:
    """
    Run the full validation gate for a plugin.

    Returns the report dict. Writes report to report_dir.
    Exits non-zero on gate failure (when promote=True) or if gates fail.
    """
    if plugin not in PLUGIN_REGISTRY:
        print(f"ERROR: Unknown plugin '{plugin}'. Known plugins: {list(PLUGIN_REGISTRY)}")
        sys.exit(1)

    plugin_meta = PLUGIN_REGISTRY[plugin]
    effective_field = field or plugin_meta["field"]

    if effective_field is None:
        print(f"ERROR: Plugin '{plugin}' requires --field <field_name> (multi-field plugin).")
        sys.exit(1)

    column = plugin_meta["column"]
    signal_type = plugin_meta["signal_type"]
    n_bars_by_tf = plugin_meta["n_bars_by_tf"]

    # --- Connect to DB ---
    settings = Settings()
    conn = psycopg2.connect(settings.database_url)

    try:
        # --- Data sufficiency check ---
        row_count = _count_qualifying_rows(conn, column, effective_field, days, symbol_filter)

        if row_count < 30:
            print(f"  Insufficient data: {row_count} bars. Triggering historical replay...")
            backfill_script = _PROJECT_ROOT / "production" / "scripts" / "historical_backfill.py"
            subprocess.run(
                [sys.executable, str(backfill_script), "--replay-only", "--days", str(days)],
                check=False,
            )
            # Re-count after backfill
            row_count = _count_qualifying_rows(conn, column, effective_field, days, symbol_filter)
            print(f"  After backfill: {row_count} qualifying bars.")

        # --- Fetch data ---
        raw_rows = _fetch_rows(conn, column, effective_field, days, symbol_filter)

    finally:
        conn.close()

    # Build DataFrame from raw rows
    records = []
    symbols_seen: set[str] = set()
    for sym, tf, ts, close, col_json in raw_rows:
        # col_json comes as dict (with psycopg2 extras) or string
        if isinstance(col_json, str):
            col_json = json.loads(col_json)
        val = col_json.get(effective_field) if col_json else None
        records.append({
            "symbol": sym,
            "timeframe": tf,
            "feature_ts": ts,
            "close": float(close) if close is not None else None,
            effective_field: float(val) if val is not None else None,
        })
        symbols_seen.add(sym)

    df = pd.DataFrame(records)
    if df.empty or effective_field not in df.columns:
        df = pd.DataFrame(columns=["symbol", "timeframe", "feature_ts", "close", effective_field])

    # Drop rows where close or field is null
    df = df.dropna(subset=["close", effective_field])

    # --- Compute statistics ---
    stats = _compute_stats(df, effective_field, signal_type, n_bars_by_tf)

    # --- Evaluate gates ---
    n_signal = stats["n_signal_bars"]
    pearson_r = stats["pearson_r"]
    pearson_p = stats["pearson_pvalue"]

    gate_n = n_signal >= 30
    gate_r = bool(isinstance(pearson_r, float) and pearson_r > 0)
    gate_p = bool(isinstance(pearson_p, float) and pearson_p < 0.05)

    all_pass = gate_n and gate_r and gate_p
    verdict = "PASS" if all_pass else "FAIL"

    # --- Build report ---
    run_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    report: dict[str, Any] = {
        "plugin": plugin,
        "field": effective_field,
        "run_at": run_at,
        "days": days,
        "symbols": sorted(symbols_seen),
        "n_signal_bars": n_signal,
        "n_total_bars": stats["n_total_bars"],
        "signal_frequency": stats["signal_frequency"],
        "adf_stat": stats["adf_stat"],
        "adf_pvalue": stats["adf_pvalue"],
        "adf_stationary": stats["adf_stationary"],
        "pearson_r": stats["pearson_r"],
        "pearson_pvalue": stats["pearson_pvalue"],
        "false_positive_rate": stats["false_positive_rate"],
        "gates": {
            "n_min_30": gate_n,
            "pearson_r_positive": gate_r,
            "pearson_p_lt_05": gate_p,
        },
        "verdict": verdict,
        "promoted": False,
    }

    # --- Print terminal summary ---
    print("\n" + "=" * 60)
    print(f"Validation Report: {plugin} / {effective_field}")
    print("=" * 60)
    print(f"  Days:            {days}")
    print(f"  Symbols:         {', '.join(sorted(symbols_seen)) or 'none'}")
    print(f"  N signal bars:   {n_signal}")
    print(f"  N total bars:    {stats['n_total_bars']}")
    print(f"  Signal freq:     {stats['signal_frequency']:.4f}")
    print(f"  ADF stat:        {stats['adf_stat']}")
    print(f"  ADF p-value:     {stats['adf_pvalue']}")
    print(f"  ADF stationary:  {stats['adf_stationary']} (informational)")
    print(f"  Pearson r:       {pearson_r}")
    print(f"  Pearson p:       {pearson_p}")
    print(f"  False-pos rate:  {stats['false_positive_rate']} (informational)")
    print()
    print(f"  Gate N>=30:      {'PASS' if gate_n else 'FAIL'}")
    print(f"  Gate r>0:        {'PASS' if gate_r else 'FAIL'}")
    print(f"  Gate p<0.05:     {'PASS' if gate_p else 'FAIL'}")
    print()
    print(f"  VERDICT:         {verdict}")
    print("=" * 60)

    # --- Write report ---
    report_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    safe_field = effective_field.replace("/", "_").replace(".", "_")
    report_filename = f"{date_str}-{plugin}-{safe_field}.json"
    report_path = report_dir / report_filename
    report_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"  Report written: {report_path}")

    # --- Promote (gates must pass) ---
    if promote:
        if not all_pass:
            print("\nBLOCKED: Gates failed — register_plugins.py NOT modified.")
            return report

        print("\nPromoting...")
        _patch_register_plugins(plugin, plugin_meta, _PROJECT_ROOT)

        # Secondary patch for patt_CandlestickPatterns
        if plugin_meta.get("secondary_patch") == "candlestick_pattern_setup":
            _patch_candlestick_setup(effective_field, _PROJECT_ROOT)

        report["promoted"] = True
        report_path.write_text(json.dumps(report, indent=2, default=str))
        print("  Promotion complete. Service restart required:")
        print("    sudo systemctl restart indicagent-market-analysis indicagent-signal-generator")

    return report


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Statistical validation gate for new alpha sources.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--plugin",
        required=True,
        help=f"Plugin name to validate. Known: {list(PLUGIN_REGISTRY)}",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Number of days of historical data to query (default: 90)",
    )
    parser.add_argument(
        "--symbol-filter",
        type=str,
        default=None,
        help="Comma-separated symbol filter, e.g. ESH6,NQH6",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        default=False,
        help="Patch register_plugins.py if gates pass (hard-blocked on failure)",
    )
    parser.add_argument(
        "--field",
        type=str,
        default=None,
        help="Plugin output field (required for multi-field plugins like patt_CandlestickPatterns)",
    )

    args = parser.parse_args()

    symbol_filter: list[str] | None = None
    if args.symbol_filter:
        symbol_filter = [s.strip() for s in args.symbol_filter.split(",") if s.strip()]

    # Report directory: docs/validation/ relative to project root
    report_dir = _PROJECT_ROOT / "docs" / "validation"

    result = run_validation(
        plugin=args.plugin,
        days=args.days,
        symbol_filter=symbol_filter,
        promote=args.promote,
        field=args.field,
        report_dir=report_dir,
    )

    # Exit code: 0 = PASS, 1 = FAIL
    if result["verdict"] != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    main()
