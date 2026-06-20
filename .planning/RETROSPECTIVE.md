# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

---

## Milestone: v2.10 — Data Architecture Evolution

**Shipped:** 2026-06-20
**Phases:** 12 (123, 124, 125, 126, 127, 128, 129, 130, 131, 132, 134, 136) | **Plans:** ~58 complete | **Timeline:** 7 days (2026-06-14 → 2026-06-20)

### What Was Built

- ECL boundary restored: all 37 I7 plugins emit on intrinsic criteria only; CTF score, zone friction, exhaustion state demoted to annotations; `context_features` + `factor_scores` promoted to persisted signal fields; `_nullable_float()` pattern preserves None vs 0.0 ML semantics
- APR full migration: 51 constants externalized across all 3 tiers (Tier A detection gates, Tier B confidence weights, Tier C zone geometry); weight sum invariant enforced in all Tier B plugins; zero hard-coded numerics in src/
- 3-table signal architecture: `signal_events` / `trade_frames` / `trade_executions` deployed; `counterfactual_pnl_r` as first-class ML training target; 1,443,231 rows migrated; all writers/trackers/APIs migrated; `signal_ledger` dropped
- Signal universe hardening: 5 over-firing plugins corrected to event-onset (<3%/bar); `_I7_I6_EXEMPT` frozenset deleted; universal ATR zone width gate eliminates phantom stopped-at-entry outcomes
- Signal generation integrity: I6 CTF zero bug fixed; asset_class injection corrected; BOCPD look-ahead bias removed; 16 I7 plugins had HMM regime gates removed
- Type safety: PG ENUM types on all classification columns; EntryType Python enum; SignalOutcome persisted to trade_executions; stopped_at_entry < 5%
- Post-reboot repair: 1,343 orphaned rows recovered; feature_writer pre-flight schema check; intelligence_pipeline graceful SIGTERM; FVGFill disabled; ValidationResult NamedTuple

### What Worked

- ECL-first ordering: fixing emission suppression before replay prevented cleaning symptoms while root causes persisted — the entire Phase 123 fix unlocked correct data for all subsequent analysis
- APR-before-replay: having all 51 parameters externalized before clean replay means the corpus reflects tunable seeds, not buried constants — ML optimization can now actually optimize something
- 3-table migration during the same milestone as replay: corpus landed in the final schema with `counterfactual_pnl_r` populated from day one; avoided a second replay migration later
- Continuous verifier pattern: each phase ended with a VERIFICATION.md with numbered truths — gaps caught at phase-close time rather than at milestone close

### What Was Inefficient

- Phase 133 planned and then cancelled: 7 plans written for a corpus rebuild that was superseded when the v3.0 architecture was decided; architectural thinking about what IC measurement requires (all bars vs. fired bars) would have caught this before planning
- REQUIREMENTS.md checkbox drift: 5 requirements showed "Pending" in the traceability table at milestone close despite their phases being complete; the traceability table was never updated at phase completion time; maintenance discipline needs a phase-close checklist item
- Phase scope creep: v2.10 was scoped as Phases 123-130 at design time but grew to include 131, 132, 134, 135, 136 as integrity issues were discovered; this is appropriate (discover-and-fix vs. defer-and-replay) but scope should be re-stated at each addition

### Key Decisions Validated

- `counterfactual_pnl_r` on `trade_frames` (not `signal_events`): correct separation — detection layer captures what fired; hypothesis layer captures what the trade would have been; outcome layer captures what actually happened. ML trains on hypothesis-vs-outcome, not detection-vs-outcome
- None vs 0.0 semantics: `_nullable_float()` pattern is the right abstraction; avoids OR-fallback contamination of ML labels; future engineers: never use `value or 0.0` on a financial measurement

### Key Decisions for v3.0

- Phase 133 CANCELLED: IC measurement runs on `intelligence_features` (unconditional, all bars), not `signal_events` (conditional, only bars where a plugin fired). Building a corpus of the old paradigm would have been immediately obsolete. Phase A of v3.0 uses the existing corpus as an exploratory baseline; Phase B is when unbiased IC begins.
- AlphaEngine before AnalogEngine: V1 Quant (existing 138 plugins) must demonstrate IC > 0 before introducing pgvector infrastructure. Don't add complexity before validating the core thesis.

---

## Milestone: v2.9 — Signal Quality Renaissance

**Shipped:** 2026-06-13
**Phases:** 6 (117, 118, 119, 120, 121, 122) | **Plans:** 32 complete (33 written; 121-02 deferred) | **Timeline:** 6 days (2026-06-07 → 2026-06-13)

### What Was Built

- PatternCompletion data bug fixed: pattern_detections JSONB was not being persisted; 795K phantom signals traced to missing write path; fixed + FeatureParityAuditor timer deployed
- Extrinsic confidence strip: hmm_regime_weight, apply_exhaustion_boost, CTF boosts, zone penalties removed from all 36 I7 confidence formulas; confidence is now intrinsic-only (signal geometry, magnitude, persistence)
- 21 NEEDS_REFACTOR setups refactored with 6 GOOD patterns: multi-factor intrinsic confidence, I6 confluence gate, dual gate (regime + CTF), continuous hmm_regime_weight, early gate optimization
- Shadow promotion pipeline: ShadowValidator weekly oneshot (5-gate: binomtest p<0.05, N>=100, win_rate>50%, avg_pnl_r>0, calibration_corr>0.3); shadow_auditor becomes demotion-only
- Signal ledger replay: 5.18M noise signals deleted; phase_121_orchestrate.py 7-stage state machine; clean replay from stored features; MacroContextPlugin 5-field enrichment
- I2 tier persistence: I2Events schema 45 fields, extra="forbid"; intelligence_features i2 JSONB column; feature_replay.py I7-only replay path; 46 plugin constants wired to param store (migration 129)

### What Worked

- Root cause first: fixing upstream data bugs (PatternCompletion write path, CVD threshold enforcement) before refactoring downstream confidence formulas prevented cleaning up symptoms while root causes persisted
- Intrinsic-only confidence principle: single architectural rule (confidence = signal geometry only) replaced dozens of ad-hoc adjustments and made the refactor mechanical across all 21 setups
- Orchestrated replay (7-stage state machine with decompress/recompress): prevented hours-long stall on TimescaleDB compressed chunks; state persistence allowed safe interruption and resume
- Shadow-only gate on all refactored setups: validation framework exists before promotion is possible; promotion criteria are statistical, not manual

### What Was Inefficient

- Phase 122 replanning: the param-store migration was planned as Phase 121 absorbed work, then expanded to 10 plans; earlier scoping would have set cleaner phase boundaries
- Plan 121-02 (validation report) deferred: replay completed but the comparison report requires v2.10 clean-replay baseline for meaningful before/after; deferred work could have been scoped differently upfront
- Feature_replay.py uuid4 fallbacks: architecture review identified 2 edge-case paths still using random UUIDs; flagged but not closed within v2.9

### Patterns Established

- Intrinsic confidence rule: I7 confidence is computed from signal geometry only; extrinsic context (HMM regime, I6 scores, macro state) travels via capture_signal_features() and is excluded from the confidence path
- shadow-only promotion ceremony: all refactored setups require ShadowValidator 5-gate pass before shadow_registry.shadow_only can be set False; no manual promotion
- Param store pattern: runtime-tunable constants use config-backed getters; no hardcoded thresholds in production code paths
- Orchestrated replay pattern: 7-stage state machine with decompress → clean → replay → recompress; state persisted to disk to survive interruption

### Key Lessons

1. **Fix data bugs before refactoring consumers**: 795K phantom PatternCompletion signals came from a write-path bug, not a logic bug; fixing the write path first made the refactor correct from the start
2. **Extrinsic modifiers in confidence formulas corrupt ML training data**: when HMM regime weight was inside confidence, it was impossible to learn HMM's marginal contribution from labeled outcomes - the label already reflected HMM's influence
3. **Replay architecture needs a fast path**: I1-I6 full recompute in replay is a DAG violation and wastes hours; feature_replay.py from stored intelligence_features is the right pattern for I7-only re-evaluation
4. **Plan deferred work explicitly**: "121-02 deferred to Phase 126" is cleaner than leaving an unchecked box; makes the deferral and its dependency (clean-replay baseline) explicit

### Cost Observations

- Sessions: ~6 sessions over 6 days
- Notable: Phase 122 was the deepest single phase (10 plans, touching schema, write path, replay, and param store in sequence); factoring it into smaller milestones would have been cleaner

---

## Milestone: v2.7 — Mathematical Correctness, Storage & Hardening

**Shipped:** 2026-05-29
**Phases:** 9 (093, 100, 100.5, 104, 105, 106, 107, 108, 109) | **Plans:** 43 | **Timeline:** 10 days (2026-05-20 → 2026-05-29)

### What Was Built

- Mathematical correctness audit: ATR Wilder bug fixed; 28 I1 indicators validated vs pandas-ta; Kalman/GARCH stateful invariants; edge case coverage; CI gate
- Plugin shared infrastructure: IncrementalMixin for 31 incremental plugins; shared utilities (atr_utils, state_utils, confidence_utils); PluginObserver; 24 plugins migrated
- Storage redesign: signal_ledger 97→38 columns; intelligence_features column renames (i1–i8 → concept names); 9 retention policies; 13 GB freed (feature_snapshots_shadow)
- Architecture hotfixes: shadow signal suppression, writer AttributeErrors, OTel metric type corrections (Phase 105)
- Foundation + hygiene (Renaissance): 9/9 HYGIENE criteria; DAG 31→42+ services; PluginCircuitBreaker wired; enqueue_blocking backpressure (Phases 106, 107)
- Self-healing: WatchdogSec=60 on 39 daemons; DLQ quarantine (.dead-final); consumer stall detection; api_health gauge; oneshot job_completed_total counters (Phase 108)
- Config foundation: DB-backed OPS config (4 tables), ConfigService HTTP API (port 9001), Kafka transactional outbox, BaseAgent hot-reload, SelfHealingAgent (port 9002) (Phase 109)

### What Worked

- Renaissance 9-criterion expansion for Phase 107: expanding from 4→9 HYGIENE criteria with binary SQL verification created a rigorous, objectively measurable close — no ambiguity about whether the phase was done
- Treating Phase 109 as v2.7 capstone (not v2.8): config foundation is hardening, not AI platform; correct scoping prevented scope creep into v2.8
- Decimal phase insertion (100.5): allowed plugin hardening to ship cleanly without disrupting the 100→104 dependency chain
- Emergency hotfix pattern (Phase 105): inserting an unplanned architectural hotfix sprint immediately after discovering the 2026-05-23 audit findings — catching bugs before they compound is cheaper than fixing them later

### What Was Inefficient

- REQUIREMENTS.md tracking lag: FOUND/HYGIENE-05-09 requirements had incorrect checkbox state throughout v2.7 — phase completion wasn't reflected in the doc; burned time at close reconciling
- ROADMAP.md milestone assignment drift: Phase 109 was listed as v2.8 in the progress table despite being a v2.7 capstone — inconsistency required cleanup at close
- v2.7-MILESTONE-SUMMARY.md was created mid-milestone (after Phase 107) and not updated as 108 and 109 shipped — partial summaries create confusion

### Key Lessons

- **Track requirements against phases as they complete, not at milestone close** — retroactive reconciliation at close is error-prone; mark [x] in REQUIREMENTS.md when the phase SUMMARY is written
- **Milestone assignment must be locked before execution** — if a phase is v2.7 work, set it as v2.7 in ROADMAP before executing; don't let it drift to v2.8 by default
- **Config foundation is infrastructure, not AI** — any "load config at startup, react to changes" work belongs in the hardening milestone; keep it out of the AI platform milestone to prevent dilution

---

## Milestone: v2.0 — Signal Integrity & ML Foundation

**Shipped:** 2026-03-22
**Phases:** 14 (39–47, including 39.1, 40, 44.1, 44.2, 44.3, 46.1) | **Plans:** 60 | **Timeline:** 4 days (2026-03-19 → 2026-03-22)

### What Was Built

- Intelligence pipeline DAG refactor: FeaturePipelineService (I1–I6 unified, 3 Kafka hops → 1), SignalGeneratorService (6-stage in-process, 8 hops → 2), atomic `BarIntelligenceRecord` INSERT; service count 18 → 9
- ML training data foundation: all 36 I7 plugins emit `_shadow` dict with I6 ctf_* sub-scores via `capture_confluence_features()` — Phase 49 learns weights from this data
- DB hardening: `signal_ledger` generated columns + CHECK constraints + composite lifecycle index; `market_data_ohlcv` rebuilt 15,740 → 21 chunks; 15-min data quality monitoring with 10 Prometheus gauges
- Intelligence gap fill: real FVG/OB CTF alignment (was 0.0 stubs), VP as T1/T2 targets, HTF 1h cache injection, 18 new I5 candlestick patterns with DB-driven weight feedback
- I6 Confluence Expansion: VIXRegimePlugin + CrossAssetContextPlugin promoted to I4 (layer violation fixed); 4 new CTF measurement fields; cross-asset + VIX frames injected into pipeline
- Code quality enforcement: SignalStatus + SignalOutcome enums; regime_type Protocol field; pre-commit hooks; 3 production bug fixes; dual topic namespace cleanup
- Shadow graduation: CROSS_ASSET_ENABLED feature flag removed (unconditionally active); regime gate parametrized via Settings

### What Worked

- Decimal phase insertion (39.1, 46.1) handled urgency cleanly without disrupting main phase numbering — clean pattern for priority work
- Phase 44 restructuring (44 → 44.1 → 44.2 → 44.3): decomposing the pipeline refactor into independent concerns (schema, in-process, atomic persistence) made each step verifiable without live infra
- Milestone audit before archival caught 5 doc inconsistencies that would have corrupted the requirements record — worth the investment
- "Absorbed in-process" pattern for Phase 44.2: 6 microservices absorbed into 1 with bounded async audit queue preserved all observability at 1/8th the Kafka hop cost
- I4 layer promotion for VIX/cross-asset (Phase 46.1): catching the layer violation before ML training data accumulation prevented a data quality defect in the training matrix

### What Was Inefficient

- Phase 40 built 6 DAG microservices that were absorbed back in Phase 44.2 (3 phases later) — architectural indirection created real work without lasting value. Should have validated the in-process architecture first before creating standalone services.
- SHADOW-03 couldn't be fully validated because `market_data_5m` was empty after DB cleanup — operational gate blocked by infrastructure state, not code quality. A CI-resistant graduation ceremony needs test-data fixtures, not live data.
- 1 broken CI test (threading.Lock characterization) carried forward from Phase 43 → delayed until Phase 49. Should have been fixed in the same phase.

### Patterns Established

- `_shadow` dict capture pattern: I7 plugins call `capture_confluence_features()` → structured ML feature capture without modifying signal logic; weights learned later
- `BarIntelligenceRecord` as typed handoff: clean schema boundary between FeaturePipelineService and feature_writer/signal_generator eliminates partial-row race conditions
- Decimal phase ceremony rule: feature flag removal only after operational gate passes (D-21 validation) — prevents premature graduation of unvalidated signal paths
- I4 layer rule: macro regime context (VIX, cross-asset spreads) belongs in I4 (per-bar, per-TF, consistent), not I6 (cross-TF scoring layer)

### Key Lessons

1. **In-process > microservices for compute-bound pipelines**: 6 Kafka round-trips per bar cost more than the isolation benefit for a single-host system. Build in-process first; extract to microservice only when isolation is actually needed.
2. **DAG refactors need clear direction before execution**: Phase 40 built toward external microservices; Phase 44 reversed toward in-process. The indirection consumed 2 milestones of work. Better to spike both approaches before committing.
3. **Shadow ceremony rule prevents premature graduation**: The SHADOW-03 stall (empty market_data_5m) vindicated the "gate must pass before removal" rule. Without it, roll monitor would have been enabled on stale/missing data.
4. **Milestone audit before archival is worth it**: 43/58 requirements actually satisfied (vs 38/58 on paper) — audit found 5 checkbox inconsistencies that would have under-counted v2.0's real accomplishments.

### Cost Observations

- Model mix: ~60% sonnet, ~40% opus (heavy planning phases used opus; execution on sonnet)
- Sessions: ~8 sessions over 4 days
- Notable: Phase 44 chain (44→44.1→44.2→44.3) was the most complex sequence — typed schema handoffs prevented integration breaks that would have been invisible with duck-typed dicts

---

## Milestone: v1.4 — Quant Foundation

**Shipped:** 2026-03-07
**Phases:** 6 (12-17) | **Plans:** 29 | **Timeline:** 4 days (2026-03-04 → 2026-03-07)

### What Was Built

- Regime-aware I7 gating: all 17 plugins enforce hmm_regime type, prob≥0.60 conviction gate, and duration≥5 stability gate before firing
- Shadow signals: regime-suppressed setups tracked in signal_ledger with full counterfactual MAE/MFE/8-class outcome for empirical gate tuning
- Complete ML training dataset: intelligence_features now carries i7 JSONB (all_ranked per bar), i8 JSONB (narrative metadata), days_to_expiry — no missing samples
- Adaptive aggregator: setup_performance table (rolling 30-day win rate, avg_pnl_r, Sharpe) feeds perf_multiplier as primary sort key; best Sharpe setups rank first
- validate_alpha.py statistical promotion gate (Pearson r>0, p<0.05, N≥30 + ADF stationarity); bootstrap policy for correct implementations without live data
- 4 new alpha sources live: DerivativeOscillatorPlugin (I2), 10 Candlestick Tier 1 patterns (I5/I7), MACD histogram acceleration (I2), ACOscillatorPlugin (I1)
- Full LLM audit log: llm_calls TimescaleDB hypertable — every call (success, failure, counterfactual) captured with outcome back-fill from signal lifecycle
- Adaptive LLM model routing: llm_model_scores + 15-min score recompute + per-regime _preferred_models routing (is_significant: n≥30, p<0.05)
- Phase 17 gap closure: signal_id UUID threaded through signals:aggregated → llm_calls (E2E Flows 3+4 restored); regime vocabulary standardized

### What Worked

- TDD RED/GREEN discipline on every plan — RED tests caught integration contracts before implementation diverged
- Milestone audit (v1.4-MILESTONE-AUDIT.md) run mid-milestone identified LLM-04/LLM-05 production wiring breaks that unit tests couldn't catch; resulted in Phase 17 being added
- Bootstrap policy for validate_alpha.py: solved the chicken-and-egg problem for new plugins without live data (verdict=BOOTSTRAP + audit trail) without blocking forward progress
- perf_multiplier as primary sort key: simple, clear fix for what was a subtle formula bug (composite_rank × multiplier where high-priority setup always got composite_rank=1)
- Phase GAP plans (15-GAP-01, 15-GAP-02) handled bootstrap promotion and I7 candlestick wiring cleanly without reopening earlier plans

### What Was Inefficient

- Audit ran mid-milestone (before Phase 14/15 started) and identified orphaned requirements — not wrong, but required a re-audit pass at completion; running audit after milestone is more efficient
- REQUIREMENTS.md traceability table diverged from audit file (showed Complete while audit showed orphaned) — single source of truth needed; the audit should be re-run at completion, not just mid-milestone
- Rate limit mid-plan (14-05) interrupted execution; minor, but plan continuations benefit from smaller atomic chunks
- State.md showed "Phase 15 active, 4 of 5 plans done" at session start but all 7 plans (incl. GAP-01/02) were complete — STATE.md wasn't updated after the final push; requires discipline on every session end

### Patterns Established

- **Bootstrap policy for data-absent plugins**: verdict=BOOTSTRAP not FAIL; audit trail in docs/validation/; re-run validate_alpha.py --promote after data accumulates
- **Milestone audit mid-milestone**: Identifies structural gaps early; Phase 17 was a direct result of the Phase 16 audit catch
- **GAP plans within a phase**: 15-GAP-01 and 15-GAP-02 handled retroactive gap closure without renumbering existing plans; clean extension pattern
- **perf_multiplier primary sort**: Performance rank is the primary key; SETUP_PRIORITY only as tiebreaker — simpler, correct, resistant to priority-inflation bugs
- **signal_id hot-tier-first pattern**: xadd fires before DB insert; xdel compensates on DB failure — prevents orphaned signal_id in Redis

### Key Lessons

1. **Audit before claiming complete**: The v1.4 audit ran before Phase 14/15 existed — it identified real gaps but created confusion because REQUIREMENTS.md showed them as Complete. Always re-run audit at completion, not just mid-milestone.
2. **Unit tests don't catch integration wiring**: LLM-04/LLM-05 had passing unit tests but broken production wiring (signal_id=NULL, regime vocab mismatch). Integration checks (or runtime observation) are required alongside unit tests for stream-to-stream contracts.
3. **Validate correctness early, defer data gate**: Bootstrap policy works — implementing a plugin correctly and promoting with BOOTSTRAP verdict is better than blocking development on the live-data chicken-and-egg. Re-run when data accumulates.
4. **STATE.md must be committed after every plan**: Stale STATE.md misleads the next session. Phase completion = commit STATE.md update is a hard rule.

### Cost Observations

- Model: claude-sonnet-4-6 (100% — balanced profile)
- Sessions: ~8-10 across 4 days
- Notable: Parallel wave execution in execute-phase kept each plan under 2 sessions; Phase 17 was the most focused (2 plans, surgical fixes)

---

## Milestone: v1.5 — Production Hardening

**Shipped:** 2026-03-10
**Phases:** 5 (18-22) | **Plans:** 25 | **Timeline:** 2 days (2026-03-07 → 2026-03-09)

### What Was Built

- Epsilon tolerance (1e-9) for all floating-point comparisons in trade_framer + CIS scorer; ATR multipliers, regime thresholds, RSI zero-loss guard all named constants
- Configurable ibkr_timeout_sec / llm_timeout_sec in Settings; IBKR and all 4 LLM providers use Settings values
- per-key asyncio.Lock() in market_analysis_service, indicator_service, ai_narrative_service — shared state protected from concurrent task access
- Characterization tests pinning RSI zero-loss (100.0), zero-ATR emergency fallback, and concurrent lock isolation
- retry_utils.py: exponential_backoff_with_jitter() + retry_with_backoff() async wrapper; PluginCircuitBreaker wired to all LLM providers and IBKR; Prometheus metrics on all circuit breaker state transitions
- DataFrame cache invalidated only on buffer overflow (not every bar); CIS scorer numpy/BLAS vectorized; plugin call metrics modulo sampling (PLUGIN_METRICS_SAMPLE_RATE=10)
- Three-tier I8 narrative: action_tag (deterministic, instant), narrative_short (~500ms), narrative_deep (~5-8s) as concurrent asyncio tasks; independent SSE routing; dashboard progressive disclosure; old single-call path retired

### What Worked

- Phase scope was tight and surgical — no phase needed a GAP plan or re-verification after gap closure
- Characterization tests (Phase 19) proved the right pattern for pinning numeric invariants: seed _state directly, assert behavioral ordering not exact floats, use `__new__` to bypass `__init__`
- Three-tier narrative (Phase 22) was the highest-complexity plan of the milestone and had zero rework — the concurrent task pattern was clean once the spread-merge SSE approach was chosen
- Audit at completion (not mid-milestone, per v1.4 lesson) worked well — `tech_debt` verdict didn't block completion, and the 3 partial items were correctly scoped as naming/tracking gaps not functional gaps
- 2-day execution for 5 phases is the fastest milestone yet — hardening work is well-suited to parallel waves

### What Was Inefficient

- Phase 18 required re-verification (score went 9/13 → 13/13) — plans 18-01 through 18-03 were executed before the epsilon tolerance scope was fully clear; plans 18-04 through 18-06 closed the gaps. Better upfront scoping of which files needed epsilon treatment would have avoided the re-verification pass.
- REQUIREMENTS.md checkboxes weren't updated during execution (3 "partial" API items in audit were actually tracking gaps, not implementation gaps) — the audit caught them as `tech_debt` but they should have been marked complete as each plan was committed
- ai_narrative_service._per_signal_timeout still bypasses Settings.llm_timeout_sec — discovered in audit. This was a wiring oversight in Phase 18 not caught until Phase 22 verification. A cross-file grep for hardcoded timeout values at the start of Phase 18 would have caught it.
- STATE.md `percent: 36` at milestone completion was stale — progress tracking wasn't updated after Phase 22 completed. Same issue as v1.4.

### Patterns Established

- **Characterization tests over exact-value assertions**: Pin behavioral invariants (directional ordering, fallback presence, lock isolation) not exact floats — tests are robust to implementation changes while still encoding the contract
- **`__new__` pattern for lock tests**: Bypass `__init__` entirely and set only the specific attribute being tested — isolates the asyncio.Lock test from all service startup complexity
- **spread-merge SSE state for async arrivals**: `{...existing, ...newFields}` merges independent async stream messages into the same state key without coupling tier arrivals — clean pattern for any multi-message per-event SSE design
- **Overflow detection via `len_before == history.maxlen`**: Deque semantics guarantee eviction only when at capacity; flag-based cache invalidation avoids rebuilding DataFrame on every bar
- **Prometheus state snapshot pattern**: Capture `previous_state` before the operation, compare after — detects actual state transitions for metric emission without false positives

### Key Lessons

1. **Hardcoded values need a grep sweep at phase start**: Phase 18 targeted configurable timeouts but missed `_per_signal_timeout` in ai_narrative_service. A `grep -r "timeout" services/` at the start of the phase would have included it in scope before plans were written.
2. **Audit as `tech_debt` is a valid completion gate**: Not every gap needs to be closed before shipping. The 3 partial items were naming and tracking gaps, not broken behavior — accepting them as tech debt and noting in MILESTONES.md is the right call.
3. **Concurrent task patterns need SSE-side counterparts**: Phase 22 fired two independent LLM tasks correctly but the SSE handler needed a matching spread-merge pattern. The async task change and the SSE handler change must be designed together — one is incomplete without the other.
4. **STATE.md progress percent is unreliable** — it gets set at phase start and not updated. Either remove percent tracking or enforce update-on-completion. Currently it's noise.

### Cost Observations

- Model: claude-sonnet-4-6 (100% — balanced profile)
- Sessions: ~6-8 across 2 days
- Notable: Fastest milestone execution yet — surgical hardening phases fit well into short focused sessions; Phase 22 (most complex) completed in one session

---

## Milestone: v1.8 — Signal Intelligence

**Shipped:** 2026-03-13
**Phases:** 2 (28-29) | **Plans:** 15 | **Timeline:** 2 days (2026-03-12 → 2026-03-13)

### What Was Built

- Signal Scorecard panel: I7 all-ranked signals with confidence, direction, composite rank, and suppression labels wired to SSE `signal_scorecard` event and drill panel
- DB signal history in drill panel: `signal_ledger` loaded on mount, merged with live SSE, deduplicated by `signal_id`; `GET /api/signals/recent` backend endpoint
- GARCH/Kalman I4 fields + SMC BSL/SSL detail + premium/discount: full I4 context and smart money structure surfaced in drill panel
- Tier tooltips: I1–I8 labels show hover explanations for each intelligence tier
- CIS constituent contributions: 6 bucket methods refactored to return (float, dict); per-setup feature contributions stored in JSONB — attribution analysis enabled without recomputation
- Alpha decay (QUAL-02) + freshness decay (QUAL-03): same-setup signals down-weighted when fired repeatedly; active signal confidence decays exponentially — both in-memory, ML labels untouched
- HurstExponentPlugin + ShannonEntropyPlugin (I4): two new quality gate plugins; Hurst enforces regime-type alignment, Shannon entropy gates noise market periods
- KS + CUSUM drift detection: `drift_monitor_service` with `drift_monitor` TimescaleDB hypertable; CUSUM integrated into `weight_updater`; `/api/drift` endpoint

### What Worked

- Phase 28 (dashboard) executed very fast — frontend changes cleanly mapped to SSE types and API endpoints already in place from v1.7
- Bucket method tuple-return refactor (Phase 29-01) was surgical — zero consumer breakage because public `score()` signature unchanged
- TDD RED/GREEN on every plan maintained; integration tests caught the QUAL-03 freshness wiring gap that unit tests missed (leading to gap-closure plan 29-08)
- Splitting drift detection into KS (29-06) and CUSUM (29-07) plans kept complexity manageable; CUSUM reusing `weight_updater` scheduling was elegant

### What Was Inefficient

- QUAL-03 (freshness decay) required a gap-closure plan (29-08) because the initial implementation wired the signal generator side but not the lifecycle service side — the integration gap wasn't caught until a post-phase integration test
- SIG-01 to SIG-05 requirements were included in the v1.8 REQUIREMENTS.md but delivered in v1.7 — never marked complete before archival; caused confusion in requirements count

### Patterns Established

- **intelligence_i7 domain before intelligence domain**: SSE domain routing requires explicit ordering; `startswith` shadowing is non-obvious — always add the more-specific domain first with a test
- **Bucket method tuple return**: `(score, contributions)` unpacking keeps caller code readable; contribution keys use feature/plugin names for direct attribution at signal time
- **Gap-closure plans within a phase**: 29-08 followed same pattern as v1.4 GAP plans — retroactive gap closure without renumbering; clean, documented extension pattern
- **CUSUM in weight_updater**: performance drift detection collocated with the weight update job; same data, same cadence, no scheduler drift

### Key Lessons

1. **Integration tests reveal wiring gaps unit tests miss**: QUAL-03 freshness decay unit tests passed but the service-level integration showed the lifecycle wire was incomplete. Integration tests for multi-service contracts are not optional.
2. **Requirements.md needs milestone-scoped discipline**: Including requirements for phases from a prior milestone (SIG-01 to SIG-05 for Phase 27) created confusion. Each REQUIREMENTS.md should include only requirements for phases in *this* milestone.
3. **Dashboard completeness pays forward**: Phase 28 was fast because the SSE infrastructure (Phase 27) and DB schema were already in place. Completing infrastructure phases before UI phases is the right sequencing.

### Cost Observations

- Sessions: ~4-5 across 2 days
- Notable: Two-phase milestone (28 + 29) executed in record time relative to complexity; Phase 29's 10 quality requirements across 8 plans shipped in ~1 day

---

## Milestone: v1.9 — I7 Alpha Engine

**Shipped:** 2026-03-18
**Phases:** 8 (31-38) | **Plans:** 23 | **Timeline:** 2 days (2026-03-16 → 2026-03-18)

### What Was Built

- CIS self-improving learning loop: binary win/loss labels + asset-cluster segmented logistic regression (5 clusters); `signal_features` hypertable for mid-bar ML snapshots
- Structure-first stop architecture centralized in `trade_framer.py`: FVG-priority stop, GARCH-adaptive ATR multipliers (0.8×/1.0×/1.35×), `stop_basis` classification — all 36 I7 plugins inherit automatically
- 10 new I7 setups from Phase 33/34: FailedBreakout, ORB15, ORB30, PrevDayLevelTest, SecondLegContinuation, VCP, AnchoredVWAPReversion, VWAPReclaim, POCRejection, HVNRejection
- I4 AnchoredVWAP + VolumeProfile: session/rolling dual-track POC/VAH/VAL, AVWAP deviation bands, 93-field I4Context
- Isotonic regression confidence calibration + TOD Bayesian multiplier (120 cells) + CIS Kalman filter — full confidence pipeline
- OFI + CVD I1 indicators with tick/proxy dual-path; 7 new I7 microstructure plugins; IS_SHADOW pattern for unproven plugins
- `cross_asset_service` microservice: ES/NQ/RTY/YM spread z-scores, correlation break; CrossAssetDivergencePlugin I7
- Automated futures roll detection: volume z-score + 3-bar confirmation + TOD adjustment; full pipeline propagation (indicator/market-analysis/signal-generator/feature-writer), plugin state migration, `seed_roll_chain` backfill

### What Worked

- **Centralized stop architecture** — putting `trade_framer.py` as the single stop source before adding plugins meant every new plugin got correct stops for free; zero per-plugin stop logic needed
- **Shadow mode as standard pattern** — both ROLL_MONITOR_ENABLED=false and CROSS_ASSET_ENABLED=false allow safe deployment without live risk; IS_SHADOW plugin-level flag extends this to individual signals
- **Kalman filter reuse** — KalmanTrendPlugin at `src/intelligence/context/kalman_trend.py` provided a tested local-level implementation that was directly adapted for CIS smoothing; no new filter math needed
- **Phase interleaving (38 before 36/37)** — executing roll detection (38) before microstructure/cross-asset worked because roll detection is infrastructure (DB, topic, Settings) with no plugin dependencies; phases composed cleanly

### What Was Inefficient

- **Phase numbering confusion** — phases were executed out of order (38 before 36/37) due to parallel sessions, causing STATE.md and ROADMAP to get out of sync; ROADMAP had 36/37 as `[ ]` after 38 was already `[x]`
- **Parallel session coordination** — when two sessions work simultaneously (one on 038, one on 036/037), the shared STATE.md becomes inconsistent; requires explicit sync step at merge
- **MACD extension for roll analysis** — added macd_div and macd_hist_contracting fields to support roll analysis, but this coupling between I5 divergence patterns and roll detection feels fragile; proper approach would be roll-specific I1 features

### Patterns Established

- **IS_SHADOW plugin flag** — `getattr(plugin_instance, 'IS_SHADOW', False)` in signal_generator_service extends Phase 35 Kalman shadow pattern to plugin-level; use for unproven setups that need live data before promotion
- **Shadow mode feature flags** — any new microservice or detection system defaults `ENABLED=false`; validate via shadow period before enabling
- **`all_ranked` as source of `active`** — winner selection must always derive from `all_ranked` list after perf_weights applied, never from raw `signals`

### Key Lessons

- **Phase order needs explicit tracking when executing in parallel** — use a shared session state or always update STATE.md immediately after each plan completes
- **All new microservices need a shadow period** — don't enable CROSS_ASSET_ENABLED or ROLL_MONITOR_ENABLED on live without at least 1 week of shadow monitoring
- **CIS Kalman parameters are TF-dependent** — R values {1m:0.08, 5m:0.06, 15m:0.04, 1h:0.02} reflect noise levels at each granularity; document this whenever adding new Kalman applications

### Cost Observations

- 8 phases completed in 2 days — highest velocity milestone to date
- Sessions: ~6-8 intensive sessions across 2026-03-16 to 2026-03-18
- Parallel execution (038 + 036/037 in separate sessions) contributed to velocity but caused sync debt

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 MVP | 10 | 29 | Established typed bus, feature store, dashboard |
| v1.1 | 1 | 1 | Code quality sprint; ruff 206→0 |
| v1.2 | 6 | ~18 | Intelligence expansion (I2/I5/I6); correctness audit pattern |
| v1.3 | 4 | ~10 | I7 plugin additions; Signal Lifecycle redesign |
| v1.4 | 6 | 29 | Regime gating, feedback loops, statistical validation, LLM audit |
| v1.5 | 5 | 25 | Production hardening: float safety, locks, circuit breakers, efficiency, three-tier I8 |
| v1.6 | 2 | 10 | Signal quality: onset detection, flip suppression, HMA, 2nd-derivative I2/I3 |
| v1.7 | 3 | 13 | Data integrity: CIS repair, warmup seed, lifecycle stream events + dashboard outcomes |
| v1.8 | 2 | 15 | Signal intelligence: dashboard completion + Renaissance quality gates + drift detection |
| v1.9 | 8 | 23 | I7 Alpha Engine: learning loop, stop architecture, 18 new plugins, microstructure, cross-asset, roll detection |

### Cumulative Quality

| Milestone | Tests | Ruff | Plugins |
|-----------|-------|------|---------|
| v1.0 | 796 | 0 | 62 + 2 agg |
| v1.1 | 803 | 0 | 62 + 2 agg |
| v1.2 | 965 | 0 | 84 + 2 agg |
| v1.3 | 1083 | 0 | 88 + 2 agg |
| v1.4 | 1286 | 34 (E501 only) | 91 + 2 agg |
| v1.5 | 1318 | 74 (E501 only) | 91 + 2 agg |
| v1.6 | ~1400 | 74 | 93 + 2 agg |
| v1.7 | ~1550 | 167 | 101 + 2 agg |
| v1.8 | 1659 | 167 | 103 + 2 agg |
| v1.9 | ~1800+ | ~0 (E501 only) | 121 + 2 agg |

### Top Lessons (Verified Across Milestones)

1. **Integration wiring breaks evade unit tests** — v1.4 LLM-04/05 wiring, v1.3 consumer group stale position, v1.2 duplicate timestamps. Unit test pass ≠ production wiring correct. Always verify stream-to-stream contracts with an integration check.
2. **TDD RED phase is load-bearing** — Plans without a TDD RED phase produced more rework. RED tests encode behavioral contracts; catching them before implementation prevents subtle bugs in aggregation and stream contracts.
3. **Data capture over correctness** — Several v1.4 decisions (shadow signals, bootstrap policy, LLM call capture even on failure) follow the Jim Simons principle: capture everything, you can filter later. You cannot recover data you didn't capture.
4. **Grep sweep before writing plans** — v1.5 taught that hardcoded values (timeouts, constants) need a cross-codebase grep at phase start, not discovered during audit. Scope definition belongs in research, not verification.
