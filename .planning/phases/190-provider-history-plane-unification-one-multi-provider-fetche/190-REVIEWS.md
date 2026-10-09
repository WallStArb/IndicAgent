---
phase: 190
reviewers: [antigravity]
reviewed_at: 2026-10-10T00:05:00Z
plans_reviewed: [190-01-PLAN.md, 190-02-PLAN.md, 190-03-PLAN.md, 190-04-PLAN.md, 190-05-PLAN.md, 190-06-PLAN.md, 190-07-PLAN.md]
---

# Cross-AI Plan Review — Phase 190

Reviewer availability note: configured default reviewers are codex + antigravity.
Codex is out of quota until 2026-10-15 (standing reviewer plan) and was not probed;
Claude skips itself as the runtime. Antigravity (AGY) carried the review.

## Antigravity Review

Verdict: **HIGH risk as planned.** Full review below (verbatim).

# Phase 190 Adversarial Implementation Plan Review

### Summary
Phase 190 sets out an ambitious and architecturally sound vision to unify historical OHLCV data capture across vendors under a single process with a two-tier ledger, frozen external identities, and leaf-level API isolation. However, the plan set suffers from a critical operational blind spot: it attempts to maintain a running 5-hour batch drain process (`indicagent-ibkr-history-fetcher.service`, running continuously under a 15-minute systemd timer) while applying breaking PostgreSQL DDL migrations, deleting live script files via `git mv`, and heavily refactoring imported queue code. Crucially, the plan author mistook git commit atomicity for running process memory updates—applying breaking migration 465 in Wave 1 will immediately cause the live in-memory fetcher (`ON CONFLICT (symbol, timeframe)`) to crash on PostgreSQL constraint mismatches during atomic chunk persistence. Furthermore, the plan overlooks the atomic write pathway (`scripts/infrastructure/backfill/_intraday_persist.py` and [`CoverageDelta`](file:///home/bg/dev/indicagent/services/ohlcv_coverage_writer.py#L74-L85)), bypasses the new [`HistoryProvider`](file:///home/bg/dev/indicagent/src/providers/base.py) protocol in the actual IBKR fetch path, and designs a parity gate that is easily confounded by continuous database mutations. Pausing the systemd timer during the implementation window and properly sequencing migration 465 to Wave 5 restores safety and simplicity.

---

### Strengths
- **Rigorous External Identity Freeze**: Freezing [`FETCHER_LOCK_NAME`](file:///home/bg/dev/indicagent/scripts/infrastructure/backfill/_fetcher_lock.py#L31), `JOB`, [`LOCK_HELD_MESSAGE`](file:///home/bg/dev/indicagent/scripts/infrastructure/backfill/_fetcher_lock.py#L34), and systemd unit names avoids breaking external dependents (such as [`bar_reconciliation_audit.py`](file:///home/bg/dev/indicagent/services/bar_reconciliation_audit.py#L736) and manual ops scripts) while allowing internal Python class and module names to be updated cleanly.
- **Architectural Boundary Enforcement**: Introducing [test_provider_leaf_boundary.py](file:///home/bg/dev/indicagent/tests/unit/test_provider_leaf_boundary.py) and [test_history_conformance.py](file:///home/bg/dev/indicagent/tests/unit/providers/test_history_conformance.py) creates clear, automated guardrails preventing Ring 2/scripts from coupling to concrete vendor leaves.
- **Two-Tier Ledger Conceptual Model**: Separating the stored-state canonical tier (`ohlcv_coverage`) from the planning source of record (`ohlcv_provider_head` and per-provider failure state) cleanly prevents one vendor's API outages from polluting another vendor's gap planning.
- **Single-Writer and Ring Discipline**: Preserves [`services/ohlcv_coverage_writer.py`](file:///home/bg/dev/indicagent/services/ohlcv_coverage_writer.py) as the sole writer under `SET LOCAL ROLE bar_derivation_writer` and respects Ring 1 rules for leaf modules.

---

### Concerns

- **[HIGH] [190-02] Premature execution of breaking migration 465 in Wave 1 crashes active in-flight batch fetchers.**
  In [190-02-PLAN.md](file:///home/bg/dev/indicagent/.planning/phases/190-provider-history-plane-unification-one-multi-provider-fetche/190-02-PLAN.md#L124), migration 465 is executed live in Task 3 to drop `PRIMARY KEY (symbol, timeframe)` and add `PRIMARY KEY (symbol, timeframe, provider)`. The running process (PID 4105824, which runs for up to 5 hours under `RuntimeMaxSec=18000`) has `services/ohlcv_coverage_writer.py` loaded in memory with `ON CONFLICT (symbol, timeframe)`. In PostgreSQL, `ON CONFLICT` requires an exact matching unique index; dropping the old PK causes all subsequent chunk persists in [`upsert_coverage`](file:///home/bg/dev/indicagent/services/ohlcv_coverage_writer.py#L108-L127) and outcome writes in [`record_fetch_outcome`](file:///home/bg/dev/indicagent/services/ohlcv_coverage_writer.py#L129-L135) to fail with `ERROR: 42P10: there is no unique or exclusion constraint matching the ON CONFLICT specification`. The transaction rolls back, fetched chunks are lost, and unhandled exceptions crash the loop. The assumption that *"writer commit and 465 apply must be seconds apart... drain may error for the seconds in between"* falsely assumes a running Python process reloads code on git commit.

- **[HIGH] [190-02 / 190-03] Migration 465 breaks `ohlcv_provider_head` writes and reads across the live system throughout Wave 1.**
  Migration 465 alters `ohlcv_provider_head` to `PRIMARY KEY (symbol, provider, timeframe)` with `timeframe NOT NULL`. However, [`_empty_history.py`](file:///home/bg/dev/indicagent/scripts/infrastructure/backfill/_empty_history.py#L224-L230) is not updated until Wave 2 ([190-03-PLAN.md](file:///home/bg/dev/indicagent/.planning/phases/190-provider-history-plane-unification-one-multi-provider-fetche/190-03-PLAN.md#L120-L134)). Any head lookup executed during Wave 1 calls `record_head()`, which executes `INSERT ... (symbol, provider, head_ts) ... ON CONFLICT (symbol, provider)`—failing with both a `NOT NULL` constraint violation on `timeframe` and an `ON CONFLICT` target mismatch. Furthermore, existing queue code in [`_fetch_queue.py`](file:///home/bg/dev/indicagent/scripts/infrastructure/backfill/_fetch_queue.py#L513-L516) executes `_HEADS_SQL` without a `timeframe` filter; after 465 seeds 1d and 5m rows, the dict comprehension `{r[0]: r[1] for r in rows}` will non-deterministically clobber 1d heads with 5m heads (or vice versa) depending on PostgreSQL disk scan order.

- **[HIGH] [190-05 / 190-06] Renaming `ibkr_history_fetcher.py` in Wave 4 orphans the live systemd unit before Wave 5 cutover.**
  In [190-05-PLAN.md](file:///home/bg/dev/indicagent/.planning/phases/190-provider-history-plane-unification-one-multi-provider-fetche/190-05-PLAN.md#L83-L90), `ibkr_history_fetcher.py` is moved to `ohlcv_history_fetcher.py` via `git mv`. Task 2 explicitly notes: *"Do NOT touch the root-owned live copies in /etc/systemd/system or daemon-reload here: the live install happens in the 190-06 cutover window."* If the running service finishes or restarts during Wave 4, systemd fires `/etc/systemd/system/indicagent-ibkr-history-fetcher.service`, which attempts to invoke the deleted `ibkr_history_fetcher.py` file, instantly failing with `203/EXEC (No such file or directory)`.

- **[HIGH] [190-02 / 190-04] Omission of `_intraday_persist.py` and `CoverageDelta` parameterization breaks multi-provider atomic writes.**
  Neither `190-02-PLAN.md` nor `190-04-PLAN.md` includes [`scripts/infrastructure/backfill/_intraday_persist.py`](file:///home/bg/dev/indicagent/scripts/infrastructure/backfill/_intraday_persist.py) in `files_modified`. In the live system, [`_write_bars_and_coverage`](file:///home/bg/dev/indicagent/scripts/infrastructure/backfill/_intraday_persist.py#L222-L228) calls `upsert_coverage(cur, coverage, ...)` where `coverage` is a [`CoverageDelta`](file:///home/bg/dev/indicagent/services/ohlcv_coverage_writer.py#L74-L85). Because `CoverageDelta` has no `provider` field, `upsert_coverage` will always fall back to the default `provider="ibkr"`. This means when a second vendor (e.g. Alpaca) persists bars through `persist_chunk_atomically`, its coverage will silently be recorded as `provider='ibkr'`, violating the two-tier ledger invariant.

- **[MEDIUM] [190-04 / 190-01] The registry-dispatch design does not deliver the "one-leaf-per-vendor" criterion.**
  In [190-04-PLAN.md](file:///home/bg/dev/indicagent/.planning/phases/190-provider-history-plane-unification-one-multi-provider-fetche/190-04-PLAN.md#L108-L111), `_PROVIDER_REGISTRY` entries require a `fetch: Callable[..., Awaitable[ItemOutcome]]` hook that *"owns that vendor's mechanics"*. For IBKR, this hook wraps 898 lines of [`_history_fetch_item.py`](file:///home/bg/dev/indicagent/scripts/infrastructure/backfill/_history_fetch_item.py) (retries, chunk pacing, atomic persistence, request observation logging). The newly introduced [`HistoryProvider.fetch_ohlcv`](file:///home/bg/dev/indicagent/src/providers/base.py) protocol returns only `HistoryPage(bars, next_window_start, verdict)` and is actually bypassed by the IBKR production fetch path. Adding a second vendor cannot cost "one leaf module" unless a generic, vendor-blind `ItemRunner` exists that drives pagination, persistence, and `ItemOutcome` creation for any `HistoryProvider`. Otherwise, every new vendor requires a custom 500+ line item-fetch hook in `scripts/infrastructure/backfill/` and custom SQL in `services/ohlcv_coverage_writer.py:_REBUILD_FILTERS`.

- **[MEDIUM] [190-06] The parity gate diff is invalidated by continuous background data mutations.**
  In [190-02-PLAN.md](file:///home/bg/dev/indicagent/.planning/phases/190-provider-history-plane-unification-one-multi-provider-fetche/190-02-PLAN.md#L91-L98), `parity-before.tsv` is captured in Wave 1. Over the hours/days required to execute Waves 1 through 5, the live 5m drain continues inserting bars and advancing coverage bounds. When [190-06-PLAN.md](file:///home/bg/dev/indicagent/.planning/phases/190-provider-history-plane-unification-one-multi-provider-fetche/190-06-PLAN.md#L68-L75) captures `parity-after.tsv` and diffs them, hundreds of symbols will have different `gap_days`, updated lanes, and altered queue ranks. Admitting delta class (2) (*"rows whose gap/lane moved because the drain landed bars"*) transforms the parity gate into an un-verifiable manual review. Furthermore, blindly executing `--reset-failures` to eliminate "quarantine drift" wipes out genuine vendor failures alongside refactor-induced errors.

- **[MEDIUM] [190-06] Cutover verification in Task 2 contains a false-positive race condition.**
  In [190-06-PLAN.md](file:///home/bg/dev/indicagent/.planning/phases/190-provider-history-plane-unification-one-multi-provider-fetche/190-06-PLAN.md#L83-L86), the automated verification checks:
  ```bash
  python -c "import json; d=json.load(open('logs/ibkr_history_fetcher_status.json')); print(d.get('status'))"
  ```
  In [`ohlcv_history_fetcher.py`](file:///home/bg/dev/indicagent/scripts/infrastructure/backfill/ibkr_history_fetcher.py#L1178-L1197), `_write_status()` is called only at the end of a run. When Task 2 starts the service, the new run is in-flight (or queued). The check immediately reads the status file written by the *previous* run hours earlier, printing `"success"` and falsely passing before the new unified fetcher has processed a single item.

- **[MEDIUM] [190-05] Renaming the fetcher script causes CI failure in `test_provider_leaf_boundary.py`.**
  [190-01-PLAN.md](file:///home/bg/dev/indicagent/.planning/phases/190-provider-history-plane-unification-one-multi-provider-fetche/190-01-PLAN.md#L128-L137) introduces [test_provider_leaf_boundary.py](file:///home/bg/dev/indicagent/tests/unit/test_provider_leaf_boundary.py) with an allow-list seeded with `scripts/infrastructure/backfill/ibkr_history_fetcher.py`. In [190-05-PLAN.md](file:///home/bg/dev/indicagent/.planning/phases/190-provider-history-plane-unification-one-multi-provider-fetche/190-05-PLAN.md), the file is renamed to `ohlcv_history_fetcher.py`, but `test_provider_leaf_boundary.py` is not in `files_modified`. The new file's imports of `IBKRProvider` will trigger an unlisted reference error and fail `.venv/bin/pytest tests/unit/ -q`.

- **[LOW] [190-06] Operational blockage from manual wait instructions.**
  [190-06-PLAN.md](file:///home/bg/dev/indicagent/.planning/phases/190-provider-history-plane-unification-one-multi-provider-fetche/190-06-PLAN.md#L81) instructs the executor to *"confirm no run is mid-item; if one is, wait for it to finish (runs are ~1.5 h; do not kill mid-chunk)"*. Because `RuntimeMaxSec=18000` allows runs to last up to 5 hours, an automated agent or operator cannot wait synchronously. The database writes in `persist_chunk_atomically` are fully transactional per-chunk; pausing via `systemctl stop` is already safe and supported by the kill-and-resume procedure in [gotchas.md](file:///home/bg/dev/indicagent/docs/reference/gotchas.md).

- **[LOW] [190-03] Over-engineered candidate revision gating prior to multi-vendor arrival.**
  [190-03-PLAN.md](file:///home/bg/dev/indicagent/.planning/phases/190-provider-history-plane-unification-one-multi-provider-fetche/190-03-PLAN.md#L142-L156) introduces a `bar_source_policy` query into `_fetch_queue.py` that implements revision-span gating. In production today, `bar_source_policy` has no rows and IBKR is the only active source. Implementing revision gating rules before the second provider arrives adds unverified code paths that cannot be tested against production data.

---

### Suggestions
- **Stop the fetcher timer during the refactor window**: Do not attempt zero-downtime hot-reloading while mutating queue structures and schema keys. Stop `indicagent-ibkr-history-fetcher.timer` and `.service` at the start of Wave 1 (or Wave 2). Resuming from coverage is already proven crash-safe and avoids the fragile "dual-shape" legacy compatibility layer in `_fetch_queue.py`.
- **Restore the 464/465 migration sequencing intended by ROADMAP.md**:
  - Apply **464** in Wave 1 (strictly additive: add nullable `provider` and `timeframe` columns).
  - Apply **465** in Wave 5 during the cutover stop window (swap PKs, enforce `NOT NULL`, seed per-TF floors).
- **Include `_intraday_persist.py` and `CoverageDelta` in the refactor**:
  Add `provider: str = "ibkr"` to [`CoverageDelta`](file:///home/bg/dev/indicagent/services/ohlcv_coverage_writer.py#L74-L85), thread it through [`_write_bars_and_coverage`](file:///home/bg/dev/indicagent/scripts/infrastructure/backfill/_intraday_persist.py#L222-L228), and update `test_intraday_persist.py`.
- **Provide a shim wrapper during the rename window**:
  In 190-05, keep `scripts/infrastructure/backfill/ibkr_history_fetcher.py` as a lightweight compatibility stub pointing to `ohlcv_history_fetcher.py` until the live `/etc/systemd/system/` unit is installed in 190-06.
- **Fix the cutover verification check**:
  In 190-06 Task 2, verify post-cutover execution by checking that `started_at` in `logs/ibkr_history_fetcher_status.json` is greater than the cutover timestamp (or delete the status file before triggering the unit), rather than simply checking `status == "success"`.
- **Formalize the `ItemRunner` abstraction**:
  To truly deliver "adding a vendor costs one leaf module", build a provider-blind `fetch_history_item()` helper in `ohlcv_history_fetcher.py` that drives any [`HistoryProvider`](file:///home/bg/dev/indicagent/src/providers/base.py) protocol instance through its window pages and calls `persist_chunk_atomically`.

---

### Risk Assessment
**Overall Risk: HIGH**

**Justification:**
Executing breaking schema changes (migration 465) and script renames on disk while a background batch process continues to run for hours in production will trigger active PostgreSQL constraint errors, transaction aborts, and potential unit execution failures (`203/EXEC`). Furthermore, the omission of `_intraday_persist.py` leaves the atomic persistence pipeline hardcoded to IBKR, undermining the multi-provider goal. These risks can be downgraded to **LOW** by stopping the systemd timer during the refactor, deferring migration 465 to the cutover window in Wave 5, and parameterizing `CoverageDelta`.

---

## Orchestrator Adjudication (verified against plan text and live code, 2026-10-10)

### Accepted (fed to revision)

1. **[HIGH, confirmed] 465 must not apply in wave 1.** The running drain keeps the old
   `ON CONFLICT (symbol, timeframe)` in memory until it restarts; dropping that PK makes
   every chunk persist fail with 42P10 and rolls back in-flight chunks. Fix: waves 1-4
   write code and migrations but apply only 464; migration 465 applies in the wave-5
   cutover window with the fetcher stopped, in the same breath as the writer-conflict-target
   flip. Every changed module (coverage writer, `_empty_history.py` head writes) keeps
   old-shape writes until wave 5; contract tests exercise the 465 schema via
   transaction-rollback fixtures so tests do not depend on live apply timing.
2. **[HIGH, confirmed] `CoverageDelta` / `_intraday_persist.py` provider threading.**
   Without it, a second vendor's coverage rows silently record as `provider='ibkr'`,
   violating the two-tier ledger invariant. Added to 190-02's files and tasks.
3. **[HIGH, confirmed] wave-4 rename orphans the live unit.** The timer fires every 15
   minutes and the drain restarts continuously; the 190-05-to-190-06 window is not
   minutes. Fix: 190-05 keeps `ibkr_history_fetcher.py` as a thin wrapper importing the
   new module until 190-06 installs the unit, then deletes the wrapper. 190-05 also
   updates the `test_provider_leaf_boundary.py` allow-list entry (CI would fail otherwise).
4. **[MEDIUM, confirmed] parity gate redesigned to back-to-back comparison.** At 190-06,
   run the OLD fetcher's dry-run from a temp git worktree at the pre-phase commit and the
   NEW fetcher's dry-run minutes apart against the same DB state; diff those two.
   Wave-1's parity-before.tsv is demoted to a sanity reference. The ambiguous "rows that
   moved because the drain landed bars" delta class is deleted. `--reset-failures`
   leaves the parity path (back-to-back runs share quarantine state) and stays only as
   an idempotent cutover step.
5. **[MEDIUM, confirmed] cutover status check is a false-positive race.** Verify
   `started_at` in the status file is greater than the cutover timestamp (or delete the
   status file before triggering the unit), not `status == "success"` alone.

### Rejected or adapted (with reasons)

6. **Stop-the-timer-during-refactor (AGY suggestion): rejected.** The dual-shape
   compatibility contract (checker blocker B2 fix, already verified in the plans) keeps
   every commit boundary fetchable without an operational stall. With alerting
   deliberately unwired (UAT), an execution crash that leaves the timer stopped is the
   worse failure mode: silent ingestion stall versus a compat layer that tests prove
   correct at every boundary. Moving 465 out of waves 1-4 removes the sharpest risk the
   suggestion targeted.
7. **Generic ItemRunner abstraction (MEDIUM): adapted, deferred.** The entry.fetch hook
   (checker B3 fix) wraps the proven 189 mechanics and is the lower-risk cut with one
   real vendor. Honest cost accounting: a new vendor contributes a leaf module plus a
   ProviderEntry registration plus an optional rebuild filter, not literally one file.
   190-07's downstream note must state exactly that; a vendor-blind ItemRunner is a
   candidate refactor when the second vendor arrives, not before (YAGNI discipline).
8. **bar_source_policy gating before a second vendor exists (LOW): rejected.** The read
   gate is a locked design decision, is a no-op with an empty policy table, and ships
   with tests; deleting it would re-open a settled decision.

## Consensus Summary

### Agreed Strengths
- External-identity freeze is rigorous and correctly scoped (both reviewers).
- Two-tier ledger cleanly separates vendor outage domains (both reviewers).
- Boundary and conformance tests enforce the leaf criterion mechanically (both).

### Agreed Concerns (highest priority)
- Migration 465 timing vs the live drain (AGY HIGH; orchestrator-confirmed, accepted).
- Cutover-window operational hazards: orphaned unit, status-file race (both flagged;
  checker's info note 2 was the same finding, severity now corrected upward).

### Divergent Views
- Zero-downtime compat layer vs stop-the-timer simplicity: resolved in favor of the
  compat layer with reasons above; revisit if wave execution spans multiple sessions.
