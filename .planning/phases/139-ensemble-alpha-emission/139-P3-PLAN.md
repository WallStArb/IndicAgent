---
phase: 139-ensemble-alpha-emission
plan: P3
type: execute
wave: 3
depends_on: [P2]
files_modified:
  - docs/analysis/ic-discovery-report.md
  - docs/analysis/ic-discovery-report.json
  - services/generate_ic_discovery_report.py
autonomous: true

must_haves:
  truths:
    - "EnsembleBuilder has run against the full corpus and populated ensemble_weights + ensemble_alpha for all (symbol, tf, regime) strata with passing features"
    - "AlphaEmitter has run and populated alpha_events in shadow mode, with events also published to the alpha.events Kafka topic"
    - "effective_N >= 3.0 was enforced on every emission (no row in alpha_events has effective_n < the gate)"
    - "An IC discovery report (markdown + json) documents passing features per stratum, weight vectors, effective_N, alpha event count, and emission rate"
  artifacts:
    - path: "docs/analysis/ic-discovery-report.md"
      provides: "Human-readable IC/ensemble discovery report"
      min_lines: 30
    - path: "docs/analysis/ic-discovery-report.json"
      provides: "Machine-readable discovery metrics"
      contains: "emission_rate"
    - path: "services/generate_ic_discovery_report.py"
      provides: "Report generator querying ensemble_weights/ensemble_alpha/alpha_events"
      min_lines: 60
  key_links:
    - from: "services/generate_ic_discovery_report.py"
      to: "ensemble_weights / ensemble_alpha / alpha_events"
      via: "SQL aggregation queries"
      pattern: "FROM (ensemble_weights|ensemble_alpha|alpha_events)"
---

<objective>
Run the Phase 139 corpus pipeline end to end against the populated v3.0 training corpus, then generate the IC discovery report. This is the application/data plan: EnsembleBuilder produces weights and scores all bars, AlphaEmitter emits shadow-mode alpha events, and a report documents what the data discovered.

Purpose: Phase 139's success criteria are only fully provable with corpus data — the weights, alpha scores, effective_N distribution, and emission rate all require feature_vectors + feature_ic_scores to be populated.
Output: Populated ensemble_weights, ensemble_alpha, alpha_events tables; alpha events on the Kafka topic; services/generate_ic_discovery_report.py; and docs/analysis/ic-discovery-report.{md,json}.
</objective>

<dependency_note>
GATING DEPENDENCY — Phase 138 P8 corpus data.

This plan requires the full v3.0 corpus to exist before it can run:
- feature_vectors must be populated (the 58-ETF FeatureFactory backfill — STATE.md shows 0 rows as of 2026-06-23; backfill_feature_factory.py estimated ~20-30h).
- forward_returns must be populated (ForwardReturnWriter run over the corpus).
- feature_ic_scores must contain passing rows (ic_engine.py full run; STATE.md shows 0 rows as of 2026-06-23).

Per the planning context: "P3 (corpus scoring run) gates on Phase 138 P8 completing the full 58-ETF backfill + IC engine run." P1 and P2 are fully independent of this data and can be executed and unit-tested immediately. P3 must verify corpus presence with the startup gate before doing real work.

If the corpus is not yet present when P3 is reached, the EnsembleBuilder startup gate (built in P2 Task 1) will raise RuntimeError loudly. That is the correct behavior — do not stub or bypass it. Re-run P3 after Phase 138 P8 completes.
</dependency_note>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/139-ensemble-alpha-emission/139-RESEARCH.md
@.planning/phases/139-ensemble-alpha-emission/139-P2-PLAN.md
@services/ic_engine.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Run EnsembleBuilder and AlphaEmitter against the corpus</name>
  <read_first>
    - services/ensemble_builder.py (P2 — the __main__ entrypoint and startup gates)
    - services/alpha_emitter.py (P2 — the __main__ entrypoint, emission gate, Kafka publish)
    - .planning/STATE.md (Data State section — confirm feature_vectors / forward_returns / feature_ic_scores row counts before running; if all 0, the corpus is not ready and the gate will fire)
    - .planning/phases/139-ensemble-alpha-emission/139-RESEARCH.md (Open Questions 1 — corpus availability gating)
  </read_first>
  <action>
    First confirm the corpus is present:
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT (SELECT count(*) FROM feature_vectors) AS fv, (SELECT count(*) FROM forward_returns) AS fr, (SELECT count(*) FROM feature_ic_scores WHERE is_pooled=false AND passes_walkforward=true) AS ic_pass"
    If fv=0 or ic_pass=0, the Phase 138 P8 corpus run has not completed. Record this in the SUMMARY as a blocked state and STOP — do not stub data. The EnsembleBuilder gate enforces this loudly if run anyway.

    When the corpus is present:
    1. Run EnsembleBuilder: .venv/bin/python services/ensemble_builder.py 2>&1 | tee logs/ensemble_builder_run.log. Confirm it exits 0 and writes ensemble_weights + ensemble_alpha.
    2. Run AlphaEmitter: .venv/bin/python services/alpha_emitter.py 2>&1 | tee logs/alpha_emitter_run.log. Confirm it exits 0, writes alpha_events, and publishes to the Kafka topic.
    3. Verify the effective_N gate held: no alpha_events row has effective_n below the gate.
    4. Verify the Kafka topic received messages: docker exec redpanda rpk topic consume <env-prefixed alpha.events> --num 5 --offset start (use the env-prefixed topic name; derive via the same env_prefix the service uses).

    Both services are idempotent (ON CONFLICT DO NOTHING), so a re-run is safe if interrupted.
  </action>
  <verify>
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT count(*) FROM ensemble_weights" returns > 0 (when corpus present).
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT count(*) FROM ensemble_alpha" returns > 0.
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT count(*) FROM alpha_events WHERE effective_n < (SELECT config_value::float FROM config_state WHERE config_key='alpha.ensemble.effective_n_gate')" returns 0 (gate enforced).
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT count(*) FROM alpha_events WHERE top_features IS NULL" returns 0 (traceability invariant).
  </verify>
  <acceptance_criteria>
    - ensemble_weights row count > 0 (or SUMMARY records blocked-on-corpus state with the exact row-count query output)
    - ensemble_alpha row count > 0
    - Zero alpha_events rows with effective_n below the APR gate
    - Zero alpha_events rows with NULL top_features
    - Kafka topic alpha.events shows at least 1 consumed message (rpk consume output non-empty), OR SUMMARY documents the blocked-on-corpus state
    - Both service runs exited 0 (job_completed_total status=success in logs)
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 2: Generate IC discovery report</name>
  <read_first>
    - services/ic_engine.py (DB connection pattern, Settings.database_url handling — replicate for the report generator)
    - .planning/phases/139-ensemble-alpha-emission/139-RESEARCH.md (Phase Structure P3 lines 580-586 — report content: passing features per (symbol, tf, regime), weight vectors, effective_N per stratum, alpha event count, emission rate)
    - docs/plans/2026-06-20-alphaengine-architecture.md (Observability Contract — traceability chain lines 571-584, the metrics the report should surface)
  </read_first>
  <action>
    Create services/generate_ic_discovery_report.py — a read-only report generator (psycopg2 or asyncpg, read-only queries; not a BaseBatch service, it produces docs not DB rows). It queries:
    - Per (symbol, tf, regime): count of passing features (from ensemble_weights for the active weight_version), the weight vector (feature_name -> weight, sorted desc), effective_n.
    - Per (symbol, tf): bars scored (ensemble_alpha count), alpha events emitted (alpha_events count), emission_rate = emissions / bars_scored.
    - Overall: total strata with weights, total alpha events, mean/median effective_n, distribution of emission directions (long/short).
    Load the active weight_version from alpha.ensemble.weight_version APR.

    Write two outputs to docs/analysis/:
    - ic-discovery-report.json: structured metrics (strata array, per-symbol-tf emission stats, overall summary including emission_rate field).
    - ic-discovery-report.md: human-readable — title, run timestamp, summary table of strata, top features by weight per stratum, effective_N distribution, emission rate table, and a note that this is shadow-mode output.

    Run it: .venv/bin/python services/generate_ic_discovery_report.py. If the corpus is not present (empty ensemble tables), the report should still generate but clearly state "NO DATA — corpus not yet populated" rather than crash.
  </action>
  <verify>
    test -f docs/analysis/ic-discovery-report.md && test -f docs/analysis/ic-discovery-report.json && echo report-exists prints report-exists.
    grep -n "emission_rate" docs/analysis/ic-discovery-report.json returns a match.
    .venv/bin/python -c "import json; d=json.load(open('docs/analysis/ic-discovery-report.json')); print('summary' in d or 'overall' in d)" prints True.
    .venv/bin/ruff check services/generate_ic_discovery_report.py exits 0.
  </verify>
  <acceptance_criteria>
    - services/generate_ic_discovery_report.py exists and is read-only (no INSERT/UPDATE/CREATE statements)
    - docs/analysis/ic-discovery-report.md and ic-discovery-report.json both exist
    - JSON contains an emission_rate field and a per-stratum breakdown
    - Report generator does not crash on empty tables (emits "NO DATA" state instead)
    - `.venv/bin/ruff check services/generate_ic_discovery_report.py` exits 0
  </acceptance_criteria>
</task>

</tasks>

<verification>
- ensemble_weights, ensemble_alpha, alpha_events populated (or SUMMARY records the blocked-on-corpus state with query output)
- effective_N gate provably enforced: zero alpha_events below the APR gate
- top_features never NULL: zero violations
- Kafka alpha.events topic received messages
- IC discovery report (md + json) generated with emission_rate and per-stratum metrics
</verification>

<success_criteria>
- ensemble_weights populated with Ledoit-Wolf weights per (symbol, tf, regime, weight_version), 0.20 cap — success criterion 1
- ensemble_alpha populated with z-scored composite + CI bounds per (symbol, tf, bar_ts) — success criterion 2
- alpha_events populated in shadow mode + published to Kafka — success criterion 4
- effective_N >= 3.0 enforced before every emission (zero violations) — success criterion 5
- IC discovery report documents the discovery
</success_criteria>

<output>
After completion, create `.planning/phases/139-ensemble-alpha-emission/139-P3-SUMMARY.md`
</output>
