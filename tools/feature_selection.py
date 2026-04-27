"""Renaissance feature selection based on automated validation results.

Applies IC-threshold-based categorization to determine deploy/tweak/kill
decisions for I6 cross-TF plugins.

Categories:
- KEEP (IC > 0.05, p < 0.01, N >= 30): Deploy to shadow mode
- TWEAK (IC 0.02-0.05): Parameter adjustments needed
- KILL (IC < 0.02 or N < 30): Abandon feature per Renaissance discipline
"""

from __future__ import annotations

from tools.validate_i6_backtest import ValidationResults


def apply_feature_selection(
    validation_results: dict[str, ValidationResults],
) -> dict[str, list[str]]:
    """Apply Renaissance feature selection criteria.

    Args:
        validation_results: Output from validate_all_plugins()

    Returns:
        Dict with keys KEEP, TWEAK, KILL — each a list of plugin names.
    """
    keep: list[str] = []
    tweak: list[str] = []
    kill: list[str] = []

    for plugin_name, results in validation_results.items():
        if results.decision == "VALIDATED":
            keep.append(plugin_name)
        elif results.decision.startswith("TWEAK"):
            tweak.append(plugin_name)
        else:
            kill.append(plugin_name)

    return {
        "KEEP": keep,
        "TWEAK": tweak,
        "KILL": kill,
    }


def print_feature_selection_report(selection: dict[str, list[str]]) -> None:
    """Print feature selection report with automated deployment decision."""
    print("\n" + "=" * 80)
    print("RENAISSANCE FEATURE SELECTION REPORT")
    print("=" * 80)
    print("")

    print("KEEP (deploy to shadow mode, IC > 0.05 AND p < 0.01 AND N >= 30):")
    if selection["KEEP"]:
        for plugin in selection["KEEP"]:
            print(f"  - {plugin}")
    else:
        print("  (none)")

    print("")
    print("TWEAK (parameter adjustments needed, IC 0.02-0.05):")
    if selection["TWEAK"]:
        for plugin in selection["TWEAK"]:
            print(f"  - {plugin}")
    else:
        print("  (none)")

    print("")
    print("KILL (abandon feature, IC < 0.02 or insufficient data):")
    if selection["KILL"]:
        for plugin in selection["KILL"]:
            print(f"  - {plugin}")
    else:
        print("  (none)")

    print("")
    print("=" * 80)
    print("AUTOMATED DECISION")
    print("=" * 80)

    if len(selection["KEEP"]) >= 1:
        print(f"AT LEAST 1 FEATURE VALIDATED ({len(selection['KEEP'])} plugins)")
        print("-> Deploy to shadow mode per D-25")
        print("-> Proceed to Plan 04 (macro factors)")
        print("-> Monitor shadow mode performance for 2 weeks minimum")
    else:
        print("NO FEATURES VALIDATED (0 plugins passed IC > 0.05 gate)")
        print("-> Abandon cross-TF direction per Renaissance discipline")
        print("-> Do NOT invest in Plan 04 (macro factors) until data gate lifts")
        print("-> Re-run validation after ~May 10 (30-day pnl_r data gate)")

    print("=" * 80)


if __name__ == "__main__":
    from datetime import datetime, UTC
    from tools.backtest_cross_tf_plugins import backtest_all_cross_tf_plugins
    from tools.validate_i6_backtest import validate_all_plugins

    # Run backtest on available data
    results = backtest_all_cross_tf_plugins()

    # Validate all plugins
    validation_results = validate_all_plugins(results)

    # Apply feature selection
    selection = apply_feature_selection(validation_results)

    # Print report
    print_feature_selection_report(selection)
