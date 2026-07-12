#!/usr/bin/env python3
"""Cross-Sectional Regime Model — generic dispatcher that populates market_regimes.

Generalizes services/equity_regime_model.py: instead of a single hardcoded 'equity'
label, this dispatcher iterates every enabled group in APR key alpha.regime.groups
(JSON array) and writes group-scoped regime labels to market_regimes.regime_group
(migration 229 renamed asset_class -> regime_group).

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

NOTE: this file currently ships only the pure, DB-free helper functions
(_parse_group_configs / _resolve_group_symbols / _bucket / _assign_labels). The
runtime (main(), DB fetch/write, TF-scaling wiring) is added in a follow-up commit
within this same plan.
"""

from __future__ import annotations

import json

import numpy as np

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


def _bucket(vals: np.ndarray, tiers: list[tuple[str, float]]) -> np.ndarray:
    """Assign tier names by threshold. tiers sorted ascending by upper_bound; last = inf.

    A value is assigned to the first tier whose upper_bound STRICTLY exceeds the value.
    """
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
    set on EVERY emitted row (column renamed from asset_class per migration 229).
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
    labels1 = _bucket(sig1_arr, tiers1)
    labels2 = _bucket(sig2_arr, tiers2)
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
