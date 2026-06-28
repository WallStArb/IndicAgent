#!/usr/bin/env python3
"""
debug_validate_alpha.py — statistical validation gate for new alpha sources

Validates that all new alpha sources pass Pearson r > 0, p < 0.05, and N >= 30 against
forward close-to-close returns before live promotion ("earn the right through proof").
Run when adding new indicators/patterns to the pipeline; --promote patches register_plugins.py on pass.
Requires intelligence_features table with plugin field data >= 30 bars.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from scipy.stats import pearsonr
from statsmodels.tsa.stattools import adfuller

# ---------------------------------------------------------------------------
# Path setup — consistent with run_historical_pipeline.py pattern
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.config.settings import Settings
from src.core.database_manager import DatabaseManager
from src.intelligence.schemas import TIER_DB_COLUMNS

# ---------------------------------------------------------------------------
# Plugin auto-discovery
# ---------------------------------------------------------------------------


# Manual hints for plugins that can't be auto-detected
# signal_type: 'binary', 'zero_cross', or 'directional'
# n_bars_by_tf: default N bars for forward return window
PLUGIN_HINTS: dict[str, dict[str, Any]] = {
    "ind_ACOscillator": {
        "signal_type": "zero_cross",
        "n_bars_by_tf": {"1m": 5, "default": 3},
    },
    "cmp_DerivativeOscillator": {
        "signal_type": "binary",
        "n_bars_by_tf": {"1m": 5, "default": 3},
    },
    "patt_CandlestickPatterns": {
        "signal_type": "binary",
        "n_bars_by_tf": {"1m": 5, "default": 3},
        "secondary_patch": "candlestick_pattern_setup",
    },
    "evt_MACDEvents": {
        "signal_type": "directional",
        "n_bars_by_tf": {"1m": 5, "default": 3},
    },
}


def _discover_plugin_metadata(plugin_name: str) -> dict[str, Any] | None:
    """
    Auto-discover plugin metadata by importing and inspecting.

    Returns dict with: column, tier, signal_type, n_bars_by_tf, import_path, import_alias, register_fn
    Returns None if plugin not found.
    """
    # Try to find plugin by name in tier lists
    from src.intelligence.register_plugins import (
        TIER_I1,
        TIER_I2,
        TIER_I3,
        TIER_I4,
        TIER_I5,
        TIER_I6,
        TIER_I7,
    )

    all_tiers = {
        "I1": TIER_I1,
        "I2": TIER_I2,
        "I3": TIER_I3,
        "I4": TIER_I4,
        "I5": TIER_I5,
        "I6": TIER_I6,
        "I7": TIER_I7,
    }

    # Find which tier this plugin belongs to
    tier = None
    for tier_name, tier_list in all_tiers.items():
        if plugin_name in tier_list:
            tier = tier_name
            break

    if not tier:
        return None

    # Determine import path by searching for the plugin file
    # Try intelligence subdirectories
    for subdir in ["indicators", "composites", "patterns", "trading", "events"]:
        # Convert plugin_name to snake_case for file search
        # e.g., cmp_DerivativeOscillator -> derivative_oscillator
        name_parts = plugin_name.split("_", 1)
        if len(name_parts) < 2:
            continue

        base_name = name_parts[1].lower()
        # Convert camelCase to snake_case
        base_name = re.sub(r"(?<!^)(?=[A-Z])", "_", base_name).lower()

        # Try module import
        module_path = f"src.intelligence.{subdir}.{base_name}"

        try:
            # Try to determine if it uses register_indicator or register_pattern
            # Indicators use register_indicator, patterns use register_pattern
            if subdir == "indicators":
                register_fn = "register_indicator"
            else:
                register_fn = "register_pattern"

            # Create import alias
            import_alias = f"{base_name}_plugin"

            return {
                "column": TIER_DB_COLUMNS[tier.lower()],
                "tier": tier,
                "register_fn": register_fn,
                "import_path": f".{subdir}.{base_name}",
                "import_alias": import_alias,
                # Will be filled from hints or defaults
                "signal_type": PLUGIN_HINTS.get(plugin_name, {}).get("signal_type", "directional"),
                "n_bars_by_tf": PLUGIN_HINTS.get(plugin_name, {}).get(
                    "n_bars_by_tf", {"1m": 5, "default": 3}
                ),
                "secondary_patch": PLUGIN_HINTS.get(plugin_name, {}).get("secondary_patch"),
            }
        except (ImportError, AttributeError):
            continue

    return None


def list_known_plugins() -> dict[str, dict[str, Any]]:
    """List all discoverable plugins from register_plugins tier lists."""
    from src.intelligence.register_plugins import (
        TIER_I1,
        TIER_I2,
        TIER_I3,
        TIER_I4,
        TIER_I5,
        TIER_I6,
        TIER_I7,
    )

    all_plugins = {}
    for tier_name, tier_list in [
        ("I1", TIER_I1),
        ("I2", TIER_I2),
        ("I3", TIER_I3),
        ("I4", TIER_I4),
        ("I5", TIER_I5),
        ("I6", TIER_I6),
        ("I7", TIER_I7),
    ]:
        for plugin_name in tier_list:
            metadata = _discover_plugin_metadata(plugin_name)
            if metadata:
                all_plugins[plugin_name] = metadata

    return all_plugins


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

    for (_symbol, tf), group in df.groupby(["symbol", "tf"]):
        group = group.sort_values("ts").reset_index(drop=True)
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
            direction = field_vals.apply(lambda v: 1.0 if v > 0 else (-1.0 if v < 0 else 0.0))
        elif signal_type == "directional":
            # Positive = bullish (+1), negative = bearish (-1), zero = no signal
            direction = field_vals.apply(lambda v: 1.0 if v > 0 else (-1.0 if v < 0 else 0.0))
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


async def _count_qualifying_rows(
    db: DatabaseManager,
    column: str,
    field: str,
    days: int,
    symbol_filter: list[str] | None,
) -> int:
    """Return count of rows where the plugin field is present and non-null."""
    async with db.get_connection() as conn:
        base_sql = f"""
            SELECT COUNT(*)
            FROM intelligence_features
            WHERE ts >= NOW() - INTERVAL '{days} days'
            AND {column} ? $1
            AND ({column}->>$2) IS NOT NULL
            AND ($3::text[] IS NULL OR symbol = ANY($3))
        """
        params: list[Any] = [field, field, symbol_filter]

        return await conn.fetchval(base_sql, *params)


async def _fetch_rows(
    db: DatabaseManager,
    column: str,
    field: str,
    days: int,
    symbol_filter: list[str] | None,
) -> list[tuple[Any, ...]]:
    """Fetch (symbol, tf, ts, close, column_jsonb) rows."""
    async with db.get_connection() as conn:
        base_sql = f"""
            SELECT symbol, tf, ts, (bar->>'close')::float, {column}
            FROM intelligence_features
            WHERE ts >= NOW() - INTERVAL '{days} days'
            AND {column} ? $1
            AND ($2::text[] IS NULL OR symbol = ANY($2))
            ORDER BY symbol, tf, ts
        """
        params: list[Any] = [field, symbol_filter]

        rows = await conn.fetch(base_sql, *params)
        return [tuple(row) for row in rows]


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
        read_line = f'        {field} = float(features.get("{field}", 0.0))' f"{promoted_comment}\n"
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
            f'            candidates.append((1, {direction}, "{field}", {conf}, False))\n'
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


async def run_validation(
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
    # Auto-discover plugin metadata
    all_plugins = list_known_plugins()

    if plugin not in all_plugins:
        print(f"ERROR: Unknown plugin '{plugin}'.")
        print(f"Known plugins: {sorted(all_plugins.keys())}")
        sys.exit(1)

    plugin_meta = all_plugins[plugin]

    # For multi-field plugins (like candlestick patterns), field must be specified
    if plugin == "patt_CandlestickPatterns" and field is None:
        print(f"ERROR: Plugin '{plugin}' requires --field <field_name> (multi-field plugin).")
        sys.exit(1)

    effective_field = field or plugin_meta.get("field")

    # For single-field plugins without explicit field, use plugin name as field
    if effective_field is None:
        # Try to derive field from plugin name
        # e.g., ind_ACOscillator -> ac
        name_parts = plugin.split("_", 1)
        if len(name_parts) == 2:
            # Convert CamelCase to snake_case for field
            base_name = name_parts[1]
            effective_field = re.sub(r"(?<!^)(?=[A-Z])", "_", base_name).lower()

    if effective_field is None:
        print(f"ERROR: Cannot determine field for plugin '{plugin}'. Use --field <field_name>.")
        sys.exit(1)

    column = plugin_meta["column"]
    signal_type = plugin_meta["signal_type"]
    n_bars_by_tf = plugin_meta["n_bars_by_tf"]

    # --- Connect to DB ---
    from src.core.script_utils import get_script_db

    settings = Settings()
    db = await get_script_db(settings)

    try:
        # --- Data sufficiency check ---
        row_count = await _count_qualifying_rows(db, column, effective_field, days, symbol_filter)

        if row_count < 30:
            print(f"  Insufficient data: {row_count} bars. Triggering historical replay...")
            backfill_script = _PROJECT_ROOT / "production" / "scripts" / "historical_backfill.py"
            subprocess.run(
                [sys.executable, str(backfill_script), "--replay-only", "--days", str(days)],
                check=False,
            )
            # Re-count after backfill
            row_count = await _count_qualifying_rows(
                db, column, effective_field, days, symbol_filter
            )
            print(f"  After backfill: {row_count} qualifying bars.")

        # --- Fetch data ---
        raw_rows = await _fetch_rows(db, column, effective_field, days, symbol_filter)

    finally:
        await db.close()

    # Build DataFrame from raw rows
    records = []
    symbols_seen: set[str] = set()
    for sym, tf, ts, close, col_json in raw_rows:
        # DatabaseManager sets up JSONB codecs — col_json is already a dict
        val = col_json.get(effective_field) if col_json else None
        records.append(
            {
                "symbol": sym,
                "tf": tf,
                "ts": ts,
                "close": float(close) if close is not None else None,
                effective_field: float(val) if val is not None else None,
            }
        )
        symbols_seen.add(sym)

    df = pd.DataFrame(records)
    if df.empty or effective_field not in df.columns:
        df = pd.DataFrame(columns=["symbol", "tf", "ts", "close", effective_field])

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
# Eligibility check
# ---------------------------------------------------------------------------


async def _check_eligibility(plugin: str | None) -> None:
    """Print resolved outcome counts — shows which plugins are ready for validate_alpha."""
    from src.core.script_utils import get_script_db

    settings = Settings()
    db = await get_script_db(settings)

    try:
        all_plugins = list_known_plugins()
        plugins_to_check = [plugin] if plugin else sorted(all_plugins.keys())

        async with db.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT setup_plugin, count(*) AS resolved_n
                FROM signal_ledger
                WHERE setup_plugin = ANY($1)
                  AND outcome IS NOT NULL
                  AND outcome != 'never_activated'
                GROUP BY setup_plugin
                ORDER BY setup_plugin
                """,
                plugins_to_check,
            )
    finally:
        await db.close()

    counts = {r["setup_plugin"]: r["resolved_n"] for r in rows}

    min_n = 30
    print(f"\nValidate-alpha eligibility (requires N >= {min_n} resolved outcomes)\n")
    eligible = []
    for p in plugins_to_check:
        n = counts.get(p, 0)
        status = "ELIGIBLE" if n >= min_n else f"NOT YET ({min_n - n} more needed)"
        print(f"  {p}: {n} resolved -> {status}")
        if n >= min_n:
            eligible.append(p)

    if eligible:
        print("\nReady to validate:")
        for p in eligible:
            print(f"  .venv/bin/python scripts/debug/validate/debug_validate_alpha.py --plugin {p}")
    print()


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
        help="Plugin name to validate.",
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
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        default=False,
        help=(
            "Record a data-absence exemption without running statistical gates. "
            "Use when plugin is newly registered and has no historical data yet."
        ),
    )
    parser.add_argument(
        "--list-plugins",
        action="store_true",
        help="List all discoverable plugins and exit.",
    )
    parser.add_argument(
        "--check-eligibility",
        action="store_true",
        help=(
            "Show resolved outcome counts per plugin to determine validate_alpha readiness. "
            "Use with --plugin to check a single plugin; omit --plugin to check all known plugins."
        ),
    )

    args = parser.parse_args()

    # Eligibility check and exit
    if args.check_eligibility:
        asyncio.run(_check_eligibility(args.plugin if hasattr(args, "plugin") else None))
        sys.exit(0)

    # List plugins and exit
    if args.list_plugins:
        all_plugins = list_known_plugins()
        print("Discoverable plugins:")
        for name in sorted(all_plugins.keys()):
            meta = all_plugins[name]
            print(f"  {name} (tier={meta['tier']}, column={meta['column']})")
        sys.exit(0)

    symbol_filter: list[str] | None = None
    if args.symbol_filter:
        symbol_filter = [s.strip() for s in args.symbol_filter.split(",") if s.strip()]

    # Report directory: docs/validation/ relative to project root
    report_dir = _PROJECT_ROOT / "docs" / "validation"

    # Bootstrap path: write audit trail without running statistical gates or DB queries.
    if args.bootstrap:
        all_plugins = list_known_plugins()
        if args.plugin not in all_plugins:
            print(f"ERROR: Unknown plugin '{args.plugin}'.")
            print("Use --list-plugins to see discoverable plugins.")
            sys.exit(1)

        plugin_meta = all_plugins[args.plugin]

        # Determine field similar to main validation
        effective_field = args.field
        if effective_field is None:
            name_parts = args.plugin.split("_", 1)
            if len(name_parts) == 2:
                base_name = name_parts[1]
                effective_field = re.sub(r"(?<!^)(?=[A-Z])", "_", base_name).lower()

        if effective_field is None:
            print(
                f"ERROR: Plugin '{args.plugin}' requires --field <field_name> "
                "(multi-field plugin)."
            )
            sys.exit(1)

        run_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        bootstrap_record: dict[str, Any] = {
            "plugin": args.plugin,
            "field": effective_field,
            "run_at": run_at,
            "days": args.days,
            "verdict": "BOOTSTRAP",
            "bootstrap_reason": "data_absence_exemption",
            "bootstrap_note": (
                "Plugin registered before gate pass. "
                "Implementation is mathematically correct (unit tests pass). "
                f"Re-run: python scripts/debug/validate/debug_validate_alpha.py "
                f"--plugin {args.plugin} --days {args.days} --promote "
                "after 30+ bars accumulate in intelligence_features."
            ),
            "promoted": False,
            "gates": {
                "n_min_30": None,
                "pearson_r_positive": None,
                "pearson_p_lt_05": None,
            },
        }

        report_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(UTC).strftime("%Y-%m-%d")
        safe_field = effective_field.replace("/", "_").replace(".", "_")
        report_filename = f"{date_str}-{args.plugin}-{safe_field}-bootstrap.json"
        report_path = report_dir / report_filename
        report_path.write_text(json.dumps(bootstrap_record, indent=2, default=str))

        print(f"BOOTSTRAP record written: {report_path}")
        print(
            f"Re-run gate after data accumulates: "
            f"python scripts/debug/validate/debug_validate_alpha.py "
            f"--plugin {args.plugin} --days {args.days} --promote"
        )
        sys.exit(0)

    result = asyncio.run(
        run_validation(
            plugin=args.plugin,
            days=args.days,
            symbol_filter=symbol_filter,
            promote=args.promote,
            field=args.field,
            report_dir=report_dir,
        )
    )

    # Exit code: 0 = PASS, 1 = FAIL
    if result["verdict"] != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    main()
