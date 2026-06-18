# Phase 134 — Signal Classification Type Safety: Verification Report

Generated: 2026-06-18

This document covers all three plans of Phase 134:
- Plan 01: SignalOutcome persistence (outcome column + 9-class taxonomy)
- Plan 02: EntryType enum + DB CHECK constraint
- Plan 03: PG ENUM types + column casts + hypertable maintenance strategy

---

## 1. Pre-migration Audit (Task 1 — Plan 03)

### trade_executions.outcome distribution

| outcome | count |
|---------|-------|
| ttl_expired_behind | 444,296 |
| stopped_in_trade | 184,226 |
| ttl_expired_ahead | 147,804 |
| stopped_at_entry | 122,606 |
| target_1 | 56,527 |
| never_activated | 308 |
| **NULL** | **0** |

NULL count: 0 (PASS — Plans 01+02 backfill complete)
Out-of-set count: 0 (PASS — all values in 9-member SignalOutcome set)

### trade_frames.entry_type distribution

| entry_type | count |
|------------|-------|
| at_close | 757,917 |

Out-of-set count: 0 (PASS)

### signal_events.status distribution

| status | count |
|--------|-------|
| expired | 700,619 |
| pending | 52,609 |
| active | 2,584 |
| regime_suppressed | 0 (valid member, no rows yet) |

Out-of-set count: 0 (PASS)

### trade_executions.exit_reason distribution

| exit_reason | count |
|-------------|-------|
| ttl_expired | 393,825 |
| stop_loss | 306,832 |
| ttl_expired_ahead | 134,186 |
| ttl_expired_behind | 64,397 |
| target_1 | 56,527 |
| chandelier_stop | 0 (live code path, signal regime) |
| condition_expired | 0 (live code path, signal regime) |

chandelier_stop: 0 rows — live code path in lifecycle_tracker.py:347, not dead code.
condition_expired: 0 rows — live code path in lifecycle_tracker.py:372, not dead code.
Both are explicitly listed in chk_te_exit_reason.

### Hypertable Confirmation

`SELECT hypertable_name FROM timescaledb_information.hypertables WHERE hypertable_name='signal_events'` = 1 row (PASS)

### signal_events Writer Services

Services that write to signal_events (from _AGENT_ID_TO_UNIT + repository analysis):
- `indicagent-signal-writer` — writes signal_events + trade_frames on new signal fires
- `indicagent-signal-tracker-compute` — updates signal_events.status
- `indicagent-lifecycle-writer` — writes lifecycle transitions
- `indicagent-intelligence-pipeline` — upstream producer (DB-ignorant per DAG invariant)

Both `indicagent-signal-writer`, `indicagent-signal-tracker-compute`, and `indicagent-lifecycle-writer`
were already inactive at migration time. Only `indicagent-intelligence-pipeline` required stopping.

---

## 2. Hypertable Maintenance Window (Task 2 — Plan 03)

**Window start:** 2026-06-18T14:59:17Z

### Services stopped

```
echo '!123Angelina' | /usr/bin/sudo.ws -S systemctl stop indicagent-intelligence-pipeline
```

Confirmed inactive:
- indicagent-intelligence-pipeline: inactive
- indicagent-signal-writer: inactive (already)
- indicagent-lifecycle-writer: inactive (already)
- indicagent-signal-tracker-compute: inactive (already)

### Decompression

103 compressed chunks decompressed:
```sql
SELECT decompress_chunk(format('%I.%I', chunk_schema, chunk_name)::regclass, if_compressed => true)
FROM timescaledb_information.chunks WHERE hypertable_name = 'signal_events' AND is_compressed = true;
```
Result: 103 chunks decompressed in ~1 second.

### status Column Type Conversion

Additional prerequisites resolved during execution (not in migration file initially):
1. signal_ledger view references signal_events.status — dropped before cast, recreated after.
2. Column DEFAULT ('pending'::text) incompatible with ENUM cast — dropped before, reset as
   'pending'::signal_status_type after.

```sql
BEGIN;
DROP VIEW IF EXISTS signal_ledger;
ALTER TABLE signal_events ALTER COLUMN status DROP DEFAULT;
ALTER TABLE signal_events ALTER COLUMN status TYPE signal_status_type USING status::signal_status_type;
ALTER TABLE signal_events ALTER COLUMN status SET DEFAULT 'pending'::signal_status_type;
CREATE VIEW signal_ledger AS ... (full definition preserved);
COMMIT;
```

Result: ALTER TABLE succeeded, COMMIT confirmed.

### Recompression

```sql
SELECT compress_chunk(format('%I.%I', chunk_schema, chunk_name)::regclass, if_not_compressed => true)
FROM timescaledb_information.chunks WHERE hypertable_name = 'signal_events'
  AND is_compressed = false AND range_end < NOW() - INTERVAL '1 week';
```
Result: 103 chunks recompressed in ~42 seconds.

### Service Restart

```
echo '!123Angelina' | /usr/bin/sudo.ws -S systemctl start indicagent-intelligence-pipeline
```
Confirmed: indicagent-intelligence-pipeline: active (running)

---

## 3. PG ENUM Type Inventory

### Types Created (migration 151)

```sql
SELECT typname, (SELECT COUNT(*) FROM pg_enum WHERE enumtypid=t.oid) as member_count
FROM pg_type t WHERE typname IN ('signal_outcome_type','entry_type_type','signal_status_type')
ORDER BY typname;
```

| typname | member_count |
|---------|-------------|
| entry_type_type | 5 |
| signal_outcome_type | 9 |
| signal_status_type | 4 |

(3 rows — PASS)

### signal_outcome_type members (9)

never_activated, stopped_at_entry, stopped_in_trade, target_1, target_1_2, target_full,
ttl_expired_ahead, ttl_expired_behind, condition_expired

### Column UDT Names After Migration

```sql
SELECT table_name, column_name, data_type, udt_name
FROM information_schema.columns
WHERE table_name IN ('trade_executions','trade_frames','signal_events')
  AND column_name IN ('outcome','entry_type','status')
ORDER BY table_name, column_name;
```

| table_name | column_name | udt_name |
|------------|-------------|----------|
| signal_events | status | signal_status_type |
| trade_executions | outcome | signal_outcome_type |
| trade_frames | entry_type | entry_type_type |

(PASS — all 3 columns typed to their ENUM types)

---

## 4. Type Enforcement Proof (Round-trip Insert Results)

Tests in `tests/unit/intelligence/trading/test_pg_enum_enforcement.py`.
All tests run against indicagent DB (not indicagent_test) to exercise migration 151.

### test_roundtrip_outcome_enum — PASS

- All 9 SignalOutcome values inserted and rolled back successfully.
- Explicit regression guards: condition_expired (PASS), stopped_in_trade (PASS).
- Invalid value 'bogus_outcome' → PG error 22P02 (PASS).

### test_roundtrip_entry_type_enum — PASS

- All 5 EntryType values inserted and rolled back successfully.
- Invalid value 'at_market' → PG error 22P02 (PASS).

### test_roundtrip_status_enum — PASS

- All 4 SignalStatus values inserted and rolled back successfully.
- Invalid value 'cancelled' → PG error 22P02 (PASS).

All round-trip tests confirmed: valid values accepted, invalid values rejected with 22P02.

---

## 5. exit_reason CHECK Verification

```sql
SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname='chk_te_exit_reason';
```

Result:
```
CHECK ((exit_reason = ANY (ARRAY['stop_loss'::text, 'chandelier_stop'::text,
'condition_expired'::text, 'ttl_expired'::text, 'ttl_expired_ahead'::text,
'ttl_expired_behind'::text, 'target_1'::text, 'target_1_2'::text, 'target_full'::text])))
```

chandelier_stop: present (PASS)
condition_expired: present (PASS)

exit_reason is retained as TEXT (not ENUM) — it is a coarser operational code,
not a taxonomy label. CHECK constraint provides sufficient enforcement.

---

## 6. EntryType Migration (Plans 02 + 03)

### Bare String Literal Grep

```
grep -rn '"at_close"\|"at_pullback"\|"at_limit"\|"at_reclaim"\|"zone_proximal"' src/ --include="*.py" | grep -v signal_outcome.py
```
Result: 0 lines (PASS)

### Migration 150 Constraint

```sql
SELECT conname FROM pg_constraint WHERE conrelid='trade_frames'::regclass AND conname='chk_tf_entry_type';
```
Result: 1 row (PASS) — upgraded to entry_type_type ENUM in migration 151.

---

## 7. SignalOutcome Persistence (Plan 01)

### NULL outcome count

```sql
SELECT COUNT(*) FROM trade_executions WHERE outcome IS NULL;
```
Result: 0 (PASS)

### Both Write Paths Confirmed

- lifecycle_replay._flush_writes: zone exit + market track + _reconcile_outcomes all write outcome
- signal_events_repository.record_execution: outcome param wired, ENUM normalization via hasattr('value')

Verified via GBPUSD 1m replay 2026-06-17+: 0 NULL outcomes.

---

## 8. Live-but-zero-row Values

### chandelier_stop

- DB rows: 0 (signal regime has not triggered this path)
- Code location: lifecycle_tracker.py:347
- Classification: live code path, NOT dead code
- outcome mapping: SignalOutcome.STOPPED_IN_TRADE
- Status: documented with comment "live code path; outcome -> stopped_in_trade. 0 rows in current corpus (signal regime), not dead code."

### condition_expired

- DB rows: 0 (signal regime has not triggered this path)
- Code location: lifecycle_tracker.py:372
- Classification: live code path, NOT dead code
- outcome mapping: SignalOutcome.CONDITION_EXPIRED (9th member)
- Status: documented with comment "live code path; outcome -> condition_expired (9th SignalOutcome). 0 rows in current corpus (signal regime), not dead code."

Verification:
```
grep -n "live code path" src/intelligence/trading/lifecycle_tracker.py
```
Result: 2 lines (PASS)

```
grep -in "dead code" src/intelligence/trading/lifecycle_tracker.py | grep -v "not dead code"
```
Result: 0 lines (PASS — no incorrect "dead code" labels)

---

## 9. Unit Suite Status

Full suite from main repo (4856 passing tests include Plan 01+02 tests):
```
4856 passed, 37 skipped, 364 warnings in 31.74s
```

Plan 03 tests (test_pg_enum_enforcement.py — 11 tests):
```
11 passed in 0.24s
```

Tests breakdown:
- TestSignalOutcomeEnumExhaustive: 3 tests (exhaustiveness + condition_expired + str_subclass)
- TestEntryTypeEnumExhaustive: 2 tests (exhaustiveness + str_subclass)
- TestSignalStatusEnumExhaustive: 2 tests (exhaustiveness + str_subclass)
- TestRoundtripOutcomeEnum: 2 tests (round-trip all 9 values + sanity count)
- TestRoundtripEntryTypeEnum: 1 test (round-trip all 5 values)
- TestRoundtripStatusEnum: 1 test (round-trip all 4 values)

All green. Phase committed and pushed.
