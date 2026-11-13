# Fetcher future hang diagnosis (archived)

Date: 2026-10-31, amended 2026-11-04. Archived 2026-11-13.
Outcome: executed (todo 538, completed at `c8c0b12b9`), then mooted. The IBKR fetcher lane it
diagnoses is on the step-7 deletion list and IBKR was removed entirely (owner ruling 2026-11-13).
The 186-26 rebuild rows its factory-reclassification finding rests on were discarded (migration
569), so that half is historical too.

Idea kept: in group-batched rebuilds, a worker sitting long in a healthy `result()` gap is normal;
kill decisions must distinguish a healthy group-batch gap from a real hang (py-spy stacks, not
wall-clock alone), or teardown kills live work.

Full text: git history, `af1d85e0a`.
