# Renaissance-Grade Standards

**Version:** 1.0
**Status:** current
**Last Updated:** 2026-06-28

## Philosophy

At Renaissance Technologies, discipline wasn't an afterthought — it was the core advantage. Jim Simons' team didn't succeed by finding better signals; they succeeded by applying mathematical rigor to everything: how they named concepts, how they evaluated evidence, how they kept their workspace.

A messy codebase is a messy mind. Accumulated junk files, bloated logs in git infrastructure, orphaned worktrees, stale cache — these are not "minor annoyances." They are institutional rot. They signal that precision is optional, that debris is acceptable, that someone else will clean up later.

"Later" never comes.

**Clean as you go** means:
- No accumulation of debris
- No shortcuts that become permanent
- No "temporary" files that outlive their context
- Git infrastructure stays pristine
- Standards are enforced, not suggested

The standard is not "clean when it hurts." The standard is **always clean**.

---

## The Renaissance Principles

| Concept | Principle | Anti-pattern |
|---------|-----------|--------------|
| **Clean As You Go** | No debris accumulation. Clean before context switch. | "I'll clean it later" (never happens) |
| **Evidence Over Opinion** | p < 0.05 or it doesn't exist. Shadow mode first. | Promoting unproven features to production |
| **Data Is Permanent** | Every labeled sample is kept forever. Storage is cheap; signal is irrecoverable. | Deleting "old" signal_events to save space |
| **Silent Failure Is Fatal** | Loud crashes > silent wrong answers. Hidden bias is a bug. | Swallowed exceptions, default values that hide errors |
| **Standards Are Enforced** | If it matters, it's automated. Pre-commit hooks, not guidelines. | "We should remember to do X" (no enforcement) |
| **Naming Precision = Thinking Precision** | One definition per term. Glossary is law. | Using "ticker" and "symbol" for same concept |
| **Separation of Concerns Is Law** | Compute ≠ Persistence ≠ Transport. Violations break the system. | Hot-path agents querying the database |
| **Trust Your Automation** | No human checkpoints on decisions context can resolve. | Mid-session confirmations on foreseeable choices |
| **Complexity Is Technical Debt** | Every unnecessary abstraction is paid forever. Remove before calcification. | Premature abstraction, over-engineering |
| **Git Infrastructure Is Sacred** | `.git/` never accumulates runtime state. Logs belong in `logs/`. | 1.9MB pre-commit.log in `.git/hooks/` |
| **Architectural Invariants Are Non-Negotiable** | The DAG topology is the architecture. Violating it means the system can't be reasoned about. | Agent-to-agent direct calls, hardcoded topic strings |
| **Renaissance Naming Convention** | Concept name derives all layer names (signal_tracker → SignalTracker). | Inconsistent naming across code/infra/db |

These are timeless. They apply whether we have I1-I7, v3.0 Feature Factory, or some future architecture.

---

## Standards by Domain

### Filesystem Hygiene

| Area | Standard | Anti-pattern |
|------|----------|--------------|
| Git infrastructure | Never accumulate runtime logs in `.git/` | 1.9MB `pre-commit.log` in `.git/hooks/` |
| Python cache | `__pycache__/`, `.pyc` removed before commit | Committing cache directories |
| Worktrees | Pruned after merge; no orphaned dirs | Empty `.worktrees/feat/` lingering for weeks |
| Logs | Rotate to `logs/`; apply retention policies | Log files growing without bound |
| Dependencies | No `*.egg-info`, no vendored libs in repo | Package build artifacts committed |

**Rule:** If it's generated, it's not committed. If it's temporary, it's removed before context switch.

### Code Hygiene

| Area | Standard | Anti-pattern |
|------|----------|--------------|
| Imports | No unused imports; no `from module import *` | Bloated import blocks |
| Dead code | Remove immediately upon deprecation | Commented-out blocks "just in case" |
| Tests | One test name per directory; no dupes | `test_signal()` in 5 files |
| Naming | Glossary-compliant; no synonyms | "ticker" and "symbol" in same codebase |
| Separation | Hot path never touches database | Pipeline agents querying DB |

**Rule:** If it's not used, delete it. If it's ambiguous, name it precisely.

### Data Hygiene

| Area | Standard | Rationale |
|------|----------|------------|
| Retention | No data deletion policies for signal-bearing tables | Every signal outcome is a labeled training sample |
| Storage | Compression over deletion | TimescaleDB compression handles cost |
| Evidence | Shadow mode before production | p < 0.05 gates prevent unproven promotion |
| Integrity | ECL boundary invariant enforced | Extrinsic emission gates discard training data permanently |

**Rule:** Storage is the cheapest thing we own. Signal is irrecoverable.

### Architecture Hygiene

| Area | Standard | Violation Impact |
|------|----------|------------------|
| DAG topology | Invariants are non-negotiable | System can no longer be reasoned about |
| Topics | All keys via `stream_keys.py` | Hardcoded strings create invisible coupling |
| Timestamps | All UTC, timezone-aware | Mixed timezones corrupt ordering |
| Communication | Topics only; no direct agent calls | Violates restart-from-offset guarantee |
| Scaling | systemd + Prometheus lag | No Kubernetes HPA; lag is the metric |

**Rule:** The DAG is the architecture. Violating it breaks guarantees.

---

## Standard Operating Procedures

### Daily (Automatic)
- Log rotation via systemd (`MaxRateInterval`, `max-size`, `max-file`)
- Python cache ignored by git (`.gitignore` enforces this)
- Pre-commit hooks enforce standards (ruff, black, glossary, duplicates)

### Weekly (Manual)
```bash
# 1. Prune git worktrees
git worktree prune

# 2. Check for accumulating artifacts
find . -type f -name "*.log" -size +10M -not -path "*/.git/*"
find . -type d -name "__pycache__" -not -path "*/.git/*"

# 3. Verify database health
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT schemaname, tablename,
       pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
LIMIT 10;
"
```

### Monthly (Manual)
```bash
# 1. Database maintenance
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "VACUUM ANALYZE;"

# 2. Check TimescaleDB compression
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
SELECT hypertable_name, compression_status,
       compressed_chunks, uncompressed_chunks
FROM timescaledb_information.hypertable_compression_stats;
"

# 3. Log archival
# Compress logs older than 30 days
find /home/bg/dev/indicagent/logs -name "*.log" -mtime +30 -exec gzip {} \;

# 4. Coverage/cleanup of test artifacts
rm -rf .pytest_cache .ruff_cache htmlcov .coverage
```

### Done-Coding SOP
From `docs/foundation/ship-or-sink-rules.md` — execute in order before considering session complete:

1. **Simplify** — run code-simplifier agent
2. **Review** — run `/review` (peer code review)
3. **Test** — `pytest tests/unit/ -q` must be green
4. **Commit** — on feature branch, no AI attribution
5. **Merge** — `git checkout main && git merge --ff-only <branch>`
6. **Clean** — `git branch -d <branch> && git worktree prune` ← Renaissance-grade
7. **Push** — `git push origin main`

No branches left behind. No worktrees accumulating. Clean as you ship.

---

## Anti-Patterns

These violate Renaissance-grade standards. Do not do them.

### The "I'll Clean It Later" Pattern
```bash
# BAD: Temporary file that becomes permanent
touch /tmp/quick_fix.json && mv /tmp/quick_fix.json data/

# GOOD: Name it properly, put it in the right place
mv /tmp/quick_fix.json data/ephemeral_fix_2026-06-28.json
```

### The "Git Infrastructure as Log Storage" Pattern
```bash
# BAD: Hook writes to .git/hooks/
LOG_FILE="${GIT_COMMON_DIR_PATH}/hooks/pre-commit.log"

# GOOD: Hook writes to repo logs/
LOG_FILE="${REPO_ROOT}/logs/pre-commit.log"
```

### The "Commented-Out Code" Pattern
```python
# BAD: Dead code "just in case"
# def old_signal_logic():
#     return deprecated_calculation()

# GOOD: Remove it. Git history has the old code.
def signal_logic():
    return current_calculation()
```

### The "Silent Failure" Pattern
```python
# BAD: Swallows errors, produces hidden wrong answers
try:
    result = risky_calculation()
except Exception:
    result = 0  # Silent default — no one knows calculation failed

# GOOD: Fail loudly
result = risky_calculation()  # Let exception propagate
```

### The "Premature Abstraction" Pattern
```python
# BAD: Abstracting before pattern is proven
class AbstractSignalProcessorFactory:
    def create_processor(self, type: str) -> SignalProcessor:
        # Only one implementation exists, but we're "ready for future"
        ...

# GOOD: One concrete class. Abstract when you have 2+ implementations.
class SignalProcessor:
    def process(self, data): ...
```

---

## Case Study: 2026-06-28 Cleanup

**Problem:** Project accumulated Renaissance-grade violations.

| Issue | Size | Violated Principle |
|-------|------|-------------------|
| `pre-commit.log` in `.git/hooks/` | 1.9MB | Git Infrastructure Is Sacred |
| Python cache scattered everywhere | ~872K | Clean As You Go |
| Orphaned worktree dirs | 2 empty | Clean As You Go |
| Old gz logs | many | Standards Are Enforced (no retention policy) |

**Resolution:**
1. **Moved pre-commit log** to `logs/pre-commit.log` (3.8KB retained)
2. **Fixed pre-commit hook** to log to correct location permanently
3. **Removed all Python cache** (`__pycache__`, `.pyc`, `.pyo`)
4. **Pruned orphaned worktrees** (`feat/`, `feature/`)
5. **Pruned old gz logs** (kept recent, removed ancient)
6. **Ran VACUUM ANALYZE** on database (38GB, fresh statistics)

**Result:** Zero debris. Git infrastructure pristine. Logs follow retention policy.

This cleanup is the first example of Renaissance-grade standards in action.

---

## Enforcement

### Pre-commit Hook
The `pre-commit` hook enforces standards automatically:
- Ruff lint (code quality)
- Black format (consistency)
- Duplicate test detection (test hygiene)
- Glossary enforcement (naming precision)
- Ring 0 boundary checks (separation of concerns)

### Git Ignore
`.gitignore` must exclude all generated artifacts:
```
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.ruff_cache/
.coverage
htmlcov/
*.log.1
*.log.[0-9].gz
```

### Review Checklist
Before any commit or merge:
- [ ] No cache directories committed
- [ ] No runtime logs in `.git/`
- [ ] No commented-out code
- [ ] No unused imports
- [ ] Glossary-compliant naming
- [ ] Database maintenance up-to-date
- [ ] Worktrees pruned

---

## References

- `docs/foundation/principles.md` — Core philosophy
- `docs/foundation/design-principles.md` — Architecture principles
- `docs/foundation/ship-or-sink-rules.md` — Done-Coding SOP
- `docs/foundation/naming-system.md` — Naming convention
- `docs/foundation/glossary.md` — Canonical vocabulary
- `docs/operations/` — Operational procedures

---

**Remember:** Renaissance-grade discipline is not a goal. It is a baseline. The alternative is institutional rot — and Renaissance didn't win by accumulating rot.
