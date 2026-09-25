"""Research DAG (docs/plans/2026-09-25-alpha-research-architecture.md): S0 snapshot ->
panel -> signal -> evaluate. Pure compute over immutable, content-hashed snapshots; only
snapshot.py touches the database, read-only, and nothing here writes production tables."""
