---
phase: 110
reviewers: [gemini, codex]
reviewed_at: 2026-05-30T15:25:00Z
plans_reviewed: [110-01-PLAN.md, 110-02-PLAN.md, 110-03-PLAN.md, 110-04-PLAN.md]
---

# Cross-AI Plan Review — Phase 110: Renaissance Rename

## Gemini Review

### Summary
The plan demonstrates a sophisticated understanding of the codebase's complexity, utilizing a multi-wave strategy to decouple infrastructure renames from file system moves. The sequential wave approach (Ring 0 → 1 → 2 → Surface) is the correct architectural choice for a refactor of this scale. The explicit handling of operational constraints — specifically metric labels and the deferral of `SignalContext` — shows good judgment in managing blast radius.

### Strengths
- **Sequential Wave Ordering:** Prioritizing base classes (Ring 0) ensures that downstream services (Rings 1 & 2) inherit the new naming conventions, minimizing potential runtime type errors.
- **Risk-Aware Deferrals:** Properly identifies `SignalContext` as an out-of-scope risk for this phase, preventing "cascading" refactor failures.
- **Operational Integrity:** Protecting `agent_id` mappings in `service_auditor_agent.py` is crucial, as this avoids breaking Prometheus dashboards and alerts that rely on specific label values.
- **Test-Driven Execution:** Requirements for CI gates after each wave provide a necessary feedback loop for a high-risk operation.

### Concerns
- **MEDIUM — Dependency on Sed:** Using `sed -i` for bulk refactoring is risky with identifiers that may have partial matches. While the plan mentions word boundaries (`\b`), human error in complex regex is high.
- **MEDIUM — Systemd/Service Discrepancy:** Wave 4 proposes updating `ExecStart` paths but does not explicitly detail how the systemd unit *filenames* (e.g., `indicagent-bar-aggregator-agent.service`) will be managed. Renaming the file, the class, and the import simultaneously without a clear unit-migration strategy could leave stale systemd services behind.
- **HIGH — Import Resolution Blast Radius:** The plan assumes a direct rename of all imports. Implicit imports or `__init__.py` re-exports are likely to cause "ModuleNotFound" errors that might not be caught until integration time.
- **LOW — Dashboard/UI Fragility:** While preserving `agent_id` labels is correct, there is no mention of validating the UI components that might be hard-coded to expect specific service names.

### Suggestions
- Instead of `sed`, use an AST-based refactoring tool (e.g., `libcst` or `rope`) if available, or at least a dry-run `grep` script to audit potential matches before applying destructive changes.
- Add a specific task in Wave 4 to handle `systemd` unit file renames. Ensure `systemctl daemon-reload` is executed as part of the pipeline.
- Insert a "Pre-flight Audit" step after each Wave that prints all occurrences of the renamed symbol before applying the `sed` command.
- Add an integration test that specifically probes the systemd unit environment variables and metric labels to verify they remain consistent despite renames.

### Risk Assessment
**MEDIUM.** While the phased approach is architecturally sound, the sheer volume of string-based replacements poses a high risk of "hidden" failures. The operational exceptions (metrics/labels) are well-protected, but the systemd migration strategy needs more explicit detail.

---

## Codex Review

### Summary
The four plans are directionally sound and mostly respect the stated Phase 110 constraints: atomic branch, clean break, sequential waves, no compatibility aliases, and preservation of operational `agent_id` labels. The biggest risks are not the class renames themselves, but missed references across non-Python surfaces: systemd units, shell scripts, docs, dashboards, import strings, deployment manifests, CLI entrypoints, and tests that only import a subset of services. The plans would benefit from stronger grep gates, explicit distinction between service file renames and systemd unit renames, and a small integration/import smoke test that imports every renamed daemon module and validates systemd `ExecStart` targets exist.

### Plan 01 — Ring 0

**Strengths:** Correctly scoped to class identifiers only; preserves agent_id; right dependency order.

**Concerns:**
- **HIGH:** `git grep -nw "BaseAgent"` may miss references in non-`.py` files, type-check config, docs, systemd comments, scripts, or generated import strings.
- **HIGH:** `sed -i` across broad paths can accidentally touch strings/comments or miss multi-line/import alias cases.
- **MEDIUM:** Success criterion focused on `src/core/` does not fully cover `src/providers/base_provider_agent.py` (outside `src/core/`).

**Suggestions:**
- Add repo-wide identifier check (not path-limited): `git grep -nE '\b(BaseAgent|BaseWriterAgent|...)\b'`
- Add import smoke test for all renamed base classes.
- Explicitly check inheritance sites after rename.

### Plan 02 — Ring 1

**Strengths:** Correctly identifies `NarrativeComputeAgent` / `NarrativeGroupComputeAgent` collision risk. Deferral of `SignalContext` file move is reasonable.

**Concerns:**
- **HIGH:** `AIContext → SignalContext` has wide blast radius — runtime consumers may deserialize event payloads, fixtures, docs, or cached JSON with old names.
- **HIGH:** Word-boundary `sed` insufficient for import path changes, file moves, aliases, or serialized class names.
- **MEDIUM:** `Evaluator` is a very generic name; may collide conceptually with existing evaluators in `src/intelligence/`.
- **MEDIUM:** `AIContextCache` renaming should include review of cache key names, metric labels, logs — some may need preservation like `agent_id`.

**Suggestions:**
- Add old-name gates across the full repo.
- Search for serialized/config references separately: `git grep -nE 'AIContext|ai_context|context_cache'`
- Document whether metric/log/cache labels containing `ai_context` are renamed or preserved.

### Plan 03 — Ring 2

**Strengths:** Broad and specific daemon rename set; correctly preserves `_AGENT_ID_TO_UNIT` keys; notes `SwarmLedgerWriterAgent` inherits `BaseAgent` (not `BaseWriterAgent`); good grouping by service role.

**Concerns:**
- **HIGH:** Largest blast-radius wave. Renaming 34 daemon classes without file renames creates temporary mismatch across class names, module names, logs, docs, tests, and service metadata.
- **HIGH:** Broad sed replacements could accidentally alter `_AGENT_ID_TO_UNIT` keys, Prometheus labels, dashboard IDs, Kafka consumer group names, or systemd unit names.
- **HIGH:** Unit tests may not instantiate every daemon. Missed constructor references, CLI entrypoints, `if __name__ == "__main__"` paths could survive unit tests.
- **MEDIUM:** `FeatureValidationAnalyzer` in Wave 3 blurs the wave boundary (Ring 1 class inside a Ring 2 wave).

**Suggestions:**
- Add a protected grep list for operational identifiers before and after the wave.
- Use a mapping file or script-driven rename table rather than manual repeated `sed`.
- Add import smoke test that imports all service modules and resolves the expected class names.
- Add a test that `_AGENT_ID_TO_UNIT.keys()` is unchanged before/after, or snapshot the expected keys.
- Check dynamic references: `git grep -nE 'import_module|getattr|globals\(\)|entry_points|ExecStart|python .*services/'`

### Plan 04 — Wave 4

**Strengths:** Correctly separates class renames from file/module path renames; includes launcher import fixes; final CI gate and fast-forward merge appropriate.

**Concerns:**
- **HIGH:** "Systemd unit files" and "ExecStart paths" are not the same thing. The plan updates `ExecStart` but does not clearly state whether unit filenames are renamed, preserved, or intentionally deferred.
- **HIGH:** `git grep -rn "_agent.py" -- services/ returns 0` conflicts with launcher files explicitly preserved as `services/ml_training_agent.py` and `services/hmm_training_agent.py`. That acceptance criterion will fail.
- **HIGH:** File renames break imports in places unit tests may not cover: systemd, deployment scripts, Makefiles, Dockerfiles, cron jobs, README/CLAUDE docs.
- **MEDIUM:** Dashboard display strings preserved by decision but plan says "Dashboard fixes" — should explicitly say audit-only, not rename.

**Suggestions:**
- Clarify systemd policy: Are unit filenames renamed (`bar_aggregator_agent.service → bar_aggregator.service`)? Are only `ExecStart` paths changed?
- Fix acceptance criterion for launchers: `git grep -n '_agent.py' -- services/ ':!services/ml_training_agent.py' ':!services/hmm_training_agent.py'`
- Add systemd ExecStart validation: `awk '/ExecStart/ {print}' systemd/*.service` then verify every referenced Python file exists.
- Add service import smoke test for every renamed file.

### Risk Assessment
**HIGH.** File/module renames plus systemd/deployment references are where clean-break rename phases usually fail. With an authoritative rename map, stronger grep gates, import smoke tests, and explicit systemd naming decisions, the phase becomes much more controlled.

---

## Consensus Summary

### Agreed Strengths
- **Sequential wave order** (Ring 0 → Ring 1 → Ring 2 → files) is the correct dependency order; both reviewers confirm.
- **agent_id operational exception** is well-handled across all plans; both reviewers note it explicitly.
- **CI gates after each wave** provide the necessary feedback loop for a high-risk rename.
- **Deferral of SignalContext file-move** is pragmatic; both reviewers agree.
- **NarrativeComputeAgent / NarrativeGroupComputeAgent disambiguation** is correctly handled.

### Agreed Concerns (highest priority)

1. **Systemd unit filenames vs ExecStart paths (MEDIUM/HIGH)** — Both reviewers flag this. Plan 04 updates `ExecStart` but the fate of unit *filenames* (e.g., `indicagent-bar-aggregator-agent.service`) is not stated. Decision required before execution: rename unit files or preserve them.

2. **Wave 4 acceptance criterion conflict (HIGH)** — `git grep -rn "_agent.py" -- services/ returns 0` will fail because `services/ml_training_agent.py` and `services/hmm_training_agent.py` are deliberately preserved as launchers. Acceptance criterion must exclude these two files explicitly.

3. **sed blast radius on operational identifiers (HIGH)** — Both reviewers flag the risk of `sed -i` accidentally touching `_AGENT_ID_TO_UNIT` keys, Prometheus label strings, Kafka consumer group names, or other operational literals that should be preserved.

4. **Unit tests insufficient coverage (HIGH)** — Both reviewers agree: unit tests alone won't catch every missed daemon reference. A service import smoke test (import every renamed module, check class name resolves) is needed. Codex specifically recommends one.

5. **Non-Python surfaces (MEDIUM)** — Docs, Makefile, Dockerfile, deployment scripts, cron jobs, and `.claude/` hooks are not covered by the grep gates or CI. Both reviewers flag this.

### Divergent Views
- **Gemini** rates overall risk as MEDIUM; **Codex** rates Wave 3 and Wave 4 as HIGH. Codex's rating is more credible given the breadth of Ring 2 coverage — 34 daemons with file renames plus systemd. Weight Codex here.
- **Gemini** suggests AST-based refactoring tools; **Codex** accepts `sed` but requires stronger grep guardrails. Either is acceptable; Codex's approach is more pragmatic for this codebase.

### Recommended Actions Before Execution

1. **Clarify systemd policy** in Plan 04: state explicitly whether `indicagent-*-agent.service` filenames are renamed or only `ExecStart` is patched.
2. **Fix Wave 4 acceptance criterion** to exclude the two preserved launcher files from the `_agent.py` grep.
3. **Add import smoke tests** to Wave 3 and Wave 4: one script that imports every renamed service module and confirms the class name is correct.
4. **Snapshot `_AGENT_ID_TO_UNIT` keys** before Wave 3 begins; assert they are identical after Wave 3 completes.
5. **Broaden grep gates** to repo-wide (not path-limited) for the final verification in Plan 04.

To incorporate feedback:
`/gsd-plan-phase 110 --reviews`
