# I8 Intelligence Extensions — Near-Term POCs

**Version:** 1.0
**Status:** draft
**Priority:** medium
**Milestone:** v1.9+
**Last Updated:** 2026-03-15
**Tags:** i8, llm, narrative, ai, intelligence, counterfactual, regime, ops

---

## Context

The I8 `ai_narrative_service` currently generates per-signal narrative and group synthesis using a 2-tier LLM chain (OpenRouter → Ollama). These are three natural extensions that use the same infrastructure — same LLM chain, same Redpanda topics, same signal/intelligence data — to add distinct intelligence value beyond narrative.

Each is a self-contained POC. They don't depend on each other.

---

## 1. Counterfactual Insight Generator

**What it does:** For every generated signal, produce a companion analysis answering "What would need to be true to validate or invalidate this setup?"

- Specifies required metric deltas: "RSI needs to cross 55, volume needs to sustain above 1.2× average"
- Suggests concrete monitoring triggers: price levels, slope conditions, time-bound confirmations
- Generates both the validation path and the invalidation path

**Why it matters:** Turns passive narrative into an active monitoring checklist. A trader reading the narrative currently gets "here's why the setup fired" — the counterfactual adds "here's exactly when to act and when to bail." Directly reduces ambiguity at decision time.

**Implementation sketch:**
- Extend `ai_narrative_service` with a second LLM call per signal (or bundle into one longer prompt)
- Output published to `intelligence.i8` topic alongside the main narrative
- Store in `llm_calls` with `call_type="counterfactual"` for outcome tracking
- Dashboard: show counterfactual inline with the signal card, collapsible

**Open questions:**
- Bundle with the narrative prompt or separate call? (Separate is cleaner for outcome tracking)
- Should counterfactuals be generated for all signals or only those above a confidence threshold?

---

## 2. Regime Change Explainer / Daily Brief

**What it does:** When HMM regime transitions occur (detected by I4), generate an LLM-authored explanation of the shift and its practical implications. Also produce a daily digest (once per session open) summarizing current regime state across all active instruments.

- **On regime transition:** "Market shifted from trending_bullish to ranging — here's why, how persistent this typically is, and what setup types to favor/avoid"
- **Daily brief:** Cross-instrument regime summary, overnight developments, session-open context
- **Links symbol-level context to macro narrative** — ES regime shift explained in terms of ZN/VIX behavior

**Why it matters:** Current system detects regime changes in I4 data but produces no human-readable explanation. A regime flip silently changes which signals fire — the regime explainer makes that change visible and interpretable.

**Implementation sketch:**
- Subscribe to `intelligence` topic; watch for HMM state transitions in the I4 JSONB field
- Trigger LLM call on state change; publish to `narratives` with `narrative_type="regime_change"`
- Daily brief: cron-triggered at session open (9:30 ET for equities, 18:00 ET for futures)
- Store in `llm_calls` for outcome attribution

**Open questions:**
- Regime change explainer should only fire on confirmed transitions (2+ bars in new state) to avoid noise from transient HMM fluctuations
- Daily brief format: structured JSON with summary + per-instrument bullets, or pure prose?

---

## 3. Anomaly Triage Assistant (Operations)

**What it does:** When the pipeline emits anomalous signals (unusual patterns in Prometheus metrics, service lag spikes, stream backlog growth, unexpected plugin error rates), generate an LLM-authored triage summary explaining likely root causes and recommended next actions.

- Consumes Prometheus metrics + service logs (structured via `logs/<service>.log`)
- Identifies likely root cause from observability signals: "indicator_service processing lag >500ms — likely GARCH convergence on high-vol bar, not a connection issue"
- Recommends action: restart, wait for recovery, investigate specific plugin, check TWS connection

**Why it matters:** Reduces time-to-diagnosis during pipeline incidents. Currently requires manually reading logs, correlating Prometheus panels, and recognizing patterns. The triage assistant makes the first-pass diagnosis automatic.

**Implementation sketch:**
- Standalone service or extension of `ai_narrative_service` (prefer standalone — different concern)
- Trigger: Prometheus alertmanager webhook OR polling Prometheus API for threshold breaches
- Output: structured triage to a `triage` Redpanda topic + Dashboard ops panel
- Not time-sensitive — 30s response latency acceptable

**Open questions:**
- What's the right trigger threshold? Don't want a triage for every minor blip.
- Could also be triggered manually via dashboard button ("explain this anomaly")
- Requires access to log files from the triage service — either read directly or tail via syslog

---

## Priority Order

1. **Counterfactual Insight Generator** — highest ROI, directly improves decision quality on existing signals, minimal infrastructure addition
2. **Regime Change Explainer** — medium effort, high value for understanding why signal mix changes
3. **Anomaly Triage Assistant** — useful but not urgent; only matters when things break
