# Performance & Throughput Investigation SOP

**Version:** 1.0 (portable)
**Status:** template — the methodology (§ The SOP) is fully portable; the case studies are illustrative and should be replaced with your own project's real incidents as they occur
**Source:** genericized from IndicAgent `docs/foundation/performance-investigation-sop.md` v1.0

## Why This Doc Exists

Two independent throughput investigations on the source project, two weeks apart, hit the **same shape of bug**: a batch write against a database hypertable measured 30-350x slower than a naive back-of-envelope estimate predicted, for a reason that was invisible until someone actually instrumented the running process instead of reasoning about it. Both times the fix, once found, was small. Both times finding it took longer than it should have because the investigation started with a guess-and-patch cycle (bigger batches, different SQL shape) instead of measurement.

**The pattern isn't "the database is slow."** It's: at scale, engineering instincts (and quick tests) consistently underestimate the cost of *mutating* data relative to the cost of *reading* it, because both instinct and quick tests are read-shaped. Any write-heavy batch job against a large partitioned/compressed table is this same operational category — not a one-off.

## The Failure Pattern, Named

1. A backfill/migration/batch job is written, reasoned about in terms of row count and an assumed per-row cost (usually inferred from a `SELECT`/`EXPLAIN` that never touches disk or the storage engine's own partition/chunk-routing layer).
2. It runs far slower than that estimate — sometimes silently (no error, no log line past startup, just... slow, or even zero rows written after hours of apparent work).
3. The instinct is to patch the shape of the query (bigger batches, bulk arrays, more parallelism) without first establishing *where* the time is actually going. This sometimes helps a little and never explains the real gap.
4. The real cause turns out to be a storage-engine-specific cost invisible to a plain `EXPLAIN` on a *read*: compressed-chunk decompression-on-write, or per-execution partition-routing overhead scaling with partition count. Both are structural properties of the storage abstraction that only show up under a real write, at real scale, against a real, populated table.

## The SOP

**Follow this order. Do not skip to step 4 because "it's probably X."**

### 1. Never trust a read-only test for a write-path question

A `SELECT`/`EXPLAIN` — even `EXPLAIN ANALYZE` — on a query shape that resembles your write does not measure your write. Benchmark the **exact operation**: same statement type (`UPDATE`, not `SELECT`), same table, same WHERE-clause shape, against real rows at realistic scale (hundreds to thousands, not five). A `SELECT` can be answered from a hot buffer or an index-only scan in a way an `UPDATE` never can (it must also touch the heap, WAL, and — for a partitioned/hypertable structure — the partition's own indexes and constraints).

### 2. Measure before theorizing — three tools, in this order

Before proposing *any* fix, run the actual write against real data and capture:

1. **Wait-event/active-query state** (e.g. Postgres `pg_stat_activity.wait_event_type` / `wait_event`), sampled during the run — `state='active'` with an *empty* wait event means the backend is on-CPU the whole time, not I/O, not lock wait; a populated I/O or Lock wait event means something else entirely. This one query eliminates entire categories of hypothesis in seconds.
2. **`iostat -x 1`** (or your platform's equivalent) for the underlying disk, sampled concurrently. Utilization near 0 while a write is measurably slow rules out disk I/O as the bottleneck outright — don't chase a disk-locality theory the data already refutes.
3. **`EXPLAIN (ANALYZE, BUFFERS)`** on the exact statement, on a single representative row. Cross-check its execution time against your measured per-row throughput — if EXPLAIN says sub-millisecond and you're measuring tens of milliseconds/row, the gap itself is the clue: something outside the query plan's own execution cost is eating the difference.

Guessing "it's probably disk" or "it's probably lock contention" without these three checks is exactly the anti-pattern this doc exists to stop. This maps directly onto a general systematic-debugging process (root cause investigation, multi-component evidence gathering) — use that process explicitly for any throughput investigation, not just correctness bugs.

### 3. Isolate with a single-variable test before writing a fix

Once you have a hypothesis, test it with the smallest possible change: same rows, same connection, same everything except the one variable you suspect. A good isolating test is literally "run the identical `UPDATE` against the parent table vs. against the one underlying partition/chunk those exact rows live in, same connection, same tuples" — a two-line change that can turn "probably partition-routing overhead" into "confirmed, N times slower." Don't ship a fix built on a plausible story; ship one built on a measured, isolated delta.

### 4. Storage-engine-specific suspects to check, in rough order of how often they tend to actually hit you

- **Partition/chunk count on the target table.** A high partition count (hundreds+) means per-execution partition-routing/exclusion overhead is a real cost for point UPDATEs/DELETEs, paid on every execution regardless of prepared-statement reuse across a client-side batch. A common fix: resolve the target partition once and write directly to it, rather than through the parent/virtual table.
- **Compression status on the target partitions/chunks.** Any compressed partition in your target range means every mutating row forces decompress-then-modify. Decompress the affected partitions first, or restructure the join to drive from the small known-target population rather than the full source table.
- **A correlated subquery (`EXISTS`, `IN`) driven from the large table instead of the small target set.** This silently degrades into a near-full-table scan; always drive from the smaller, known population.

### 5. Verify the fix live, end-to-end, with the real code path — not just a mocked unit test

A passing unit test with a fake connection proves the *logic* is right (correct SQL generated, correct grouping, correct fallback behavior). It says nothing about measured rows/sec. Both are required before a throughput fix is declared done: run the actual production function against real data on a partition/segment untouched by prior manual testing, and record the number.

### 6. Capture the finding as a durable gotcha, not just a closed ticket

A closed ticket is invisible to the next session that hits the same symptom. Add a one- or two-line entry to your gotchas reference doc. The goal is that the *third* occurrence of this pattern starts at step 4 of this SOP, not step 1.

## Case Studies (illustrative — replace with your own)

The source project's actual case studies involved a ~215M-row hypertable with compressed chunks (decompress-on-write forced by a correlated `EXISTS` driven from the wrong side of a join) and a 23M-row hypertable with 1000+ chunks (per-execution chunk-routing overhead measured at 358x — 29 rows/sec through the parent table vs. 10,423 rows/sec writing directly to the resolved chunk). Don't copy those numbers into your own docs; they're specific to that project's data. Replace this section with your own first two real investigations once they happen — that's what makes this doc a genuinely load-bearing reference instead of a plausible-sounding template.

## See Also

- [Renaissance Principles](principles.md) — "instrument everything," "empirical over theoretical"
- `superpowers:systematic-debugging` skill (or your own general debugging process) — the general process this SOP specializes for throughput/latency investigations specifically

---

## Adopting This in a New Project

1. Copy §"The Failure Pattern, Named" and §"The SOP" verbatim — fully portable, storage-engine-agnostic in spirit even though the concrete tool names (`iostat`, `pg_stat_activity`) are Postgres/Linux-flavored; swap for your own stack's equivalents.
2. Delete the illustrative case studies entirely rather than leaving IndicAgent's numbers in a new project's doc — a case study with someone else's numbers is worse than no case study (see [fast-cadence-collaboration.md](fast-cadence-collaboration.md) §5 on not writing results before they exist).
3. Write your own first case study the first time you actually run this SOP for real, and link it from a durable gotchas file the same way the source project does.
