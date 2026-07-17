# Controlled Vocabulary Open Questions Review - Two Namespaces, Not One; a Oneshot, Not a Dead Daemon

**Date:** 2026-07-16 · **Author:** Fable 5 (dispatched via Claude Code Agent tool) · **Type:** research/review, read-only
**Scope:** resolves the two open questions `161-RESEARCH.md` explicitly refused to silently settle - (1) `regime_cross_sectional` taxonomy scope given the live 15-label / two-`regime_group` finding, and (2) the drift-audit host given the new finding that no auditor-family daemon is running. Every claim verified live 2026-07-16 via psql and systemctl on the production host itself (Claude Code runs on 192.168.68.53 per CLAUDE.md; no SSH needed). Findings numbered V1-V5 to keep namespaces separate from the tag review's T1-T7 and earlier F-series.
**Verdict up front:** OQ1 resolves to neither (a) nor (b) as posed - the Label Identity Invariant forces **two namespaces seeded in this build** (`regime_cross_sectional_equity`, 9 codes + D-04's groups unchanged; `regime_cross_sectional_rates`, 6 codes + curve-shape and width groups), each drift-audited with a `regime_group` filter. OQ2 resolves to **(b)**: every candidate host daemon is verifiably dead, so "ride an existing auditor" is currently a recipe for a decorative check; build the audit as an importable module with a thin oneshot CLI entrypoint, persist to `integrity_monitor`, and chain it into the corpus pipeline script - the one hook that demonstrably runs when new labels can appear. No systemd unit gets enabled by this phase; that is an operator decision, flagged separately below.

---

## 1. Live state verified (baseline for everything below)

- `market_regimes` (psql, 2026-07-16): exactly **15 distinct `(regime_group, regime_label)` pairs** - `equity`: 9 labels (`{low,mid,high}_{bull,neutral,bear}`, 63k-850k rows each) and `rates`: 6 labels (`{flat,steep,inverted}_{tight,wide}`, 19k-618k rows each). Research's "14-15" hedge resolves to 15. Both groups' `max(ts)` = 2026-07-07 16:50 UTC - the table is 9 days stale, consistent with the in-flight 143.1 corpus re-run, not a data-flow fault.
- systemd (`systemctl list-units --all`, `list-unit-files`, this host): **every auditor-family unit is `disabled` and `inactive dead`** - `indicagent-bar-auditor.service`, `indicagent-ml-data-quality.service`+`.timer`, `indicagent-service-auditor.service`, `indicagent-shadow-auditor.service`+`.timer`, `indicagent-signal-auditor.service`. **All 10 indicagent timers are disabled**, confirming CLAUDE.md's blanket claim. Only three services are `active running`: `ctx-writer`, `feature-vector-pipeline`, `lineage-writer` (plus the two readiness gates and wave targets).
- Label Identity Invariant (`stratification-dimension-unification.md` lines 198-210, read directly): "a label is only meaningful as a `(dimension, label)` pair. No consumer or table stores a bare label without its dimension qualifier." The doc's own worked example is directly on point: `feature_ic_scores.regime` mixing 9 cross-sectional with 5 per-symbol labels unqualified was the invariant's worst live violation, patched in Phase 141.1 with a `regime_scope` qualifier column.
- Design doc drift-audit contract (`concept-controlled-vocabulary.md` lines 149-154, 227, 302): periodic check "housed in an existing auditor daemon, not a new service"; data-superset divergence is the dangerous direction.
- `services/service_auditor.py` (887 lines, read): `ServiceAuditor(BaseDaemon)` monitors systemd unit states, Prometheus lag/heartbeats, and provider data flow against `_DAG_ORDER`. It contains zero table-content checks; its entire subject matter is service liveness, not data values.

---

## 2. Findings

### V1 - OQ1: one 15-code namespace violates the Label Identity Invariant; nine-only leaves a live taxonomy unregistered. Seed two namespaces. [HIGH]

Option (a) - all 15 codes in one `regime_cross_sectional` namespace - recreates, inside the vocabulary registry itself, the exact defect the invariant was written against: two different dimensions' labels mixed in one bag with no qualifier. It is structurally the pre-141.1 `feature_ic_scores.regime` bug, transplanted into the system whose whole job is taxonomy hygiene. It also corrupts D-04's grouping semantics: a namespace holding both a `bull` direction group and a `tight` width group implies the facets cross (a `steep_bull` that does not exist), and any consumer doing `codes('regime_cross_sectional')` to populate a filter panel or a stratification loop would get 15 labels of which at most 9 are valid for the dimension it is actually conditioning on - a silent wrong answer, the worst class of failure this project recognizes.

Option (b) - 9 equity codes only, rates deferred - honors the invariant but fails the registry's own purpose test: `rates` is a **live** taxonomy (618k rows on `flat_wide` alone, written through 2026-07-07) whose labels can drift or gain members exactly as easily as equity's. "A live column whose taxonomy can silently drift" is the design doc's own stated qualification bar (line 247). Deferring it saves six INSERT rows and five group rows - there is no cost to defer.

**Resolution (c): two sibling namespaces, both seeded in this build.**

- `regime_cross_sectional_equity` - 9 codes; D-04's group seeds apply verbatim (vol-tier `low_vol`/`mid_vol`/`high_vol`, direction `bull`/`neutral`/`bear`).
- `regime_cross_sectional_rates` - 6 codes; same crossed-facet pattern D-04 already established, applied to this taxonomy's actual facets: curve-shape groups `flat`/`steep`/`inverted` (2 members each) and width groups `tight`/`wide` (3 members each).
- Drift-audit queries scoped per namespace: `... WHERE ts > now() - <window> AND regime_group = 'equity'` and `... AND regime_group = 'rates'`.

This is namespace = dimension, which is the invariant applied at the registry layer, and it is also the shape `StratificationDimension` already anticipates (equity and rates formalized as separate conditioning dimensions). Nothing here builds toward that integration (D-08 stays out of scope); it only shapes seed rows so the future integration does not require a namespace split migration. Prefer explicit `_equity`/`_rates` suffixes over keeping bare `regime_cross_sectional` = equity: an unqualified name that implicitly means "the equity one" is a bare label without its dimension qualifier in miniature, and renaming is free today (zero consumers exist) and expensive after the API and dashboard consume it.

**CONTEXT.md amendments required:** D-01's namespace list becomes six (split `regime_cross_sectional` into the two above); D-04 is re-scoped to the equity namespace and extended with the rates group seeds. Neither reopens schema shape or staging.

### V2 - The scoped drift audit has a blind spot: a future third `regime_group` drifts past both queries silently. [MEDIUM]

With both audit queries filtered by `regime_group`, a new signal module writing `regime_group = 'credit'` (say) produces labels neither query ever selects - permanent silent drift, the precise failure mode Controlled Vocabulary exists to make loud. The fix is one extra bounded query in the same audit: `SELECT DISTINCT regime_group FROM market_regimes WHERE ts > <window>`, compared against the qualifiers the registry knows (either derived from the `regime_cross_sectional_*` namespace suffixes, or a two-code `regime_group` namespace if a hardcoded list feels like the vocabulary equivalent of an APR violation - both acceptable; the derived form adds no namespace and is recommended). Cost: one query, one comparison; catches an entire class of future drift.

### V3 - OQ2: every candidate host daemon is dead; ship the audit as a module + oneshot, not a passenger on a corpse. [HIGH]

Verified this session (see §1): `bar_auditor`, `data_quality_auditor` (unit `ml-data-quality`, service and timer), and `service_auditor` are all `disabled` + `inactive dead`. The design doc's "ride an existing auditor, don't build a new service" principle presumed a live auditor fleet; that premise is empirically false in this deployment. Wiring the drift audit into any of these files as-is ships a check that is built, tested, reviewed, and never executes - `161-RESEARCH.md`'s own Pitfall 3, now confirmed rather than suspected, and for all three candidates rather than one.

Per-candidate SoC verdicts, so this does not get relitigated:

- `data_quality_auditor.py`: all 4 checks query archived v2.x tables (`intelligence_features`, `signal_ledger`); dead unit, dead timer, dead subject matter. Reject.
- `bar_auditor.py`: dead unit, and its domain is OHLCV gap detection + self-healing - vocabulary drift is not a bar-integrity concern. Reject on both liveness and SoC.
- `service_auditor.py`: dead unit, and the wrong altitude even if revived - it audits **whether services are alive** (systemd states, Prometheus lag/heartbeats against `_DAG_ORDER`); it never inspects table contents. A data-content check inside the liveness watchdog blurs the one clean boundary the file has. Reject on SoC; the prior research was right not to shortlist it.

**Resolution (b), shaped to preserve the design doc's intent:**

1. Implement the drift-audit logic as an **importable module** (e.g. `src/config/vocabulary_drift.py`, beside `vocabulary_service.py`): takes a pool, runs the bounded per-namespace queries (with V1's `regime_group` scoping, V2's group check, and research Finding 3's `regime <> ''` filter), writes `monitor_type='vocabulary_drift'` rows to `integrity_monitor`, emits the OTel counter + `logger.error` on data-superset. This preserves the design doc's option: if an auditor daemon is ever revived, hosting the check there is a two-line call into this module, not a rewrite.
2. Wrap it in a **thin oneshot CLI entrypoint** following the D-06 oneshot pattern (`job_completed_total{job, status}` at exit). No new systemd unit or timer in this phase - creating a `.timer` that joins ten other disabled timers is inventory nobody consumes.
3. **Chain it into `scripts/ops/corpus/ops_corpus_pipeline_run.sh`** as the concrete "actually runs" hook. New regime labels appear exactly when regime models refit and corpus rebuilds run - the corpus pipeline is the live, operator-invoked event that matters, and it needs no systemd change. Also run it once at phase end as the seed migration's own verification.

The "don't build a new service" principle survives intact: this adds zero DAG nodes, zero daemons, zero units - less new service surface than reviving a dead daemon to carry the check would require.

### V4 - Correct the record: two factual errors in 161-RESEARCH.md must not propagate into PLAN.md. [MEDIUM]

(1) "bar_auditor.py ... the only confirmed continuously-running, non-timer-gated auditor" (Open Question 2, also the Alternatives table) is false - the unit is `disabled`/`inactive dead`, verified this session. (2) Assumption A1's premise "this dev sandbox has no indicagent systemd units to check directly" is also false - this environment **is** the production host (CLAUDE.md: "Claude Code runs ON this machine"), and the full unit listing was obtainable all along; A1's flagged-pending status is hereby discharged (timer confirmed disabled, as CLAUDE.md said). Neither error changes this review's resolution (V3 rejects bar_auditor anyway), but a planner reading RESEARCH.md without this doc would wire the audit into a dead daemon believing it live. Planning must treat this review as overriding RESEARCH.md's Open Question 2 text and A1/A2.

### V5 - Out-of-scope visibility flags: the watchdog fleet is entirely dark, and the drift window must tolerate batch-stale sources. [LOW]

(1) `service_auditor` - the component whose job is noticing dead services - is itself dead, so nothing monitors the three services that are running. Not this phase's problem, but it materially weakened this phase's research (a live service_auditor would have made the auditor-fleet state obvious) and deserves its own operator decision. (2) `market_regimes.max(ts)` is 2026-07-07: with batch-cadence writers, a short drift window can return zero rows and read as registry-superset for every code. The audit should treat an empty observed set as "source idle, skip" (log info), never as mass deprecation evidence.

---

## 3. What's Solid

- **The research pass's DB verification was excellent.** All three data findings (15 labels across two regime_groups, three `tier` values, the `''` placeholder in `feature_vectors.regime`) reproduced exactly under this session's independent psql checks. The 15-label finding genuinely blocks D-04 as written and was correctly escalated rather than silently patched.
- **Refusing to silently resolve both questions was the right call** - OQ1 is a real scope decision (it amends two locked decisions) and OQ2's correct answer depends on production state research believed it could not see.
- **The schema, service, and API design need no changes.** Nothing found here touches the 3-table shape, `VocabularyService`'s ConfigService-mirror pattern, the `src/config/` placement, the `integrity_monitor` persistence choice, or the staging order. D-02, D-03, D-05, D-06, D-07 all stand untouched.
- **The `integrity_monitor` reuse (research Pattern 3) is confirmed as the right persistence layer** and slots directly into V3's module design.
- **D-04's crossed-facet grouping pattern was the right instinct** - it extends to the rates taxonomy without modification, which is decent evidence the pattern is real rather than bespoke.

---

## 4. Punch list

1. **[Plan]** Amend 161-CONTEXT.md: D-01 namespace list = `regime_hmm`, `regime_cross_sectional_equity`, `regime_cross_sectional_rates`, `timeframe`, `asset_class`, `tier` (six); D-04 re-scoped to the equity namespace, plus rates groups (curve-shape `flat`/`steep`/`inverted`; width `tight`/`wide`). (V1)
2. **[Seed migration]** 15 `regime_cross_sectional_*` codes across the two namespaces; 4 equity groups per D-04 unchanged; 5 rates groups per item 1. (V1)
3. **[Drift audit]** Per-namespace `market_regimes` queries carry `AND regime_group = '<qualifier>'`; add the `SELECT DISTINCT regime_group` guard comparing against registered qualifiers. (V1, V2)
4. **[Drift audit]** Build as importable module (`src/config/vocabulary_drift.py`) + D-06 oneshot CLI; persist to `integrity_monitor` (`monitor_type='vocabulary_drift'`); keep the `regime <> ''` filter; empty observed set = skip, not deprecation. No new systemd unit, no daemon edit. (V3, V5)
5. **[Drift audit]** Append the oneshot invocation to `scripts/ops/corpus/ops_corpus_pipeline_run.sh` and run it once at phase end as seed verification. (V3)
6. **[Plan hygiene]** PLAN.md must cite this review as superseding RESEARCH.md's Open Question 2, Alternatives-table bar_auditor row, and Assumptions A1/A2. (V4)
7. **[Operator decision - explicitly NOT bundled into this phase]** Scheduled/continuous drift auditing requires enabling a systemd unit or timer on this production host (reviving an auditor daemon, or a new `.timer` for the oneshot). Every auditor unit and all 10 timers are currently disabled; whether any of that changes is a production-operations sign-off for the project owner, separate from this phase's code. Relatedly: `service_auditor` itself being dark means nothing watches the three running services - worth its own decision. (V3c, V5)

---

*Informed by: `.planning/phases/161-controlled-vocabulary-system-planned/161-RESEARCH.md` and `161-CONTEXT.md` (the two open questions under review), `docs/research/concept-controlled-vocabulary.md` (drift-audit contract), `docs/research/stratification-dimension-unification.md` (Label Identity Invariant, lines 198-210).*
