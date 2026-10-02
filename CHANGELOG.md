# Changelog

## [1.0.1] - 2026-10-02

- Keep uv and uvx in the dependency-build stage only; final runtime uses the locked virtual environment directly.
- Use dynamically imported Psycopg with Debian-packaged libpq and retained native notices instead of the bundled binary wheel.
- Document actual single-replica stop-before-replace upgrades and reviewed source-build distribution boundaries.

## [1.0.0] - 2026-10-02

- Initial unpublished evaluation template: authenticated LlamaIndex approval workflow with DBOS runtime, persisted events, executor leasing and private PostgreSQL.
- Deterministic retrieval sample; SQL-idempotent ledger; offline draft restoration and local crash-recovery smoke.
