---
plan: 64-02-GAPCLOSURE
phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service
status: complete
completed: 2026-04-27
---

# Plan 64-02-GAPCLOSURE: 4 Additional Cross-TF Confluence Plugins

## What Was Built

4 new Tier-1 cross-TF I6 confluence plugins, all with continuous gradient scoring (np.tanh(), not binary), registered in TIER_I6, shadow-captured:

1. **CrossTFSRConfluencePlugin** (`cross_tf_sr_confluence.py`) — S/R level proximity alignment across HTF/LTF using proximity decay scoring. Outputs `ctf_sr_confluence` [-1,+1] and `ctf_sr_regime` (5 labels).
2. **CrossTFRegimeAgreementPlugin** (`cross_tf_regime_agreement.py`) — HMM regime agreement across all TFs. Outputs `ctf_hmm_regime_agreement` [-1,+1] and `ctf_hmm_regime_label` (5 labels: all_trending/all_ranging/mostly_trending/mostly_ranging/mixed).
3. **SqueezeExpansionDivergencePlugin** (`squeeze_expansion_divergence.py`) — ATR + shannon_entropy volatility divergence HTF vs LTF. Outputs `ctf_volatility_divergence` [-1,+1] and `ctf_volatility_regime` (5 labels).
4. **CrossTFOrderFlowAlignmentPlugin** (`cross_tf_orderflow_alignment.py`) — OFI + CVD alignment across TFs normalized by typical magnitudes. Outputs `ctf_orderflow_alignment` [-1,+1] and `ctf_orderflow_regime` (5 labels).

## Schema Changes

I6Confluence extended with 8 new gradient fields:
- `ctf_sr_confluence`, `ctf_sr_regime`
- `ctf_hmm_regime_agreement`, `ctf_hmm_regime_label`
- `ctf_volatility_divergence`, `ctf_volatility_regime`
- `ctf_orderflow_alignment`, `ctf_orderflow_regime`

`capture_signal_features()` extended: shadow key count 17→25.

## Key Files

- `src/intelligence/confluence/cross_tf_sr_confluence.py`
- `src/intelligence/confluence/cross_tf_regime_agreement.py`
- `src/intelligence/confluence/squeeze_expansion_divergence.py`
- `src/intelligence/confluence/cross_tf_orderflow_alignment.py`
- `src/intelligence/schemas.py` — extended I6Confluence
- `src/intelligence/register_plugins.py` — 4 new entries in TIER_I6
- `src/intelligence/trading/confidence_utils.py` — 8 new shadow fields
- `tests/unit/intelligence/test_cross_tf_plugins.py` — 27 passing tests

## Test Results

27/27 tests pass. All plugins produce gradients in [-1,+1] and correct regime labels.

## Self-Check: PASSED

- ✓ All 4 plugins with continuous gradient scoring (np.tanh, not binary)
- ✓ I6Confluence schema extended with 8 new gradient fields
- ✓ All 4 plugins registered in TIER_I6
- ✓ capture_signal_features() extended with all 8 new shadow fields
- ✓ 27 unit tests passing
