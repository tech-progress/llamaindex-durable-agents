# Changelog

## [1.0.3] - 2026-10-04

- Correct the marketplace dependency summary to the selected PostgreSQL17.11 image.
- Verify marketplace database-version consistency before freezing source; runtime dependencies and application behavior remain unchanged from1.0.2.
- Preserve immutable historical tags and require renewed exact-source cloud qualification.

## [1.0.2] - 2026-10-04

Source release and marketplace publication are distinct; exact-revision cloud qualification remains a prerequisite to promotion.

- Pin Compose and Railway IaC to PostgreSQL 17.11 Bookworm at the verified immutable image index.
- Keep API dependencies, Python/libpq pins, executor leasing and one-slot stop-before-replace behavior unchanged.
- Correct publication/source history and distinguish immutable v1.0.1 (`989e904`) evidence from this unqualified candidate.
- Assert the actual PostgreSQL version and private default-service boundary in local verification.

## [1.0.1] - 2026-10-02

- Keep uv and uvx in the dependency-build stage only; final runtime uses the locked virtual environment directly.
- Use dynamically imported Psycopg with Debian-packaged libpq and retained native notices instead of the bundled binary wheel.
- Document actual single-replica stop-before-replace upgrades and reviewed source-build distribution boundaries.

## [1.0.0] - 2026-10-02

- Initial unpublished evaluation template: authenticated LlamaIndex approval workflow with DBOS runtime, persisted events, executor leasing and private PostgreSQL.
- Deterministic retrieval sample; SQL-idempotent ledger; offline draft restoration and local crash-recovery smoke.
