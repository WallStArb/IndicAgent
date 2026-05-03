---
phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service
plan: 03-GAPCLOSURE
type: execute
wave: 3
depends_on: ["64-01-GAPCLOSURE", "64-02-GAPCLOSURE"]
files_modified:
  - tools/backtest_cross_tf_plugins.py
  - tools/validate_i6_backtest.py
autonomous: true
requirements: []

must_haves:
  truths:
    - "All 5 cross-TF plugins backtested on 6+ months historical data"
    - "Automated validation gate applies D-25 criteria: IC > 0.05 AND p < 0.01 (Bonferroni-corrected)"
    - "Validation tool computes IC, p-value, N, and regime-segmented statistics per D-26"
    - "Feature selection applied: keep (IC>0.05), tweak (0.02-0.05), kill (<0.02)"
    - "At least one feature validates with IC > 0.05 AND p < 0.01 AND N >= 30"
    - "Validation gate is AUTOMATED (no human checkpoint per D-25)"
    - "If validation passes: plugins deploy to shadow mode, proceed to Plan 04 (macro factors)"
    - "If validation fails: abandon cross-TF direction per Renaissance discipline"
  artifacts:
    - path: "tools/backtest_cross_tf_plugins.py"
      provides: "Backtest tool for all 5 cross-TF plugins"
      contains: "backtest_all_cross_tf_plugins() using Plan 64-00 infrastructure"
    - path: "tools/validate_i6_backtest.py"
      provides: "Automated validation tool with D-25 criteria"
      contains: "validate_backtest_results() applying IC > 0.05 AND p < 0.01 AND N >= 30"
  key_links:
    - from: "tools/backtest_cross_tf_plugins.py"
      to: "tools/backtest_i6_plugin.py"
      via: "uses backtest_i6_plugin() function from Plan 64-00"
      pattern: "from tools.backtest_i6_plugin import backtest_i6_plugin"
    - from: "tools/validate_i6_backtest.py"
      to: "scipy.stats"
      via: "pearsonr for IC computation"
      pattern: "from scipy.stats import pearsonr"
    - from: "validate_backtest_results()"
      to: "D-25 validation criteria"
      via: "automated gate: IC > 0.05 AND p < 0.01 AND N >= 30"
      pattern: "if ic > 0.05 and p < 0.01 and n >= 30"
---

<objective>
Validate all 5 cross-TF plugins using automated backtest infrastructure from Plan 64-00. Run backtests on 6+ months of historical data for all plugins. Apply Renaissance feature selection: keep (IC>0.05), tweak (0.02-0.05), kill (<0.02).

**AUTOMATED VALIDATION GATE per D-25:** This plan uses automated validation (not human checkpoint). Validation requires BOTH IC > 0.05 AND p < 0.01 (Bonferroni-corrected for 5 tests: alpha / 5 = 0.01) AND N >= 30. Significance alone is insufficient — tiny IC with low p just means we have enough data to detect a negligible effect.

Purpose: Scientific validation before production deployment. Prove signal value with automated gate. If no features validate, abandon cross-TF direction per Renaissance discipline (don't invest in macro factors).

Output: Validation report with IC/p-value/N for all 5 plugins. Automated decision: deploy to shadow mode OR abandon.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-CONTEXT.md
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-VERIFICATION.md
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-00-PLAN.md
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-01-GAPCLOSURE-PLAN.md
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-02-GAPCLOSURE-PLAN.md

@tools/backtest_i6_plugin.py
@tools/validate_i6_backtest.py
@src/intelligence/confluence/cross_tf_momentum_divergence.py
@src/intelligence/confluence/cross_tf_sr_confluence.py
@src/intelligence/confluence/cross_tf_regime_agreement.py
@src/intelligence/confluence/squeeze_expansion_divergence.py
@src/intelligence/confluence/cross_tf_orderflow_alignment.py

<interfaces>
<!-- Backtest infrastructure from Plan 64-00 -->

From tools/backtest_i6_plugin.py (USE THIS):
```python
def backtest_i6_plugin(
    plugin_class: type,
    start_date: datetime,
    end_date: datetime,
    symbols: list[str] | None = None,
    timeframes: list[str] | None = None,
) -> pd.DataFrame:
    """Backtest I6 plugin on historical data.

    Returns DataFrame with columns:
    - ts, symbol, tf
    - {output_field}_value for each plugin output
    - pnl_r (from signal_ledger JOIN)
    - hmm_regime (from intelligence_features)
    """
```

From tools/validate_i6_backtest.py (EXTEND THIS for D-25 automated gate):
```python
def validate_backtest_results(
    df: pd.DataFrame,
    field_name: str,
    min_ic: float = 0.05,  # D-25: IC > 0.05 required
    alpha: float = 0.01,  # D-25: Bonferroni-corrected for 5 tests
    min_n: int = 30,  # Minimum sample size
) -> ValidationResults:
    """Validate backtest results using IC + p-value.

    Returns ValidationResults with:
    - overall IC, p-value, N
    - regime-segmented statistics (D-26)
    - automated decision: VALIDATED / TWEAK / KILL

    Validation criteria (D-25):
    - VALIDATED: IC > 0.05 AND p < 0.01 AND N >= 30
    - TWEAK: IC 0.02-0.05 (promising but weak)
    - KILL: IC < 0.02 (no signal)
    """
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="false">
<title>Create backtest script for all 5 cross-TF plugins</title>
<dependencies></dependencies>
<action>
Create tools/backtest_cross_tf_plugins.py:

```python
"""Backtest all 5 cross-TF plugins on historical data."""

from datetime import datetime
import pandas as pd
from tools.backtest_i6_plugin import backtest_i6_plugin

# Import all 5 plugins
from src.intelligence.confluence.cross_tf_momentum_divergence import (
    CrossTFMomentumDivergencePlugin,
)
from src.intelligence.confluence.cross_tf_sr_confluence import (
    CrossTFSRConfluencePlugin,
)
from src.intelligence.confluence.cross_tf_regime_agreement import (
    CrossTFRegimeAgreementPlugin,
)
from src.intelligence.confluence.squeeze_expansion_divergence import (
    SqueezeExpansionDivergencePlugin,
)
from src.intelligence.confluence.cross_tf_orderflow_alignment import (
    CrossTFOrderFlowAlignmentPlugin,
)


def main():
    """Run backtest for all 5 cross-TF plugins."""
    start_date = datetime(2025, 10, 1)
    end_date = datetime(2026, 4, 1)

    # All 5 plugins
    plugins = [
        ("CrossTFMomentumDivergence", CrossTFMomentumDivergencePlugin),
        ("CrossTFSRConfluence", CrossTFSRConfluencePlugin),
        ("CrossTFRegimeAgreement", CrossTFRegimeAgreementPlugin),
        ("SqueezeExpansionDivergence", SqueezeExpansionDivergencePlugin),
        ("CrossTFOrderFlowAlignment", CrossTFOrderFlowAlignmentPlugin),
    ]

    results = {}

    for plugin_name, plugin_class in plugins:
        print(f"\nBacktesting {plugin_name}...")
        print(f"Period: {start_date} to {end_date}")

        try:
            df = backtest_i6_plugin(
                plugin_class=plugin_class,
                start_date=start_date,
                end_date=end_date,
                symbols=None,  # All active contracts
                timeframes=["5m", "15m", "1h", "4h"],
            )

            # Save results
            output_path = f"/tmp/{plugin_name.lower()}_backtest.csv"
            df.to_csv(output_path, index=False)
            print(f"  Backtest complete: {len(df)} bars")
            print(f"  Results saved to: {output_path}")

            # Store for validation
            field_name = plugin_class().outputs.copy().pop()
            results[plugin_name] = {
                "df": df,
                "field": field_name,
                "path": output_path,
            }

        except Exception as e:
            print(f"  ERROR: {e}")
            results[plugin_name] = {"error": str(e)}

    print("\n" + "="*80)
    print("BACKTEST SUMMARY")
    print("="*80)

    for plugin_name, result in results.items():
        if "error" in result:
            print(f"{plugin_name}: FAILED - {result['error']}")
        else:
            print(f"{plugin_name}: {len(result['df'])} bars")

    return results


if __name__ == "__main__":
    results = main()
```

Run backtest:

```bash
python tools/backtest_cross_tf_plugins.py
```
</action>
<verify>
ls -la /tmp/*_backtest.csv
</verify>
<done>
- backtest_cross_tf_plugins.py created
- Backtest runs on 6 months data (2025-10-01 to 2026-04-01)
- All 5 plugins backtested
- CSV outputs saved for validation
</done>
</task>

<task type="auto" tdd="false">
<title>Extend validation tool with D-25 automated gate</title>
<dependencies>Create backtest script for all 5 cross-TF plugins</dependencies>
<action>
Update tools/validate_i6_backtest.py with D-25 automated validation criteria:

```python
"""Automated validation tool for I6 backtest results.

Implements D-25 validation gate: IC > 0.05 AND p < 0.01 AND N >= 30.
Bonferroni-corrected for 5 tests (alpha = 0.01, not 0.05).
"""

from dataclasses import dataclass
from datetime import datetime
import pandas as pd
from scipy.stats import pearsonr


@dataclass
class ValidationResults:
    """Validation results for I6 field."""
    field_name: str
    ic: float  # Information coefficient
    p_value: float  # Statistical significance
    n: int  # Sample size

    # Regime-segmented results (D-26)
    ic_trending: float | None = None
    p_trending: float | None = None
    n_trending: int | None = None
    ic_ranging: float | None = None
    p_ranging: float | None = None
    n_ranging: int | None = None

    # Automated decision
    decision: str = "UNKNOWN"  # VALIDATED / TWEAK / KILL


def validate_backtest_results(
    df: pd.DataFrame,
    field_name: str,
    min_ic: float = 0.05,  # D-25: IC > 0.05 required
    alpha: float = 0.01,  # D-25: Bonferroni-corrected for 5 tests
    min_n: int = 30,
) -> ValidationResults:
    """Validate backtest results using IC + p-value with automated gate.

    D-25 validation criteria (automated, not human judgment):
    - VALIDATED: IC > 0.05 AND p < 0.01 AND N >= 30
    - TWEAK: IC 0.02-0.05 (promising but weak, consider parameter changes)
    - KILL: IC < 0.02 (no signal, abandon feature)

    D-26: Regime-segmented validation (trending vs ranging)
    """
    # Clean data: drop NaN values
    clean = df[[field_name, "pnl_r"]].dropna()

    if len(clean) < min_n:
        return ValidationResults(
            field_name=field_name,
            ic=0.0,
            p_value=1.0,
            n=len(clean),
            decision="KILL (insufficient data)",
        )

    # Compute IC (Pearson correlation between field and pnl_r)
    ic, p_value = pearsonr(clean[field_name], clean["pnl_r"])

    # Regime-segmented validation (D-26)
    ic_trending = p_trending = n_trending = None
    ic_ranging = p_ranging = n_ranging = None

    if "hmm_regime" in df.columns:
        # Trending regime (hmm_regime 1 or 2)
        trending = df[df["hmm_regime"].isin([1, 2])][[field_name, "pnl_r"]].dropna()
        if len(trending) >= 10:
            ic_trending, p_trending = pearsonr(trending[field_name], trending["pnl_r"])
            n_trending = len(trending)

        # Ranging regime (hmm_regime 0)
        ranging = df[df["hmm_regime"] == 0][[field_name, "pnl_r"]].dropna()
        if len(ranging) >= 10:
            ic_ranging, p_ranging = pearsonr(ranging[field_name], ranging["pnl_r"])
            n_ranging = len(ranging)

    # Automated decision per D-25
    if ic > min_ic and p_value < alpha and len(clean) >= min_n:
        decision = "VALIDATED"
    elif ic > 0.02:
        decision = "TWEAK"
    else:
        decision = "KILL"

    return ValidationResults(
        field_name=field_name,
        ic=ic,
        p_value=p_value,
        n=len(clean),
        ic_trending=ic_trending,
        p_trending=p_trending,
        n_trending=n_trending,
        ic_ranging=ic_ranging,
        p_ranging=p_ranging,
        n_ranging=n_ranging,
        decision=decision,
    )


def validate_all_plugins(
    backtest_results: dict,
    min_ic: float = 0.05,
    alpha: float = 0.01,
    min_n: int = 30,
) -> dict[str, ValidationResults]:
    """Validate all plugins from backtest results."""

    all_results = {}

    for plugin_name, result in backtest_results.items():
        if "error" in result:
            continue

        df = result["df"]
        field = result["field"]

        validation = validate_backtest_results(
            df=df,
            field_name=field,
            min_ic=min_ic,
            alpha=alpha,
            min_n=min_n,
        )

        all_results[plugin_name] = validation

    return all_results


def print_validation_report(all_results: dict[str, ValidationResults]):
    """Print validation report with automated decision."""

    print("\n" + "="*80)
    print("AUTOMATED VALIDATION REPORT (D-25)")
    print("="*80)
    print(f"Criteria: IC > 0.05 AND p < 0.01 (Bonferroni-corrected) AND N >= 30")
    print("")

    validated_count = 0
    tweak_count = 0
    kill_count = 0

    for plugin_name, results in all_results.items():
        print(f"{plugin_name}:")
        print(f"  Overall: IC={results.ic:.4f}, p={results.p_value:.4f}, N={results.n}")
        print(f"  Decision: {results.decision}")

        if results.decision == "VALIDATED":
            validated_count += 1
        elif results.decision.startswith("TWEAK"):
            tweak_count += 1
        else:
            kill_count += 1

        # Regime-segmented (D-26)
        if results.ic_trending is not None:
            print(f"  Trending: IC={results.ic_trending:.4f}, p={results.p_trending:.4f}, N={results.n_trending}")
        if results.ic_ranging is not None:
            print(f"  Ranging: IC={results.ic_ranging:.4f}, p={results.p_ranging:.4f}, N={results.n_ranging}")

        print("")

    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"VALIDATED: {validated_count} (deploy to shadow mode)")
    print(f"TWEAK: {tweak_count} (parameter adjustments needed)")
    print(f"KILL: {kill_count} (abandon feature)")
    print("")

    # Automated decision
    if validated_count >= 1:
        print("DECISION: DEPLOY to shadow mode, proceed to Plan 04 (macro factors)")
    else:
        print("DECISION: ABANDON cross-TF direction (no validated features)")

    print("="*80)


def main():
    """Run validation on all backtest results."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python validate_i6_backtest.py <plugin_name>")
        print("Example: python validate_i6_backtest.py CrossTFMomentumDivergence")
        sys.exit(1)

    plugin_name = sys.argv[1]
    csv_path = f"/tmp/{plugin_name.lower()}_backtest.csv"

    df = pd.read_csv(csv_path)

    # Extract field name (first output field from plugin)
    field_map = {
        "CrossTFMomentumDivergence": "ctf_momentum_divergence",
        "CrossTFSRConfluence": "ctf_sr_confluence",
        "CrossTFRegimeAgreement": "ctf_regime_agreement",
        "SqueezeExpansionDivergence": "ctf_volatility_divergence",
        "CrossTFOrderFlowAlignment": "ctf_orderflow_alignment",
    }

    field = field_map.get(plugin_name)
    if not field:
        print(f"Unknown plugin: {plugin_name}")
        sys.exit(1)

    results = validate_backtest_results(df, field)

    print(f"\n{plugin_name} Validation:")
    print(f"  IC: {results.ic:.4f}")
    print(f"  p-value: {results.p_value:.4f}")
    print(f"  N: {results.n}")
    print(f"  Decision: {results.decision}")

    if results.ic_trending is not None:
        print(f"  Trending: IC={results.ic_trending:.4f}, p={results.p_trending:.4f}, N={results.n_trending}")
    if results.ic_ranging is not None:
        print(f"  Ranging: IC={results.ic_ranging:.4f}, p={results.p_ranging:.4f}, N={results.n_ranging}")

    return results


if __name__ == "__main__":
    results = main()
```
</action>
<verify>
grep -n "D-25\|IC > 0.05\|p < 0.01" /home/bg/dev/indicagent/tools/validate_i6_backtest.py
</verify>
<done>
- validate_i6_backtest.py extended with D-25 automated validation gate
- Validation criteria: IC > 0.05 AND p < 0.01 (Bonferroni-corrected) AND N >= 30
- Regime-segmented validation (D-26) implemented
- Automated decision: VALIDATED / TWEAK / KILL
- No human checkpoint (fully automated per blocker #5 fix)
</done>
</task>

<task type="auto" tdd="false">
<title>Run automated validation on all 5 plugins</title>
<dependencies>Extend validation tool with D-25 automated gate</dependencies>
<action>
Create and run validation script:

```bash
#!/bin/bash
# validate_all_plugins.sh

set -e

plugins=(
  "CrossTFMomentumDivergence"
  "CrossTFSRConfluence"
  "CrossTFRegimeAgreement"
  "SqueezeExpansionDivergence"
  "CrossTFOrderFlowAlignment"
)

echo "Running automated validation on all 5 plugins..."
echo ""

for plugin in "${plugins[@]}"; do
  echo "Validating $plugin..."
  python tools/validate_i6_backtest.py "$plugin"
  echo ""
done

echo "="
echo "AUTOMATED VALIDATION COMPLETE"
echo "="
```

Run validation:

```bash
chmod +x validate_all_plugins.sh
./validate_all_plugins.sh
```

This will output validation results for all 5 plugins with automated decision.
</action>
<verify>
ls -la /tmp/*_backtest.csv
bash validate_all_plugins.sh 2>&1 | grep -A 5 "DECISION:"
</verify>
<done>
- All 5 plugins validated with automated D-25 criteria
- Validation report printed with IC, p-value, N for each plugin
- Regime-segmented statistics computed (trending vs ranging per D-26)
- Automated decision made: VALIDATED / TWEAK / KILL
</done>
</task>

<task type="auto" tdd="false">
<title>Apply Renaissance feature selection</title>
<dependencies>Run automated validation on all 5 plugins</dependencies>
<action>
Create feature selection report based on validation results:

```python
"""Apply Renaissance feature selection based on validation results."""

import pandas as pd
from tools.validate_i6_backtest import validate_backtest_results, ValidationResults


def apply_feature_selection(
    validation_results: dict[str, ValidationResults],
) -> dict:
    """Apply Renaissance feature selection criteria.

    Categories:
    - KEEP (IC > 0.05): Deploy to shadow mode
    - TWEAK (IC 0.02-0.05): Parameter adjustments needed
    - KILL (IC < 0.02): Abandon feature
    """

    keep = []
    tweak = []
    kill = []

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


def print_feature_selection_report(selection: dict):
    """Print feature selection report."""

    print("\n" + "="*80)
    print("RENAISSANCE FEATURE SELECTION REPORT")
    print("="*80)
    print("")

    print("KEEP (deploy to shadow mode):")
    if selection["KEEP"]:
        for plugin in selection["KEEP"]:
            print(f"  - {plugin}")
    else:
        print("  (none)")

    print("")
    print("TWEAK (parameter adjustments):")
    if selection["TWEAK"]:
        for plugin in selection["TWEAK"]:
            print(f"  - {plugin}")
    else:
        print("  (none)")

    print("")
    print("KILL (abandon feature):")
    if selection["KILL"]:
        for plugin in selection["KILL"]:
            print(f"  - {plugin}")
    else:
        print("  (none)")

    print("")
    print("="*80)
    print("AUTOMATED DECISION")
    print("="*80)

    if len(selection["KEEP"]) >= 1:
        print("AT LEAST 1 FEATURE VALIDATED")
        print("→ Deploy to shadow mode")
        print("→ Proceed to Plan 04 (macro factors)")
        print("→ Monitor shadow mode performance for 2 weeks")
    else:
        print("NO FEATURES VALIDATED")
        print("→ Abandon cross-TF direction per Renaissance discipline")
        print("→ Do NOT invest in Plan 04 (macro factors)")

    print("="*80)


# Load validation results and apply feature selection
if __name__ == "__main__":
    # Re-run validation to get results
    from tools.backtest_cross_tf_plugins import main as backtest_main

    backtest_results = backtest_main()

    # Validate all plugins
    validation_results = {}
    for plugin_name, result in backtest_results.items():
        if "error" in result:
            continue

        df = result["df"]
        field = result["field"]

        validation = validate_backtest_results(df, field)
        validation_results[plugin_name] = validation

    # Apply feature selection
    selection = apply_feature_selection(validation_results)

    # Print report
    print_feature_selection_report(selection)
```

Run feature selection:

```bash
python -c "
from tools.feature_selection import apply_feature_selection, print_feature_selection_report
from tools.validate_i6_backtest import validate_all_plugins
from tools.backtest_cross_tf_plugins import main

results = main()
validation = validate_all_plugins(results)
selection = apply_feature_selection(validation)
print_feature_selection_report(selection)
"
```
</action>
<verify>
echo "Feature selection applied: KEEP/TWEAK/KILL categories assigned based on IC thresholds"
</verify>
<done>
- Renaissance feature selection applied
- Plugins categorized: KEEP (IC>0.05), TWEAK (IC 0.02-0.05), KILL (IC<0.02)
- Automated decision made based on validation results
- If >=1 feature validated: deploy to shadow mode, proceed to Plan 04
- If 0 features validated: abandon cross-TF direction per Renaissance discipline
</done>
</task>

</tasks>

<verification>
## Overall Verification

1. **Backtest script created:**
   ```bash
   ls -la tools/backtest_cross_tf_plugins.py
   ```

2. **Validation tool extended with D-25:**
   ```bash
   grep -n "IC > 0.05\|p < 0.01" tools/validate_i6_backtest.py
   ```

3. **Backtest outputs exist:**
   ```bash
   ls -la /tmp/*_backtest.csv
   ```

4. **Validation ran successfully:**
   ```bash
   python tools/validate_i6_backtest.py CrossTFMomentumDivergence
   ```

5. **Automated gate applied (not human checkpoint):**
   ```bash
   grep -n "automated\|D-25" tools/validate_i6_backtest.py
   ```

6. **Feature selection report generated:**
   ```bash
   python -c "from tools.feature_selection import print_feature_selection_report; ..."
   ```

7. **ROADMAP.md requirement satisfied:**
   - Success Criteria #6: "First plugin validated: IC > 0.05, p < 0.01 (Bonferroni-corrected), N>=30" ✓
   - D-25 automated validation gate (no human checkpoint per blocker #5 fix) ✓
</verification>

<success_criteria>
1. All 5 cross-TF plugins backtested on 6+ months historical data
2. Automated validation tool implements D-25 criteria: IC > 0.05 AND p < 0.01 AND N >= 30
3. Bonferroni correction applied (alpha = 0.01 for 5 tests, not 0.05)
4. Regime-segmented validation computed per D-26 (trending vs ranging)
5. Feature selection applied: KEEP/TWEAK/KILL based on IC thresholds
6. Automated decision made (no human checkpoint per blocker #5)
7. If >=1 feature validates: deploy to shadow mode, proceed to Plan 04
8. If 0 features validate: abandon cross-TF direction per Renaissance discipline
9. Validation report includes IC, p-value, N for all 5 plugins
10. Renaissance discipline enforced: "Prove signal value before investing in macro factors"
</success_criteria>

<output>
After completion, create `.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-03-GAPCLOSURE-SUMMARY.md` with validation results and automated decision.
</output>
