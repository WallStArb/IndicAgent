#!/usr/bin/env python3
"""
Renaissance-style automated migration: Eliminate error-prone dual-state pattern.

ROOT CAUSE: Plugins have BOTH `state` parameter (correct DAG flow) AND
`self._state` instance variable (legacy, breaks separation of concerns).

SOLUTION:
1. Remove _state field from plugin dataclasses
2. Update all compute_next to use state parameter
3. Add _state to return dict for persistence
4. Verify with automated tests

PRINCIPLES:
- Single source of truth (state parameter flows through DAG)
- Separation of concerns (no hidden instance state)
- Modularity (plugins receive state, don't own it)
- Automation over manual patching
"""

import re
from pathlib import Path

# Pattern 1: Find all plugins with the buggy pattern
BUGGY_PLUGINS = [
    "src/intelligence/features/i1_indicators/atr.py",
    "src/intelligence/features/i1_indicators/rsi.py",
    "src/intelligence/features/i1_indicators/macd.py",
    "src/intelligence/features/i1_indicators/adx.py",
    "src/intelligence/features/i1_indicators/stochastic.py",
    "src/intelligence/features/i1_indicators/cci.py",
    "src/intelligence/features/i1_indicators/williams_r.py",
    "src/intelligence/features/i1_indicators/historical_volatility.py",
    "src/intelligence/features/i1_indicators/chandelier.py",
    "src/intelligence/features/i1_indicators/parabolic_sar.py",
    "src/intelligence/features/i1_indicators/stochastic_rsi.py",
    "src/intelligence/features/i1_indicators/aroon.py",
    "src/intelligence/features/i1_indicators/keltner.py",
    "src/intelligence/features/i1_indicators/ac_oscillator.py",
    "src/intelligence/features/i1_indicators/donchian.py",
    "src/intelligence/features/i1_indicators/roc_ppo.py",
    "src/intelligence/features/i1_indicators/mfi.py",
    "src/intelligence/features/i1_indicators/cmf.py",
    "src/intelligence/features/i1_indicators/bollinger.py",
    "src/intelligence/context/garch_volatility.py",
    "src/intelligence/context/kalman_trend.py",
    "src/intelligence/features/i5_patterns/bollinger_squeeze.py",
    "src/intelligence/trading/volume_zscore.py",
]


def migrate_plugin_file(file_path: str) -> dict:
    """Migrate a single plugin file to correct state pattern.

    Returns dict with success, changes_made, and any errors.
    """
    result = {"file": file_path, "success": False, "changes": [], "errors": []}

    try:
        content = Path(file_path).read_text()
        original_content = content

        # Pattern 1: Fix the conditional check
        if "if not self._state:" in content:
            content = content.replace("if not self._state:", "if not state:")
            result["changes"].append("Fixed: if not self._state: → if not state:")

        # Pattern 2: Fix state access
        if re.search(r"if key not in self\._state:", content):
            content = content.replace("if key not in self._state:", "if key not in state:")
            result["changes"].append("Fixed: if key not in self._state: → if key not in state:")

        # Pattern 3: Fix state variable access
        content = re.sub(r"self\._state\[", "state[", content)
        result["changes"].append("Fixed: self._state[key] → state[key]")

        # Pattern 4: Fix self._state assignment (GARCH pattern)
        content = re.sub(r"self\._state\s*=\s*{", "state.update({", content)
        result["changes"].append("Fixed: self._state = {...} → state.update({...})")

        # Pattern 5: Add _state to return dict
        # Find compute_next's return statement and add _state
        compute_next_pattern = r"(def compute_next\(.*?\).*?\n)(.*?)(return out\s*$)"

        def add_state_return(match):
            func_def = match.group(1)
            func_body = match.group(2)
            return_stmt = match.group(3)

            # Only add if _state not already in return
            if "_state" not in return_stmt and 'out["_state"]' not in func_body:
                # Find the last line before return
                lines = func_body.split("\n")
                if lines:
                    # Insert before return
                    indent = len(lines[-1]) - len(lines[-1].lstrip())
                    state_assign = " " * indent + 'out["_state"] = state\n'
                    return func_def + func_body + state_assign + return_stmt
            return match.group(0)

        content = re.sub(compute_next_pattern, add_state_return, content, flags=re.MULTILINE)

        # Pattern 6: Remove _state field from dataclass if it's just a default dict
        if "_state: dict = field(default_factory=dict)" in content:
            content = content.replace("_state: dict = field(default_factory=dict)\n", "")
            result["changes"].append("Removed: _state field from dataclass")

        # Write back if changed
        if content != original_content:
            Path(file_path).write_text(content)
            result["success"] = True
        else:
            result["errors"].append("No changes needed or pattern not found")

    except Exception as e:
        result["errors"].append(f"Migration failed: {e}")

    return result


def main():
    """Execute Renaissance-style automated migration."""

    print("🏛️ RENAISSANCE ARCHITECTURAL FIX: Plugin State Migration")
    print("=" * 60)
    print(f"Target plugins: {len(BUGGY_PLUGINS)}")
    print()

    results = []
    for plugin_file in BUGGY_PLUGINS:
        if not Path(plugin_file).exists():
            print(f"⚠️  Skipping {plugin_file} (not found)")
            continue

        result = migrate_plugin_file(plugin_file)
        results.append(result)

        if result["success"]:
            print(f"✅ {Path(plugin_file).name}")
            for change in result["changes"]:
                print(f"   {change}")
        else:
            print(f"❌ {Path(plugin_file).name}")
            for error in result["errors"]:
                print(f"   {error}")

    # Summary
    print()
    print("=" * 60)
    successful = sum(1 for r in results if r["success"])
    print(f"🎯 Migration complete: {successful}/{len(results)} plugins fixed")

    # Verification step
    print()
    print("🔍 VERIFICATION: Checking for remaining buggy patterns...")
    remaining_bugs = []
    for plugin_file in BUGGY_PLUGINS:
        if Path(plugin_file).exists():
            content = Path(plugin_file).read_text()
            if "if not self._state:" in content or "self._state[" in content:
                remaining_bugs.append(plugin_file)

    if remaining_bugs:
        print(f"⚠️  {len(remaining_bugs)} files still have buggy patterns:")
        for f in remaining_bugs:
            print(f"   {f}")
    else:
        print("✅ No buggy patterns found - migration successful!")

    print()
    print("🚀 Next steps:")
    print("1. Restart intelligence pipeline")
    print("2. Verify ATR values are in correct range")
    print("3. Run plugin tests to ensure no regressions")
    print("4. Consider adding _state field removal to cleanup")


if __name__ == "__main__":
    main()
