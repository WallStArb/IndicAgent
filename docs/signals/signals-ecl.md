# Signals — Extrinsic Confidence Layer

**Version:** 1.0
**Status:** current
**Last Updated:** 2026-06-16

---

## 1. Purpose

System reference for the Extrinsic Confidence Layer (ECL): what each vector is, where it lives in the data model, how the ML model consumes it, and how to verify the boundary invariant holds.

**Who reads this:** ML engineers writing training queries, systems engineers auditing signal quality, and plugin reviewers verifying ECL compliance. Plugin *authors* read `docs/signals/signals-confidence-patterns.md` Section 5 for the implementation contract.

---

## 2. Design Principles

ECL is not a filter. It is a feature collection system. The full design rationale — the two survivorship bias layers, why gates were rejected, the emission vs. activation distinction — is in `docs/concepts/extrinsic-confidence-layer.md`. This document covers the implementation surface only.

The single invariant: **every emitted signal carries every ECL vector, unconditionally.** A missing vector is a data integrity failure, not a valid "no data" state (with the exception of cold-start NULL semantics documented below).

---

## 3. Architecture

```
I7 plugin
  │  reads features dict (ctf_score, zone_friction_score, etc.)
  │  computes ctf_confirmed boolean
  │  emits signal dict with all ECL fields present
  ▼
IntelligencePipeline (signal_processor.py)
  │  stage: apply_regime_gate() — HMM regime gate here, post-emission
  │  stage: emit to intelligence.i7.signals topic
  ▼
signal_events (hypertable)
  │  ECL fields: ctf_score, ctf_confirmed, zone_friction_score (top-level columns)
  │  Full feature snapshot: context_features JSONB
  ▼
CounterfactualTracker (Phase 130)
  │  populates counterfactual_pnl_r on trade_frames
  │  enables ML attribution against ECL vectors
  ▼
ML training query
  │  signal_events JOIN trade_frames ON (signal_id, signal_ts)
  │  features: raw_confidence, ctf_score, ctf_confirmed, zone_friction_score
  │  target: counterfactual_pnl_r
```

<!-- src: src/intelligence/pipeline/signal_processor.py, signal_events table -->

---

## 4. Data Contracts

### ECL Vectors on `signal_events`

| Field | Type | Description | Null semantics |
|-------|------|-------------|----------------|
| `ctf_score` | `float8 \| NULL` | I6 cross-timeframe alignment score; signed, range [-1, 1]. | `NULL` = I6 had no data at emit time (cold-start, warm-up). `0.0` = genuine neutral alignment. These are different populations. Never substitute `or 0.0` for NULL. |
| `ctf_confirmed` | `bool \| NULL` | `abs(ctf_score) >= threshold.global.min_ctf_score`. Boolean feature for ML categorical attribution. | `NULL` when `ctf_score` is `NULL`. |
| `zone_friction_score` | `float8 \| NULL` | Zone friction at emit time. Higher = more structural resistance at the signal's zone. | `NULL` = no zone data at emit time. |
| `context_features` | `jsonb \| NULL` | Full `capture_signal_features()` output — the ML feature matrix including exhaustion state, AVWAP proximity, macro context, and all other extrinsic signals not promoted to top-level columns. | `NULL` only on very early cold-start bars before pipeline warms. |

<!-- src: production/migrations/137_3table_schema.sql — signal_events DDL -->

### HMM Regime Gate — Not a Vector, a Status

The HMM regime gate does not produce an ECL field. It produces a `status` transition:

- Signal written with `status = 'pending'`
- `SignalTracker` applies regime gate: if regime mismatch → `status = 'regime_suppressed'`

`hmm_regime_at_fire` and `plugin_regime_type` are stored on `signal_events` and provide the audit trail for whether the gate applied. The `regime_suppressed` status is visible to ML training queries.

<!-- src: src/intelligence/pipeline/signal_processor.py — apply_regime_gate() -->

### APR Parameters Governing ECL

| APR key | Default | Controls |
|---------|---------|----------|
| `threshold.global.min_ctf_score` | 0.25 | Threshold for computing `ctf_confirmed`. Not a gate — used to compute the boolean annotation only. |

<!-- src: src/config/config_service.py; src/intelligence/plugins/confidence_utils.py -->

---

## 5. ML Training Patterns

### Standard ECL training query

```sql
SELECT
    se.signal_id,
    se.ts,
    se.symbol,
    se.tf,
    se.setup_plugin,
    se.raw_confidence,
    se.factor_scores,
    se.ctf_score,
    se.ctf_confirmed,
    se.zone_friction_score,
    se.hmm_regime_at_fire,
    se.plugin_regime_type,
    se.status,
    tf.entry_type,
    tf.counterfactual_pnl_r,
    tf.counterfactual_mfe,
    tf.counterfactual_mae
FROM signal_events se
JOIN trade_frames tf
  ON tf.signal_id = se.signal_id
 AND tf.signal_ts = se.ts
WHERE tf.counterfactual_pnl_r IS NOT NULL;
-- Do NOT filter on se.status — regime_suppressed signals are training data.
-- Do NOT filter on se.is_shadow unless deliberately excluding shadow plugins.
```

**Critical:** do not add `WHERE se.status != 'regime_suppressed'`. Those rows are the evidence the ML model uses to learn the value of the HMM regime gate. Filtering them reintroduces Bias Layer 2.

### ECL attribution query — does CTF confirmation predict outcome?

```sql
SELECT
    ctf_confirmed,
    count(*) AS n,
    avg(tf.counterfactual_pnl_r) AS avg_pnl_r,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY tf.counterfactual_pnl_r) AS median_pnl_r
FROM signal_events se
JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
WHERE tf.counterfactual_pnl_r IS NOT NULL
  AND se.ctf_score IS NOT NULL  -- exclude cold-start NULLs
GROUP BY ctf_confirmed;
```

This query tells you whether the ML model should weight `ctf_confirmed` as a positive or negative predictor, and whether the `min_ctf_score` threshold in the APR is calibrated correctly.

### Zone friction attribution

```sql
SELECT
    width_bucket(zone_friction_score, 0, 1, 5) AS friction_bucket,
    count(*) AS n,
    avg(tf.counterfactual_pnl_r) AS avg_pnl_r
FROM signal_events se
JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
WHERE tf.counterfactual_pnl_r IS NOT NULL
  AND se.zone_friction_score IS NOT NULL
GROUP BY friction_bucket
ORDER BY friction_bucket;
```

---

## 6. Boundary Invariant Verification

### Test suite

`tests/unit/intelligence/test_i7_extrinsic_contract.py` asserts the ECL contract across all compliant I7 plugins. Run before any I7 plugin change:

```bash
.venv/bin/pytest tests/unit/intelligence/test_i7_extrinsic_contract.py -v
```

<!-- src: tests/unit/intelligence/test_i7_extrinsic_contract.py -->

### Live audit query — signals missing ECL vectors

```sql
-- Signals written in the last 24h with missing ECL fields (excluding cold-start window)
SELECT
    setup_plugin,
    count(*) AS missing_ctf,
    max(ts) AS most_recent
FROM signal_events
WHERE ts > now() - INTERVAL '24 hours'
  AND ctf_score IS NULL
  AND created_at > (SELECT min(ts) + INTERVAL '30 minutes' FROM signal_events)
GROUP BY setup_plugin
ORDER BY missing_ctf DESC;
```

Non-zero results after the cold-start window indicate a plugin that is not attaching ECL vectors at emit time — an ECL boundary violation.

---

## 7. Failure Modes

**`ctf_score IS NULL` on warm bars** — Plugin is not calling `capture_signal_features()` or is not passing `ctf_score` through to `emit_signal()`. Review plugin against the pattern in `signals-confidence-patterns.md` Section 3.

**`ctf_confirmed = NULL` when `ctf_score IS NOT NULL`** — Plugin is not computing the boolean. This makes the ML categorical feature unreliable. Check plugin `emit_signal()` call.

**`zone_friction_score` consistently NULL** — I4 zone engine may not have data for the instrument/timeframe combination, or zone data is not reaching the plugin via `features`. Check `intelligence_features.i4` for the relevant bar.

**ECL vector used as gate (most dangerous)** — Manifests as an asymmetry in the training set: the `ctf_score` distribution for fired signals is bimodal with a hard cutoff at exactly `min_ctf_score`. The attribution query above will show a sharp break at the threshold rather than a smooth gradient. Fix: audit the plugin against the anti-patterns in `signals-confidence-patterns.md` Section 8.

---

## 8. See Also

- `docs/concepts/extrinsic-confidence-layer.md` — design rationale, the two bias layers, why gates were rejected
- `docs/signals/signals-confidence-patterns.md` Section 5 — plugin implementation contract and anti-patterns
- `docs/concepts/signal-ledger-architecture.md` — why SLA + ECL together close both bias layers
- `docs/foundation/glossary.md` — ECL, ICC, survivorship bias canonical definitions
- `src/intelligence/plugins/confidence_utils.py` — `capture_signal_features()`, `compose_confidence()`
