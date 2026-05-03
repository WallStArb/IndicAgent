---
phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service
plan: 02-GAPCLOSURE
type: execute
wave: 2
depends_on: ["64-01-GAPCLOSURE"]
files_modified:
  - src/intelligence/confluence/cross_tf_sr_confluence.py
  - src/intelligence/confluence/cross_tf_regime_agreement.py
  - src/intelligence/confluence/squeeze_expansion_divergence.py
  - src/intelligence/confluence/cross_tf_orderflow_alignment.py
  - src/intelligence/schemas.py
  - src/intelligence/register_plugins.py
  - src/intelligence/trading/confidence_utils.py
  - tests/unit/intelligence/test_cross_tf_sr_confluence.py
  - tests/unit/intelligence/test_cross_tf_regime_agreement.py
  - tests/unit/intelligence/test_squeeze_expansion_divergence.py
  - tests/unit/intelligence/test_cross_tf_orderflow_alignment.py
autonomous: true
requirements: []

must_haves:
  truths:
    - "All 4 Tier 1 cross-TF plugins implemented with continuous gradient scoring"
    - "CrossTFSRConfluence plugin detects HTF/LTF support/resistance alignment"
    - "CrossTFRegimeAgreement plugin detects HMM regime agreement across timeframes"
    - "SqueezeExpansionDivergence plugin detects volatility squeeze/expansion divergence"
    - "CrossTFOrderFlowAlignment plugin detects order flow (OFI/CVD) alignment across TFs"
    - "Each plugin outputs 2 fields: continuous score [-1,+1] and categorical regime label"
    - "All plugins extend CrossTimeframeConfluencePlugin pattern"
    - "I6Confluence schema extended with 8 new fields (4 plugins × 2 outputs each)"
    - "All plugins registered in TIER_I6 and validated by registry.validate_tier()"
    - "_shadow dict capture extended for all new I6 fields"
    - "Unit tests pass for all 4 plugins with mock frames data"
    - "Backtest infrastructure can replay all plugins on historical data"
  artifacts:
    - path: "src/intelligence/confluence/cross_tf_sr_confluence.py"
      provides: "CrossTFSRConfluence plugin"
      contains: "CrossTFSRConfluencePlugin class with compute_full() implementing gradient scoring"
    - path: "src/intelligence/confluence/cross_tf_regime_agreement.py"
      provides: "CrossTFRegimeAgreement plugin"
      contains: "CrossTFRegimeAgreementPlugin class with compute_full() implementing gradient scoring"
    - path: "src/intelligence/confluence/squeeze_expansion_divergence.py"
      provides: "SqueezeExpansionDivergence plugin"
      contains: "SqueezeExpansionDivergencePlugin class with compute_full() implementing gradient scoring"
    - path: "src/intelligence/confluence/cross_tf_orderflow_alignment.py"
      provides: "CrossTFOrderFlowAlignment plugin"
      contains: "CrossTFOrderFlowAlignmentPlugin class with compute_full() implementing gradient scoring"
    - path: "src/intelligence/schemas.py"
      provides: "I6Confluence schema extended with 8 new fields"
      contains: "ctf_sr_confluence, ctf_sr_regime, ctf_regime_agreement, ctf_regime_agreement_label, ctf_volatility_divergence, ctf_volatility_regime, ctf_orderflow_alignment, ctf_orderflow_regime"
    - path: "src/intelligence/register_plugins.py"
      provides: "Plugin registration for all 4 plugins"
      contains: "All 4 plugins in TIER_I6 list"
  key_links:
    - from: "All 4 new plugins"
      to: "src/intelligence/confluence/cross_timeframe.py"
      via: "imports CrossTimeframeConfluencePlugin pattern"
      pattern: "from src.intelligence.confluence.cross_timeframe import"
    - from: "All 4 new plugins"
      to: "frames['intel_*']"
      via: "read I1/I2/I4/I5 context from frames"
      pattern: "frames['intel_i4'], frames['intel_i2']"
    - from: "All 4 new plugins"
      to: "IntelligencePipelineComputeAgent"
      via: "Wave 4 execution, called by _collect_plugin_results()"
      pattern: "compute_full(frames)"
    - from: "All new I6 fields"
      to: "signal_ledger._shadow"
      via: "capture_signal_features() extension"
      pattern: "_shadow['ctf_*']"
---

<objective>
Implement remaining 4 Tier 1 cross-TF plugins per ROADMAP.md Success Criteria #3 and D-01. All plugins use continuous gradient scoring (not binary) and follow CrossTimeframeConfluencePlugin pattern. Each plugin outputs 2 fields: continuous score [-1,+1] and categorical regime label for ML segmentation.

Per ROADMAP.md: "4 additional cross-TF plugins after Plan 01 validation gate passes"
Per D-01: "Plan 02: Remaining 4 Tier 1 cross-TF plugins (CrossTFSRConfluence, CrossTFRegimeAgreement, SqueezeExpansionDivergence, CrossTFOrderFlowAlignment)"

Plugins:
1. **CrossTFSRConfluence** — HTF/LTF support/resistance alignment using I4 pivot S/R levels
2. **CrossTFRegimeAgreement** — HMM regime agreement across timeframes using I4 hmm_regime
3. **SqueezeExpansionDivergence** — Volatility squeeze/expansion divergence using I4 ATR/shannon_entropy
4. **CrossTFOrderFlowAlignment** — Order flow (OFI/CVD) alignment across TFs using I1 OFI/CVD

All plugins execute in Wave 4 within IntelligencePipelineComputeAgent (in-process, zero new infra per D-04).

Purpose: Complete Tier 1 cross-TF plugin suite. If validation passes (IC > 0.05 AND p < 0.01 per D-25), proceed to macro factors (Plan 03). If no signal, abandon cross-TF direction per Renaissance discipline.

Output: 4 working plugins deployed to shadow mode, validated on historical data, _shadow capture enabled for ML.
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
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-01-GAPCLOSURE-PLAN.md

@src/intelligence/confluence/cross_timeframe.py
@src/intelligence/confluence/cross_tf_momentum_divergence.py
@src/intelligence/schemas.py
@src/intelligence/register_plugins.py
@src/intelligence/trading/confidence_utils.py

<interfaces>
<!-- CrossTimeframeConfluencePlugin pattern (same as Plan 64-01) -->

From src/intelligence/confluence/cross_tf_momentum_divergence.py (USE THIS PATTERN):
```python
@dataclass
class CrossTFMomentumDivergencePlugin(CrossTimeframeConfluencePlugin):
    name: str = "i6_CrossTFMomentumDivergence"
    outputs: frozenset[str] = frozenset({
        "ctf_momentum_divergence",
        "ctf_momentum_regime",
    })
    min_lookback: int = 20

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        # Read frames["intel_i2"], frames["intel_i4"], etc.
        # Compute gradient score using np.tanh() or other continuous function
        # Return dict with 2 fields: continuous score + categorical label
```

From src/intelligence/schemas.py (EXTEND this):
```python
class I6Confluence(BaseModel):
    # ... existing fields ...
    # Plan 64-01 fields ...
    ctf_momentum_divergence: float | None = None
    ctf_momentum_regime: str | None = None

    # ADD 8 NEW FIELDS (4 plugins × 2 outputs):
    # CrossTFSRConfluence
    ctf_sr_confluence: float | None = None  # [-1, +1] HTF-LTF S/R alignment
    ctf_sr_regime: str | None = None  # aligned/divergent/no_sr

    # CrossTFRegimeAgreement
    ctf_regime_agreement: float | None = None  # [-1, +1] HMM regime agreement
    ctf_regime_agreement_label: str | None = None  # all_trending/all_ranging/mixed

    # SqueezeExpansionDivergence
    ctf_volatility_divergence: float | None = None  # [-1, +1] squeeze/expansion divergence
    ctf_volatility_regime: str | None = None  # both_squeezing/both_expanding/squeeze_htf_expand_ltf/squeeze_ltf_expand_htf

    # CrossTFOrderFlowAlignment
    ctf_orderflow_alignment: float | None = None  # [-1, +1] OFI/CVD alignment
    ctf_orderflow_regime: str | None = None  # aligned_bull/aligned_bear/divergent/missing_data
```
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
<title>Create CrossTFSRConfluence plugin</title>
<dependencies></dependencies>
<action>
Create src/intelligence/confluence/cross_tf_sr_confluence.py:

```python
"""Cross-TF Support/Resistance Confluence Plugin.

Detects support/resistance level alignment between HTF and LTF.
Uses I4 pivot S/R levels to measure price proximity to key levels.

Outputs:
    ctf_sr_confluence: float [-1, +1]
        - Positive: Both HTF and LTF near resistance
        - Negative: Both HTF and LTF near support
        - Near 0: No S/R confluence
    ctf_sr_regime: str
        - aligned_both_resistance: HTF+LTF at resistance
        - aligned_both_support: HTF+LTF at support
        - aligned_htf_only: Only HTF at S/R
        - aligned_ltf_only: Only LTF at S/R
        - no_confluence: No S/R proximity
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.intelligence.confluence.cross_timeframe import CrossTimeframeConfluencePlugin


@dataclass
class CrossTFSRConfluencePlugin(CrossTimeframeConfluencePlugin):
    """Cross-TF support/resistance confluence detector."""

    name: str = "i6_CrossTFSRConfluence"
    outputs: frozenset[str] = frozenset({
        "ctf_sr_confluence",
        "ctf_sr_regime",
    })
    min_lookback: int = 20

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Compute S/R confluence across timeframes."""
        i4_context = frames.get("intel_i4", {})
        ohlcv = frames.get("intel_ohlcv", {})

        sr_scores = {}

        for tf in ["5m", "15m", "1h", "4h"]:
            if tf not in i4_context or tf not in ohlcv:
                continue

            i4_tf = i4_context[tf]
            if not isinstance(i4_tf, dict):
                continue

            # Get current price and S/R levels
            bar = ohlcv[tf]
            if not isinstance(bar, dict):
                continue

            close = bar.get("close", 0)
            if close == 0:
                continue

            resistance = i4_tf.get("pivot_r1", i4_tf.get("pivot_r2", 0))
            support = i4_tf.get("pivot_s1", i4_tf.get("pivot_s2", 0))

            if resistance == 0 or support == 0:
                continue

            # Compute proximity to S/R (within 1 ATR)
            atr = i4_tf.get("atr", 1)
            dist_to_resistance = (resistance - close) / atr
            dist_to_support = (close - support) / atr

            # Score: positive near resistance, negative near support
            # Use 1.0 / (distance + 1) for proximity decay (D-17)
            if dist_to_resistance >= 0 and dist_to_resistance <= 1.0:
                sr_score = 1.0 / (dist_to_resistance + 1.0)
            elif dist_to_support >= 0 and dist_to_support <= 1.0:
                sr_score = -1.0 / (dist_to_support + 1.0)
            else:
                sr_score = 0.0

            sr_scores[tf] = sr_score

        if not sr_scores:
            return {
                "ctf_sr_confluence": 0.0,
                "ctf_sr_regime": "no_confluence",
            }

        # Separate HTF and LTF scores
        htf_scores = [sr_scores.get(tf, 0.0) for tf in ["1h", "4h"] if tf in sr_scores]
        ltf_scores = [sr_scores.get(tf, 0.0) for tf in ["5m", "15m"] if tf in sr_scores]

        if not htf_scores or not ltf_scores:
            return {
                "ctf_sr_confluence": 0.0,
                "ctf_sr_regime": "no_confluence",
            }

        htf_avg = np.mean(htf_scores)
        ltf_avg = np.mean(ltf_scores)

        # Confluence: both near same S/R level
        # Normalize via tanh for gradient output
        confluence = np.tanh(htf_avg + ltf_avg)

        # Regime classification
        if htf_avg > 0.5 and ltf_avg > 0.5:
            regime = "aligned_both_resistance"
        elif htf_avg < -0.5 and ltf_avg < -0.5:
            regime = "aligned_both_support"
        elif abs(htf_avg) > 0.5 and abs(ltf_avg) < 0.2:
            regime = "aligned_htf_only"
        elif abs(htf_avg) < 0.2 and abs(ltf_avg) > 0.5:
            regime = "aligned_ltf_only"
        else:
            regime = "no_confluence"

        return {
            "ctf_sr_confluence": float(confluence),
            "ctf_sr_regime": regime,
        }
```
</action>
<verify>
grep -n "class CrossTFSRConfluencePlugin" /home/bg/dev/indicagent/src/intelligence/confluence/cross_tf_sr_confluence.py
</verify>
<done>
- CrossTFSRConfluence plugin created
- Extends CrossTimeframeConfluencePlugin
- Outputs ctf_sr_confluence [-1,+1], ctf_sr_regime (5 categorical labels)
- Gradient scoring using proximity decay formula
</done>
</task>

<task type="auto" tdd="true">
<title>Create CrossTFRegimeAgreement plugin</title>
<dependencies></dependencies>
<action>
Create src/intelligence/confluence/cross_tf_regime_agreement.py:

```python
"""Cross-TF Regime Agreement Plugin.

Detects HMM regime agreement across timeframes.
Uses I4 hmm_regime to classify trending vs ranging agreement.

Outputs:
    ctf_regime_agreement: float [-1, +1]
        - Positive: All timeframes trending
        - Negative: All timeframes ranging
        - Near 0: Mixed regimes
    ctf_regime_agreement_label: str
        - all_trending: All TFs in trending regime (hmm_regime 1 or 2)
        - all_ranging: All TFs in ranging regime (hmm_regime 0)
        - mostly_trending: Majority trending
        - mostly_ranging: Majority ranging
        - mixed: Split decision
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.intelligence.confluence.cross_timeframe import CrossTimeframeConfluencePlugin


@dataclass
class CrossTFRegimeAgreementPlugin(CrossTimeframeConfluencePlugin):
    """Cross-TF regime agreement detector."""

    name: str = "i6_CrossTFRegimeAgreement"
    outputs: frozenset[str] = frozenset({
        "ctf_regime_agreement",
        "ctf_regime_agreement_label",
    })
    min_lookback: int = 1

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Compute regime agreement across timeframes."""
        i4_context = frames.get("intel_i4", {})

        regime_scores = {}

        for tf in ["5m", "15m", "1h", "4h"]:
            if tf not in i4_context:
                continue

            i4_tf = i4_context[tf]
            if not isinstance(i4_tf, dict):
                continue

            hmm_regime = i4_tf.get("hmm_regime", 0)

            # Score: trending = +1, ranging = -1
            if hmm_regime in (1, 2):  # Trending (up/down)
                regime_scores[tf] = 1.0
            elif hmm_regime == 0:  # Ranging
                regime_scores[tf] = -1.0
            else:
                regime_scores[tf] = 0.0

        if not regime_scores:
            return {
                "ctf_regime_agreement": 0.0,
                "ctf_regime_agreement_label": "mixed",
            }

        # Average regime score
        avg_regime = np.mean(list(regime_scores.values()))

        # Agreement: how much do TFs agree?
        # Use tanh for gradient output
        agreement = np.tanh(avg_regime * 2.0)  # Multiply to sharpen gradient

        # Regime classification
        if all(v > 0 for v in regime_scores.values()):
            label = "all_trending"
        elif all(v < 0 for v in regime_scores.values()):
            label = "all_ranging"
        elif avg_regime > 0.3:
            label = "mostly_trending"
        elif avg_regime < -0.3:
            label = "mostly_ranging"
        else:
            label = "mixed"

        return {
            "ctf_regime_agreement": float(agreement),
            "ctf_regime_agreement_label": label,
        }
```
</action>
<verify>
grep -n "class CrossTFRegimeAgreementPlugin" /home/bg/dev/indicagent/src/intelligence/confluence/cross_tf_regime_agreement.py
</verify>
<done>
- CrossTFRegimeAgreement plugin created
- Extends CrossTimeframeConfluencePlugin
- Outputs ctf_regime_agreement [-1,+1], ctf_regime_agreement_label (5 categorical labels)
- Gradient scoring using np.tanh()
</done>
</task>

<task type="auto" tdd="true">
<title>Create SqueezeExpansionDivergence plugin</title>
<dependencies></dependencies>
<action>
Create src/intelligence/confluence/squeeze_expansion_divergence.py:

```python
"""Squeeze/Expansion Divergence Plugin.

Detects volatility squeeze/expansion divergence between HTF and LTF.
Uses I4 ATR and shannon_entropy to classify volatility regimes.

Outputs:
    ctf_volatility_divergence: float [-1, +1]
        - Positive: HTF expanding, LTF squeezing
        - Negative: HTF squeezing, LTF expanding
        - Near 0: Both in same volatility regime
    ctf_volatility_regime: str
        - both_squeezing: Low volatility on both TFs
        - both_expanding: High volatility on both TFs
        - squeeze_htf_expand_ltf: HTF squeeze, LTF expansion (coiling)
        - squeeze_ltf_expand_htf: LTF squeeze, HTF expansion (exhaustion)
        - mixed: Unclear
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.intelligence.confluence.cross_timeframe import CrossTimeframeConfluencePlugin


@dataclass
class SqueezeExpansionDivergencePlugin(CrossTimeframeConfluencePlugin):
    """Squeeze/expansion divergence detector."""

    name: str = "i6_SqueezeExpansionDivergence"
    outputs: frozenset[str] = frozenset({
        "ctf_volatility_divergence",
        "ctf_volatility_regime",
    })
    min_lookback: int = 20

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Compute volatility squeeze/expansion divergence."""
        i4_context = frames.get("intel_i4", {})

        vol_scores = {}

        for tf in ["5m", "15m", "1h", "4h"]:
            if tf not in i4_context:
                continue

            i4_tf = i4_context[tf]
            if not isinstance(i4_tf, dict):
                continue

            # Use ATR ratio and shannon_entropy for volatility classification
            atr = i4_tf.get("atr", 0)
            entropy = i4_tf.get("shannon_entropy", 0)

            if atr == 0 or entropy == 0:
                continue

            # Normalize: low ATR + low entropy = squeeze (-1), high = expansion (+1)
            # Use percentile-based scoring (would need rolling window, simplified here)
            atr_z = np.tanh((atr - 0.02) / 0.01)  # Normalize ATR
            entropy_z = np.tanh((entropy - 0.7) / 0.2)  # Normalize entropy

            # Combined volatility score
            vol_score = (atr_z + entropy_z) / 2.0
            vol_scores[tf] = vol_score

        if not vol_scores:
            return {
                "ctf_volatility_divergence": 0.0,
                "ctf_volatility_regime": "mixed",
            }

        # Separate HTF and LTF scores
        htf_scores = [vol_scores.get(tf, 0.0) for tf in ["1h", "4h"] if tf in vol_scores]
        ltf_scores = [vol_scores.get(tf, 0.0) for tf in ["5m", "15m"] if tf in vol_scores]

        if not htf_scores or not ltf_scores:
            return {
                "ctf_volatility_divergence": 0.0,
                "ctf_volatility_regime": "mixed",
            }

        htf_avg = np.mean(htf_scores)
        ltf_avg = np.mean(ltf_scores)

        # Divergence: HTF - LTF
        divergence = np.tanh(htf_avg - ltf_avg)

        # Regime classification
        if htf_avg < -0.3 and ltf_avg < -0.3:
            regime = "both_squeezing"
        elif htf_avg > 0.3 and ltf_avg > 0.3:
            regime = "both_expanding"
        elif htf_avg < -0.3 and ltf_avg > 0.3:
            regime = "squeeze_htf_expand_ltf"
        elif htf_avg > 0.3 and ltf_avg < -0.3:
            regime = "squeeze_ltf_expand_htf"
        else:
            regime = "mixed"

        return {
            "ctf_volatility_divergence": float(divergence),
            "ctf_volatility_regime": regime,
        }
```
</action>
<verify>
grep -n "class SqueezeExpansionDivergencePlugin" /home/bg/dev/indicagent/src/intelligence/confluence/squeeze_expansion_divergence.py
</verify>
<done>
- SqueezeExpansionDivergence plugin created
- Extends CrossTimeframeConfluencePlugin
- Outputs ctf_volatility_divergence [-1,+1], ctf_volatility_regime (5 categorical labels)
- Gradient scoring using np.tanh()
</done>
</task>

<task type="auto" tdd="true">
<title>Create CrossTFOrderFlowAlignment plugin</title>
<dependencies></dependencies>
<action>
Create src/intelligence/confluence/cross_tf_orderflow_alignment.py:

```python
"""Cross-TF Order Flow Alignment Plugin.

Detects order flow (OFI/CVD) alignment across timeframes.
Uses I1 OFI and CVD to measure buying/selling pressure agreement.

Outputs:
    ctf_orderflow_alignment: float [-1, +1]
        - Positive: All TFs showing buying pressure
        - Negative: All TFs showing selling pressure
        - Near 0: Mixed order flow
    ctf_orderflow_regime: str
        - aligned_bull: All TFs bullish OFI/CVD
        - aligned_bear: All TFs bearish OFI/CVD
        - divergent: Mixed bullish/bearish across TFs
        - missing_data: Insufficient order flow data
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.intelligence.confluence.cross_timeframe import CrossTimeframeConfluencePlugin


@dataclass
class CrossTFOrderFlowAlignmentPlugin(CrossTimeframeConfluencePlugin):
    """Cross-TF order flow alignment detector."""

    name: str = "i6_CrossTFOrderFlowAlignment"
    outputs: frozenset[str] = frozenset({
        "ctf_orderflow_alignment",
        "ctf_orderflow_regime",
    })
    min_lookback: int = 10

    def compute_full(self, frames: dict[str, Any]) -> dict[str, Any]:
        """Compute order flow alignment across timeframes."""
        i1_events = frames.get("intel_i1", {})

        of_scores = {}

        for tf in ["5m", "15m", "1h", "4h"]:
            if tf not in i1_events:
                continue

            i1_tf = i1_events[tf]
            if not isinstance(i1_tf, dict):
                continue

            # Get OFI and CVD values
            ofi = i1_tf.get("ofi", 0)
            cvd = i1_tf.get("cvd", 0)

            # Score: positive OFI/CVD = bullish, negative = bearish
            # Normalize via tanh
            ofi_score = np.tanh(ofi / 1000.0)  # Normalize by typical magnitude
            cvd_score = np.tanh(cvd / 5000.0)

            # Combined order flow score
            of_score = (ofi_score + cvd_score) / 2.0
            of_scores[tf] = of_score

        if not of_scores:
            return {
                "ctf_orderflow_alignment": 0.0,
                "ctf_orderflow_regime": "missing_data",
            }

        # Average order flow score
        avg_of = np.mean(list(of_scores.values()))

        # Alignment: how much do TFs agree?
        alignment = np.tanh(avg_of * 2.0)  # Multiply to sharpen gradient

        # Regime classification
        if all(v > 0.3 for v in of_scores.values()):
            regime = "aligned_bull"
        elif all(v < -0.3 for v in of_scores.values()):
            regime = "aligned_bear"
        elif avg_of > 0.3:
            regime = "mostly_bull"
        elif avg_of < -0.3:
            regime = "mostly_bear"
        else:
            regime = "divergent"

        return {
            "ctf_orderflow_alignment": float(alignment),
            "ctf_orderflow_regime": regime,
        }
```
</action>
<verify>
grep -n "class CrossTFOrderFlowAlignmentPlugin" /home/bg/dev/indicagent/src/intelligence/confluence/cross_tf_orderflow_alignment.py
</verify>
<done>
- CrossTFOrderFlowAlignment plugin created
- Extends CrossTimeframeConfluencePlugin
- Outputs ctf_orderflow_alignment [-1,+1], ctf_orderflow_regime (5 categorical labels)
- Gradient scoring using np.tanh()
</done>
</task>

<task type="auto" tdd="true">
<title>Extend I6Confluence schema with 8 new fields</title>
<dependencies>Create CrossTFSRConfluence plugin, Create CrossTFRegimeAgreement plugin, Create SqueezeExpansionDivergence plugin, Create CrossTFOrderFlowAlignment plugin</dependencies>
<action>
Update src/intelligence/schemas.py:

Find I6Confluence class and add 8 new fields (4 plugins × 2 outputs):

```python
class I6Confluence(BaseModel):
    """I6 cross-timeframe confluence outputs."""
    model_config = ConfigDict(extra="forbid")

    # ... existing 16 fields ...
    # Plan 64-01 fields ...
    ctf_momentum_divergence: float | None = None
    ctf_momentum_regime: str | None = None

    # Plan 64-02: 4 additional cross-TF plugins (D-01)

    # CrossTFSRConfluence
    ctf_sr_confluence: float | None = None  # [-1, +1] HTF-LTF S/R alignment
    ctf_sr_regime: str | None = None  # aligned_both_resistance/aligned_both_support/aligned_htf_only/aligned_ltf_only/no_confluence

    # CrossTFRegimeAgreement
    ctf_regime_agreement: float | None = None  # [-1, +1] HMM regime agreement
    ctf_regime_agreement_label: str | None = None  # all_trending/all_ranging/mostly_trending/mostly_ranging/mixed

    # SqueezeExpansionDivergence
    ctf_volatility_divergence: float | None = None  # [-1, +1] squeeze/expansion divergence
    ctf_volatility_regime: str | None = None  # both_squeezing/both_expanding/squeeze_htf_expand_ltf/squeeze_ltf_expand_htf/mixed

    # CrossTFOrderFlowAlignment
    ctf_orderflow_alignment: float | None = None  # [-1, +1] OFI/CVD alignment
    ctf_orderflow_regime: str | None = None  # aligned_bull/aligned_bear/mostly_bull/mostly_bear/divergent
```
</action>
<verify>
grep -c "ctf_" /home/bg/dev/indicagent/src/intelligence/schemas.py
</verify>
<done>
- I6Confluence schema extended with 8 new fields
- Total I6 fields: 16 existing + 2 (Plan 64-01) + 8 (Plan 64-02) = 26 fields
- All fields follow continuous gradient [-1,+1] + categorical label pattern
</done>
</task>

<task type="auto" tdd="true">
<title>Register all 4 plugins in TIER_I6</title>
<dependencies>Extend I6Confluence schema with 8 new fields</dependencies>
<action>
Update src/intelligence/register_plugins.py:

Add all 4 new plugins to TIER_I6 list:

```python
# In TIER_I6 list:
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

TIER_I6: list[type[Plugin]] = [
    # ... existing I6 plugins ...
    CrossTFMomentumDivergencePlugin,  # Plan 64-01
    CrossTFSRConfluencePlugin,  # ADD THIS LINE (Plan 64-02)
    CrossTFRegimeAgreementPlugin,  # ADD THIS LINE (Plan 64-02)
    SqueezeExpansionDivergencePlugin,  # ADD THIS LINE (Plan 64-02)
    CrossTFOrderFlowAlignmentPlugin,  # ADD THIS LINE (Plan 64-02)
]
```

Validate registration:

```bash
python3 -c "
from src.intelligence.register_plugins import TIER_I6, validate_tier
validate_tier(TIER_I6, tier_checks={'i6': 26})  # 16 existing + 2 Plan01 + 8 Plan02
print('Tier validation: PASS (26 I6 fields)')
"
```
</action>
<verify>
grep -c "Plugin" /home/bg/dev/indicagent/src/intelligence/register_plugins.py | grep TIER_I6 -A 20
python3 -c "from src.intelligence.register_plugins import TIER_I6; print('I6 plugins:', len([p for p in TIER_I6 if 'i6_' in p.name]))"
</verify>
<done>
- All 4 plugins imported and added to TIER_I6 list
- registry.validate_tier() passes (26 I6 fields total)
- All 5 plugins execute in Wave 4 via intelligence_pipeline_agent
</done>
</task>

<task type="auto" tdd="true">
<title>Extend _shadow capture for all 8 new I6 fields</title>
<dependencies>Register all 4 plugins in TIER_I6</dependencies>
<action>
Update src/intelligence/trading/confidence_utils.py:

Extend capture_signal_features() with all 8 new fields:

```python
def capture_signal_features(
    signal: dict,
    bar: dict,
    frames: dict | None = None,
) -> dict:
    """Capture signal features for _shadow tracking."""
    _shadow = {
        # ... existing 15 keys ...
        # Plan 64-01 fields ...
    }

    # NEW: Plan 64-02 cross-TF fields (D-13, D-14)
    if frames and "intel_i6" in frames:
        i6 = frames["intel_i6"]
        if isinstance(i6, dict):
            # CrossTFSRConfluence
            if "ctf_sr_confluence" in i6 and i6["ctf_sr_confluence"] is not None:
                _shadow["ctf_sr_confluence"] = float(i6["ctf_sr_confluence"])
            if "ctf_sr_regime" in i6 and i6["ctf_sr_regime"] is not None:
                _shadow["ctf_sr_regime"] = str(i6["ctf_sr_regime"])

            # CrossTFRegimeAgreement
            if "ctf_regime_agreement" in i6 and i6["ctf_regime_agreement"] is not None:
                _shadow["ctf_regime_agreement"] = float(i6["ctf_regime_agreement"])
            if "ctf_regime_agreement_label" in i6 and i6["ctf_regime_agreement_label"] is not None:
                _shadow["ctf_regime_agreement_label"] = str(i6["ctf_regime_agreement_label"])

            # SqueezeExpansionDivergence
            if "ctf_volatility_divergence" in i6 and i6["ctf_volatility_divergence"] is not None:
                _shadow["ctf_volatility_divergence"] = float(i6["ctf_volatility_divergence"])
            if "ctf_volatility_regime" in i6 and i6["ctf_volatility_regime"] is not None:
                _shadow["ctf_volatility_regime"] = str(i6["ctf_volatility_regime"])

            # CrossTFOrderFlowAlignment
            if "ctf_orderflow_alignment" in i6 and i6["ctf_orderflow_alignment"] is not None:
                _shadow["ctf_orderflow_alignment"] = float(i6["ctf_orderflow_alignment"])
            if "ctf_orderflow_regime" in i6 and i6["ctf_orderflow_regime"] is not None:
                _shadow["ctf_orderflow_regime"] = str(i6["ctf_orderflow_regime"])

    return _shadow
```
</action>
<verify>
grep -n "ctf_sr_confluence\|ctf_regime_agreement\|ctf_volatility_divergence\|ctf_orderflow_alignment" /home/bg/dev/indicagent/src/intelligence/trading/confidence_utils.py
</verify>
<done>
- capture_signal_features() extended with all 8 new I6 fields
- All fields persisted to signal_ledger for ML training
- Total _shadow keys: 15 existing + 2 (Plan 64-01) + 8 (Plan 64-02) = 25 keys
</done>
</task>

<task type="auto" tdd="true">
<title>Create unit tests for all 4 plugins</title>
<dependencies>Extend _shadow capture for all 8 new I6 fields</dependencies>
<action>
Create unit test files for all 4 plugins:

1. tests/unit/intelligence/test_cross_tf_sr_confluence.py
2. tests/unit/intelligence/test_cross_tf_regime_agreement.py
3. tests/unit/intelligence/test_squeeze_expansion_divergence.py
4. tests/unit/intelligence/test_cross_tf_orderflow_alignment.py

Each test file should have 5-7 tests covering:
- Plugin instantiation
- All categorical regimes
- Gradient output range [-1, +1]
- Missing data handling
- Specific regime scenarios

Example for test_cross_tf_sr_confluence.py:

```python
"""Unit tests for CrossTFSRConfluence plugin."""

import pytest
from src.intelligence.confluence.cross_tf_sr_confluence import (
    CrossTFSRConfluencePlugin,
)


class TestCrossTFSRConfluence:
    """Test cross-TF S/R confluence detection."""

    @pytest.fixture
    def plugin(self):
        return CrossTFSRConfluencePlugin()

    def test_plugin_exists(self, plugin):
        """Plugin instantiates."""
        assert plugin.name == "i6_CrossTFSRConfluence"
        assert "ctf_sr_confluence" in plugin.outputs
        assert "ctf_sr_regime" in plugin.outputs

    def test_aligned_both_resistance(self, plugin):
        """Both HTF and LTF near resistance."""
        frames = {
            "intel_i4": {
                "5m": {"pivot_r1": 4510, "pivot_s1": 4500, "atr": 5},
                "15m": {"pivot_r1": 4510, "pivot_s1": 4500, "atr": 8},
                "1h": {"pivot_r1": 4510, "pivot_s1": 4500, "atr": 15},
                "4h": {"pivot_r1": 4510, "pivot_s1": 4500, "atr": 25},
            },
            "intel_ohlcv": {
                "5m": {"close": 4509},
                "15m": {"close": 4509},
                "1h": {"close": 4509},
                "4h": {"close": 4509},
            },
        }

        result = plugin.compute_full(frames)

        assert result["ctf_sr_regime"] in ("aligned_both_resistance", "aligned_htf_only", "aligned_ltf_only")
        assert result["ctf_sr_confluence"] > 0  # Positive near resistance

    # ... additional tests for all regimes, gradient range, missing data ...
```

Run all tests:

```bash
.venv/bin/pytest tests/unit/intelligence/test_cross_tf_sr_confluence.py \
                  tests/unit/intelligence/test_cross_tf_regime_agreement.py \
                  tests/unit/intelligence/test_squeeze_expansion_divergence.py \
                  tests/unit/intelligence/test_cross_tf_orderflow_alignment.py -v
```
</action>
<verify>
.venv/bin/pytest tests/unit/intelligence/test_cross_tf_sr_confluence.py -v
.venv/bin/pytest tests/unit/intelligence/test_cross_tf_regime_agreement.py -v
.venv/bin/pytest tests/unit/intelligence/test_squeeze_expansion_divergence.py -v
.venv/bin/pytest tests/unit/intelligence/test_cross_tf_orderflow_alignment.py -v
</verify>
<done>
- All 4 test files created
- Each plugin has 5-7 unit tests
- All categorical regimes covered
- Gradient output range verified [-1, +1]
- Missing data handling tested
- All pytest tests pass
</done>
</task>

</tasks>

<verification>
## Overall Verification

1. **All 4 plugins created:**
   ```bash
   ls -la src/intelligence/confluence/cross_tf_*.py
   ```

2. **Schema extended with 8 new fields:**
   ```bash
   grep -c "ctf_" src/intelligence/schemas.py  # Should show 26 total I6 fields
   ```

3. **All plugins registered:**
   ```bash
   grep -A 5 "TIER_I6" src/intelligence/register_plugins.py | grep -c "Plugin"
   ```

4. **_shadow capture extended:**
   ```bash
   grep -n "ctf_sr_confluence\|ctf_regime_agreement\|ctf_volatility_divergence\|ctf_orderflow_alignment" src/intelligence/trading/confidence_utils.py
   ```

5. **Unit tests pass:**
   ```bash
   pytest tests/unit/intelligence/test_cross_tf_*.py -v
   ```

6. **Registry validation:**
   ```bash
   python3 -c "from src.intelligence.register_plugins import validate_tier, TIER_I6; validate_tier(TIER_I6, tier_checks={'i6': 26}); print('PASS')"
   ```

7. **ROADMAP.md requirement satisfied:**
   - Success Criteria #3: "4 additional cross-TF plugins after Plan 01 validation gate passes" ✓
   - D-01: "Plan 02: Remaining 4 Tier 1 cross-TF plugins" ✓
</verification>

<success_criteria>
1. All 4 Tier 1 cross-TF plugins implemented per ROADMAP.md and D-01
2. CrossTFSRConfluence plugin created with gradient scoring
3. CrossTFRegimeAgreement plugin created with gradient scoring
4. SqueezeExpansionDivergence plugin created with gradient scoring
5. CrossTFOrderFlowAlignment plugin created with gradient scoring
6. I6Confluence schema extended with 8 new fields (26 total I6 fields)
7. All plugins registered in TIER_I6, registry validation passes
8. _shadow capture extended for all 8 new fields (25 total _shadow keys)
9. Unit tests pass for all 4 plugins (20+ tests total)
10. All plugins execute in Wave 4 via intelligence_pipeline_agent (in-process per D-04)
11. All outputs use continuous gradient scoring [-1,+1] (not binary per D-17)
</success_criteria>

<output>
After completion, create `.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-02-GAPCLOSURE-SUMMARY.md`
</output>
